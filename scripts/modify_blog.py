#!/usr/bin/env python3
"""
modify_blog.py — Weekly blog refresher for MeeeShop
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
For every published article (oldest first, up to --limit per run):
  1. Detect out-of-stock product links in the body HTML
  2. Replace each with the best in-stock alternative (same product_type)
  3. If the post has NO product cards at all, inject a related product
  4. Rewrite the article body with fresh, Discover-ready HTML (same URL handle / title kept)
  5. Re-set SEO metafields (title_tag + description_tag) and featured-image ALT text
  6. Publish the update (patch, NOT delete+recreate → handle/URL unchanged)

Google Discover requirements preserved:
  - Featured image ≥ 1200px (CDN transform applied where possible)
  - EEAT voice, high-intent format, LSI keywords embedded
  - SEO title 50-60 chars, meta desc 140-155 chars
  - All product links include UTM params

AI: Gemini 2.0 Flash → Groq Llama-3.3-70B → OpenRouter (multi-model free tier)

Usage:
  python scripts/modify_blog.py              # process 5 articles (default)
  python scripts/modify_blog.py --limit 10   # process up to 10
  python scripts/modify_blog.py --dry-run    # print plan, no Shopify writes
  python scripts/modify_blog.py --article-id 123456  # update one specific article
  python scripts/modify_blog.py --force      # update ALL articles
  python scripts/modify_blog.py --force --batch-size 20 --batch-index 0  # batch 0 of N
"""

import os, sys, re, time, random, json, argparse
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import requests

# ── resolve project root and import local modules ─────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
# Assuming local utility scripts (ai_client, secrets_manager) are in the same directory
import ai_client

# ── env / credentials ─────────────────────────────────────────────────────────
from secrets_manager import inject_to_env, get_secret
inject_to_env()

SHOP      = get_secret("SHOPIFY_STORE")
TOKEN     = get_secret("SHOPIFY_ACCESS_TOKEN")
API_VER   = "2024-10"
BASE      = f"https://{SHOP}/admin/api/{API_VER}"
HEADERS   = {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}
STORE_URL = get_secret("STORE_BASE_URL")

if not TOKEN:
    sys.exit("ERROR: SHOPIFY_ACCESS_TOKEN not set.")

YEAR  = datetime.now().year
MONTH = datetime.now().strftime("%B %Y")

# ── Shopify helpers ───────────────────────────────────────────────────────────
def _req(method: str, url: str, **kw):
    for attempt in range(5):
        try:
            r = getattr(requests, method)(url, headers=HEADERS, timeout=30, **kw)
            if r.status_code == 429:
                wait = int(float(r.headers.get("Retry-After", 4)))
                print(f"    [rate-limit] sleeping {wait}s…")
                time.sleep(wait)
                continue
            return r
        except requests.exceptions.ConnectionError:
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"{method.upper()} {url} failed after 5 attempts")


# ── Product fetching ──────────────────────────────────────────────────────────
def fetch_all_products() -> list:
    """Fetch all products with inventory info (up to 250 per page)."""
    products, page_info = [], None
    while True:
        params = {
            "limit": 250,
            "fields": "id,title,handle,product_type,variants,images,tags,body_html",
        }
        if page_info:
            params["page_info"] = page_info
        r = _req("get", f"{BASE}/products.json", params=params)
        r.raise_for_status()
        batch = r.json().get("products", [])
        products.extend(batch)
        link = r.headers.get("Link", "")
        m = re.search(r'<[^>]*page_info=([^&>]+)[^>]*>;\s*rel="next"', link)
        if m:
            page_info = m.group(1)
        else:
            break
    return products


def is_in_stock(product: dict) -> bool:
    """Return True if any variant has inventory > 0 OR inventory policy is 'continue'."""
    for v in product.get("variants", []):
        if v.get("inventory_policy") == "continue":
            return True
        qty = v.get("inventory_quantity", 0)
        if qty is None or qty > 0:
            return True
    return False


def split_products(products: list) -> tuple[list, list]:
    """Return (in_stock, out_of_stock) lists."""
    ins, outs = [], []
    for p in products:
        (ins if is_in_stock(p) else outs).append(p)
    return ins, outs


def find_best_replacement(out_product: dict, in_stock: list) -> dict | None:
    """Find best in-stock replacement: same product_type first (must have image), then any with image."""
    ptype = (out_product.get("product_type") or "").lower()
    # Same type with image
    same = [p for p in in_stock if (p.get("product_type") or "").lower() == ptype and p.get("images")]
    if same:
        return random.choice(same)
    # Any in-stock with image
    with_img = [p for p in in_stock if p.get("images")]
    return random.choice(with_img) if with_img else None


# ── Blog / article fetching ───────────────────────────────────────────────────
def fetch_all_blogs() -> list:
    r = _req("get", f"{BASE}/blogs.json")
    r.raise_for_status()
    return r.json().get("blogs", [])


def fetch_articles_for_blog(blog_id: int, limit: int = 50) -> list:
    """Fetch articles for one blog, oldest first."""
    articles = []
    page_info = None
    while len(articles) < limit:
        params = {
            "limit": min(50, limit - len(articles)),
            "fields": "id,title,handle,body_html,image,tags,summary_html,published_at",
        }
        if page_info:
            params["page_info"] = page_info
        r = _req("get", f"{BASE}/blogs/{blog_id}/articles.json", params=params)
        r.raise_for_status()
        batch = r.json().get("articles", [])
        if not batch:
            break
        articles.extend(batch)
        link = r.headers.get("Link", "")
        m = re.search(r'<[^>]*page_info=([^&>]+)[^>]*>;\s*rel="next"', link)
        if m:
            page_info = m.group(1)
        else:
            break
    return articles


def fetch_article_metafields(blog_id: int, article_id: int) -> list:
    r = _req("get", f"{BASE}/blogs/{blog_id}/articles/{article_id}/metafields.json")
    if r.ok:
        return r.json().get("metafields", [])
    return []


# ── Product link detection ────────────────────────────────────────────────────
PRODUCT_LINK_RE = re.compile(
    r'href=["\']https?://(?:us\.)?meeeshop\.com/products/([a-z0-9_-]+)[^"\']*["\']',
    re.IGNORECASE,
)

def extract_product_handles(html: str) -> set[str]:
    return set(PRODUCT_LINK_RE.findall(html or ""))


def has_product_card(html: str) -> bool:
    """Detect our styled product card div or any product link in the body."""
    if not html:
        return False
    return bool(re.search(r'us\.meeeshop\.com/products/', html, re.IGNORECASE))


# ── Image helpers (same as blog_daily.py) ────────────────────────────────────
def product_img_url(product: dict) -> str | None:
    imgs = product.get("images", [])
    return imgs[0]["src"] if imgs else None


def make_featured_image_url(product: dict) -> str:
    imgs = product.get("images", [])
    if not imgs:
        raise ValueError(f"Product '{product.get('title')}' has no images. Direct CDN images are required for Discover.")
    src = imgs[0]["src"]
    return re.sub(r'\.(jpg|jpeg|png|webp)(\?.*)?$',
                  r'_1200x630_crop_center.\1', src, flags=re.IGNORECASE)


# ── Product card HTML (same style as blog_daily.py) ──────────────────────────
def make_product_card(product: dict, keyword: str = "",
                      label: str = "IN STOCK NOW — FEATURED PICK") -> str:
    import html
    raw_title = product["title"]
    escaped_title = html.escape(raw_title)
    price  = product["variants"][0]["price"] if product.get("variants") else "0"
    handle = product.get("handle", "")
    ptype  = (product.get("product_type") or "women's fashion").lower()
    url    = f"{STORE_URL}/products/{handle}?utm_source=blog&utm_medium=featured_card&utm_campaign=meeeshop_refresh"
    img    = product_img_url(product)
    alt    = f"{raw_title} — {keyword or ptype} for women at MeeeShop"

    alt_clean = alt.replace('"', "'")

    img_html = (
        f'<a href="{url}"><img src="{img}" alt="{alt_clean}" '
        f'style="width:220px;height:220px;object-fit:cover;border-radius:10px;flex-shrink:0;" loading="lazy" /></a>'
        if img else ""
    )
    return f"""
<div style="background:#f8f6f3;border-radius:14px;padding:24px 28px;margin:32px 0;
            display:flex;flex-wrap:wrap;gap:24px;align-items:center;
            border:1px solid #eee;font-family:sans-serif;">
  {img_html}
  <div style="flex:1;min-width:200px;">
    <p style="font-size:11px;color:#999;margin:0 0 6px;text-transform:uppercase;letter-spacing:1.5px;font-weight:600;">{label}</p>
    <h3 style="font-size:18px;font-weight:700;margin:0 0 8px;color:#1a1a1a;line-height:1.3;">{escaped_title}</h3>
    <p style="font-size:26px;font-weight:800;color:#1a1a1a;margin:0 0 6px;">${price}</p>
    <p style="font-size:12px;color:#777;margin:0 0 18px;">
      Free US shipping on orders $50+ &nbsp;&bull;&nbsp; 7-day easy returns &nbsp;&bull;&nbsp; Sizes XS–3X
    </p>
    <a href="{url}"
       style="background:#1a1a1a;color:#ffffff;padding:13px 30px;text-decoration:none;
              border-radius:8px;font-size:14px;font-weight:700;letter-spacing:0.5px;
              display:inline-block;">
      Shop Now &rarr;
    </a>
  </div>
</div>
"""


def make_related_products_section(products: list, exclude_handle: str,
                                  keyword: str = "") -> str:
    import html
    pool = [p for p in products if p.get("handle") != exclude_handle and is_in_stock(p)]
    if not pool:
        pool = [p for p in products if p.get("handle") != exclude_handle]
    picks = random.sample(pool, min(3, len(pool)))

    cards_html = ""
    for p in picks:
        raw_title  = p["title"]
        escaped_title = html.escape(raw_title)
        price  = p["variants"][0]["price"] if p.get("variants") else "0"
        handle = p.get("handle", "")
        ptype  = (p.get("product_type") or "women's fashion").lower()
        url    = f"{STORE_URL}/products/{handle}?utm_source=blog&utm_medium=related_card&utm_campaign=meeeshop_refresh"
        img    = product_img_url(p)
        alt    = f"{raw_title} — shop {keyword or ptype} at MeeeShop"
        
        alt_clean = alt.replace('"', "'")

        img_tag = (
            f'<a href="{url}"><img src="{img}" alt="{alt_clean}" '
            f'style="width:100%;height:200px;object-fit:cover;border-radius:10px;margin-bottom:12px;" loading="lazy" /></a>'
            if img else ""
        )
        cards_html += f"""
  <div style="flex:1;min-width:200px;max-width:260px;font-family:sans-serif;text-align:center;">
    {img_tag}
    <p style="font-size:14px;font-weight:700;color:#1a1a1a;margin:0 0 4px;line-height:1.3;">{escaped_title}</p>
    <p style="font-size:16px;font-weight:800;color:#1a1a1a;margin:0 0 12px;">${price}</p>
    <a href="{url}"
       style="background:#f0ede8;color:#1a1a1a;padding:9px 20px;text-decoration:none;
              border-radius:6px;font-size:13px;font-weight:600;display:inline-block;">
      Shop Similar
    </a>
  </div>"""

    if not cards_html:
        return ""

    return f"""
<div style="margin:48px 0;padding:32px;background:#fafafa;border-radius:14px;border:1px solid #eee;">
  <h2 style="font-size:20px;font-weight:700;color:#1a1a1a;margin:0 0 24px;text-align:center;">
    You Might Also Love
  </h2>
  <div style="display:flex;flex-wrap:wrap;gap:24px;justify-content:center;">
    {cards_html}
  </div>
</div>
"""


# ── SEO metadata generation ───────────────────────────────────────────────────
EEAT_RULES = (
    "E-E-A-T requirements (Google trust signals):\n"
    "1. Write from the perspective of an expert MeeeShop fashion stylist/editor.\n"
    "2. Focus on objective product specifications (e.g., fabric blend, cut structure, weight, how the garment drapes).\n"
    "3. Provide genuine, actionable styling advice (e.g., what shoes/accessories pair best, how to transition from casual to formal).\n"
    "4. Address real-world questions from customer interactions (e.g., 'our customers often ask how the shoulders fit' or 'how to care for this fabric').\n"
    "5. Highlight merchant trust elements: free US shipping on orders $50+, easy 7-day returns, size availability from XS to 3X.\n"
    "6. Avoid fake personal anecdotes (e.g., do NOT invent stories like 'I wore this to a party last weekend'). Stick to professional analysis.\n"
    "7. Use varied, authentic vocabulary. Keep tone warm, clean, and helpful, and cut generic filler.\n\n"
)

SEED_KEYWORDS = [
    "women's fashion 2026", "affordable women's clothing USA",
    "summer dress outfits for women", "women's jeans styles guide",
    "casual chic outfits women", "cute outfits under $50",
    "stylish women's tops", "best dresses for women",
    "women's summer wardrobe essentials", "affordable boutique fashion USA",
    "work outfits for women", "women's spring outfit ideas 2026",
    "best tops to wear with jeans", "women's date night outfit ideas",
]


def _lsi_keywords(ptype: str) -> list[str]:
    ptype_lsi = {
        "dress":      ["summer dress outfits", "flattering dresses women", "midi dress", "casual dress"],
        "jean":       ["jeans for women", "best fitting jeans", "high waist jeans", "denim styles"],
        "top":        ["tops for women", "blouse styles", "work tops", "casual tops women"],
        "blouse":     ["blouse outfits", "women's blouse styles", "office blouse"],
        "skirt":      ["skirt outfits women", "midi skirt", "how to wear skirts"],
        "pant":       ["women's pants guide", "wide leg pants", "work pants women"],
        "jacket":     ["women's jacket outfits", "blazer women", "casual jacket"],
        "coat":       ["women's coat styles", "trench coat women", "coat outfit ideas"],
        "sweater":    ["cozy sweater outfits", "sweater styles", "fall fashion women"],
        "cardigan":   ["cardigan outfits", "layering cardigan", "cozy fashion"],
        "swimwear":   ["swimsuit styles women", "one piece swimsuit", "flattering swimwear"],
        "activewear": ["workout outfit women", "athleisure look", "gym clothes women"],
        "accessory":  ["women's accessories", "how to accessorize", "fashion accessories"],
    }
    base = ["women's outfit ideas", "stylish women USA", "affordable fashion", "USA boutique fashion"]
    extras = []
    for k, v in ptype_lsi.items():
        if k in ptype.lower():
            extras = v
            break
    return list(dict.fromkeys(extras + base))[:6]


def _build_refresh_prompt(article_title: str, product: dict, keyword: str,
                          existing_body: str) -> str:
    title  = product["title"]
    ptype  = (product.get("product_type") or "women's fashion").lower()
    price  = product["variants"][0]["price"] if product.get("variants") else "49"
    handle = product.get("handle", "")
    url    = f"{STORE_URL}/products/{handle}" if handle else STORE_URL
    lsi    = _lsi_keywords(ptype)
    lsi_str = ", ".join(f'"{k}"' for k in lsi)

    # Summarise existing content briefly to steer the rewrite
    existing_text = re.sub(r"<[^>]+>", " ", existing_body or "")[:600].strip()

    return (
        f"You are a fashion editor at MeeeShop, a USA women's clothing boutique.\n"
        f"TASK: Completely rewrite the body of this existing blog post for {MONTH}.\n"
        f"Keep the title EXACTLY as-is: \"{article_title}\"\n"
        f"Featured product (in-stock): {title} — ${price}\n"
        f"Product page: {url}\n"
        f"Product type: {ptype}\n\n"
        f"Existing content summary (do NOT copy, use as context only):\n{existing_text}\n\n"
        f"{EEAT_RULES}"
        f"SEO rules:\n"
        f"- Target keyword '{keyword}': use 3-4 times — in first paragraph, H2 subheadings, body, conclusion\n"
        f"- LSI keywords (weave in naturally, at least 2 in H2 subheadings): {lsi_str}\n"
        f"- Link to {url} at least twice with natural anchor text\n"
        f"- Do NOT include the <h1> tag — that is the article title already, start with <p>\n"
        f"- Use <h2>, <h3>, <p>, <ul>, <li> for structure\n"
        f"- Include sizing notes, styling tips, outfit ideas specific to this product\n"
        f"- End with a warm CTA linking to the product\n"
        f"- Answer a real problem women face when shopping for {ptype}\n"
        f"- To avoid programmatic footprints, vary your structure. Occasionally include a <blockquote style='border-left: 3px solid #ccc; padding-left: 10px; margin: 15px 0; font-style: italic;'> for a 'Stylist Tip', or distinct visual callouts. Make the flow feel like a hand-written editorial, not a template.\n\n"
        f"Store info: Free US shipping on orders $50+. 7-day returns. Sizes XS-3X.\n\n"
        f"Target: 750-900 words. Output ONLY clean HTML — no markdown, no code fences.\n"
    )


def generate_seo_meta(article_title: str, keyword: str,
                      product_title: str, ptype: str) -> dict:
    prompt = (
        f"Generate SEO metadata for a women's fashion blog post.\n"
        f"Post title: \"{article_title}\"\n"
        f"Target keyword: \"{keyword}\"\n"
        f"Featured product: {product_title} ({ptype})\n"
        f"Store: MeeeShop — USA women's boutique at us.meeeshop.com\n\n"
        f"Return ONLY these 3 lines:\n"
        f"SEO_TITLE: [50-60 chars, keyword near start, compelling]\n"
        f"META_DESC: [140-155 chars, action-oriented, includes keyword, free shipping mention, ends with CTA]\n"
        f"IMG_ALT: [10-15 words, includes keyword + 'women' + product type, no quotes]\n"
    )
    raw = ai_client.generate(prompt, max_tokens=200, temperature=0.4)

    seo_title = meta_desc = img_alt = ""
    if raw:
        for line in raw.splitlines():
            line = line.strip()
            if line.upper().startswith("SEO_TITLE:"):
                seo_title = line.split(":", 1)[1].strip().strip('"')
            elif line.upper().startswith("META_DESC:"):
                meta_desc = line.split(":", 1)[1].strip().strip('"')
            elif line.upper().startswith("IMG_ALT:"):
                img_alt = line.split(":", 1)[1].strip().strip('"')

    if not seo_title or len(seo_title) > 70:
        seo_title = f"{keyword.title()} — MeeeShop {YEAR}"[:60]
    if not meta_desc or len(meta_desc) > 165:
        meta_desc = (
            f"Discover the best {ptype} for women in {YEAR}. "
            f"Shop {product_title} at MeeeShop — free US shipping on orders $50+, "
            f"easy 7-day returns, sizes XS–3X."
        )[:155]
    if not img_alt:
        img_alt = f"{product_title} — {ptype} for women, {YEAR} fashion guide at MeeeShop"

    return {"seo_title": seo_title, "meta_desc": meta_desc, "img_alt": img_alt}


def set_article_seo_metafields(blog_id: int, article_id: int,
                                seo_title: str, meta_desc: str):
    metafields = [
        {"namespace": "global", "key": "title_tag",       "value": seo_title, "type": "single_line_text_field"},
        {"namespace": "global", "key": "description_tag", "value": meta_desc, "type": "single_line_text_field"},
    ]
    for mf in metafields:
        # Try to find existing metafield to update (upsert pattern)
        existing = fetch_article_metafields(blog_id, article_id)
        existing_mf = next((m for m in existing
                            if m.get("namespace") == "global" and m.get("key") == mf["key"]), None)
        if existing_mf:
            r = _req("put",
                     f"{BASE}/blogs/{blog_id}/articles/{article_id}/metafields/{existing_mf['id']}.json",
                     json={"metafield": {"id": existing_mf["id"], "value": mf["value"]}})
        else:
            r = _req("post",
                     f"{BASE}/blogs/{blog_id}/articles/{article_id}/metafields.json",
                     json={"metafield": mf})
        if r.status_code in (200, 201):
            print(f"    SEO metafield: {mf['key']} = {mf['value'][:60]}")
        else:
            print(f"    SEO metafield FAILED ({mf['key']}): {r.status_code} {r.text[:100]}")


def _clean_html(raw: str) -> str:
    raw = raw.strip()
    raw = re.sub(r"^```html?\s*", "", raw, flags=re.IGNORECASE)
    return re.sub(r"\s*```$", "", raw).strip()


# ── Replace out-of-stock product links in HTML ────────────────────────────────
def replace_product_links(html: str, out_handles: set[str],
                           handle_map: dict[str, dict]) -> tuple[str, int]:
    """
    Swap every href pointing to an out-of-stock product handle to its replacement.
    Returns (updated_html, swap_count).
    """
    if not out_handles:
        return html, 0

    swaps = 0

    def replace_href(m: re.Match) -> str:
        nonlocal swaps
        handle = m.group(1)
        if handle in handle_map:
            rep = handle_map[handle]
            new_handle = rep.get("handle", "")
            if not new_handle:
                return m.group(0)
            new_url = (
                f"https://us.meeeshop.com/products/{new_handle}"
                f"?utm_source=blog&utm_medium=refreshed_link&utm_campaign=meeeshop_refresh"
            )
            swaps += 1
            return f'href="{new_url}"'
        return m.group(0)

    # Replace hrefs
    html = PRODUCT_LINK_RE.sub(replace_href, html)

    # Also update any visible product titles/prices near the swapped links.
    # We do a best-effort replacement of product name text that appeared in cards.
    for old_handle, new_product in handle_map.items():
        if old_handle not in out_handles:
            continue
        new_title = re.escape(new_product.get("title", ""))
        # We can't reliably replace product names in prose — we leave that to the AI rewrite.

    return html, swaps


def remove_out_of_stock_product_cards(html: str, out_handles: set[str]) -> str:
    """
    Remove entire styled product-card divs that contain out-of-stock product links.
    These are identified by our characteristic card div pattern.
    """
    if not out_handles:
        return html

    for handle in out_handles:
        # Match our card div: starts with <div style="background:#f8f6f3 ...
        # and contains a link to this product handle
        pattern = re.compile(
            r'<div\s+style="background:#f8f6f3[^"]*"[^>]*>(?:(?!<div\s+style="background:#f8f6f3).)*?'
            + re.escape(f'/products/{handle}') + r'.*?</div>\s*</div>',
            re.DOTALL | re.IGNORECASE,
        )
        html = pattern.sub("", html)

    return html


# ── Main article refresh logic ────────────────────────────────────────────────
def refresh_article(blog: dict, article: dict, all_products: list,
                    in_stock: list, out_of_stock_handles: set[str],
                    product_by_handle: dict[str, dict],
                    dry_run: bool = False) -> dict | None:
    """
    Refresh one article. Returns a result dict on success, None on skip/failure.
    Result keys: replacements (list of {old, new} dicts), featured_product (title).
    """
    blog_id    = blog["id"]
    article_id = article["id"]
    art_title  = article["title"]
    art_handle = article.get("handle", "")
    body       = article.get("body_html", "") or ""

    print(f"\n  Article : '{art_title[:70]}'")
    print(f"  Handle  : {art_handle}")

    # ── 1. Find out-of-stock product handles referenced in this article ───────
    referenced = extract_product_handles(body)
    oos_in_article = referenced & out_of_stock_handles
    print(f"  Products referenced: {len(referenced)} | out-of-stock: {len(oos_in_article)}")

    # Build replacement map for out-of-stock handles
    replacement_map: dict[str, dict] = {}
    replacements_log: list[dict] = []
    chosen_featured: dict | None = None

    for handle in oos_in_article:
        old_product = product_by_handle.get(handle)
        if not old_product:
            continue
        replacement = find_best_replacement(old_product, in_stock)
        if replacement:
            replacement_map[handle] = replacement
            if chosen_featured is None:
                chosen_featured = replacement
            replacements_log.append({
                "old_handle": handle,
                "old_title":  old_product["title"],
                "new_handle": replacement["handle"],
                "new_title":  replacement["title"],
            })
            print(f"    Replacing '{old_product['title'][:40]}' → '{replacement['title'][:40]}'")
        else:
            print(f"    No replacement found for '{handle}'")

    # ── 2. If no products in article at all, pick a featured product ──────────
    no_products_originally = not referenced
    if no_products_originally:
        print("  No products in post — will inject a featured product")
        with_img = [p for p in in_stock if p.get("images")]
        chosen_featured = random.choice(with_img) if with_img else (random.choice(in_stock) if in_stock else None)

    # If we have no replacement to feature, pick any in-stock product
    if chosen_featured is None and in_stock:
        with_img = [p for p in in_stock if p.get("images")]
        chosen_featured = random.choice(with_img) if with_img else random.choice(in_stock)

    if not chosen_featured:
        print("  SKIP — no in-stock products available")
        return None

    # ── 3. Pick keyword for this refresh ──────────────────────────────────────
    ptype   = (chosen_featured.get("product_type") or "women's fashion").lower()
    keyword = random.choice(SEED_KEYWORDS)

    # ── 4. Build new body HTML via AI ─────────────────────────────────────────
    print(f"  Featured: '{chosen_featured['title'][:50]}' (${chosen_featured['variants'][0]['price'] if chosen_featured.get('variants') else '?'})")
    print(f"  Keyword : {keyword}")
    print("  Generating refreshed content…")

    prompt   = _build_refresh_prompt(art_title, chosen_featured, keyword, body)
    new_body = ai_client.generate(prompt, max_tokens=1800, temperature=0.75)

    if not new_body:
        print("  [AI] all providers failed — skipping article")
        return None

    new_body = _clean_html(new_body)

    # ── 5. Inject product card + related products ──────────────────────────────
    # Insert featured product card after first </p>
    card = make_product_card(chosen_featured, keyword)
    pos  = new_body.find("</p>")
    if pos != -1:
        new_body = new_body[:pos+4] + "\n" + card + new_body[pos+4:]
    else:
        new_body = card + new_body

    # "You Might Also Love" section at the bottom
    new_body += make_related_products_section(
        all_products, chosen_featured.get("handle", ""), keyword
    )

    # ── 6. Generate SEO metadata ───────────────────────────────────────────────
    print("  Generating SEO metadata…")
    seo = generate_seo_meta(art_title, keyword, chosen_featured["title"], ptype)
    print(f"  SEO title : {seo['seo_title']}")
    print(f"  Meta desc : {seo['meta_desc'][:80]}…")

    # ── 7. Featured image URL (1200px) ────────────────────────────────────────
    img_url = make_featured_image_url(chosen_featured)
    img_src = "Shopify CDN 1200x630" if chosen_featured.get("images") else "Pollinations.ai"
    print(f"  Image     : {img_src}")

    # ── 8. Build summary_html (meta description excerpt) ─────────────────────
    summary_html = f"<p>{seo['meta_desc']}</p>"

    # ── 9. Build updated tags ─────────────────────────────────────────────────
    existing_tags = [t.strip() for t in (article.get("tags") or "").split(",") if t.strip()]
    new_tags = list(dict.fromkeys(
        existing_tags +
        ["fashion", "women fashion", "MeeeShop", "USA fashion", f"fashion {YEAR}"] +
        [w for w in keyword.split() if len(w) > 3][:3]
    ))[:20]
    tags_str = ", ".join(new_tags)

    # ── 10. Dry-run short-circuit ─────────────────────────────────────────────
    if dry_run:
        preview = re.sub(r"<[^>]+>", " ", new_body)[:200].strip()
        print(f"  [DRY-RUN] would PATCH article {article_id}")
        print(f"  Preview  : {preview}…")
        return {"replacements": replacements_log, "featured_product": chosen_featured["title"]}

    # Save a backup of the original article content before we edit it
    backup_data = {
        "article_id": article_id,
        "title": art_title,
        "handle": art_handle,
        "body_html": body,
        "summary_html": article.get("summary_html", ""),
        "tags": article.get("tags", ""),
        "image": article.get("image", {}),
        "backup_timestamp": datetime.now().isoformat()
    }
    backup_dir = ROOT / "backup_articles"
    backup_dir.mkdir(exist_ok=True)
    backup_file = backup_dir / f"article_{article_id}_{int(time.time())}.json"
    backup_file.write_text(json.dumps(backup_data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"    [Backup] Saved original article content to backup_articles/{backup_file.name}")

    # ── 11. PATCH the article (keeps same URL handle and title) ───────────────
    payload = {
        "article": {
            "id":           article_id,
            "body_html":    new_body,
            "summary_html": summary_html,
            "tags":         tags_str,
            "published":    True,
        }
    }
    # Update featured image
    payload["article"]["image"] = {
        "src": img_url,
        "alt": seo["img_alt"],
    }

    r = _req("put", f"{BASE}/blogs/{blog_id}/articles/{article_id}.json", json=payload)
    if r.status_code not in (200, 201):
        print(f"  PATCH FAILED {r.status_code}: {r.text[:200]}")
        return None

    print(f"  PATCHED  : article {article_id} updated successfully")

    # ── 12. Upsert SEO metafields ─────────────────────────────────────────────
    set_article_seo_metafields(blog_id, article_id, seo["seo_title"], seo["meta_desc"])

    return {"replacements": replacements_log, "featured_product": chosen_featured["title"]}


# ── Entrypoint ────────────────────────────────────────────────────────────────
def run(limit: int = 5, dry_run: bool = False, article_id: int | None = None,
        force: bool = False, batch_size: int = 20, batch_index: int = 0):
    mode = "force" if force else ("single" if article_id else "batch")
    print(f"\n{'='*64}")
    print(f"  MeeeShop Blog Refresher — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  Mode: {mode} | Limit: {limit} | Dry-run: {dry_run}")
    if force:
        print(f"  Batch: {batch_index} (size {batch_size})")
    print(f"{'='*64}\n")

    # ── Products ──────────────────────────────────────────────────────────────
    print("Fetching all products…")
    all_products = fetch_all_products()
    in_stock, out_of_stock = split_products(all_products)
    out_of_stock_handles   = {p["handle"] for p in out_of_stock if p.get("handle")}
    product_by_handle      = {p["handle"]: p for p in all_products if p.get("handle")}

    print(f"  Total: {len(all_products)} | In-stock: {len(in_stock)} | Out-of-stock: {len(out_of_stock)}\n")

    if not in_stock:
        sys.exit("ERROR: No in-stock products found — nothing to replace with.")

    # ── Blogs ─────────────────────────────────────────────────────────────────
    print("Fetching blogs…")
    blogs = fetch_all_blogs()
    print(f"  {len(blogs)} blogs: {[b['title'] for b in blogs]}\n")

    # ── Collect articles to process ───────────────────────────────────────────
    work_items: list[tuple[dict, dict]] = []  # (blog, article)

    if article_id:
        # Single article mode
        for blog in blogs:
            r = _req("get", f"{BASE}/blogs/{blog['id']}/articles/{article_id}.json")
            if r.ok:
                art = r.json().get("article")
                if art:
                    work_items.append((blog, art))
                    break
        if not work_items:
            sys.exit(f"ERROR: Article {article_id} not found in any blog.")
    else:
        # Gather ALL articles across all blogs, oldest published_at first
        all_articles: list[tuple[dict, dict]] = []
        for blog in blogs:
            arts = fetch_articles_for_blog(blog["id"], limit=500)
            for art in arts:
                all_articles.append((blog, art))

        all_articles.sort(key=lambda x: x[1].get("published_at") or "")

        if force:
            # Slice this batch out of the full sorted list
            start = batch_index * batch_size
            end   = start + batch_size
            work_items = all_articles[start:end]
            print(f"  Force batch {batch_index}: articles {start}–{end-1} of {len(all_articles)} total")
        else:
            work_items = all_articles[:limit]

    print(f"Articles to refresh: {len(work_items)}\n")

    # ── Process each article ──────────────────────────────────────────────────
    updated = skipped = 0
    log = []

    for blog, article in work_items:
        try:
            result = refresh_article(
                blog, article, all_products,
                in_stock, out_of_stock_handles, product_by_handle,
                dry_run=dry_run,
            )
            if result:
                updated += 1
                log.append({"id": article["id"], "title": article["title"],
                             "status": "updated", "dry_run": dry_run,
                             "replacements": result.get("replacements", []),
                             "featured_product": result.get("featured_product")})
            else:
                skipped += 1
                log.append({"id": article["id"], "title": article["title"],
                             "status": "skipped"})
        except Exception as exc:
            print(f"  ERROR on article {article.get('id')}: {exc}")
            skipped += 1
            log.append({"id": article.get("id"), "title": article.get("title"),
                         "status": "error", "error": str(exc)})
        time.sleep(1.5)  # polite rate-limiting

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'='*64}")
    print(f"  Done — {updated} refreshed, {skipped} skipped (of {len(work_items)} articles)")
    if not dry_run:
        print(f"  View updated posts at: https://{SHOP}/blogs")
    print(f"{'='*64}\n")

    # Write JSON log for GitHub Actions artifact upload
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = ROOT / f"modify_blog_{stamp}.json"
    log_file.write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Log written: {log_file.name}")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="MeeeShop weekly blog refresher")
    ap.add_argument("--dry-run",     action="store_true", help="Print plan, no Shopify writes")
    ap.add_argument("--limit",       type=int, default=5,  help="Max articles per run (default 5; ignored in --force)")
    ap.add_argument("--article-id",  type=int, default=None, help="Refresh one specific article by ID")
    ap.add_argument("--force",       action="store_true", help="Update ALL articles (use with --batch-size/--batch-index)")
    ap.add_argument("--batch-size",  type=int, default=20, help="Articles per batch in force mode (default 20)")
    ap.add_argument("--batch-index", type=int, default=0,  help="Which batch to process (0-based)")
    args = ap.parse_args()

    run(
        limit=args.limit,
        dry_run=args.dry_run,
        article_id=args.article_id,
        force=args.force,
        batch_size=args.batch_size,
        batch_index=args.batch_index,
    )

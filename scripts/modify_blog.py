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
from bs4 import BeautifulSoup

import requests
ROOT = Path(__file__).resolve().parent.parent

import ai_client
from blog_daily import generate_fallback_blog_post, get_product_display_name, PEN_NAMES

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
    """Find best in-stock replacement: same product_type (must have image, different product)."""
    ptype = (out_product.get("product_type") or "").lower()
    out_handle = out_product.get("handle")
    # Same type with image, different product
    same = [
        p for p in in_stock 
        if (p.get("product_type") or "").lower() == ptype 
        and p.get("images") 
        and p.get("handle") != out_handle
    ]
    if same:
        return random.choice(same)
    return None


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
            "fields": "id,title,handle,body_html,image,tags,summary_html,published_at,author",
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

def fix_article_images(html_str: str, product_by_handle: dict[str, dict]) -> tuple[str, int]:
    """
    Parse article body, find any links to products, and if they contain an image,
    ensure the image src matches the latest live product image.
    Returns (updated_html, swap_count).
    """
    if not html_str:
        return html_str, 0

    soup = BeautifulSoup(f"<div>{html_str}</div>", "html.parser")
    root = soup.div
    if not root:
        return html_str, 0
        
    swaps = 0
    # 1. Update existing images
    for a in root.find_all("a"):
        href = a.get("href", "")
        m = re.search(r'/products/([a-z0-9_-]+)', href, re.IGNORECASE)
        if m:
            handle = m.group(1)
            product = product_by_handle.get(handle)
            if product:
                # Find img inside
                img = a.find("img")
                if img:
                    current_src = img.get("src", "")
                    new_src = product_img_url(product)
                    # We compare the base URL without query parameters for a cleaner check
                    if new_src:
                        new_src_base = new_src.split('?')[0]
                        current_src_base = current_src.split('?')[0] if current_src else ""
                        if current_src_base != new_src_base:
                            img["src"] = new_src
                            swaps += 1

    # 2. Add missing images to product cards
    for div in root.find_all("div"):
        style = div.get("style", "") or ""
        style_clean = style.replace(" ", "").lower()
        # Identify main product card
        if "background:#f8f6f3" in style_clean:
            # Check if it lacks an img
            if not div.find("img"):
                # It doesn't have an image, find the product link inside to get the handle
                a_tag = div.find("a", href=re.compile(r'/products/', re.IGNORECASE))
                if a_tag:
                    href = a_tag.get("href", "")
                    m = re.search(r'/products/([a-z0-9_-]+)', href, re.IGNORECASE)
                    if m:
                        handle = m.group(1)
                        product = product_by_handle.get(handle)
                        if product:
                            img_src = product_img_url(product)
                            if img_src:
                                import html
                                raw_title = product.get("title", "")
                                ptype = (product.get("product_type") or "women's fashion").lower()
                                alt = f"{raw_title} — {ptype} for women at MeeeShop"
                                alt_clean = alt.replace('"', "'")
                                url = f"{STORE_URL}/products/{handle}?utm_source=blog&utm_medium=featured_card&utm_campaign=meeeshop_refresh"
                                
                                img_html = f'<a href="{url}"><img src="{img_src}" alt="{alt_clean}" style="width:220px;height:220px;object-fit:cover;border-radius:10px;flex-shrink:0;" loading="lazy" /></a>'
                                new_img_soup = BeautifulSoup(img_html, "html.parser")
                                div.insert(0, new_img_soup)
                                swaps += 1

    # Reconstruct the inner HTML
    res = "".join(str(c) for c in root.contents)
    return res.strip(), swaps



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
    "EDITORIAL VOICE & E-E-A-T REQUIREMENTS (non-negotiable — Google trust signals + reader value):\n\n"

    "═══ OPENING HOOK (Critical for Google Discover CTR) ═══\n"
    "Open with a SPECIFIC, OPINIONATED hook that immediately validates the reader's real-world problem.\n"
    "✅ GOOD: 'The single-roll cuff is everywhere right now — and after testing every variation on dark wash, barrel leg, and cigarette jeans, here is exactly what actually works.'\n"
    "✅ GOOD: 'If your jeans still smell faintly musty after washing, you are not alone — and a second wash is rarely the answer.'\n"
    "❌ BAD: 'Jeans are a timeless wardrobe staple that women everywhere love.'\n"
    "❌ BAD: 'In today's world of fashion, finding the perfect pair of jeans can be challenging.'\n\n"

    "═══ VOICE & TONE ═══\n"
    "Write as a knowledgeable, trusted stylist friend — warm, direct, and specific. NOT a brand.\n"
    "• Use second person ('your jeans', 'your body') to keep the reader central.\n"
    "• Mix short punchy sentences with longer explanatory ones. Vary rhythm deliberately.\n"
    "• Be opinionated where it helps: 'Skip the wide-leg for petite frames — the volume will overwhelm.'\n"
    "• Acknowledge real trade-offs: 'Cigarette jeans are incredibly chic, but if you run curvy in the hip, size up and have them tailored at the waist.'\n\n"

    "═══ SPECIFIC RECOMMENDATIONS (Required — not vague) ═══\n"
    "All styling advice MUST name specific item categories with descriptors. MeeeShop sells clothing only — do NOT recommend specific shoes. Instead recommend clothing layers, tops, bags, belts, and jewelry with specific descriptors:\n"
    "✅ GOOD: 'A relaxed linen button-down in ecru — untucked, one button undone at the collar — hits differently over dark wash jeans.'\n"
    "✅ GOOD: 'A structured mini tote in chocolate brown or off-white anchors the quiet luxury aesthetic without trying too hard.'\n"
    "✅ GOOD: 'Layer a cropped blazer in camel or ivory over the top — it balances the proportions instantly.'\n"
    "❌ BAD: 'Pair with heels for a polished look.' (no shoe recs — MeeeShop doesn't sell shoes)\n"
    "❌ BAD: 'Accessorize to complete the outfit.' (too vague)\n"
    "❌ BAD: 'Add a bag to elevate the look.' (generic filler)\n\n"

    "═══ 2026 TREND CONTEXT (Weave in naturally — sourced from Flipboard #Style 8.4M followers) ═══\n"
    "Reference real trends where relevant but do NOT force every trend into every article:\n"
    "• Quiet luxury: 'No logos, no distressing — clean dark wash denim with a tucked-in linen shirt is the 2026 quiet luxury formula.'\n"
    "• Cigarette/stovepipe silhouette replacing wide-leg as dominant denim cut in 2026.\n"
    "• Dark indigo clean wash over distressed/light wash — reads more expensive instantly.\n"
    "• Linen top + dark wash jean = the heat-proof chic summer formula trending on Flipboard.\n"
    "• All-black outfits even in summer — trending on Flipboard #Style with 8.4M followers.\n"
    "• Oversized blazer over a simple tank + straight-leg jeans = the office-to-evening formula.\n\n"

    "═══ STRUCTURE & FORMAT ═══\n"
    "• Use H2 for major sections, H3 for sub-steps or occasions.\n"
    "• Include at least 1 blockquote styled as a 'Stylist Tip' with specific advice.\n"
    "• Use bullet lists for step-by-step instructions (care guides, how-tos).\n"
    "• For outfit formulas: name EACH look with a creative occasion title (e.g., 'Look 1: Sunday Farmers Market', not 'Casual Look').\n"
    "• Vary structure between articles — avoid formulaic repetition.\n\n"

    "═══ BANNED PHRASES (never use these) ═══\n"
    "elevate your look | effortlessly chic | perfect for any occasion | versatile wardrobe staple\n"
    "timeless classic | fashion-forward | look and feel your best | style game\n"
    "take your look to the next level | complete your outfit | fashion journey\n\n"

    "═══ TRUST SIGNALS ═══\n"
    "Include naturally (once, in CTA or intro): Free US shipping on orders $50+. Easy 7-day returns. Sizes XS–3X.\n\n"
)

SEED_KEYWORDS = [
    # 2026 Trending — sourced from Flipboard #Style (8.4M followers) & Who What Wear
    "women's fashion 2026", "summer outfit ideas for women 2026",
    "affordable women's clothing USA", "summer dress outfits for women",
    "women's jeans styles guide", "casual chic outfits women",
    "cute outfits under $50", "stylish women's tops",
    "best dresses for women", "women's summer wardrobe essentials",
    "affordable boutique fashion USA", "work outfits for women",
    "best tops to wear with jeans", "women's date night outfit ideas",
    # Jeans-specific trending 2026 (Flipboard #Jeans 66K followers)
    "how to style jeans 2026", "dark wash jeans outfits",
    "quiet luxury jeans women", "cigarette jeans styling tips",
    "barrel leg jeans vs wide leg", "linen top with jeans outfit",
    "blazer with jeans outfit ideas", "how to look taller in jeans",
    # Care & How-To (high search intent)
    "how to wash jeans without fading", "how to remove stains from jeans",
    "how to remove smell from clothes", "how to fix pilling on clothes",
    # Summer 2026 (Flipboard #SummerFashion 73.9K followers)
    "linen top with jeans outfit", "summer denim outfit ideas",
    "all black summer outfit women", "women's capsule wardrobe 2026",
]


def _lsi_keywords(ptype: str) -> list[str]:
    ptype_lsi = {
        "dress":      ["summer dress outfits", "flattering dresses women", "midi dress",
                       "linen dresses 2026", "casual dress outfit ideas"],
        "jean":       ["jeans for women 2026", "best fitting jeans", "high waist jeans",
                       "dark wash jeans outfits", "cigarette jeans styling", "quiet luxury denim",
                       "barrel leg jeans", "linen top with jeans outfit", "denim trends 2026"],
        "top":        ["tops for women", "blouse styles", "work tops", "casual tops women",
                       "linen tops summer 2026"],
        "blouse":     ["blouse outfits", "women's blouse styles", "office blouse", "summer blouse ideas"],
        "skirt":      ["skirt outfits women", "midi skirt", "how to wear skirts", "asymmetric skirt 2026"],
        "pant":       ["women's pants guide", "wide leg pants", "work pants women", "trouser trends 2026"],
        "jacket":     ["women's jacket outfits", "blazer women", "casual jacket", "blazer jeans combo"],
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
    return list(dict.fromkeys(extras + base))[:8]


# ── Handle-aware content blueprint map ───────────────────────────────────────
# Maps URL handle keywords → required article structure so content matches URL.
# Sourced from Flipboard trending topics & Who What Wear 2026 editorial standards.
HANDLE_CONTENT_RULES: dict[str, dict] = {
    "how-to-cuff":         {"topic": "how to cuff jeans",
                            "required_sections": ["Why Cuffing Works (proportion + ankle visibility + outfit balance)",
                                                  "The Single Roll Cuff", "The Double Roll Cuff",
                                                  "The Pin Roll Cuff",
                                                  "What Tops Work Best With Each Cuff Style (tuck in or crop?)",
                                                  "2026 Styling Tip: Cigarette Jeans + Cropped Linen Top — The Cuffed Look"],
                            "tone": "step-by-step how-to, practical"},
    "sizing-guide":        {"topic": "jeans sizing guide for women",
                            "required_sections": ["How to Measure Yourself for Jeans",
                                                  "US Jeans Size Chart",
                                                  "Fit Guide by Body Shape (petite, hourglass, curvy, tall)",
                                                  "High Waist vs Mid Rise vs Low Rise — Which Fits Best?",
                                                  "How to Choose Size XS–3X Online"],
                            "tone": "helpful, inclusive, size-positive"},
    "how-to-look-taller":  {"topic": "how to look taller with clothing",
                            "required_sections": ["The Leg-Lengthening Formula: Rise + Tuck-In Trick",
                                                  "High-Waisted Jeans and Why They Work",
                                                  "The Tuck-In Effect: How a Cropped or Tucked Top Creates Leg Length",
                                                  "Monochrome Dressing for Height Illusion",
                                                  "Vertical Stripes and Elongating Details on Tops",
                                                  "2026 Pro Tip: Cigarette Jeans + Fitted Ribbed Top = Longest-Looking Legs"],
                            "tone": "empowering, styling expert"},
    "how-to-pair":         {"topic": "how to pair jeans with outfits",
                            "required_sections": ["The Foundation: Choosing the Right Jeans Wash for the Vibe",
                                                  "Casual Formula: Linen Top + Dark Wash Jean + Crossbody Bag",
                                                  "Office Formula: Blazer + Fitted Top + Straight-Leg Jeans",
                                                  "Evening Formula: Silk Blouse + Cigarette Jeans + Statement Earrings",
                                                  "Weekend Formula: Oversized Tee + Barrel Leg + Tote Bag",
                                                  "The Quiet Luxury Jeans Look for 2026"],
                            "tone": "outfit formula, editorial"},
    "what-to-pair":        {"topic": "what to pair with jeans",
                            "required_sections": ["Tops That Always Work With Jeans (tuck-in vs untucked vs knotted)",
                                                  "Layering Pieces: Blazers, Cardigans, and Jackets That Elevate Denim",
                                                  "Accessories: Belts, Bags, and Jewelry That Complete the Look",
                                                  "The Top + Bottom Proportion Rule for Different Jeans Silhouettes",
                                                  "Complete Outfit Formulas for 5 Occasions"],
                            "tone": "practical, shoppable, style guide"},
    "how-to-clean-pilling": {"topic": "how to remove pilling from clothes",
                             "required_sections": ["What Causes Pilling (and Which Fabrics Are Most Vulnerable)",
                                                   "The Sweater Stone Method",
                                                   "The Fabric Shaver Method",
                                                   "The Razor Trick",
                                                   "How to Prevent Pilling: Washing Tips",
                                                   "Care Instructions by Fabric Type"],
                             "tone": "practical, care expert"},
    "stinky-smell":        {"topic": "how to remove smell from clothes without washing",
                            "required_sections": ["Why Clothes Smell (bacteria, sweat, detergent buildup)",
                                                  "The Freezer Method",
                                                  "White Vinegar Spray",
                                                  "Baking Soda Treatment",
                                                  "Vodka Spritz Hack",
                                                  "Steam vs Dry Air Out",
                                                  "Prevention: The Wash-Less Denim Movement 2026"],
                            "tone": "practical, problem-solver"},
    "remove-stain":        {"topic": "how to remove stains from jeans and clothes",
                            "required_sections": ["Act Fast: The First 60 Seconds Rule",
                                                  "Oil and Grease Stains",
                                                  "Wine and Berry Stains",
                                                  "Grass and Mud Stains",
                                                  "Dye Transfer Stains",
                                                  "What NOT To Do (common mistakes)",
                                                  "Care After Stain Removal"],
                            "tone": "practical, urgent, step-by-step"},
}


def _get_handle_rules(article_handle: str) -> dict | None:
    """Return handle-specific content rules if the handle matches a known pattern."""
    handle_lower = (article_handle or "").lower()
    for pattern, rules in HANDLE_CONTENT_RULES.items():
        if pattern in handle_lower:
            return rules
    return None


def _build_refresh_prompt(article_title: str, product: dict, keyword: str,
                          existing_body: str, article_handle: str = "") -> str:
    title  = product["title"]
    ptype  = (product.get("product_type") or "women's fashion").lower()
    price  = product["variants"][0]["price"] if product.get("variants") else "49"
    lsi    = _lsi_keywords(ptype)
    lsi_str = ", ".join(f'"{k}"' for k in lsi)

    # Summarise existing content briefly to steer the rewrite
    existing_text = re.sub(r"<[^>]+>", " ", existing_body or "")[:600].strip()

    # ── Handle-aware content blueprint ────────────────────────────────────────
    # If the article handle matches a known how-to/guide pattern, inject
    # explicit structural requirements so the content MATCHES the URL handle.
    # This fixes the handle/content mismatch reported after daily/weekly refreshes.
    handle_rules = _get_handle_rules(article_handle)
    handle_section = ""
    if handle_rules:
        sections_list = "\n".join(f"  {i+1}. {s}" for i, s in enumerate(handle_rules["required_sections"]))
        handle_section = (
            f"\n\n⚠️  CRITICAL — HANDLE/CONTENT ALIGNMENT (SEO REQUIREMENT):\n"
            f"The URL handle for this article is: '{article_handle}'\n"
            f"This URL handle tells Google and readers the article is about: '{handle_rules['topic']}'\n"
            f"The article body MUST deliver exactly this promised content or Google will downrank it.\n"
            f"Tone for this article: {handle_rules['tone']}\n"
            f"REQUIRED H2 sections (cover ALL of these, in a logical order):\n{sections_list}\n"
            f"The featured product ({title}) should be woven in as a RECOMMENDATION within this guide, "
            f"NOT as the primary focus. The guide topic is the primary focus.\n"
            f"2026 FRESHNESS ANGLES to include naturally:\n"
            f"  - Reference 'quiet luxury' denim aesthetic: dark wash + tucked linen top, no logos, clean lines\n"
            f"  - Mention cigarette/stovepipe jeans as the 2026 trending silhouette\n"
            f"  - Reference linen tops + jeans as the trending summer formula (heat-proof + chic)\n"
            f"  - Mention dark indigo/clean wash denim as the elevated 2026 choice\n"
        )
    else:
        # For articles without a specific handle match, add general 2026 freshness
        handle_section = (
            f"\n\n2026 TREND FRESHNESS (weave in naturally, 1-2 references):\n"
            f"  - Quiet luxury styling: clean lines, no logos, elevated basics\n"
            f"  - Summer 2026 colour palette: dark indigo denim, linen textures, earth tones\n"
            f"  - The office-to-evening formula: oversized blazer + fitted top + straight-leg jeans\n"
            f"  - Heat-proof summer styling: linen tops, breathable fabrics, cropped layers\n"
        )

    return (
        f"You are a fashion editor at MeeeShop, a USA women's clothing boutique.\n"
        f"TASK: Completely rewrite the body of this existing blog post for {MONTH}.\n"
        f"Keep the title EXACTLY as-is: \"{article_title}\"\n"
        f"Featured product (in-stock): {title} — ${price}\n"
        f"Product type: {ptype}\n"
        f"Article URL handle: {article_handle or '(unknown)'}\n\n"
        f"Existing content summary (do NOT copy, use as context only):\n{existing_text}\n"
        f"{handle_section}\n\n"
        f"{EEAT_RULES}"
        f"SEO rules:\n"
        f"- Target keyword '{keyword}': use 3-4 times — in first paragraph, H2 subheadings, body, conclusion\n"
        f"- LSI keywords (weave in naturally, at least 2 in H2 subheadings): {lsi_str}\n"
        f"- Do NOT write or include any HTML links (<a> tags) to the product page or MeeeShop anywhere in the body text. The product card and shop-the-look widgets will be programmatically injected by the developer, so manual linking inside the article is redundant and violates SEO guidelines by looking spammy.\n"
        f"- Limit mentions of the product title '{title}' to a maximum of 2 times in the entire body. When referring to the product subsequent times, use pronouns or generic terms (e.g., 'this dress', 'the top', 'it', 'this piece') instead of repeating the full product name.\n"
        f"- Do NOT include the <h1> tag — that is the article title already, start with <p>\n"
        f"- Use <h2>, <h3>, <p>, <ul>, <li> for structure\n"
        f"- Include sizing notes, styling tips, outfit ideas specific to the article topic and product\n"
        f"- End with a warm CTA recommendation and price (do NOT include HTML links)\n"
        f"- Answer a real problem women face: '{handle_rules['topic'] if handle_rules else f'shopping for {ptype}'}' \n"
        f"- To avoid programmatic footprints, vary your structure. Occasionally include a "
        f"<blockquote style='border-left: 3px solid #ccc; padding-left: 10px; margin: 15px 0; font-style: italic;'> "
        f"for a 'Stylist Tip', or a styled callout box. Make the flow feel like a hand-written editorial, not a template.\n\n"
        f"Store info: Free US shipping on orders $50+. 7-day returns. Sizes XS-3X.\n\n"
        f"Target: 800-950 words. Output ONLY clean HTML — no markdown, no code fences.\n"
        f"\n\nAt the very end of your response, after the HTML content, you MUST append a `<seometa>` section "
        f"containing the SEO metadata. The format MUST be exactly like this (use these exact keys):\n"
        f"<seometa>\n"
        f"SEO_TITLE: [50-60 chars, handle topic keyword near start, year or 'for Women', compelling]\n"
        f"META_DESC: [140-155 chars, action-oriented, includes handle topic keyword, free shipping mention, ends with CTA]\n"
        f"IMG_ALT: [descriptive ALT text for featured image, 10-15 words, includes topic keyword + 'women' + product type, no quotes]\n"
        f"</seometa>\n"
        f"Make sure there are no other text or markdown code fences enclosing the <seometa> block."
    )


def parse_and_clean_seo_meta(raw_seo_text: str, keyword: str, product_title: str, ptype: str) -> dict:
    """
    Parse SEO title, meta description, and image ALT text from the extracted text block.
    Falls back to deterministic values if parsing fails or fields are missing.
    """
    seo_title = meta_desc = img_alt = ""

    if raw_seo_text:
        for line in raw_seo_text.splitlines():
            line = line.strip()
            if line.upper().startswith("SEO_TITLE:"):
                seo_title = line.split(":", 1)[1].strip().strip('"')
            elif line.upper().startswith("META_DESC:"):
                meta_desc = line.split(":", 1)[1].strip().strip('"')
            elif line.upper().startswith("IMG_ALT:"):
                img_alt = line.split(":", 1)[1].strip().strip('"')

    # Deterministic fallbacks — always valid even if AI fails
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


def clean_article_body_html(html_str: str) -> str:
    from bs4 import BeautifulSoup
    if not html_str:
        return ""

    # Remove previous shop-the-look widgets via robust regex
    html_str = re.sub(r'<!--\s*meeeshop-shop-the-look-start\s*-->[\s\S]*?<!--\s*meeeshop-shop-the-look-end\s*-->', '', html_str)
    html_str = html_str.replace("meeeshop-shop-the-look-start", "").replace("meeeshop-shop-the-look-end", "")

    soup = BeautifulSoup(f"<div>{html_str}</div>", "html.parser")
    root = soup.div
    if not root:
        return html_str

    # 1. Remove featured product cards, related products sections, and shop-the-look widgets
    for h3 in root.find_all("h3"):
        if h3.get_text().strip().lower() in ("shop the look", "you might also love"):
            h3.decompose()

    for div in root.find_all("div"):
        if div.attrs is None:
            continue
        style = div.get("style", "") or ""
        style = style.replace(" ", "").lower()
        if "background:#f8f6f3" in style or "background:#fafafa" in style or "background:#f0ede8" in style:
            div.decompose()
            continue
        if "display:grid" in style and "grid-template-columns" in style:
            div.decompose()
            continue
        if "border:1pxsolid#f0f0f0" in style or "background:#fff" in style:
            div.decompose()
            continue

    # Remove leftover <hr> tags that might have divided the widget
    for hr in root.find_all("hr"):
        style = hr.get("style", "") or ""
        style = style.replace(" ", "").lower()
        if "border-top:1pxsolid#eee" in style:
            hr.decompose()

    # 2. Strip all internal links pointing to meeeshop
    for a in root.find_all("a"):
        href = a.get("href", "").lower()
        if "meeeshop" in href or "/collections/" in href or "/products/" in href:
            # Replace <a> tag with its inner text content
            a.replace_with(a.get_text())

    # Reconstruct the inner HTML
    res = "".join(str(c) for c in root.contents)
    return res.strip()


def swap_products_in_html(body_html: str, replacement_map: dict[str, dict], product_by_handle: dict[str, dict]) -> tuple[str, int]:
    """
    Parse the HTML, find all product links that point to out-of-stock products,
    and replace their product card container (if found) or the link/text inline.
    Returns (new_html, swap_count).
    """
    if not body_html or not replacement_map:
        return body_html, 0

    soup = BeautifulSoup(body_html, "html.parser")
    swaps = 0

    # 1. First find and replace product card containers
    for a in soup.find_all("a"):
        href = a.get("href", "")
        m = re.search(r'/products/([a-z0-9_-]+)', href, re.IGNORECASE)
        if m:
            handle = m.group(1)
            if handle in replacement_map:
                rep = replacement_map[handle]
                
                # Check for styled product card container
                card_container = None
                parent = a.parent
                while parent and parent.name not in ("body", "html", "[document]"):
                    style = parent.get("style", "") or ""
                    style_clean = style.replace(" ", "").lower()
                    if "background:#f8f6f3" in style_clean: # main product card
                        card_container = parent
                        break
                    parent = parent.parent
                
                if card_container:
                    new_card_html = make_product_card(rep)
                    new_card_soup = BeautifulSoup(new_card_html, "html.parser")
                    card_container.replace_with(new_card_soup)
                    swaps += 1

    # 2. Swap inline product links (href, titles, and inner images)
    for a in soup.find_all("a"):
        href = a.get("href", "")
        m = re.search(r'/products/([a-z0-9_-]+)', href, re.IGNORECASE)
        if m:
            handle = m.group(1)
            if handle in replacement_map:
                rep = replacement_map[handle]
                
                # Update href
                new_url = f"https://us.meeeshop.com/products/{rep['handle']}?utm_source=blog&utm_medium=refreshed_link&utm_campaign=meeeshop_refresh"
                a["href"] = new_url
                
                # Update visible text if it contains the old title
                old_prod = product_by_handle.get(handle)
                if old_prod:
                    old_title = old_prod.get("title", "")
                    if a.string and old_title.lower() in a.string.lower():
                        a.string = rep["title"]
                    else:
                        for child in list(a.descendants):
                            if isinstance(child, str) and old_title.lower() in child.lower():
                                child.replace_with(child.replace(old_title, rep["title"]))
                swaps += 1

    # 3. Update image references inside product links
    for a in soup.find_all("a"):
        href = a.get("href", "")
        m = re.search(r'/products/([a-z0-9_-]+)', href, re.IGNORECASE)
        if m:
            handle = m.group(1)
            prod = replacement_map.get(handle)
            if prod:
                img = a.find("img")
                if img:
                    new_src = product_img_url(prod)
                    if new_src:
                        img["src"] = new_src
                    img["alt"] = f"{prod['title']} — shop at MeeeShop"

    return str(soup), swaps


# ── Main article refresh logic ────────────────────────────────────────────────
def refresh_article(blog: dict, article: dict, all_products: list,
                    in_stock: list, out_of_stock_handles: set[str],
                    product_by_handle: dict[str, dict],
                    dry_run: bool = False, no_ai: bool = False,
                    **kwargs) -> dict | None:
    """
    Refresh one article by replacing out-of-stock products with in-stock ones of the same type.
    Does NOT rewrite the article content or change the handle & title.
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

    if not oos_in_article:
        # Run fix_article_images to ensure any existing images are up-to-date
        new_body, swaps = fix_article_images(body, product_by_handle)
        if swaps > 0:
            print(f"  [Fix Images] Fixed {swaps} broken/outdated product images.")
            if dry_run:
                print(f"  [DRY-RUN] would PATCH article {article_id} with fixed images.")
                return {"status": "images_fixed", "swaps": swaps}
            
            payload = {
                "article": {
                    "id": article_id,
                    "body_html": new_body
                }
            }
            r = _req("put", f"{BASE}/blogs/{blog_id}/articles/{article_id}.json", json=payload)
            if r.status_code in (200, 201):
                print(f"  PATCHED  : article {article_id} images updated successfully")
                return {"status": "images_fixed", "swaps": swaps}
            else:
                print(f"  PATCH FAILED {r.status_code}: {r.text[:200]}")
                return None
        else:
            print("  No out-of-stock products or outdated images found. No changes needed.")
            return {"status": "no_changes_needed", "swaps": 0}

    # Build replacement map for out-of-stock handles
    replacement_map: dict[str, dict] = {}
    replacements_log: list[dict] = []
    first_replacement: dict | None = None

    for handle in oos_in_article:
        old_product = product_by_handle.get(handle)
        if not old_product:
            continue
        replacement = find_best_replacement(old_product, in_stock)
        if replacement:
            replacement_map[handle] = replacement
            if first_replacement is None:
                first_replacement = replacement
            replacements_log.append({
                "old_handle": handle,
                "old_title":  old_product["title"],
                "new_handle": replacement["handle"],
                "new_title":  replacement["title"],
            })
            print(f"    Replacing '{old_product['title'][:40]}' → '{replacement['title'][:40]}'")
        else:
            print(f"    No replacement found for '{handle}'")

    if not replacement_map:
        print("  SKIP — No replacements could be determined for out-of-stock products.")
        return None

    # Swap product links and styled card containers in HTML
    new_body, swaps = swap_products_in_html(body, replacement_map, product_by_handle)
    
    # Run image fixes on top of the swapped HTML to ensure images are fresh
    new_body, img_swaps = fix_article_images(new_body, product_by_handle)

    if swaps == 0 and img_swaps == 0:
        print("  No replacements or changes made in HTML. Skipping.")
        return {"status": "no_changes_needed", "swaps": 0}

    print(f"  HTML Swaps made: {swaps} | Image updates: {img_swaps}")

    # ── Dry-run short-circuit ─────────────────────────────────────────────
    if dry_run:
        print(f"  [DRY-RUN] would PATCH article {article_id} with swapped products.")
        return {"replacements": replacements_log, "featured_product": first_replacement["title"]}

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

    # ── PATCH the article (keeps same URL handle, title, author, tags, etc.) ──
    payload = {
        "article": {
            "id":           article_id,
            "body_html":    new_body,
        }
    }

    r = _req("put", f"{BASE}/blogs/{blog_id}/articles/{article_id}.json", json=payload)
    if r.status_code not in (200, 201):
        print(f"  PATCH FAILED {r.status_code}: {r.text[:200]}")
        return None

    print(f"  PATCHED  : article {article_id} updated successfully with in-stock products.")
    return {"replacements": replacements_log, "featured_product": first_replacement["title"]}


# ── Entrypoint ────────────────────────────────────────────────────────────────
def run(limit: int = 5, dry_run: bool = False, article_id: int | None = None,
        force: bool = False, batch_size: int = 20, batch_index: int = 0, no_ai: bool = False,
        fix_images_only: bool = False):
    mode = "force" if force else ("single" if article_id else "batch")
    print(f"\n{'='*64}")
    print(f"  MeeeShop Blog Refresher — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  Mode: {mode} | Limit: {limit} | Dry-run: {dry_run} | No-AI: {no_ai} | Fix Images Only: {fix_images_only}")
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

    # ── Check and update authors for all articles in the store ──────────────────
    print("Checking article authors...")
    articles_to_check = work_items if article_id else all_articles
    for blog, art in articles_to_check:
        cur_author = (art.get("author") or "").strip()
        # If author is empty or generic (and doesn't contain 'meeeshop'), update to a valid E-E-A-T named pen name
        is_generic = not cur_author or any(g in cur_author.lower() for g in ["author", "staff", "writer", "admin"])
        if "meeeshop" not in cur_author.lower() and is_generic:
            new_author = random.choice(PEN_NAMES)
            print(f"  Article '{art.get('title')}' (ID {art.get('id')}) has generic/empty author '{cur_author}'. Updating to E-E-A-T author '{new_author}'...")
            if not dry_run:
                payload = {"article": {"id": art["id"], "author": new_author}}
                r = _req("put", f"{BASE}/blogs/{blog['id']}/articles/{art['id']}.json", json=payload)
                if r.status_code in (200, 201):
                    print("    ✓ Updated successfully.")
                    art["author"] = new_author
                else:
                    print(f"    ✗ Update failed: {r.status_code} {r.text[:200]}")
                time.sleep(1.0)
            else:
                print(f"    [DRY-RUN] Would update author to '{new_author}'.")

    # ── Process each article ──────────────────────────────────────────────────
    updated = skipped = 0
    log = []

    for blog, article in work_items:
        try:
            result = refresh_article(
                blog, article, all_products,
                in_stock, out_of_stock_handles, product_by_handle,
                dry_run=dry_run,
                no_ai=no_ai,
                fix_images_only=fix_images_only,
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
            import traceback
            traceback.print_exc()
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
    ap.add_argument("--no-ai",       action="store_true", help="Perform refresh programmatically without AI calls")
    ap.add_argument("--fix-images-only", action="store_true", help="Only fix broken product images in articles without other modifications")
    args = ap.parse_args()

    run(
        limit=args.limit,
        dry_run=args.dry_run,
        article_id=args.article_id,
        force=args.force,
        batch_size=args.batch_size,
        batch_index=args.batch_index,
        no_ai=args.no_ai,
        fix_images_only=args.fix_images_only,
    )

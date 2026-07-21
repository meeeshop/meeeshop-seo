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

import os, sys, re, time, random, json, argparse, base64
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from io import BytesIO
from bs4 import BeautifulSoup
from PIL import Image, ImageOps

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


def _graphql(query: str, variables: dict = None) -> dict:
    for attempt in range(5):
        try:
            payload = {"query": query}
            if variables:
                payload["variables"] = variables
            r = getattr(requests, "post")(f"{BASE.replace('/api/'+API_VER, '/api/'+API_VER+'/graphql.json')}", headers=HEADERS, json=payload, timeout=45)
            if r.status_code == 429:
                wait = 4
                print(f"    [GraphQL rate-limit] sleeping {wait}s…")
                time.sleep(wait)
                continue
            r.raise_for_status()
            res = r.json()
            if "errors" in res and res["errors"]:
                print("    [GraphQL Errors]:", res["errors"])
                # Sometimes a query has errors but also data, but typically it's bad.
                if attempt == 4: raise RuntimeError(f"GraphQL Errors: {res['errors']}")
            return res
        except requests.exceptions.ConnectionError:
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"GraphQL POST failed after 5 attempts")


# ── Product fetching ──────────────────────────────────────────────────────────
def fetch_all_products() -> list:
    """Fetch all products using GraphQL and map to REST-like dicts."""
    query = """
    query($cursor: String) {
      products(first: 250, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        edges {
          node {
            legacyResourceId title handle productType tags
            variants(first: 10) {
              edges { node { price inventoryQuantity inventoryPolicy } }
            }
            images(first: 10) {
              edges { node { url } }
            }
          }
        }
      }
    }
    """
    products = []
    cursor = None
    while True:
        res = _graphql(query, variables={"cursor": cursor})
        data = res.get("data", {}).get("products", {})
        for edge in data.get("edges", []):
            node = edge["node"]
            variants = [{"price": v["node"]["price"], "inventory_quantity": v["node"]["inventoryQuantity"], "inventory_policy": v["node"]["inventoryPolicy"]} for v in node.get("variants", {}).get("edges", [])]
            images = [{"src": img["node"]["url"]} for img in node.get("images", {}).get("edges", [])]
            products.append({
                "id": int(node["legacyResourceId"]),
                "title": node.get("title"),
                "handle": node.get("handle"),
                "product_type": node.get("productType"),
                "tags": ", ".join(node.get("tags", [])),
                "variants": variants,
                "images": images
            })
        
        page_info = data.get("pageInfo", {})
        if page_info.get("hasNextPage"):
            cursor = page_info.get("endCursor")
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
    query = """
    query {
      blogs(first: 10) {
        edges {
          node {
            id title handle
          }
        }
      }
    }
    """
    res = _graphql(query)
    blogs = []
    for edge in res.get("data", {}).get("blogs", {}).get("edges", []):
        node = edge["node"]
        # Extract numeric ID from gid://shopify/Blog/123
        gid = node["id"]
        num_id = int(gid.split("/")[-1])
        blogs.append({"id": num_id, "title": node.get("title"), "handle": node.get("handle")})
    return blogs


def fetch_articles_for_blog(blog_id: int, limit: int = 50) -> list:
    query = """
    query($id: ID!, $cursor: String, $first: Int) {
      blog(id: $id) {
        articles(first: $first, after: $cursor) {
          pageInfo { hasNextPage endCursor }
          edges {
            node {
              id title handle body tags publishedAt
              image { url }
              author { name }
            }
          }
        }
      }
    }
    """
    articles = []
    cursor = None
    gid = f"gid://shopify/Blog/{blog_id}"
    while len(articles) < limit:
        first = min(50, limit - len(articles))
        res = _graphql(query, variables={"id": gid, "first": first, "cursor": cursor})
        blog_data = res.get("data", {}).get("blog", {})
        if not blog_data: break
        arts_data = blog_data.get("articles", {})
        for edge in arts_data.get("edges", []):
            node = edge["node"]
            num_id = int(node["id"].split("/")[-1])
            author_name = node.get("author", {}).get("name", "") if node.get("author") else ""
            img_dict = {"src": node["image"]["url"]} if node.get("image") else None
            tags_str = ", ".join(node.get("tags", []))
            articles.append({
                "id": num_id,
                "title": node.get("title"),
                "handle": node.get("handle"),
                "body_html": node.get("body", ""),
                "tags": tags_str,
                "published_at": node.get("publishedAt"),
                "author": author_name,
                "image": img_dict,
                "gid": node["id"]
            })
        
        page_info = arts_data.get("pageInfo", {})
        if page_info.get("hasNextPage"):
            cursor = page_info.get("endCursor")
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
    if not imgs:
        return None
    src = imgs[0].get("src", "")
    if not src:
        return None
    if src.startswith("//"):
        src = "https:" + src
    return src


def build_discover_landscape_collage(featured_prod: dict, related_prods: list) -> bytes | None:
    """
    Build a 1200x630 landscape Google Discover eligible 3-panel collage image.
    - 3 images side-by-side: Left (rel #1), Center (Featured), Right (rel #2)
    - Featured product image is CENTERED
    - All 3 product images have identical panel sizes with plain flat borders
    """
    feat_url = product_img_url(featured_prod)
    if not feat_url:
        return None

    rel_urls = [product_img_url(p) for p in related_prods if product_img_url(p)]
    left_url = rel_urls[0] if len(rel_urls) > 0 else feat_url
    center_url = feat_url  # Featured product is CENTERED
    right_url = rel_urls[1] if len(rel_urls) > 1 else (rel_urls[0] if len(rel_urls) > 0 else feat_url)

    urls = [left_url, center_url, right_url]

    CANVAS_W = 1200
    CANVAS_H = 630
    PANEL_W = CANVAS_W // 3  # 400px per panel

    # Plain white background / clean flat borders
    bg = Image.new("RGB", (CANVAS_W, CANVAS_H), (255, 255, 255))

    for i, url in enumerate(urls):
        try:
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            raw = Image.open(BytesIO(r.content)).convert("RGB")
            # Same size for all 3 panels (390x610 inside 400x630 column), plain flat borders
            fitted = ImageOps.fit(raw, (PANEL_W - 10, CANVAS_H - 20), method=Image.Resampling.LANCZOS)
            x_pos = i * PANEL_W + 5
            y_pos = 10
            bg.paste(fitted, (x_pos, y_pos))
        except Exception as exc:
            print(f"  [Collage Warning] Failed to load image {url}: {exc}")

    buf = BytesIO()
    bg.save(buf, format="JPEG", quality=90, optimize=True)
    return buf.getvalue()


def extract_handle_category(handle: str) -> str:
    h = (handle or "").lower().replace("_", "-")
    words = set(re.findall(r'\b[a-z0-9]+\b', h))
    if any(w in words or w in h for w in ["skirt", "skirts"]):
        return "skirt"
    if any(w in words or w in h for w in ["dress", "dresses", "gown", "gowns", "frock"]):
        return "dress"
    if any(w in words or w in h for w in ["jean", "jeans", "denim"]):
        return "jean"
    if any(w in words or w in h for w in ["top", "tops", "blouse", "blouses", "shirt", "shirts", "tee", "tees", "tank", "tanks"]):
        return "top"
    if any(w in words or w in h for w in ["pant", "pants", "trouser", "trousers", "slacks", "leggings"]):
        return "pant"
    if any(w in words or w in h for w in ["jacket", "jackets", "blazer", "blazers", "coat", "coats", "outerwear"]):
        return "jacket"
    if any(w in words or w in h for w in ["sweater", "sweaters", "cardigan", "cardigans", "knitwear"]):
        return "sweater"
    return ""


def find_matching_product_for_handle(handle: str, in_stock: list, exclude_handles: set = None) -> dict | None:
    if not in_stock:
        return None
    exclude = exclude_handles or set()
    cat = extract_handle_category(handle)
    valid_pool = [p for p in in_stock if p.get("handle") not in exclude and product_img_url(p)]
    if not valid_pool:
        valid_pool = [p for p in in_stock if product_img_url(p)]
        if not valid_pool:
            return None

    if cat:
        strict_matches = []
        secondary_matches = []
        for p in valid_pool:
            ptype = (p.get("product_type") or "").lower()
            title = (p.get("title") or "").lower()
            tags  = (p.get("tags") or "").lower()

            # Exclude mismatched item types (e.g., sets/tops/dresses when looking for skirts)
            if cat == "skirt" and ("set" in title or "top" in ptype or "dress" in ptype or "top" in title or "dress" in title):
                continue
            if cat == "dress" and ("skirt" in ptype or "top" in ptype or "pant" in ptype):
                continue
            if cat == "top" and ("skirt" in ptype or "dress" in ptype or "pant" in ptype):
                continue
            if cat == "jean" and ("dress" in ptype or "top" in ptype):
                continue

            if ptype == cat or ptype == f"{cat}s":
                strict_matches.append(p)
            elif cat in title or cat in ptype or cat in tags:
                secondary_matches.append(p)

        if strict_matches:
            return random.choice(strict_matches)
        if secondary_matches:
            return random.choice(secondary_matches)

    return random.choice(valid_pool)


def fix_article_images(html_str: str, product_by_handle: dict[str, dict]) -> tuple[str, int]:
    """
    Parse article body, find any links to products, and ensure all product images
    are present, valid HTTPS URLs, and up-to-date with live Shopify data.
    Returns (updated_html, swap_count).
    """
    if not html_str:
        return html_str, 0

    soup = BeautifulSoup(f"<div>{html_str}</div>", "html.parser")
    root = soup.div
    if not root:
        return html_str, 0
        
    swaps = 0
    # 1. Update existing images inside <a> links pointing to /products/
    for a in root.find_all("a"):
        href = a.get("href", "")
        m = re.search(r'/products/([a-z0-9_-]+)', href, re.IGNORECASE)
        if m:
            handle = m.group(1)
            product = product_by_handle.get(handle)
            if product:
                new_src = product_img_url(product)
                if new_src:
                    img = a.find("img")
                    if img:
                        current_src = img.get("src", "")
                        new_base = new_src.split('?')[0]
                        curr_base = current_src.split('?')[0] if current_src else ""
                        if curr_base != new_base or not current_src.startswith("http"):
                            img["src"] = new_src
                            swaps += 1
                    else:
                        # Skip if parent div or ancestor div ALREADY contains an img
                        parent_div = a.parent
                        has_img = False
                        p = parent_div
                        while p and p.name not in ("body", "html", "[document]"):
                            if p.name == "div" and p.find("img"):
                                has_img = True
                                break
                            p = p.parent
                        if not has_img and parent_div and parent_div.name == "div":
                            raw_title = product.get("title", "")
                            ptype = (product.get("product_type") or "women's fashion").lower()
                            alt = f"{raw_title} — {ptype} for women at MeeeShop".replace('"', "'")
                            url = f"{STORE_URL}/products/{handle}?utm_source=blog&utm_medium=featured_card&utm_campaign=meeeshop_refresh"
                            img_html = f'<a href="{url}"><img src="{new_src}" alt="{alt}" style="width:220px;height:220px;object-fit:cover;border-radius:10px;flex-shrink:0;" loading="lazy" /></a>'
                            new_img_soup = BeautifulSoup(img_html, "html.parser")
                            parent_div.insert(0, new_img_soup)
                            swaps += 1

    # 2. Check all card divs containing product links that lack images
    for div in root.find_all("div"):
        style = (div.get("style", "") or "").replace(" ", "").lower()
        if any(pat in style for pat in ["background:", "border:", "display:flex", "padding:"]):
            # Prevent double image: skip if div or ancestor/descendant div already has an img
            if div.find("img") or div.find_parent(lambda p: p.name == "div" and p.find("img")):
                continue
            a_tag = div.find("a", href=re.compile(r'/products/([a-z0-9_-]+)', re.IGNORECASE))
            if a_tag:
                m = re.search(r'/products/([a-z0-9_-]+)', a_tag.get("href", ""), re.IGNORECASE)
                if m:
                    handle = m.group(1)
                    product = product_by_handle.get(handle)
                    if product:
                        new_src = product_img_url(product)
                        if new_src:
                            raw_title = product.get("title", "")
                            ptype = (product.get("product_type") or "women's fashion").lower()
                            alt = f"{raw_title} — {ptype} for women at MeeeShop".replace('"', "'")
                            url = f"{STORE_URL}/products/{handle}?utm_source=blog&utm_medium=featured_card&utm_campaign=meeeshop_refresh"
                            img_html = f'<a href="{url}"><img src="{new_src}" alt="{alt}" style="width:220px;height:220px;object-fit:cover;border-radius:10px;flex-shrink:0;" loading="lazy" /></a>'
                            new_img_soup = BeautifulSoup(img_html, "html.parser")
                            div.insert(0, new_img_soup)
                            swaps += 1

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
                                  keyword: str = "", handle: str = "") -> str:
    import html
    cat = extract_handle_category(handle or keyword)
    pool = [p for p in products if p.get("handle") != exclude_handle and is_in_stock(p) and product_img_url(p)]

    if cat:
        cat_pool = []
        for p in pool:
            ptype = (p.get("product_type") or "").lower()
            title = (p.get("title") or "").lower()
            tags  = (p.get("tags") or "").lower()

            if cat == "skirt" and ("set" in title or "top" in ptype or "dress" in ptype or "top" in title or "dress" in title):
                continue
            if cat == "dress" and ("skirt" in ptype or "top" in ptype or "pant" in ptype):
                continue
            if cat == "top" and ("skirt" in ptype or "dress" in ptype or "pant" in ptype):
                continue
            if cat == "jean" and ("dress" in ptype or "top" in ptype):
                continue

            if cat in ptype or cat in title or cat in tags:
                cat_pool.append(p)

        if len(cat_pool) >= 3:
            pool = cat_pool
        elif cat_pool:
            pool = cat_pool + [p for p in pool if p not in cat_pool]

    picks = random.sample(pool, min(3, len(pool)))

    cards_html = ""
    for p in picks:
        raw_title  = p["title"]
        escaped_title = html.escape(raw_title)
        price  = p["variants"][0]["price"] if p.get("variants") else "0"
        h_val  = p.get("handle", "")
        ptype  = (p.get("product_type") or "women's fashion").lower()
        url    = f"{STORE_URL}/products/{h_val}?utm_source=blog&utm_medium=related_card&utm_campaign=meeeshop_refresh"
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


def _get_handle_rules(article_handle: str) -> dict:
    """Return handle-specific content rules or dynamically generate a structured blueprint."""
    handle_lower = (article_handle or "").lower()
    for pattern, rules in HANDLE_CONTENT_RULES.items():
        if pattern in handle_lower:
            return rules

    # Dynamic section blueprint for unlisted handles
    topic = article_handle.replace("-", " ").replace("_", " ").title()
    cat = extract_handle_category(article_handle)

    if cat == "skirt":
        sections = [
            "Understanding Skirt Silhouettes & Fit Principles for Curvy Shapes",
            "Top Flattering Skirt Styles You Need (Midi, A-Line, Wrap & Pencil)",
            "How to Style Skirts with Tops, Blazers & Accessories",
            "Common Fit Mistakes & Tailoring Solutions",
            "Stylist Recommended Outfits & Picks"
        ]
        tone = "body-positive, stylish, practical style guide"
    elif cat == "dress":
        sections = [
            "Choosing the Right Dress Silhouette for Your Body",
            "Key Fit & Fabric Features to Look For in 2026",
            "How to Outfit & Layer Your Dress for Any Occasion",
            "Styling & Accessory Tips",
            "Stylist Recommended Outfits & Picks"
        ]
        tone = "chic, effortless, practical fashion guide"
    elif cat == "top":
        sections = [
            "Essential Top Styles & Necklines That Flatter",
            "How to Pair Tops with Jeans, Skirts, and Trousers",
            "The Tuck-In Trick & Proportional Styling",
            "Layering Hacks for Everyday Elegance",
            "Stylist Recommended Outfits & Picks"
        ]
        tone = "versatile, modern, practical style guide"
    elif cat == "jean":
        sections = [
            "Denim Fit Guide & Silhouette Breakthroughs for 2026",
            "High Waist vs Straight vs Wide-Leg: Finding Your Best Match",
            "How to Style Jeans from Office Casual to Weekend Chic",
            "Care & Washing Hacks to Preserve Stretch & Wash",
            "Stylist Recommended Outfits & Picks"
        ]
        tone = "denim expert, practical, trend-conscious"
    else:
        sections = [
            f"Introduction & Essential Guide to {topic}",
            "Key Styling Principles & What to Look For",
            "Complete Outfit Formulas for Everyday & Special Occasions",
            "Common Fashion Mistakes & Pro Stylist Hacks",
            "Final Thoughts & Recommended Store Picks"
        ]
        tone = "expert styling advice, practical, trend-conscious"

    return {
        "topic": topic,
        "required_sections": sections,
        "tone": tone
    }


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


def check_alignment(handle: str, title: str, html_content: str, product_by_handle: dict[str, dict] = None) -> bool:
    if not handle or not html_content:
        return True
    raw_words = handle.replace('-', ' ').replace('_', ' ').split()
    stop_words = {"how", "to", "the", "a", "an", "is", "for", "with", "what", "where", "why", "on", "in", "of", "and", "or", "you", "need", "your", "best", "most"}
    significant_words = [w.lower() for w in raw_words if w.lower() not in stop_words and len(w) > 2]
    if not significant_words:
        return True
    
    # 1. Check if the Title aligns with the handle
    title_text = title.lower()
    found_in_title = sum(1 for word in significant_words if word in title_text)
    if (found_in_title / len(significant_words)) < 0.4:
        return False
    
    # 2. Check if the Body aligns with the handle
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html_content, "html.parser")
    body_text = soup.get_text().lower()
    body_words = set(re.findall(r'\b\w+\b', body_text))
    
    found_in_body = sum(1 for word in significant_words if word in body_words)
    if (found_in_body / len(significant_words)) < 0.5:
        return False

    # 3. Check Product Category alignment
    cat = extract_handle_category(handle)
    if cat and product_by_handle:
        handles_in_body = extract_product_handles(html_content)
        if handles_in_body:
            matched_cat = False
            for h in handles_in_body:
                prod = product_by_handle.get(h)
                if prod:
                    ptype = (prod.get("product_type") or "").lower()
                    pname = (prod.get("title") or "").lower()
                    ptags = (prod.get("tags") or "").lower()
                    if cat in ptype or cat in pname or cat in ptags:
                        matched_cat = True
                        break
            if not matched_cat:
                print(f"  [Alignment Check] Handle category '{cat}' does NOT match referenced products in body.")
                return False
                
    return True

# ── Main article refresh logic ────────────────────────────────────────────────
def refresh_article(blog: dict, article: dict, all_products: list,
                    in_stock: list, out_of_stock_handles: set[str],
                    product_by_handle: dict[str, dict],
                    dry_run: bool = False, no_ai: bool = False,
                    fix_images_only: bool = False, force: bool = False,
                    is_single_article: bool = False,
                    **kwargs) -> dict | None:
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

    # ── 2. Handle Fix Images Only mode ────────────────────────────────────────
    if fix_images_only:
        new_body, swaps = fix_article_images(body, product_by_handle)
        replacement_map = {}
        for h in oos_in_article:
            old_prod = product_by_handle.get(h)
            if old_prod:
                rep = find_matching_product_for_handle(art_handle, in_stock)
                if rep:
                    replacement_map[h] = rep
        if replacement_map:
            new_body, oos_swaps = swap_products_in_html(new_body, replacement_map, product_by_handle)
            swaps += oos_swaps

        if swaps == 0 and not is_single_article and not force:
            print("  [Fix Images Only] No images or out-of-stock links needed fixing.")
            return {"status": "no_changes_needed", "swaps": 0}

        print(f"  [Fix Images Only] Updated {swaps} product images / links.")
        return {
            "status": "images_fixed",
            "gid": article.get("gid", f"gid://shopify/Article/{article_id}"),
            "title": art_title,
            "body_html": new_body,
            "replacements": [],
            "featured_product": None
        }

    # ── 3. Find out-of-stock replacements or category-aligned product ─────────
    replacement_map: dict[str, dict] = {}
    replacements_log: list[dict] = []
    first_replacement: dict | None = None

    for handle in oos_in_article:
        old_product = product_by_handle.get(handle)
        if not old_product:
            continue
        replacement = find_best_replacement(old_product, in_stock) or find_matching_product_for_handle(art_handle, in_stock)
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

    # Swap product links & styled cards in HTML
    new_body, swaps = swap_products_in_html(body, replacement_map, product_by_handle)
    new_body, img_swaps = fix_article_images(new_body, product_by_handle)

    # ── 4. Check alignment & product category ─────────────────────────────────
    aligned = check_alignment(art_handle, art_title, new_body, product_by_handle)
    has_products = len(extract_product_handles(new_body)) > 0
    needs_rewrite = not aligned or not has_products or force or is_single_article

    if not needs_rewrite and swaps == 0 and img_swaps == 0:
        print("  Article content is aligned and images are up to date. No changes needed.")
        return {"status": "no_changes_needed", "swaps": 0}

    print(f"  HTML Swaps: {swaps} | Image updates: {img_swaps} | Needs Rewrite: {needs_rewrite}")

    # Determine featured product matching the handle category
    featured = first_replacement
    if not featured:
        # Check if existing referenced products match category
        cat = extract_handle_category(art_handle)
        for h in extract_product_handles(new_body):
            p = product_by_handle.get(h)
            if p and is_in_stock(p) and product_img_url(p):
                if not cat or cat in (p.get("product_type") or "").lower() or cat in (p.get("title") or "").lower():
                    featured = p
                    break
    if not featured:
        featured = find_matching_product_for_handle(art_handle, in_stock)

    if not featured:
        print("  ERROR: No suitable in-stock featured product found.")
        return None

    # ── 5. Rewrite content if needed ──────────────────────────────────────────
    payload_title = art_title
    seo_meta = None

    if needs_rewrite:
        keyword = art_handle.replace("-", " ")
        if not no_ai:
            print(f"  [Rewrite] Rewriting article for handle '{art_handle}' using featured product '{featured['title'][:40]}'")
            cleaned_context = clean_article_body_html(new_body)
            prompt = _build_refresh_prompt(art_title, featured, keyword, cleaned_context, art_handle)
            prompt += (
                f"\nCRITICAL INSTRUCTION: The article MUST focus strictly on '{art_handle.replace('-', ' ')}'. "
                f"Use featured product '{featured['title']}' (${featured['variants'][0]['price'] if featured.get('variants') else '49'}) "
                f"as the primary recommended pick. Do NOT include HTML links inside the article prose."
            )
            
            import ai_client
            ai_html = ai_client.generate(prompt, max_tokens=1600, temperature=0.7)
            
            if ai_html:
                parsed_body = _clean_html(ai_html)
                seo_meta = parse_and_clean_seo_meta(ai_html, keyword, featured["title"], featured.get("product_type", ""))
                # Inject product card & related products widget matching handle category
                card_html = make_product_card(featured, keyword=keyword)
                related_html = make_related_products_section(in_stock, featured["handle"], keyword=keyword, handle=art_handle)
                new_body = f"{card_html}\n{parsed_body}\n{related_html}"
                print("  [Rewrite] AI rewrite completed successfully with product card and related section.")
            else:
                print("  [AI Fallback] AI generation returned empty, using programmatic fallback...")
                from blog_daily import generate_fallback_blog_post
                fmt = random.choice(["sizing_guide", "outfit_formula", "buying_guide", "comparison"])
                fb_html, seo_meta = generate_fallback_blog_post(fmt, featured, keyword, art_title, in_stock, in_stock)
                new_body = _clean_html(fb_html)
        else:
            print(f"  [No-AI Refresh] Updating product card and images programmatically...")
            cleaned_context = clean_article_body_html(new_body)
            card_html = make_product_card(featured, keyword=art_handle.replace("-", " "))
            related_html = make_related_products_section(in_stock, featured["handle"], keyword=art_handle.replace("-", " "), handle=art_handle)
            new_body = f"{card_html}\n{cleaned_context}\n{related_html}"

    if dry_run:
        print(f"  [DRY-RUN] Would PATCH article {article_id} with updated body HTML.")
        return {"status": "updated", "replacements": replacements_log, "featured_product": featured["title"]}

    # Backup original article content
    backup_data = {
        "article_id": article_id,
        "title": art_title,
        "handle": art_handle,
        "body_html": body,
        "backup_timestamp": datetime.now().isoformat()
    }
    backup_dir = ROOT / "backup_articles"
    backup_dir.mkdir(exist_ok=True)
    backup_file = backup_dir / f"article_{article_id}_{int(time.time())}.json"
    backup_file.write_text(json.dumps(backup_data, indent=2, ensure_ascii=False), encoding="utf-8")

    # Generate 1200px Discover landscape 3-panel collage (Featured centered)
    b64_collage = None
    if featured:
        cat_rel_picks = [p for p in in_stock if p.get("handle") != featured["handle"] and product_img_url(p)]
        cat = extract_handle_category(art_handle)
        if cat:
            filtered_rel = [p for p in cat_rel_picks if cat in (p.get("product_type") or "").lower() or cat in (p.get("title") or "").lower()]
            if len(filtered_rel) >= 2:
                cat_rel_picks = filtered_rel
        collage_bytes = build_discover_landscape_collage(featured, cat_rel_picks)
        if collage_bytes:
            b64_collage = base64.b64encode(collage_bytes).decode("utf-8")

    ret = {
        "status": "updated",
        "blog_id": blog_id,
        "gid": article.get("gid", f"gid://shopify/Article/{article_id}"),
        "title": payload_title,
        "body_html": new_body,
        "replacements": replacements_log,
        "featured_product": featured["title"],
        "featured_img_url": product_img_url(featured),
        "b64_collage": b64_collage
    }
    if seo_meta:
        ret["seo_title"] = seo_meta["seo_title"]
        ret["meta_desc"] = seo_meta["meta_desc"]

    return ret


# ── Entrypoint ────────────────────────────────────────────────────────────────

def _execute_article_batch(batch: list):
    if not batch: return

    var_defs = []
    variables = {}
    mutations = []

    for i, payload in enumerate(batch):
        var_defs.append(f"$artTitle_{i}: String!")
        var_defs.append(f"$body_{i}: HTML!")
        variables[f"artTitle_{i}"] = payload.get("title")
        variables[f"body_{i}"] = payload["body_html"]

        metafields_input = ""
        if payload.get("seo_title") and payload.get("meta_desc"):
            var_defs.append(f"$title_{i}: String!")
            var_defs.append(f"$desc_{i}: String!")
            variables[f"title_{i}"] = payload["seo_title"]
            variables[f"desc_{i}"] = payload["meta_desc"]
            metafields_input = (
                f', metafields: ['
                f'{{namespace: "global", key: "title_tag", type: "single_line_text_field", value: $title_{i}}}, '
                f'{{namespace: "global", key: "description_tag", type: "single_line_text_field", value: $desc_{i}}}'
                f']'
            )

        mutations.append(
            f'  m{i}: articleUpdate(id: "{payload["gid"]}", article: {{title: $artTitle_{i}, body: $body_{i}{metafields_input}}}) {{ userErrors {{ field message }} }}'
        )

    query_str = f"mutation({', '.join(var_defs)}) {{\n" + "\n".join(mutations) + "\n}"

    res = _graphql(query_str, variables=variables)
    data = res.get("data", {})
    for i, payload in enumerate(batch):
        errs = data.get(f"m{i}", {}).get("userErrors", [])
        if errs:
            print(f"  [GraphQL Error] article {payload['gid']}: {errs}")
        else:
            print(f"  ✓ Batch Updated article {payload['gid']}")
            if payload.get("b64_collage"):
                gid_num = payload["gid"].split("/")[-1]
                blog_num = payload.get("blog_id")
                if blog_num:
                    url = f"{BASE}/blogs/{blog_num}/articles/{gid_num}.json"
                    img_payload = {
                        "article": {
                            "id": int(gid_num),
                            "image": {
                                "attachment": payload["b64_collage"],
                                "filename": f"discover_collage_{gid_num}.jpg"
                            }
                        }
                    }
                    _req("put", url, json=img_payload)
                    print(f"    ✓ Uploaded 1200px Discover landscape 3-panel collage header image to Shopify article {gid_num}")


def _execute_author_batch(batch: list):
    if not batch: return

    var_defs = []
    variables = {}
    mutations = []

    for i, payload in enumerate(batch):
        var_defs.append(f"$author_{i}: String!")
        variables[f"author_{i}"] = payload["author"]
        mutations.append(
            f'  m{i}: articleUpdate(id: "{payload["gid"]}", article: {{author: $author_{i}}}) {{ userErrors {{ field message }} }}'
        )

    query_str = f"mutation({', '.join(var_defs)}) {{\n" + "\n".join(mutations) + "\n}"

    res = _graphql(query_str, variables=variables)
    data = res.get("data", {})
    for i, payload in enumerate(batch):
        errs = data.get(f"m{i}", {}).get("userErrors", [])
        if errs:
            print(f"  [GraphQL Error] author update {payload['gid']}: {errs}")
        else:
            print(f"    ✓ Updated author {payload['gid']} to {payload['author']}")


def run(limit: int = 0, dry_run: bool = False, article_id: int | None = None,
        force: bool = False, batch_size: int = 20, batch_index: int = 0, no_ai: bool = False,
        fix_images_only: bool = False):
    is_single_article = bool(article_id)
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
            work_items = all_articles if limit <= 0 else all_articles[:limit]

    print(f"Articles to refresh: {len(work_items)}\n")

    # ── Check and update authors for all articles in the store ──────────────────
    if not no_ai:
        print("Checking article authors...")
        articles_to_check = work_items if article_id else all_articles
        author_batch = []
        for blog, art in articles_to_check:
            cur_author = (art.get("author") or "").strip()
            # If author doesn't contain 'meeeshop', update to a valid E-E-A-T named pen name
            if "meeeshop" not in cur_author.lower():
                new_author = random.choice(PEN_NAMES)
                print(f"  Article '{art.get('title')}' (ID {art.get('id')}) has author '{cur_author}' missing 'MeeeShop'. Updating to E-E-A-T author '{new_author}'...")
                if not dry_run:
                    author_batch.append({"gid": art.get("gid", f"gid://shopify/Article/{art['id']}"), "author": new_author})
                    art["author"] = new_author
                    if len(author_batch) >= 10:
                        _execute_author_batch(author_batch)
                        author_batch = []
                else:
                    print(f"    [DRY-RUN] Would update author to '{new_author}'.")

        if author_batch:
            _execute_author_batch(author_batch)

    # ── Process each article ──────────────────────────────────────────────────
    updated = skipped = 0
    log = []
    article_batch = []

    for blog, article in work_items:
        try:
            result = refresh_article(
                blog, article, all_products,
                in_stock, out_of_stock_handles, product_by_handle,
                dry_run=dry_run,
                no_ai=no_ai,
                fix_images_only=fix_images_only, force=force,
                is_single_article=is_single_article,
            )
            if result and result.get("status") in ("updated", "images_fixed"):
                if not dry_run:
                    article_batch.append(result)
                    if len(article_batch) >= 5:
                        _execute_article_batch(article_batch)
                        article_batch = []
                        
                updated += 1
                log.append({"id": article["id"], "title": article["title"],
                             "status": "updated", "dry_run": dry_run,
                             "replacements": result.get("replacements", []),
                             "featured_product": result.get("featured_product")})
            elif result and result.get("status") == "no_changes_needed":
                skipped += 1
                log.append({"id": article["id"], "title": article["title"],
                             "status": "skipped"})
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

    if article_batch and not dry_run:
        _execute_article_batch(article_batch)

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
    ap.add_argument("--limit",       type=int, default=0,  help="Max articles per run (default 0 for all; ignored in --force)")
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

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
from utils import is_product_compatible, select_styling_matches
ROOT = Path(__file__).resolve().parent.parent

from eeat_constants import PEN_NAMES, needs_author_update

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
    ptype = (out_product.get("product_type") or "").strip().lower()
    out_handle = out_product.get("handle")
    # Same type with image, different product
    if ptype:
        same = [
            p for p in in_stock 
            if (p.get("product_type") or "").strip().lower() == ptype 
            and p.get("images") 
            and p.get("handle") != out_handle
        ]
        if same:
            return random.choice(same)

    # Fallback to category derived from out_product (product_type, title, or handle)
    text_for_cat = ptype or out_product.get("title", "") or out_product.get("handle", "")
    cat = extract_handle_category(text_for_cat)
    if cat:
        same_cat = [
            p for p in in_stock
            if (cat in (p.get("product_type") or "").lower() or cat in (p.get("title") or "").lower() or cat in (p.get("tags") or "").lower())
            and p.get("images") and p.get("handle") != out_handle
        ]
        if same_cat:
            return random.choice(same_cat)

    valid = [p for p in in_stock if p.get("images") and p.get("handle") != out_handle]
    return random.choice(valid) if valid else None


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


def fetch_article_by_id(article_id: int) -> tuple[dict, dict] | None:
    """Directly fetch an article by Shopify article ID using GraphQL node query."""
    query = """
    query($id: ID!) {
      node(id: $id) {
        ... on Article {
          id title handle body tags publishedAt
          image { url }
          author { name }
          blog { id title handle }
        }
      }
    }
    """
    gid = f"gid://shopify/Article/{article_id}"
    res = _graphql(query, variables={"id": gid})
    node = res.get("data", {}).get("node")
    if node and isinstance(node, dict) and "title" in node:
        num_id = int(node["id"].split("/")[-1])
        blog_node = node.get("blog", {})
        blog_id = int(blog_node["id"].split("/")[-1]) if blog_node.get("id") else 0
        blog = {"id": blog_id, "title": blog_node.get("title", ""), "handle": blog_node.get("handle", "")}
        author_name = node.get("author", {}).get("name", "") if node.get("author") else ""
        img_dict = {"src": node["image"]["url"]} if node.get("image") else None
        tags_str = ", ".join(node.get("tags", []))
        art = {
            "id": num_id,
            "title": node.get("title"),
            "handle": node.get("handle"),
            "body_html": node.get("body", ""),
            "tags": tags_str,
            "published_at": node.get("publishedAt"),
            "author": author_name,
            "image": img_dict,
            "gid": node["id"]
        }
        return blog, art
    return None


# ── Redirect mapping & link updating ──────────────────────────────────────────
SLUG_MAP = {
    # Blogs
    '/blogs/dresses': '/blogs/dresses-style-guide',
    '/blogs/jeans': '/blogs/jeans-style-guide',
    '/blogs/coats-jackets': '/blogs/coats-jackets-style-guide',
    '/blogs/coats': '/blogs/coats-jackets-style-guide',
    '/blogs/cardigans-sweaters': '/blogs/cardigans-sweaters-style-guide',
    '/blogs/sweaters': '/blogs/cardigans-sweaters-style-guide',
    '/blogs/womens-pants': '/blogs/womens-pants-style-guide',
    '/blogs/pants': '/blogs/womens-pants-style-guide',
    '/blogs/womens-shirts-tops': '/blogs/womens-shirts-tops-style-guide',
    '/blogs/shirts': '/blogs/womens-shirts-tops-style-guide',
    '/blogs/tops': '/blogs/womens-shirts-tops-style-guide',
    '/blogs/womens-skirts': '/blogs/womens-skirts-style-guide',
    '/blogs/skirts': '/blogs/womens-skirts-style-guide',
    
    # Collections
    '/collections/dresses': '/collections/womens-dresses',
    '/collections/casual-dresses': '/collections/womens-casual-dresses',
    '/collections/formal-evening-dresses': '/collections/womens-formal-evening-dresses',
    '/collections/maxi-dresses': '/collections/womens-maxi-dresses',
    '/collections/new-collection': '/collections/womens-new-collection',
    '/collections/jeans': '/collections/womens-jeans',
    '/collections/pants': '/collections/womens-pants-leggings',
    '/collections/leggings': '/collections/womens-pants-leggings',
    '/collections/tops': '/collections/womens-tops',
    '/collections/shirts': '/collections/womens-shirts',
    '/collections/sweaters': '/collections/womens-sweaters',
    '/collections/cardigans': '/collections/womens-cardigans',
    '/collections/coats-jackets': '/collections/womens-coats-jackets',
    '/collections/outerwear': '/collections/womens-outerwear',
    '/collections/shorts': '/collections/womens-shorts',
    '/collections/skirts': '/collections/womens-skirts',
    '/collections/shoes': '/collections/womens-shoes',
    '/collections/bottoms': '/collections/womens-bottoms',
    '/collections/activewear': '/collections/womens-activewear',
    '/collections/rompers': '/collections/womens-rompers',
    '/collections/jumpsuits-sets': '/collections/womens-rompers-jumpsuit-sets',
    '/collections/luxe-apparel': '/collections/womens-luxe-apparel',
    '/collections/graphic-tees': '/collections/womens-graphic-tees',
    '/collections/camis-tanks': '/collections/womens-camis-tanks-tops'
}

def fetch_all_redirects() -> dict[str, str]:
    """Fetch active store redirects from Shopify REST API and merge with canonical SLUG_MAP."""
    redirect_map = {k.lower(): v for k, v in SLUG_MAP.items()}
    try:
        url = f"{BASE}/redirects.json?limit=250"
        while url:
            r = _req("get", url)
            if r.status_code != 200:
                break
            data = r.json()
            for item in data.get("redirects", []):
                src = (item.get("path") or "").strip().lower().rstrip("/")
                target = (item.get("target") or "").strip().rstrip("/")
                if src and target:
                    redirect_map[src] = target
            link_hdr = r.headers.get("Link")
            url = None
            if link_hdr:
                for link in link_hdr.split(","):
                    if 'rel="next"' in link:
                        url = link.split(";")[0].strip("<> ")
    except Exception as exc:
        print(f"  [Warning] Failed to fetch live redirects: {exc}")

    final_map = {}
    for src, target in redirect_map.items():
        curr = target
        visited = {src, target.lower()}
        while curr.lower() in redirect_map:
            nxt = redirect_map[curr.lower()]
            if nxt.lower() in visited:
                break
            visited.add(nxt.lower())
            curr = nxt
        final_map[src] = curr

    return final_map


def fix_redirected_internal_links(html_str: str, redirect_map: dict[str, str]) -> tuple[str, int]:
    """Scan HTML for internal links (blogs, collections, products) and update redirected hrefs."""
    if not html_str or not redirect_map:
        return html_str, 0
    
    soup = BeautifulSoup(f"<div>{html_str}</div>", "html.parser")
    root = soup.div
    if not root:
        return html_str, 0

    swaps = 0
    for a in root.find_all("a"):
        href = a.get("href", "").strip()
        if not href:
            continue
        
        pathname = href
        if "meeeshop.com" in href.lower():
            m = re.search(r'https?://(?:us\.)?meeeshop\.com(/[^?\s#]*)', href, re.IGNORECASE)
            if m:
                pathname = m.group(1)
        elif href.startswith("/"):
            pathname = href.split("?")[0].split("#")[0]
        else:
            continue

        clean_path = pathname.lower().rstrip("/")
        if clean_path in redirect_map:
            new_target = redirect_map[clean_path]
            if "meeeshop.com" in href.lower():
                if new_target.startswith("http"):
                    new_href = new_target
                else:
                    new_href = f"{STORE_URL}{new_target}"
            else:
                new_href = new_target
            
            if "?" in href and "?" not in new_href:
                query = href.split("?", 1)[1]
                new_href = f"{new_href}?{query}"

            if href != new_href:
                a["href"] = new_href
                swaps += 1

    res = "".join(str(c) for c in root.contents)
    return res.strip(), swaps


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
    - Center image (Featured product): TALLER (380x600 tile) with a clean solid white/cream border.
    - Side images (Left & Right related products): SHORTER (360x500 tile), vertically centered.
    - Plain cream/white background (#f8f6f3).
    """
    feat_url = product_img_url(featured_prod)
    if not feat_url:
        return None

    rel_urls = [product_img_url(p) for p in related_prods if product_img_url(p)]
    left_url = rel_urls[0] if len(rel_urls) > 0 else feat_url
    right_url = rel_urls[1] if len(rel_urls) > 1 else (rel_urls[0] if len(rel_urls) > 0 else feat_url)

    CANVAS_W = 1200
    CANVAS_H = 630

    BG_COLOR = (248, 246, 243)     # #f8f6f3 cream background
    BORDER_COLOR = (255, 255, 255) # white border around center featured image

    bg = Image.new("RGB", (CANVAS_W, CANVAS_H), BG_COLOR)

    # 1. Left image (Shorter - 360x500)
    try:
        r = requests.get(left_url, timeout=15)
        r.raise_for_status()
        raw = Image.open(BytesIO(r.content)).convert("RGB")
        fitted_left = ImageOps.fit(raw, (360, 500), method=Image.Resampling.LANCZOS)
        bg.paste(fitted_left, (20, (CANVAS_H - 500) // 2))
    except Exception as exc:
        print(f"  [Collage Warning] Failed to load left image {left_url}: {exc}")

    # 2. Right image (Shorter - 360x500)
    try:
        r = requests.get(right_url, timeout=15)
        r.raise_for_status()
        raw = Image.open(BytesIO(r.content)).convert("RGB")
        fitted_right = ImageOps.fit(raw, (360, 500), method=Image.Resampling.LANCZOS)
        bg.paste(fitted_right, (820, (CANVAS_H - 500) // 2))
    except Exception as exc:
        print(f"  [Collage Warning] Failed to load right image {right_url}: {exc}")

    # 3. Center featured image (TALLER - 380x600 with white/cream border)
    try:
        r = requests.get(feat_url, timeout=15)
        r.raise_for_status()
        raw = Image.open(BytesIO(r.content)).convert("RGB")
        
        # Fit inner image into 368x588 tile
        feat_img = ImageOps.fit(raw, (368, 588), method=Image.Resampling.LANCZOS)
        
        # Add 6px solid white border around featured image (total tile 380x600)
        bordered_feat = ImageOps.expand(feat_img, border=6, fill=BORDER_COLOR)
        
        # Paste centered in center column
        bg.paste(bordered_feat, (410, (CANVAS_H - 600) // 2))
    except Exception as exc:
        print(f"  [Collage Warning] Failed to load featured image {feat_url}: {exc}")

    buf = BytesIO()
    bg.save(buf, format="JPEG", quality=92, optimize=True)
    return buf.getvalue()


def extract_handle_count(handle: str) -> int:
    """Extract item/outfit count from handle if specified (e.g., '5-stunning-outfits' -> 5). Default is 3."""
    m = re.search(r'\b(\d+)\b', handle or "")
    if m:
        num = int(m.group(1))
        if 2 <= num <= 10:
            return num
    return 3


def extract_handle_keywords(handle: str) -> list[str]:
    """Extract key material, style, and garment keywords from handle."""
    h = (handle or "").lower().replace("_", "-")
    tokens = set(re.findall(r'\b[a-z0-9]+\b', h))
    keywords = []
    modifiers = ["denim", "linen", "lace", "leather", "silk", "cotton", "knit", 
                 "off-shoulder", "puff", "sleeves", "smocked", "midi", "maxi", "mini", 
                 "wrap", "a-line", "curvy", "plus-size", "summer", "work"]
    for mod in modifiers:
        if mod in tokens or mod in h:
            keywords.append(mod)
    cat = extract_handle_category(handle)
    if cat and cat not in keywords:
        keywords.append(cat)
    return keywords


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
    valid_pool = [p for p in in_stock if p.get("handle") not in exclude and product_img_url(p)]
    if not valid_pool:
        valid_pool = [p for p in in_stock if product_img_url(p)]
        if not valid_pool:
            return None

    cat = extract_handle_category(handle)
    keywords = extract_handle_keywords(handle)

    scored = []
    for p in valid_pool:
        ptype = (p.get("product_type") or "").lower()
        title = (p.get("title") or "").lower()
        tags  = (p.get("tags") or "").lower()
        text  = f"{ptype} {title} {tags}"

        score = 0
        for kw in keywords:
            if kw in text:
                score += 3 if (kw in ptype or kw in title) else 1

        # Additional bonus for exact multi-keyword combinations (e.g. denim + dress)
        if "denim" in keywords and "dress" in keywords and "denim" in text and "dress" in text:
            score += 10

        # Mismatch penalties
        if cat == "skirt" and ("set" in title or "top" in ptype or "dress" in ptype or "top" in title or "dress" in title):
            score -= 15
        if cat == "dress" and ("skirt" in ptype or "top" in ptype or "pant" in ptype):
            score -= 15
        if cat == "top" and ("skirt" in ptype or "dress" in ptype or "pant" in ptype):
            score -= 15
        if cat == "jean" and ("dress" in ptype or "top" in ptype):
            score -= 15

        if score > 0:
            scored.append((score, p))

    if scored:
        scored.sort(key=lambda x: x[0], reverse=True)
        top_score = scored[0][0]
        top_candidates = [p for s, p in scored if s == top_score]
        return random.choice(top_candidates)

    return random.choice(valid_pool)


def fix_article_images(html_str: str, product_by_handle: dict[str, dict], in_stock: list = None) -> tuple[str, int]:
    """
    Parse article body, find any links to products, and ensure all product images
    are present, valid HTTPS URLs, and up-to-date with live Shopify data.
    Also repair broken or missing standalone <img> tags.
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

    # 3. Check for broken or missing general <img> tags in the body
    if in_stock:
        for img in root.find_all("img"):
            src = (img.get("src") or "").strip()
            if not src or src in ("undefined", "null", "#") or not src.startswith("http"):
                repl_prod = random.choice(in_stock)
                repl_src = product_img_url(repl_prod)
                if repl_src:
                    img["src"] = repl_src
                    if not img.get("alt"):
                        img["alt"] = repl_prod.get("title", "MeeeShop fashion item")
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


def make_related_product_card(p: dict, keyword: str = "") -> str:
    import html
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
    return f"""
  <div style="flex:1;min-width:180px;max-width:240px;font-family:sans-serif;text-align:center;">
    {img_tag}
    <p style="font-size:14px;font-weight:700;color:#1a1a1a;margin:0 0 4px;line-height:1.3;">{escaped_title}</p>
    <p style="font-size:16px;font-weight:800;color:#1a1a1a;margin:0 0 12px;">${price}</p>
    <a href="{url}"
       style="background:#f0ede8;color:#1a1a1a;padding:9px 20px;text-decoration:none;
              border-radius:6px;font-size:13px;font-weight:600;display:inline-block;">
      Shop Similar
    </a>
  </div>"""

def make_related_products_section(products: list, exclude_handle: str,
                                  keyword: str = "", handle: str = "") -> str:
    import html
    count = extract_handle_count(handle or keyword)
    cat = extract_handle_category(handle or keyword)
    keywords = extract_handle_keywords(handle or keyword)

    main_prod_matches = [p for p in products if p.get("handle") == exclude_handle]
    main_product = main_prod_matches[0] if main_prod_matches else {"handle": exclude_handle, "product_type": cat or keyword}

    pool = [p for p in products if p.get("handle") != exclude_handle and is_in_stock(p) and product_img_url(p) and is_product_compatible(main_product, p, topic_context=handle or keyword)]

    # Score candidates based on keyword relevance
    scored = []
    for p in pool:
        ptype = (p.get("product_type") or "").lower()
        title = (p.get("title") or "").lower()
        tags  = (p.get("tags") or "").lower()
        text  = f"{ptype} {title} {tags}"

        score = 0
        for kw in keywords:
            if kw in text:
                score += 3 if (kw in ptype or kw in title) else 1

        if "denim" in keywords and "dress" in keywords and "denim" in text and "dress" in text:
            score += 10

        if cat == "skirt" and ("set" in title or "top" in ptype or "dress" in ptype or "top" in title or "dress" in title):
            score -= 15
        if cat == "dress" and ("skirt" in ptype or "top" in ptype or "pant" in ptype):
            score -= 15

        if score > 0:
            scored.append((score, p))

    scored.sort(key=lambda x: x[0], reverse=True)
    high_picks = [p for s, p in scored[:count * 2]]

    if len(high_picks) >= count:
        picks = random.sample(high_picks, count)
    else:
        remaining_needed = count - len(high_picks)
        rest = [p for p in pool if p not in high_picks and is_product_compatible(main_product, p, topic_context=handle or keyword)]
        picks = high_picks + random.sample(rest, min(remaining_needed, len(rest)))

    cards_html = ""
    for p in picks:
        cards_html += make_related_product_card(p, keyword=keyword)

    if not cards_html:
        return ""

    return f"""
<div style="margin:48px 0;padding:32px;background:#fafafa;border-radius:14px;border:1px solid #eee;">
  <h2 style="font-size:20px;font-weight:700;color:#1a1a1a;margin:0 0 24px;text-align:center;">
    Shop The Look — {count} Featured Picks
  </h2>
  <div style="display:flex;flex-wrap:wrap;gap:20px;justify-content:center;">
    {cards_html}
  </div>
</div>
"""


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

    # 2. Keep internal links intact (redirects will be updated by fix_redirected_internal_links)
    pass

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
    replaced_containers = set()
    for a in soup.find_all("a"):
        href = a.get("href", "")
        m = re.search(r'/products/([a-z0-9_-]+)', href, re.IGNORECASE)
        if m:
            handle = m.group(1)
            if handle in replacement_map:
                rep = replacement_map[handle]
                
                # Check for styled product card container
                card_container = None
                card_type = None
                parent = a.parent
                while parent and parent.name not in ("body", "html", "[document]"):
                    style = parent.get("style", "") or ""
                    style_clean = style.replace(" ", "").lower()
                    if "background:#f8f6f3" in style_clean: # main product card
                        card_container = parent
                        card_type = "main"
                        break
                    elif "flex:1" in style_clean and ("min-width:180px" in style_clean or "max-width:240px" in style_clean or "max-width:220px" in style_clean):
                        card_container = parent
                        card_type = "related"
                        break
                    parent = parent.parent
                
                if card_container:
                    if id(card_container) in replaced_containers:
                        continue
                    replaced_containers.add(id(card_container))
                    
                    if card_type == "main":
                        new_card_html = make_product_card(rep)
                    else:
                        new_card_html = make_related_product_card(rep)
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
                    redirect_map: dict[str, str] = None,
                    dry_run: bool = False,
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
    
    def needs_replacement(handle):
        if handle in out_of_stock_handles:
            return True
        prod = product_by_handle.get(handle)
        # Replace if product is completely deleted from store
        if not prod:
            return True
        # Replace if product is in stock but has no image
        if not product_img_url(prod):
            return True
        return False
        
    oos_in_article = {h for h in referenced if needs_replacement(h)}
    print(f"  Products referenced: {len(referenced)} | out-of-stock/missing-image: {len(oos_in_article)}")

    # ── 3. Find out-of-stock replacements matching same product type ──────────
    replacement_map: dict[str, dict] = {}
    replacements_log: list[dict] = []
    first_replacement: dict | None = None

    for handle in oos_in_article:
        old_product = product_by_handle.get(handle)
        replacement = find_best_replacement(old_product or {"handle": handle}, in_stock)
        if replacement:
            replacement_map[handle] = replacement
            if first_replacement is None:
                first_replacement = replacement
            replacements_log.append({
                "old_handle": handle,
                "old_title":  old_product["title"] if old_product else handle,
                "new_handle": replacement["handle"],
                "new_title":  replacement["title"],
            })
            print(f"    Replacing '{old_product['title'][:40] if old_product else handle}' → '{replacement['title'][:40]}'")

    # Swap product links, images, and redirected internal links in HTML
    new_body, swaps = swap_products_in_html(body, replacement_map, product_by_handle)
    new_body, img_swaps = fix_article_images(new_body, product_by_handle, in_stock)
    new_body, redirect_swaps = fix_redirected_internal_links(new_body, redirect_map or {})

    total_swaps = swaps + img_swaps + redirect_swaps

    if total_swaps == 0:
        print("  Article content is aligned, images are up to date, and internal links are canonical. No changes needed.")
        return {"status": "no_changes_needed", "swaps": 0}

    print(f"  HTML Swaps: {swaps} | Image updates: {img_swaps} | Redirect updates: {redirect_swaps}")

    if dry_run:
        print(f"  [DRY-RUN] Would PATCH article {article_id} with updated body HTML.")
        return {"status": "updated", "replacements": replacements_log, "featured_product": None}

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

    # Perform update via GraphQL
    mut_query = """
    mutation blogArticleUpdate($id: ID!, $article: ArticleUpdateInput!) {
      blogArticleUpdate(id: $id, article: $article) {
        article { id handle title }
        userErrors { field message }
      }
    }
    """
    vars = {
        "id": article.get("gid", f"gid://shopify/Article/{article_id}"),
        "article": {
            "bodyHtml": new_body
        }
    }

    res = _graphql(mut_query, vars)
    errors = res.get("data", {}).get("blogArticleUpdate", {}).get("userErrors", [])
    if errors:
        print(f"  ERROR updating article {article_id}: {errors}")
        return {"status": "error", "error": str(errors)}

    print(f"  Successfully updated article {article_id}.")
    
    return {
        "status": "updated",
        "gid": article.get("gid", f"gid://shopify/Article/{article_id}"),
        "title": art_title,
        "body_html": new_body,
        "replacements": replacements_log,
        "featured_product": None
    }


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


def run(limit: int = 0, dry_run: bool = False, article_id: int | None = None):
    is_single_article = bool(article_id)
    mode = "single" if article_id else "all"
    print(f"\\n{'='*64}")
    print(f"  MeeeShop Blog Refresher — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  Mode: {mode} | Limit: {limit} | Dry-run: {dry_run}")
    print(f"{'='*64}\\n")

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

    # ── Redirects ─────────────────────────────────────────────────────────────
    print("Fetching active store redirects...")
    redirect_map = fetch_all_redirects()
    print(f"  Loaded {len(redirect_map)} active redirects.\n")

    # ── Collect articles to process ───────────────────────────────────────────
    work_items: list[tuple[dict, dict]] = []  # (blog, article)

    if article_id:
        # Single article mode: attempt direct GraphQL lookup first
        art_res = fetch_article_by_id(article_id)
        if art_res:
            work_items.append(art_res)
        else:
            print(f"  GraphQL node lookup for article {article_id} returned empty. Searching all blogs...")
            for blog in blogs:
                arts = fetch_articles_for_blog(blog["id"], limit=500)
                for art in arts:
                    if art["id"] == article_id:
                        work_items.append((blog, art))
                        break
                if work_items:
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

        work_items = all_articles if limit <= 0 else all_articles[:limit]

    print(f"Articles to refresh: {len(work_items)}\n")

    # ── Check and update authors for all articles in the store ──────────────────
    if True:
        print("Checking article authors...")
        articles_to_check = work_items if article_id else all_articles
        author_batch = []
        for blog, art in articles_to_check:
            cur_author = (art.get("author") or "").strip()
            # Only update if author is generic/blank. Existing pen names are NEVER re-randomised.
            if needs_author_update(cur_author):
                new_author = random.choice(PEN_NAMES)
                print(f"  Article '{art.get('title')}' (ID {art.get('id')}) has generic author '{cur_author}'. Updating to E-E-A-T pen name '{new_author}'...")
                if not dry_run:
                    author_batch.append({"gid": art.get("gid", f"gid://shopify/Article/{art['id']}"), "author": new_author})
                    art["author"] = new_author
                    if len(author_batch) >= 10:
                        _execute_author_batch(author_batch)
                        author_batch = []
                else:
                    print(f"    [DRY-RUN] Would update author to '{new_author}'.")
            else:
                pass  # valid pen name or custom name — keep it silently

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
                redirect_map=redirect_map,
                dry_run=dry_run
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
    args = ap.parse_args()

    run(
        limit=args.limit,
        dry_run=args.dry_run,
        article_id=args.article_id,
    )

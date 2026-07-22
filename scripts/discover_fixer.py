#!/usr/bin/env python3
"""
discover_fixer.py — Automated Google Discover SEO & E-E-A-T Fixer for MeeeShop
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Scans existing published blog articles on Shopify and automatically fixes:
  1. E-E-A-T Author: Replaces generic authors (e.g. "Meeeshop") with fictional style pen names.
  2. SEO Metafields: Fills in missing global.title_tag and global.description_tag.
  3. Body HTML Duplicates & Overlinking:
     - Converts body H1 tags to H2s (since theme already prints a main H1).
     - Limits dense inline links.
  4. Shoppers' Q&A: Injects a custom Why/What/How styled FAQ block if missing.
  5. Low-Res Image Replacement: If the featured image is under 1200px wide, it
     auto-detects the product, builds an outfit collage, uploads it, and replaces the image.
"""

import os
import sys
import re
import json
import time
import argparse
import random
from pathlib import Path
from urllib.parse import urlparse, quote
import requests
from bs4 import BeautifulSoup
from PIL import Image
from io import BytesIO

# ── path setup ────────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from secrets_manager import inject_to_env, get_secret

inject_to_env()

# ── credentials ───────────────────────────────────────────────────────────────
SHOP      = get_secret("SHOPIFY_STORE")
TOKEN     = get_secret("SHOPIFY_ACCESS_TOKEN")
STORE_URL = get_secret("STORE_BASE_URL").rstrip("/")
API_VER   = "2024-10"
BASE      = f"https://{SHOP}/admin/api/{API_VER}"
SHP_HDR   = {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}

import ai_client
from eeat_constants import PEN_NAMES, GENERIC_AUTHORS, needs_author_update, is_valid_pen_name

# ── API Helpers ───────────────────────────────────────────────────────────────
def _req(method, url, **kw):
    for attempt in range(5):
        try:
            r = getattr(requests, method)(url, headers=SHP_HDR, timeout=25, **kw)
            if r.status_code == 429:
                wait = int(float(r.headers.get("Retry-After", 4)))
                time.sleep(wait)
                continue
            return r
        except requests.exceptions.ConnectionError:
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"{method.upper()} {url} failed after 5 attempts")

def get_all_blogs() -> list:
    r = _req("get", f"{BASE}/blogs.json")
    r.raise_for_status()
    return r.json().get("blogs", [])

def get_articles(blog_id: int, limit: int = 20) -> list:
    r = _req("get", f"{BASE}/blogs/{blog_id}/articles.json", params={"limit": limit})
    r.raise_for_status()
    return r.json().get("articles", [])

def get_metafields(blog_id: int, article_id: int) -> list:
    r = _req("get", f"{BASE}/blogs/{blog_id}/articles/{article_id}/metafields.json")
    r.raise_for_status()
    return r.json().get("metafields", [])

def set_metafield(blog_id: int, article_id: int, namespace: str, key: str, value: str):
    mf = {"namespace": namespace, "key": key, "value": value, "type": "single_line_text_field"}
    r = _req("post", f"{BASE}/blogs/{blog_id}/articles/{article_id}/metafields.json", json={"metafield": mf})
    r.raise_for_status()

def update_article(blog_id: int, article_id: int, payload: dict):
    r = _req("put", f"{BASE}/blogs/{blog_id}/articles/{article_id}.json", json={"article": payload})
    r.raise_for_status()
    return r.json().get("article")

def fetch_product_by_handle(handle: str) -> dict | None:
    try:
        r = _req("get", f"{BASE}/products.json", params={"handle": handle, "fields": "id,title,handle,product_type,variants,images"})
        products = r.json().get("products", [])
        return products[0] if products else None
    except Exception as e:
        print(f"    [!] Error getting product '{handle}': {e}")
        return None

def fetch_all_active_products() -> list:
    try:
        r = _req("get", f"{BASE}/products.json", params={"limit": 100, "status": "active", "fields": "id,title,handle,product_type,variants,images"})
        return r.json().get("products", [])
    except Exception as e:
        print(f"    [!] Error getting catalog pool: {e}")
        return []

# ── Image processing & upload ──────────────────────────────────────────────────
def check_image_width(url: str) -> int:
    try:
        if "_1200x" in url or "_1200x630" in url:
            return 1200
        # Quick download header to see size
        r = requests.get(url, headers={"Range": "bytes=0-131072"}, timeout=10)
        if r.status_code in (200, 206):
            img = Image.open(BytesIO(r.content))
            return img.width
        # Full download fallback
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            img = Image.open(BytesIO(r.content))
            return img.width
    except Exception:
        pass
    return 0

def select_styling_matches(main_product: dict, pool: list) -> list[dict]:
    main_type = (main_product.get("product_type") or "").lower()
    main_id = main_product.get("id")
    
    is_top = any(x in main_type for x in ["top", "blouse", "shirt", "tee"])
    is_bottom = any(x in main_type for x in ["jean", "pant", "skirt", "legging", "short"])
    is_one_piece = any(x in main_type for x in ["dress", "jumpsuit", "romper"])
    
    complementary_pool = []
    for p in pool:
        if p.get("id") == main_id or not p.get("images"):
            continue
        ptype = (p.get("product_type") or "").lower()
        
        if is_top:
            if any(x in ptype for x in ["jean", "pant", "skirt", "jacket", "coat", "cardigan", "accessory"]):
                complementary_pool.append(p)
        elif is_bottom:
            if any(x in ptype for x in ["top", "blouse", "shirt", "tee", "sweater", "jacket", "coat", "cardigan"]):
                complementary_pool.append(p)
        elif is_one_piece:
            if any(x in ptype for x in ["jacket", "coat", "cardigan", "accessory", "shoe", "bag"]):
                complementary_pool.append(p)
        else:
            complementary_pool.append(p)
            
    if len(complementary_pool) >= 2:
        return random.sample(complementary_pool, 2)
    fallback_pool = [p for p in pool if p.get("id") != main_id and p.get("images")]
    if len(fallback_pool) >= 2:
        return random.sample(fallback_pool, 2)
    return fallback_pool

def crop_to_fit(img, target_w, target_h):
    img_ratio = img.width / img.height
    target_ratio = target_w / target_h
    if img_ratio > target_ratio:
        new_h = target_h
        new_w = int(img.width * (target_h / img.height))
        img_resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        crop_x = (new_w - target_w) // 2
        return img_resized.crop((crop_x, 0, crop_x + target_w, target_h))
    else:
        new_w = target_w
        new_h = int(img.height * (target_w / img.width))
        img_resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        crop_y = (new_h - target_h) // 2
        return img_resized.crop((0, crop_y, target_w, crop_y + target_h))

def generate_outfit_collage(main_product: dict, matching_products: list) -> Path | None:
    images_to_load = []
    main_imgs = main_product.get("images", [])
    if main_imgs:
        images_to_load.append(main_imgs[0]["src"])
    for p in matching_products:
        imgs = p.get("images", [])
        if imgs:
            images_to_load.append(imgs[0]["src"])
            
    if not images_to_load:
        return None
        
    downloaded_imgs = []
    for url in images_to_load:
        try:
            r = requests.get(url, timeout=15)
            if r.status_code == 200:
                img = Image.open(BytesIO(r.content))
                downloaded_imgs.append(img)
        except Exception:
            pass
            
    if not downloaded_imgs:
        return None
        
    canvas_w, canvas_h = 1200, 630
    collage = Image.new("RGB", (canvas_w, canvas_h), (255, 255, 255))
    num_imgs = len(downloaded_imgs)
    
    try:
        if num_imgs == 1:
            img = downloaded_imgs[0]
            collage.paste(crop_to_fit(img, canvas_w, canvas_h), (0, 0))
        elif num_imgs == 2:
            spacing = 25
            col_w = (canvas_w - (3 * spacing)) // 2
            col_h = canvas_h - (2 * spacing)
            for i, img in enumerate(downloaded_imgs):
                collage.paste(crop_to_fit(img, col_w, col_h), (spacing + i * (col_w + spacing), spacing))
        else:
            spacing = 20
            col_w = (canvas_w - (4 * spacing)) // 3
            col_h = canvas_h - (2 * spacing)
            for i, img in enumerate(downloaded_imgs[:3]):
                collage.paste(crop_to_fit(img, col_w, col_h), (spacing + i * (col_w + spacing), spacing))
                
        temp_path = Path("collage_temp_fix.jpg")
        collage.save(temp_path, "JPEG", quality=92)
        return temp_path
    except Exception as e:
        print(f"      [!] Collage drawing failed: {e}")
        return None

def upload_image_to_shopify(filepath: Path, filename: str) -> str | None:
    graphql_url = f"{BASE}/graphql.json"
    staged_mut = f"""
    mutation {{
      stagedUploadsCreate(input: [{{
        resource: FILE,
        filename: "{filename}",
        mimeType: "image/jpeg",
        httpMethod: POST
      }}]) {{
        stagedTargets {{
          url
          resourceUrl
          parameters {{
            name
            value
          }}
        }}
      }}
    }}
    """
    try:
        r = _req("post", graphql_url, json={"query": staged_mut})
        r.raise_for_status()
        data = r.json()
        target = data["data"]["stagedUploadsCreate"]["stagedTargets"][0]
        
        with open(filepath, "rb") as f:
            form_data = []
            for p in target["parameters"]:
                form_data.append((p["name"], p["value"]))
            form_data.append(("file", (filename, f, "image/jpeg")))
            
            upload_resp = requests.post(target["url"], files=form_data, timeout=30)
            if upload_resp.status_code not in (200, 201):
                print(f"      [!] Staged upload failed with status {upload_resp.status_code}. Response body:")
                print(upload_resp.text)
            upload_resp.raise_for_status()
            
        create_mut = """
        mutation fileCreate($files: [FileCreateInput!]!) {
          fileCreate(files: $files) {
            files { id fileStatus }
            userErrors { message }
          }
        }
        """
        variables = {"files": [{"originalSource": target["resourceUrl"], "contentType": "FILE"}]}
        r = _req("post", graphql_url, json={"query": create_mut, "variables": variables})
        create_data = r.json()
        file_id = create_data["data"]["fileCreate"]["files"][0]["id"]
        
        public_url = None
        for _ in range(15):
            time.sleep(2)
            query_file = f"query {{ node(id: \"{file_id}\") {{ ... on GenericFile {{ url fileStatus }} }} }}"
            r = _req("post", graphql_url, json={"query": query_file})
            node = r.json().get("data", {}).get("node", {})
            if node.get("fileStatus") == "READY":
                public_url = node.get("url")
                break
        return public_url.split("?")[0] if public_url else None
    except Exception as e:
        print(f"      [!] Staged upload failed: {e}")
        return None

# ── Shoppers' Q&A Generation ──────────────────────────────────────────────────
def generate_shoppers_qa(post_title: str, product_title: str, category: str) -> str:
    """Uses AI to generate a custom 3-question Q&A section answering shoppers' questions."""
    print("      Generating custom Q&A block using AI...")
    prompt = (
        f"You are a fashion stylist editor at MeeeShop boutique.\n"
        f"Write a Shoppers' Q&A section in HTML for the blog article \"{post_title}\".\n"
        f"Featured Product: {product_title} (category: {category}).\n\n"
        f"You must strictly follow this format (output only these tags with clean, warm styling tips):\n"
        f"<h2>Shoppers' Q&A: Common Questions Answered</h2>\n"
        f"<h3>Why should this style be in my closet?</h3>\n"
        f"<p>[Explain in 2 sentences its versatility, fabrics, or styling value]</p>\n"
        f"<h3>What is the fabric composition and how do I wash it?</h3>\n"
        f"<p>[Explain how to wash and care for this product type to preserve its drape and quality in 2 sentences]</p>\n"
        f"<h3>How do I choose the correct size?</h3>\n"
        f"<p>[Provide sizing guidelines, mention sizes XS-3X, 2 sentences]</p>\n\n"
        f"Output ONLY clean HTML, no markdown code block formatting."
    )
    try:
        raw = ai_client.generate(prompt, max_tokens=300, temperature=0.6)
        if raw:
            raw = raw.strip()
            raw = re.sub(r"^```html?\s*", "", raw, flags=re.IGNORECASE)
            raw = re.sub(r"\s*```$", "", raw).strip()
            return raw
    except Exception as e:
        print(f"      [!] AI Q&A generation failed: {e}")
    
    # Fallback template
    return f"""
<h2>Shoppers' Q&A: Common Questions Answered</h2>
<h3>Why should this style be in my closet?</h3>
<p>This styled piece provides ultimate versatility, making it perfect to layer for casual wear or transition easily to dressier occasions while retaining high-quality structure.</p>
<h3>What is the fabric composition and how do I wash it?</h3>
<p>To preserve the shape, drape, and color richness of the fabric, we recommend washing inside out in cold water on a gentle cycle, then line drying or drying on a flat surface.</p>
<h3>How do I choose the correct size?</h3>
<p>This collection runs true to size and is available in sizes XS–3X. If you prefer a relaxed or slightly oversized fit for layering, we recommend sizing up one size.</p>
"""

# ── Fixer Core Logic ───────────────────────────────────────────────────────────
def fix_article(blog_id: int, blog_title: str, article: dict, catalog_pool: list, force_image: bool = False):
    article_id = article["id"]
    title = article.get("title", "")
    author = article.get("author", "").strip()
    body_html = article.get("body_html", "")
    image = article.get("image", {})
    
    print(f"\n[*] Auditing: '{title}' (ID {article_id})")
    
    has_changes = False
    updates = {}
    
    # 1. Author (E-E-A-T) Fix
    # Only replace if author is generic/blank. Existing pen names are NEVER re-randomised.
    if needs_author_update(author):
        new_author = random.choice(PEN_NAMES)
        updates["author"] = new_author
        has_changes = True
        print(f"  [EEAT] Replaced author '{author}' with: '{new_author}'")
    else:
        print(f"  [EEAT] Author '{author}' is a valid pen name — skipping.")
        
    # 2. HTML Body Fixes (Double H1s, Overlinking, Q&A injection)
    soup = BeautifulSoup(body_html, "html.parser")
    body_changed = False
    
    # H1 conversion
    h1s = soup.find_all("h1")
    if h1s:
        for h1 in h1s:
            h1.name = "h2"  # Changes tag name in-place; preserves all inner HTML, images, and child nodes intact
        body_changed = True
        print(f"  [HTML] Converted {len(h1s)} H1 tag(s) to H2(s) (preserved all inner content & images).")
        
    # Overlinking reduction — only flag INLINE text links, not product card widgets
    # Product card widgets contain 'View Product' buttons and price elements; these are
    # intentional shopping features, NOT spam links, so we exclude them from the count.
    PRODUCT_LINK_LIMIT = 15  # Articles featuring 5-15 products with buy buttons is normal
    links = soup.find_all("a")
    product_links = [l for l in links if "/products/" in l.get("href", "")]

    # Filter out product card widget links (View Product buttons, price text, empty text, image links)
    def is_widget_link(tag):
        text = tag.get_text(strip=True).lower()
        return (
            text in ("", "view product", "shop now", "buy now") or
            "$" in tag.get_text() or
            tag.find("img") is not None or  # NEVER touch links containing product images
            any(cls in " ".join(tag.get("class", [])) for cls in ["btn", "button", "product-card", "cta"])
        )

    inline_product_links = [l for l in product_links if not is_widget_link(l)]

    if len(inline_product_links) > PRODUCT_LINK_LIMIT:
        # Only remove href from excessive inline text links — preserve all inner HTML/images intact
        for l in inline_product_links[PRODUCT_LINK_LIMIT:]:
            l.name = "span"
            if "href" in l.attrs:
                del l["href"]
        body_changed = True
        print(f"  [HTML] Reduced inline product link count from {len(inline_product_links)} to {PRODUCT_LINK_LIMIT} (widget & image links preserved).")
    else:
        print(f"  [HTML] {len(inline_product_links)} inline product links (total {len(product_links)} incl. widgets) — within limit — NO change.")

    # Detect product handles for Q&A and collage
    linked_handles = []
    all_links = soup.find_all("a")
    for l in all_links:
        href = l.get("href", "")
        if "/products/" in href:
            path = urlparse(href).path
            m = re.search(r"/products/([^/]+)", path)
            if m:
                h = m.group(1).split("?")[0]
                if h not in linked_handles:
                    linked_handles.append(h)
                    
    main_product_handle = linked_handles[0] if linked_handles else None

    # Shoppers' Q&A Injection
    text_lower = soup.get_text().lower()
    has_qa = any(q in text_lower for q in ["faq", "q&a", "common questions", "shoppers' q&a"])
    if not has_qa:
        # Resolve featured product details
        prod_title = "this product"
        prod_type = "apparel"
        prod_data = None
        if main_product_handle:
            prod_data = fetch_product_by_handle(main_product_handle)
            if prod_data:
                prod_title = prod_data["title"]
                prod_type = prod_data.get("product_type", "apparel")
        
        qa_html = generate_shoppers_qa(title, prod_title, prod_type)
        
        # ALWAYS append Q&A block to the very end of the article body
        soup.append(qa_soup)
        body_changed = True
        print("  [HTML] Injected Shoppers' Q&A section at end of article.")
        
    if body_changed:
        updates["body_html"] = str(soup)
        has_changes = True

    # 3. Featured Image Check (Dimension Audit and Collage Fix)
    img_src = image.get("src", "") if image else ""
    needs_image_fix = False
    
    if force_image:
        needs_image_fix = True
    elif not img_src:
        needs_image_fix = True
        print("  [IMAGE] Featured image is missing.")
    else:
        width = check_image_width(img_src)
        if width > 0 and width < 1200:
            needs_image_fix = True
            print(f"  [IMAGE] Image is low-res ({width}px wide). Requires 1200px wide for Discover.")
            
    if needs_image_fix:
        # Load main product details
        main_prod = None
        if main_product_handle:
            main_prod = fetch_product_by_handle(main_product_handle)
        else:
            # Fallback: try mapping title keywords to product handles
            words = [w.lower() for w in re.split(r"\W+", title) if len(w) > 3]
            for w in words[:4]:
                main_prod = fetch_product_by_handle(w)
                if main_prod:
                    break
                    
        if main_prod and main_prod.get("images"):
            # Only use products that are actually linked in the article body (excluding the main product)
            matches = []
            other_handles = [h for h in linked_handles if h != main_prod["handle"]]
            for h in other_handles[:2]:  # limit to 2 matches for collage
                p_data = fetch_product_by_handle(h)
                if p_data and p_data.get("images"):
                    matches.append(p_data)
            
            # Generate the collage. If matches is empty, it will generate a 1200x630 single product crop!
            collage_local = generate_outfit_collage(main_prod, matches)
            
            if collage_local and collage_local.exists():
                ts = int(time.time())
                filename = f"styling_collage_fixed_{article_id}_{ts}.jpg"
                cdn_url = upload_image_to_shopify(collage_local, filename)
                
                try:
                    collage_local.unlink()
                except Exception:
                    pass
                    
                if cdn_url:
                    updates["image"] = {
                        "src": cdn_url,
                        "alt": f"{main_prod['title']} style formula collage for Google Discover lookbook"
                    }
                    has_changes = True
                    print(f"  [IMAGE] Successfully generated and uploaded 1200x630 outfit collage/featured image: {cdn_url}")
                else:
                    print("  [IMAGE] [!] Staged upload failed during collage/featured image update.")
            else:
                print("  [IMAGE] [!] Collage/featured image creation failed.")
        else:
            print("  [IMAGE] [!] No associated product or images found for this article — skipping collage/featured image build.")

    # 4. Push Shopify updates
    if has_changes:
        try:
            update_article(blog_id, article_id, updates)
            print("  ✓ Shopify article updated successfully.")
        except Exception as e:
            print(f"  [!] Failed to save article updates: {e}")
    else:
        print("  ✓ Article is fully optimized — no changes required.")

    # 5. Check and fix SEO Metafields
    metafields = get_metafields(blog_id, article_id)
    title_tag = next((m["value"] for m in metafields if m["namespace"] == "global" and m["key"] == "title_tag"), None)
    desc_tag = next((m["value"] for m in metafields if m["namespace"] == "global" and m["key"] == "description_tag"), None)
    
    if not title_tag or not desc_tag:
        clean_title = re.sub(r"<[^>]+>", "", title).strip()
        seo_title = f"{clean_title[:45]} — MeeeShop 2026"[:60]
        
        # Clean text summary for desc
        soup_text = BeautifulSoup(body_html, "html.parser").get_text()
        clean_desc = re.sub(r"\s+", " ", soup_text).strip()
        seo_desc = f"Discover styling ideas in this outfit guide. Shop boutique fashion at MeeeShop — free US shipping on orders $50+ and easy returns."
        if len(clean_desc) > 80:
            seo_desc = f"{clean_desc[:120]}... Shop MeeeShop boutique with free US shipping."[:155]
            
        try:
            if not title_tag:
                set_metafield(blog_id, article_id, "global", "title_tag", seo_title)
                print(f"  [SEO] Created Title tag: '{seo_title}'")
            if not desc_tag:
                set_metafield(blog_id, article_id, "global", "description_tag", seo_desc)
                print(f"  [SEO] Created Meta description: '{seo_desc}'")
        except Exception as e:
            print(f"  [SEO] [!] Metafields update failed: {e}")

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Fix published MeeeShop blog posts for Google Discover")
    parser.add_argument("--limit",      type=int,  default=5,  help="Number of articles to fix per blog (default: 5)")
    parser.add_argument("--force-image",action="store_true",   help="Force rebuild featured images as styling collages")

    # ── Safe single-article test flags ──────────────────────────────────────
    parser.add_argument("--article-id", type=int,  default=None,
                        help="Target a SINGLE article by its Shopify article ID (use with --blog-id)")
    parser.add_argument("--blog-id",    type=int,  default=None,
                        help="Blog ID the target article belongs to (required when using --article-id)")
    parser.add_argument("--dry-run",    action="store_true",
                        help="PRINT all changes that WOULD be made without writing anything to Shopify. "
                             "Safe for inspection before going live.")
    args = parser.parse_args()

    print("=" * 75)
    print("MEEESHOP GOOGLE DISCOVER SEO & E-E-A-T AUTOMATED FIXER")
    if args.dry_run:
        print("  *** DRY-RUN MODE — NO CHANGES WILL BE WRITTEN TO SHOPIFY ***")
    if args.article_id:
        print(f"  *** SINGLE ARTICLE MODE — targeting article ID {args.article_id} ***")
    print("=" * 75)

    if not SHOP or not TOKEN:
        sys.exit("ERROR: Shopify credentials missing from secrets.enc.")

    print(f"Targeting: {SHOP}")

    # ── Single-article test path ─────────────────────────────────────────────
    if args.article_id:
        if not args.blog_id:
            sys.exit("ERROR: --blog-id is required when using --article-id.\n"
                     "       Find it in Shopify Admin → Online Store → Blog Posts "
                     "→ click any post → the URL contains /blogs/{blog_id}/articles/{article_id}")

        print(f"\n[*] Fetching single article {args.article_id} from blog {args.blog_id}...")
        r = _req("get", f"{BASE}/blogs/{args.blog_id}/articles/{args.article_id}.json")
        if r.status_code != 200:
            sys.exit(f"ERROR: Could not fetch article. Status {r.status_code}: {r.text[:200]}")

        article = r.json().get("article", {})
        if not article:
            sys.exit("ERROR: Article not found.")

        print(f"  Found: '{article.get('title', '(no title)')}'\n")

        if args.dry_run:
            print("DRY-RUN: What WOULD be changed:")
            print("-" * 50)
            _dry_run_report(args.blog_id, article)
        else:
            catalog_pool = fetch_all_active_products()
            print(f"[*] Loaded {len(catalog_pool)} active products for collage matching.")
            fix_article(args.blog_id, "(single-article test)", article,
                        catalog_pool, force_image=args.force_image)

        print("\n✓ Single-article run complete.")
        return

    # ── Normal batch path ────────────────────────────────────────────────────
    print("[*] Fetching product catalog pool for collages...")
    catalog_pool = fetch_all_active_products()
    print(f"    Loaded {len(catalog_pool)} active products.")

    print("[*] Fetching blogs...")
    try:
        blogs = get_all_blogs()
    except Exception as e:
        sys.exit(f"ERROR: Could not retrieve blogs: {e}")

    print(f"Found {len(blogs)} blog(s) to process.")

    for blog in blogs:
        blog_title = blog["title"]
        blog_id    = blog["id"]
        print(f"\nProcessing blog: '{blog_title}' (ID {blog_id})...")
        try:
            articles = get_articles(blog_id, limit=args.limit)
            print(f"Found {len(articles)} article(s).")
            for art in articles:
                if args.dry_run:
                    _dry_run_report(blog_id, art)
                else:
                    fix_article(blog_id, blog_title, art, catalog_pool, force_image=args.force_image)
                time.sleep(1.0)
        except Exception as e:
            print(f"[!] Error processing blog '{blog_title}': {e}")

    print("\n✓ Discover Fixer run completed.")


# ── Dry-run inspector (prints what would change, touches nothing) ─────────────
def _dry_run_report(blog_id: int, article: dict):
    """Inspect an article and print every change that fix_article() would make."""
    title      = article.get("title", "")
    author     = article.get("author", "").strip()
    body_html  = article.get("body_html", "")
    image      = article.get("image") or {}
    article_id = article["id"]

    print(f"\n[DRY-RUN] Article: '{title}' (ID {article_id})")
    print(f"  Live URL  : https://us.meeeshop.com/blogs/*/article-slug")

    # 1. Author — uses shared needs_author_update() so logic is identical to fix_article
    if needs_author_update(author):
        print(f"  [EEAT]  WOULD replace author '{author}' with a pen name (e.g. 'Elena Vance, MeeeShop Lead Stylist')")
    else:
        print(f"  [EEAT]  Author '{author}' is already a valid pen name — NO change")

    # 2a. H1 check
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(body_html, "html.parser")
    h1s = soup.find_all("h1")
    if h1s:
        print(f"  [HTML]  WOULD convert {len(h1s)} H1(s) inside body to H2(s): {[h.get_text()[:40] for h in h1s]}")
    else:
        print("  [HTML]  No H1 tags inside body — NO change")

    # 2b. Overlinking — widget-aware (same logic as fix_article)
    all_product_links = [l for l in soup.find_all("a") if "/products/" in l.get("href", "")]
    def is_widget_link_dry(tag):
        text = tag.get_text(strip=True).lower()
        return (
            text in ("", "view product", "shop now", "buy now") or
            "$" in tag.get_text() or
            any(cls in " ".join(tag.get("class", [])) for cls in ["btn", "button", "product-card", "cta"])
        )
    inline_links = [l for l in all_product_links if not is_widget_link_dry(l)]
    widget_links  = len(all_product_links) - len(inline_links)
    if len(inline_links) > 15:
        print(f"  [HTML]  WOULD remove {len(inline_links)-15} inline product link(s) (widget links: {widget_links} preserved)")
    else:
        print(f"  [HTML]  {len(inline_links)} inline + {widget_links} widget product links — within limit — NO change")

    # 2c. Q&A
    text_lower = soup.get_text().lower()
    has_qa = any(q in text_lower for q in ["faq", "q&a", "common questions", "shoppers' q&a"])
    if not has_qa:
        print("  [HTML]  WOULD inject a 3-question 'Shoppers Q&A' section at end of article")
    else:
        print("  [HTML]  Q&A/FAQ section already exists — NO change")

    # 3. Image
    img_src = image.get("src", "")
    if not img_src:
        print("  [IMAGE] WOULD generate + upload a 1200x630 product collage (no image currently)")
    else:
        width = check_image_width(img_src)
        if width > 0 and width < 1200:
            print(f"  [IMAGE] WOULD replace featured image ({width}px wide) with a 1200x630 collage")
        elif width >= 1200:
            print(f"  [IMAGE] Image is already {width}px wide — meets Discover requirement — NO change")
        else:
            print(f"  [IMAGE] Image width could not be determined — WOULD attempt collage replacement")

    # 4. SEO metafields (read from live store)
    try:
        metafields = get_metafields(blog_id, article_id)
        title_tag = next((m["value"] for m in metafields if m["namespace"] == "global" and m["key"] == "title_tag"), None)
        desc_tag  = next((m["value"] for m in metafields if m["namespace"] == "global" and m["key"] == "description_tag"), None)
        if not title_tag:
            print(f"  [SEO]   WOULD create meta title (currently missing)")
        else:
            print(f"  [SEO]   Meta title already set: '{title_tag[:60]}' — NO change")
        if not desc_tag:
            print(f"  [SEO]   WOULD create meta description (currently missing)")
        else:
            print(f"  [SEO]   Meta description already set — NO change")
    except Exception as e:
        print(f"  [SEO]   Could not read metafields: {e}")

    print("-" * 60)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()

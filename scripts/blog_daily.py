#!/usr/bin/env python3
"""
blog_daily.py — Google Discover-ready blog automation for MeeeShop
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Google Discover + SEO requirements:
  - Featured image: 1200px wide, descriptive keyword-rich ALT text
  - SEO title: 50-60 chars, keyword-first, set via Shopify metafield
  - Meta description: 140-155 chars, action-oriented, set via summary_html
  - Slug (handle): auto-generated from SEO title by Shopify
  - EEAT: first-person experience, expertise signals, trust indicators
  - 5 high-intent formats: buying guide, comparison, problem-solver,
    trend report, outfit formula
  - Popular keywords embedded naturally in H1, H2, body, ALT, meta

AI: Gemini 2.0 Flash -> Groq Llama-3.3-70B -> OpenRouter (multi-model free tier)
Image: Shopify product image resized to 1200x630 via CDN; Pollinations.ai fallback

Usage:
  python blog_daily.py              # create 1 post
  python blog_daily.py --dry-run    # print only, no Shopify publish
  python blog_daily.py --count 3    # create 3 posts
"""

import os, sys, re, time, random, argparse
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import requests
import ai_client
from PIL import Image
from io import BytesIO

# ── credentials ───────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from secrets_manager import inject_to_env, get_secret
inject_to_env()

SHOP    = get_secret("SHOPIFY_STORE")
TOKEN   = get_secret("SHOPIFY_ACCESS_TOKEN")
API_VER = "2024-10"
BASE    = f"https://{SHOP}/admin/api/{API_VER}"
HEADERS = {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}

if not TOKEN:
    sys.exit("ERROR: SHOPIFY_ACCESS_TOKEN not set.")

STORE_URL = get_secret("STORE_BASE_URL")

YEAR  = datetime.now().year
MONTH = datetime.now().strftime("%B %Y")

# ── Shopify helpers ────────────────────────────────────────────────────────────
def _req(method, url, **kw):
    for attempt in range(5):
        try:
            r = getattr(requests, method)(url, headers=HEADERS, timeout=30, **kw)
            if r.status_code == 429:
                wait = int(float(r.headers.get("Retry-After", 4)))
                time.sleep(wait)
                continue
            return r
        except requests.exceptions.ConnectionError:
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"{method.upper()} {url} failed after 5 attempts")


# ── Blog category routing ──────────────────────────────────────────────────────
CATEGORY_BLOG_MAP = {
    "dress":      ["dress", "style", "fashion", "journal"],
    "jean":       ["denim", "jean", "style", "fashion", "journal"],
    "top":        ["style", "fashion", "tops", "journal"],
    "blouse":     ["style", "fashion", "tops", "journal"],
    "skirt":      ["style", "fashion", "journal"],
    "pant":       ["style", "fashion", "journal"],
    "jacket":     ["outerwear", "style", "fashion", "journal"],
    "coat":       ["outerwear", "style", "fashion", "journal"],
    "sweater":    ["style", "fashion", "journal"],
    "cardigan":   ["style", "fashion", "journal"],
    "swimwear":   ["swim", "summer", "style", "fashion", "journal"],
    "activewear": ["active", "fitness", "style", "fashion", "journal"],
    "accessory":  ["accessories", "style", "fashion", "journal"],
}


def get_all_blogs() -> list:
    r = _req("get", f"{BASE}/blogs.json")
    r.raise_for_status()
    return r.json().get("blogs", [])


def get_or_create_blog(product_type: str, all_blogs: list, dry_run: bool = False) -> dict:
    ptype_lower = (product_type or "").lower()
    
    # 1. Direct target blog names mapping
    target_blog_title = None
    if "dress" in ptype_lower:
        target_blog_title = "dresses"
    elif any(x in ptype_lower for x in ["jean", "denim", "jort"]):
        target_blog_title = "jeans"
    elif any(x in ptype_lower for x in ["skirt", "skort"]):
        target_blog_title = "skirts"
    elif any(x in ptype_lower for x in ["pant", "legging", "short"]):
        target_blog_title = "pants"
    elif any(x in ptype_lower for x in ["top", "blouse", "shirt", "tee", "t-shirt", "tank"]):
        target_blog_title = "shirts & tops"
    elif any(x in ptype_lower for x in ["jacket", "coat", "outerwear", "blazer"]):
        target_blog_title = "coats & jackets"
    elif any(x in ptype_lower for x in ["sweater", "cardigan", "knit", "pullover"]):
        target_blog_title = "cardigans & sweaters"
        
    # 2. Try matching the targeted title
    if target_blog_title:
        for blog in all_blogs:
            title_lower = blog.get("title", "").lower()
            # Avoid matching Announcements or system blogs
            if "announcements" in title_lower or "tips" in title_lower:
                continue
            if target_blog_title in title_lower:
                return blog
                
    # 3. Fallback to "Women's Clothing" if available
    for blog in all_blogs:
        title_lower = blog.get("title", "").lower()
        if "women's clothing" in title_lower:
            return blog
            
    # 4. Fallback to any blog that is not a system blog
    non_system_blogs = [
        b for b in all_blogs 
        if "announcements" not in b.get("title", "").lower() and "tips" not in b.get("title", "").lower()
    ]
    if non_system_blogs:
        return non_system_blogs[0]
        
    if all_blogs:
        return all_blogs[0]
        
    if dry_run:
        return {"id": 0, "title": "MOCK Fallback Blog (Dry Run)"}
        
    # Create blog if none exist
    r = _req("post", f"{BASE}/blogs.json",
             json={"blog": {"title": "Women's Clothing"}})
    r.raise_for_status()
    new_blog = r.json()["blog"]
    all_blogs.append(new_blog)
    return new_blog


def fetch_products(limit=100) -> list:
    r = _req("get", f"{BASE}/products.json",
             params={"limit": limit, "fields": "id,title,handle,product_type,vendor,tags,variants,images,body_html"})
    r.raise_for_status()
    return r.json().get("products", [])


# ── SEO metadata generation ────────────────────────────────────────────────────
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

    return {
        "seo_title":  seo_title,
        "meta_desc":  meta_desc,
        "img_alt":    img_alt,
    }


def set_article_seo_metafields(blog_id: int, article_id: int, seo_title: str, meta_desc: str):
    """
    Set SEO title and meta description via Shopify metafields.
    These map to the <title> tag and <meta name="description"> in Shopify themes.
    Namespace: global — keys: title_tag, description_tag (standard Shopify SEO metafields).
    """
    metafields = [
        {"namespace": "global", "key": "title_tag",       "value": seo_title, "type": "single_line_text_field"},
        {"namespace": "global", "key": "description_tag", "value": meta_desc, "type": "single_line_text_field"},
    ]
    for mf in metafields:
        r = _req("post",
                 f"{BASE}/blogs/{blog_id}/articles/{article_id}/metafields.json",
                 json={"metafield": mf})
        if r.status_code in (200, 201):
            print(f"  SEO metafield set: {mf['key']} = {mf['value'][:60]}")
        else:
            print(f"  SEO metafield FAILED ({mf['key']}): {r.status_code} {r.text[:100]}")


# ── Image helpers ──────────────────────────────────────────────────────────────
def make_featured_image_url(product: dict, fmt: str) -> str:
    """
    Shopify product image resized to 1200x630 via CDN.
    Google Discover requires minimum 1200px wide.
    """
    images = product.get("images", [])
    if not images:
        raise ValueError(f"Product '{product.get('title')}' has no images. Direct CDN images are required for Discover.")
    src = images[0]["src"]
    # Shopify CDN image transform: insert _1200x630_crop_center before extension
    src = re.sub(r'\.(jpg|jpeg|png|webp)(\?.*)?$',
                 r'_1200x630_crop_center.\1', src, flags=re.IGNORECASE)
    return src


def product_img_url(product: dict) -> str | None:
    images = product.get("images", [])
    return images[0]["src"] if images else None


# ── Product cards ──────────────────────────────────────────────────────────────
def make_product_card(product: dict, keyword: str = "",
                      label: str = "FEATURED PICK — IN STOCK NOW") -> str:
    import html
    raw_title = product["title"]
    escaped_title = html.escape(raw_title)
    price  = product["variants"][0]["price"] if product.get("variants") else "0"
    handle = product.get("handle", "")
    ptype  = (product.get("product_type") or "women's fashion").lower()
    url    = f"{STORE_URL}/products/{handle}?utm_source=blog&utm_medium=featured_card&utm_campaign=meeeshop" if handle else STORE_URL
    img    = product_img_url(product)

    # Keyword-rich ALT text for inline product image
    alt = f"{raw_title} — {ptype} for women at MeeeShop"
    if keyword:
        alt = f"{raw_title} — {keyword}, {ptype} at MeeeShop"

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


def make_related_products_section(products: list, exclude_handle: str, keyword: str = "", matching_products: list = None) -> str:
    import html
    
    if matching_products:
        picks = matching_products
        section_title = "Shop Styled Pairings from This Article"
        cta_text = "Shop the Look"
    else:
        related = [p for p in products if p.get("handle") != exclude_handle and p.get("images")]
        if not related:
            related = [p for p in products if p.get("handle") != exclude_handle]
        picks = random.sample(related, min(3, len(related)))
        section_title = "You Might Also Love"
        cta_text = "Shop Similar"

    cards_html = ""
    for p in picks:
        raw_title  = p["title"]
        clean_title = clean_product_title(raw_title)
        escaped_title = html.escape(clean_title)
        price  = p["variants"][0]["price"] if p.get("variants") else "0"
        handle = p.get("handle", "")
        ptype  = (p.get("product_type") or "women's fashion").lower()
        url    = f"{STORE_URL}/products/{handle}?utm_source=blog&utm_medium=related_card&utm_campaign=meeeshop"
        img    = product_img_url(p)
        alt    = f"{clean_title} — {ptype} for women at MeeeShop"
        if keyword:
            alt = f"{clean_title} — shop {keyword} at MeeeShop"
        
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
      {cta_text}
    </a>
  </div>"""

    if not cards_html:
        return ""

    return f"""
<div style="margin:48px 0;padding:32px;background:#fafafa;border-radius:14px;border:1px solid #eee;">
  <h2 style="font-size:20px;font-weight:700;color:#1a1a1a;margin:0 0 24px;text-align:center;">
    {section_title}
  </h2>
  <div style="display:flex;flex-wrap:wrap;gap:24px;justify-content:center;">
    {cards_html}
  </div>
</div>
"""


def inject_product_card(html_body: str, product: dict, keyword: str = "") -> str:
    card = make_product_card(product, keyword)
    insert_after = re.search(r"</h1>\s*(<p>.*?</p>)", html_body, re.DOTALL | re.IGNORECASE)
    if insert_after:
        pos = insert_after.end()
        return html_body[:pos] + "\n" + card + html_body[pos:]
    pos = html_body.find("</p>")
    if pos != -1:
        return html_body[:pos+4] + "\n" + card + html_body[pos+4:]
    return card + html_body


# ── Dynamic Collage & Pairing Helpers ──────────────────────────────────────────

def select_styling_matches(main_product: dict, pool: list, num_matches: int = 2) -> list[dict]:
    main_type = (main_product.get("product_type") or "").lower()
    main_id = main_product.get("id")
    
    # Categorize broad clothing types
    is_top = any(x in main_type for x in ["top", "blouse", "shirt", "tee"])
    is_bottom = any(x in main_type for x in ["jean", "pant", "skirt", "legging", "short"])
    is_one_piece = any(x in main_type for x in ["dress", "jumpsuit", "romper"])
    
    matches = []
    
    # Try to find items of complementary types first
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
            
    if len(complementary_pool) >= num_matches:
        matches = random.sample(complementary_pool, num_matches)
    else:
        fallback_pool = [p for p in pool if p.get("id") != main_id and p.get("images")]
        if len(fallback_pool) >= num_matches:
            matches = random.sample(fallback_pool, num_matches)
        else:
            matches = fallback_pool
            
    return matches


def crop_to_fit(img, target_w, target_h):
    """Helper to crop and resize an image to fit target bounds cleanly (center crop)."""
    img_ratio = img.width / img.height
    target_ratio = target_w / target_h
    
    if img_ratio > target_ratio:
        # Image is wider
        new_h = target_h
        new_w = int(img.width * (target_h / img.height))
        img_resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        crop_x = (new_w - target_w) // 2
        return img_resized.crop((crop_x, 0, crop_x + target_w, target_h))
    else:
        # Image is taller
        new_w = target_w
        new_h = int(img.height * (target_w / img.width))
        img_resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        crop_y = (new_h - target_h) // 2
        return img_resized.crop((0, crop_y, target_w, crop_y + target_h))


def generate_outfit_collage(main_product: dict, matching_products: list) -> Path | None:
    """
    Downloads the featured images of the main product and matches,
    creates a beautiful side-by-side outfit collage (1200x630),
    and saves it locally.
    """
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
        
    print(f"  Downloading {len(images_to_load)} images to create styling collage...")
    downloaded_imgs = []
    for url in images_to_load:
        try:
            r = requests.get(url, timeout=15)
            if r.status_code == 200:
                img = Image.open(BytesIO(r.content))
                downloaded_imgs.append(img)
            else:
                print(f"    [!] Failed to download {url[:60]}... (HTTP {r.status_code})")
        except Exception as e:
            print(f"    [!] Error downloading {url[:60]}...: {e}")
            
    if not downloaded_imgs:
        return None
        
    canvas_w, canvas_h = 1200, 630
    collage = Image.new("RGB", (canvas_w, canvas_h), (255, 255, 255))
    
    num_imgs = len(downloaded_imgs)
    
    try:
        if num_imgs == 1:
            img = downloaded_imgs[0]
            img_ratio = img.width / img.height
            target_ratio = canvas_w / canvas_h
            
            if img_ratio > target_ratio:
                new_h = canvas_h
                new_w = int(img.width * (canvas_h / img.height))
                img_resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                crop_x = (new_w - canvas_w) // 2
                img_cropped = img_resized.crop((crop_x, 0, crop_x + canvas_w, canvas_h))
            else:
                new_w = canvas_w
                new_h = int(img.height * (canvas_w / img.width))
                img_resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                crop_y = (new_h - canvas_h) // 2
                img_cropped = img_resized.crop((0, crop_y, canvas_w, crop_y + canvas_h))
                
            collage.paste(img_cropped, (0, 0))
            
        elif num_imgs == 2:
            spacing = 25
            col_w = (canvas_w - (3 * spacing)) // 2
            col_h = canvas_h - (2 * spacing)
            
            for i, img in enumerate(downloaded_imgs):
                img_resized = crop_to_fit(img, col_w, col_h)
                left = spacing + i * (col_w + spacing)
                top = spacing
                collage.paste(img_resized, (left, top))
                
        else:
            spacing = 20
            col_w = (canvas_w - (4 * spacing)) // 3
            col_h = canvas_h - (2 * spacing)
            
            for i, img in enumerate(downloaded_imgs[:3]):
                img_resized = crop_to_fit(img, col_w, col_h)
                left = spacing + i * (col_w + spacing)
                top = spacing
                collage.paste(img_resized, (left, top))
                
        temp_path = Path("collage_temp.jpg")
        collage.save(temp_path, "JPEG", quality=92)
        print(f"  ✓ Collage generated locally: {temp_path.absolute()}")
        return temp_path
    except Exception as e:
        print(f"  [!] Failed to generate image collage: {e}")
        return None


def upload_image_to_shopify(filepath: Path, filename: str) -> str | None:
    """Uploads the generated collage to Shopify Files and fetches its CDN URL."""
    print(f"  Uploading {filename} to Shopify Files...")
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
        
        # Upload the file to staging
        with open(filepath, "rb") as f:
            files = {"file": (filename, f, "image/jpeg")}
            params = {p["name"]: p["value"] for p in target["parameters"]}
            upload_resp = requests.post(target["url"], data=params, files=files, timeout=30)
            upload_resp.raise_for_status()
            
        # Create file reference in Shopify
        create_mut = """
        mutation fileCreate($files: [FileCreateInput!]!) {
          fileCreate(files: $files) {
            files {
              id
              fileStatus
            }
            userErrors {
              message
            }
          }
        }
        """
        variables = {
            "files": [
                {
                    "originalSource": target["resourceUrl"],
                    "contentType": "FILE"
                }
            ]
        }
        r = _req("post", graphql_url, json={"query": create_mut, "variables": variables})
        r.raise_for_status()
        create_data = r.json()
        
        user_errors = create_data.get("data", {}).get("fileCreate", {}).get("userErrors", [])
        if user_errors:
            print(f"  [!] Shopify fileCreate user errors: {user_errors}")
            return None
            
        file_id = create_data["data"]["fileCreate"]["files"][0]["id"]
        
        # Wait for file compilation
        public_url = None
        for _ in range(15):
            time.sleep(2)
            query_file = f"""
            query {{
              node(id: "{file_id}") {{
                ... on GenericFile {{
                  url
                  fileStatus
                }}
              }}
            }}
            """
            r = _req("post", graphql_url, json={"query": query_file})
            r.raise_for_status()
            node_data = r.json()
            node = node_data.get("data", {}).get("node", {})
            if node.get("fileStatus") == "READY":
                public_url = node.get("url")
                break
                
        if public_url:
            cdn_url = public_url.split("?")[0]
            print(f"  ✓ Uploaded successfully: {cdn_url}")
            return cdn_url
        else:
            print("  [!] Timeout waiting for image compilation on Shopify CDN.")
            return None
    except Exception as e:
        print(f"  [!] Failed to upload image to Shopify: {e}")
        return None


# ── Publish ────────────────────────────────────────────────────────────────────
def publish_article(blog: dict, title: str, body_html: str, tags: list,
                    image_url: str, img_alt: str, meta_desc: str,
                    dry_run: bool = False, publish: bool = False,
                    author: str = "Elena Vance, MeeeShop Lead Stylist") -> dict | None:
    if dry_run:
        print(f"  [DRY-RUN] '{title}'")
        print(f"  Blog   : {blog.get('title')}")
        print(f"  Image  : {image_url[:90]}")
        print(f"  ALT    : {img_alt}")
        print(f"  Meta   : {meta_desc[:100]}")
        print(f"  Preview: {re.sub(r'<[^>]+>',' ',body_html)[:160].strip()}…\n")
        return {"id": 0, "title": title}

    payload: dict = {
        "article": {
            "title":        title,
            "body_html":    body_html,
            "summary_html": f"<p>{meta_desc}</p>",
            "tags":         ", ".join(tags),
            "published":    publish,
            "author":       author,
        }
    }
    if image_url:
        payload["article"]["image"] = {
            "src": image_url,
            "alt": img_alt,
        }

    r = _req("post", f"{BASE}/blogs/{blog['id']}/articles.json", json=payload)
    if r.status_code in (200, 201):
        art = r.json().get("article", {})
        print(f"  Published: '{art.get('title')}' (ID {art.get('id')}) → blog '{blog['title']}'")
        return art
    print(f"  FAILED {r.status_code}: {r.text[:200]}")
    return None


# ── High-intent blog formats ───────────────────────────────────────────────────
FORMATS = ["buying_guide", "comparison", "problem_solver", "trend_report", "outfit_formula", "care_guide", "sizing_guide"]

SEED_KEYWORDS = [
    "women's fashion 2026", "affordable women's clothing USA",
    "summer dress outfits for women", "women's jeans styles guide",
    "casual chic outfits women", "women's fashion trends 2026",
    "cute outfits under $50", "stylish women's tops",
    "best dresses for women", "women's summer wardrobe essentials",
    "affordable boutique fashion USA", "women's outfit ideas",
    "how to style women's clothing", "plus size fashion tips",
    "work outfits for women", "women's weekend casual looks",
    "women's spring outfit ideas 2026", "best tops to wear with jeans",
    "how to build a capsule wardrobe women", "women's date night outfit ideas",
    "Zenana women's clothing basics guide", "how to style POL clothing bohemian pieces",
    "Emory Park boutique clothing outfits", "best Judy Blue jeans styles for women",
    "Risen stretch denim jeans review", "Umgee USA clothing styling ideas",
    "Hyfve clothing fashion trends", "Bibi clothing cute outfits",
    "Artemis Vintage denim styles"
]


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


def _lsi_keywords(ptype: str, keyword: str) -> list[str]:
    """Return LSI / secondary keywords relevant to this product type and primary keyword."""
    base_lsi = [
        "women's outfit ideas", "stylish women USA", "affordable fashion",
        "how to style", "women's clothing guide", "USA boutique fashion",
    ]
    ptype_lsi = {
        "dress":      ["summer dress outfits", "flattering dresses women", "dress styles guide", "midi dress", "casual dress"],
        "jean":       ["jeans for women", "best fitting jeans", "denim styles", "high waist jeans", "women's denim guide"],
        "top":        ["tops for women", "blouse styles", "women's shirts", "work tops", "casual tops women"],
        "blouse":     ["blouse outfits", "women's blouse styles", "office blouse", "flowy tops women"],
        "skirt":      ["skirt outfits women", "midi skirt", "mini skirt style", "how to wear skirts"],
        "pant":       ["women's pants guide", "trousers women", "wide leg pants", "work pants women"],
        "jacket":     ["women's jacket outfits", "layering outfits", "blazer women", "casual jacket"],
        "coat":       ["women's coat styles", "winter coat", "trench coat women", "coat outfit ideas"],
        "sweater":    ["cozy sweater outfits", "women's knitwear", "sweater styles", "fall fashion women"],
        "cardigan":   ["cardigan outfits", "layering cardigan", "open front cardigan", "cozy fashion"],
        "swimwear":   ["swimsuit styles women", "bikini guide", "one piece swimsuit", "flattering swimwear"],
        "activewear": ["workout outfit women", "athleisure look", "gym clothes women", "active style"],
        "accessory":  ["women's accessories", "accessory guide", "how to accessorize", "fashion accessories"],
    }
    extras = []
    for k, v in ptype_lsi.items():
        if k in ptype:
            extras = v
            break
    combined = list(dict.fromkeys(extras + base_lsi))[:6]
    return combined


def _build_prompt(fmt: str, product: dict, keyword: str, title_hint: str, similar_products: list | None = None, matching_products: list | None = None) -> tuple[str, str]:
    display_name = get_product_display_name(product)
    clean_ptype = get_clean_product_type(product)
    price  = product["variants"][0]["price"] if product.get("variants") else "49"
    handle = product.get("handle", "")
    url    = f"{STORE_URL}/products/{handle}" if handle else STORE_URL

    lsi    = _lsi_keywords(clean_ptype, keyword)
    lsi_str = ", ".join(f'"{k}"' for k in lsi)

    if similar_products is None:
        similar_products = []
    if matching_products is None:
        matching_products = []

    # Build styling instructions for the collage items to tie image & text together
    match_instr = ""
    if matching_products:
        clean_matches = [get_product_display_name(m) for m in matching_products]
        matches_str = " and ".join([f"'{m_title}' (${m['variants'][0]['price'] if m.get('variants') else '49'})" for m_title, m in zip(clean_matches, matching_products)])
        match_instr = (
            f"- We are featuring a styling lookbook collage showing this product paired with: {matches_str}.\n"
            f"- In the styling or outfit sections of your article, you MUST explicitly mention these matching pieces by name, explaining how to style them together with the main featured product to create a complete, cohesive outfit (e.g., 'pair it with the {clean_matches[0]}' or 'complete this look using the {clean_matches[1]}').\n"
        )

    base = (
        f"You are a fashion editor at MeeeShop, a USA women's clothing boutique.\n"
        f"Write a {MONTH} blog post. Target keyword: '{keyword}'\n"
        f"Feature product: {display_name} — ${price}\n"
        f"Category: {clean_ptype}\n\n"
        f"{EEAT_RULES}"
        f"SEO rules (follow precisely):\n"
        f"- Primary keyword '{keyword}': use 3-4 times naturally — once in H1, once in first paragraph, 1-2 times in body/conclusion\n"
        f"- LSI / secondary keywords to weave in naturally (don't force all, pick what fits): {lsi_str}\n"
        f"- At least 2 of these LSI keywords must appear in H2 subheadings\n"
        f"- Do NOT write or include any HTML links (<a> tags) to the product page or MeeeShop anywhere in the body text. The product card and shop-the-look widgets will be programmatically injected by the system, so manual linking inside the article is redundant and violates SEO guidelines by looking spammy.\n"
        f"- Limit mentions of the product title '{display_name}' to a maximum of 2 times in the entire body. When referring to the product subsequent times, use pronouns or the specific generic term '{clean_ptype}' (e.g., 'this {clean_ptype}', 'the {clean_ptype}', 'it', 'this piece') instead of repeating the full product name.\n"
        f"- H1 title must include year {YEAR} or 'for Women'\n"
        f"- Keyword density: natural reading, never stuffed — if it sounds forced, rephrase\n"
        f"- Answer a real problem women face when shopping for this item\n"
        f"{match_instr}"
        f"- To avoid programmatic footprints, vary your structure. Occasionally include a <blockquote style='border-left: 3px solid #ccc; padding-left: 10px; margin: 15px 0; font-style: italic;'> for a 'Stylist Tip', or distinct visual callouts. Make the flow feel like a hand-written editorial, not a template.\n"
        f"- You MUST include a Shoppers' Q&A section immediately before the final CTA/verdict section. This must consist of:\n"
        f"  <h2>Shoppers' Q&A: Common Questions Answered</h2>\n"
        f"  <h3>Why should the {display_name} be in my closet?</h3>\n"
        f"  <p>[Detailed first-person answer from a stylist explaining why it's a wardrobe staple, 40-50 words]</p>\n"
        f"  <h3>What is the fabric composition and how do I wash this style?</h3>\n"
        f"  <p>[Detailed answer detailing how to wash and maintain the fabric quality, 40-50 words]</p>\n"
        f"  <h3>How do I choose the correct size for the {display_name}?</h3>\n"
        f"  <p>[Actionable advice on sizing fit, body shape guidelines, sizes XS-3X, 40-50 words]</p>\n\n"
        f"Store info: Free US shipping on orders $50+. Easy 7-day returns. Sizes XS-3X.\n\n"
    )

    if fmt == "buying_guide":
        prompt = base + (
            f"Format: Definitive Buying Guide\n"
            f"Write in HTML (<h1>,<h2>,<h3>,<p>,<ul>,<li>):\n"
            f"1. <h1> '{title_hint}'\n"
            f"2. <p> Hook — personal stylist perspective: why I tested the {display_name} and my honest verdict (80 words)\n"
            f"3. <h2> What Makes a Great {clean_ptype.title()}? (4 criteria as <ul><li> bullets with brief real explanations)\n"
            f"4. <h2> Our Featured Recommendation: {display_name} — Honest Review (120 words, first-person stylist review of its cut, drape, fabric, and sizing, do NOT include HTML links)\n"
            f"5. <h2> Curated Style Pairings: 3 Outfit Formulas (H3 subheadings for each outfit, 70 words each with specific styling instructions)\n"
            f"6. <h2> Who Is This {clean_ptype.title()} Perfect For? (50 words — specific body shape, lifestyle, and occasion advice)\n"
            f"7. <h2> Sizing & Fit Verdict (40 words — real fit details, bust/length notes, size availability XS-3X)\n"
            f"8. <p> Warm stylist verdict + CTA to shop (mention price, free US shipping on orders $50+, 7-day easy returns, do NOT include HTML links)\n"
            f"Target: 750-900 words. Output ONLY clean HTML, no markdown code fences."
        )

    elif fmt == "comparison":
        real_alts = [
            p for p in similar_products
            if p.get('handle') != product.get('handle') and p.get('images')
        ][:2]
        if len(real_alts) < 2:
            # Fallback: any 2 other products
            real_alts = [
                p for p in similar_products
                if p.get('handle') != product.get('handle')
            ][:2]
        alt1_display = get_product_display_name(real_alts[0]) if real_alts else "a similar style"
        alt1_price = real_alts[0]['variants'][0]['price'] if (real_alts and real_alts[0].get('variants')) else "49"
        alt2_display = get_product_display_name(real_alts[1]) if len(real_alts) > 1 else "another option"
        alt2_price = real_alts[1]['variants'][0]['price'] if (len(real_alts) > 1 and real_alts[1].get('variants')) else "49"
        
        prompt = base + (
            f"Format: Comparison Article — helps women choose the right style\n"
            f"Write in HTML:\n"
            f"1. <h1> '{title_hint}'\n"
            f"2. <p> Intro — 'I get asked this question every week from our customers: how does {display_name} compare to other styles?' (70 words, empathetic stylist perspective)\n"
            f"3. <h2> Option 1: {display_name} — What I Love + Who It's For (100 words, detailed stylist analysis of the drape and cut, do NOT include HTML links)\n"
            f"4. <h2> Option 2: {alt1_display} — Pros, Cons, and Styling Fit (80 words). Price: ${alt1_price}\n"
            f"5. <h2> Option 3: {alt2_display} — Pros, Cons, and Styling Fit (80 words). Price: ${alt2_price}\n"
            f"6. <h2> Quick Styling Comparison (HTML table: Style | Best For | Price Range | Fabric Draping Winner)\n"
            f"7. <h2> My Honest Verdict — The Winner for Most Women (80 words, stylist recommendation)\n"
            f"8. <p> CTA to shop {display_name} at MeeeShop + price, free shipping on orders $50+, easy returns, do NOT include HTML links\n"
            f"Target: 750-900 words. Output ONLY clean HTML."
        )

    elif fmt == "problem_solver":
        problems = {
            "dress":      "finding a flattering dress that works for multiple occasions without breaking the budget",
            "jean":       "finding jeans that actually fit your body type perfectly",
            "top":        "building a versatile work-to-weekend wardrobe on a budget",
            "blouse":     "finding a blouse that's polished enough for work but fun enough for weekends",
            "pant":       "finding pants that look amazing and feel comfortable all day long",
            "skirt":      "styling a skirt confidently for every occasion without overthinking it",
            "sweater":    "staying stylish and warm without looking frumpy in the cold months",
            "cardigan":   "layering outfits that look intentional, not sloppy",
            "jacket":     "layering outfits without looking bulky or adding too much volume",
            "coat":       "finding a coat that's practical in the cold but still looks chic",
            "swimwear":   "finding a swimsuit that flatters your figure and makes you feel confident",
            "activewear": "finding workout clothes that look great enough to wear all day",
        }
        problem = next(
            (v for k, v in problems.items() if k in clean_ptype or k in display_name.lower()),
            "dressing well on a budget without sacrificing style or looking like everyone else",
        )
        prompt = base + (
            f"Format: Problem-Solver — solving '{problem}' for women\n"
            f"Write in HTML:\n"
            f"1. <h1> '{title_hint}'\n"
            f"2. <p> Opening — 'I hear this from our customers constantly: {problem}' (80 words, empathetic, validating, from a professional stylist's view)\n"
            f"3. <h2> Why This Styling Struggle Is So Frustrating (and More Common Than You Think) (60 words)\n"
            f"4. <h2> The Solution: {display_name} — Here's Exactly Why It Works (120 words, first-person stylist perspective on how the fabric/cut solves the problem, do NOT include HTML links)\n"
            f"5. <h2> 3 Curated Outfit Solutions (H3 for each occasion, 70 words each with specific styling instructions)\n"
            f"6. <h2> My Top 4 Styling Tips From Years in Fashion (bullet list, specific and actionable, not generic)\n"
            f"7. <p> Warm stylist recommendation to shop the {display_name} + price + free US shipping + returns reminder, do NOT include HTML links\n"
            f"Target: 700-850 words. Output ONLY clean HTML."
        )

    elif fmt == "trend_report":
        prompt = base + (
            f"Format: {MONTH} Trend Report — what real women are actually wearing\n"
            f"Write in HTML:\n"
            f"1. <h1> '{title_hint}'\n"
            f"2. <p> Intro — 'I've been tracking what real women are actually wearing, not just runways' (70 words, authentic stylist voice)\n"
            f"3. Five trends, each as <h2> with trend name + 90-word description:\n"
            f"   - Trend #1 MUST be {display_name} (do NOT include HTML links)\n"
            f"   - Trends #2-5: invent 4 real, current women's fashion micro-trends for {MONTH}\n"
            f"   - Each trend: what it is, why it's trending, how to wear it, who it's for\n"
            f"4. <h2> How to Mix These Trends Without Looking Overdone (60 words, practical)\n"
            f"5. <p> Shop the trends at MeeeShop, featured piece {display_name} + price, free shipping, do NOT include HTML links\n"
            f"Target: 750-900 words. Output ONLY clean HTML."
        )

    elif fmt == "care_guide":
        prompt = base + (
            f"Format: Fabric Care & Washing Guide\n"
            f"Write in HTML:\n"
            f"1. <h1> '{title_hint}'\n"
            f"2. <p> Intro — Why taking care of your {clean_ptype} properly is essential to preserve fits, fabric drapes, and colors (70 words)\n"
            f"3. <h2> Fabric Care Label Analysis (provide a detailed explanation of caring for {clean_ptype} fabric blends like polyester/spandex or rayon/linen blends)\n"
            f"4. <h2> Step-by-Step Washing Instructions (H3 Machine Wash vs. H3 Hand Washing instructions, including safe temperatures and detergents)\n"
            f"5. <h2> How to Dry and Iron Without Damage (discuss air drying vs. tumble drying to prevent shrinking, and safe steam/iron settings)\n"
            f"6. <h2> Stylist Care & Storage Tips (how to hang or fold to maintain shape and avoid stretching the fabric)\n"
            f"7. <p> Warm editor CTA to shop new arrivals including the {display_name} with free US shipping & 7-day easy returns, do NOT include HTML links\n"
            f"Target: 700-850 words. Output ONLY clean HTML."
        )

    elif fmt == "sizing_guide":
        prompt = base + (
            f"Format: Sizing & Fit Guide\n"
            f"Write in HTML:\n"
            f"1. <h1> '{title_hint}'\n"
            f"2. <p> Intro — The common struggle of online clothing sizing and how to get the perfect fit (70 words)\n"
            f"3. <h2> Understanding Sizing for this style (explain standard measurements, size ranges XS-3X, and comparison to general US sizes)\n"
            f"4. <h2> Fit Review by Body Shapes (H3 Petite Fit, H3 Hourglass, H3 Plus Size / Curvy, with real fit notes for bust/chest and length)\n"
            f"5. <h2> Fabric Stretch & Draping Factor (describe the fabric blend stretchiness and comfort levels when worn)\n"
            f"6. <h2> Stylist Sizing Recommendation (honest verdict on whether to buy your usual size or size up/down in the {display_name})\n"
            f"7. <p> CTA to shop the collection with free shipping on orders $50+ & easy 7-day returns, do NOT include HTML links\n"
            f"Target: 700-850 words. Output ONLY clean HTML."
        )

    else:  # outfit_formula
        prompt = base + (
            f"Format: 5-Outfit Formula — shows versatility of one piece\n"
            f"Write in HTML:\n"
            f"1. <h1> '{title_hint}'\n"
            f"2. <p> Intro — 'The best fashion investment is a piece you can wear 5 different ways. I put the {display_name} to the real-life test.' (70 words, first-person, engaging, do NOT include HTML links)\n"
            f"3. Five outfits as <h2> sections with creative occasion names:\n"
            f"   e.g. 'Look 1: Sunday Farmers Market', 'Look 2: Office Polished', 'Look 3: Date Night'\n"
            f"   Each: specific items to pair it with, where to wear it, personal styling note (80-90 words)\n"
            f"4. <h2> Fit & Sizing Notes — The Honest Truth (40 words, specific body-type advice)\n"
            f"5. <p> CTA: get yours, price, 7-day returns, limited sizes urgency, do NOT include HTML links\n"
            f"Target: 750-900 words. Output ONLY clean HTML."
        )

    # Append SEO metadata instructions to the prompt so we generate all details in one AI call
    prompt += (
        f"\n\nAt the very end of your response, after the HTML content, you MUST append a `<seometa>` section containing the SEO metadata. The format MUST be exactly like this (use these exact keys):\n"
        f"<seometa>\n"
        f"SEO_TITLE: [50-60 chars, keyword near start, year or 'for Women', compelling]\n"
        f"META_DESC: [140-155 chars, action-oriented, includes keyword, free shipping mention, ends with CTA]\n"
        f"IMG_ALT: [descriptive ALT text for featured image, 10-15 words, includes keyword + 'women' + product type, no quotes]\n"
        f"</seometa>\n"
        f"Make sure there are no other text or markdown code fences enclosing the <seometa> block."
    )

    return prompt, title_hint


def _extract_h1(html: str, fallback: str) -> str:
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.IGNORECASE | re.DOTALL)
    return re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else fallback


def _clean_html(raw: str) -> str:
    raw = raw.strip()
    raw = re.sub(r"^```html?\s*", "", raw, flags=re.IGNORECASE)
    return re.sub(r"\s*```$", "", raw).strip()


def _make_tags(product: dict, fmt: str, keyword: str) -> list[str]:
    base_tags = ["fashion", "women fashion", "MeeeShop", "USA fashion",
                 "women's clothing", "affordable fashion", "style tips"]
    ptype = (product.get("product_type") or "").lower()
    fmt_tags = {
        "buying_guide":   ["buying guide", "fashion guide", f"best picks {YEAR}"],
        "comparison":     ["fashion comparison", "style guide", "what to buy"],
        "problem_solver": ["styling advice", "outfit help", "fashion tips"],
        "trend_report":   [f"fashion trends {YEAR}", "trending styles", "new in fashion"],
        "outfit_formula": ["outfit ideas", "how to style", "outfit inspiration"],
    }
    tags = base_tags + fmt_tags.get(fmt, [])
    if ptype:
        tags.append(ptype)
    # Primary keyword words as tags
    tags += [w for w in keyword.split() if len(w) > 3][:3]
    # Top LSI keywords as tags (short ones work best as Shopify tags)
    lsi = _lsi_keywords(ptype, keyword)
    tags += [k for k in lsi if len(k) < 30][:4]
    return list(dict.fromkeys(tags))[:20]


def clean_product_title(title: str) -> str:
    """Removes formatting chars like *, quotes, and trailing details."""
    t = re.sub(r'[*"\']', '', title)
    t = re.sub(r'\s*\([^)]+\)\s*$', '', t)
    t = re.sub(r'\s*-\s*[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s*$', '', t)
    return t.strip()


def get_product_display_name(product: dict) -> str:
    """Returns a clean display name with vendor (if not already in title)."""
    vendor = (product.get("vendor") or "").strip()
    title = product.get("title", "").strip()
    clean_title = clean_product_title(title)
    if vendor and vendor.lower() not in clean_title.lower():
        return f"{vendor} {clean_title}"
    return clean_title


def get_clean_product_type(product: dict) -> str:
    """Infers a clean singular product type name from title or type."""
    title = product.get("title", "").lower()
    ptype = (product.get("product_type") or "").lower()
    
    # Specific overrides
    if "skort" in title:
        return "skort"
    if "jort" in title:
        return "jort"
    if "short" in title:
        return "shorts"
    if "jean" in title:
        return "jeans"
    if "denim" in title:
        return "denim"
    if "jacket" in title:
        return "jacket"
    if "coat" in title:
        return "coat"
    if "cardigan" in title:
        return "cardigan"
    if "sweater" in title:
        return "sweater"
    if "dress" in title:
        return "dress"
    if "blouse" in title:
        return "blouse"
    if "shirt" in title:
        return "shirt"
    if "tee" in title or "t-shirt" in title:
        return "t-shirt"
    if "top" in title:
        return "top"
    if "pant" in title:
        return "pants"
    if "skirt" in title:
        return "skirt"
    if "bag" in title or "handbag" in title:
        return "handbag"
        
    # Standardizations
    if "jean" in ptype or "denim" in ptype:
        return "jeans"
    if "dress" in ptype:
        return "dress"
    if "top" in ptype or "blouse" in ptype or "shirt" in ptype:
        return "top"
    if "sweater" in ptype or "cardigan" in ptype or "knit" in ptype:
        return "knitwear"
    if "skirt" in ptype:
        return "skirt"
    if "pant" in ptype:
        return "pants"
    if "bag" in ptype or "handbag" in ptype:
        return "handbag"
        
    return ptype if ptype else "apparel"


def generate_keyword_title_and_format(product: dict, format_override: str = None) -> tuple[str, str, str]:
    display_name = get_product_display_name(product)
    
    options = [
        (f"{display_name} sizing", f"Is {display_name} True to Size? Sizing & Fit Guide for {YEAR}", "sizing_guide"),
        (f"how to style {display_name}", f"5 Stunning Outfits You Can Build Around {display_name}", "outfit_formula"),
        (f"{display_name} review", f"The Best {display_name} for Women in {YEAR}: Our Editor's Guide", "buying_guide"),
        (f"styling {display_name}", f"{MONTH} Women's Fashion Trends: How to Style the {display_name}", "trend_report"),
        (f"how to wash {display_name}", f"How to Wash and Care for Your {display_name} ({YEAR} Style Guide)", "care_guide"),
        (f"{display_name} styling", f"How to Style the {display_name} for Casual Chic Outfits", "problem_solver")
    ]
    
    if format_override:
        matched = [opt for opt in options if opt[2] == format_override]
        if matched:
            return matched[0]
            
    # Weights: sizing_guide (10%), outfit_formula (25%), buying_guide (20%), trend_report (20%), care_guide (5%), problem_solver (20%)
    weights = [0.10, 0.25, 0.20, 0.20, 0.05, 0.20]
    return random.choices(options, weights=weights, k=1)[0]


# ── main ──────────────────────────────────────────────────────────────────────
def run(count: int = 1, dry_run: bool = False, publish: bool = False, format_override: str = None):
    print(f"\n{'='*62}")
    print(f"  MeeeShop Blog Automation — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  Posts: {count} | Dry-run: {dry_run} | Publish: {publish} | Format: {format_override or 'weighted random'}")
    print(f"{'='*62}\n")

    print("Fetching products…")
    products = fetch_products(limit=100)
    if not products:
        sys.exit("ERROR: No products returned from Shopify.")
    products_with_imgs = [p for p in products if p.get("images")]
    # Strictly restrict pool to products with images to ensure high quality for Discover
    pool = products_with_imgs
    if not pool:
        sys.exit("ERROR: No products with images found in Shopify. Cannot generate Discover-ready blog posts without product images.")
    if len(pool) < count:
        print(f"  [Warning] Only found {len(pool)} products with images, but requested {count} posts. Adjusting count to {len(pool)}.")
        count = len(pool)
    print(f"  {len(products)} products ({len(products_with_imgs)} with images used as pool)\n")

    all_blogs = get_all_blogs()
    print(f"  Available blogs: {[b['title'] for b in all_blogs]}\n")

    chosen   = random.sample(pool, min(count, len(pool)))

    created = 0
    for i, product in enumerate(chosen):
        keyword, title_hint, fmt = generate_keyword_title_and_format(product, format_override)

        print(f"[{i+1}/{count}] Format: {fmt} | Keyword: '{keyword}'")
        print(f"  Product: {product['title'][:70]}")
        print(f"  Type   : {product.get('product_type', 'unknown')}")

        blog = get_or_create_blog(product.get("product_type", ""), all_blogs, dry_run)
        print(f"  Blog   : {blog['title']}")

        # Select styling matches first so we can feed them into the prompt, ONLY for styling formats
        is_styling_format = fmt in ["outfit_formula", "buying_guide", "trend_report", "problem_solver"]
        if is_styling_format:
            matching_products = select_styling_matches(product, pool, num_matches=2)
        else:
            matching_products = []

        # Generate content — pass full pool and matching products for cohesion
        prompt, h1_hint = _build_prompt(fmt, product, keyword, title_hint, similar_products=pool, matching_products=matching_products)
        print("  Generating content…")
        html_body = ai_client.generate(prompt, max_tokens=1600, temperature=0.75)

        if not html_body:
            print("  [AI] all providers failed — skipping\n")
            continue

        # Extract <seometa> block if present
        seo_text = ""
        seo_match = re.search(r"<seometa>(.*?)</seometa>", html_body, re.DOTALL | re.IGNORECASE)
        if seo_match:
            seo_text = seo_match.group(1).strip()
            # Remove the <seometa> block from body
            html_body = html_body[:seo_match.start()] + html_body[seo_match.end():]
        else:
            # Inline detection fallback if tags were omitted
            lines = html_body.splitlines()
            cleaned_lines = []
            seo_lines = []
            for line in lines:
                l_upper = line.strip().upper()
                if l_upper.startswith("SEO_TITLE:") or l_upper.startswith("META_DESC:") or l_upper.startswith("IMG_ALT:"):
                    seo_lines.append(line)
                elif "seometa" not in line.lower():
                    cleaned_lines.append(line)
            if seo_lines:
                seo_text = "\n".join(seo_lines)
                html_body = "\n".join(cleaned_lines)

        html_body = _clean_html(html_body)
        post_title = _extract_h1(html_body, h1_hint)

        print("  Extracting SEO metadata…")
        ptype = (product.get("product_type") or "women's fashion").lower()
        seo   = parse_and_clean_seo_meta(seo_text, keyword, product["title"], ptype)
        print(f"  SEO title : {seo['seo_title']}")
        print(f"  Meta desc : {seo['meta_desc'][:80]}…")
        print(f"  IMG ALT   : {seo['img_alt']}")
        collage_path = None
        img_url = None
        
        if is_styling_format and matching_products:
            collage_path = generate_outfit_collage(product, matching_products)
            if collage_path and collage_path.exists():
                if not dry_run:
                    ts = int(time.time())
                    filename = f"styling_collage_{product['id']}_{ts}.jpg"
                    img_url = upload_image_to_shopify(collage_path, filename)
                    try:
                        collage_path.unlink()
                    except Exception:
                        pass
                else:
                    img_url = f"file:///{collage_path.absolute().as_posix()}"
                    
        if not img_url:
            img_url = make_featured_image_url(product, fmt)
            img_src = "Shopify CDN 1200x630 (Single product fallback)"
        else:
            img_src = f"Shopify CDN 1200x630 (Outfit Collage of {1 + len(matching_products)} products)"
            
        print(f"  Featured Image : {img_src}")
        if img_url:
            print(f"  Image URL      : {img_url[:90]}...")

        # Inject featured product card + related products
        html_body = inject_product_card(html_body, product, keyword)
        html_body += make_related_products_section(products, product.get("handle", ""), keyword, matching_products if is_styling_format else None)

        tags = _make_tags(product, fmt, keyword)
        print(f"  Title     : {post_title[:80]}")

        # Select fictional author pseudonym for E-E-A-T
        PEN_NAMES = [
            "Elena Vance, MeeeShop Lead Stylist",
            "Seraphina Croft, MeeeShop Fashion Editor",
            "Audrey Sterling, MeeeShop Style Director",
            "Maya Devereaux, MeeeShop Fashion Consultant",
            "Vivienne Vance, MeeeShop Senior Stylist",
            "Genevieve Thorne, MeeeShop Trend Forecaster"
        ]
        author_name = random.choice(PEN_NAMES)
        print(f"  Author    : {author_name}")

        # Publish (or save as draft)
        status_label = "live" if publish else "DRAFT (review in Shopify Admin before publishing)"
        print(f"  Status    : {status_label}")
        article = publish_article(
            blog, post_title, html_body, tags,
            img_url, seo["img_alt"], seo["meta_desc"],
            dry_run, publish=publish, author=author_name
        )

        # Set SEO metafields (title_tag + description_tag) after creation
        if article and not dry_run and article.get("id"):
            set_article_seo_metafields(blog["id"], article["id"],
                                       seo["seo_title"], seo["meta_desc"])

        if article:
            created += 1
        print()
        time.sleep(1.0)

    result_label = "published live" if publish else "saved as DRAFT"
    print(f"Done — {created}/{count} blog posts {result_label}.")
    if not dry_run:
        if publish:
            print(f"View at: https://{SHOP}/blogs\n")
        else:
            print(f"Review drafts at: https://{SHOP}/admin/articles\n")
            print("Tip: add --publish flag to go live immediately (use after reviewing content)\n")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="MeeeShop Google Discover blog generator")
    ap.add_argument("--dry-run",  action="store_true", help="Print only, no publishing")
    ap.add_argument("--count",    type=int, default=1,  help="Number of posts to create (default 1)")
    ap.add_argument("--publish",  action="store_true",
                    help="Publish immediately (default: save as DRAFT for human review)")
    ap.add_argument("--format",   type=str, default=None,
                    choices=["sizing_guide", "outfit_formula", "buying_guide", "trend_report", "care_guide", "problem_solver"],
                    help="Force a specific blog format (default: weighted choice)")
    args = ap.parse_args()
    run(count=args.count, dry_run=args.dry_run, publish=args.publish, format_override=args.format)

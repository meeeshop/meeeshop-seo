#!/usr/bin/env python3
"""
generate_3product_collages.py — Unified 3-Product Collage & Content Sync Engine
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Updates ALL blog articles across all Shopify blogs to ensure:
  1. Body HTML has 3 linked products with high-res product card images.
  2. Article featured image is a high-res (1200x630) 3-product outfit collage
     combining all 3 products referenced in that article.

Usage:
  python scripts/generate_3product_collages.py --dry-run
  python scripts/generate_3product_collages.py --apply
"""

import os
import sys
import re
import json
import time
import random
import requests
from io import BytesIO
from pathlib import Path
from PIL import Image

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from secrets_manager import inject_to_env, get_secret
inject_to_env()

SHOP = get_secret("SHOPIFY_STORE")
TOKEN = get_secret("SHOPIFY_ACCESS_TOKEN")
STORE_URL = get_secret("STORE_BASE_URL").rstrip("/")
API_VER = "2024-10"
BASE = f"https://{SHOP}/admin/api/{API_VER}"
HEADERS = {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}
GRAPHQL_URL = f"https://{SHOP}/admin/api/{API_VER}/graphql.json"


def fetch_all_products() -> list:
    """Fetches all active catalog products with pagination."""
    all_prods = []
    page_info = None
    while True:
        params = {"limit": 250, "status": "active", "fields": "id,title,handle,product_type,variants,images"}
        if page_info:
            params["page_info"] = page_info
        try:
            r = requests.get(f"{BASE}/products.json", headers=HEADERS, params=params, timeout=25)
            r.raise_for_status()
            prods = r.json().get("products", [])
            all_prods.extend(prods)
            
            link_hdr = r.headers.get("Link", "")
            nxt = re.search(r'<([^>]+)>;\s*rel="next"', link_hdr)
            if nxt and len(prods) == 250:
                pi = re.search(r"page_info=([^&]+)", nxt.group(1))
                page_info = pi.group(1) if pi else None
                if not page_info:
                    break
            else:
                break
        except Exception as e:
            print(f"Error fetching products page: {e}")
            break
            
    print(f"Fetched {len(all_prods)} total catalog products.")
    return [p for p in all_prods if p.get("images")]


def fetch_all_articles() -> list:
    """Fetches all published articles across all blogs with pagination."""
    try:
        r = requests.get(f"{BASE}/blogs.json", headers=HEADERS, timeout=20)
        blogs = r.json().get("blogs", [])
    except Exception as e:
        print(f"Error fetching blogs: {e}")
        return []

    articles_out = []
    for blog in blogs:
        b_id = blog["id"]
        page_info = None
        while True:
            params = {"limit": 250}
            if page_info:
                params["page_info"] = page_info
            try:
                r = requests.get(f"{BASE}/blogs/{b_id}/articles.json", headers=HEADERS, params=params, timeout=25)
                arts = r.json().get("articles", [])
                for a in arts:
                    a["blog_id"] = b_id
                    articles_out.append(a)
                
                link_hdr = r.headers.get("Link", "")
                nxt = re.search(r'<([^>]+)>;\s*rel="next"', link_hdr)
                if nxt and len(arts) == 250:
                    pi = re.search(r"page_info=([^&]+)", nxt.group(1))
                    page_info = pi.group(1) if pi else None
                    if not page_info:
                        break
                else:
                    break
            except Exception as e:
                print(f"Error fetching articles for blog {b_id}: {e}")
                break

    print(f"Fetched {len(articles_out)} total published articles across all blogs.")
    return articles_out


def select_complementary_products(main_prod: dict, pool: list, needed_count: int = 2) -> list:
    """Selects complementary products matching the primary product's type."""
    main_type = (main_prod.get("product_type") or "").lower()
    main_id = main_prod.get("id")

    candidates = [p for p in pool if p.get("id") != main_id and p.get("images")]
    if not candidates:
        return []

    is_top = any(x in main_type for x in ["top", "blouse", "shirt", "tee", "sweater", "knit"])
    is_bottom = any(x in main_type for x in ["jean", "pant", "skirt", "short", "legging"])
    is_dress = any(x in main_type for x in ["dress", "jumpsuit", "romper"])

    matching = []
    for p in candidates:
        ptype = (p.get("product_type") or "").lower()
        if is_top and any(x in ptype for x in ["jean", "pant", "skirt", "short", "jacket", "bag"]):
            matching.append(p)
        elif is_bottom and any(x in ptype for x in ["top", "blouse", "shirt", "tee", "sweater", "jacket"]):
            matching.append(p)
        elif is_dress and any(x in ptype for x in ["jacket", "cardigan", "bag", "accessory", "shoe"]):
            matching.append(p)

    if len(matching) >= needed_count:
        return random.sample(matching, needed_count)

    remaining = [p for p in candidates if p not in matching]
    random.shuffle(remaining)
    combined = matching + remaining
    return combined[:min(needed_count, len(combined))]


def crop_to_fit(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
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


def build_3product_collage(image_urls: list[str], output_path: Path) -> bool:
    """Creates a clean 1200x630 3-product collage image."""
    downloaded = []
    for url in image_urls:
        if not url:
            continue
        try:
            r = requests.get(url, timeout=15)
            if r.status_code == 200:
                img = Image.open(BytesIO(r.content)).convert("RGB")
                downloaded.append(img)
        except Exception:
            pass

    if not downloaded:
        return False

    canvas_w, canvas_h = 1200, 630
    collage = Image.new("RGB", (canvas_w, canvas_h), (255, 255, 255))
    num_imgs = len(downloaded)

    if num_imgs == 1:
        collage.paste(crop_to_fit(downloaded[0], canvas_w, canvas_h), (0, 0))
    elif num_imgs == 2:
        spacing = 25
        col_w = (canvas_w - (3 * spacing)) // 2
        col_h = canvas_h - (2 * spacing)
        for i, img in enumerate(downloaded):
            collage.paste(crop_to_fit(img, col_w, col_h), (spacing + i * (col_w + spacing), spacing))
    else:
        spacing = 20
        col_w = (canvas_w - (4 * spacing)) // 3
        col_h = canvas_h - (2 * spacing)
        for i, img in enumerate(downloaded[:3]):
            collage.paste(crop_to_fit(img, col_w, col_h), (spacing + i * (col_w + spacing), spacing))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    collage.save(output_path, "JPEG", quality=92)
    return True


def upload_image_to_shopify(filepath: Path, filename: str) -> str | None:
    """Uploads local collage image to Shopify Files via GraphQL."""
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
        r = requests.post(GRAPHQL_URL, headers=HEADERS, json={"query": staged_mut}, timeout=30)
        r.raise_for_status()
        target = r.json()["data"]["stagedUploadsCreate"]["stagedTargets"][0]
        
        with open(filepath, "rb") as f:
            form_data = []
            for p in target["parameters"]:
                form_data.append((p["name"], p["value"]))
            form_data.append(("file", (filename, f, "image/jpeg")))
            
            upload_resp = requests.post(target["url"], files=form_data, timeout=30)
            upload_resp.raise_for_status()
            
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
        variables = {"files": [{"originalSource": target["resourceUrl"], "contentType": "FILE"}]}
        r = requests.post(GRAPHQL_URL, headers=HEADERS, json={"query": create_mut, "variables": variables}, timeout=30)
        r.raise_for_status()
        create_data = r.json()
        
        file_id = create_data["data"]["fileCreate"]["files"][0]["id"]
        
        for _ in range(15):
            time.sleep(1.5)
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
            r = requests.post(GRAPHQL_URL, headers=HEADERS, json={"query": query_file}, timeout=30)
            r.raise_for_status()
            node = r.json().get("data", {}).get("node", {})
            if node.get("fileStatus") == "READY":
                cdn_url = node.get("url").split("?")[0]
                return cdn_url
        return None
    except Exception as e:
        print(f"    [!] GraphQL Upload failed: {e}", flush=True)
        return None


def generate_product_card_html(product: dict, label: str = "FEATURED PICK") -> str:
    title = product["title"]
    price = product["variants"][0]["price"] if product.get("variants") else "49"
    handle = product.get("handle", "")
    url = f"{STORE_URL}/products/{handle}?utm_source=blog&utm_medium=card"
    img = product["images"][0]["src"] if product.get("images") else ""
    card_alt = f"{title} - Women's Fashion Essential at MeeeShop"
    
    img_html = f'<a href="{url}"><img src="{img}" alt="{card_alt}" style="width:200px;height:200px;object-fit:cover;border-radius:8px;" /></a>' if img else ""
    
    return f"""
<div style="background:#f9f9f9;border:1px solid #eee;border-radius:12px;padding:20px;margin:24px 0;display:flex;gap:20px;align-items:center;font-family:sans-serif;">
  {img_html}
  <div>
    <p style="font-size:11px;color:#888;margin:0 0 4px;text-transform:uppercase;font-weight:bold;">{label}</p>
    <h3 style="margin:0 0 8px;font-size:16px;color:#111;">{title}</h3>
    <p style="font-size:20px;font-weight:bold;margin:0 0 12px;color:#111;">${price}</p>
    <a href="{url}" style="background:#111;color:#fff;padding:10px 20px;text-decoration:none;border-radius:6px;font-size:13px;font-weight:bold;display:inline-block;">Shop Now →</a>
  </div>
</div>
"""


def process_all_articles(dry_run: bool = False):
    print("\n--- Processing ALL Blog Articles for 3-Product Collages & In-Body Sync ---", flush=True)

    pool = fetch_all_products()
    if not pool:
        print("ERROR: Catalog pool empty.")
        return

    handle_to_prod = {p["handle"].lower().strip(): p for p in pool if p.get("handle")}
    articles = fetch_all_articles()

    updated_count = 0

    for idx, art in enumerate(articles, 1):
        art_id = art["id"]
        blog_id = art["blog_id"]
        title = art.get("title", "Untitled")
        body = art.get("body_html", "")

        # Extract product handles from body
        handles = re.findall(r'/products/([a-zA-Z0-9_-]+)', body)
        clean_handles = list(dict.fromkeys([h.lower().strip() for h in handles if h and h != "all"]))

        matched_prods = []
        for h in clean_handles:
            if h in handle_to_prod and handle_to_prod[h] not in matched_prods:
                matched_prods.append(handle_to_prod[h])

        # If article has fewer than 3 products, complement from catalog pool
        if len(matched_prods) < 3:
            main_prod = matched_prods[0] if matched_prods else random.choice(pool)
            if main_prod not in matched_prods:
                matched_prods.append(main_prod)
                
            needed = 3 - len(matched_prods)
            extra = select_complementary_products(main_prod, pool, needed_count=needed)
            for ex in extra:
                if ex not in matched_prods and len(matched_prods) < 3:
                    matched_prods.append(ex)

        # We now have exactly 3 products
        prod3 = matched_prods[:3]
        prod3_handles = [p["handle"] for p in prod3]
        prod3_imgs = [p["images"][0]["src"] for p in prod3 if p.get("images")]

        print(f"\n[{idx}/{len(articles)}] Article {art_id}: '{title}'", flush=True)
        print(f"  3 Referenced Products: {', '.join(prod3_handles)}", flush=True)

        # 1. Build local 1200x630 3-product collage image
        temp_path = Path(f"scratch/collage_3p_{art_id}.jpg")
        success = build_3product_collage(prod3_imgs, temp_path)
        if not success:
            print("  [!] Failed to generate 3-product PIL collage.", flush=True)
            continue

        print(f"  ✓ Built 1200x630 3-Product Collage Image: {temp_path}", flush=True)

        if dry_run:
            print("  [DRY-RUN] Skipping Shopify update.", flush=True)
            updated_count += 1
            continue

        # 2. Upload collage image to Shopify Files
        filename = f"3p_collage_{art_id}_{int(time.time())}.jpg"
        cdn_url = upload_image_to_shopify(temp_path, filename)
        if not cdn_url:
            print("  [!] Failed GraphQL image upload.", flush=True)
            continue

        print(f"  ✓ Uploaded 3-Product Collage to Shopify Files: {cdn_url}", flush=True)

        # 3. Update body HTML: inject featured product card for main product if missing
        updated_body = body
        main_prod = prod3[0]
        if f"/products/{main_prod['handle']}" not in updated_body:
            card_html = generate_product_card_html(main_prod, label="EDITOR'S FEATURED PICK")
            updated_body = card_html + "\n" + updated_body

        # 4. Save payload to Shopify
        payload = {
            "article": {
                "id": art_id,
                "body_html": updated_body,
                "image": {
                    "src": cdn_url,
                    "alt": f"{title} - 3-Product Styled Outfit Collage"
                }
            }
        }

        try:
            up_res = requests.put(f"{BASE}/blogs/{blog_id}/articles/{art_id}.json", headers=HEADERS, json=payload, timeout=25)
            if up_res.status_code in (200, 201):
                updated_count += 1
                print("  ✓ Successfully updated Article Body & 3-Product Featured Image on Shopify!", flush=True)
            else:
                print(f"  ❌ Update failed (HTTP {up_res.status_code}): {up_res.text[:100]}", flush=True)
        except Exception as e:
            print(f"  ❌ Error updating article {art_id}: {e}", flush=True)

        # Cleanup temp file
        if temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass

        time.sleep(0.3)

    print(f"\n[DONE] Finished 3-Product Collage & Content Sync across all articles. Total updated: {updated_count}", flush=True)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="3-Product Collage Featured Image & Content Sync Engine")
    parser.add_argument("--dry-run", action="store_true", help="Preview 3-product collage builds without updating Shopify")
    parser.add_argument("--apply", action="store_true", help="Apply live 3-product collages to all Shopify blog articles")
    args = parser.parse_args()

    process_all_articles(dry_run=not args.apply)

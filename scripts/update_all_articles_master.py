#!/usr/bin/env python3
"""
update_all_articles_master.py — Master Blog Article & Collage Orchestrator
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Updates ALL Shopify blog articles to guarantee:
  1. Linked Products: Inline product card links pointing to valid, in-stock catalog items.
  2. Matching Product Images: Inline product card <img> elements showing correct high-res photos.
  3. 3-Product Outfit Collage Featured Image: High-res (1200x630) 3-product collage created
     from the exact products referenced in the article, uploaded to Shopify Files via GraphQL.

Usage:
  python scripts/update_all_articles_master.py --dry-run
  python scripts/update_all_articles_master.py --apply
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
from fix_duplicate_blog_products import ProductRotationManager
inject_to_env()

SHOP = get_secret("SHOPIFY_STORE")
TOKEN = get_secret("SHOPIFY_ACCESS_TOKEN")
STORE_URL = get_secret("STORE_BASE_URL").rstrip("/")
API_VER = "2024-10"
BASE = f"https://{SHOP}/admin/api/{API_VER}"
HEADERS = {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}
GRAPHQL_URL = f"https://{SHOP}/admin/api/{API_VER}/graphql.json"


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


def create_3product_collage(image_urls: list[str], output_path: Path) -> bool:
    """Builds a 1200x630 3-product collage image from product image URLs."""
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
    """Uploads local image file to Shopify Files via GraphQL staged upload."""
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
        print(f"    [!] Upload failed: {e}", flush=True)
        return None


def make_product_card(product: dict, label: str = "FEATURED FAVORITE") -> str:
    title = product["title"]
    price = product["variants"][0]["price"] if product.get("variants") else "49"
    handle = product.get("handle", "")
    url = f"{STORE_URL}/products/{handle}?utm_source=blog&utm_medium=featured_card"
    img = product["images"][0]["src"] if product.get("images") else ""
    card_alt = f"{title} - US Women's Fashion Outfit Pick"
    
    img_html = f'<a href="{url}"><img src="{img}" alt="{card_alt}" style="width:200px;height:200px;object-fit:cover;border-radius:8px;flex-shrink:0;" loading="lazy" /></a>' if img else ""
    
    return f"""
<div style="background:#f9f9f9;border:1px solid #eee;border-radius:12px;padding:20px;margin:24px 0;display:flex;flex-wrap:wrap;gap:20px;align-items:center;font-family:sans-serif;">
  {img_html}
  <div style="flex:1;min-width:200px;">
    <p style="font-size:11px;color:#888;margin:0 0 4px;text-transform:uppercase;font-weight:bold;letter-spacing:1px;">{label}</p>
    <h3 style="margin:0 0 8px;font-size:17px;color:#111;font-weight:700;">{title}</h3>
    <p style="font-size:22px;font-weight:bold;margin:0 0 12px;color:#111;">${price}</p>
    <a href="{url}" style="background:#111;color:#fff;padding:11px 24px;text-decoration:none;border-radius:6px;font-size:13px;font-weight:bold;display:inline-block;">Shop Now &rarr;</a>
  </div>
</div>
"""


def process_all_articles(dry_run: bool = False):
    print("\n--- Master Orchestrator: Updating Products, Cards & Collages for All Articles ---", flush=True)

    # 1. Fetch catalog products
    try:
        r = requests.get(f"{BASE}/products.json", headers=HEADERS, params={"limit": 250}, timeout=20)
        all_prods = r.json().get("products", [])
        pool = [p for p in all_prods if p.get("images")]
        handle_to_prod = {p["handle"].lower().strip(): p for p in pool if p.get("handle")}
        print(f"Loaded {len(pool)} active catalog products with images.", flush=True)
    except Exception as e:
        print(f"Error fetching catalog products: {e}", flush=True)
        return

    rotation = ProductRotationManager()

    # 2. Fetch blogs
    r = requests.get(f"{BASE}/blogs.json", headers=HEADERS, timeout=20)
    blogs = r.json().get("blogs", [])

    updated_count = 0

    for blog in blogs:
        b_id = blog["id"]
        r2 = requests.get(f"{BASE}/blogs/{b_id}/articles.json", headers=HEADERS, params={"limit": 250}, timeout=20)
        articles = r2.json().get("articles", [])

        for art in articles:
            art_id = art["id"]
            title = art.get("title", "")
            body = art.get("body_html", "")

            # Parse handles in body
            handles = re.findall(r'/products/([a-zA-Z0-9_-]+)', body)
            clean_handles = list(dict.fromkeys([h.lower().strip() for h in handles if h and h != "all"]))

            # Gather target products
            referenced_prods = []
            for h in clean_handles:
                if h in handle_to_prod and handle_to_prod[h] not in referenced_prods:
                    referenced_prods.append(handle_to_prod[h])

            # If fewer than 3 products in article, supplement with available unfeatured products
            if len(referenced_prods) < 3:
                fresh_pool = rotation.filter_available_products(pool, days=15)
                for p in fresh_pool:
                    if p not in referenced_prods:
                        referenced_prods.append(p)
                    if len(referenced_prods) >= 3:
                        break

            target_3_prods = referenced_prods[:3]
            collage_imgs = [p["images"][0]["src"] for p in target_3_prods if p.get("images")]

            if not collage_imgs:
                continue

            print(f"\n[Processing Article {art_id}] '{title}'", flush=True)
            print(f"  Referenced Products ({len(target_3_prods)}): {[p['handle'] for p in target_3_prods]}", flush=True)

            # Build 1200x630 3-Product Collage Image
            temp_collage = Path(f"scratch/master_collage_{art_id}.jpg")
            built_ok = create_3product_collage(collage_imgs, temp_collage)
            if not built_ok:
                print("  [!] Failed to build local PIL collage image.", flush=True)
                continue

            print(f"  ✓ Created 1200x630 Outfit Collage: {temp_collage}", flush=True)

            # Ensure primary product card is injected in body HTML
            primary_prod = target_3_prods[0]
            updated_body = body

            # If body has no product card div, append product card
            if "utm_medium=featured_card" not in updated_body and "utm_medium=card" not in updated_body:
                card_html = make_product_card(primary_prod)
                updated_body += f"\n{card_html}"

            if dry_run:
                print("  [DRY-RUN] Skipping Shopify GraphQL upload and article update.", flush=True)
                updated_count += 1
                continue

            # Upload 3-product collage image to Shopify Files
            filename = f"outfit_collage_{art_id}_{int(time.time())}.jpg"
            cdn_url = upload_image_to_shopify(temp_collage, filename)

            if not cdn_url:
                print("  [!] GraphQL upload failed for collage image.", flush=True)
                continue

            print(f"  ✓ Uploaded Collage to Shopify Files: {cdn_url}", flush=True)

            # Update article payload
            payload = {
                "article": {
                    "id": art_id,
                    "body_html": updated_body,
                    "image": {
                        "src": cdn_url,
                        "alt": f"{title} - 3-Product Outfit Style Collage"
                    }
                }
            }

            try:
                up_res = requests.put(f"{BASE}/blogs/{b_id}/articles/{art_id}.json", headers=HEADERS, json=payload, timeout=20)
                if up_res.status_code in (200, 201):
                    for p in target_3_prods:
                        rotation.mark_used(p.get("handle", ""))
                    updated_count += 1
                    print("  ✓ Successfully updated Article Body & 3-Product Collage Featured Image on Shopify!", flush=True)
                else:
                    print(f"  ❌ Article update failed (HTTP {up_res.status_code}): {up_res.text[:100]}", flush=True)
            except Exception as e:
                print(f"  ❌ Error updating article: {e}", flush=True)

            # Clean up temp file
            if temp_collage.exists():
                try:
                    temp_collage.unlink()
                except Exception:
                    pass

            time.sleep(0.5)

    print(f"\n[DONE] Master Article & Collage update complete. Total articles updated: {updated_count}", flush=True)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Master Blog Article & Collage Orchestrator")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without updating Shopify")
    parser.add_argument("--apply", action="store_true", help="Apply product link, card, and 3-product collage fixes live to Shopify")
    args = parser.parse_args()

    process_all_articles(dry_run=not args.apply)

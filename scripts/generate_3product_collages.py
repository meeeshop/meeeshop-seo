#!/usr/bin/env python3
"""
generate_3product_collages.py — 3-Product Outfit Collage Featured Image Generator
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Creates high-resolution (1200x630) 3-product outfit collage featured images for
all blog articles using the 3 exact products referenced in each article's content.

Usage:
  python scripts/generate_3product_collages.py --dry-run
  python scripts/generate_3product_collages.py --apply
"""

import os
import sys
import re
import json
import time
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


def build_3product_collage(image_urls: list[str], output_path: Path) -> bool:
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


def run_3product_collage_generator(dry_run: bool = False):
    print("\n--- Generating 3-Product Outfit Collages for Blog Featured Images ---", flush=True)

    # 1. Fetch products map
    try:
        r = requests.get(f"{BASE}/products.json", headers=HEADERS, params={"limit": 250}, timeout=20)
        all_prods = r.json().get("products", [])
        handle_to_prod = {p["handle"].lower().strip(): p for p in all_prods if p.get("handle")}
        print(f"Loaded {len(handle_to_prod)} catalog products.", flush=True)
    except Exception as e:
        print(f"Error loading catalog products: {e}", flush=True)
        return

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

            # Extract product handles from body
            handles = re.findall(r'/products/([a-zA-Z0-9_-]+)', body)
            clean_handles = list(dict.fromkeys([h.lower().strip() for h in handles if h and h != "all"]))

            if not clean_handles:
                continue

            # Gather up to 3 product image URLs
            collage_imgs = []
            matched_handles = []
            for h in clean_handles:
                prod = handle_to_prod.get(h)
                if prod and prod.get("images"):
                    img_src = prod["images"][0]["src"]
                    if img_src not in collage_imgs:
                        collage_imgs.append(img_src)
                        matched_handles.append(h)
                    if len(collage_imgs) >= 3:
                        break

            if not collage_imgs:
                continue

            print(f"\n[Article {art_id}] '{title}'", flush=True)
            print(f"  Referenced Products ({len(matched_handles)}): {', '.join(matched_handles)}", flush=True)

            # Build local 3-product collage image
            temp_path = Path(f"scratch/collage_art_{art_id}.jpg")
            success = build_3product_collage(collage_imgs, temp_path)
            if not success:
                print("  [!] Failed to build local PIL collage.", flush=True)
                continue

            print(f"  ✓ Built 1200x630 3-Product Collage Image: {temp_path}", flush=True)

            if dry_run:
                print("  [DRY-RUN] Skipping Shopify GraphQL upload and article image update.", flush=True)
                updated_count += 1
                continue

            # Upload collage to Shopify
            filename = f"3prod_collage_{art_id}_{int(time.time())}.jpg"
            cdn_url = upload_image_to_shopify(temp_path, filename)

            if not cdn_url:
                print("  [!] GraphQL upload failed for collage.", flush=True)
                continue

            print(f"  ✓ Uploaded Collage to Shopify Files: {cdn_url}", flush=True)

            # Update article featured image on Shopify
            payload = {
                "article": {
                    "id": art_id,
                    "image": {
                        "src": cdn_url,
                        "alt": f"{title} - 3-Product Styled Outfit Collage"
                    }
                }
            }
            try:
                up_res = requests.put(f"{BASE}/blogs/{b_id}/articles/{art_id}.json", headers=HEADERS, json=payload, timeout=20)
                if up_res.status_code in (200, 201):
                    updated_count += 1
                    print("  ✓ Successfully updated Featured Image on Shopify!", flush=True)
                else:
                    print(f"  ❌ Update failed (HTTP {up_res.status_code}): {up_res.text[:100]}", flush=True)
            except Exception as e:
                print(f"  ❌ Error updating article: {e}", flush=True)

            # Clean up temp file
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass

    print(f"\n[DONE] 3-Product Collage Featured Image update complete. Total articles updated: {updated_count}", flush=True)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate 3-Product Outfit Collages for Blog Featured Images")
    parser.add_argument("--dry-run", action="store_true", help="Preview collage creation without uploading to Shopify")
    parser.add_argument("--apply", action="store_true", help="Build and upload 3-product collage images live to Shopify")
    args = parser.parse_args()

    run_3product_collage_generator(dry_run=not args.apply)

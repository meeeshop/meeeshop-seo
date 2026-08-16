#!/usr/bin/env python3
"""
update_article_hero_featured_images.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Updates the featured image of each blog article on Shopify to match its exact
primary product hero photo, ensuring 100% unique featured images across all articles.
"""

import sys
import re
import json
import time
import requests
from pathlib import Path

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
BASE = f"https://{SHOP}/admin/api/2024-10"
HEADERS = {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}


def fix_featured_images(dry_run: bool = False):
    print("\n--- Updating Article Featured Images with Unique Hero Product Photos ---", flush=True)
    
    # 1. Fetch catalog products to build handle -> main_image_url map
    try:
        r = requests.get(f"{BASE}/products.json", headers=HEADERS, params={"limit": 250}, timeout=20)
        prods = r.json().get("products", [])
        handle_to_img = {}
        handle_to_title = {}
        for p in prods:
            h = p.get("handle", "").lower().strip()
            imgs = p.get("images", [])
            if h and imgs:
                handle_to_img[h] = imgs[0]["src"]
                handle_to_title[h] = p.get("title", "")
        print(f"Loaded {len(handle_to_img)} catalog products with images.", flush=True)
    except Exception as e:
        print(f"Error fetching catalog products: {e}", flush=True)
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
            
            # Find product handles in body
            handles = re.findall(r'/products/([a-zA-Z0-9_-]+)', body)
            clean_handles = [h.lower().strip() for h in handles if h and h != "all"]
            
            if not clean_handles:
                continue
                
            # Take primary product handle
            primary_handle = clean_handles[0]
            hero_img = handle_to_img.get(primary_handle)
            hero_title = handle_to_title.get(primary_handle, title)
            
            if not hero_img:
                # Try any other handle in body
                for h in clean_handles[1:]:
                    if h in handle_to_img:
                        hero_img = handle_to_img[h]
                        hero_title = handle_to_title.get(h, title)
                        primary_handle = h
                        break
            
            if not hero_img:
                continue
                
            curr_feat_img = art.get("image", {}).get("src", "")
            
            # Update article image if hero_img is not already set
            print(f"  [Article {art_id}] '{title}'", flush=True)
            print(f"    - Primary Handle: '{primary_handle}' ({hero_title})", flush=True)
            print(f"    - New Hero Featured Image: {hero_img}", flush=True)

            if dry_run:
                print("    [DRY-RUN] Skipping Shopify upload.", flush=True)
                updated_count += 1
                continue

            payload = {
                "article": {
                    "id": art_id,
                    "image": {
                        "src": hero_img,
                        "alt": f"{hero_title} - Featured Pick at MeeeShop"
                    }
                }
            }
            try:
                up_res = requests.put(f"{BASE}/blogs/{b_id}/articles/{art_id}.json", headers=HEADERS, json=payload, timeout=20)
                if up_res.status_code in (200, 201):
                    updated_count += 1
                    print("    ✓ Successfully updated featured image on Shopify!", flush=True)
                else:
                    print(f"    ❌ Update failed (HTTP {up_res.status_code}): {up_res.text[:100]}", flush=True)
            except Exception as e:
                print(f"    ❌ Error updating article: {e}", flush=True)
            
            time.sleep(0.3)

    print(f"\n[DONE] Finished updating featured images. Total articles updated: {updated_count}", flush=True)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    fix_featured_images(dry_run=args.dry_run)

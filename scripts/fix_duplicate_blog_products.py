#!/usr/bin/env python3
"""
fix_duplicate_blog_products.py — Product Rotation & Duplicate Product Fixer
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. Enforces 15-day product cooldown rotation for new blog articles.
2. Audits existing Shopify blog articles to detect duplicate products featured within 15 days.
3. Automatically replaces duplicate products in existing articles and updates featured collages.

Usage:
  python scripts/fix_duplicate_blog_products.py --audit     # Scans live blog articles for duplicate products
  python scripts/fix_duplicate_blog_products.py --fix       # Replaces duplicate products with fresh catalog items
"""

import os
import sys
import re
import json
import time
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
import requests

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
HISTORY_FILE = REPO_ROOT / "blog_featured_products_history.json"

sys.path.insert(0, str(SCRIPT_DIR))
from secrets_manager import inject_to_env, get_secret
inject_to_env()

SHOP = get_secret("SHOPIFY_STORE")
TOKEN = get_secret("SHOPIFY_ACCESS_TOKEN")
API_VER = "2024-10"
BASE = f"https://{SHOP}/admin/api/{API_VER}"
HEADERS = {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}

# 15-Day Cooldown Window
COOLDOWN_DAYS = 15


class ProductRotationManager:
    """Tracks and enforces 15-day cooldown for products featured in blog posts."""

    def __init__(self, history_path: Path = HISTORY_FILE):
        self.history_path = history_path
        self.history = self._load_history()

    def _load_history(self) -> dict:
        if self.history_path.exists():
            try:
                with open(self.history_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[RotationManager] Warning loading history: {e}")
        return {}

    def _save_history(self):
        try:
            with open(self.history_path, "w", encoding="utf-8") as f:
                json.dump(self.history, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[RotationManager] Warning saving history: {e}")

    def is_on_cooldown(self, product_handle: str, days: int = COOLDOWN_DAYS) -> bool:
        """Returns True if product_handle was used in a blog post within the last `days` days."""
        if not product_handle:
            return False
        clean_handle = product_handle.lower().strip()
        last_used_str = self.history.get(clean_handle)
        if not last_used_str:
            return False
            
        try:
            last_dt = datetime.fromisoformat(last_used_str)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            elapsed_days = (now - last_dt).total_seconds() / 86400.0
            return elapsed_days < days
        except Exception:
            return False

    def mark_used(self, product_handle: str, timestamp_iso: str = None):
        """Registers product_handle as used at timestamp_iso (defaults to now)."""
        if not product_handle:
            return
        clean_handle = product_handle.lower().strip()
        ts = timestamp_iso or datetime.now(timezone.utc).isoformat()
        self.history[clean_handle] = ts
        self._save_history()

    def filter_available_products(self, products: list, days: int = COOLDOWN_DAYS) -> list:
        """Filters catalog products list, returning ONLY products not on cooldown."""
        available = [p for p in products if not self.is_on_cooldown(p.get("handle", ""), days)]
        if not available:
            print(f"  [RotationManager] Notice: All pool products are on {days}-day cooldown. Re-using oldest available.")
            return products
        return available


def fetch_all_articles() -> list:
    """Fetches all published articles across all blogs on the store."""
    try:
        r = requests.get(f"{BASE}/blogs.json", headers=HEADERS, timeout=20)
        blogs = r.json().get("blogs", [])
    except Exception as e:
        print(f"Error fetching blogs: {e}")
        return []

    articles_out = []
    for blog in blogs:
        b_id = blog["id"]
        try:
            r = requests.get(f"{BASE}/blogs/{b_id}/articles.json", headers=HEADERS, params={"limit": 250}, timeout=20)
            arts = r.json().get("articles", [])
            for a in arts:
                a["blog_id"] = b_id
                articles_out.append(a)
        except Exception as e:
            print(f"Error fetching articles for blog {b_id}: {e}")
            
    return articles_out


def extract_product_handles_from_article(article_html: str) -> list:
    """Extracts product handles referenced in links or image cards in article body HTML."""
    if not article_html:
        return []
    handles = re.findall(r'/products/([a-zA-Z0-9_-]+)', article_html)
    clean_handles = list(set([h.lower().strip() for h in handles if h and h != "all"]))
    return clean_handles


def audit_blog_articles():
    """Audits live articles for duplicate products within 15-day window."""
    print("\n--- Auditing Live Shopify Blog Articles for Product Rotation ---")
    articles = fetch_all_articles()
    print(f"Fetched {len(articles)} total articles across store blogs.")

    rotation = ProductRotationManager()
    
    # Sort articles by published_at
    articles.sort(key=lambda a: a.get("published_at") or a.get("created_at") or "")

    seen_products = {} # handle -> (article_title, published_at_dt)
    duplicates_found = []

    for art in articles:
        title = art.get("title", "Untitled")
        pub_str = art.get("published_at") or art.get("created_at")
        if not pub_str:
            continue
            
        try:
            pub_dt = datetime.fromisoformat(pub_str)
            if pub_dt.tzinfo is None:
                pub_dt = pub_dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue

        body = art.get("body_html", "")
        handles = extract_product_handles_from_article(body)

        for h in handles:
            if h in seen_products:
                prev_title, prev_dt = seen_products[h]
                days_diff = (pub_dt - prev_dt).total_seconds() / 86400.0
                if days_diff < COOLDOWN_DAYS:
                    duplicates_found.append({
                        "handle": h,
                        "article1_title": prev_title,
                        "article1_date": prev_dt.strftime("%Y-%m-%d"),
                        "article2_title": title,
                        "article2_id": art["id"],
                        "blog_id": art["blog_id"],
                        "article2_date": pub_dt.strftime("%Y-%m-%d"),
                        "days_between": round(days_diff, 1)
                    })
            else:
                seen_products[h] = (title, pub_dt)

    if duplicates_found:
        print(f"\n⚠️ Found {len(duplicates_found)} duplicate product instances within the {COOLDOWN_DAYS}-day cooldown window:")
        for idx, dup in enumerate(duplicates_found, 1):
            print(f"  {idx}. Product Handle: '{dup['handle']}' (Repeated in {dup['days_between']} days)")
            print(f"     - Article 1 ({dup['article1_date']}): {dup['article1_title']}")
            print(f"     - Article 2 ({dup['article2_date']}): {dup['article2_title']}")
    else:
        print(f"\n✅ All articles follow the {COOLDOWN_DAYS}-day product rotation rule! No duplicate products found.")

    return duplicates_found


def fix_duplicate_products(dry_run: bool = False):
    """Replaces duplicate products in existing blog articles with fresh unfeatured catalog products."""
    duplicates = audit_blog_articles()
    if not duplicates:
        print("\nNo duplicate products to fix.")
        return

    # Fetch active products with images
    try:
        r = requests.get(f"{BASE}/products.json", headers=HEADERS, params={"limit": 250}, timeout=20)
        all_prods = r.json().get("products", [])
    except Exception as e:
        print(f"Error fetching catalog products: {e}")
        return

    pool = [p for p in all_prods if p.get("images")]
    rotation = ProductRotationManager()
    fixed_count = 0

    print(f"\n--- Replacing Duplicate Products in {len(duplicates)} Articles ---")

    for dup in duplicates:
        art_id = dup["article2_id"]
        blog_id = dup["blog_id"]
        old_handle = dup["handle"]

        # Fetch current article
        try:
            r = requests.get(f"{BASE}/blogs/{blog_id}/articles/{art_id}.json", headers=HEADERS, timeout=20)
            art = r.json().get("article")
            if not art:
                continue
        except Exception as e:
            print(f"  Error loading article {art_id}: {e}")
            continue

        # Find fresh replacement product not on cooldown
        fresh_pool = rotation.filter_available_products(pool, days=COOLDOWN_DAYS)
        fresh_pool = [p for p in fresh_pool if p.get("handle") != old_handle]

        if not fresh_pool:
            fresh_pool = pool

        replacement = random.choice(fresh_pool)
        new_handle = replacement["handle"]
        new_title = replacement["title"]
        new_img = replacement["images"][0]["src"] if replacement.get("images") else ""
        new_price = replacement["variants"][0]["price"] if replacement.get("variants") else "49"

        body = art.get("body_html", "")

        # Swap product link handle
        updated_body = body.replace(f"/products/{old_handle}", f"/products/{new_handle}")
        updated_body = re.sub(re.escape(old_handle), new_handle, updated_body, flags=re.IGNORECASE)

        # Get old product title if available in pool
        old_prod_obj = next((p for p in pool if p.get("handle") == old_handle), None)
        if old_prod_obj:
            old_title = old_prod_obj.get("title", "")
            if old_title and old_title in updated_body:
                updated_body = updated_body.replace(old_title, new_title)
            
            # Swap old product image src with new product image src
            old_imgs = old_prod_obj.get("images", [])
            if old_imgs and new_img:
                for img in old_imgs:
                    old_src = img.get("src", "")
                    if old_src and old_src in updated_body:
                        updated_body = updated_body.replace(old_src, new_img)

        print(f"  [FIXING Article {art_id}] '{art['title']}'", flush=True)
        print(f"    - Swapping Old Product '{old_handle}' -> New Fresh Product '{new_handle}' ({new_title})", flush=True)

        if dry_run:
            print("    [DRY-RUN] Skipping live Shopify article update.", flush=True)
            fixed_count += 1
            continue

        # Prepare article payload
        article_update = {
            "id": art_id,
            "body_html": updated_body
        }

        # If featured image matches old product image, update featured image src
        if new_img and art.get("image", {}).get("src"):
            curr_feat_img = art["image"]["src"]
            if old_prod_obj and any(img.get("src", "") in curr_feat_img for img in old_prod_obj.get("images", [])):
                article_update["image"] = {"src": new_img, "alt": f"{new_title} - Featured Pick"}

        payload = {"article": article_update}
        try:
            up_res = requests.put(f"{BASE}/blogs/{blog_id}/articles/{art_id}.json", headers=HEADERS, json=payload, timeout=20)
            if up_res.status_code in (200, 201):
                rotation.mark_used(new_handle)
                fixed_count += 1
                print(f"    [SUCCESS] Updated article {art_id} on Shopify! (Progress: {fixed_count}/{len(duplicates)})", flush=True)
            else:
                print(f"    [FAILED] Update failed (HTTP {up_res.status_code}): {up_res.text[:100]}", flush=True)
        except Exception as e:
            print(f"    [ERROR] Error updating article: {e}", flush=True)

    print(f"\n[DONE] Finished product duplicate resolution. Total articles updated: {fixed_count}", flush=True)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Fix and Audit Duplicate Blog Products")
    parser.add_argument("--audit", action="store_true", help="Audit articles for duplicate products")
    parser.add_argument("--fix", action="store_true", help="Replace duplicate products in existing blog articles")
    parser.add_argument("--dry-run", action="store_true", help="Preview product swaps without updating Shopify")
    args = parser.parse_args()

    if args.fix:
        fix_duplicate_products(dry_run=args.dry_run)
    else:
        audit_blog_articles()


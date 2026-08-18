#!/usr/bin/env python3
"""
auto_redirect_sync.py — Proactive Automatic 301 Redirect Sync for MeeeShop
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Automatically detects deleted, archived, or missing products and creates
native Shopify 301 URL redirects to the most relevant collection with at least
20 active products in the Online Store sales channel.

How it works:
  1. Fetches all active collections and filters only those with >= 20 active products.
  2. Fetches all active products from Shopify GraphQL.
  3. Compares against the persistent catalog snapshot (data/catalog_snapshot.json).
  4. For any handle that was removed/deleted:
     - Extracts title, type, vendor, and tags from snapshot metadata.
     - Classifies the item to a rich, relevant collection with >= 20 products.
     - Creates the native Shopify 301 URL Redirect via GraphQL/REST.
  5. Audits and updates any existing redirects that point to empty/thin collections (< 20 products).
  6. Saves the updated catalog snapshot.

Usage:
  python auto_redirect_sync.py                 # Sync and create missing redirects
  python auto_redirect_sync.py --dry-run       # Preview without creating
  python auto_redirect_sync.py --init-snapshot # Initialize baseline catalog snapshot
  python auto_redirect_sync.py --fix-existing  # Re-audit and fix existing redirects targeting thin collections
"""

import os
import sys
import json
import time
import re
import argparse
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
import requests

# ── path setup ──
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_DIR = SCRIPT_DIR.parent
DATA_DIR = REPO_DIR / "data"
REPORTS_DIR = REPO_DIR / "reports"
SNAPSHOT_FILE = DATA_DIR / "catalog_snapshot.json"
HISTORY_FILE = REPORTS_DIR / "auto_redirects_history.json"

DATA_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(REPO_DIR))

from secrets_manager import inject_to_env, get_secret
inject_to_env()

STORE = get_secret("SHOPIFY_STORE")
TOKEN = get_secret("SHOPIFY_ACCESS_TOKEN")
BASE_URL = f"https://{STORE}/admin/api/2024-10"
GRAPHQL_URL = f"{BASE_URL}/graphql.json"
HEADERS = {
    "X-Shopify-Access-Token": TOKEN,
    "Content-Type": "application/json"
}

MIN_COLLECTION_PRODUCTS = 20

# ── Hierarchical Classification Rules ──
# (Pattern, Preferred Target Collection, Fallback Category Collection)
CATEGORY_RULES = [
    # Plus Size / Curvy
    (r"\b(plus\s*size|curvy|plus)\b", "/collections/womens-curvy-plus-size-clothing", "/collections/womens-curvy-plus-size-clothing"),

    # Dresses
    (r"\b(maxi\s*dress|maxi)\b", "/collections/womens-maxi-dresses", "/collections/womens-dresses"),
    (r"\b(midi\s*dress|midi)\b", "/collections/midi-dresses", "/collections/womens-dresses"),
    (r"\b(mini\s*dress|mini)\b", "/collections/mini-dresses", "/collections/womens-dresses"),
    (r"\b(casual\s*dress|sundress|t-shirt\s*dress|shift\s*dress)\b", "/collections/womens-casual-dresses", "/collections/womens-dresses"),
    (r"\b(dress|dresses|shirtdress|babydoll|slip\s*dress)\b", "/collections/womens-dresses", "/collections/womens-dresses"),

    # Jeans & Denim
    (r"\b(judy\s*blue|jb)\b", "/collections/judy-blue-womens-jeans", "/collections/womens-jeans"),
    (r"\b(risen)\b", "/collections/risen-womens-jeans-collection", "/collections/womens-jeans"),
    (r"\b(artemis)\b", "/collections/artemis-vintage-womens-jeans", "/collections/womens-jeans"),
    (r"\b(ymi)\b", "/collections/ymi-jeans", "/collections/womens-jeans"),
    (r"\b(wide\s*leg|palazzo|baggy|barrel)\b", "/collections/wide-leg-jeans", "/collections/womens-jeans"),
    (r"\b(straight\s*leg|straight\s*jeans|mom\s*jeans|boyfriend\s*jeans)\b", "/collections/straight-leg-jeans", "/collections/womens-jeans"),
    (r"\b(flare\s*jean|bell\s*bottom|bootcut)\b", "/collections/womens-new-denim", "/collections/womens-jeans"),
    (r"\b(jeans|denim|jorts)\b", "/collections/womens-jeans", "/collections/womens-jeans"),

    # Tops & Shirts
    (r"\b(graphic\s*tee|vintage\s*tee|band\s*tee|t-shirt|tee)\b", "/collections/womens-t-shirts", "/collections/womens-tops"),
    (r"\b(tank|cami|sleeveless|crop\s*top|tube\s*top|halter)\b", "/collections/womens-camis-tanks-tops", "/collections/womens-tops"),
    (r"\b(knit\s*top|ribbed\s*top)\b", "/collections/womens-knit-tops", "/collections/womens-tops"),
    (r"\b(long\s*sleeve)\b", "/collections/long-sleeve-tops", "/collections/womens-tops"),
    (r"\b(v-neck|v\s*neck)\b", "/collections/v-neck-tops", "/collections/womens-tops"),
    (r"\b(top|blouse|shirt|shacket|tunic|button\s*down)\b", "/collections/womens-tops", "/collections/womens-tops"),

    # Sweaters & Hoodies
    (r"\b(sweatshirt|hoodie)\b", "/collections/womens-sweatshirts-hoodies", "/collections/womens-sweaters"),
    (r"\b(sweater|cardigan|pullover|turtleneck|knitwear)\b", "/collections/womens-sweaters", "/collections/womens-sweaters"),

    # Bottoms, Pants, Shorts, Skirts
    (r"\b(shorts|biker\s*short|bermuda)\b", "/collections/womens-shorts", "/collections/womens-bottoms"),
    (r"\b(skirt|skort)\b", "/collections/womens-skirts", "/collections/womens-bottoms"),
    (r"\b(jogger|joggers|sweatpant|sweatpants|lounge\s*pant)\b", "/collections/womens-loungewear", "/collections/womens-pants-leggings"),
    (r"\b(legging|leggings|trousers|pants|pant|bottoms)\b", "/collections/womens-pants-leggings", "/collections/womens-bottoms"),

    # Rompers, Jumpsuits, Sets
    (r"\b(outfit\s*set|lounge\s*set|pant\s*set|short\s*set|2pcs|2-piece|2\s*piece)\b", "/collections/womens-outfit-sets", "/collections/womens-rompers-jumpsuit-sets"),
    (r"\b(romper|jumpsuit|overalls|overall)\b", "/collections/womens-rompers-jumpsuit-sets", "/collections/womens-rompers-jumpsuit-sets"),

    # Outerwear & Blazers
    (r"\b(blazer|vest|waistcoat)\b", "/collections/womens-blazers-vests-jackets", "/collections/womens-outerwear"),
    (r"\b(jacket|coat|outerwear|trench|parka|shacket)\b", "/collections/womens-coats-jackets", "/collections/womens-outerwear"),

    # Shoes & Footwear
    (r"\b(sandal|sandals|wedge|wedges|heels|heel|flats|flat|sneaker|sneakers|boot|boots|bootie|booties|clog|clogs|shoe|shoes|slide|slides)\b", "/collections/womens-shoes", "/collections/womens-shoes"),

    # Bags & Accessories
    (r"\b(bag|tote|backpack|crossbody|clutch|sling|purse|fanny|handbag|satchel|wallet)\b", "/collections/womens-handbags-accessories", "/collections/womens-handbags-accessories"),

    # Activewear
    (r"\b(active|workout|gym|sports\s*bra|yoga)\b", "/collections/womens-activewear", "/collections/womens-activewear"),

    # Brand specific (only if collection has >= 20 products)
    (r"\b(emory\s*park)\b", "/collections/emory-park-womens-clothing", "/collections/womens-dresses"),
    (r"\b(orange\s*farm)\b", "/collections/orange-farm-womens-clothing", "/collections/womens-tops"),
    (r"\b(luxe)\b", "/collections/womens-luxe-apparel", "/collections/womens-dresses"),
]

# Ultimate safe fallbacks with 100+ active items
DEFAULT_FALLBACK = "/collections/womens-new-collection"


def fetch_valid_collections() -> dict:
    """Fetch all active collections from Shopify and filter only those with >= 20 active products."""
    print("Fetching collection taxonomy and product counts from Shopify...")
    valid_cols = {}
    
    query = """
    query {
      collections(first: 250) {
        edges {
          node {
            handle
            title
            productsCount {
              count
            }
          }
        }
      }
    }
    """
    resp = requests.post(GRAPHQL_URL, headers=HEADERS, json={"query": query}, timeout=30)
    if resp.status_code != 200:
        print(f"Error querying collections: {resp.status_code}")
        return valid_cols

    cols = resp.json().get("data", {}).get("collections", {}).get("edges", [])
    for c in cols:
        node = c["node"]
        handle = node["handle"]
        count = node.get("productsCount", {}).get("count", 0)
        path = f"/collections/{handle}"
        
        # Exclude administrative/internal collections
        if handle in ["all-products_do_not_delete", "all"]:
            continue

        if count >= MIN_COLLECTION_PRODUCTS:
            valid_cols[path] = {
                "handle": handle,
                "title": node["title"],
                "count": count
            }

    print(f"Found {len(valid_cols)} active collections with >= {MIN_COLLECTION_PRODUCTS} products.")
    return valid_cols


def get_smart_target_collection(path_or_handle: str, title: str = "", product_type: str = "", vendor: str = "", tags: list = None, valid_cols: dict = None) -> str:
    """Determine the optimal target collection that is guaranteed to have >= 20 active products."""
    combined = f"{path_or_handle} {title} {product_type} {vendor} {' '.join(tags or [])}".lower()
    combined = combined.replace("-", " ").replace("_", " ")

    valid_paths = set(valid_cols.keys()) if valid_cols else set()

    for pattern, preferred_target, fallback_target in CATEGORY_RULES:
        if re.search(pattern, combined):
            # Check if preferred target has >= 20 items
            if not valid_paths or preferred_target in valid_paths:
                return preferred_target
            # Check if fallback category has >= 20 items
            if fallback_target in valid_paths:
                return fallback_target

    # General type-level fallback
    if valid_paths:
        if "dress" in combined and "/collections/womens-dresses" in valid_paths:
            return "/collections/womens-dresses"
        if ("jean" in combined or "denim" in combined) and "/collections/womens-jeans" in valid_paths:
            return "/collections/womens-jeans"
        if ("top" in combined or "shirt" in combined) and "/collections/womens-tops" in valid_paths:
            return "/collections/womens-tops"
        if ("shoe" in combined or "sandal" in combined) and "/collections/womens-shoes" in valid_paths:
            return "/collections/womens-shoes"
        if ("bag" in combined or "tote" in combined) and "/collections/womens-handbags-accessories" in valid_paths:
            return "/collections/womens-handbags-accessories"

    return DEFAULT_FALLBACK


def fetch_all_active_products() -> dict:
    """Fetch all active products from Shopify via GraphQL pagination."""
    products = {}
    has_next = True
    cursor = None

    query = """
    query GetProducts($cursor: String) {
      products(first: 250, after: $cursor, query: "status:ACTIVE") {
        pageInfo {
          hasNextPage
          endCursor
        }
        edges {
          node {
            id
            handle
            title
            productType
            vendor
            tags
            status
          }
        }
      }
    }
    """

    print("Fetching active products from Shopify...")
    while has_next:
        vars_ = {"cursor": cursor} if cursor else {}
        resp = requests.post(GRAPHQL_URL, headers=HEADERS, json={"query": query, "variables": vars_}, timeout=30)
        if resp.status_code != 200:
            print(f"Error fetching products: {resp.status_code}")
            break

        data = resp.json().get("data", {}).get("products", {})
        for edge in data.get("edges", []):
            node = edge["node"]
            handle = node["handle"]
            products[handle] = {
                "id": node["id"],
                "handle": handle,
                "title": node["title"],
                "productType": node.get("productType", ""),
                "vendor": node.get("vendor", ""),
                "tags": node.get("tags", []),
                "last_seen": datetime.now(timezone.utc).isoformat()
            }

        page_info = data.get("pageInfo", {})
        has_next = page_info.get("hasNextPage", False)
        cursor = page_info.get("endCursor")

    print(f"Total active products fetched: {len(products)}")
    return products


def fetch_existing_redirects() -> dict:
    """Pre-fetch all existing redirects from Shopify."""
    existing_redirects = {}
    url = f"{BASE_URL}/redirects.json?limit=250"
    while url:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        if resp.status_code != 200:
            break
        data = resp.json().get("redirects", [])
        for r in data:
            path = r.get("path", "").strip()
            existing_redirects[path] = {
                "id": r["id"],
                "target": r.get("target", "").strip()
            }
        
        # Pagination via Link header
        link_header = resp.headers.get("Link", "")
        next_url = None
        if "rel=\"next\"" in link_header:
            for part in link_header.split(","):
                if "rel=\"next\"" in part:
                    next_url = part.split(";")[0].strip("<> ")
        url = next_url

    print(f"Total existing Shopify redirects: {len(existing_redirects)}")
    return existing_redirects


def create_or_update_redirect(path: str, target: str, redirect_id: int = None) -> bool:
    """Create or update a 301 redirect in Shopify."""
    if redirect_id:
        url = f"{BASE_URL}/redirects/{redirect_id}.json"
        payload = {"redirect": {"id": redirect_id, "target": target}}
        try:
            resp = requests.put(url, headers=HEADERS, json=payload, timeout=15)
            return resp.status_code in [200, 201]
        except Exception as e:
            print(f"  Error updating redirect {redirect_id}: {e}")
            return False
    else:
        url = f"{BASE_URL}/redirects.json"
        payload = {"redirect": {"path": path, "target": target}}
        try:
            resp = requests.post(url, headers=HEADERS, json=payload, timeout=15)
            if resp.status_code in [200, 201]:
                return True
            elif resp.status_code == 422:
                return False  # Already exists
            else:
                time.sleep(0.5)
                resp = requests.post(url, headers=HEADERS, json=payload, timeout=15)
                return resp.status_code in [200, 201]
        except Exception as e:
            print(f"  Error creating redirect for {path}: {e}")
            return False


def fix_existing_thin_redirects(valid_cols: dict, dry_run: bool = False):
    """Scan all existing redirects and update any targeting collections with < 20 products."""
    print("\nAuditing existing redirects to ensure all target collections have >= 20 products...")
    existing = fetch_existing_redirects()
    valid_paths = set(valid_cols.keys())
    
    fixed_count = 0
    for path, data in existing.items():
        target = data["target"].split("?")[0].rstrip("/")
        red_id = data["id"]

        # If redirect points to a collection with < 20 products (or 0 products)
        if target.startswith("/collections/") and target not in valid_paths and target != "/collections/all":
            new_target = get_smart_target_collection(path, valid_cols=valid_cols)
            if new_target != target:
                if dry_run:
                    print(f"[DRY-RUN FIX] {path}: {target} (thin) -> {new_target} ({valid_cols.get(new_target, {}).get('count', 0)} items)")
                    fixed_count += 1
                else:
                    success = create_or_update_redirect(path, new_target, redirect_id=red_id)
                    if success:
                        print(f"[UPDATED] {path}: {target} -> {new_target} ({valid_cols.get(new_target, {}).get('count', 0)} items)")
                        fixed_count += 1
                    time.sleep(0.1)

    print(f"Finished audit: {fixed_count} redirects updated to high-inventory collections.")


def run_sync(dry_run: bool = False, init_snapshot: bool = False, fix_existing: bool = False):
    """Main execution routine."""
    print("=" * 70)
    print("  MeeeShop Proactive Auto-Redirect Sync Engine (High Inventory >= 20)")
    print(f"  Store: {STORE} | Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 70)

    # 1. Fetch valid collections with >= 20 active products
    valid_cols = fetch_valid_collections()

    # If requested to fix existing redirects targeting thin collections
    if fix_existing:
        fix_existing_thin_redirects(valid_cols, dry_run=dry_run)

    current_products = fetch_all_active_products()

    # If initializing baseline snapshot
    if init_snapshot or not SNAPSHOT_FILE.exists():
        print(f"\nInitializing baseline catalog snapshot ({len(current_products)} products)...")
        with open(SNAPSHOT_FILE, "w", encoding="utf-8") as f:
            json.dump(current_products, f, indent=2)
        print(f"Snapshot saved to {SNAPSHOT_FILE}")
        return

    # Load previous snapshot
    with open(SNAPSHOT_FILE, "r", encoding="utf-8") as f:
        previous_snapshot = json.load(f)

    # Detect deleted/discontinued handles
    missing_handles = set(previous_snapshot.keys()) - set(current_products.keys())
    print(f"\nDetected {len(missing_handles)} products removed/discontinued since last snapshot.")

    if not missing_handles:
        print("All catalog items are active. No new redirects required.")
        with open(SNAPSHOT_FILE, "w", encoding="utf-8") as f:
            json.dump(current_products, f, indent=2)
        return

    existing_redirects = fetch_existing_redirects()
    newly_created = []

    for handle in sorted(missing_handles):
        src_path = f"/products/{handle}"
        
        meta = previous_snapshot.get(handle, {})
        target = get_smart_target_collection(
            path_or_handle=handle,
            title=meta.get("title", ""),
            product_type=meta.get("productType", ""),
            vendor=meta.get("vendor", ""),
            tags=meta.get("tags", []),
            valid_cols=valid_cols
        )

        col_item_count = valid_cols.get(target, {}).get("count", 0)

        # If redirect already exists, check if target needs upgrading to >= 20 collection
        if src_path in existing_redirects:
            curr_target = existing_redirects[src_path]["target"].split("?")[0].rstrip("/")
            if curr_target not in valid_cols and curr_target != "/collections/all":
                red_id = existing_redirects[src_path]["id"]
                if not dry_run:
                    create_or_update_redirect(src_path, target, redirect_id=red_id)
                    print(f"[UPGRADED] {src_path}: {curr_target} -> {target} ({col_item_count} items)")
            continue

        if dry_run:
            print(f"[DRY-RUN] Would create: {src_path} -> {target} ({col_item_count} items)")
            newly_created.append({"path": src_path, "target": target})
        else:
            success = create_or_update_redirect(src_path, target)
            if success:
                print(f"[CREATED] {src_path} -> {target} ({col_item_count} items)")
                newly_created.append({
                    "path": src_path, 
                    "target": target, 
                    "items_in_collection": col_item_count,
                    "created_at": datetime.now(timezone.utc).isoformat()
                })
                existing_redirects[src_path] = {"id": None, "target": target}
            time.sleep(0.1)

    print(f"\nProcessed {len(newly_created)} new proactive redirects targeting collections with >= {MIN_COLLECTION_PRODUCTS} items.")

    # Save to history
    if newly_created and not dry_run:
        history = []
        if HISTORY_FILE.exists():
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                try:
                    history = json.load(f)
                except Exception:
                    history = []
        history.extend(newly_created)
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)

    # Save updated snapshot
    if not dry_run:
        with open(SNAPSHOT_FILE, "w", encoding="utf-8") as f:
            json.dump(current_products, f, indent=2)
        print(f"Catalog snapshot updated with {len(current_products)} active products.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Proactive Auto-Redirect Sync for MeeeShop (>= 20 products)")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without creating redirects")
    parser.add_argument("--init-snapshot", action="store_true", help="Initialize baseline catalog snapshot")
    parser.add_argument("--fix-existing", action="store_true", help="Scan and fix existing redirects pointing to thin/empty collections")
    args = parser.parse_args()

    run_sync(dry_run=args.dry_run, init_snapshot=args.init_snapshot, fix_existing=args.fix_existing)

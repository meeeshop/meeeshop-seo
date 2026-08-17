#!/usr/bin/env python3
"""
auto_redirect_sync.py — Proactive Automatic 301 Redirect Sync for MeeeShop
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Automatically detects deleted, archived, or missing products and creates
native Shopify 301 URL redirects to the most relevant collection before
Googlebot or shoppers encounter 404 errors.

How it works:
  1. Fetches all active products from Shopify GraphQL.
  2. Compares against the persistent catalog snapshot (data/catalog_snapshot.json).
  3. For any handle that was removed/deleted:
     - Extracts title, type, vendor, and tags from snapshot metadata.
     - Classifies the item to its exact category/brand collection.
     - Creates the native Shopify 301 URL Redirect via GraphQL.
  4. Saves the updated catalog snapshot.

Usage:
  python auto_redirect_sync.py                 # Sync and create missing redirects
  python auto_redirect_sync.py --dry-run       # Preview without creating
  python auto_redirect_sync.py --init-snapshot # Initialize baseline catalog snapshot
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

# ── Category Classifier ──
CATEGORY_RULES = [
    # Brands
    (r"\b(judy\s*blue|jb)\b", "/collections/judy-blue-womens-jeans"),
    (r"\b(pol|p\.o\.l)\b", "/collections/pol-womens-clothing-collection"),
    (r"\b(umgee)\b", "/collections/umgee-womens-clothing"),
    (r"\b(bibi)\b", "/collections/bibi-womens-clothing"),
    (r"\b(risen)\b", "/collections/risen-womens-jeans-collection"),
    (r"\b(zenana)\b", "/collections/zenana-womens-clothing"),
    (r"\b(hyfve)\b", "/collections/hyfve-womens-clothing"),
    (r"\b(emory\s*park)\b", "/collections/emory-park-womens-clothing"),
    (r"\b(so\s*me)\b", "/collections/so-me-clothing"),
    (r"\b(davi\s*dani)\b", "/collections/davi-dani-womens-apparel"),
    (r"\b(kancan)\b", "/collections/kancan-usa-womens-jeans"),
    (r"\b(vervet|flying\s*monkey)\b", "/collections/vervet-by-flying-monkey-womens-jeans"),
    (r"\b(mkf|mia\s*k)\b", "/collections/womens-handbags-accessories"),

    # Specific Product Types
    (r"\b(maxi\s*dress|maxi)\b", "/collections/womens-maxi-dresses"),
    (r"\b(midi\s*dress|midi)\b", "/collections/midi-dresses"),
    (r"\b(mini\s*dress|mini)\b", "/collections/mini-dresses"),
    (r"\b(cocktail\s*dress|evening\s*dress)\b", "/collections/womens-formal-evening-dresses"),
    (r"\b(dress|dresses|sundress|shirtdress|babydoll)\b", "/collections/womens-dresses"),
    
    (r"\b(flare\s*jean|bell\s*bottom)\b", "/collections/flare-jeans"),
    (r"\b(wide\s*leg|palazzo|baggy)\b", "/collections/wide-leg-jeans"),
    (r"\b(straight\s*leg|straight\s*jeans|mom\s*jeans|boyfriend\s*jeans)\b", "/collections/straight-leg-jeans"),
    (r"\b(skinny\s*jeans|jeggings)\b", "/collections/womens-skinny-jeans"),
    (r"\b(jeans|denim|jorts)\b", "/collections/womens-jeans"),

    (r"\b(sweater|cardigan|pullover|knit\s*top|turtleneck|hoodie|sweatshirt)\b", "/collections/womens-sweaters"),
    (r"\b(tank|cami|sleeveless|crop\s*top|tube\s*top|halter)\b", "/collections/womens-camis-tanks-tops"),
    (r"\b(graphic\s*tee|vintage\s*tee|band\s*tee|t-shirt|tee)\b", "/collections/womens-t-shirts"),
    (r"\b(top|blouse|shirt|shacket|tunic|button\s*down)\b", "/collections/womens-tops"),

    (r"\b(sandal|sandals|wedge|wedges|heels|heel|flats|flat|sneaker|sneakers|boot|boots|bootie|booties|clog|clogs|shoe|shoes)\b", "/collections/womens-shoes"),
    (r"\b(bag|tote|backpack|crossbody|clutch|sling|purse|fanny|handbag|satchel)\b", "/collections/womens-handbags-accessories"),
    
    (r"\b(romper|jumpsuit|overalls|overall|outfit\s*set|lounge\s*set|pant\s*set|short\s*set|2pcs|2-piece)\b", "/collections/womens-rompers-jumpsuit-sets"),
    (r"\b(skirt|skort)\b", "/collections/womens-skirts"),
    (r"\b(shorts|biker\s*short|bermuda)\b", "/collections/womens-shorts"),
    (r"\b(jacket|coat|vest|blazer|outerwear|trench)\b", "/collections/womens-outerwear"),
    (r"\b(legging|leggings|jogger|joggers|pants|pant|trousers)\b", "/collections/womens-pants-leggings"),
]

def get_smart_target(path_or_handle: str, title: str = "", product_type: str = "", vendor: str = "", tags: list = None) -> str:
    """Determine the optimal target collection for a product."""
    combined = f"{path_or_handle} {title} {product_type} {vendor} {' '.join(tags or [])}".lower()
    combined = combined.replace("-", " ").replace("_", " ")

    for pattern, target in CATEGORY_RULES:
        if re.search(pattern, combined):
            return target

    return "/collections/womens-new-collection"


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


def fetch_existing_redirect_paths() -> set:
    """Pre-fetch all existing redirect paths from Shopify."""
    existing_paths = set()
    url = f"{BASE_URL}/redirects.json?limit=250"
    while url:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        if resp.status_code != 200:
            break
        data = resp.json().get("redirects", [])
        for r in data:
            existing_paths.add(r.get("path", "").strip())
        
        # Pagination via Link header
        link_header = resp.headers.get("Link", "")
        next_url = None
        if "rel=\"next\"" in link_header:
            for part in link_header.split(","):
                if "rel=\"next\"" in part:
                    next_url = part.split(";")[0].strip("<> ")
        url = next_url

    print(f"Total existing Shopify redirects: {len(existing_paths)}")
    return existing_paths


def create_redirect(path: str, target: str) -> bool:
    """Create a 301 redirect in Shopify."""
    url = f"{BASE_URL}/redirects.json"
    payload = {"redirect": {"path": path, "target": target}}
    try:
        resp = requests.post(url, headers=HEADERS, json=payload, timeout=15)
        if resp.status_code in [200, 201]:
            return True
        elif resp.status_code == 422:
            return False  # Already exists
        else:
            time.sleep(1)
            resp = requests.post(url, headers=HEADERS, json=payload, timeout=15)
            return resp.status_code in [200, 201]
    except Exception as e:
        print(f"  Error creating redirect for {path}: {e}")
        return False


def run_sync(dry_run: bool = False, init_snapshot: bool = False):
    """Main execution routine."""
    print("=" * 65)
    print("  MeeeShop Proactive Auto-Redirect Sync Engine")
    print(f"  Store: {STORE} | Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 65)

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
        # Update snapshot last_seen
        with open(SNAPSHOT_FILE, "w", encoding="utf-8") as f:
            json.dump(current_products, f, indent=2)
        return

    existing_redirects = fetch_existing_redirect_paths()
    newly_created = []

    for handle in sorted(missing_handles):
        src_path = f"/products/{handle}"
        if src_path in existing_redirects:
            continue

        meta = previous_snapshot.get(handle, {})
        target = get_smart_target(
            path_or_handle=handle,
            title=meta.get("title", ""),
            product_type=meta.get("productType", ""),
            vendor=meta.get("vendor", ""),
            tags=meta.get("tags", [])
        )

        if dry_run:
            print(f"[DRY-RUN] Would create: {src_path} -> {target}")
            newly_created.append({"path": src_path, "target": target})
        else:
            success = create_redirect(src_path, target)
            if success:
                print(f"[CREATED] {src_path} -> {target}")
                newly_created.append({"path": src_path, "target": target, "created_at": datetime.now(timezone.utc).isoformat()})
                existing_redirects.add(src_path)
            time.sleep(0.1)

    print(f"\nCreated {len(newly_created)} new proactive redirects.")

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
    parser = argparse.ArgumentParser(description="Proactive Auto-Redirect Sync for MeeeShop")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without creating redirects")
    parser.add_argument("--init-snapshot", action="store_true", help="Initialize baseline catalog snapshot")
    args = parser.parse_args()

    run_sync(dry_run=args.dry_run, init_snapshot=args.init_snapshot)

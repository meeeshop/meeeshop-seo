#!/usr/bin/env python3
"""
deploy_404_smart_redirects.py — Deploy Smart 301 Redirects for 404 Pages
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Connects to Shopify Admin GraphQL API using store secrets.
Pre-fetches existing redirects in bulk for high performance, then creates/updates
redirects for all GSC-reported 404 URLs, mapping them to exact Brand & Category
collections instead of soft-404 targets.
"""

import os
import sys
import csv
import json
import time
from urllib.parse import urlparse
from pathlib import Path
import requests

# ── Path & Credentials Setup ──────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from secrets_manager import get_secret

STORE = get_secret("SHOPIFY_STORE")
TOKEN = get_secret("SHOPIFY_ACCESS_TOKEN")
STORE_URL = get_secret("STORE_BASE_URL").rstrip("/")
API_VER = "2024-10"
BASE_URL = f"https://{STORE}/admin/api/{API_VER}"
HEADERS = {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}

# ── Smart Taxonomy Categorization ─────────────────────────────────────────────
def get_smart_target_collection(path: str) -> str:
    slug = path.split("/")[-1].lower()

    # 1. Blogs
    if path.startswith("/blogs/"):
        if "jean" in slug: return "/blogs/jeans-style-guide"
        if "dress" in slug: return "/blogs/dresses-style-guide"
        if "skirt" in slug: return "/blogs/womens-skirts-style-guide"
        if "pant" in slug: return "/blogs/womens-pants-style-guide"
        if "shirt" in slug or "top" in slug: return "/blogs/womens-shirts-tops-style-guide"
        if "coat" in slug or "jacket" in slug: return "/blogs/coats-jackets-style-guide"
        return "/blogs/our-tips"

    # 2. Legacy / Deleted Collection Paths
    if path.startswith("/collections/"):
        if any(w in slug for w in ["shoe", "sandals", "heels", "boots"]): return "/collections/womens-shoes"
        if "dress" in slug: return "/collections/womens-dresses"
        if "top" in slug: return "/collections/womens-tops"
        if "jean" in slug: return "/collections/womens-jeans"
        if "zenana" in slug: return "/collections/zenana-womens-clothing"
        if "flying-monkey" in slug: return "/collections/flying-monkey-womens-jeans-collection"
        return "/collections/womens-new-collection"

    # 3. Specific Brand Mapping
    if "judy-blue" in slug or "judy_blue" in slug: return "/collections/judy-blue-womens-jeans"
    if "pol-" in slug or "pol_" in slug or slug.startswith("pol-") or "womens-pol-" in slug or "-pol-" in slug:
        return "/collections/pol-womens-clothing-collection"
    if "risen" in slug: return "/collections/risen-womens-jeans-collection"
    if "zenana" in slug: return "/collections/zenana-womens-clothing"
    if "bibi" in slug: return "/collections/bibi-womens-clothing"
    if "hyfve" in slug: return "/collections/hyfve-womens-clothing"
    if "kancan" in slug: return "/collections/kancan-usa-womens-jeans"
    if "flying-monkey" in slug: return "/collections/flying-monkey-womens-jeans-collection"
    if "vervet" in slug: return "/collections/vervet-by-flying-monkey-womens-jeans"
    if "celeste" in slug: return "/collections/celeste-clothing"
    if "emory-park" in slug: return "/collections/emory-park-womens-clothing"
    if "heyson" in slug: return "/collections/heyson-clothing"
    if "le-lis" in slug: return "/collections/le-lis-womens-clothing"
    if "lilou" in slug: return "/collections/lilou-womens-clothing-collection"
    if "white-birch" in slug: return "/collections/white-birch-womens-clothing"
    if "fame" in slug: return "/collections/fame-accessories"
    if "davi-dani" in slug: return "/collections/davi-dani-womens-apparel"
    if "recycled-karma" in slug: return "/collections/recycled-karma-womens-graphic-tees"
    if "acting-pro" in slug: return "/collections/acting-pro-womens-clothing-collection-us-meeeshop"
    if "gilli" in slug: return "/collections/gilli-womens-clothing-collection"
    if "mustard-seed" in slug: return "/collections/mustard-seed-womens-clothing"
    if "ninexis" in slug: return "/collections/ninexis-womens-clothing-collection"
    if "orange-farm" in slug: return "/collections/orange-farm-womens-clothing"
    if "la-miel" in slug: return "/collections/la-miel-womens-clothing-collection"
    if "hailey-co" in slug: return "/collections/hailey-co"
    if "oddi" in slug: return "/collections/oddi"
    if "amoli" in slug: return "/collections/amoli"
    if "kimberly-c" in slug: return "/collections/kimberly-c"
    if "yelete" in slug: return "/collections/yelete-womens-clothing"
    if "culture-code" in slug: return "/collections/culture-code-womens-clothing"
    if "justin-taylor" in slug: return "/collections/justin-taylor-apparel-accessories"
    if "jade-by-jane" in slug: return "/collections/jade-by-jane-womens-clothing"
    if "insane-gene" in slug: return "/collections/insane-gene-womens-denim"
    if "very-j" in slug: return "/collections/very-j-womens-clothing"
    if "e-luna" in slug: return "/collections/e-luna-womens-clothing"
    if "artemis-vintage" in slug: return "/collections/artemis-vintage-womens-jeans"
    if "himawari" in slug: return "/collections/himawari-backpacks"

    # 4. Product Type & Category Matching
    # Shoes & Footwear
    if any(w in slug for w in ["sandal", "sneaker", "bootie", "boots", "flat", "wedge", "heeled", "shoes", "footwear", "clogs", "platform", "slide", "toe-ring", "thong", "lace-up"]):
        return "/collections/womens-shoes"

    # Dresses
    if any(w in slug for w in ["maxi"]): return "/collections/womens-maxi-dresses"
    if any(w in slug for w in ["dress", "sundress", "babydoll", "gown", "shift-dress", "mini-dress", "midi-dress", "tiered-dress"]):
        return "/collections/womens-dresses"

    # Rompers, Jumpsuits & Sets
    if any(w in slug for w in ["romper", "jumpsuit", "set", "outfit", "2pcs", "two-pcs", "pant-set", "lounge-set", "sweat-set", "shorts-set"]):
        return "/collections/womens-rompers-jumpsuit-sets"

    # Jeans & Denim
    if any(w in slug for w in ["jean", "jeans", "denim", "barrel", "flare", "bootcut", "straight-leg", "palazzo", "jorts", "wide-leg", "mom-jeans", "skinny", "tummy-control", "crop-jeans"]):
        return "/collections/womens-jeans"

    # Shorts & Skirts
    if any(w in slug for w in ["short", "shorts", "bermuda", "skort"]): return "/collections/womens-shorts"
    if any(w in slug for w in ["skirt", "mini-skirt", "maxi-skirt", "swing-skirt"]): return "/collections/womens-skirts"

    # Pants & Leggings
    if any(w in slug for w in ["pants", "trouser", "jogger", "legging", "leggings", "culotte", "culottes"]): return "/collections/womens-pants-leggings"

    # Outerwear, Sweaters & Hoodies
    if any(w in slug for w in ["sweater", "cardigan", "pullover", "knit-sweater", "cable-knit"]): return "/collections/womens-sweaters"
    if any(w in slug for w in ["hoodie", "sweatshirt"]): return "/collections/womens-sweatshirts-hoodies"
    if any(w in slug for w in ["jacket", "coat", "vest", "shacket", "puffer", "fleece", "sherpa", "blazer", "outerwear", "windbreaker", "bomber"]):
        return "/collections/womens-outerwear"

    # Tops, Shirts & Tees
    if any(w in slug for w in ["tee", "t-shirt", "graphic-tee"]): return "/collections/womens-t-shirts"
    if any(w in slug for w in ["tank", "cami", "crop-top", "bustier", "tube-top", "halter"]): return "/collections/womens-camis-tanks-tops"
    if any(w in slug for w in ["blouse", "shirt", "button-down", "button-up", "peplum", "tunic", "top", "wrap-top", "knit-top"]):
        return "/collections/womens-tops"

    # Bags & Accessories
    if any(w in slug for w in ["bag", "tote", "clutch", "backpack", "fanny", "purse", "wristlet", "crossbody", "messenger", "bum-bag", "shoulder-bag"]):
        return "/collections/womens-handbags-accessories"
    if any(w in slug for w in ["hat", "scarf"]): return "/collections/womens-hats-scarves"

    # Curvy & Plus Size
    if any(w in slug for w in ["plus-size", "plus", "curvy"]): return "/collections/womens-curvy-plus-size-clothing"

    return "/collections/womens-new-collection"

# ── Load URLs to Redirect ────────────────────────────────────────────────────
def find_file_upwards(relative_path: str) -> Path | None:
    curr = Path(__file__).resolve()
    for p in curr.parents:
        cand = p / relative_path
        if cand.exists():
            return cand
    return None

def load_all_404_paths() -> dict[str, str]:
    candidates = {}
    
    # 1. Check Table.csv in 404 directory
    table_csv = find_file_upwards("404/Table.csv")
    if table_csv:
        print(f"Loading URLs from {table_csv}...")
        with open(table_csv, "r", encoding="utf-8", errors="ignore") as f:
            reader = csv.reader(f)
            next(reader, None)
            for row in reader:
                if row and row[0]:
                    p = urlparse(row[0].strip()).path.strip()
                    if p and p not in ["/products/*", "/collections/*", "/*account*", "/*"]:
                        candidates[p] = get_smart_target_collection(p)
                        
    # 2. Check shopify_redirects_upload.csv in 404 directory
    upload_csv = find_file_upwards("404/shopify_redirects_upload.csv")
    if upload_csv:
        print(f"Loading URLs from {upload_csv}...")
        with open(upload_csv, "r", encoding="utf-8", errors="ignore") as f:
            reader = csv.reader(f)
            next(reader, None)
            for row in reader:
                if row and row[0]:
                    p = urlparse(row[0].strip()).path.strip()
                    if p and p not in ["/products/*", "/collections/*", "/*account*", "/*"]:
                        if p not in candidates:
                            candidates[p] = get_smart_target_collection(p)

    print(f"Total unique 404 paths mapped: {len(candidates)}")
    return candidates

# ── Shopify GraphQL Operations ────────────────────────────────────────────────
def graphql_post(query: str, variables: dict = None) -> dict:
    url = f"{BASE_URL}/graphql.json"
    payload = {"query": query}
    if variables:
        payload["variables"] = variables

    for attempt in range(5):
        resp = requests.post(url, headers=HEADERS, json=payload, timeout=25)
        if resp.status_code == 429:
            retry_after = float(resp.headers.get("Retry-After", 2.0))
            print(f"  [Rate Limit] Sleeping {retry_after}s...")
            time.sleep(retry_after)
            continue
        if resp.status_code == 200:
            return resp.json()
        time.sleep(1.0)

    raise Exception(f"GraphQL request failed after 5 retries (Status {resp.status_code}): {resp.text}")

def create_redirect_graphql(path: str, target: str) -> tuple[bool, str]:
    mut = """
    mutation urlRedirectCreate($urlRedirect: UrlRedirectInput!) {
      urlRedirectCreate(urlRedirect: $urlRedirect) {
        urlRedirect {
          id
          path
          target
        }
        userErrors {
          field
          message
        }
      }
    }
    """
    res = graphql_post(mut, {"urlRedirect": {"path": path, "target": target}})
    data = res.get("data", {}).get("urlRedirectCreate", {})
    errors = data.get("userErrors", [])
    if errors:
        return False, errors[0].get("message", "Unknown error")
    return True, data.get("urlRedirect", {}).get("id", "")

def update_redirect_graphql(redirect_id: str, path: str, target: str) -> tuple[bool, str]:
    mut = """
    mutation urlRedirectUpdate($id: ID!, $urlRedirect: UrlRedirectInput!) {
      urlRedirectUpdate(id: $id, urlRedirect: $urlRedirect) {
        urlRedirect {
          id
          path
          target
        }
        userErrors {
          field
          message
        }
      }
    }
    """
    res = graphql_post(mut, {"id": redirect_id, "urlRedirect": {"path": path, "target": target}})
    data = res.get("data", {}).get("urlRedirectUpdate", {})
    errors = data.get("userErrors", [])
    if errors:
        return False, errors[0].get("message", "Unknown error")
    return True, data.get("urlRedirect", {}).get("id", "")

def fetch_all_existing_redirects() -> dict[str, dict]:
    print("Pre-fetching all existing redirects from Shopify...")
    existing = {}
    
    query = """
    query ($first: Int!, $after: String) {
      urlRedirects(first: $first, after: $after) {
        pageInfo {
          hasNextPage
          endCursor
        }
        edges {
          node {
            id
            path
            target
          }
        }
      }
    }
    """
    has_next = True
    cursor = None
    batch = 0
    
    while has_next:
        batch += 1
        res = graphql_post(query, {"first": 250, "after": cursor})
        data = res.get("data", {}).get("urlRedirects", {})
        edges = data.get("edges", [])
        
        for edge in edges:
            node = edge.get("node", {})
            p = node.get("path")
            if p:
                existing[p] = {
                    "id": node.get("id"),
                    "target": node.get("target")
                }
                
        page_info = data.get("pageInfo", {})
        has_next = page_info.get("hasNextPage", False)
        cursor = page_info.get("endCursor")
        
        if batch % 10 == 0 or not has_next:
            print(f"  Loaded {len(existing)} existing redirects so far...")
            
        time.sleep(0.1)
        
    print(f"Total existing redirects indexed in memory: {len(existing)}")
    return existing

# ── Main Deployment Loop ─────────────────────────────────────────────────────
def deploy_redirects():
    print("=" * 65)
    print("  Deploying Smart 301 Redirects to Shopify via GraphQL")
    print(f"  Store: {STORE}")
    print("=" * 65)

    redirects_to_deploy = load_all_404_paths()
    if not redirects_to_deploy:
        print("No 404 paths found to deploy. Exiting.")
        return

    # Pre-fetch existing redirects
    existing_redirects = fetch_all_existing_redirects()

    stats = {
        "total": len(redirects_to_deploy),
        "created": 0,
        "updated": 0,
        "already_accurate": 0,
        "failed": 0
    }

    print(f"\nProcessing {len(redirects_to_deploy)} 404 paths...\n")
    
    count = 0
    for src_path, target_path in redirects_to_deploy.items():
        count += 1
        prefix = f"[{count}/{len(redirects_to_deploy)}]"
        
        try:
            if src_path in existing_redirects:
                curr = existing_redirects[src_path]
                curr_target = curr["target"]
                redirect_id = curr["id"]
                
                # Check if it already points to the exact smart collection
                if curr_target == target_path:
                    stats["already_accurate"] += 1
                else:
                    # Update generic / old targets (e.g. /collections/all) to specific collection
                    success, msg = update_redirect_graphql(redirect_id, src_path, target_path)
                    if success:
                        print(f"{prefix} [UPDATED] {src_path} -> {target_path} (was: {curr_target})")
                        stats["updated"] += 1
                    else:
                        print(f"{prefix} [UPDATE-ERR] {src_path} ({msg})")
                        stats["failed"] += 1
                    time.sleep(0.15)
            else:
                # Create brand new redirect
                success, msg = create_redirect_graphql(src_path, target_path)
                if success:
                    print(f"{prefix} [CREATED] {src_path} -> {target_path}")
                    stats["created"] += 1
                else:
                    print(f"{prefix} [CREATE-ERR] {src_path} ({msg})")
                    stats["failed"] += 1
                time.sleep(0.15)

        except Exception as e:
            print(f"{prefix} [ERROR] {src_path}: {e}")
            stats["failed"] += 1

    # Save Summary Report
    report_dir = Path(__file__).parent.parent / "reports"
    report_dir.mkdir(exist_ok=True)
    report_path = report_dir / "404_redirects_deployment_report.json"
    report_path.write_text(json.dumps(stats, indent=2), encoding="utf-8")

    print("\n" + "=" * 65)
    print("  Deployment Complete")
    print(f"  Total Processed:    {stats['total']}")
    print(f"  Newly Created:      {stats['created']}")
    print(f"  Updated to Smart:   {stats['updated']}")
    print(f"  Already Accurate:   {stats['already_accurate']}")
    print(f"  Failed:             {stats['failed']}")
    print(f"  Report Saved to:    {report_path}")
    print("=" * 65)

if __name__ == "__main__":
    deploy_redirects()

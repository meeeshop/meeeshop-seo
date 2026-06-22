#!/usr/bin/env python3
"""
increase_orange_farm_prices.py — Locate draft products under the 'Orange Farm Clothing' vendor
and add $20 to all their variant prices. Supports dry-run and reversion from backup logs.
"""

import os
import sys
import json
import time
import argparse
import requests
from datetime import datetime, timezone
from pathlib import Path

# Add parent directory and scripts directory to python path for importing secrets_manager
scripts_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(scripts_dir))
sys.path.insert(0, scripts_dir)

from secrets_manager import inject_to_env, get_secret
inject_to_env()

store = get_secret("SHOPIFY_STORE")
token = get_secret("SHOPIFY_ACCESS_TOKEN")

API_VERSION = "2025-01"
BASE_URL = f"https://{store}/admin/api/{API_VERSION}/graphql.json"
HEADERS = {
    "X-Shopify-Access-Token": token,
    "Content-Type": "application/json"
}

# Configure standard encoding for Windows terminal
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')


def run_graphql(query: str, variables: dict = None) -> dict:
    """Run GraphQL Admin API query with retry on rate limit."""
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
        
    for attempt in range(5):
        try:
            resp = requests.post(BASE_URL, headers=HEADERS, json=payload, timeout=30)
            if resp.status_code == 429:
                retry_after = float(resp.headers.get("Retry-After", 2.0))
                print(f"[RateLimit] 429 received, sleeping {retry_after}s...")
                time.sleep(retry_after)
                continue
            resp.raise_for_status()
            result = resp.json()
            if "errors" in result:
                print(f"[GraphQL Error] {result['errors']}", file=sys.stderr)
            return result
        except requests.exceptions.RequestException as e:
            if attempt < 4:
                sleep_time = 2.0 ** attempt
                print(f"[Network Error] {e}, retrying in {sleep_time}s...")
                time.sleep(sleep_time)
            else:
                raise e
    raise RuntimeError("GraphQL request failed after 5 attempts")


def fetch_draft_products_by_vendor(target_vendor: str = "Orange Farm Clothing") -> list:
    """Scan all draft products and filter by vendor (case-insensitive)."""
    # Query fetches draft products
    query = """
    query ($first: Int!, $after: String, $queryStr: String) {
      products(first: $first, after: $after, query: $queryStr) {
        pageInfo {
          hasNextPage
          endCursor
        }
        edges {
          node {
            id
            title
            vendor
            status
            variants(first: 100) {
              edges {
                node {
                  id
                  sku
                  price
                }
              }
            }
          }
        }
      }
    }
    """
    
    # We query status:draft on Shopify
    query_str = "status:draft"
    
    products_found = []
    has_next = True
    cursor = None
    page = 1
    
    target_lower = target_vendor.lower()
    
    print(f"Scanning draft products on Shopify for vendor '{target_vendor}'...")
    while has_next:
        variables = {"first": 100, "after": cursor, "queryStr": query_str}
        data = run_graphql(query, variables)
        
        prod_data = data.get("data", {}).get("products", {})
        edges = prod_data.get("edges", [])
        
        for edge in edges:
            node = edge["node"]
            vendor = (node.get("vendor") or "").strip()
            
            # Check vendor case-insensitively
            if vendor.lower() == target_lower:
                variants = []
                for v in node["variants"]["edges"]:
                    vn = v["node"]
                    variants.append({
                        "id": vn["id"],
                        "sku": vn.get("sku", "") or "",
                        "price": vn["price"]
                    })
                
                products_found.append({
                  "id": node["id"],
                  "title": node["title"],
                  "vendor": vendor,
                  "status": node["status"],
                  "variants": variants
                })
                
        page_info = prod_data.get("pageInfo", {})
        has_next = page_info.get("hasNextPage", False)
        cursor = page_info.get("endCursor")
        print(f"  Scanned page {page}. Matches found so far: {len(products_found)}")
        page += 1
        
    return products_found


def perform_price_updates(products: list, dry_run: bool = False) -> bool:
    """Increase price by $20 for all variants of target products."""
    mutation = """
    mutation productVariantsBulkUpdate($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
      productVariantsBulkUpdate(productId: $productId, variants: $variants) {
        product {
          id
        }
        productVariants {
          id
          price
        }
        userErrors {
          field
          message
        }
      }
    }
    """
    
    total_products = len(products)
    success_count = 0
    error_count = 0
    
    print(f"\nStarting price updates for {total_products} products...")
    for idx, product in enumerate(products, 1):
        product_id = product["id"]
        title = product["title"]
        variants = product["variants"]
        
        variant_inputs = []
        print(f"[{idx}/{total_products}] Processing '{title}'...")
        for var in variants:
            old_price = float(var["price"])
            new_price = round(old_price + 20.00, 2)
            print(f"    Variant {var['id']} ({var['sku']}): ${old_price:.2f} -> ${new_price:.2f}")
            
            variant_inputs.append({
                "id": var["id"],
                "price": f"{new_price:.2f}"
            })
            
        if dry_run:
            print("    [DRY RUN] Skipped writing to Shopify")
            success_count += 1
            continue
            
        variables = {
            "productId": product_id,
            "variants": variant_inputs
        }
        
        try:
            res = run_graphql(mutation, variables)
            bulk_res = res.get("data", {}).get("productVariantsBulkUpdate", {})
            errors = bulk_res.get("userErrors", [])
            
            if errors:
                print(f"  [ERROR] Failed to update '{title}': {errors}", file=sys.stderr)
                error_count += 1
            else:
                print("    ✓ Prices updated successfully")
                success_count += 1
                
        except Exception as e:
            print(f"  [EXCEPTION] Failed to update '{title}': {e}", file=sys.stderr)
            error_count += 1
            
        time.sleep(0.4)  # respect rate limits
        
    print(f"\nPrice updates completed: {success_count} succeeded, {error_count} failed.")
    return error_count == 0


def revert_price_updates(backup_path: str, dry_run: bool = False) -> bool:
    """Restore variant prices to their original state from a backup file."""
    mutation = """
    mutation productVariantsBulkUpdate($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
      productVariantsBulkUpdate(productId: $productId, variants: $variants) {
        product {
          id
        }
        productVariants {
          id
          price
        }
        userErrors {
          field
          message
        }
      }
    }
    """
    
    if not os.path.exists(backup_path):
        sys.exit(f"ERROR: Backup file '{backup_path}' does not exist.")
        
    with open(backup_path, "r", encoding="utf-8") as f:
        backup_data = json.load(f)
        
    products = backup_data.get("products", [])
    total_products = len(products)
    success_count = 0
    error_count = 0
    
    print(f"\nReverting price updates for {total_products} products from backup file...")
    for idx, product in enumerate(products, 1):
        product_id = product["id"]
        title = product["title"]
        variants = product["variants"]
        
        variant_inputs = []
        print(f"[{idx}/{total_products}] Reverting '{title}'...")
        for var in variants:
            old_price = float(var["price"])
            print(f"    Variant {var['id']} ({var['sku']}) -> Restoring to: ${old_price:.2f}")
            
            variant_inputs.append({
                "id": var["id"],
                "price": f"{old_price:.2f}"
            })
            
        if dry_run:
            print("    [DRY RUN] Skipped writing to Shopify")
            success_count += 1
            continue
            
        variables = {
            "productId": product_id,
            "variants": variant_inputs
        }
        
        try:
            res = run_graphql(mutation, variables)
            bulk_res = res.get("data", {}).get("productVariantsBulkUpdate", {})
            errors = bulk_res.get("userErrors", [])
            
            if errors:
                print(f"  [ERROR] Failed to revert '{title}': {errors}", file=sys.stderr)
                error_count += 1
            else:
                print("    ✓ Prices restored successfully")
                success_count += 1
                
        except Exception as e:
            print(f"  [EXCEPTION] Failed to revert '{title}': {e}", file=sys.stderr)
            error_count += 1
            
        time.sleep(0.4)  # respect rate limits
        
    print(f"\nReversion completed: {success_count} succeeded, {error_count} failed.")
    return error_count == 0


def main():
    parser = argparse.ArgumentParser(description="Locate draft products for vendor Orange Farm Clothing and add $20 to variant prices")
    parser.add_argument("--dry-run", action="store_true", help="Simulate updates without writing to Shopify")
    parser.add_argument("--revert", type=str, default="", help="Restore prices from a JSON backup file path")
    parser.add_argument("--vendor", type=str, default="Orange Farm Clothing", help="Vendor name filter (default: Orange Farm Clothing)")
    args = parser.parse_args()
    
    if args.revert:
        revert_price_updates(args.revert, dry_run=args.dry_run)
        sys.exit(0)
        
    # 1. Fetch matching draft products
    target_vendor = args.vendor
    products = fetch_draft_products_by_vendor(target_vendor)
    
    if not products:
        print(f"\nNo draft products found for vendor '{target_vendor}'. Nothing to do!")
        sys.exit(0)
        
    total_variants = sum(len(p["variants"]) for p in products)
    print(f"\nFound {total_variants} variant(s) across {len(products)} product(s) in draft status.")
    
    # 2. Save Backup (before updates)
    if not args.dry_run:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        scratch_dir = os.path.join(os.path.dirname(scripts_dir), "scratch")
        os.makedirs(scratch_dir, exist_ok=True)
        backup_file = os.path.join(scratch_dir, f"backup_orange_farm_prices_{timestamp}.json")
        
        print(f"Saving backup of current prices to {backup_file}...")
        backup_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "vendor": target_vendor,
            "total_products": len(products),
            "total_variants": total_variants,
            "products": products
        }
        
        with open(backup_file, "w", encoding="utf-8") as f:
            json.dump(backup_data, f, indent=2, ensure_ascii=False)
        print("Backup completed successfully.\n")
    
    # 3. Perform Updates
    success = perform_price_updates(products, dry_run=args.dry_run)
    if success:
        print(f"\nPrice updates successfully applied{' (Dry Run)' if args.dry_run else ''}!")
    else:
        print("\nPrice updates completed, but some errors occurred. Please check logs.")


if __name__ == "__main__":
    main()

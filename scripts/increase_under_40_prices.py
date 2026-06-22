import os
import sys
import json
import time
import requests
from datetime import datetime, timezone

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

def scan_prices_under_40() -> list:
    """Scan all active products and return a list of products having variants with price < 40.0."""
    query = """
    query ($first: Int!, $after: String) {
      products(first: $first, after: $after) {
        pageInfo {
          hasNextPage
          endCursor
        }
        edges {
          node {
            id
            title
            variants(first: 100) {
              edges {
                node {
                  id
                  sku
                  price
                  compareAtPrice
                }
              }
            }
          }
        }
      }
    }
    """
    
    products_under_40 = []
    has_next = True
    cursor = None
    page = 1
    
    print("Scanning products for variants with price < $40...")
    while has_next:
        variables = {"first": 100, "after": cursor}
        data = run_graphql(query, variables)
        
        prod_data = data.get("data", {}).get("products", {})
        edges = prod_data.get("edges", [])
        
        for edge in edges:
            node = edge["node"]
            variants_to_update = []
            for v in node["variants"]["edges"]:
                vn = v["node"]
                price_val = float(vn.get("price") or 0.0)
                if price_val < 40.0:
                    variants_to_update.append({
                        "id": vn["id"],
                        "sku": vn.get("sku", ""),
                        "price": vn["price"],
                        "compareAtPrice": vn.get("compareAtPrice")
                    })
            
            if variants_to_update:
                products_under_40.append({
                    "id": node["id"],
                    "title": node["title"],
                    "variants": variants_to_update
                })
                
        page_info = prod_data.get("pageInfo", {})
        has_next = page_info.get("hasNextPage", False)
        cursor = page_info.get("endCursor")
        print(f"  Scanned page {page}. Products found so far: {len(products_under_40)}")
        page += 1
        
    return products_under_40

def perform_bulk_update(products_to_update: list) -> bool:
    """Update variant prices to $44.99 in bulk product-by-product."""
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
    
    total_products = len(products_to_update)
    success_count = 0
    error_count = 0
    
    print(f"\nStarting price updates for {total_products} products...")
    for idx, product in enumerate(products_to_update, 1):
        product_id = product["id"]
        title = product["title"]
        variants = product["variants"]
        
        # Prepare bulk update input list
        variant_inputs = []
        for var in variants:
            variant_inputs.append({
                "id": var["id"],
                "price": "44.99"  # Update price to 44.99
            })
            
        print(f"[{idx}/{total_products}] Updating price to $44.99 for '{title}' ({len(variants)} variants)...")
        
        variables = {
            "productId": product_id,
            "variants": variant_inputs
        }
        
        try:
            res = run_graphql(mutation, variables)
            bulk_res = res.get("data", {}).get("productVariantsBulkUpdate", {})
            errors = bulk_res.get("userErrors", [])
            
            if errors:
                print(f"  [ERROR] Failed to update variants for '{title}': {errors}", file=sys.stderr)
                error_count += 1
            else:
                success_count += 1
                
        except Exception as e:
            print(f"  [EXCEPTION] Failed to update '{title}': {e}", file=sys.stderr)
            error_count += 1
            
        # Standard sleep to respect API limits
        time.sleep(0.4)
        
    print(f"\nUpdate processing complete: {success_count} succeeded, {error_count} failed.")
    return error_count == 0

def main():
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    
    # 1. Scan products
    products_to_update = scan_prices_under_40()
    if not products_to_update:
        print("\nNo product variants found with price < $40. Nothing to do!")
        sys.exit(0)
        
    total_variants = sum(len(p["variants"]) for p in products_to_update)
    print(f"\nFound {total_variants} variants across {len(products_to_update)} products to update.")
    
    # 2. Save Backup
    scratch_dir = os.path.join(os.path.dirname(scripts_dir), "scratch")
    os.makedirs(scratch_dir, exist_ok=True)
    backup_file = os.path.join(scratch_dir, f"backup_prices_under_40_{timestamp}.json")
    
    print(f"Saving backup to {backup_file}...")
    backup_data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_products": len(products_to_update),
        "total_variants": total_variants,
        "products": products_to_update
    }
    
    with open(backup_file, "w", encoding="utf-8") as f:
        json.dump(backup_data, f, indent=2, ensure_ascii=False)
    print("Backup completed successfully.\n")
    
    # 3. Perform clearance
    success = perform_bulk_update(products_to_update)
    if success:
        print("\nAll product prices updated successfully!")
    else:
        print("\nUpdate complete, but some errors occurred. Please check the logs.")

if __name__ == "__main__":
    main()

import os
import sys
import json
import time
from datetime import datetime

# Set up paths for import
scripts_dir = r"c:\Users\USER\Downloads\Shopify_Claude\Shopify_Claude\repos\meeeshop-seo\meeeshop-seo\scripts"
sys.path.insert(0, scripts_dir)

from secrets_manager import inject_to_env
inject_to_env()

from shopify_graphql import run_graphql

def fetch_all_mkf_products():
    print("Fetching all products from vendor 'MKF Dropship'...")
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
            productType
            status
            category {
              id
              name
            }
          }
        }
      }
    }
    """
    
    products = []
    has_next = True
    cursor = None
    
    while has_next:
        variables = {
            "first": 250,
            "queryStr": "vendor:'MKF Dropship'",
            "after": cursor
        }
        res = run_graphql(query, variables)
        prod_data = res.get("data", {}).get("products", {})
        
        for edge in prod_data.get("edges", []):
            products.append(edge["node"])
            
        page_info = prod_data.get("pageInfo", {})
        has_next = page_info.get("hasNextPage", False)
        cursor = page_info.get("endCursor")
        
    return products

def update_product(product_id, title):
    mutation = """
    mutation productUpdate($input: ProductInput!) {
      productUpdate(input: $input) {
        product {
          id
          title
          productType
          status
          category {
            id
            name
          }
        }
        userErrors {
          field
          message
        }
      }
    }
    """
    
    variables = {
      "input": {
        "id": product_id,
        "productType": "Handbags",
        "category": "gid://shopify/TaxonomyCategory/aa-5-4",
        "status": "ACTIVE"
      }
    }
    
    res = run_graphql(mutation, variables)
    errors = res.get("data", {}).get("productUpdate", {}).get("userErrors", [])
    if errors:
        print(f"  [ERROR] Error updating product '{title}' ({product_id}): {errors}")
        return False, errors
        
    p = res.get("data", {}).get("productUpdate", {}).get("product", {})
    cat_name = p.get("category", {}).get("name") if p.get("category") else "None"
    print(f"  [OK] Updated '{title}': Type='{p.get('productType')}', Cat='{cat_name}', Status='{p.get('status')}'")
    return True, None

def main():
    import argparse
    parser = argparse.ArgumentParser(description="One-time script to modify MKF Dropship products.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--diagnose", action="store_true", help="Diagnose and preview changes")
    group.add_argument("--apply", action="store_true", help="Apply updates directly to the store")
    args = parser.parse_args()
    
    products = fetch_all_mkf_products()
    print(f"Found {len(products)} products from vendor 'MKF Dropship'.")
    
    if args.diagnose:
        print("\n--- DIAGNOSE/PREVIEW MODE ---")
        for i, p in enumerate(products, 1):
            curr_cat = p.get("category", {}).get("name") if p.get("category") else "None"
            print(f"{i}. [Target Update] '{p['title']}' ({p['id']})")
            print(f"   Current: Type='{p['productType']}', Category='{curr_cat}', Status='{p['status']}'")
            print(f"   Target : Type='Handbags', Category='Handbags', Status='ACTIVE'")
            print("-" * 60)
        print("\nPreview complete. Run with --apply to execute updates.")
        
    elif args.apply:
        print("\n--- APPLY MODE ---")
        # 1. Create a local backup first
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = f"scratch/backup_mkf_products_{timestamp}.json"
        backup_path = os.path.join(r"c:\Users\USER\Downloads\Shopify_Claude\Shopify_Claude\repos\meeeshop-seo\meeeshop-seo", backup_file)
        
        backup_data = {
            "timestamp": timestamp,
            "products": products
        }
        
        with open(backup_path, "w", encoding="utf-8") as f:
            json.dump(backup_data, f, indent=2, ensure_ascii=False)
        print(f"Backup of current state saved to: {backup_path}")
        
        # 2. Apply updates
        success_count = 0
        fail_count = 0
        
        for i, p in enumerate(products, 1):
            print(f"[{i}/{len(products)}] Updating '{p['title']}'...")
            success, err = update_product(p["id"], p["title"])
            if success:
                success_count += 1
            else:
                fail_count += 1
            # Add a small sleep to avoid hitting limit immediately (though shopify_graphql handles 429 retries)
            time.sleep(0.1)
            
        print("\n--- Execution Summary ---")
        print(f"  Total Products Processed: {len(products)}")
        print(f"  Successful Updates      : {success_count}")
        print(f"  Failed Updates          : {fail_count}")

if __name__ == "__main__":
    main()

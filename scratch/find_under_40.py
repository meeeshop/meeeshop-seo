import os
import sys
import json
import requests

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
from secrets_manager import inject_to_env, get_secret
inject_to_env()

store = get_secret("SHOPIFY_STORE")
token = get_secret("SHOPIFY_ACCESS_TOKEN")

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

url = f"https://{store}/admin/api/2025-01/graphql.json"
headers = {
    "X-Shopify-Access-Token": token,
    "Content-Type": "application/json"
}

has_next = True
cursor = None
page = 1
total_variants_under_40 = 0
products_under_40 = []

print("Scanning products for prices under $40...")

while has_next:
    variables = {"first": 100, "after": cursor}
    resp = requests.post(url, headers=headers, json={"query": query, "variables": variables})
    resp.raise_for_status()
    data = resp.json()
    
    if "errors" in data:
        print(f"GraphQL Errors: {data['errors']}")
        break
        
    prod_data = data.get("data", {}).get("products", {})
    edges = prod_data.get("edges", [])
    
    for edge in edges:
        node = edge["node"]
        variants_under_40 = []
        for v in node["variants"]["edges"]:
            vn = v["node"]
            price_val = float(vn.get("price") or 0.0)
            if price_val < 40.0:
                variants_under_40.append(vn)
                total_variants_under_40 += 1
        
        if variants_under_40:
            products_under_40.append({
                "id": node["id"],
                "title": node["title"],
                "variants": variants_under_40
            })
            
    page_info = prod_data.get("pageInfo", {})
    has_next = page_info.get("hasNextPage", False)
    cursor = page_info.get("endCursor")
    print(f"Page {page} processed. Current total variants under $40: {total_variants_under_40}")
    page += 1

print(f"\nScan complete! Found {total_variants_under_40} variants (across {len(products_under_40)} products) with price < $40.")
for p in products_under_40[:10]:
    print(f"Product: {p['title']} ({p['id']})")
    for v in p["variants"]:
        print(f"  Variant: {v['id']} | SKU: {v['sku']} | Price: {v['price']}")
if len(products_under_40) > 10:
    print(f"... and {len(products_under_40) - 10} more products")

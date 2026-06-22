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
total_variants_with_compare = 0
products_with_compare = []

print("Scanning products...")

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
        variants_to_report = []
        for v in node["variants"]["edges"]:
            vn = v["node"]
            cap = vn.get("compareAtPrice")
            if cap is not None and float(cap) > 0.0:
                variants_to_report.append(vn)
                total_variants_with_compare += 1
        
        if variants_to_report:
            products_with_compare.append({
                "id": node["id"],
                "title": node["title"],
                "variants": variants_to_report
            })
            
    page_info = prod_data.get("pageInfo", {})
    has_next = page_info.get("hasNextPage", False)
    cursor = page_info.get("endCursor")
    print(f"Page {page} processed. Current total variants with compare price: {total_variants_with_compare}")
    page += 1

print(f"\nScan complete! Found {total_variants_with_compare} variants (across {len(products_with_compare)} products) with a non-null compareAtPrice.")
for p in products_with_compare[:10]:
    print(f"Product: {p['title']} ({p['id']})")
    for v in p["variants"]:
        print(f"  Variant: {v['id']} | Price: {v['price']} | CompareAt: {v['compareAtPrice']}")
if len(products_with_compare) > 10:
    print(f"... and {len(products_with_compare) - 10} more products")

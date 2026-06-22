import os
import sys
import requests

scripts_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(scripts_dir))
sys.path.insert(0, os.path.join(os.path.dirname(scripts_dir), "scripts"))

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

def inspect():
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
            variants(first: 5) {
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
    
    # Query all products with vendor "Orange Farm Clothing"
    query_str = "vendor:'Orange Farm Clothing'"
    variables = {"first": 50, "queryStr": query_str}
    
    resp = requests.post(BASE_URL, headers=HEADERS, json={"query": query, "variables": variables}, timeout=30)
    data = resp.json()
    
    products = data.get("data", {}).get("products", {}).get("edges", [])
    print(f"Found {len(products)} products under 'Orange Farm Clothing':")
    for idx, p in enumerate(products, 1):
        node = p["node"]
        variants = [v["node"] for v in node["variants"]["edges"]]
        print(f"[{idx}] Title: {node['title']} | Status: {node['status']}")
        for v in variants:
            print(f"   - Variant {v['id']} ({v.get('sku')}): ${v['price']}")

if __name__ == "__main__":
    inspect()

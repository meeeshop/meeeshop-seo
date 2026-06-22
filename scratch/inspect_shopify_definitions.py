import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.shopify_graphql import run_graphql

def main():
    query = """
    query {
      metafieldDefinitions(first: 250, ownerType: PRODUCT) {
        edges {
          node {
            key
            namespace
            name
            type {
              name
            }
          }
        }
      }
    }
    """
    res = run_graphql(query)
    edges = res.get("data", {}).get("metafieldDefinitions", {}).get("edges", [])
    print("Active standard 'shopify' namespace metafield definitions:")
    count = 0
    for edge in edges:
        node = edge["node"]
        if node["namespace"] == "shopify":
            print(f" - Key: {node['key']:<30} Name: {node['name']:<25} Type: {node['type']['name']}")
            count += 1
    print(f"\nTotal: {count} definitions in the 'shopify' namespace.")

if __name__ == "__main__":
    main()

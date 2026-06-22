import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.shopify_graphql import run_graphql

def main():
    query = """
    query {
      products(first: 50, query: "product_type:Handbags") {
        edges {
          node {
            id
            title
            handle
            descriptionHtml
          }
        }
      }
    }
    """
    res = run_graphql(query)
    edges = res.get("data", {}).get("products", {}).get("edges", [])
    
    count = 0
    for edge in edges:
        node = edge["node"]
        desc = node.get("descriptionHtml") or ""
        if "table" in desc.lower() or "size chart" in desc.lower():
            print(f"\n========================================\nProduct: {node['title']} (Handle: {node['handle']})")
            print("Description HTML:")
            print(desc)
            count += 1
            if count >= 3:
                break
                
    if count == 0:
        print("No handbag products with table or size charts found in the first 50 results.")

if __name__ == "__main__":
    main()

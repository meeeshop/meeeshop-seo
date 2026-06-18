import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.shopify_graphql import run_graphql

def main():
    query = """
    query GetTemplates($cursor: String) {
      standardMetafieldDefinitionTemplates(first: 250, after: $cursor) {
        edges {
          node {
            id
            name
            key
            namespace
            type {
              name
            }
            validations {
              name
              type
              value
            }
          }
        }
        pageInfo {
          hasNextPage
          endCursor
        }
      }
    }
    """
    
    target_keys = {"accessory-size", "bag-case-closure", "bag-case-features", "bag-case-storage-features"}
    found = {}
    has_next = True
    cursor = None
    
    while has_next and len(found) < len(target_keys):
        res = run_graphql(query, {"cursor": cursor})
        data = res.get("data", {}).get("standardMetafieldDefinitionTemplates", {})
        for edge in data.get("edges", []):
            node = edge["node"]
            if node["key"] in target_keys:
                found[node["key"]] = node
                
        page_info = data.get("pageInfo", {})
        has_next = page_info.get("hasNextPage", False)
        cursor = page_info.get("endCursor")
        
    print(f"Found {len(found)} matching templates:")
    for key, node in found.items():
        print(f"\nTemplate: {node['name']} (Key: {node['key']})")
        print(f"ID: {node['id']}")
        print(f"Type: {node['type']['name']}")
        print("Validations:")
        for val in node["validations"]:
            print(f" - Name: {val['name']}, Type: {val['type']}, Value: {val['value']}")

if __name__ == "__main__":
    main()

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.shopify_graphql import run_graphql

def main():
    keys = ["accessory-size", "bag-case-closure", "bag-case-features", "bag-case-storage-features"]
    query = """
    query GetTemplates($keys: [String!]) {
      standardMetafieldDefinitionTemplates(first: 50, ownerType: PRODUCT, keys: $keys) {
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
      }
    }
    """
    res = run_graphql(query, {"keys": keys})
    edges = res.get("data", {}).get("standardMetafieldDefinitionTemplates", {}).get("edges", [])
    print(f"Found {len(edges)} standard templates:")
    for edge in edges:
        node = edge["node"]
        print(f"\nTemplate: {node['name']} (Key: {node['key']})")
        print(f"ID: {node['id']}")
        print(f"Type: {node['type']['name']}")
        print("Validations:")
        for val in node["validations"]:
            print(f" - Name: {val['name']}, Type: {val['type']}, Value: {val['value']}")

if __name__ == "__main__":
    main()

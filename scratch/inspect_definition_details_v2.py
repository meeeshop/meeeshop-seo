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
            id
            key
            namespace
            name
            type {
              name
            }
            validations {
              name
              type
              value
            }
            standardTemplate {
              id
              name
              key
            }
          }
        }
      }
    }
    """
    res = run_graphql(query)
    edges = res.get("data", {}).get("metafieldDefinitions", {}).get("edges", [])
    for edge in edges:
        node = edge["node"]
        if node["key"] == "carry-options" and node["namespace"] == "shopify":
            print("Carry Options Definition Details:")
            print(f"ID: {node['id']}")
            print(f"Key: {node['key']}")
            print(f"Namespace: {node['namespace']}")
            print(f"Name: {node['name']}")
            print(f"Type: {node['type']['name']}")
            print("Validations:")
            for val in node["validations"]:
                print(f" - Name: {val['name']}, Type: {val['type']}, Value: {val['value']}")
            if node.get("standardTemplate"):
                print(f"Standard Template: {node['standardTemplate']['name']} ({node['standardTemplate']['key']})")
            break

if __name__ == "__main__":
    main()

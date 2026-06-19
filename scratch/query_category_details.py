import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.shopify_graphql import run_graphql

def main():
    cat_id = "gid://shopify/TaxonomyCategory/aa-5-4-5"
    print(f"Inspecting category GID: {cat_id}")
    query = """
    query GetCategory($id: ID!) {
      node(id: $id) {
        ... on TaxonomyCategory {
          id
          name
          fullName
          attributes(first: 50) {
            edges {
              node {
                __typename
                ... on TaxonomyChoiceListAttribute {
                  id
                  name
                  values(first: 50) {
                    edges {
                      node {
                        id
                        name
                      }
                    }
                  }
                }
              }
            }
          }
        }
      }
    }
    """
    res = run_graphql(query, {"id": cat_id})
    node = res.get("data", {}).get("node", {})
    if node:
        print(f"Category Name: {node.get('name')}")
        print(f"Full Name: {node.get('fullName')}")
        print("\nAttributes found:")
        for edge in node.get("attributes", {}).get("edges", []):
            attr = edge["node"]
            if attr.get("__typename") == "TaxonomyChoiceListAttribute":
                print(f"\n- Attribute: {attr['name']} (GID: {attr['id']})")
                print("  Values (first 10):")
                values = [val_edge["node"]["name"] for val_edge in attr.get("values", {}).get("edges", [])]
                for val in values[:10]:
                    print(f"    * {val}")
                if len(values) > 10:
                    print(f"    ... and {len(values) - 10} more values")
    else:
        print("No category details found.")

if __name__ == "__main__":
    main()

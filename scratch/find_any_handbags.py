import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.shopify_graphql import run_graphql

def main():
    # Search for products with query "handbag" or "bag"
    query = """
    query GetProducts($queryStr: String) {
      products(first: 50, query: $queryStr) {
        edges {
          node {
            id
            title
            handle
            productType
            category {
              id
              name
              fullName
            }
          }
        }
      }
    }
    """
    
    # Try different search terms
    for term in ["product_type:Handbags", "bag", "tote", "handbag"]:
        print(f"\nSearching with query: '{term}'")
        res = run_graphql(query, {"queryStr": term})
        edges = res.get("data", {}).get("products", {}).get("edges", [])
        print(f"Found {len(edges)} results.")
        for edge in edges[:10]:
            node = edge["node"]
            cat = node.get("category")
            cat_name = cat["fullName"] if cat else "None"
            print(f" - Title: {node['title'][:30]:<30} Type: {node['productType']:<15} Category: {cat_name}")
            
        # Let's inspect the Handbags category if found
        for edge in edges:
            node = edge["node"]
            cat = node.get("category")
            if cat and "handbag" in cat["fullName"].lower():
                inspect_category(cat["id"])
                return

def inspect_category(cat_id):
    print(f"\nInspecting category GID: {cat_id}")
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
                name
                id
                ... on TaxonomyChoiceListAttribute {
                  values(first: 10) {
                    edges {
                      node {
                        name
                        id
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
        print("Attributes:")
        for edge in node.get("attributes", {}).get("edges", []):
            attr = edge["node"]
            print(f" - Attribute: {attr['name']} (GID: {attr['id']})")
            print("   Values:")
            for val_edge in attr.get("values", {}).get("edges", []):
                val = val_edge["node"]
                print(f"     * {val['name']} ({val['id']})")
    else:
        print("No category details found.")

if __name__ == "__main__":
    main()

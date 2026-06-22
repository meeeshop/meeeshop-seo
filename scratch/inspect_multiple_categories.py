import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.shopify_graphql import run_graphql

def main():
    # Find products with category/type containing bag, tote, or handbag
    query = """
    query GetProducts {
      products(first: 100, query: "product_type:Handbags") {
        edges {
          node {
            category {
              id
              fullName
            }
          }
        }
      }
    }
    """
    res = run_graphql(query)
    edges = res.get("data", {}).get("products", {}).get("edges", [])
    
    unique_categories = {}
    for edge in edges:
        cat = edge["node"].get("category")
        if cat:
            unique_categories[cat["id"]] = cat["fullName"]
            
    print(f"Found {len(unique_categories)} unique categories for Handbags:")
    for cat_id, full_name in unique_categories.items():
        print(f" - {full_name} ({cat_id})")
        
    # Inspect each unique category
    for cat_id, full_name in unique_categories.items():
        print(f"\n========================================\nCategory: {full_name} ({cat_id})")
        cat_query = """
        query GetCategory($id: ID!) {
          node(id: $id) {
            ... on TaxonomyCategory {
              attributes(first: 50) {
                edges {
                  node {
                    __typename
                    ... on TaxonomyChoiceListAttribute {
                      name
                    }
                  }
                }
              }
            }
          }
        }
        """
        cat_res = run_graphql(cat_query, {"id": cat_id})
        node = cat_res.get("data", {}).get("node", {})
        if node:
            for edge in node.get("attributes", {}).get("edges", []):
                attr = edge["node"]
                if attr.get("__typename") == "TaxonomyChoiceListAttribute":
                    print(f" - Attribute: {attr['name']}")
        else:
            print("No details found.")

if __name__ == "__main__":
    main()

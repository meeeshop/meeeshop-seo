import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.shopify_graphql import run_graphql

def main():
    # Find products with category/type containing bag, tote, or handbag
    query = """
    query {
      products(first: 50) {
        edges {
          node {
            id
            title
            handle
            productType
            category {
              id
              name
            }
          }
        }
      }
    }
    """
    res = run_graphql(query)
    products = res.get("data", {}).get("products", {}).get("edges", [])
    
    print("Found products:")
    handbag_category_id = None
    for p in products:
        node = p["node"]
        title = node["title"]
        category = node.get("category")
        cat_name = category["name"] if category else "None"
        prod_type = node.get("productType")
        print(f" - Title: {title:<40} Type: {prod_type:<20} Category: {cat_name}")
        
        if category and ("handbag" in cat_name.lower() or "bag" in cat_name.lower() or "wallets" in cat_name.lower()):
            handbag_category_id = category["id"]
            
    if handbag_category_id:
        print(f"\nInspecting Taxonomy Category ID: {handbag_category_id}")
        cat_query = """
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
        cat_res = run_graphql(cat_query, {"id": handbag_category_id})
        node = cat_res.get("data", {}).get("node", {})
        if node:
            print(f"Full Name: {node.get('fullName')}")
            print("Attributes:")
            for edge in node.get("attributes", {}).get("edges", []):
                print(f" - {edge['node']['name']}")
        else:
            print("Could not retrieve category info.")
    else:
        print("\nNo handbag category products found in the first 50 products.")

if __name__ == "__main__":
    main()

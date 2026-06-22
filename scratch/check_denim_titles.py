import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
from shopify_graphql import fetch_products_graphql

def main():
    print("Fetching active products...")
    products = fetch_products_graphql(hours=0)
    print(f"Total active products: {len(products)}")
    
    denim_products = []
    for p in products:
        title = p["title"].lower()
        if "denim" in title:
            denim_products.append(p)
            
    print(f"Found {len(denim_products)} products with 'denim' in title.")
    for p in denim_products[:50]:
        print(f"Title: {p['title']} | Type: {p['product_type']} | Handle: {p['handle']}")

if __name__ == "__main__":
    main()

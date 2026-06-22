import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
from shopify_graphql import fetch_products_graphql

def main():
    products = fetch_products_graphql(hours=0)
    for p in products:
        title = p["title"].lower()
        if "jean" in title:
            print(f"Title: {p['title']} | Type: {p['product_type']}")

if __name__ == "__main__":
    main()

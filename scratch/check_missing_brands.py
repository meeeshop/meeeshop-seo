import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
from shopify_graphql import fetch_products_graphql

def main():
    print("Fetching active products...")
    products = fetch_products_graphql(hours=0)
    
    brands = ["bibi", "umgee", "zenana", "judy blue", "risen"]
    
    for brand in brands:
        matches = []
        for p in products:
            title = p["title"].lower()
            vendor = p["vendor"].lower()
            # We can't access tags directly unless they are in title or vendor,
            # but let's check if the title or vendor contains the brand name.
            if brand in title or brand in vendor:
                matches.append(p)
                
        print(f"Brand '{brand}': Found {len(matches)} products matching title/vendor.")
        for p in matches[:5]:
            print(f"  - Title: '{p['title']}' | Vendor: '{p['vendor']}'")

if __name__ == "__main__":
    main()

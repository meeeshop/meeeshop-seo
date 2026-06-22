import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
from shopify_graphql import fetch_products_graphql

def main():
    products = fetch_products_graphql(hours=0)
    
    shoes_keywords = ["shoe", "sandal", "boot", "heel", "sneaker", "footwear", "clog", "slippers", "flat", "wedge"]
    
    matched = []
    for p in products:
        title = p["title"].lower()
        ptype = p["product_type"].lower()
        
        is_shoe = any(kw in title for kw in shoes_keywords) or any(kw in ptype for kw in ["shoes", "footwear"])
        if is_shoe:
            matched.append(p)
            
    print(f"Found {len(matched)} shoe-related products:")
    for p in matched:
        print(f"Title: '{p['title']}' | Vendor: '{p['vendor']}' | Type: '{p['product_type']}'")

if __name__ == "__main__":
    main()

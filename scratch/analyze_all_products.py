import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
from shopify_graphql import fetch_products_graphql

def main():
    print("Fetching active products from Shopify...")
    products = fetch_products_graphql(hours=0)
    print(f"Total products fetched: {len(products)}")
    
    # 1. Count Vendors (case insensitive and exact)
    vendors = Counter()
    for p in products:
        v = p.get("vendor", "")
        if v:
            vendors[v] += 1
            
    print("\n--- Active Vendors in MeeeShop ---")
    for v, count in vendors.most_common():
        print(f"Vendor: '{v}' - count: {count}")
        
    # 2. Count Product Types
    types = Counter()
    for p in products:
        ptype = p.get("product_type", "")
        if ptype:
            types[ptype] += 1
            
    print("\n--- Active Product Types in MeeeShop ---")
    for t, count in types.most_common():
        print(f"Type: '{t}' - count: {count}")

    # 3. Analyze specific empty collections
    # Let's see if we have products matching:
    # Anniewear, Adora, acting pro, davi & dani, gilli, heimish, KanCan, La Miel, Ninexis, Yelete, White Birch, etc.
    print("\n--- Checking for products of empty brand collections ---")
    brands_to_check = [
        "adora", "annie wear", "anniewear", "acting pro", "davi & dani", "davi and dani",
        "gilli", "heimish", "kancan", "kan can", "la miel", "ninexis", "yelete", "white birch",
        "e luna", "insane gene", "recycled karma", "vibrant"
    ]
    
    for brand in brands_to_check:
        matches = []
        for p in products:
            title = p["title"].lower()
            vendor = p["vendor"].lower()
            if brand in title or brand in vendor:
                matches.append(p)
        if matches:
            print(f"Brand '{brand}': Found {len(matches)} matching products. Sample titles:")
            for p in matches[:3]:
                print(f"  - Title: '{p['title']}' | Vendor: '{p['vendor']}' | Type: '{p['product_type']}'")
        else:
            print(f"Brand '{brand}': 0 matching products in store.")

    # 4. Check category collections that are empty
    # Jackets & Blazers, Sleepwear, Shoes
    print("\n--- Checking for category products that are currently empty in collections ---")
    
    # Jackets/blazers
    jackets_blazers = []
    for p in products:
        title = p["title"].lower()
        ptype = p["product_type"].lower()
        if "jacket" in title or "blazer" in title or "jacket" in ptype or "coats & jackets" in ptype:
            jackets_blazers.append(p)
    print(f"Found {len(jackets_blazers)} potential Jackets/Blazers (empty or low count collections).")
    
    # Shoes
    shoes = []
    for p in products:
        title = p["title"].lower()
        ptype = p["product_type"].lower()
        if "shoe" in title or "sandal" in title or "boot" in title or "heel" in title or "sneaker" in title or "shoes" in ptype or "footwear" in ptype:
            shoes.append(p)
    print(f"Found {len(shoes)} potential Shoes (collection currently has 0).")
    
    # Sleepwear
    sleepwear = []
    for p in products:
        title = p["title"].lower()
        ptype = p["product_type"].lower()
        if "sleepwear" in ptype or "sleep" in title or "pajama" in title or "pajamas" in title or "sleepwear" in title or "nightwear" in title:
            sleepwear.append(p)
    print(f"Found {len(sleepwear)} potential Sleepwear products (collection currently has 0).")

if __name__ == "__main__":
    main()

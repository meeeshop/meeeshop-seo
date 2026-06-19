import os
import sys
import requests

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
from secrets_manager import inject_to_env, get_secret
inject_to_env()

STORE = get_secret("SHOPIFY_STORE")
TOKEN = get_secret("SHOPIFY_ACCESS_TOKEN")
API_VER = "2024-01"
BASE_URL = f"https://{STORE}/admin/api/{API_VER}"
HEADERS = {
    "X-Shopify-Access-Token": TOKEN,
    "Content-Type": "application/json"
}

def analyze_collection_sync(handle):
    # Get collection rules
    url = f"{BASE_URL}/smart_collections.json?handle={handle}"
    r = requests.get(url, headers=HEADERS)
    r.raise_for_status()
    cols = r.json().get("smart_collections", [])
    if not cols:
        print(f"Smart collection '{handle}' not found.")
        return
    
    col = cols[0]
    col_id = col["id"]
    rules = col.get("rules", [])
    disjunctive = col.get("disjunctive", False)
    
    # Get products currently in this collection (REST)
    products_url = f"{BASE_URL}/products.json?collection_id={col_id}&limit=250"
    p_resp = requests.get(products_url, headers=HEADERS)
    p_resp.raise_for_status()
    in_coll = p_resp.json().get("products", [])
    
    print(f"\nCollection: {col['title']} ({handle})")
    print(f"  ID: {col_id}")
    print(f"  Disjunctive: {disjunctive}")
    print(f"  Rules: {rules}")
    print(f"  Products currently in collection: {len(in_coll)}")
    if in_coll:
        print(f"  Sample product in collection: '{in_coll[0]['title']}' | Vendor: '{in_coll[0]['vendor']}'")
        
    # Let's count active products with the exact vendor in the store
    # We will search products by vendor
    # Wait, the vendor is often case sensitive in matching
    # Let's search using the rules to see what matches
    for rule in rules:
        if rule["column"] == "vendor":
            relation = rule["relation"]
            condition = rule["condition"]
            # Fetch products matching this vendor condition
            v_url = f"{BASE_URL}/products.json?vendor={condition}&limit=250"
            v_resp = requests.get(v_url, headers=HEADERS)
            v_resp.raise_for_status()
            matching_vendor_prods = v_resp.json().get("products", [])
            print(f"  Products matching vendor condition '{condition}': {len(matching_vendor_prods)}")
            if matching_vendor_prods:
                print(f"    Sample: '{matching_vendor_prods[0]['title']}' | Vendor: '{matching_vendor_prods[0]['vendor']}'")

def main():
    analyze_collection_sync("pol-womens-clothing-collection")
    analyze_collection_sync("bibi-womens-clothing")
    analyze_collection_sync("zenana-womens-clothing")
    analyze_collection_sync("yelete-womens-clothing")

if __name__ == "__main__":
    main()

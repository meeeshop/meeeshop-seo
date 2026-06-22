import os
import sys
import json
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

def get_all_product_types():
    url = f"{BASE_URL}/products.json?limit=250&status=active&fields=product_type"
    product_types = set()
    while url:
        r = requests.get(url, headers=HEADERS)
        r.raise_for_status()
        for p in r.json().get("products", []):
            ptype = p.get("product_type")
            if ptype:
                product_types.add(ptype.strip())
        nxt = [p.split(';')[0].strip().strip('<>') for p in r.headers.get('Link','').split(',') if 'rel="next"' in p]
        url = nxt[0] if nxt else None
    return product_types

def get_existing_collection_titles_and_handles():
    url = f"{BASE_URL}/smart_collections.json?limit=250&fields=title,handle"
    r = requests.get(url, headers=HEADERS)
    r.raise_for_status()
    smart = r.json().get("smart_collections", [])

    url2 = f"{BASE_URL}/custom_collections.json?limit=250&fields=title,handle"
    r2 = requests.get(url2, headers=HEADERS)
    r2.raise_for_status()
    custom = r2.json().get("custom_collections", [])

    return {c["title"].lower().strip(): c["handle"] for c in smart + custom}

def main():
    print("Fetching active product types from Shopify...")
    ptypes = get_all_product_types()
    print(f"Found product types: {ptypes}")

    print("Fetching existing collection titles...")
    existing = get_existing_collection_titles_and_handles()

    print("\n--- Verification of Product Type Collections ---")
    missing = []
    for ptype in ptypes:
        ptype_lower = ptype.lower().strip()
        # Check if the product type exists as a collection title (e.g. "Dresses" or "Jeans")
        found = False
        for title in existing:
            if ptype_lower in title or title in ptype_lower:
                found = True
                break
        if not found:
            missing.append(ptype)
            print(f"MISSING COLLECTION for product type: '{ptype}'")
        else:
            print(f"MATCHED: Product type '{ptype}' has a matching collection.")

    if not missing:
        print("\nAll product types in the store already have matching ZSV collections!")
    else:
        print(f"\nFound {len(missing)} product types without a direct collection.")

if __name__ == "__main__":
    main()

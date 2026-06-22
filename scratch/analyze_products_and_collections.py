import os
import sys
import json
import requests

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
from secrets_manager import inject_to_env, get_secret
inject_to_env()
from shopify_graphql import fetch_products_graphql, run_graphql

STORE = get_secret("SHOPIFY_STORE")
TOKEN = get_secret("SHOPIFY_ACCESS_TOKEN")
API_VER = "2024-01"
BASE_URL = f"https://{STORE}/admin/api/{API_VER}"
HEADERS = {
    "X-Shopify-Access-Token": TOKEN,
    "Content-Type": "application/json"
}

def get_existing_collections():
    url = f"{BASE_URL}/smart_collections.json?limit=250"
    r = requests.get(url, headers=HEADERS)
    r.raise_for_status()
    smart = r.json().get("smart_collections", [])

    url2 = f"{BASE_URL}/custom_collections.json?limit=250"
    r2 = requests.get(url2, headers=HEADERS)
    r2.raise_for_status()
    custom = r2.json().get("custom_collections", [])

    return {c["handle"]: c for c in smart + custom}

def main():
    print("Fetching all products from Shopify via GraphQL...")
    products = fetch_products_graphql(hours=0)
    print(f"Total products fetched: {len(products)}")

    # Analyze products
    unique_types = set()
    unique_vendors = set()
    all_tags = set()

    for p in products:
        if p.get("product_type"):
            unique_types.add(p["product_type"])
        if p.get("vendor"):
            unique_vendors.add(p["vendor"])
        # If tags are not parsed, let's check what's in products structure
        # Wait, fetch_products_graphql returns mapped products. Let's see if tags are there.

    print(f"\nUnique Product Types: {unique_types}")
    print(f"Unique Vendors: {unique_vendors}")

    existing = get_existing_collections()
    print(f"Total existing collections in store: {len(existing)}")

    # We will build a recommendation map for all collections
    # Let's inspect some samples
    for handle, c in list(existing.items())[:10]:
        print(f"Collection: {c['title']} ({handle}) - Rules: {c.get('rules')}")

if __name__ == "__main__":
    main()

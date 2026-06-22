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

def check_collection(handle):
    url = f"{BASE_URL}/smart_collections.json?handle={handle}"
    r = requests.get(url, headers=HEADERS)
    r.raise_for_status()
    cols = r.json().get("smart_collections", [])
    if not cols:
        print(f"Collection '{handle}' not found.")
        return
    
    col = cols[0]
    count_url = f"{BASE_URL}/products/count.json?collection_id={col['id']}"
    resp = requests.get(count_url, headers=HEADERS)
    count = resp.json().get("count", 0)
    print(f"Collection: {col['title']} ({handle})")
    print(f"  Product Count: {count}")
    print(f"  Rules: {col['rules']}")
    print("-" * 50)

def main():
    handles = [
        "pol-womens-clothing-collection",
        "womens-blazers-vests-jackets",
        "womens-shoes",
        "womens-tops"
    ]
    for h in handles:
        check_collection(h)

if __name__ == "__main__":
    main()

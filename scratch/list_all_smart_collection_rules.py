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

def fetch_all_smart_collections():
    url = f"{BASE_URL}/smart_collections.json?limit=250"
    smart_collections = []
    while url:
        r = requests.get(url, headers=HEADERS)
        r.raise_for_status()
        smart_collections.extend(r.json().get("smart_collections", []))
        nxt = [p.split(';')[0].strip().strip('<>') for p in r.headers.get('Link','').split(',') if 'rel="next"' in p]
        url = nxt[0] if nxt else None
    return smart_collections

def main():
    print("Fetching all smart collections from Shopify...")
    collections = fetch_all_smart_collections()
    print(f"Found {len(collections)} smart collections.")
    
    # Sort by title
    collections.sort(key=lambda x: x["title"])
    
    with open("scratch/all_smart_collections_report.txt", "w", encoding="utf-8") as f:
        f.write(f"Total Smart Collections: {len(collections)}\n")
        f.write("="*80 + "\n")
        
        for c in collections:
            count_url = f"{BASE_URL}/products/count.json?collection_id={c['id']}"
            resp = requests.get(count_url, headers=HEADERS)
            count = resp.json().get("count", 0)
            
            f.write(f"Title: {c['title']}\n")
            f.write(f"Handle: {c['handle']}\n")
            f.write(f"Product Count: {count}\n")
            f.write(f"Disjunctive: {c.get('disjunctive')}\n")
            f.write(f"Rules: {c.get('rules')}\n")
            f.write("-" * 80 + "\n")
            
    print("Saved report to scratch/all_smart_collections_report.txt")

if __name__ == "__main__":
    main()

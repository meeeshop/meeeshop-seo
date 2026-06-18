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
    print("Fetching smart collections...")
    collections = fetch_all_smart_collections()
    
    print("\n--- Collections with Potential Rule Issues ---")
    for c in collections:
        rules = c.get("rules", [])
        has_issue = False
        reasons = []
        
        # Check for trailing or embedded double quotes in condition
        for r in rules:
            cond = r.get("condition", "")
            if '"' in cond:
                has_issue = True
                reasons.append(f"Double quote in condition: '{cond}'")
            if cond.strip() == "":
                has_issue = True
                reasons.append("Empty condition field")
                
        # Check brand collections that might be matching People of Leisure
        if "pol" in c["title"].lower() or "pol" in c["handle"].lower():
            has_issue = True
            reasons.append("POL collection should match 'People of Leisure' vendor/tag")

        if has_issue:
            print(f"Collection: {c['title']} ({c['handle']})")
            print(f"  Rules: {rules}")
            print(f"  Issues found: {reasons}")
            print("-" * 60)

if __name__ == "__main__":
    main()

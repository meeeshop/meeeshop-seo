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

with open("scratch/matched_collections.json", "r", encoding="utf-8") as f:
    matched = json.load(f)

sitemap_handles = {item[1]: item[0] for item in matched}

def get_smart_collections():
    url = f"{BASE_URL}/smart_collections.json?limit=250"
    r = requests.get(url, headers=HEADERS)
    r.raise_for_status()
    return {c["handle"]: c for c in r.json().get("smart_collections", [])}

def get_custom_collections():
    url = f"{BASE_URL}/custom_collections.json?limit=250"
    r = requests.get(url, headers=HEADERS)
    r.raise_for_status()
    return {c["handle"]: c for c in r.json().get("custom_collections", [])}

print("Fetching collections...")
smart = get_smart_collections()
custom = get_custom_collections()

print("Fetching collections...")
smart = get_smart_collections()
custom = get_custom_collections()

print("\n--- ZSV Collections Status ---")
for handle, title in sitemap_handles.items():
    if handle in smart:
        c = smart[handle]
        # Fetch product count using REST API
        count_url = f"{BASE_URL}/products/count.json?collection_id={c['id']}"
        resp = requests.get(count_url, headers=HEADERS)
        count = resp.json().get("count", 0)
        print(f"SMART: {title} ({handle}) - {count} products - Rules: {c.get('rules')}")
    elif handle in custom:
        c = custom[handle]
        count_url = f"{BASE_URL}/products/count.json?collection_id={c['id']}"
        resp = requests.get(count_url, headers=HEADERS)
        count = resp.json().get("count", 0)
        print(f"CUSTOM: {title} ({handle}) - {count} products")
    else:
        print(f"MISSING: {title} ({handle})")

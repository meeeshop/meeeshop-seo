import os
import sys
import json
import requests

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
from secrets_manager import inject_to_env, get_secret
inject_to_env()

STORE = get_secret("SHOPIFY_STORE")
TOKEN = get_secret("SHOPIFY_ACCESS_TOKEN")
THEME_ID = get_secret("LIVE_THEME_ID")

BASE_URL = f"https://{STORE}/admin/api/2024-01"
HEADERS = {
    "X-Shopify-Access-Token": TOKEN,
    "Content-Type": "application/json"
}

# Read updated snippet
with open("scratch/popular-searches.liquid", "r", encoding="utf-8") as f:
    snippet_content = f.read()

payload = {
    "asset": {
        "key": "snippets/popular-searches.liquid",
        "value": snippet_content
    }
}

print(f"Uploading snippets/popular-searches.liquid to theme {THEME_ID}...")
url = f"{BASE_URL}/themes/{THEME_ID}/assets.json"
resp = requests.put(url, headers=HEADERS, json=payload)

if resp.status_code == 200:
    print("[SUCCESS] Successfully updated snippets/popular-searches.liquid on live theme!")
    print(json.dumps(resp.json()["asset"], indent=2))
else:
    print(f"[ERROR] Failed to upload asset: {resp.status_code}")
    print(resp.text)

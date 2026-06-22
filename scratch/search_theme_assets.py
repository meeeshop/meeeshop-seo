import os
import sys
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

print(f"Fetching assets for theme {THEME_ID}...")
url = f"{BASE_URL}/themes/{THEME_ID}/assets.json"
resp = requests.get(url, headers=HEADERS)
if resp.status_code != 200:
    print(f"Error listing assets: {resp.status_code}")
    print(resp.text)
    sys.exit(1)

assets = resp.json()["assets"]
print(f"Found {len(assets)} assets. Searching for matching keys/content...")

for asset in assets:
    key = asset["key"]
    if not key.endswith(".liquid") and not key.endswith(".json") and not key.endswith(".js"):
        continue
    
    # Fetch content
    asset_url = f"{BASE_URL}/themes/{THEME_ID}/assets.json?asset[key]={key}"
    asset_resp = requests.get(asset_url, headers=HEADERS)
    if asset_resp.status_code == 200:
        val = asset_resp.json()["asset"].get("value", "")
        # search case-insensitive for popular searches
        if "popular" in val.lower() or "searches" in val.lower() or "sitemap" in val.lower():
            print(f"Match in {key}!")
            # Print snippet
            for line in val.splitlines():
                if "popular" in line.lower() or "searches" in line.lower():
                    print(f"  {line.strip()[:120]}")
    else:
        print(f"Failed to fetch {key}")

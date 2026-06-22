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

url = f"{BASE_URL}/themes/{THEME_ID}/assets.json?asset[key]=layout/theme.liquid"
resp = requests.get(url, headers=HEADERS)
if resp.status_code == 200:
    with open("scratch/theme.liquid", "w", encoding="utf-8") as f:
        f.write(resp.json()["asset"]["value"])
    print("Saved layout/theme.liquid to scratch/theme.liquid")
else:
    print(f"Error fetching layout/theme.liquid: {resp.status_code}")
    print(resp.text)

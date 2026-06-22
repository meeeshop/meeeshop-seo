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

def get_asset(key):
    url = f"{BASE_URL}/themes/{THEME_ID}/assets.json?asset[key]={key}"
    resp = requests.get(url, headers=HEADERS)
    if resp.status_code == 200:
        return resp.json()["asset"]["value"]
    else:
        print(f"Error fetching {key}: {resp.status_code}")
        print(resp.text)
        return None

popular_searches = get_asset("snippets/popular-searches.liquid")
if popular_searches:
    with open("scratch/popular-searches.liquid", "w", encoding="utf-8") as f:
        f.write(popular_searches)
    print("Saved snippets/popular-searches.liquid to scratch/popular-searches.liquid")

footer = get_asset("sections/footer.liquid")
if footer:
    with open("scratch/footer.liquid", "w", encoding="utf-8") as f:
        f.write(footer)
    print("Saved sections/footer.liquid to scratch/footer.liquid")

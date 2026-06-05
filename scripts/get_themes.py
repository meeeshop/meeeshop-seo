import os
import sys
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from secrets_manager import inject_to_env, get_secret
inject_to_env()

STORE = get_secret("SHOPIFY_STORE")
TOKEN = get_secret("SHOPIFY_ACCESS_TOKEN")

url = f"https://{STORE}/admin/api/2024-01/themes.json"
headers = {"X-Shopify-Access-Token": TOKEN}

resp = requests.get(url, headers=headers)
if resp.status_code == 200:
    for theme in resp.json()["themes"]:
        print(f"ID: {theme['id']:>15} | Role: {theme['role']:>10} | Name: {theme['name']}")
else:
    print(f"Error: {resp.status_code}")
    print(resp.text)

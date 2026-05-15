import os
import requests
from dotenv import load_dotenv

load_dotenv()
STORE = os.getenv("SHOPIFY_STORE")
TOKEN = os.getenv("SHOPIFY_ACCESS_TOKEN")

url = f"https://{STORE}/admin/api/2024-01/themes.json"
headers = {"X-Shopify-Access-Token": TOKEN}

resp = requests.get(url, headers=headers)
if resp.status_code == 200:
    for theme in resp.json()["themes"]:
        print(f"ID: {theme['id']:>15} | Role: {theme['role']:>10} | Name: {theme['name']}")
else:
    print(f"Error: {resp.status_code}")
    print(resp.text)

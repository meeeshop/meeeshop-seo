import os
import sys
import requests
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from secrets_manager import inject_to_env, get_secret
inject_to_env()

STORE = get_secret("SHOPIFY_STORE")
TOKEN = get_secret("SHOPIFY_ACCESS_TOKEN")
THEME_ID = get_secret("LIVE_THEME_ID")
ASSET_KEY = "layout/theme.liquid"

BASE_URL = f"https://{STORE}/admin/api/2024-01"
HEADERS = {
    "X-Shopify-Access-Token": TOKEN,
    "Content-Type": "application/json"
}

print("=" * 70)
print("SCHEMA THEME CODE VERIFICATION")
print("=" * 70)
print(f"Store: {STORE}")
print(f"Theme ID: {THEME_ID}")
print(f"Asset: {ASSET_KEY}\n")

# Fetch theme
url = f"{BASE_URL}/themes/{THEME_ID}/assets.json?asset[key]={ASSET_KEY}"
resp = requests.get(url, headers=HEADERS)

if resp.status_code != 200:
    print(f"[ERROR] Failed to fetch theme: {resp.status_code}")
    exit(1)

content = resp.json()["asset"]["value"]
print(f"[+] Theme file retrieved: {len(content)} bytes\n")

# Verify each component
checks = [
    ("JSON-LD Schema Rendering", "Schema rendering code header"),
    ("product.metafields.json_ld_schema", "Product schema rendering"),
    ("collection.metafields.json_ld_schema", "Collection schema rendering"),
    ("page.metafields.json_ld_schema", "Page schema rendering"),
    ("article.metafields.json_ld_schema", "Article schema rendering"),
    ('"@type": "Organization"', "Global Organization schema"),
    ('"name": "MeeeShop"', "Store name in Organization"),
    ('"email": "support@meeeshop.com"', "Contact email"),
]

print("COMPONENT CHECKS:")
print("-" * 70)
all_ok = True
for pattern, desc in checks:
    if pattern in content:
        print(f"[OK] {desc}")
    else:
        print(f"[FAIL] {desc}")
        all_ok = False

print("\n" + "=" * 70)
if all_ok:
    print("RESULT: ALL CHECKS PASSED - SCHEMA CODE FULLY DEPLOYED")
    print("=" * 70)
    print("\nTheme is now rendering:")
    print("  - Product schemas from metafields")
    print("  - Collection schemas from metafields")
    print("  - Page schemas from metafields")
    print("  - Article schemas from metafields")
    print("  - Global Organization schema")
    print("\nNext: Trigger first schema validation run in GitHub Actions")
else:
    print("RESULT: SOME CHECKS FAILED")
    print("=" * 70)

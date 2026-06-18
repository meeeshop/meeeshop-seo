import os
import sys
import xml.etree.ElementTree as ET
import requests

# Set up paths to import secrets_manager and shopify_graphql
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
from secrets_manager import inject_to_env
inject_to_env()
from shopify_graphql import fetch_collections_graphql

# 1. Parse sitemap collections
sitemap_url = "https://us.meeeshop.com/sitemap_collections_1.xml?from=279139745963&to=312370397355"
headers = {"User-Agent": "Mozilla/5.0"}
resp = requests.get(sitemap_url, headers=headers)
if resp.status_code != 200:
    print(f"Failed to fetch sitemap: {resp.status_code}")
    sys.exit(1)

root = ET.fromstring(resp.content)
namespaces = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
sitemap_handles = set()
for loc in root.findall('.//ns:loc', namespaces):
    url = loc.text
    handle = url.split("/collections/")[-1]
    sitemap_handles.add(handle)

print(f"Loaded {len(sitemap_handles)} handles from sitemap.")

# 2. Fetch all collections from Shopify
print("Fetching all collections from Shopify...")
all_collections = fetch_collections_graphql()
print(f"Fetched {len(all_collections)} collections from Shopify.")

# 3. Match sitemap handles to titles
matched = []
unmatched = []

for handle in sitemap_handles:
    # Find in fetched collections
    found = False
    for col in all_collections:
        if col["handle"] == handle:
            matched.append((col["title"], handle))
            found = True
            break
    if not found:
        # Try to retrieve it manually via REST / fallback
        unmatched.append(handle)

print(f"Successfully matched: {len(matched)}")
if unmatched:
    print(f"Unmatched handles: {unmatched}")

# Save the matched list
import json
with open("scratch/matched_collections.json", "w", encoding="utf-8") as f:
    json.dump(matched, f, indent=2, ensure_ascii=False)

print("Saved matches to scratch/matched_collections.json")

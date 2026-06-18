import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
from secrets_manager import inject_to_env
inject_to_env()
from shopify_graphql import fetch_collections_graphql

# Load matched sitemap collections
with open("scratch/matched_collections.json", "r", encoding="utf-8") as f:
    matched = json.load(f)
sitemap_handles = {item[1] for item in matched}

print("Fetching collections with metafields from Shopify...")
all_collections = fetch_collections_graphql()

sitemap_cols = [c for c in all_collections if c["handle"] in sitemap_handles]
print(f"Found {len(sitemap_cols)} matching collections in Shopify.")

# Print info on their SEO metafields
has_seo_title = 0
has_seo_desc = 0

for col in sitemap_cols:
    title_tag = None
    desc_tag = None
    for m in col["metafields"]:
        if m["namespace"] == "global" and m["key"] == "title_tag":
            title_tag = m["value"]
            has_seo_title += 1
        elif m["namespace"] == "global" and m["key"] == "description_tag":
            desc_tag = m["value"]
            has_seo_desc += 1
            
    print(f"Collection: {col['title']} ({col['handle']})")
    print(f"  SEO Title: {title_tag}")
    print(f"  SEO Desc:  {desc_tag}")
    print("-" * 40)

print(f"\nSummary:")
print(f"Total collections: {len(sitemap_cols)}")
print(f"Collections with SEO Title: {has_seo_title}")
print(f"Collections with SEO Desc:  {has_seo_desc}")

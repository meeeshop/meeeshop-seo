#!/usr/bin/env python3
import sys
import requests
import json
import re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from secrets_manager import inject_to_env, get_secret

inject_to_env()
SHOP = get_secret("SHOPIFY_STORE")
TOKEN = get_secret("SHOPIFY_ACCESS_TOKEN")
BASE = f"https://{SHOP}/admin/api/2024-10"
HEADERS = {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}

r = requests.get(f"{BASE}/blogs.json", headers=HEADERS)
blogs = r.json().get("blogs", [])

for b in blogs:
    r2 = requests.get(f"{BASE}/blogs/{b['id']}/articles.json", headers=HEADERS, params={"limit": 10})
    arts = r2.json().get("articles", [])
    print(f"\n=================== Blog: {b['title']} (ID: {b['id']}) ===================")
    for a in arts[:8]:
        print(f"ID: {a['id']} | Title: '{a['title']}' | Published: {a.get('published_at')}")
        feat_img = a.get("image", {}).get("src", "NO_IMAGE")
        print(f"  Featured Image: {feat_img}")
        body = a.get("body_html", "")
        links = re.findall(r'/products/([a-zA-Z0-9_-]+)', body)
        imgs = re.findall(r'src=["\']([^"\']+)["\']', body)
        print(f"  Product Handles in Body: {list(set(links))}")
        print(f"  Images in Body ({len(imgs)} total): {imgs[:3]}")
        print("-" * 60)

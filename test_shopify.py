#!/usr/bin/env python3
"""
shopify_test.py
Simple Shopify API authentication + product fetch test

Usage:
    python shopify_test.py

Optional .env file:
    SHOPIFY_STORE=us-meeeshop.myshopify.com
    SHOPIFY_ACCESS_TOKEN=shpat_xxxxx
"""

import os
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "-q"])
    import requests


# ── LOAD ENV ────────────────────────────────────────────────────────
def load_env():
    env = Path(".env")

    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))


load_env()


# ── CONFIG ──────────────────────────────────────────────────────────
SHOP = os.getenv("SHOPIFY_STORE", "us-meeeshop.myshopify.com")
TOKEN = os.getenv("SHOPIFY_ACCESS_TOKEN", "")
API_VERSION = "2024-10"

BASE = f"https://{SHOP}/admin/api/{API_VERSION}"

HEADERS = {
    "X-Shopify-Access-Token": TOKEN,
    "Content-Type": "application/json",
    "User-Agent": "MeeeShop-Test/1.0"
}


# ── VALIDATION ──────────────────────────────────────────────────────
if not TOKEN:
    sys.exit("❌ ERROR: SHOPIFY_ACCESS_TOKEN not set")


print("\n==============================")
print(" Shopify API Test")
print("==============================")
print("Store :", SHOP)
print("API   :", API_VERSION)
print()


# ── TEST 1: SHOP ACCESS ────────────────────────────────────────────
shop_url = f"{BASE}/shop.json"

try:
    print("🔍 Testing authentication...")

    r = requests.get(
        shop_url,
        headers=HEADERS,
        timeout=30
    )

    print("Status:", r.status_code)

    if r.status_code != 200:
        print("\n❌ AUTH FAILED")
        print(r.text[:500])
        sys.exit(1)

    shop = r.json().get("shop", {})

    print("\n✅ AUTH SUCCESS")
    print("Shop Name :", shop.get("name"))
    print("Domain    :", shop.get("domain"))
    print("Email     :", shop.get("email"))

except requests.exceptions.ConnectionError as e:
    print("\n❌ CONNECTION ERROR")
    print(e)
    sys.exit(1)

except Exception as e:
    print("\n❌ UNKNOWN ERROR")
    print(e)
    sys.exit(1)


# ── TEST 2: FETCH PRODUCTS ─────────────────────────────────────────
products_url = f"{BASE}/products.json"

params = {
    "limit": 5,
    "fields": "id,title,handle,vendor,product_type,status"
}

try:
    print("\n🔍 Fetching products...")

    r = requests.get(
        products_url,
        headers=HEADERS,
        params=params,
        timeout=30
    )

    print("Status:", r.status_code)

    if r.status_code != 200:
        print("\n❌ PRODUCT FETCH FAILED")
        print(r.text[:500])
        sys.exit(1)

    products = r.json().get("products", [])

    print(f"\n✅ SUCCESS: fetched {len(products)} products\n")

    for i, p in enumerate(products, start=1):
        print(f"{i}. {p.get('title')}")
        print(f"   ID      : {p.get('id')}")
        print(f"   Handle  : {p.get('handle')}")
        print(f"   Vendor  : {p.get('vendor')}")
        print(f"   Type    : {p.get('product_type')}")
        print(f"   Status  : {p.get('status')}")
        print()

except Exception as e:
    print("\n❌ PRODUCT FETCH ERROR")
    print(e)
    sys.exit(1)


print("🎉 Shopify API test completed successfully.")
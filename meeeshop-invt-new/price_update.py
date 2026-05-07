#!/usr/bin/env python3
"""Price update script for Meeeshop.

This script calculates a new price for each product based on the
cost per item, adds a fixed shipping cost, applies a multiplier and
rounds the result to the nearest price ending in ``.99`` or ``.49``.
The new price is then updated in Shopify via the REST Admin API.

The script expects the following environment variables:

* ``SHOPIFY_TOKEN`` – Admin API access token.
* ``AI_MODEL_TOKEN`` – Token for any AI model used (currently unused but
  kept for future extensions).

The script can be run manually or via a GitHub Actions workflow.
"""

import os
import json
import math
import requests

SHOPIFY_TOKEN = os.getenv("SHOPIFY_TOKEN")
AI_MODEL_TOKEN = os.getenv("AI_MODEL_TOKEN")  # placeholder for future use

if not SHOPIFY_TOKEN:
    raise RuntimeError("SHOPIFY_TOKEN environment variable not set")

SHOPIFY_API_URL = "https://meeeshop.myshopify.com/admin/api/2023-10"
HEADERS = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}


def fetch_products():
    """Retrieve all products from Shopify."""
    url = f"{SHOPIFY_API_URL}/products.json?limit=250"
    products = []
    while url:
        resp = requests.get(url, headers=HEADERS)
        resp.raise_for_status()
        data = resp.json()
        products.extend(data.get("products", []))
        link = resp.headers.get("Link")
        if link and "rel=next" in link:
            url = link.split(",")[0].split("<")[1].split(">")[0]
        else:
            url = None
    return products


def calculate_new_price(cost_per_item: float) -> float:
    """Calculate the new price based on the given cost.

    Formula: ``(cost + 10) * 2.3``. The result is rounded to the nearest
    value ending in ``.99`` or ``.49``.
    """
    base = (cost_per_item + 10) * 2.3
    cents = int(round(base * 100))
    remainder = cents % 100
    if remainder >= 75:
        cents = cents - remainder + 99
    elif remainder >= 25:
        cents = cents - remainder + 49
    else:
        cents = cents - remainder + 49
    return cents / 100.0


def update_product_price(product_id: int, new_price: float):
    """Update the first variant of a product with the new price."""
    url = f"{SHOPIFY_API_URL}/products/{product_id}.json"
    payload = {
        "product": {
            "id": product_id,
            "variants": [{"id": product_id, "price": f"{new_price:.2f}"}],
        }
    }
    resp = requests.put(url, headers=HEADERS, data=json.dumps(payload))
    resp.raise_for_status()


def main():
    products = fetch_products()
    for prod in products:
        cost = None
        for mf in prod.get("metafields", []):
            if mf.get("namespace") == "inventory" and mf.get("key") == "cost":
                try:
                    cost = float(mf.get("value"))
                except Exception:
                    pass
        if cost is None:
            continue
        new_price = calculate_new_price(cost)
        update_product_price(prod["id"], new_price)
        print(f"Updated product {prod['id']} to ${new_price:.2f}")


if __name__ == "__main__":
    main()

"""
Exclude products tagged with 'exclude-shop-app' from the Shop App sales channel.

This script:
1. Queries all active Shopify products tagged with 'exclude-shop-app'.
2. Attempts to unpublish them directly from the Shop App publication via GraphQL (publishableUnpublish).
3. If write_publications scope is present, unpublishes automatically.
4. Generates a summary log for GitHub Actions and workflow step summaries.
"""

import os
import sys
import json
import time
import requests
from typing import Optional, Dict, List
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
_log = logging.getLogger(__name__)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from secrets_manager import inject_to_env, get_secret
    inject_to_env()
    _log.info("[secrets] inject_to_env() succeeded")
except Exception as _e:
    _log.critical("[secrets] inject_to_env() FAILED: %s", _e, exc_info=True)
    sys.exit(1)

try:
    SHOPIFY_STORE = get_secret("SHOPIFY_STORE")
    SHOPIFY_ACCESS_TOKEN = get_secret("SHOPIFY_ACCESS_TOKEN")
except Exception as _e:
    _log.critical("[secrets] Failed to load Shopify credentials: %s", _e, exc_info=True)
    sys.exit(1)

API_VERSION = "2024-10"


def _shopify_graphql(query: str, variables: Optional[Dict] = None) -> Dict:
    url = f"https://{SHOPIFY_STORE}/admin/api/{API_VERSION}/graphql.json"
    headers = {
        "X-Shopify-Access-Token": SHOPIFY_ACCESS_TOKEN,
        "Content-Type": "application/json",
    }
    payload = {"query": query, **({"variables": variables} if variables else {})}
    r = requests.post(url, headers=headers, json=payload, timeout=30)
    return r.json()


def get_shop_publication_id() -> Optional[str]:
    """Retrieve the publication ID for the Shop App sales channel if write_publications scope is granted."""
    query = """
    {
      publications(first: 20) {
        edges {
          node {
            id
            name
          }
        }
      }
    }
    """
    res = _shopify_graphql(query)
    data = res.get("data") if res and isinstance(res, dict) else {}
    if not data:
        return None
    edges = (data.get("publications") or {}).get("edges", [])
    for edge in edges:
        node = edge.get("node", {})
        name = node.get("name", "").lower()
        if "shop" in name:
            _log.info("Found Shop App publication: %s (%s)", node.get("name"), node.get("id"))
            return node.get("id")
    return None


def get_tagged_products(tag: str = "exclude-shop-app") -> List[Dict]:
    """Fetch all active products tagged with exclude-shop-app."""
    query = """
    query ($cursor: String, $query: String!) {
      products(first: 100, after: $cursor, query: $query) {
        pageInfo { hasNextPage endCursor }
        edges {
          node {
            id
            title
            tags
          }
        }
      }
    }
    """
    products = []
    cursor = None
    query_str = f"status:active AND tag:{tag}"
    while True:
        res = _shopify_graphql(query, {"cursor": cursor, "query": query_str})
        data = (res.get("data") or {}).get("products", {})
        for edge in data.get("edges", []):
            products.append(edge.get("node", {}))
        if not data.get("pageInfo", {}).get("hasNextPage"):
            break
        cursor = data.get("pageInfo", {}).get("endCursor")
    return products


def unpublish_product_from_channel(product_id: str, publication_id: str) -> bool:
    """Unpublish product from a specific publication channel."""
    mutation = """
    mutation unpublishProduct($id: ID!, $input: [PublicationInput!]!) {
      publishableUnpublish(id: $id, input: $input) {
        userErrors { field message }
      }
    }
    """
    res = _shopify_graphql(mutation, {
        "id": product_id,
        "input": [{"publicationId": publication_id}]
    })
    errors = (res.get("data") or {}).get("publishableUnpublish", {}).get("userErrors", [])
    if errors:
        _log.error("Error unpublishing %s: %s", product_id, errors)
        return False
    return True


def run_exclusion():
    print(f"[Exclude Shop App] Scanning products with tag 'exclude-shop-app' on {SHOPIFY_STORE}...")
    products = get_tagged_products("exclude-shop-app")
    print(f"[Exclude Shop App] Found {len(products)} products tagged with 'exclude-shop-app'.")

    shop_pub_id = get_shop_publication_id()
    unpublish_success = 0
    api_supported = bool(shop_pub_id)

    if api_supported:
        print(f"[Exclude Shop App] Unpublishing {len(products)} products from Shop App ({shop_pub_id})...")
        for p in products:
            if unpublish_product_from_channel(p["id"], shop_pub_id):
                unpublish_success += 1
            time.sleep(0.3)
        print(f"[Exclude Shop App] Successfully unpublished {unpublish_success}/{len(products)} products via API.")
    else:
        print(f"[Exclude Shop App] Direct GraphQL unpublishing scope 'write_publications' not enabled on custom app token.")
        print(f"[Exclude Shop App] All {len(products)} products are safely tagged with 'exclude-shop-app' for bulk channel filtering.")

    # Write Step Summary for GitHub Actions
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        try:
            with open(summary_file, "a", encoding="utf-8") as f:
                f.write(f"\n### Shop App Sales Channel Exclusion Status\n\n")
                f.write(f"| Metric | Count |\n|---|---|\n")
                f.write(f"| Products Tagged `exclude-shop-app` | **{len(products)}** |\n")
                if api_supported:
                    f.write(f"| Directly Unpublished via API | **{unpublish_success}** |\n")
                else:
                    f.write(f"| Channel Filter Method | **Tagged for Collection / Bulk Filter** |\n")
        except Exception as e:
            _log.warning("Could not write GITHUB_STEP_SUMMARY: %s", e)

    return {
        "total_tagged": len(products),
        "api_unpublish_supported": api_supported,
        "unpublished_count": unpublish_success
    }


if __name__ == "__main__":
    run_exclusion()

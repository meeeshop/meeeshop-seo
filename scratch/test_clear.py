import os
import sys
import json
import requests

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
from secrets_manager import inject_to_env, get_secret
inject_to_env()

store = get_secret("SHOPIFY_STORE")
token = get_secret("SHOPIFY_ACCESS_TOKEN")

# We'll use one of the products found in the scan:
# Product: Riley Technical Top (gid://shopify/Product/8744047083691)
# Variant: gid://shopify/ProductVariant/46492121039019
# Current Price: 110.00, CompareAt: 110.00

product_id = "gid://shopify/Product/8744047083691"
variant_id = "gid://shopify/ProductVariant/46492121039019"

query = """
mutation productVariantsBulkUpdate($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
  productVariantsBulkUpdate(productId: $productId, variants: $variants) {
    product {
      id
    }
    productVariants {
      id
      price
      compareAtPrice
    }
    userErrors {
      field
      message
    }
  }
}
"""

variables = {
    "productId": product_id,
    "variants": [
        {
            "id": variant_id,
            "compareAtPrice": None # testing null/None first
        }
    ]
}

url = f"https://{store}/admin/api/2025-01/graphql.json"
headers = {
    "X-Shopify-Access-Token": token,
    "Content-Type": "application/json"
}

resp = requests.post(url, headers=headers, json={"query": query, "variables": variables})
resp.raise_for_status()
data = resp.json()

print(json.dumps(data, indent=2))

"""
Dynamic pricing engine for MeeeShop inventory.

Rules:
  - Multiplier: 2.3-2.5x cost per item
  - Shipping: $7-10 USD added
  - Target profit: $20+ per product after all expenses
  - Price ending: .99 psychology (e.g., 70.99 -> 74.99, 76.99 -> 79.99)
  - Skip: Products already at target price (no unnecessary API calls)
"""

import os
import sys
import json
import requests
from pathlib import Path
from typing import Optional, Dict, List
from datetime import datetime

import ai_client


def _load_env():
    """Load .env file from local or parent directory."""
    for candidate in [Path(__file__).with_name(".env"), Path(".env")]:
        if candidate.exists():
            for line in candidate.read_text(encoding="utf-8").splitlines():
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"'))


_load_env()

SHOPIFY_STORE = os.getenv("SHOPIFY_STORE", "us-meeeshop.myshopify.com")
SHOPIFY_ACCESS_TOKEN = os.getenv("SHOPIFY_ACCESS_TOKEN", "")
API_VERSION = "2025-01"

# Pricing configuration
COST_MULTIPLIER_MIN = 2.3
COST_MULTIPLIER_MAX = 2.5
SHIPPING_COST_MIN = 7
SHIPPING_COST_MAX = 10
TARGET_PROFIT = 20


def _shopify_request(method: str, endpoint: str, data: Optional[Dict] = None, params: Optional[Dict] = None) -> Dict:
    """Make authenticated Shopify API request."""
    if not SHOPIFY_ACCESS_TOKEN:
        raise RuntimeError("SHOPIFY_ACCESS_TOKEN not set in environment")

    url = f"https://{SHOPIFY_STORE}/admin/api/{API_VERSION}/{endpoint}.json"
    headers = {
        "X-Shopify-Access-Token": SHOPIFY_ACCESS_TOKEN,
        "Content-Type": "application/json",
    }

    try:
        if method == "GET":
            r = requests.get(url, headers=headers, params=params, timeout=30)
        elif method == "POST":
            r = requests.post(url, headers=headers, json=data, timeout=30)
        elif method == "PUT":
            r = requests.put(url, headers=headers, json=data, timeout=30)
        else:
            raise ValueError(f"Unsupported method: {method}")

        if r.status_code >= 400:
            raise RuntimeError(f"{method} {endpoint}: HTTP {r.status_code} - {r.text[:200]}")

        result = r.json()
        result["_link_header"] = r.headers.get("Link", None)
        return result
    except requests.exceptions.Timeout:
        raise RuntimeError(f"{method} {endpoint}: Request timeout")
    except ValueError as e:
        raise RuntimeError(f"{method} {endpoint}: Invalid JSON response - {e}")


def _shopify_graphql(query: str, variables: Optional[Dict] = None) -> Dict:
    """Make Shopify GraphQL API request."""
    if not SHOPIFY_ACCESS_TOKEN:
        raise RuntimeError("SHOPIFY_ACCESS_TOKEN not set in environment")

    url = f"https://{SHOPIFY_STORE}/admin/api/{API_VERSION}/graphql.json"
    headers = {
        "X-Shopify-Access-Token": SHOPIFY_ACCESS_TOKEN,
        "Content-Type": "application/json",
    }
    payload = {"query": query}
    if variables:
        payload["variables"] = variables

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=30)
        if r.status_code >= 400:
            raise RuntimeError(f"GraphQL: HTTP {r.status_code} - {r.text[:200]}")

        result = r.json()
        if "errors" in result:
            raise RuntimeError(f"GraphQL errors: {result['errors']}")
        return result
    except requests.exceptions.Timeout:
        raise RuntimeError("GraphQL: Request timeout")
    except ValueError as e:
        raise RuntimeError(f"GraphQL: Invalid JSON response - {e}")


def get_products(status: str = "active") -> List[Dict]:
    """Fetch all products from Shopify store via GraphQL with cost data."""
    products = []
    cursor = None

    query = """
query ($first: Int!, $after: String) {
  products(first: $first, after: $after, query: "status:active") {
    pageInfo {
      hasNextPage
      endCursor
    }
    edges {
      node {
        id
        title
        variants(first: 100) {
          edges {
            node {
              id
              sku
              price
              inventoryItem {
                unitCost {
                  amount
                }
              }
            }
          }
        }
      }
    }
  }
}
"""

    page = 1
    while True:
        try:
            variables = {
                "first": 50,
                "after": cursor
            }

            response = _shopify_graphql(query, variables)
            data = response.get("data", {}).get("products", {})

            batch = []
            for edge in data.get("edges", []):
                node = edge.get("node", {})
                product = {
                    "id": node.get("id"),
                    "title": node.get("title"),
                    "variants": []
                }
                for var_edge in node.get("variants", {}).get("edges", []):
                    var_node = var_edge.get("node", {})
                    inv_item = var_node.get("inventoryItem", {})
                    unit_cost_data = inv_item.get("unitCost", {})
                    cost = float(unit_cost_data.get("amount") or 0)

                    product["variants"].append({
                        "id": var_node.get("id"),
                        "sku": var_node.get("sku"),
                        "price": float(var_node.get("price") or 0),
                        "cost": cost,
                    })
                batch.append(product)

            products.extend(batch)
            print(f"[Fetch] Page {page}: {len(batch)} products (total: {len(products)})")

            page_info = data.get("pageInfo", {})
            if not page_info.get("hasNextPage"):
                break

            cursor = page_info.get("endCursor")
            page += 1
        except Exception as e:
            print(f"[Error] Failed to fetch page {page}: {e}")
            break

    return products


def calculate_target_price(cost: float, multiplier: Optional[float] = None, verbose: bool = True) -> float:
    """
    Calculate target retail price using dynamic multiplier.

    Uses AI to suggest optimal multiplier based on product category/cost range,
    then applies psychology pricing (.99 ending).
    Falls back to fixed multiplier if AI fails.
    """
    if cost <= 0:
        return 0

    multiplier = multiplier or COST_MULTIPLIER_MIN
    shipping = (SHIPPING_COST_MIN + SHIPPING_COST_MAX) / 2

    # For low-cost items, use higher multiplier to meet profit target
    # Items under $20 cost benefit from 2.5x multiplier
    if cost < 20 and multiplier == COST_MULTIPLIER_MIN:
        multiplier = COST_MULTIPLIER_MAX

    # Skip AI if no API key is configured to avoid timeout overhead
    try:
        import os
        if os.getenv("OPENROUTER_API_KEY") or os.getenv("GEMINI_API_KEY"):
            prompt = f"""Given a product cost of ${cost:.2f}, suggest the best price multiplier (2.3-2.5) to maximize sales while maintaining $20+ profit after $8.50 shipping cost.

Only respond with a single decimal number between 2.3 and 2.5, nothing else.
Example response: 2.4"""

            ai_multiplier = ai_client.generate(prompt, max_tokens=10, temperature=0.3, category="pricing")
            if ai_multiplier:
                try:
                    m = float(ai_multiplier.strip())
                    if COST_MULTIPLIER_MIN <= m <= COST_MULTIPLIER_MAX:
                        multiplier = m
                        if verbose:
                            print(f"    [Pricing] AI suggested multiplier: {m}")
                except (ValueError, AttributeError):
                    if verbose:
                        print(f"    [Pricing] AI response not parseable: {ai_multiplier}, using default")
    except Exception:
        pass

    raw_price = (cost * multiplier) + shipping

    integer_part = int(raw_price)
    price_99 = integer_part + 0.99

    if price_99 < raw_price:
        price_99 = (integer_part + 1) + 0.99

    return round(price_99, 2)


def should_update_price(product: Dict, new_price: float) -> bool:
    """Check if price actually needs updating (avoid unnecessary API calls)."""
    for variant in product.get("variants", []):
        current = float(variant.get("price", 0))
        if abs(current - new_price) > 0.01:
            return True
    return False


def update_variant_prices(product_id: str, variant_id: str, new_price: float) -> bool:
    """Update a single variant price in Shopify."""
    try:
        data = {
            "variant": {
                "id": variant_id,
                "price": new_price,
            }
        }
        _shopify_request("PUT", f"variants/{variant_id}", data)
        return True
    except Exception as e:
        print(f"    ERROR updating variant {variant_id}: {e}")
        return False




def update_product_prices(products: List[Dict]) -> Dict:
    """Update prices for all products based on calculated multipliers."""
    stats = {
        "total": len(products),
        "updated": 0,
        "skipped": 0,
        "errors": 0,
        "timestamp": datetime.now().isoformat(),
        "products": [],
    }

    print(f"\n[PriceUpdate] Processing {len(products)} products...")
    print(f"\n{'Seq':<5} | {'Product Title':<35} | {'Old Price':<10} | {'New Price':<10} | {'Cost':<8} | {'Profit':<8} | {'Status':<10}")
    print("-" * 110)

    for i, product in enumerate(products, 1):
        product_id = product.get("id")
        title = product.get("title", "Unknown")[:32]

        for variant in product.get("variants", []):
            variant_id = variant.get("id")
            sku = variant.get("sku", "N/A")
            cost = float(variant.get("cost", 0))
            current_price = float(variant.get("price", 0))

            if cost <= 0:
                status = "NO COST"
                print(f"{i:<5} | {title:<35} | {'—':<10} | {'—':<10} | {'—':<8} | {'—':<8} | {status:<10}")
                stats["skipped"] += 1
                stats["products"].append({
                    "sku": sku,
                    "title": title,
                    "old_price": None,
                    "new_price": None,
                    "cost": None,
                    "profit": None,
                    "status": "skipped_no_cost"
                })
                continue

            new_price = calculate_target_price(cost, verbose=False)
            profit = new_price - cost - (SHIPPING_COST_MAX / 2)

            if abs(current_price - new_price) < 0.01:
                status = "OPTIMAL"
                print(f"{i:<5} | {title:<35} | ${current_price:<9.2f} | ${new_price:<9.2f} | ${cost:<7.2f} | ${profit:<7.2f} | {status:<10}")
                stats["skipped"] += 1
                stats["products"].append({
                    "sku": sku,
                    "title": title,
                    "old_price": current_price,
                    "new_price": new_price,
                    "cost": cost,
                    "profit": profit,
                    "status": "skipped_optimal"
                })
                continue

            print(f"{i:<5} | {title:<35} | ${current_price:<9.2f} | ${new_price:<9.2f} | ${cost:<7.2f} | ${profit:<7.2f} | UPDATED   ")

            if update_variant_prices(product_id, variant_id, new_price):
                stats["updated"] += 1
                stats["products"].append({
                    "sku": sku,
                    "title": title,
                    "old_price": current_price,
                    "new_price": new_price,
                    "cost": cost,
                    "profit": profit,
                    "status": "updated"
                })
            else:
                stats["errors"] += 1
                stats["products"].append({
                    "sku": sku,
                    "title": title,
                    "old_price": current_price,
                    "new_price": new_price,
                    "cost": cost,
                    "profit": profit,
                    "status": "error"
                })

    print("-" * 110)
    print(f"\n[PriceUpdate] Complete: {stats['updated']} updated, {stats['skipped']} skipped, {stats['errors']} errors")
    return stats


def save_update_log(stats: Dict, filepath: str = "price_update_log.json"):
    """Save detailed update statistics to JSON log with product-level info."""
    log_entry = {
        "timestamp": stats["timestamp"],
        "summary": {
            "total_products": stats["total"],
            "updated": stats["updated"],
            "skipped": stats["skipped"],
            "errors": stats["errors"],
        },
        "products": stats.get("products", [])
    }

    logs = []
    if Path(filepath).exists():
        try:
            logs = json.loads(Path(filepath).read_text())
        except (json.JSONDecodeError, IOError):
            logs = []

    logs.append(log_entry)
    Path(filepath).write_text(json.dumps(logs, indent=2))
    print(f"[Log] Saved detailed log to {filepath}")


if __name__ == "__main__":
    print(f"[MeeeShop] Price Update Engine (LIVE mode)")
    print(f"Store: {SHOPIFY_STORE}")
    print(f"Pricing: {COST_MULTIPLIER_MIN}x - {COST_MULTIPLIER_MAX}x cost + ${SHIPPING_COST_MIN}-${SHIPPING_COST_MAX} shipping")
    print(f"Target profit: ${TARGET_PROFIT} minimum\n")

    try:
        print("[Fetch] Retrieving active products from Shopify...")
        products = get_products(status="active")
        print(f"[Fetch] Found {len(products)} products")

        stats = update_product_prices(products)
        save_update_log(stats)

    except KeyboardInterrupt:
        print("\n[Cancelled] Update interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n[Error] {e}")
        sys.exit(1)

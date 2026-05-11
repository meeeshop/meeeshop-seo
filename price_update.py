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


def _shopify_request(method: str, endpoint: str, data: Optional[Dict] = None) -> Dict:
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
            r = requests.get(url, headers=headers, timeout=30)
        elif method == "POST":
            r = requests.post(url, headers=headers, json=data, timeout=30)
        elif method == "PUT":
            r = requests.put(url, headers=headers, json=data, timeout=30)
        else:
            raise ValueError(f"Unsupported method: {method}")

        if r.status_code >= 400:
            raise RuntimeError(f"{method} {endpoint}: HTTP {r.status_code} - {r.text[:200]}")
        return r.json()
    except requests.exceptions.Timeout:
        raise RuntimeError(f"{method} {endpoint}: Request timeout")
    except ValueError as e:
        raise RuntimeError(f"{method} {endpoint}: Invalid JSON response - {e}")


def get_products(limit: int = 250, status: str = "active") -> List[Dict]:
    """Fetch all products from Shopify store."""
    products = []
    cursor = None
    page = 1

    while True:
        try:
            query = f"products?limit={limit}&status={status}&fields=id,title,variants"
            if cursor:
                query += f"&after={cursor}"

            response = _shopify_request("GET", query)
            batch = response.get("products", [])
            products.extend(batch)
            print(f"[Fetch] Page {page}: {len(batch)} products")

            if "next" not in response.get("_links", {}):
                break

            cursor = response["_links"]["next"].split("after=")[1]
            if "&" in cursor:
                cursor = cursor.split("&")[0]
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


def update_product_prices(products: List[Dict], dry_run: bool = False) -> Dict:
    """Update prices for all products based on calculated multipliers."""
    stats = {
        "total": len(products),
        "updated": 0,
        "skipped": 0,
        "errors": 0,
        "timestamp": datetime.now().isoformat(),
    }

    print(f"\n[PriceUpdate] Processing {len(products)} products...")

    for i, product in enumerate(products, 1):
        product_id = product.get("id")
        title = product.get("title", "Unknown")

        for variant in product.get("variants", []):
            variant_id = variant.get("id")
            cost = float(variant.get("cost", 0))

            if cost <= 0:
                print(f"  [{i}/{len(products)}] {title}: SKU {variant.get('sku', 'N/A')} - NO COST, skipping")
                stats["skipped"] += 1
                continue

            new_price = calculate_target_price(cost)
            current_price = float(variant.get("price", 0))

            if abs(current_price - new_price) < 0.01:
                print(f"  [{i}/{len(products)}] {title}: Already ${new_price:.2f}, no update needed")
                stats["skipped"] += 1
                continue

            profit = new_price - cost - (SHIPPING_COST_MAX / 2)
            print(f"  [{i}/{len(products)}] {title}: ${current_price:.2f} -> ${new_price:.2f} (cost: ${cost:.2f}, profit: ${profit:.2f})")

            if dry_run:
                print(f"      [DRY-RUN] Would update to ${new_price:.2f}")
                stats["updated"] += 1
            else:
                if update_variant_prices(product_id, variant_id, new_price):
                    stats["updated"] += 1
                else:
                    stats["errors"] += 1

    print(f"\n[PriceUpdate] Complete: {stats['updated']} updated, {stats['skipped']} skipped, {stats['errors']} errors")
    return stats


def save_update_log(stats: Dict, filepath: str = "price_update_log.json"):
    """Save update statistics to JSON log."""
    logs = []
    if Path(filepath).exists():
        logs = json.loads(Path(filepath).read_text())
    logs.append(stats)
    Path(filepath).write_text(json.dumps(logs, indent=2))
    print(f"[Log] Saved to {filepath}")


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv or "--test" in sys.argv
    mode = "DRY-RUN" if dry_run else "LIVE"

    print(f"[MeeeShop] Price Update Engine ({mode} mode)")
    print(f"Store: {SHOPIFY_STORE}")
    print(f"Pricing: {COST_MULTIPLIER_MIN}x - {COST_MULTIPLIER_MAX}x cost + ${SHIPPING_COST_MIN}-${SHIPPING_COST_MAX} shipping")
    print(f"Target profit: ${TARGET_PROFIT} minimum\n")

    try:
        print("[Fetch] Retrieving active products from Shopify...")
        products = get_products(status="active")
        print(f"[Fetch] Found {len(products)} products")

        stats = update_product_prices(products, dry_run=dry_run)
        save_update_log(stats)

    except KeyboardInterrupt:
        print("\n[Cancelled] Update interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n[Error] {e}")
        sys.exit(1)

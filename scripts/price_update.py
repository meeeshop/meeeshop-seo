"""
Dynamic pricing, market competitiveness, and margin protection engine for MeeeShop inventory.

Rules:
  - Protects store profits against Shop App CAC ($29.00), Shopify Capital repayment (10%),
    and payment processing fees (~2.9% + $0.30).
  - Guarantees minimum +$10.00 net profit per single-item order on Shop App.
  - Market Competitiveness Guardrails: Checks category-specific price ceilings (Tops, Sweaters,
    Denim, Dresses, Outerwear, Bags) so products are NEVER overpriced. Customers won't be scared
    away by inflated prices.
  - Smart Channel Routing: If a product's required break-even price exceeds its category market ceiling,
    it is capped at a competitive market price and automatically tagged 'exclude-shop-app' (so it sells
    profitably on Web / Google / Pinterest without the $29 CAC penalty).
  - Ensures uniform retail pricing across all standard sizes (XS - XXL) of a product.
  - Fixes inverted compare-at prices.
  - Snaps prices to clean boutique endings (x4.99 or x9.99).

Modes:
  daily  -- products created in the last 48 hours (default)
  weekly -- products created in the last 7 days
  force  -- ALL active products, supports --batch-size / --batch-index
            for splitting across multiple GitHub Actions jobs

Usage:
  python price_update.py --mode daily
  python price_update.py --mode weekly
  python price_update.py --mode force --batch-size 150 --batch-index 0
"""

import os
import sys
import json
import time
import math
import argparse
import requests
from pathlib import Path
from typing import Optional, Dict, List, Set, Tuple
from datetime import datetime, timezone, timedelta

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

# ---------------------------------------------------------------------------
# Unit Economics Parameters (Shop App & Storefront)
# ---------------------------------------------------------------------------
SHOP_APP_CAC = 29.00               # Fixed acquisition fee per converted Shop App customer
SHOPIFY_CAPITAL_RATE = 0.10        # 10% deduction on gross store revenue
PAYMENT_GATEWAY_RATE = 0.029       # ~2.9% Shopify Payments / Shop Pay processing fee
PAYMENT_FIXED_FEE = 0.30           # $0.30 fixed processing fee
ESTIMATED_DROPSHIP_SHIPPING = 7.50  # Average vendor dropship & handling fee
TARGET_MIN_PROFIT = 10.00          # Minimum target net profit per single-item order
MIN_PRICE_FLOOR = 74.99            # Minimum price floor to safeguard margins
API_DELAY_SECONDS = 0.4            # Delay between Shopify API calls to respect rate limits

# ---------------------------------------------------------------------------
# Category Market Ceilings (Prevents Overpricing)
# ---------------------------------------------------------------------------
# If an item requires a price above these ceilings to cover Shop App CAC,
# it is capped at the ceiling and EXCLUDED from Shop App to preserve high
# conversion rates on Web / Google / Pinterest.
CATEGORY_MARKET_CEILINGS = {
    "outerwear": 159.99,    # Coats, Jackets, Blazers, Parkas, Vests
    "dresses": 134.99,      # Maxi, Midi, Gowns, Jumpsuits, Rompers
    "sweaters": 104.99,     # Knitwear, Sweaters, Cardigans, Pullovers
    "bottoms": 104.99,      # Jeans, Denim, Pants, Trousers, Skirts
    "bags": 119.99,         # Handbags, Totes, Crossbody, Backpacks
    "shoes": 119.99,        # Boots, Heels, Sneakers, Flats
    "tops": 84.99,          # Blouses, Button-ups, Shirts, Camis, Halters
    "tees": 64.99,          # Graphic Tees, Basic T-Shirts
    "accessories": 49.99,   # Hats, Belts, Scarves, Jewelry, Socks
    "general": 99.99,       # Default fallback ceiling
}


def get_category_market_ceiling(title: str, product_type: str) -> Tuple[str, float]:
    """
    Classifies a product into its fashion category and returns its market ceiling.
    Ensures retail prices remain competitive and attractive to shoppers.
    """
    text = f"{product_type} {title}".lower()
    if any(k in text for k in ['jacket', 'coat', 'blazer', 'outerwear', 'parka', 'vest', 'shacket']):
        return "outerwear", CATEGORY_MARKET_CEILINGS["outerwear"]
    if any(k in text for k in ['dress', 'gown', 'jumpsuit', 'romper', 'maxi', 'midi']):
        return "dresses", CATEGORY_MARKET_CEILINGS["dresses"]
    if any(k in text for k in ['sweater', 'cardigan', 'knit', 'pullover', 'hoodie']):
        return "sweaters", CATEGORY_MARKET_CEILINGS["sweaters"]
    if any(k in text for k in ['jean', 'denim', 'pant', 'trouser', 'legging', 'skirt', 'short']):
        return "bottoms", CATEGORY_MARKET_CEILINGS["bottoms"]
    if any(k in text for k in ['bag', 'tote', 'backpack', 'crossbody', 'purse', 'satchel', 'wallet']):
        return "bags", CATEGORY_MARKET_CEILINGS["bags"]
    if any(k in text for k in ['boot', 'shoe', 'heel', 'sneaker', 'sandal', 'flat']):
        return "shoes", CATEGORY_MARKET_CEILINGS["shoes"]
    if any(k in text for k in ['tee', 't-shirt', 'graphic']):
        return "tees", CATEGORY_MARKET_CEILINGS["tees"]
    if any(k in text for k in ['top', 'blouse', 'cami', 'tank', 'shirt', 'halter', 'corset']):
        return "tops", CATEGORY_MARKET_CEILINGS["tops"]
    if any(k in text for k in ['hat', 'beanie', 'scarf', 'belt', 'jewelry', 'earring', 'necklace', 'bracelet', 'sock']):
        return "accessories", CATEGORY_MARKET_CEILINGS["accessories"]
    return "general", CATEGORY_MARKET_CEILINGS["general"]


# ---------------------------------------------------------------------------
# Shopify API helpers
# ---------------------------------------------------------------------------

def _shopify_request(method: str, endpoint: str, data: Optional[Dict] = None,
                     params: Optional[Dict] = None) -> Dict:
    url = f"https://{SHOPIFY_STORE}/admin/api/{API_VERSION}/{endpoint}.json"
    headers = {
        "X-Shopify-Access-Token": SHOPIFY_ACCESS_TOKEN,
        "Content-Type": "application/json",
    }
    for attempt in range(3):
        try:
            if method == "GET":
                r = requests.get(url, headers=headers, params=params, timeout=30)
            elif method == "PUT":
                r = requests.put(url, headers=headers, json=data, timeout=30)
            else:
                raise ValueError(f"Unsupported method: {method}")

            if r.status_code == 429:
                retry_after = int(float(r.headers.get("Retry-After", 4)))
                _log.warning("[RateLimit] 429 received, sleeping %ds", retry_after)
                time.sleep(retry_after)
                continue

            if r.status_code >= 400:
                raise RuntimeError(f"{method} {endpoint}: HTTP {r.status_code} - {r.text[:200]}")

            result = r.json()
            result["_link_header"] = r.headers.get("Link")
            return result
        except requests.exceptions.Timeout:
            if attempt == 2:
                raise RuntimeError(f"{method} {endpoint}: Request timeout after 3 attempts")
            time.sleep(2)
    raise RuntimeError(f"{method} {endpoint}: Failed after 3 attempts")


def _shopify_graphql(query: str, variables: Optional[Dict] = None) -> Dict:
    url = f"https://{SHOPIFY_STORE}/admin/api/{API_VERSION}/graphql.json"
    headers = {
        "X-Shopify-Access-Token": SHOPIFY_ACCESS_TOKEN,
        "Content-Type": "application/json",
    }
    payload = {"query": query, **({"variables": variables} if variables else {})}

    for attempt in range(3):
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=30)
            if r.status_code == 429:
                retry_after = int(float(r.headers.get("Retry-After", 4)))
                _log.warning("[RateLimit] 429 on GraphQL, sleeping %ds", retry_after)
                time.sleep(retry_after)
                continue
            if r.status_code >= 400:
                raise RuntimeError(f"GraphQL: HTTP {r.status_code} - {r.text[:200]}")
            result = r.json()
            if "errors" in result:
                raise RuntimeError(f"GraphQL errors: {result['errors']}")
            return result
        except requests.exceptions.Timeout:
            if attempt == 2:
                raise RuntimeError("GraphQL: timeout after 3 attempts")
            time.sleep(2)
    raise RuntimeError("GraphQL: Failed after 3 attempts")


# ---------------------------------------------------------------------------
# Product fetching
# ---------------------------------------------------------------------------

_PRODUCT_QUERY = """
query ($first: Int!, $after: String, $query: String!) {
  products(first: $first, after: $after, query: $query) {
    pageInfo { hasNextPage endCursor }
    edges {
      node {
        id
        title
        vendor
        productType
        tags
        createdAt
        variants(first: 100) {
          edges {
            node {
              id
              title
              sku
              price
              compareAtPrice
              inventoryItem {
                unitCost { amount }
              }
            }
          }
        }
      }
    }
  }
}
"""


def get_products(mode: str, window_hours: Optional[int] = None) -> List[Dict]:
    now = datetime.now(timezone.utc)
    if mode == "daily":
        hours = window_hours if window_hours is not None else 48
        since = now - timedelta(hours=hours)
        date_filter = f" AND created_at:>={since.strftime('%Y-%m-%dT%H:%M:%SZ')}"
        window_label = f"last {hours} hours"
    elif mode == "weekly":
        hours = window_hours if window_hours is not None else 168
        since = now - timedelta(hours=hours)
        date_filter = f" AND created_at:>={since.strftime('%Y-%m-%dT%H:%M:%SZ')}"
        window_label = f"last {hours} hours"
    else:  # force
        date_filter = ""
        window_label = "all time"

    gql_query_filter = f"status:active{date_filter}"
    print(f"[Fetch] Mode={mode}, window={window_label}")
    print(f"[Fetch] GraphQL filter: {gql_query_filter}")

    products = []
    cursor = None
    page = 1

    while True:
        try:
            variables = {"first": 50, "after": cursor, "query": gql_query_filter}
            response = _shopify_graphql(_PRODUCT_QUERY, variables)
            data = response.get("data", {}).get("products", {})

            batch = []
            for edge in data.get("edges", []):
                node = edge.get("node", {})
                product = {
                    "id": node.get("id"),
                    "title": node.get("title"),
                    "vendor": node.get("vendor", ""),
                    "product_type": node.get("productType", ""),
                    "tags": node.get("tags", []),
                    "created_at": node.get("createdAt"),
                    "variants": [],
                }
                for var_edge in node.get("variants", {}).get("edges", []):
                    v = var_edge.get("node", {})
                    cost_node = v.get("inventoryItem", {}).get("unitCost")
                    unit_cost = float(cost_node["amount"]) if cost_node and cost_node.get("amount") else None
                    compare_at = float(v["compareAtPrice"]) if v.get("compareAtPrice") else None

                    product["variants"].append({
                        "id": v.get("id"),
                        "title": v.get("title", ""),
                        "sku": v.get("sku", ""),
                        "price": float(v.get("price") or 0),
                        "compare_at_price": compare_at,
                        "unit_cost": unit_cost,
                    })
                batch.append(product)

            products.extend(batch)
            print(f"[Fetch] Page {page}: {len(batch)} products (total so far: {len(products)})")

            page_info = data.get("pageInfo", {})
            if not page_info.get("hasNextPage"):
                break
            cursor = page_info.get("endCursor")
            page += 1

        except Exception as e:
            _log.error("[Fetch] Failed on page %d: %s", page, e)
            break

    return products


# ---------------------------------------------------------------------------
# Pricing & Market Guardrail Logic
# ---------------------------------------------------------------------------

def snap_to_ending(price: float) -> float:
    """Snap price up to the nearest x4.99 or x9.99 ending."""
    base = int(price)
    candidates = []
    for b in range(base - 1, base + 11):
        if b % 10 in (4, 9):
            candidates.append(round(b + 0.99, 2))
    above = [c for c in candidates if c >= price - 0.01]
    return above[0] if above else candidates[-1]


def is_valid_ending(price: float) -> bool:
    """Return True if price has a valid x4.99 or x9.99 ending."""
    cents = round(price % 10, 2)
    return cents in (4.99, 9.99)


def calculate_optimal_price_and_eligibility(
    current_price: float,
    unit_cost: Optional[float],
    title: str,
    product_type: str
) -> Tuple[float, bool]:
    """
    Balances profit guarantee with market price competitiveness:

    1. Computes the required break-even + profit price for Shop App:
       Required = (VendorCost + $29 CAC + $0.30 fee + $10 profit) / 0.871

    2. Checks the Category Market Ceiling (e.g. $84.99 for Tops, $104.99 for Sweaters/Jeans, $134.99 for Dresses):
       - If Required Price <= Category Market Ceiling:
         The price is competitive, attractive to customers, AND profitable on Shop App!
         -> Sets price to Required Price (snapped to .99/.49)
         -> Eligible for Shop App (exclude_from_shop = False)

       - If Required Price > Category Market Ceiling:
         Charging the required price would make the item too expensive for shoppers.
         Instead of overpricing the item and destroying sales conversion:
         -> Caps price at the competitive Category Market Ceiling.
         -> Excludes item from Shop App (exclude_from_shop = True) so it sells profitably on
            Web / Google / Pinterest (where no $29 CAC applies, yielding healthy 50%+ margins).

    3. Low-Ticket Items (< $45 MSRP accessories/tees):
       -> Kept at standard competitive boutique price.
       -> Excluded from Shop App (exclude_from_shop = True).
    """
    category, market_ceiling = get_category_market_ceiling(title, product_type)

    if unit_cost is not None and unit_cost > 0:
        vendor_payout = unit_cost + ESTIMATED_DROPSHIP_SHIPPING
        required_raw = (vendor_payout + SHOP_APP_CAC + PAYMENT_FIXED_FEE + TARGET_MIN_PROFIT) / (1.0 - SHOPIFY_CAPITAL_RATE - PAYMENT_GATEWAY_RATE)
        required_price = snap_to_ending(max(MIN_PRICE_FLOOR, required_raw))

        if required_price <= market_ceiling and unit_cost <= 70.0:
            # Safe and competitive for Shop App!
            final_price = max(required_price, current_price)
            final_price = snap_to_ending(final_price)
            return final_price, False
        else:
            # Over market ceiling: Cap at market ceiling to keep customers buying on Web/Google,
            # and exclude from Shop App to protect CAC margins.
            competitive_price = min(max(MIN_PRICE_FLOOR, current_price), market_ceiling)
            competitive_price = snap_to_ending(competitive_price)
            return competitive_price, True
    else:
        # Fallback when unit cost is not provided in inventoryItem
        if current_price < 40.0:
            raw = max(MIN_PRICE_FLOOR, current_price + 35.0)
        elif current_price < 65.0:
            raw = max(79.99, current_price + 25.0)
        elif current_price < 90.0:
            raw = max(94.99, current_price + 20.0)
        else:
            raw = current_price + 15.0

        target = snap_to_ending(raw)
        if target > market_ceiling:
            return market_ceiling, True
        return target, False


# ---------------------------------------------------------------------------
# Bulk Mutations
# ---------------------------------------------------------------------------

def bulk_update_variants(product_id: str, variant_updates: List[Dict]) -> bool:
    """Update multiple variant prices and compare-at prices for a product in bulk via GraphQL."""
    query = """
    mutation productVariantsBulkUpdate($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
      productVariantsBulkUpdate(productId: $productId, variants: $variants) {
        product { id }
        productVariants { id price compareAtPrice }
        userErrors { field message }
      }
    }
    """
    formatted_variants = []
    for vu in variant_updates:
        v_dict = {
            "id": vu["id"],
            "price": f"{vu['price']:.2f}"
        }
        if "compare_at_price" in vu and vu["compare_at_price"] is not None:
            v_dict["compareAtPrice"] = f"{vu['compare_at_price']:.2f}"
        formatted_variants.append(v_dict)

    variables = {
        "productId": product_id,
        "variants": formatted_variants
    }
    try:
        res = _shopify_graphql(query, variables)
        errors = res.get("data", {}).get("productVariantsBulkUpdate", {}).get("userErrors", [])
        if errors:
            _log.error("[GraphQL] Errors bulk updating variants for %s: %s", product_id, errors)
            return False
        return True
    except Exception as e:
        _log.error("[GraphQL] Exception bulk updating variants for %s: %s", product_id, e)
        return False


def set_product_tag(product_id: str, tag: str, add: bool = True) -> bool:
    """Add or remove a tag from a product via GraphQL."""
    mutation = """
    mutation tagsAdd($id: ID!, $tags: [String!]!) {
      tagsAdd(id: $id, tags: $tags) {
        node { id }
        userErrors { field message }
      }
    }
    """ if add else """
    mutation tagsRemove($id: ID!, $tags: [String!]!) {
      tagsRemove(id: $id, tags: $tags) {
        node { id }
        userErrors { field message }
      }
    }
    """
    op = "tagsAdd" if add else "tagsRemove"
    try:
        res = _shopify_graphql(mutation, {"id": product_id, "tags": [tag]})
        errors = res.get("data", {}).get(op, {}).get("userErrors", [])
        if errors:
            _log.error("[Tags] %s error for %s: %s", op, product_id, errors)
            return False
        return True
    except Exception as e:
        _log.error("[Tags] Exception in %s for %s: %s", op, product_id, e)
        return False


# ---------------------------------------------------------------------------
# Core Pricing & Channel Protection Engine
# ---------------------------------------------------------------------------

def update_product_prices(products: List[Dict], batch_index: int = 0,
                          batch_size: int = 0,
                          skip_ids: Optional[set] = None,
                          dry_run: bool = False) -> Dict:
    """
    Process products list with market guardrails and Shop App channel exclusion.

    Guarantees:
      1. Prices are competitive as per category market ceilings (never too expensive).
      2. Prices cover Shop App CAC + 10% Capital + 3% Fees + $10 Profit.
      3. Products exceeding market ceiling are capped and tagged 'exclude-shop-app'.
      4. All sizes of a product share a uniform retail price.
    """
    if batch_size > 0:
        start = batch_index * batch_size
        end = start + batch_size
        slice_ = products[start:end]
        print(f"[Batch] Processing slice [{start}:{end}] — {len(slice_)} of {len(products)} products")
    else:
        slice_ = products

    skip_ids = skip_ids or set()

    stats = {
        "mode_total_fetched": len(products),
        "batch_index": batch_index,
        "batch_size": batch_size,
        "total": len(slice_),
        "updated": 0,
        "skipped": 0,
        "tagged_excluded": 0,
        "errors": 0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "products": [],
    }

    mode_tag = " (DRY RUN)" if dry_run else ""
    col = f"{'#':<5} | {'Product':<34} | {'Category':<10} | {'Old Price':>9} | {'New Price':>9} | Status{mode_tag}"
    print(f"\n{col}")
    print("-" * len(col))

    for i, product in enumerate(slice_, 1):
        title = product.get("title", "Unknown")[:32]
        product_id = product.get("id")
        product_tags = product.get("tags", [])
        product_type = product.get("product_type", "")
        vendor = product.get("vendor", "")

        variants = product.get("variants", [])
        if not variants:
            continue

        valid_prices = [v["price"] for v in variants if v.get("price", 0) > 0]
        valid_costs = [v["unit_cost"] for v in variants if v.get("unit_cost") is not None and v["unit_cost"] > 0]

        if not valid_prices:
            print(f"{i:<5} | {title:<34} | {'—':<10} | {'—':>9} | {'—':>9} | NO PRICE")
            stats["skipped"] += len(variants)
            continue

        product_max_price = max(valid_prices)
        avg_cost = sum(valid_costs) / len(valid_costs) if valid_costs else None

        category, market_ceiling = get_category_market_ceiling(product.get("title", ""), product_type)

        uniform_target, must_exclude = calculate_optimal_price_and_eligibility(
            current_price=product_max_price,
            unit_cost=avg_cost,
            title=product.get("title", ""),
            product_type=product_type
        )

        # Manage 'exclude-shop-app' tag
        if must_exclude:
            if "exclude-shop-app" not in product_tags:
                if not dry_run:
                    if set_product_tag(product_id, "exclude-shop-app", add=True):
                        stats["tagged_excluded"] += 1
                        _log.info("[ExcludeTag] Added 'exclude-shop-app' to %s (Ceiling: $%.2f)", title, market_ceiling)
                else:
                    stats["tagged_excluded"] += 1
        else:
            if "exclude-shop-app" in product_tags:
                if not dry_run:
                    if set_product_tag(product_id, "exclude-shop-app", add=False):
                        _log.info("[ExcludeTag] Removed 'exclude-shop-app' from now profitable product %s", title)

        # Build variant updates (ensures uniform pricing across all sizes)
        to_update = []
        for variant in variants:
            variant_id = variant.get("id", "")
            sku = variant.get("sku", "N/A")
            current_price = float(variant.get("price", 0))
            compare_at = variant.get("compare_at_price")

            if current_price <= 0:
                stats["skipped"] += 1
                continue

            if variant_id in skip_ids:
                stats["skipped"] += 1
                continue

            needs_price_change = abs(current_price - uniform_target) >= 0.01

            # Inversion check
            needs_compare_at_change = False
            new_compare_at = compare_at
            if compare_at is not None and compare_at <= uniform_target:
                new_compare_at = snap_to_ending(uniform_target + 15.0)
                needs_compare_at_change = True

            if needs_price_change or needs_compare_at_change:
                update_item = {
                    "id": variant_id,
                    "price": uniform_target,
                    "sku": sku,
                    "old_price": current_price
                }
                if needs_compare_at_change:
                    update_item["compare_at_price"] = new_compare_at
                to_update.append(update_item)
            else:
                stats["skipped"] += 1

        if to_update:
            if dry_run:
                success = True
                label = "DRY RUN"
            else:
                success = bulk_update_variants(product_id, to_update)
                label = "UPDATED" if success else "ERROR"
                time.sleep(API_DELAY_SECONDS)

            for item in to_update:
                ex_note = " [EXCLUDED]" if must_exclude else " [SHOP-OK]"
                print(f"{i:<5} | {title:<34} | {category:<10} | ${item['old_price']:>8.2f} | ${item['price']:>8.2f} | {label}{ex_note}")
                entry = {
                    "sku": item["sku"], "title": title, "category": category, "variant_gid": item["id"],
                    "old_price": item["old_price"], "new_price": item["price"], "excluded_from_shop": must_exclude,
                    "status": "would_update" if dry_run else ("updated" if success else "error"),
                }
                if success:
                    stats["updated"] += 1
                else:
                    stats["errors"] += 1
                stats["products"].append(entry)
        else:
            ex_note = " [EXCLUDED]" if must_exclude else " [SHOP-OK]"
            print(f"{i:<5} | {title:<34} | {category:<10} | ${product_max_price:>8.2f} | ${uniform_target:>8.2f} | ALREADY OK{ex_note}")

    print("-" * len(col))
    print(f"\n[Done] {stats['updated']} updated, {stats['skipped']} skipped, {stats['tagged_excluded']} tagged excluded, {stats['errors']} errors")
    return stats


# ---------------------------------------------------------------------------
# Log helpers
# ---------------------------------------------------------------------------

def load_recently_updated_ids(filepath: str = "price_update_log.json",
                              within_hours: Optional[int] = None) -> set:
    log_files = []
    if os.path.exists(filepath):
        log_files.append(Path(filepath))

    for p in Path(".").glob("**/price_update_log.json"):
        if p.resolve() not in [lf.resolve() for lf in log_files]:
            log_files.append(p)

    cutoff = None
    if within_hours is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=within_hours)

    updated_ids: set = set()
    for lf in log_files:
        try:
            logs = json.loads(lf.read_text(encoding="utf-8"))
            if not isinstance(logs, list):
                continue
            for entry in logs:
                if not isinstance(entry, dict):
                    continue
                ts_str = entry.get("timestamp", "")
                if cutoff is not None:
                    try:
                        ts = datetime.fromisoformat(ts_str)
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=timezone.utc)
                    except ValueError:
                        continue
                    if ts < cutoff:
                        continue
                for p in entry.get("products", []):
                    if p.get("status") == "updated" and p.get("variant_gid"):
                        updated_ids.add(p["variant_gid"])
        except Exception as e:
            _log.warning("Failed to parse log file %s: %s", lf, e)

    return updated_ids


def save_update_log(stats: Dict, filepath: str = "price_update_log.json"):
    log_path = Path(filepath)
    logs = []
    if log_path.exists():
        try:
            logs = json.loads(log_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, IOError):
            logs = []

    existing_timestamps = {entry.get("timestamp") for entry in logs if isinstance(entry, dict)}

    for p in Path(".").glob("**/price_update_log.json"):
        if p.resolve() == log_path.resolve():
            continue
        try:
            sub_logs = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(sub_logs, list):
                for entry in sub_logs:
                    if isinstance(entry, dict):
                        ts = entry.get("timestamp")
                        if ts not in existing_timestamps:
                            logs.append(entry)
                            existing_timestamps.add(ts)
        except Exception as e:
            _log.warning("Failed to parse sub-log file %s: %s", p, e)

    def get_ts(entry):
        return entry.get("timestamp") or ""
    logs.sort(key=get_ts)

    logs.append({
        "timestamp": stats["timestamp"],
        "summary": {
            "mode_total_fetched": stats.get("mode_total_fetched"),
            "batch_index": stats.get("batch_index"),
            "batch_size": stats.get("batch_size"),
            "total_in_batch": stats["total"],
            "updated": stats["updated"],
            "skipped": stats["skipped"],
            "tagged_excluded": stats.get("tagged_excluded", 0),
            "errors": stats["errors"],
        },
        "products": stats.get("products", []),
    })

    log_path.write_text(json.dumps(logs, indent=2), encoding="utf-8")
    print(f"[Log] Saved consolidated log to {filepath}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description="MeeeShop dynamic pricing and market guardrail engine")
    p.add_argument(
        "--mode",
        choices=["daily", "weekly", "force"],
        default="daily",
        help="daily=48h, weekly=7d, force=all products (default: daily)",
    )
    p.add_argument(
        "--batch-size",
        type=int,
        default=0,
        help="For force mode: how many products per batch job (0=no batching)",
    )
    p.add_argument(
        "--batch-index",
        type=int,
        default=0,
        help="For force mode: which batch to process (0-based)",
    )
    p.add_argument(
        "--window",
        type=int,
        default=None,
        metavar="HOURS",
        help="Override fetch window in hours (e.g. --window 12). Only applies to daily/weekly modes.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate calculations and print preview without updating Shopify",
    )
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()

    print(f"[MeeeShop] Tiered Profit Margin & Market Guardrail Engine (Floor: ${MIN_PRICE_FLOOR:.2f})")
    print(f"Store   : {SHOPIFY_STORE}")
    print(f"Mode    : {args.mode}")
    print(f"Dry Run : {args.dry_run}")
    if args.window is not None:
        print(f"Window  : last {args.window}h (manual override)")
    if args.batch_size > 0:
        print(f"Batch   : index={args.batch_index}, size={args.batch_size}")
    print()

    try:
        products = get_products(mode=args.mode, window_hours=args.window)
        print(f"[Fetch] Total products matching filter: {len(products)}\n")

        if not products:
            print("[Done] No products to process.")
            sys.exit(0)

        skip_ids = set()
        if args.mode != "force" and not args.dry_run:
            skip_ids = load_recently_updated_ids()
            if skip_ids:
                print(f"[Skip] {len(skip_ids)} variant(s) already updated in previous runs — will skip\n")

        stats = update_product_prices(
            products,
            batch_index=args.batch_index,
            batch_size=args.batch_size,
            skip_ids=skip_ids,
            dry_run=args.dry_run,
        )
        if not args.dry_run:
            save_update_log(stats)
        else:
            print("[DryRun] Complete. No changes were committed to Shopify.")

    except KeyboardInterrupt:
        print("\n[Cancelled] Interrupted by user")
        sys.exit(1)
    except Exception as e:
        _log.exception("[Fatal] %s", e)
        sys.exit(1)

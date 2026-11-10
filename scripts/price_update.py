"""
Dynamic pricing, market competitiveness, and margin protection engine for MeeeShop inventory.

Features:
  - Unit Economics & Profit Guarantee:
      Protects store profits against Shop App CAC ($29.00), Shopify Capital (10%),
      and payment processing fees (~2.9% + $0.30) to guarantee minimum +$10.00 net profit.
  - Premium & Specialty Brand Intelligence:
      Recognizes products that are legitimately worth higher prices (technical performance,
      equestrian breeches, genuine leather, silk, cashmere, outerwear, or high wholesale cost).
      Expands ceilings up to $249 - $349+ to preserve luxury margins (generating +$35 to +$60+ profit).
  - Everyday Market Ceilings (Anti-Overpricing Guardrails):
      For everyday fashion (basic tops, graphic tees, casual pants), enforces strict category
      market ceilings so everyday items NEVER look artificially inflated.
  - Smart Channel Routing:
      If an everyday item requires a price higher than its category ceiling to cover the $29 CAC,
      it is capped at the competitive market price and automatically tagged 'exclude-shop-app'
      (so it sells profitably on Web / Google / Pinterest where no $29 CAC applies).
  - Uniform Variant Pricing:
      Ensures all sizes (XS - XXL) of a product share the exact same retail price.
  - Inverted Compare-At Fix:
      Ensures compare-at prices are never lower than the active selling price.

Modes:
  daily  -- products created in the last 48 hours (default)
  weekly -- products created in the last 7 days
  force  -- ALL active products, supports --batch-size / --batch-index
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
# Category Market Ceilings (Standard Everyday Fashion)
# ---------------------------------------------------------------------------
STANDARD_CATEGORY_CEILINGS = {
    "outerwear": 159.99,    # Standard Coats, Jackets, Blazers
    "dresses": 134.99,      # Casual/Day Dresses, Jumpsuits, Rompers
    "sweaters": 104.99,     # Knitwear, Sweaters, Cardigans, Pullovers
    "bottoms": 104.99,      # Jeans, Denim, Pants, Trousers, Skirts
    "bags": 119.99,         # Handbags, Totes, Crossbody, Backpacks
    "shoes": 119.99,        # Boots, Heels, Sneakers, Flats
    "tops": 84.99,          # Blouses, Button-ups, Shirts, Camis, Halters
    "tees": 64.99,          # Graphic Tees, Basic T-Shirts
    "accessories": 49.99,   # Hats, Belts, Scarves, Jewelry, Socks
    "general": 99.99,       # Default fallback ceiling
}

# ---------------------------------------------------------------------------
# Premium & Specialty Brand Intelligence
# ---------------------------------------------------------------------------
# Identifies items that are legitimately expensive and worth $150 - $350+
PREMIUM_VENDORS = {
    "botori equestrian", "buki", "artemis vintage", "charming bunny"
}

PREMIUM_KEYWORDS = [
    "leather", "suede", "silk", "cashmere", "merino", "wool", "shearling",
    "breech", "riding tights", "riding pants", "technical", "tweed",
    "gown", "evening dress", "sequin", "velvet", "down coat", "trench coat",
    "parka", "blazer set", "tailored suit"
]


def is_legitimately_premium(
    title: str,
    vendor: str,
    product_type: str,
    unit_cost: Optional[float],
    current_price: float
) -> Tuple[bool, str]:
    """
    Checks if a product is legitimately a high-ticket / luxury / technical item.
    Returns (is_premium, reason).
    """
    text = f"{title} {product_type}".lower()
    v_lower = (vendor or "").lower()

    if v_lower in PREMIUM_VENDORS:
        return True, f"premium vendor ({vendor})"

    if unit_cost is not None and unit_cost >= 58.0:
        return True, f"high wholesale cost (${unit_cost:.2f})"

    for kw in PREMIUM_KEYWORDS:
        if kw in text:
            return True, f"premium material/craftsmanship ({kw})"

    if current_price >= 135.0:
        return True, f"established high-ticket positioning (${current_price:.2f})"

    return False, "standard boutique"


def get_category_market_ceiling(title: str, product_type: str) -> Tuple[str, float]:
    """Classifies a product into its fashion category and returns its standard market ceiling."""
    text = f"{product_type} {title}".lower()
    if any(k in text for k in ['jacket', 'coat', 'blazer', 'outerwear', 'parka', 'vest', 'shacket']):
        return "outerwear", STANDARD_CATEGORY_CEILINGS["outerwear"]
    if any(k in text for k in ['dress', 'gown', 'jumpsuit', 'romper', 'maxi', 'midi']):
        return "dresses", STANDARD_CATEGORY_CEILINGS["dresses"]
    if any(k in text for k in ['sweater', 'cardigan', 'knit', 'pullover', 'hoodie']):
        return "sweaters", STANDARD_CATEGORY_CEILINGS["sweaters"]
    if any(k in text for k in ['jean', 'denim', 'pant', 'trouser', 'legging', 'skirt', 'short']):
        return "bottoms", STANDARD_CATEGORY_CEILINGS["bottoms"]
    if any(k in text for k in ['bag', 'tote', 'backpack', 'crossbody', 'purse', 'satchel', 'wallet']):
        return "bags", STANDARD_CATEGORY_CEILINGS["bags"]
    if any(k in text for k in ['boot', 'shoe', 'heel', 'sneaker', 'sandal', 'flat']):
        return "shoes", STANDARD_CATEGORY_CEILINGS["shoes"]
    if any(k in text for k in ['tee', 't-shirt', 'graphic']):
        return "tees", STANDARD_CATEGORY_CEILINGS["tees"]
    if any(k in text for k in ['top', 'blouse', 'cami', 'tank', 'shirt', 'halter', 'corset']):
        return "tops", STANDARD_CATEGORY_CEILINGS["tops"]
    if any(k in text for k in ['hat', 'beanie', 'scarf', 'belt', 'jewelry', 'earring', 'necklace', 'bracelet', 'sock']):
        return "accessories", STANDARD_CATEGORY_CEILINGS["accessories"]
    return "general", STANDARD_CATEGORY_CEILINGS["general"]


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
    vendor: str,
    product_type: str
) -> Tuple[float, bool, str]:
    """
    Intelligent Dual-Tier Pricing:
    
    1. Premium & Specialty Items (e.g. equestrian breeches, cashmere, silk, leather, coats):
       - Recognizes authentic high-ticket value.
       - Expands ceiling up to $249 - $349+.
       - Preserves full luxury/technical price point ($150 - $220+).
       - Approves for Shop App (exclude_from_shop = False) because high ticket orders
         generate massive +$35 to +$60+ net profit after the $29 CAC!

    2. Everyday Fashion Items (basic tops, casual shorts, graphic tees):
       - Enforces strict category ceilings ($64.99 tees, $84.99 tops, $104.99 bottoms).
       - If required break-even price exceeds category ceiling:
         -> Caps price at competitive ceiling (so shoppers buy!).
         -> Excludes from Shop App (exclude_from_shop = True) so it sells profitably
            on Web / Google / Pinterest with NO $29 CAC.
    """
    is_premium, premium_reason = is_legitimately_premium(title, vendor, product_type, unit_cost, current_price)
    category, std_ceiling = get_category_market_ceiling(title, product_type)

    if is_premium:
        # Dynamic premium ceiling based on wholesale cost or luxury tier
        if unit_cost and unit_cost > 0:
            premium_ceiling = max(249.99, snap_to_ending(unit_cost * 2.4))
        else:
            premium_ceiling = max(249.99, snap_to_ending(current_price * 1.3))

        # Calculate price to ensure full profit
        if unit_cost and unit_cost > 0:
            vendor_payout = unit_cost + ESTIMATED_DROPSHIP_SHIPPING
            # For premium items, target higher net profit ($20 - $40+)
            premium_target_profit = max(TARGET_MIN_PROFIT, unit_cost * 0.35)
            required_raw = (vendor_payout + SHOP_APP_CAC + PAYMENT_FIXED_FEE + premium_target_profit) / (1.0 - SHOPIFY_CAPITAL_RATE - PAYMENT_GATEWAY_RATE)
            raw_target = max(current_price, required_raw, unit_cost * 2.0)
        else:
            raw_target = max(current_price, 129.99)

        final_price = snap_to_ending(min(raw_target, premium_ceiling))
        # High-ticket premium items are fully profitable and approved on Shop App
        return final_price, False, f"PREMIUM ({premium_reason})"

    # --- Everyday / Standard Fashion Path ---
    if unit_cost is not None and unit_cost > 0:
        vendor_payout = unit_cost + ESTIMATED_DROPSHIP_SHIPPING
        required_raw = (vendor_payout + SHOP_APP_CAC + PAYMENT_FIXED_FEE + TARGET_MIN_PROFIT) / (1.0 - SHOPIFY_CAPITAL_RATE - PAYMENT_GATEWAY_RATE)
        required_price = snap_to_ending(max(MIN_PRICE_FLOOR, required_raw))

        if required_price <= std_ceiling and unit_cost <= 55.0:
            # Safe, competitive, and profitable on Shop App
            final_price = snap_to_ending(max(required_price, current_price))
            return final_price, False, f"STANDARD ({category})"
        else:
            # Over ceiling: Cap at category ceiling to preserve customer conversion, exclude from Shop App
            capped_price = min(max(MIN_PRICE_FLOOR, current_price), std_ceiling)
            capped_price = snap_to_ending(capped_price)
            return capped_price, True, f"CAPPED & EXCLUDED (exceeds ${std_ceiling:.2f} ceiling)"
    else:
        # Fallback when unit cost is not provided
        if current_price < 40.0:
            raw = max(MIN_PRICE_FLOOR, current_price + 35.0)
        elif current_price < 65.0:
            raw = max(79.99, current_price + 25.0)
        elif current_price < 90.0:
            raw = max(94.99, current_price + 20.0)
        else:
            raw = current_price + 15.0

        target = snap_to_ending(raw)
        if target > std_ceiling:
            return std_ceiling, True, f"CAPPED & EXCLUDED (exceeds ${std_ceiling:.2f})"
        return target, False, f"STANDARD ({category})"


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
# Core Pricing Engine
# ---------------------------------------------------------------------------

def update_product_prices(products: List[Dict], batch_index: int = 0,
                          batch_size: int = 0,
                          skip_ids: Optional[set] = None,
                          dry_run: bool = False) -> Dict:
    """
    Process products list with Dual-Tier Premium & Standard Market Guardrails.
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
        "premium_count": 0,
        "errors": 0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "products": [],
    }

    mode_tag = " (DRY RUN)" if dry_run else ""
    col = f"{'#':<5} | {'Product':<32} | {'Tier / Classification':<24} | {'Old Price':>9} | {'New Price':>9} | Status{mode_tag}"
    print(f"\n{col}")
    print("-" * len(col))

    for i, product in enumerate(slice_, 1):
        title = product.get("title", "Unknown")[:30]
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
            print(f"{i:<5} | {title:<32} | {'—':<24} | {'—':>9} | {'—':>9} | NO PRICE")
            stats["skipped"] += len(variants)
            continue

        product_max_price = max(valid_prices)
        avg_cost = sum(valid_costs) / len(valid_costs) if valid_costs else None

        uniform_target, must_exclude, tier_label = calculate_optimal_price_and_eligibility(
            current_price=product_max_price,
            unit_cost=avg_cost,
            title=product.get("title", ""),
            vendor=vendor,
            product_type=product_type
        )

        if "PREMIUM" in tier_label:
            stats["premium_count"] += 1

        # Manage 'exclude-shop-app' tag
        if must_exclude:
            if "exclude-shop-app" not in product_tags:
                if not dry_run:
                    if set_product_tag(product_id, "exclude-shop-app", add=True):
                        stats["tagged_excluded"] += 1
                        _log.info("[ExcludeTag] Added 'exclude-shop-app' to %s (%s)", title, tier_label)
                else:
                    stats["tagged_excluded"] += 1
        else:
            if "exclude-shop-app" in product_tags:
                if not dry_run:
                    if set_product_tag(product_id, "exclude-shop-app", add=False):
                        _log.info("[ExcludeTag] Removed 'exclude-shop-app' from now profitable product %s (%s)", title, tier_label)

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
                new_compare_at = snap_to_ending(uniform_target + 20.0)
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
                print(f"{i:<5} | {title:<32} | {tier_label[:24]:<24} | ${item['old_price']:>8.2f} | ${item['price']:>8.2f} | {label}{ex_note}")
                entry = {
                    "sku": item["sku"], "title": title, "tier": tier_label, "variant_gid": item["id"],
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
            print(f"{i:<5} | {title:<32} | {tier_label[:24]:<24} | ${product_max_price:>8.2f} | ${uniform_target:>8.2f} | ALREADY OK{ex_note}")

    print("-" * len(col))
    print(f"\n[Done] {stats['updated']} updated, {stats['skipped']} skipped, {stats['premium_count']} premium identified, {stats['tagged_excluded']} tagged excluded, {stats['errors']} errors")
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
            "premium_identified": stats.get("premium_count", 0),
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

    print(f"[MeeeShop] Tiered Profit Margin & Premium Intelligence Engine (Floor: ${MIN_PRICE_FLOOR:.2f})")
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

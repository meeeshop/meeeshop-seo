"""
Dynamic pricing and margin protection engine for MeeeShop inventory.

Rules:
  - Protects store profits against Shop App CAC ($29.00), Shopify Capital repayment (10%),
    and payment processing fees (~2.9% + $0.30).
  - Guarantees minimum +$10.00 net profit per single-item order on Shop App.
  - Ensures uniform retail pricing across all standard sizes (XS - XXL) of a product.
  - Fixes inverted compare-at prices.
  - Automatically tags uncompetitively high-cost (> $75 wholesale) or low-ticket (< $45)
    products with 'exclude-shop-app' so they will not be published to the Shop App sales channel.
  - Automatically removes 'exclude-shop-app' if a product is safely profitable.
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
MAX_MARKET_CEILING = 159.99        # Maximum realistic price for standard boutique items before auto-excluding
API_DELAY_SECONDS = 0.4            # Delay between Shopify API calls to respect rate limits


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
    """
    Fetch active products filtered by creation date.

    daily              -> last 48 hours (or --window override)
    weekly             -> last 168 hours / 7 days (or --window override)
    force              -> all active products (no date filter)
    --window <hours>   -> override fetch window for daily/weekly
    """
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
# Pricing logic
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


def calculate_target_price(current_price: float, unit_cost: Optional[float] = None) -> float:
    """
    Tiered dynamic margin pricing engine:
    Protects store profits against Shop App CAC ($29.00), Shopify Capital (10%),
    and payment processing fees (~2.9% + $0.30).

    Formula:
      Net Revenue = Price * (1 - 0.10 - 0.029) - (VendorCost + $29.00 + $0.30)
      Net Revenue = 0.871 * Price - VendorCost - $29.30
    For Net Profit >= $10.00:
      0.871 * Price >= VendorCost + $39.30
      Price >= (VendorCost + $39.30) / 0.871

    Tiers (when unit_cost is known from inventory item):
      VendorCost = unit_cost + $7.50 dropshipping/handling
      Required Price = (VendorCost + $39.30) / 0.871
      Enforces MIN_PRICE_FLOOR ($74.99).

    Fallback (when unit_cost is not provided):
      - current_price < $40.00:  target = max(MIN_PRICE_FLOOR, current_price + $35.00)
      - current_price $40-$65:   target = max(79.99, current_price + $25.00)
      - current_price $65-$90:   target = max(94.99, current_price + $20.00)
      - current_price >= $90.00: target = current_price + $15.00
    """
    if unit_cost is not None and unit_cost > 0:
        vendor_payout = unit_cost + ESTIMATED_DROPSHIP_SHIPPING
        required_raw = (vendor_payout + SHOP_APP_CAC + PAYMENT_FIXED_FEE + TARGET_MIN_PROFIT) / (1.0 - SHOPIFY_CAPITAL_RATE - PAYMENT_GATEWAY_RATE)
        raw_price = max(MIN_PRICE_FLOOR, required_raw)
    else:
        if current_price < 40.0:
            raw_price = max(MIN_PRICE_FLOOR, current_price + 35.0)
        elif current_price < 65.0:
            raw_price = max(79.99, current_price + 25.0)
        elif current_price < 90.0:
            raw_price = max(94.99, current_price + 20.0)
        else:
            raw_price = current_price + 15.0

    target = snap_to_ending(raw_price)
    return max(MIN_PRICE_FLOOR, target)


def should_exclude_from_shop_app(
    target_price: float,
    unit_cost: Optional[float] = None,
    current_price: float = 0.0,
    product_type: str = ""
) -> bool:
    """
    Determine whether a product should be tagged 'exclude-shop-app'.
    Products excluded:
      1. Vendor wholesale cost is too high (unit_cost > $75.0) such that retail price would exceed market ceiling.
      2. Required target price exceeds MAX_MARKET_CEILING ($159.99).
      3. Low-ticket items (original MSRP < $45) that are small accessories/tees/socks/jewelry where pushing
         to $74.99+ is unreasonable.
    """
    if unit_cost is not None and unit_cost > 75.0:
        return True
    if target_price > MAX_MARKET_CEILING:
        return True
    pt_lower = (product_type or "").lower()
    if 0 < current_price < 45.0 and any(k in pt_lower for k in ['accessory', 'socks', 'jewelry', 'hat', 'belt', 'tee', 'cami']):
        return True
    return False


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
    Process products list with tiered margin pricing and Shop App channel exclusion.

    Enforces uniform variant pricing across all sizes of a product.
    Fixes inverted compare-at prices.
    Auto-tags uncompetitive products with 'exclude-shop-app'.
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
    col = f"{'#':<5} | {'Product':<36} | {'Old Price':>10} | {'New Price':>10} | Status{mode_tag}"
    print(f"\n{col}")
    print("-" * len(col))

    for i, product in enumerate(slice_, 1):
        title = product.get("title", "Unknown")[:33]
        product_id = product.get("id")
        product_tags = product.get("tags", [])
        product_type = product.get("product_type", "")
        vendor = product.get("vendor", "")

        variants = product.get("variants", [])
        if not variants:
            continue

        # Extract costs and prices across variants
        valid_prices = [v["price"] for v in variants if v.get("price", 0) > 0]
        valid_costs = [v["unit_cost"] for v in variants if v.get("unit_cost") is not None and v["unit_cost"] > 0]

        if not valid_prices:
            print(f"{i:<5} | {title:<36} | {'—':>10} | {'—':>10} | NO PRICE")
            stats["skipped"] += len(variants)
            continue

        product_max_price = max(valid_prices)
        avg_cost = sum(valid_costs) / len(valid_costs) if valid_costs else None

        # Determine uniform target retail price for the product
        uniform_target = calculate_target_price(product_max_price, avg_cost)
        # Protect against lowering existing luxury or higher-priced variants
        uniform_target = max(uniform_target, product_max_price)
        if not is_valid_ending(uniform_target):
            uniform_target = snap_to_ending(uniform_target)

        # Check whether this product should be excluded from Shop App
        must_exclude = should_exclude_from_shop_app(
            target_price=uniform_target,
            unit_cost=avg_cost,
            current_price=product_max_price,
            product_type=product_type
        )

        # Manage 'exclude-shop-app' tag
        if must_exclude:
            if "exclude-shop-app" not in product_tags:
                if not dry_run:
                    if set_product_tag(product_id, "exclude-shop-app", add=True):
                        stats["tagged_excluded"] += 1
                        _log.info("[ExcludeTag] Added 'exclude-shop-app' to %s", title)
                else:
                    stats["tagged_excluded"] += 1
                    _log.info("[DryRun] Would add 'exclude-shop-app' to %s", title)
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

            # Skip variants recently processed in previous runs
            if variant_id in skip_ids:
                stats["skipped"] += 1
                continue

            needs_price_change = abs(current_price - uniform_target) >= 0.01

            # Inversion check: compare_at must be higher than selling price if present
            needs_compare_at_change = False
            new_compare_at = compare_at
            if compare_at is not None and compare_at <= uniform_target:
                # Set compare-at to reasonable markup or remove inversion
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
                label = "DRY RUN (WOULD UPDATE)"
            else:
                success = bulk_update_variants(product_id, to_update)
                label = "UPDATED" if success else "ERROR"
                time.sleep(API_DELAY_SECONDS)

            for item in to_update:
                print(f"{i:<5} | {title:<36} | ${item['old_price']:>9.2f} | ${item['price']:>9.2f} | {label}")
                entry = {
                    "sku": item["sku"], "title": title, "variant_gid": item["id"],
                    "old_price": item["old_price"], "new_price": item["price"],
                    "status": "would_update" if dry_run else ("updated" if success else "error"),
                }
                if success:
                    stats["updated"] += 1
                else:
                    stats["errors"] += 1
                stats["products"].append(entry)
        else:
            print(f"{i:<5} | {title:<36} | ${product_max_price:>9.2f} | ${uniform_target:>9.2f} | ALREADY OK")

    print("-" * len(col))
    print(f"\n[Done] {stats['updated']} updated, {stats['skipped']} skipped, {stats['tagged_excluded']} tagged excluded, {stats['errors']} errors")
    return stats


# ---------------------------------------------------------------------------
# Log helpers
# ---------------------------------------------------------------------------

def load_recently_updated_ids(filepath: str = "price_update_log.json",
                              within_hours: Optional[int] = None) -> set:
    """Return set of variant IDs updated in recent runs."""
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
    p = argparse.ArgumentParser(description="MeeeShop dynamic pricing and margin protection engine")
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

    print(f"[MeeeShop] Tiered Profit Margin & Shop App Protection Engine (Floor: ${MIN_PRICE_FLOOR:.2f})")
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

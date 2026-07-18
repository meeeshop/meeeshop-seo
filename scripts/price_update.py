"""
Dynamic pricing engine for MeeeShop inventory.

Rules:
  - Take current MSRP (selling price) from Shopify
  - Add $20.00 to every variant
  - Snap to nearest x4.99 or x9.99 ending
      e.g. $71.99 + $20 = $91.99 -> $94.99
           $76.99 + $20 = $96.99 -> $99.99
           $45.00 + $20 = $65.00 -> $69.99
  - Skip variants already at the correct target price

Modes:
  daily  -- products created in the last 48 hours (default)
  weekly -- products created in the last 7 days
  force  -- ALL active products, supports --batch-size / --batch-index
            for splitting across multiple GitHub Actions jobs

Usage:
  python price_update.py --mode daily
  python price_update.py --mode weekly
  python price_update.py --mode force --batch-size 200 --batch-index 0
  python price_update.py --mode force --batch-size 200 --batch-index 1
"""

import os
import sys
import json
import time
import argparse
import requests
from pathlib import Path
from typing import Optional, Dict, List
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

API_VERSION = "2025-01"
PRICE_MARKUP = 20.00
# Shopify REST API allows ~2 req/s on standard plans; stay well under to avoid 429s
API_DELAY_SECONDS = 0.6


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
        createdAt
        variants(first: 100) {
          edges {
            node { id sku price }
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
                    "created_at": node.get("createdAt"),
                    "variants": [],
                }
                for var_edge in node.get("variants", {}).get("edges", []):
                    v = var_edge.get("node", {})
                    product["variants"].append({
                        "id": v.get("id"),
                        "sku": v.get("sku", ""),
                        "price": float(v.get("price") or 0),
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

def calculate_target_price(current_price: float) -> float:
    """
    Add $20 to current MSRP, then snap up to the nearest x4.99 or x9.99.

    The rule: valid endings are ...4.99 and ...9.99 (ones digit 4 or 9).
    We always round UP so we never under-price.

    Examples:
      $71.99 + $20 = $91.99 -> $94.99
      $76.99 + $20 = $96.99 -> $99.99
      $45.00 + $20 = $65.00 -> $69.99  (65.00 is not a valid ending, go up)
      $34.99 + $20 = $54.99 -> $54.99  (already valid, keep)
      $14.99 + $20 = $34.99 -> $39.99
    """
    raw = round(current_price + PRICE_MARKUP, 2)
    base = int(raw)

    # Collect all valid x4.99 / x9.99 candidates in a tight window above base
    candidates = []
    for b in range(base - 1, base + 11):
        if b % 10 in (4, 9):
            candidates.append(round(b + 0.99, 2))

    # Pick the smallest candidate that is >= raw (round up, never down)
    above = [c for c in candidates if c >= raw]
    if above:
        return above[0]
    return candidates[-1]


def is_already_correct(price: float) -> bool:
    """Return True if price is already a valid x4.99 or x9.99 value."""
    cents = round(price % 10, 2)
    return cents in (4.99, 9.99)


# ---------------------------------------------------------------------------
# Price update
# ---------------------------------------------------------------------------

def bulk_update_variants(product_id: str, variant_updates: List[Dict]) -> bool:
    """Update multiple variant prices for a product in bulk via GraphQL."""
    query = """
    mutation productVariantsBulkUpdate($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
      productVariantsBulkUpdate(productId: $productId, variants: $variants) {
        product { id }
        productVariants { id price }
        userErrors { field message }
      }
    }
    """
    variables = {
        "productId": product_id,
        "variants": [
            {"id": vu["id"], "price": f"{vu['price']:.2f}"}
            for vu in variant_updates
        ]
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


def update_product_prices(products: List[Dict], batch_index: int = 0,
                          batch_size: int = 0,
                          skip_ids: Optional[set] = None) -> Dict:
    """
    Process products list.

    When batch_size > 0, only process the slice [batch_index*batch_size :
    (batch_index+1)*batch_size] — used by force mode to split work across jobs.
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
        "errors": 0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "products": [],
    }

    col = f"{'#':<5} | {'Product':<36} | {'Old Price':>10} | {'New Price':>10} | Status"
    print(f"\n{col}")
    print("-" * len(col))

    for i, product in enumerate(slice_, 1):
        title = product.get("title", "Unknown")[:33]
        product_id = product.get("id")

        to_update = []
        for variant in product.get("variants", []):
            variant_id = variant.get("id", "")
            sku = variant.get("sku", "N/A")
            current_price = float(variant.get("price", 0))

            if current_price <= 0:
                print(f"{i:<5} | {title:<36} | {'—':>10} | {'—':>10} | NO PRICE")
                stats["skipped"] += 1
                stats["products"].append({"sku": sku, "title": title, "status": "skipped_no_price"})
                continue

            # Skip variants updated in a recent prior run (within 23h)
            if variant_id in skip_ids:
                print(f"{i:<5} | {title:<36} | ${current_price:>9.2f} | {'—':>10} | SKIP (recent)")
                stats["skipped"] += 1
                stats["products"].append({
                    "sku": sku, "title": title, "variant_gid": variant_id,
                    "old_price": current_price, "status": "skipped_recent_run",
                })
                continue

            new_price = calculate_target_price(current_price)

            # Already correct: current price is already a valid x4.99/x9.99 AND equals new_price
            if abs(current_price - new_price) < 0.01:
                print(f"{i:<5} | {title:<36} | ${current_price:>9.2f} | ${new_price:>9.2f} | ALREADY OK")
                stats["skipped"] += 1
                stats["products"].append({
                    "sku": sku, "title": title, "variant_gid": variant_id,
                    "old_price": current_price, "new_price": new_price,
                    "status": "skipped_optimal",
                })
                continue

            to_update.append({
                "id": variant_id,
                "price": new_price,
                "sku": sku,
                "old_price": current_price
            })

        if to_update:
            success = bulk_update_variants(product_id, to_update)
            label = "UPDATED" if success else "ERROR"

            for item in to_update:
                print(f"{i:<5} | {title:<36} | ${item['old_price']:>9.2f} | ${item['price']:>9.2f} | {label}")
                entry = {
                    "sku": item["sku"], "title": title, "variant_gid": item["id"],
                    "old_price": item["old_price"], "new_price": item["price"],
                    "status": "updated" if success else "error",
                }
                if success:
                    stats["updated"] += 1
                else:
                    stats["errors"] += 1
                stats["products"].append(entry)

    print("-" * len(col))
    print(f"\n[Done] {stats['updated']} updated, {stats['skipped']} skipped, {stats['errors']} errors")
    return stats


# ---------------------------------------------------------------------------
# Log helpers
# ---------------------------------------------------------------------------

def load_recently_updated_ids(filepath: str = "price_update_log.json",
                              within_hours: Optional[int] = None) -> set:
    """
    Return a set of variant IDs (GID strings) that were successfully updated.
    If within_hours is provided, only retrieves those updated within the last
    `within_hours` hours. Otherwise, retrieves ALL previously updated variant IDs.
    
    This function searches recursively for all `price_update_log.json` files in the
    workspace to merge logs from previous runs and matrix batch runs.
    """
    log_files = []
    # If the root/specified filepath exists, add it
    if os.path.exists(filepath):
        log_files.append(Path(filepath))

    # Search current directory and all subdirectories for other price_update_log.json files
    # to support downloaded logs from previous matrix jobs
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

    # Search and merge entries from other price_update_log.json files
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

    # Sort logs chronologically by timestamp
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
    p = argparse.ArgumentParser(description="MeeeShop price update engine")
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
        help="Override the fetch window in hours (e.g. --window 12 fetches products created in last 12h). "
             "Only applies to daily/weekly modes. Next daily run will skip these via log.",
    )
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()

    print(f"[MeeeShop] Price Update Engine — MSRP +${PRICE_MARKUP:.2f} -> x4.99/x9.99")
    print(f"Store  : {SHOPIFY_STORE}")
    print(f"Mode   : {args.mode}")
    if args.window is not None:
        print(f"Window : last {args.window}h (manual override)")
    if args.batch_size > 0:
        print(f"Batch  : index={args.batch_index}, size={args.batch_size}")
    print()

    try:
        products = get_products(mode=args.mode, window_hours=args.window)
        print(f"[Fetch] Total products matching filter: {len(products)}\n")

        if not products:
            print("[Done] No products to process.")
            sys.exit(0)

        # Skip variants already updated in any previous run (unless force mode is used)
        skip_ids = set()
        if args.mode != "force":
            skip_ids = load_recently_updated_ids()
            if skip_ids:
                print(f"[Skip] {len(skip_ids)} variant(s) already updated in previous runs — will skip\n")

        stats = update_product_prices(
            products,
            batch_index=args.batch_index,
            batch_size=args.batch_size,
            skip_ids=skip_ids,
        )
        save_update_log(stats)

    except KeyboardInterrupt:
        print("\n[Cancelled] Interrupted by user")
        sys.exit(1)
    except Exception as e:
        _log.exception("[Fatal] %s", e)
        sys.exit(1)

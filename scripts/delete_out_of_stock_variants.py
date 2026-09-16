#!/usr/bin/env python3
"""
delete_out_of_stock_variants.py

Automated script to:
1. Delete products whose combined in-stock inventory across all variants is less than the threshold (default: 10).
   This includes products where all variants have 0 or negative inventory.
2. For products with combined inventory >= threshold:
   Delete individual variants that have 0 or negative inventory (inventoryQuantity <= 0),
   ensuring customers cannot place orders for out-of-stock variants while keeping in-stock variants available.

Logging & Audit:
- Logs every deleted product and variant to stdout with full identifiers (Title, Vendor, SKU, Price, Qty, IDs).
- Updates deleted_inventory_history.json with complete metadata for every deleted product and variant for future review/recovery.
- Produces timestamped run reports in logs/delete_out_of_stock_YYYYMMDD_HHMMSS.json and logs/delete_out_of_stock_latest.json.

Targeting & Flexibility:
- Supports scanning all products (default), or targeting a single product via --handle or --product-id for fast testing.
- Supports --dry-run to simulate without making changes.
- Uses Double-Fernet encryption via secrets_manager.py and secrets.enc.
"""

import argparse
import datetime
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Ensure scripts/ directory is in sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

# Import existing secrets manager
try:
    from secrets_manager import get_secret, inject_to_env
    inject_to_env()
except ImportError as e:
    print(f"ERROR: Could not import secrets_manager: {e}", file=sys.stderr)
    sys.exit(1)

# Configure logging
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger("delete_out_of_stock")

# Persistent history tracking file
HISTORY_FILE = REPO_ROOT / "deleted_inventory_history.json"

# Primary store fulfillment location (where non-Collective / store wholesale products are stocked)
STORE_PRIMARY_LOCATION_ID = "85751005355"

# Known Shopify Collective Suppliers
# Products from these suppliers automatically sync with supplier catalogs.
# Deleting individual 0-stock variants causes Collective to recreate them in Admin.
# We skip variant deletion for these suppliers to conserve API limits and runner minutes.
COLLECTIVE_VENDORS = {
    "RETROLICIOUS",
    "ALYTH ACTIVE",
    "ARTEMIS VINTAGE",
    "ATHINA RETAIL",
    "BOHO CLOTHING AND ACCESSORIES",
    "BOTORI EQUESTRIAN",
    "BUKI",
    "COTTONWAYS",
    "DIZZY-LIZZIE",
    "DOWNEAST",
    "ELLISONYOUNG.COM",
    "FLYING TOMATO",
    "GLEE + CO",
    "GOAL FIVE",
    "HELLODAY.US",
    "INDIE & CO.",
    "LUCKY FEET SHOES",
    "MADELINE LOVE",
    "MISSFINCHNYC",
    "ORANGE FARM CLOTHING",
    "PRETTY SIMPLE",
    "TROPHY YOGA",
    "VAILA SHOES",
    "YMI JEANS",
}


def is_shopify_collective_product(
    vendor: str,
    variants: Optional[List[Dict[str, Any]]] = None,
    extra_collective_vendors: Optional[set] = None,
) -> Tuple[bool, str]:
    """
    Determines if a product originates from a Shopify Collective supplier.
    
    Collective products automatically synchronize with the supplier's price list / catalog.
    If individual 0-stock variants are deleted via API, Collective automatically restores them
    within seconds. Skipping individual variant deletion for Collective suppliers avoids
    burning API rate limits and execution time (while the storefront theme rule hides them).
    
    Returns:
        (is_collective, reason)
    """
    v_clean = (vendor or "").strip().upper()
    
    # 1. Check known / configured Collective vendor list
    all_collective = set(COLLECTIVE_VENDORS)
    if extra_collective_vendors:
        all_collective.update(ev.strip().upper() for ev in extra_collective_vendors if ev.strip())
        
    if v_clean in all_collective:
        return True, f"Vendor '{vendor}' is a known Shopify Collective supplier"
        
    for cv in all_collective:
        if cv in v_clean or v_clean in cv:
            return True, f"Vendor '{vendor}' matches Shopify Collective supplier '{cv}'"

    # 2. Check variant inventory location (Collective suppliers have dedicated fulfillment locations)
    if variants:
        for v in variants:
            levels = (
                v.get("inventoryItem", {})
                .get("inventoryLevels", {})
                .get("edges", [])
            )
            for lvl in levels:
                loc_id = lvl.get("node", {}).get("location", {}).get("id", "").split("/")[-1]
                # If location is not the store primary location and not Trendsi app
                if loc_id and loc_id not in (STORE_PRIMARY_LOCATION_ID, "65746272427", "85754413227"):
                    return True, f"Variant stocked at dedicated Collective supplier location ({loc_id})"

    return False, "Standard / non-Collective supplier"


# GraphQL Queries & Mutations
QUERY_PRODUCTS = """
query GetProducts($first: Int!, $after: String) {
  products(first: $first, after: $after) {
    pageInfo {
      hasNextPage
      endCursor
    }
    edges {
      node {
        id
        title
        handle
        vendor
        status
        totalInventory
        variants(first: 100) {
          edges {
            node {
              id
              title
              sku
              price
              barcode
              inventoryQuantity
              inventoryItem {
                inventoryLevels(first: 2) {
                  edges {
                    node {
                      location {
                        id
                      }
                    }
                  }
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

QUERY_PRODUCT_BY_HANDLE = """
query GetProductByHandle($handle: String!) {
  productByHandle(handle: $handle) {
    id
    title
    handle
    vendor
    status
    totalInventory
    variants(first: 100) {
      edges {
        node {
          id
          title
          sku
          price
          barcode
          inventoryQuantity
          inventoryItem {
            inventoryLevels(first: 2) {
              edges {
                node {
                  location {
                    id
                  }
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

QUERY_PRODUCT_BY_ID = """
query GetProductById($id: ID!) {
  product(id: $id) {
    id
    title
    handle
    vendor
    status
    totalInventory
    variants(first: 100) {
      edges {
        node {
          id
          title
          sku
          price
          barcode
          inventoryQuantity
          inventoryItem {
            inventoryLevels(first: 2) {
              edges {
                node {
                  location {
                    id
                  }
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

MUTATION_DELETE_PRODUCT = """
mutation ProductDelete($input: ProductDeleteInput!) {
  productDelete(input: $input) {
    deletedProductId
    userErrors {
      field
      message
    }
  }
}
"""

MUTATION_DELETE_VARIANTS = """
mutation ProductVariantsBulkDelete($productId: ID!, $variantsIds: [ID!]!) {
  productVariantsBulkDelete(productId: $productId, variantsIds: $variantsIds) {
    product {
      id
    }
    userErrors {
      field
      message
    }
  }
}
"""


class ShopifyGraphQLClient:
    """GraphQL client with rate-limiting, cost management, and exponential backoff."""

    def __init__(self, store: str, token: str, api_version: str = "2024-01"):
        clean_store = store.replace("https://", "").replace("http://", "").rstrip("/")
        self.store = clean_store
        self.endpoint = f"https://{clean_store}/admin/api/{api_version}/graphql.json"
        self.headers = {
            "X-Shopify-Access-Token": token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        import requests
        self.session = requests.Session()

    def execute(self, query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables

        max_attempts = 6
        for attempt in range(1, max_attempts + 1):
            try:
                response = self.session.post(
                    self.endpoint,
                    headers=self.headers,
                    json=payload,
                    timeout=45,
                )

                # Handle HTTP 429 Too Many Requests
                if response.status_code == 429:
                    retry_after = float(response.headers.get("Retry-After", 2.0 * attempt))
                    logger.warning(f"Rate limited (HTTP 429). Waiting {retry_after:.1f}s (attempt {attempt}/{max_attempts})...")
                    time.sleep(retry_after)
                    continue

                response.raise_for_status()
                data = response.json()

                # Handle GraphQL-level throttling and cost tracking
                extensions = data.get("extensions", {})
                cost = extensions.get("cost", {})
                throttle_status = cost.get("throttleStatus", {})
                currently_available = throttle_status.get("currentlyAvailable")
                restore_rate = throttle_status.get("restoreRate", 100.0)

                if currently_available is not None and currently_available < 150:
                    needed = 250 - currently_available
                    sleep_time = max(0.5, needed / max(1.0, restore_rate))
                    logger.debug(f"API budget low ({currently_available:.0f} pts). Sleeping {sleep_time:.2f}s...")
                    time.sleep(sleep_time)

                if "errors" in data and not data.get("data"):
                    logger.error(f"GraphQL top-level errors: {data['errors']}")
                    if attempt < max_attempts:
                        time.sleep(1.5 * attempt)
                        continue

                return data

            except Exception as exc:
                if attempt == max_attempts:
                    logger.error(f"GraphQL request failed after {max_attempts} attempts: {exc}")
                    raise
                wait_seconds = 1.5 ** attempt
                logger.warning(f"Network error: {exc}. Retrying in {wait_seconds:.1f}s...")
                time.sleep(wait_seconds)

        raise RuntimeError("Failed to execute GraphQL query after maximum retries")


def load_history() -> Dict[str, Any]:
    """Load persistent deletion history from disk."""
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    data.setdefault("deleted_products", {})
                    data.setdefault("deleted_variants", {})
                    return data
        except Exception as e:
            logger.warning(f"Could not read {HISTORY_FILE}: {e}")
    return {"deleted_products": {}, "deleted_variants": {}}


def save_history(history: Dict[str, Any]) -> None:
    """Save persistent deletion history to disk."""
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save {HISTORY_FILE}: {e}")


def process_single_product(
    node: Dict[str, Any],
    client: ShopifyGraphQLClient,
    stats: Dict[str, Any],
    history: Dict[str, Any],
    min_combined_inventory: int,
    dry_run: bool,
    iso_timestamp: str,
    skip_collective_variants: bool = True,
    extra_collective_vendors: Optional[set] = None,
) -> int:
    """Process a single product node, applying inventory rules."""
    new_entries = 0
    product_id = node.get("id")
    title = node.get("title", "Untitled")
    handle = node.get("handle", "")
    vendor = node.get("vendor", "")

    variant_edges = node.get("variants", {}).get("edges", [])
    variants = [v["node"] for v in variant_edges]

    # Calculate combined in-stock inventory (sum of positive stock across all variants)
    combined_stock = sum(max(0, v.get("inventoryQuantity") or 0) for v in variants)
    total_variants_count = len(variants)

    # Identify out-of-stock variants
    out_of_stock_variants = [
        v for v in variants if (v.get("inventoryQuantity") or 0) <= 0
    ]
    out_of_stock_ids = [v["id"] for v in out_of_stock_variants]

    # Case 1: Combined inventory is less than threshold (e.g. < 10) OR all variants 0
    # Rule applies to ALL products (standard and Collective). Collective does NOT recreate deleted products.
    if combined_stock < min_combined_inventory:
        action_tag = "[SIMULATED PRODUCT DELETE]" if dry_run else "[PRODUCT DELETED]"
        logger.info(
            f"🗑️  {action_tag} '{title}' ({handle}) | Vendor: {vendor} | ID: {product_id} | "
            f"Stock: {combined_stock} (< {min_combined_inventory}) | Variants: {total_variants_count}"
        )

        prod_record = {
            "deleted_at": iso_timestamp,
            "dry_run": dry_run,
            "product_id": product_id,
            "title": title,
            "handle": handle,
            "vendor": vendor,
            "combined_stock": combined_stock,
            "variants_count": total_variants_count,
            "reason": f"Combined inventory ({combined_stock}) < threshold ({min_combined_inventory})",
            "variants": [
                {
                    "id": v["id"],
                    "title": v.get("title"),
                    "sku": v.get("sku"),
                    "price": v.get("price"),
                    "barcode": v.get("barcode"),
                    "inventoryQuantity": v.get("inventoryQuantity"),
                }
                for v in variants
            ],
        }
        stats["products_deleted_count"] += 1
        stats["deleted_products"].append(prod_record)

        if not dry_run:
            history["deleted_products"][product_id] = prod_record
            new_entries += 1
            try:
                del_res = client.execute(MUTATION_DELETE_PRODUCT, {"input": {"id": product_id}})
                user_errors = del_res.get("data", {}).get("productDelete", {}).get("userErrors", [])
                if user_errors:
                    err_msg = f"Failed to delete product {product_id}: {user_errors}"
                    logger.error(err_msg)
                    stats["errors_count"] += 1
                    stats["errors"].append(err_msg)
            except Exception as e:
                err_msg = f"Exception deleting product {product_id}: {e}"
                logger.error(err_msg)
                stats["errors_count"] += 1
                stats["errors"].append(err_msg)

    # Case 2: Combined inventory >= threshold, but some variants are out of stock
    elif out_of_stock_ids:
        # Check if product is from a Shopify Collective supplier
        is_collective, collective_reason = is_shopify_collective_product(
            vendor=vendor,
            variants=variants,
            extra_collective_vendors=extra_collective_vendors,
        )

        # Skip deleting individual variants for Collective products to conserve API limits & runner minutes
        if is_collective and skip_collective_variants:
            logger.info(
                f"🛡️  [COLLECTIVE SKIP] '{title}' ({handle}) | Vendor: {vendor} | Stock: {combined_stock} >= {min_combined_inventory} | "
                f"{len(out_of_stock_ids)}/{total_variants_count} variants out of stock. "
                f"Skipping variant deletion to save API limits & runner minutes ({collective_reason}). Storefront theme hides them."
            )
            stats["collective_products_skipped_count"] += 1
            stats["collective_skipped_products"].append({
                "product_id": product_id,
                "title": title,
                "handle": handle,
                "vendor": vendor,
                "combined_stock": combined_stock,
                "out_of_stock_variants_count": len(out_of_stock_ids),
                "reason": collective_reason,
            })
            return 0

        action_tag = "[SIMULATED VARIANT DELETE]" if dry_run else "[VARIANT DELETED]"
        logger.info(
            f"✂️  {action_tag} '{title}' ({handle}) | Vendor: {vendor} | Stock: {combined_stock} >= {min_combined_inventory} | "
            f"Deleting {len(out_of_stock_ids)}/{total_variants_count} out-of-stock variants"
        )

        deleted_var_details = []
        for v in out_of_stock_variants:
            var_detail = {
                "deleted_at": iso_timestamp,
                "dry_run": dry_run,
                "product_id": product_id,
                "product_title": title,
                "product_handle": handle,
                "vendor": vendor,
                "variant_id": v["id"],
                "variant_title": v.get("title"),
                "sku": v.get("sku"),
                "price": v.get("price"),
                "barcode": v.get("barcode"),
                "inventoryQuantity": v.get("inventoryQuantity"),
                "reason": "Variant out of stock (inventory <= 0) on in-stock product",
            }
            deleted_var_details.append(var_detail)
            logger.info(
                f"   ↳ {action_tag} Variant: '{v.get('title')}' | SKU: {v.get('sku') or 'N/A'} | "
                f"Qty: {v.get('inventoryQuantity')} | Price: ${v.get('price')} | ID: {v['id']}"
            )

            if not dry_run:
                history["deleted_variants"][v["id"]] = var_detail
                new_entries += 1

        stats["variants_deleted_count"] += len(out_of_stock_ids)
        stats["products_variants_cleaned_count"] += 1
        stats["cleaned_products"].append({
            "product_id": product_id,
            "title": title,
            "handle": handle,
            "vendor": vendor,
            "combined_stock": combined_stock,
            "deleted_variants": deleted_var_details,
        })

        if not dry_run:
            try:
                # Delete in chunks of 250 (Shopify max per mutation)
                for i in range(0, len(out_of_stock_ids), 250):
                    chunk_ids = out_of_stock_ids[i:i + 250]
                    del_var_res = client.execute(
                        MUTATION_DELETE_VARIANTS,
                        {"productId": product_id, "variantsIds": chunk_ids},
                    )
                    user_errors = (
                        del_var_res.get("data", {})
                        .get("productVariantsBulkDelete", {})
                        .get("userErrors", [])
                    )
                    if user_errors:
                        err_msg = f"Failed to delete variants on product {product_id}: {user_errors}"
                        logger.error(err_msg)
                        stats["errors_count"] += 1
                        stats["errors"].append(err_msg)
            except Exception as e:
                err_msg = f"Exception deleting variants for {product_id}: {e}"
                logger.error(err_msg)
                stats["errors_count"] += 1
                stats["errors"].append(err_msg)

    # Case 3: Fully in-stock and >= threshold
    else:
        stats["products_kept_untouched_count"] += 1

    return new_entries


def run_inventory_cleanup(
    client: ShopifyGraphQLClient,
    min_combined_inventory: int = 10,
    dry_run: bool = False,
    limit: Optional[int] = None,
    handle: Optional[str] = None,
    product_id: Optional[str] = None,
    log_dir: Optional[Path] = None,
    skip_collective_variants: bool = True,
    extra_collective_vendors: Optional[set] = None,
) -> Dict[str, Any]:
    """
    Main cleanup engine:
    1. Fetches products (either single targeted product, or paginated scan).
    2. Deletes products if combined in-stock inventory < min_combined_inventory (all suppliers, including Collective).
    3. For products with combined inventory >= threshold:
       - Skips variant deletion for Shopify Collective products to conserve API limits and runner minutes.
       - Deletes 0-inventory variants for standard / non-Collective products.
    4. Logs all deleted items and updates persistent history.
    """
    if log_dir is None:
        log_dir = REPO_ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    start_time = datetime.datetime.now(datetime.timezone.utc)
    timestamp_str = start_time.strftime("%Y%m%d_%H%M%S")
    iso_timestamp = start_time.isoformat()

    history = load_history()
    new_history_entries = 0

    stats = {
        "start_time": iso_timestamp,
        "dry_run": dry_run,
        "min_combined_inventory": min_combined_inventory,
        "skip_collective_variants": skip_collective_variants,
        "targeted_handle": handle,
        "targeted_product_id": product_id,
        "total_products_scanned": 0,
        "products_deleted_count": 0,
        "variants_deleted_count": 0,
        "collective_products_skipped_count": 0,
        "products_kept_untouched_count": 0,
        "products_variants_cleaned_count": 0,
        "errors_count": 0,
        "deleted_products": [],
        "cleaned_products": [],
        "collective_skipped_products": [],
        "errors": [],
    }

    mode_label = "DRY-RUN (SIMULATION - NO DELETIONS)" if dry_run else "LIVE EXECUTION (PERMANENT DELETIONS)"
    logger.info("=" * 70)
    logger.info(f"STARTING OUT-OF-STOCK CLEANUP | Mode: {mode_label}")
    logger.info(f"Threshold: Delete products if combined inventory < {min_combined_inventory}")
    logger.info(f"Skip Collective Variants: {skip_collective_variants} (conserve API limits & minutes)")
    if handle:
        logger.info(f"Targeting single product by handle: {handle}")
    elif product_id:
        logger.info(f"Targeting single product by ID: {product_id}")
    logger.info("=" * 70)

    try:
        # Option A: Single product targeting by handle
        if handle:
            res = client.execute(QUERY_PRODUCT_BY_HANDLE, {"handle": handle})
            prod_node = res.get("data", {}).get("productByHandle")
            if not prod_node:
                logger.error(f"Product with handle '{handle}' not found.")
                stats["errors"].append(f"Handle '{handle}' not found")
                stats["errors_count"] += 1
            else:
                stats["total_products_scanned"] += 1
                new_history_entries += process_single_product(
                    node=prod_node,
                    client=client,
                    stats=stats,
                    history=history,
                    min_combined_inventory=min_combined_inventory,
                    dry_run=dry_run,
                    iso_timestamp=iso_timestamp,
                    skip_collective_variants=skip_collective_variants,
                    extra_collective_vendors=extra_collective_vendors,
                )

        # Option B: Single product targeting by ID
        elif product_id:
            formatted_id = product_id if product_id.startswith("gid://") else f"gid://shopify/Product/{product_id}"
            res = client.execute(QUERY_PRODUCT_BY_ID, {"id": formatted_id})
            prod_node = res.get("data", {}).get("product")
            if not prod_node:
                logger.error(f"Product with ID '{product_id}' not found.")
                stats["errors"].append(f"Product ID '{product_id}' not found")
                stats["errors_count"] += 1
            else:
                stats["total_products_scanned"] += 1
                new_history_entries += process_single_product(
                    node=prod_node,
                    client=client,
                    stats=stats,
                    history=history,
                    min_combined_inventory=min_combined_inventory,
                    dry_run=dry_run,
                    iso_timestamp=iso_timestamp,
                    skip_collective_variants=skip_collective_variants,
                    extra_collective_vendors=extra_collective_vendors,
                )

        # Option C: Storewide paginated scan
        else:
            after_cursor: Optional[str] = None
            processed_count = 0
            batch_size = 100

            while True:
                fetch_size = batch_size
                if limit is not None:
                    remaining = limit - processed_count
                    if remaining <= 0:
                        break
                    fetch_size = min(batch_size, remaining)

                variables: Dict[str, Any] = {"first": fetch_size, "after": after_cursor}
                result = client.execute(QUERY_PRODUCTS, variables)

                products_data = result.get("data", {}).get("products", {})
                edges = products_data.get("edges", [])
                page_info = products_data.get("pageInfo", {})

                if not edges:
                    break

                for edge in edges:
                    processed_count += 1
                    stats["total_products_scanned"] += 1
                    node = edge.get("node", {})
                    new_history_entries += process_single_product(
                        node=node,
                        client=client,
                        stats=stats,
                        history=history,
                        min_combined_inventory=min_combined_inventory,
                        dry_run=dry_run,
                        iso_timestamp=iso_timestamp,
                        skip_collective_variants=skip_collective_variants,
                        extra_collective_vendors=extra_collective_vendors,
                    )

                    if limit is not None and processed_count >= limit:
                        break

                if not page_info.get("hasNextPage"):
                    break
                after_cursor = page_info.get("endCursor")

                if stats["total_products_scanned"] % 500 == 0:
                    logger.info(
                        f"Progress: {stats['total_products_scanned']} products scanned | "
                        f"Products to delete: {stats['products_deleted_count']} | "
                        f"Variants to delete: {stats['variants_deleted_count']} | "
                        f"Collective skipped: {stats['collective_products_skipped_count']}"
                    )

    except KeyboardInterrupt:
        logger.warning("Execution interrupted by user.")
    except Exception as exc:
        logger.exception(f"Unexpected error during inventory cleanup: {exc}")
        stats["errors"].append(str(exc))
        stats["errors_count"] += 1

    end_time = datetime.datetime.now(datetime.timezone.utc)
    stats["end_time"] = end_time.isoformat()
    stats["duration_seconds"] = round((end_time - start_time).total_seconds(), 2)

    # If live changes were made, write updated history to disk
    if not dry_run and new_history_entries > 0:
        save_history(history)
        logger.info(f"✅ Updated persistent deletion history: {HISTORY_FILE} ({new_history_entries} new records)")

    # Save detailed JSON run logs
    timestamped_log = log_dir / f"delete_out_of_stock_{timestamp_str}.json"
    latest_log = log_dir / "delete_out_of_stock_latest.json"

    with open(timestamped_log, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2)

    with open(latest_log, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2)

    # Print clean summary
    mode_str = "DRY-RUN (SIMULATION)" if dry_run else "LIVE EXECUTION"
    logger.info("=" * 70)
    logger.info(f"CLEANUP SUMMARY [{mode_str}]")
    logger.info(f"Total Products Scanned:             {stats['total_products_scanned']}")
    logger.info(f"Products Deleted (< {min_combined_inventory} inventory): {stats['products_deleted_count']}")
    logger.info(f"Products with Variants Cleaned:     {stats['products_variants_cleaned_count']}")
    logger.info(f"Total Out-of-Stock Variants Deleted:{stats['variants_deleted_count']}")
    logger.info(f"Collective Skipped (Saved API calls):{stats['collective_products_skipped_count']}")
    logger.info(f"Products In-Stock (Untouched):      {stats['products_kept_untouched_count']}")
    logger.info(f"Errors Encountered:                 {stats['errors_count']}")
    logger.info(f"Duration:                           {stats['duration_seconds']}s")
    logger.info(f"Detailed Run Log:                   {timestamped_log}")
    logger.info(f"Persistent History Log:             {HISTORY_FILE}")
    logger.info("=" * 70)

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Delete out-of-stock variants and products with combined inventory < threshold."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate the cleanup without modifying or deleting anything in Shopify.",
    )
    parser.add_argument(
        "--min-inventory",
        type=int,
        default=10,
        help="Minimum combined in-stock inventory required to keep a product (default: 10).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of products to scan (useful for quick local tests).",
    )
    parser.add_argument(
        "--handle",
        type=str,
        default=None,
        help="Target a single product by handle (e.g. retrolicious-zombies-vintage-dress).",
    )
    parser.add_argument(
        "--product-id",
        type=str,
        default=None,
        help="Target a single product by Shopify ID (e.g. 8988062515371).",
    )
    parser.add_argument(
        "--no-skip-collective",
        action="store_true",
        help="Do not skip variant deletion for Shopify Collective products (default is to skip to conserve API limits).",
    )
    parser.add_argument(
        "--collective-vendors",
        type=str,
        default="",
        help="Comma-separated additional Shopify Collective vendor names.",
    )
    parser.add_argument(
        "--log-dir",
        type=str,
        default=None,
        help="Directory to save execution logs (default: REPO_ROOT/logs).",
    )

    args = parser.parse_args()

    # Retrieve decrypted secrets
    store = get_secret("SHOPIFY_STORE")
    token = get_secret("SHOPIFY_ACCESS_TOKEN")

    if not store or not token:
        logger.error("Failed to retrieve SHOPIFY_STORE or SHOPIFY_ACCESS_TOKEN from secrets.")
        sys.exit(1)

    log_path = Path(args.log_dir) if args.log_dir else None
    client = ShopifyGraphQLClient(store=store, token=token)

    extra_vendors = {v.strip() for v in args.collective_vendors.split(",") if v.strip()}
    skip_collective = not args.no_skip_collective

    run_inventory_cleanup(
        client=client,
        min_combined_inventory=args.min_inventory,
        dry_run=args.dry_run,
        limit=args.limit,
        handle=args.handle,
        product_id=args.product_id,
        log_dir=log_path,
        skip_collective_variants=skip_collective,
        extra_collective_vendors=extra_vendors,
    )


if __name__ == "__main__":
    main()

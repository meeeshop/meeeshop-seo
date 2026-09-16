#!/usr/bin/env python3
"""
delete_out_of_stock_variants.py

Automated script to:
1. Delete products whose combined in-stock inventory across all variants is less than the threshold (default: 10).
   This includes products where all variants have 0 or negative inventory.
2. For products with combined inventory >= threshold:
   Delete individual variants that have 0 or negative inventory (inventoryQuantity <= 0),
   ensuring customers cannot place orders for out-of-stock variants while keeping in-stock variants available.

Uses:
- Double-Fernet encryption via secrets_manager.py and secrets.enc for secure credential retrieval.
- Shopify Admin GraphQL API with automatic rate-limiting, cost throttling, and retry logic.
- Configurable --dry-run, --min-inventory, and --limit CLI options.
- Detailed audit logging to logs/ directory.
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
        status
        totalInventory
        variants(first: 100) {
          edges {
            node {
              id
              title
              sku
              inventoryQuantity
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
        self.store = store
        self.endpoint = f"https://{store}/admin/api/{api_version}/graphql.json"
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


def clean_gid(gid: str) -> str:
    """Ensure GID format."""
    return gid.strip() if gid else ""


def run_inventory_cleanup(
    client: ShopifyGraphQLClient,
    min_combined_inventory: int = 10,
    dry_run: bool = False,
    limit: Optional[int] = None,
    log_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Main cleanup engine:
    1. Fetches all products and their variants.
    2. Deletes products if combined in-stock inventory < min_combined_inventory.
    3. Otherwise, deletes any variants with inventoryQuantity <= 0.
    """
    if log_dir is None:
        log_dir = REPO_ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    start_time = datetime.datetime.now(datetime.timezone.utc)
    timestamp_str = start_time.strftime("%Y%m%d_%H%M%S")

    stats = {
        "start_time": start_time.isoformat(),
        "dry_run": dry_run,
        "min_combined_inventory": min_combined_inventory,
        "total_products_scanned": 0,
        "products_deleted_count": 0,
        "variants_deleted_count": 0,
        "products_kept_untouched_count": 0,
        "products_variants_cleaned_count": 0,
        "errors_count": 0,
        "deleted_products": [],
        "cleaned_products": [],
        "errors": [],
    }

    logger.info("=" * 70)
    logger.info(f"STARTING OUT-OF-STOCK CLEANUP | Dry-Run: {dry_run} | Min Inventory: {min_combined_inventory}")
    logger.info("=" * 70)

    after_cursor: Optional[str] = None
    processed_count = 0
    batch_size = 100

    try:
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
                product_id = node.get("id")
                title = node.get("title", "Untitled")
                handle = node.get("handle", "")

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
                if combined_stock < min_combined_inventory:
                    logger.info(
                        f"[PRODUCT DELETE] '{title}' ({handle}) | Total Stock: {combined_stock} (< {min_combined_inventory}) | Variants: {total_variants_count}"
                    )
                    stats["products_deleted_count"] += 1
                    stats["deleted_products"].append({
                        "product_id": product_id,
                        "title": title,
                        "handle": handle,
                        "combined_stock": combined_stock,
                        "variants_count": total_variants_count,
                        "reason": f"Combined inventory ({combined_stock}) < threshold ({min_combined_inventory})",
                    })

                    if not dry_run:
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
                    logger.info(
                        f"[VARIANTS DELETE] '{title}' ({handle}) | Stock: {combined_stock} >= {min_combined_inventory} | Deleting {len(out_of_stock_ids)}/{total_variants_count} out-of-stock variants"
                    )
                    stats["variants_deleted_count"] += len(out_of_stock_ids)
                    stats["products_variants_cleaned_count"] += 1
                    stats["cleaned_products"].append({
                        "product_id": product_id,
                        "title": title,
                        "handle": handle,
                        "combined_stock": combined_stock,
                        "deleted_variants": [
                            {
                                "id": v["id"],
                                "title": v.get("title"),
                                "sku": v.get("sku"),
                                "inventoryQuantity": v.get("inventoryQuantity"),
                            }
                            for v in out_of_stock_variants
                        ],
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

                if limit is not None and processed_count >= limit:
                    break

            if not page_info.get("hasNextPage"):
                break
            after_cursor = page_info.get("endCursor")

            if stats["total_products_scanned"] % 500 == 0:
                logger.info(
                    f"Progress: {stats['total_products_scanned']} products scanned | "
                    f"Products to delete: {stats['products_deleted_count']} | "
                    f"Variants to delete: {stats['variants_deleted_count']}"
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

    # Save detailed JSON logs
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
    logger.info(f"Products In-Stock (Untouched):      {stats['products_kept_untouched_count']}")
    logger.info(f"Errors Encountered:                 {stats['errors_count']}")
    logger.info(f"Duration:                           {stats['duration_seconds']}s")
    logger.info(f"Log written to:                     {timestamped_log}")
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

    run_inventory_cleanup(
        client=client,
        min_combined_inventory=args.min_inventory,
        dry_run=args.dry_run,
        limit=args.limit,
        log_dir=log_path,
    )


if __name__ == "__main__":
    main()

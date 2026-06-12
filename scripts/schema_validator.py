"""
MeeeShop Schema Validation & Optimization v1.0
Daily validation of all required JSON-LD schemas for:
  - Products (Product, Offer, Rating)
  - Collections (CollectionPage, AggregateOffer)
  - Pages (WebPage)
  - Blog Posts (BlogPosting, NewsArticle)

Adds missing schemas, validates structure, logs results, optimizes page speed.
"""
import os, json, re, time, argparse, logging, sys
import requests
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Tuple, Optional
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from secrets_manager import inject_to_env, get_secret
inject_to_env()

STORE = get_secret("SHOPIFY_STORE")
TOKEN = get_secret("SHOPIFY_ACCESS_TOKEN")
HEADS = {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}
BASE = f"https://{STORE}/admin/api/2024-01"
SITE = get_secret("STORE_BASE_URL")
BRAND = "MeeeShop"

# Rate limiting settings
MAX_RETRIES = 5
INITIAL_BACKOFF = 5  # seconds
MAX_BACKOFF = 120  # seconds
REQUEST_DELAY = 2.0  # seconds between requests to avoid hitting rate limits

# Logging setup
log_dir = "schema_logs"
os.makedirs(log_dir, exist_ok=True)
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
log_file = os.path.join(log_dir, f"schema_validation_{timestamp}.log")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
# Fix Windows console encoding
if sys.stdout.encoding and 'cp' in sys.stdout.encoding.lower():
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
logger = logging.getLogger(__name__)

# Track validation health
validation_health = {
    "total_errors": 0,
    "critical_errors": 0,
    "fatal_error": False
}


# ══════════════════════════════════════════════════════════════════════════════
# RATE LIMITING & RETRY LOGIC
# ══════════════════════════════════════════════════════════════════════════════

def make_request_with_retry(method: str, url: str, max_retries: int = MAX_RETRIES,
                           **kwargs) -> Optional[requests.Response]:
    """Make API request with exponential backoff for rate limiting"""
    backoff = INITIAL_BACKOFF
    last_error = None

    for attempt in range(max_retries):
        try:
            time.sleep(REQUEST_DELAY)  # Delay between all requests

            if method.lower() == 'get':
                resp = requests.get(url, headers=HEADS, **kwargs)
            elif method.lower() == 'post':
                resp = requests.post(url, headers=HEADS, **kwargs)
            else:
                raise ValueError(f"Unsupported method: {method}")

            # Success
            if resp.status_code < 400:
                return resp

            # Handle rate limiting (429)
            if resp.status_code == 429:
                retry_after = float(resp.headers.get('Retry-After', backoff))
                logger.warning(f"Rate limited (429). Waiting {retry_after}s before retry {attempt + 1}/{max_retries}")
                validation_health["total_errors"] += 1
                time.sleep(retry_after)
                backoff = min(backoff * 2, MAX_BACKOFF)
                continue

            # Handle other errors
            resp.raise_for_status()
            return resp

        except requests.exceptions.RequestException as e:
            last_error = e
            if attempt < max_retries - 1:
                logger.warning(f"Request failed (attempt {attempt + 1}/{max_retries}): {e}. Retrying in {backoff}s...")
                validation_health["total_errors"] += 1
                time.sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF)
            else:
                logger.error(f"Request failed after {max_retries} attempts: {e}")
                validation_health["critical_errors"] += 1

    if last_error:
        logger.error(f"Final error after {max_retries} retries on {url}: {last_error}")
    return None


# ══════════════════════════════════════════════════════════════════════════════
# SCHEMA TEMPLATES
# ══════════════════════════════════════════════════════════════════════════════

def product_schema(product: Dict) -> Dict:
    """Generate complete Product schema with all Merchant Listings required fields.

    Required for GSC Merchant Listings (distinct from Product Snippets):
      - shippingDetails  (OfferShippingDetails)
      - hasMerchantReturnPolicy (MerchantReturnPolicy)
      - priceValidUntil
      - gtin / mpn  (per-variant identifiers)
    """
    vendor = product.get('vendor', 'Unknown')
    description = product.get('body_html', '').replace('<p>', '').replace('</p>', '').strip()[:160]

    # Extract variant-level identifiers from the first variant
    first_variant = product.get('variants', [{}])[0]
    barcode = first_variant.get('barcode', '') or ''
    sku     = first_variant.get('sku', '') or ''
    price   = str(first_variant.get('price', '0'))

    # Validate GTIN — must be 8, 12, 13, or 14 numeric digits
    gtin = barcode if (barcode.isdigit() and len(barcode) in (8, 12, 13, 14)) else ''

    # priceValidUntil: set to Dec 31 of next calendar year
    price_valid_until = f"{datetime.now().year + 1}-12-31"

    schema = {
        "@context": "https://schema.org/",
        "@type": "Product",
        "name": product.get('title', ''),
        "description": description or f"{vendor} {product.get('title', '')}",
        "image": [
            img.get('src', '')
            for img in product.get('images', [])[:3]
            if img.get('src')
        ],
        "brand": {
            "@type": "Brand",
            "name": vendor
        },
        "offers": {
            "@type": "Offer",
            "url": f"{SITE}/products/{product.get('handle', '')}",
            "priceCurrency": "USD",
            "price": price,
            "priceValidUntil": price_valid_until,
            "availability": f"https://schema.org/{'InStock' if product.get('available') else 'OutOfStock'}",
            "seller": {
                "@type": "Organization",
                "name": BRAND
            },
            # ── Merchant Listings required fields ──────────────────────────────
            "shippingDetails": {
                "@type": "OfferShippingDetails",
                "shippingDestination": {
                    "@type": "DefinedRegion",
                    "addressCountry": "US"
                },
                "shippingRate": {
                    "@type": "MonetaryAmount",
                    "value": "0.00",
                    "currency": "USD"
                },
                "deliveryTime": {
                    "@type": "ShippingDeliveryTime",
                    "handlingTime": {
                        "@type": "QuantitativeValue",
                        "minValue": 0,
                        "maxValue": 1,
                        "unitCode": "DAY"
                    },
                    "transitTime": {
                        "@type": "QuantitativeValue",
                        "minValue": 2,
                        "maxValue": 5,
                        "unitCode": "DAY"
                    }
                }
            },
            "hasMerchantReturnPolicy": {
                "@type": "MerchantReturnPolicy",
                "applicableCountry": "US",
                "returnPolicyCategory": "https://schema.org/MerchantReturnFiniteReturnWindow",
                "merchantReturnDays": 7,
                "returnMethod": "https://schema.org/ReturnByMail",
                "returnFees": "https://schema.org/FreeReturn"
            }
        },
        "sku": str(product.get('id', '')),
        "url": f"{SITE}/products/{product.get('handle', '')}"
    }

    # Add variant-level identifiers if available
    if gtin:
        schema["offers"]["gtin"] = gtin
    if sku:
        schema["offers"]["mpn"] = sku

    # Add rating if reviews exist
    if product.get('rating_count', 0) > 0:
        schema["aggregateRating"] = {
            "@type": "AggregateRating",
            "ratingValue": str(round(product.get('rating', 0), 1)),
            "bestRating": "5",
            "worstRating": "1",
            "reviewCount": product.get('rating_count', 0)
        }

    return schema


def collection_schema(collection: Dict) -> Dict:
    """Generate CollectionPage schema"""
    return {
        "@context": "https://schema.org/",
        "@type": "CollectionPage",
        "name": collection.get('title', ''),
        "description": collection.get('body_html', '').replace('<p>', '').replace('</p>', '').strip()[:160],
        "url": f"{SITE}/collections/{collection.get('handle', '')}",
        "isPartOf": {
            "@type": "WebSite",
            "name": BRAND,
            "url": SITE
        }
    }


def page_schema(page: Dict) -> Dict:
    """Generate WebPage schema"""
    body = page.get('body_html') or ''
    return {
        "@context": "https://schema.org/",
        "@type": "WebPage",
        "name": page.get('title', ''),
        "description": body.replace('<p>', '').replace('</p>', '').strip()[:160],
        "url": f"{SITE}/pages/{page.get('handle', '')}",
        "isPartOf": {
            "@type": "WebSite",
            "name": BRAND,
            "url": SITE
        }
    }


def blog_schema(article: Dict, blog_handle: str) -> Dict:
    """Generate BlogPosting schema"""
    return {
        "@context": "https://schema.org/",
        "@type": "BlogPosting",
        "headline": article.get('title', ''),
        "description": article.get('excerpt_html', '').replace('<p>', '').replace('</p>', '').strip()[:160],
        "image": article.get('image', {}).get('src', '') if article.get('image') else '',
        "datePublished": article.get('published_at', ''),
        "dateModified": article.get('updated_at', ''),
        "author": {
            "@type": "Person",
            "name": article.get('author', BRAND)
        },
        "publisher": {
            "@type": "Organization",
            "name": BRAND,
            "logo": {
                "@type": "ImageObject",
                "url": f"{SITE}/logo.png"
            }
        },
        "url": f"{SITE}/blogs/{blog_handle}/{article.get('handle', '')}"
    }


def organization_schema() -> Dict:
    """Generate Organization schema for site header"""
    return {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": BRAND,
        "url": SITE,
        "logo": f"{SITE}/logo.png",
        "description": "Women's fashion store specializing in dresses, tops, and accessories",
        "sameAs": [
            "https://www.pinterest.com/meeeshop",
            "https://www.youtube.com/@meeeshop"
        ],
        "contactPoint": {
            "@type": "ContactPoint",
            "contactType": "Customer Service",
            "email": "support@meeeshop.com"
        }
    }


def breadcrumb_schema(path: List[Tuple[str, str]]) -> Dict:
    """Generate BreadcrumbList schema"""
    items = []
    for i, (name, url) in enumerate(path, 1):
        items.append({
            "@type": "ListItem",
            "position": i,
            "name": name,
            "item": url
        })

    return {
        "@context": "https://schema.org/",
        "@type": "BreadcrumbList",
        "itemListElement": items
    }


# ══════════════════════════════════════════════════════════════════════════════
# VALIDATION & CHECKING
# ══════════════════════════════════════════════════════════════════════════════

def validate_schema(schema: Dict, resource_type: str) -> Tuple[bool, List[str]]:
    """Validate schema structure and required fields"""
    errors = []

    required_fields = {
        "Product": ["name", "description", "image", "offers"],
        "CollectionPage": ["name", "url"],
        "WebPage": ["name", "url"],
        "BlogPosting": ["headline", "datePublished", "author"],
        "Organization": ["name", "url"]
    }

    schema_type = schema.get("@type", "")
    required = required_fields.get(schema_type, [])

    for field in required:
        if field not in schema or not schema[field]:
            errors.append(f"Missing required field: {field}")

    # Check nested objects
    if schema_type == "Product":
        if "offers" in schema:
            offer = schema["offers"]
            offers_list = offer if isinstance(offer, list) else [offer]
            for idx, off in enumerate(offers_list):
                if not isinstance(off, dict):
                    errors.append(f"Offer[{idx}] is not a dict")
                    continue
                for req in ["priceCurrency", "price", "availability"]:
                    if req not in off or not off[req]:
                        errors.append(f"Offer[{idx}] missing: {req}")
                if "shippingDetails" not in off:
                    errors.append(f"Offer[{idx}] missing: shippingDetails")
                else:
                    sd = off["shippingDetails"]
                    if not isinstance(sd, dict):
                        errors.append(f"Offer[{idx}].shippingDetails is not a dict")
                    elif "deliveryTime" not in sd:
                        errors.append(f"Offer[{idx}].shippingDetails missing: deliveryTime")
                if "hasMerchantReturnPolicy" not in off:
                    errors.append(f"Offer[{idx}] missing: hasMerchantReturnPolicy")

    return len(errors) == 0, errors


def schema_exists(metafields: List[Dict], namespace: str, key: str) -> bool:
    """Check if schema already exists in metafields"""
    return any(
        m.get("namespace") == namespace and m.get("key") == key
        for m in metafields
    )


# ══════════════════════════════════════════════════════════════════════════════
# SHOPIFY API OPERATIONS
# ══════════════════════════════════════════════════════════════════════════════

def get_products(hours: int = 0) -> List[Dict]:
    """Fetch products created since cutoff (last N hours). 0 = all products."""
    from shopify_graphql import fetch_products_graphql
    products = fetch_products_graphql(hours)
    logger.info(f"Fetched {len(products)} products (GraphQL)")
    return products


def get_collections(hours: int = 0) -> List[Dict]:
    """Fetch both custom and smart collections created since cutoff. 0 = all collections."""
    from shopify_graphql import fetch_collections_graphql
    collections = fetch_collections_graphql(hours)
    logger.info(f"Fetched {len(collections)} collections (GraphQL)")
    return collections


def get_pages(hours: int = 0) -> List[Dict]:
    """Fetch pages created since cutoff. 0 = all pages."""
    from shopify_graphql import fetch_pages_graphql
    pages = fetch_pages_graphql(hours)
    logger.info(f"Fetched {len(pages)} pages (GraphQL)")
    return pages


_cached_articles = {}

def get_blog_articles(blog_id: str, hours: int = 0) -> List[Dict]:
    """Fetch articles from a blog created since cutoff. 0 = all articles."""
    from shopify_graphql import fetch_articles_graphql
    cache_key = (hours,)
    if cache_key not in _cached_articles:
        _cached_articles[cache_key] = fetch_articles_graphql(hours)
    filtered = [a for a in _cached_articles[cache_key] if a.get("blog_id") == int(blog_id)]
    logger.info(f"Fetched {len(filtered)} articles for blog {blog_id} (GraphQL)")
    return filtered


def set_metafield(resource_type: str, resource_id: str, schema: Dict) -> bool:
    """Add/update schema as metafield with retry logic"""
    url = f"{BASE}/{resource_type.lower()}s/{resource_id}/metafields.json"

    metafield = {
        "metafield": {
            "namespace": "json_ld_schema",
            "key": f"{schema.get('@type', 'unknown').lower()}",
            "type": "json",
            "value": json.dumps(schema)
        }
    }

    resp = make_request_with_retry("post", url, json=metafield)

    if resp is None:
        logger.error(f"Failed to set metafield for {resource_type} {resource_id} after retries")
        validation_health["critical_errors"] += 1
        return False

    if resp.status_code >= 400:
        logger.error(f"Failed to set metafield for {resource_type} {resource_id}: {resp.status_code} {resp.reason}")
        validation_health["critical_errors"] += 1
        return False

    try:
        resp.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"Failed to set metafield for {resource_type} {resource_id}: {e}")
        validation_health["critical_errors"] += 1
        return False


# ══════════════════════════════════════════════════════════════════════════════
# MAIN VALIDATION & ADDITION
# ══════════════════════════════════════════════════════════════════════════════

def validate_and_add_schemas(mode: str = "daily", batch_size: int = 0, batch_index: int = 0, resource: str = "all"):
    """Main validation and schema addition loop"""

    report = {
        "timestamp": datetime.now().isoformat(),
        "mode": mode,
        "products": {"checked": 0, "missing_schemas": 0, "added": 0, "errors": 0},
        "collections": {"checked": 0, "missing_schemas": 0, "added": 0, "errors": 0},
        "pages": {"checked": 0, "missing_schemas": 0, "added": 0, "errors": 0},
        "blog_articles": {"checked": 0, "missing_schemas": 0, "added": 0, "errors": 0},
        "details": []
    }

    # Determine time window based on mode
    if mode == "daily":
        hours = 48
    elif mode == "weekly":
        hours = 0  # All products
    else:  # force
        hours = 0  # All products

    logger.info(f"Starting schema validation in {mode} mode (hours={hours if hours > 0 else 'all'})")

    # ─── Products ───────────────────────────────────────────────────────────
    if resource in ("all", "products"):
        logger.info("=" * 60)
        logger.info("VALIDATING PRODUCTS")
        logger.info("=" * 60)

        try:
            products = get_products(hours)
            if mode in ('force', 'weekly') and batch_size > 0:
                start = batch_index * batch_size
                end = start + batch_size
                total_fetched = len(products)
                products = products[start:end]
                logger.info(f"Batch {batch_index}: validating products {start} to {min(end, total_fetched)} of {total_fetched}")

            for product in products:
                report["products"]["checked"] += 1
                product_id = product.get("id")
                title = product.get("title", "Unknown")

                # Check if schema exists
                metafields = product.get("metafields", [])
                has_schema = schema_exists(metafields, "json_ld_schema", "product")

                if not has_schema:
                    report["products"]["missing_schemas"] += 1
                    schema = product_schema(product)
                    is_valid, errors = validate_schema(schema, "Product")

                    if is_valid:
                        if set_metafield("product", product_id, schema):
                            report["products"]["added"] += 1
                            logger.info(f"[OK] Added Product schema: {title}")
                            report["details"].append({
                                "type": "product",
                                "id": product_id,
                                "title": title,
                                "action": "added"
                            })
                        else:
                            report["products"]["errors"] += 1
                            logger.error(f"✗ Failed to add schema: {title}")
                    else:
                        report["products"]["errors"] += 1
                        logger.warning(f"Schema validation failed for {title}: {errors}")
                else:
                    logger.debug(f"Schema already exists: {title}")

        except Exception as e:
            logger.error(f"Products validation error: {e}")
            report["products"]["errors"] += 1

    # ─── Collections ────────────────────────────────────────────────────────
    if resource in ("all", "collections"):
        logger.info("=" * 60)
        logger.info("VALIDATING COLLECTIONS")
        logger.info("=" * 60)

        try:
            collections = get_collections(hours)
            for collection in collections:
                report["collections"]["checked"] += 1
                coll_id = collection.get("id")
                title = collection.get("title", "Unknown")

                metafields = collection.get("metafields", [])
                has_schema = schema_exists(metafields, "json_ld_schema", "collectionpage")

                if not has_schema:
                    report["collections"]["missing_schemas"] += 1
                    schema = collection_schema(collection)
                    is_valid, errors = validate_schema(schema, "CollectionPage")

                    if is_valid:
                        if set_metafield("collection", coll_id, schema):
                            report["collections"]["added"] += 1
                            logger.info(f"[OK] Added CollectionPage schema: {title}")
                            report["details"].append({
                                "type": "collection",
                                "id": coll_id,
                                "title": title,
                                "action": "added"
                            })
                        else:
                            report["collections"]["errors"] += 1
                    else:
                        report["collections"]["errors"] += 1
                        logger.warning(f"Schema validation failed for {title}: {errors}")
                else:
                    logger.debug(f"Schema already exists: {title}")

        except Exception as e:
            logger.error(f"Collections validation error: {e}")
            report["collections"]["errors"] += 1

    # ─── Pages ──────────────────────────────────────────────────────────────
    if resource in ("all", "pages"):
        logger.info("=" * 60)
        logger.info("VALIDATING PAGES")
        logger.info("=" * 60)

        try:
            pages = get_pages(hours)
            for page in pages:
                report["pages"]["checked"] += 1
                page_id = page.get("id")
                title = page.get("title", "Unknown")

                metafields = page.get("metafields", [])
                has_schema = schema_exists(metafields, "json_ld_schema", "webpage")

                if not has_schema:
                    report["pages"]["missing_schemas"] += 1
                    schema = page_schema(page)
                    is_valid, errors = validate_schema(schema, "WebPage")

                    if is_valid:
                        if set_metafield("page", page_id, schema):
                            report["pages"]["added"] += 1
                            logger.info(f"[OK] Added WebPage schema: {title}")
                            report["details"].append({
                                "type": "page",
                                "id": page_id,
                                "title": title,
                                "action": "added"
                            })
                        else:
                            report["pages"]["errors"] += 1
                    else:
                        report["pages"]["errors"] += 1
                        logger.warning(f"Schema validation failed for {title}: {errors}")
                else:
                    logger.debug(f"Schema already exists: {title}")

        except Exception as e:
            logger.error(f"Pages validation error: {e}")
            report["pages"]["errors"] += 1

    # ─── Blog Articles ──────────────────────────────────────────────────────
    if resource in ("all", "blogs"):
        logger.info("=" * 60)
        logger.info("VALIDATING BLOG ARTICLES")
        logger.info("=" * 60)

        try:
            # Get all blogs first
            blogs_url = f"{BASE}/blogs.json"
            blogs_resp = make_request_with_retry("get", blogs_url, params={"limit": 50})
            if blogs_resp is None:
                logger.error("Failed to fetch blogs")
                blogs = []
            else:
                try:
                    blogs = blogs_resp.json().get("blogs", [])
                except Exception as e:
                    logger.error(f"Error parsing blogs: {e}")
                    validation_health["critical_errors"] += 1
                    blogs = []

            for blog in blogs:
                blog_id = blog.get("id")
                blog_handle = blog.get("handle")
                articles = get_blog_articles(str(blog_id), hours)

                for article in articles:
                    report["blog_articles"]["checked"] += 1
                    article_id = article.get("id")
                    title = article.get("title", "Unknown")

                    metafields = article.get("metafields", [])
                    has_schema = schema_exists(metafields, "json_ld_schema", "blogposting")

                    if not has_schema:
                        report["blog_articles"]["missing_schemas"] += 1
                        schema = blog_schema(article, blog_handle)
                        is_valid, errors = validate_schema(schema, "BlogPosting")

                        if is_valid:
                            if set_metafield("article", article_id, schema):
                                report["blog_articles"]["added"] += 1
                                logger.info(f"[OK] Added BlogPosting schema: {title}")
                                report["details"].append({
                                    "type": "blog_article",
                                    "id": article_id,
                                    "title": title,
                                    "action": "added"
                                })
                            else:
                                report["blog_articles"]["errors"] += 1
                        else:
                            report["blog_articles"]["errors"] += 1
                            logger.warning(f"Schema validation failed for {title}: {errors}")
                    else:
                        logger.debug(f"Schema already exists: {title}")

        except Exception as e:
            logger.error(f"Blog articles validation error: {e}")
            report["blog_articles"]["errors"] += 1

    # ─── Summary ────────────────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("VALIDATION COMPLETE")
    logger.info("=" * 60)

    # Calculate health metrics
    total_checked = sum(report[r]["checked"] for r in ["products", "collections", "pages", "blog_articles"])
    total_errors = sum(report[r]["errors"] for r in ["products", "collections", "pages", "blog_articles"])
    error_rate = (total_errors / total_checked * 100) if total_checked > 0 else 0

    print("\n" + "=" * 60)
    print("SCHEMA VALIDATION REPORT")
    print("=" * 60)
    print(f"Mode: {mode}")
    print(f"Timestamp: {report['timestamp']}\n")

    for resource in ["products", "collections", "pages", "blog_articles"]:
        stats = report[resource]
        print(f"{resource.upper()}")
        print(f"  Checked:          {stats['checked']}")
        print(f"  Missing Schemas:  {stats['missing_schemas']}")
        print(f"  Added:            {stats['added']}")
        print(f"  Errors:           {stats['errors']}\n")

    print("=" * 60)
    print(f"VALIDATION HEALTH")
    print("=" * 60)
    print(f"Total Resources Checked: {total_checked}")
    print(f"Total Errors:            {total_errors}")
    print(f"Error Rate:              {error_rate:.1f}%")
    print(f"Retry Errors:            {validation_health['total_errors']}")
    print(f"Critical Errors:         {validation_health['critical_errors']}")
    print(f"Status:                  {'⚠️  PARTIAL FAILURE' if validation_health['fatal_error'] else '✅ SUCCESS'}\n")

    # Add health info to report
    report["health"] = {
        "total_errors": validation_health["total_errors"],
        "critical_errors": validation_health["critical_errors"],
        "error_rate": error_rate,
        "fatal_error": validation_health["fatal_error"],
        "status": "PARTIAL_FAILURE" if validation_health["fatal_error"] else "SUCCESS"
    }

    # Save report
    report_file = f"schema_report_{timestamp}.json"
    with open(report_file, "w") as f:
        json.dump(report, f, indent=2)
    logger.info(f"Report saved to {report_file}")

    # Exit with non-zero code if fatal errors occurred (for GitHub Actions)
    if validation_health["fatal_error"]:
        logger.error("❌ VALIDATION FAILED: Fatal errors detected during schema validation")
        sys.exit(1)

    if validation_health["critical_errors"] > (total_checked * 0.1):  # >10% critical errors
        logger.warning(f"⚠️  WARNING: High error rate ({validation_health['critical_errors']} critical errors)")
        sys.exit(1)

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--daily", action="store_true", help="Daily mode (48h)")
    parser.add_argument("--weekly", action="store_true", help="Weekly mode (7d)")
    parser.add_argument("--force", action="store_true", help="Force all resources")
    parser.add_argument("--batch-size", type=int, default=0, help="Batch size for force mode")
    parser.add_argument("--batch-index", type=int, default=0, help="Batch index for force mode")
    parser.add_argument("--resource", type=str, default="all", choices=["all", "products", "collections", "pages", "blogs"], help="Resource type to validate")

    args = parser.parse_args()

    mode = "daily"
    if args.weekly:
        mode = "weekly"
    elif args.force:
        mode = "force"

    validate_and_add_schemas(mode, batch_size=args.batch_size, batch_index=args.batch_index, resource=args.resource)

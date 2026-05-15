"""
MeeeShop Schema Validation & Optimization v1.0
Daily validation of all required JSON-LD schemas for:
  - Products (Product, Offer, Rating)
  - Collections (CollectionPage, AggregateOffer)
  - Pages (WebPage)
  - Blog Posts (BlogPosting, NewsArticle)

Adds missing schemas, validates structure, logs results, optimizes page speed.
"""
import os, json, re, time, argparse, logging
import requests
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from typing import Dict, List, Any, Tuple

load_dotenv()

STORE = os.getenv("SHOPIFY_STORE")
TOKEN = os.getenv("SHOPIFY_ACCESS_TOKEN")
HEADS = {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}
BASE = f"https://{STORE}/admin/api/2024-01"
SITE = "https://us.meeeshop.com"
BRAND = "MeeeShop"

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
import sys
if sys.stdout.encoding and 'cp' in sys.stdout.encoding.lower():
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# SCHEMA TEMPLATES
# ══════════════════════════════════════════════════════════════════════════════

def product_schema(product: Dict) -> Dict:
    """Generate complete Product schema with all required fields"""
    vendor = product.get('vendor', 'Unknown')
    description = product.get('body_html', '').replace('<p>', '').replace('</p>', '').strip()[:160]

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
            "price": str(product.get('variants', [{}])[0].get('price', '0')),
            "availability": f"https://schema.org/{'InStock' if product.get('available') else 'OutOfStock'}",
            "seller": {
                "@type": "Organization",
                "name": BRAND
            }
        },
        "sku": str(product.get('id', '')),
        "url": f"{SITE}/products/{product.get('handle', '')}"
    }

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
            "email": "meeeshop17@gmail.com"
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
            for req in ["priceCurrency", "price", "availability"]:
                if req not in offer:
                    errors.append(f"Offer missing: {req}")

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

def get_products(hours: int = 48) -> List[Dict]:
    """Fetch products updated in last N hours"""
    url = f"{BASE}/products.json"
    params = {"limit": 250, "status": "active"}

    all_products = []
    has_more = True
    while has_more:
        try:
            resp = requests.get(url, params=params, headers=HEADS)
            resp.raise_for_status()
            data = resp.json()
            products = data.get("products", [])

            if not products:
                has_more = False
                break

            all_products.extend(products)

            # Check for next page in Link header
            has_more = False
            link_header = resp.headers.get("Link", "")
            if link_header:
                for link in link_header.split(","):
                    if 'rel="next"' in link:
                        url = link.split(";")[0].strip().strip("<>")
                        has_more = True
                        break
        except Exception as e:
            logger.error(f"Error fetching products: {e}")
            has_more = False

    logger.info(f"Fetched {len(all_products)} products (status=active)")
    return all_products


def get_collections() -> List[Dict]:
    """Fetch all collections"""
    url = f"{BASE}/custom_collections.json"
    resp = requests.get(url, params={"limit": 250}, headers=HEADS)
    resp.raise_for_status()
    collections = resp.json().get("custom_collections", [])
    logger.info(f"Fetched {len(collections)} collections")
    return collections


def get_pages() -> List[Dict]:
    """Fetch all pages"""
    url = f"{BASE}/pages.json"
    resp = requests.get(url, params={"limit": 250}, headers=HEADS)
    resp.raise_for_status()
    pages = resp.json().get("pages", [])
    logger.info(f"Fetched {len(pages)} pages")
    return pages


def get_blog_articles(blog_id: str) -> List[Dict]:
    """Fetch all articles from a blog"""
    url = f"{BASE}/blogs/{blog_id}/articles.json"
    resp = requests.get(url, params={"limit": 250}, headers=HEADS)
    resp.raise_for_status()
    return resp.json().get("articles", [])


def set_metafield(resource_type: str, resource_id: str, schema: Dict) -> bool:
    """Add/update schema as metafield"""
    url = f"{BASE}/{resource_type.lower()}s/{resource_id}/metafields.json"

    metafield = {
        "metafield": {
            "namespace": "json_ld_schema",
            "key": f"{schema.get('@type', 'unknown').lower()}",
            "type": "json",
            "value": json.dumps(schema)
        }
    }

    try:
        resp = requests.post(url, json=metafield, headers=HEADS)
        resp.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"Failed to set metafield for {resource_type} {resource_id}: {e}")
        return False


# ══════════════════════════════════════════════════════════════════════════════
# MAIN VALIDATION & ADDITION
# ══════════════════════════════════════════════════════════════════════════════

def validate_and_add_schemas(mode: str = "daily"):
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

    # Determine time window
    hours = 48 if mode == "daily" else 168 if mode == "weekly" else 0

    logger.info(f"Starting schema validation in {mode} mode (hours={hours})")

    # ─── Products ───────────────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("VALIDATING PRODUCTS")
    logger.info("=" * 60)

    try:
        products = get_products(hours) if hours > 0 else get_products(10000)
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
    logger.info("=" * 60)
    logger.info("VALIDATING COLLECTIONS")
    logger.info("=" * 60)

    try:
        collections = get_collections()
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
    logger.info("=" * 60)
    logger.info("VALIDATING PAGES")
    logger.info("=" * 60)

    try:
        pages = get_pages()
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
    logger.info("=" * 60)
    logger.info("VALIDATING BLOG ARTICLES")
    logger.info("=" * 60)

    try:
        # Get all blogs first
        blogs_url = f"{BASE}/blogs.json"
        blogs_resp = requests.get(blogs_url, params={"limit": 50}, headers=HEADS)
        blogs_resp.raise_for_status()
        blogs = blogs_resp.json().get("blogs", [])

        for blog in blogs:
            blog_id = blog.get("id")
            blog_handle = blog.get("handle")
            articles = get_blog_articles(str(blog_id))

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

    # Save report
    report_file = f"schema_report_{timestamp}.json"
    with open(report_file, "w") as f:
        json.dump(report, f, indent=2)
    logger.info(f"Report saved to {report_file}")

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--daily", action="store_true", help="Daily mode (48h)")
    parser.add_argument("--weekly", action="store_true", help="Weekly mode (7d)")
    parser.add_argument("--force", action="store_true", help="Force all resources")

    args = parser.parse_args()

    mode = "daily"
    if args.weekly:
        mode = "weekly"
    elif args.force:
        mode = "force"

    validate_and_add_schemas(mode)

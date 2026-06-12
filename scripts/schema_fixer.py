"""
MeeeShop Schema Fixer v1.0
Detects and repairs invalid JSON-LD schema metafields:
  - null values  (GSC error: "Invalid top level element 'null'")
  - missing offers on Product schemas  (GSC error: "'offers' should be specified")
  - missing required fields for any schema type
  - regenerates and re-uploads broken schemas

Run modes:
  --daily   products/collections updated in last 48h
  --weekly  all resources
  --force   all resources (alias for weekly)
"""
import os, json, re, time, argparse, logging, sys
import requests
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from secrets_manager import inject_to_env, get_secret
inject_to_env()

STORE = get_secret("SHOPIFY_STORE")
TOKEN = get_secret("SHOPIFY_ACCESS_TOKEN")
HEADS = {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}
BASE  = f"https://{STORE}/admin/api/2024-01"
SITE  = get_secret("STORE_BASE_URL")
BRAND = "MeeeShop"

REQUEST_DELAY = 1.5
MAX_RETRIES   = 5
INITIAL_BACKOFF = 5
MAX_BACKOFF   = 120

log_dir = "schema_logs"
os.makedirs(log_dir, exist_ok=True)
ts = datetime.now().strftime("%Y%m%d_%H%M%S")
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(log_dir, f"schema_fixer_{ts}.log"), encoding='utf-8'),
        logging.StreamHandler()
    ]
)
if sys.stdout.encoding and 'cp' in sys.stdout.encoding.lower():
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
logger = logging.getLogger(__name__)

stats = {"scanned": 0, "null_fixed": 0, "invalid_fixed": 0, "errors": 0}


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _req(method: str, url: str, **kwargs) -> Optional[requests.Response]:
    backoff = INITIAL_BACKOFF
    for attempt in range(MAX_RETRIES):
        time.sleep(REQUEST_DELAY)
        try:
            resp = getattr(requests, method)(url, headers=HEADS, **kwargs)
            if resp.status_code == 429:
                wait = float(resp.headers.get('Retry-After', backoff))
                logger.warning(f"Rate limited — waiting {wait}s")
                time.sleep(wait)
                backoff = min(backoff * 2, MAX_BACKOFF)
                continue
            if resp.status_code < 400:
                return resp
            resp.raise_for_status()
        except requests.RequestException as e:
            if attempt < MAX_RETRIES - 1:
                logger.warning(f"Retry {attempt+1}/{MAX_RETRIES}: {e}")
                time.sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF)
            else:
                logger.error(f"Failed after {MAX_RETRIES} attempts: {e}")
    return None


def get_all_pages(url: str, key: str, params: dict = None) -> List[Dict]:
    """Fetch all pages of a paginated Shopify endpoint."""
    params = params or {}
    params["limit"] = 250
    items = []
    while url:
        resp = _req("get", url, params=params)
        if not resp:
            break
        items.extend(resp.json().get(key, []))
        link = resp.headers.get("Link", "")
        url = None
        params = {}
        for part in link.split(","):
            if 'rel="next"' in part:
                url = part.split(";")[0].strip().strip("<>")
    return items


# ── Schema validation helpers ─────────────────────────────────────────────────

REQUIRED = {
    "Product":       ["name", "offers"],
    "CollectionPage":["name", "url"],
    "WebPage":       ["name", "url"],
    "BlogPosting":   ["headline", "datePublished", "author"],
    "Organization":  ["name", "url"],
}


def _issues(schema: Any) -> List[str]:
    """Return list of GSC-relevant issues with the schema, empty = valid."""
    if schema is None:
        return ["null schema"]
    if not isinstance(schema, dict):
        return [f"unexpected type: {type(schema).__name__}"]
    issues = []
    stype = schema.get("@type", "")
    for field in REQUIRED.get(stype, []):
        if field not in schema or schema[field] in (None, "", [], {}):
            issues.append(f"missing '{field}'")
    if stype == "Product":
        offers = schema.get("offers")
        if not offers:
            issues.append("missing 'offers'")
        else:
            offers_list = offers if isinstance(offers, list) else [offers]
            for idx, offer in enumerate(offers_list):
                if not isinstance(offer, dict):
                    issues.append(f"offer[{idx}] is not a dict")
                    continue
                for req in ("priceCurrency", "price", "availability"):
                    if req not in offer or not offer[req]:
                        issues.append(f"offer[{idx}] missing '{req}'")
                if "shippingDetails" not in offer:
                    issues.append(f"offer[{idx}] missing 'shippingDetails'")
                else:
                    sd = offer["shippingDetails"]
                    if not isinstance(sd, dict):
                        issues.append(f"offer[{idx}].shippingDetails is not a dict")
                    elif "deliveryTime" not in sd:
                        issues.append(f"offer[{idx}].shippingDetails missing 'deliveryTime'")
                if "hasMerchantReturnPolicy" not in offer:
                    issues.append(f"offer[{idx}] missing 'hasMerchantReturnPolicy'")
    return issues


# ── Schema generators ─────────────────────────────────────────────────────────

def _product_schema(p: Dict) -> Dict:
    vendor = p.get("vendor", BRAND)
    desc   = re.sub(r'<[^>]+>', '', p.get("body_html") or "").strip()[:500]
    variants = p.get("variants") or [{}]
    price_valid_until = f"{datetime.now().year + 1}-12-31"
    
    offers_list = []
    for v in variants:
        barcode = v.get("barcode", "") or ""
        sku = v.get("sku", "") or ""
        gtin = barcode if (barcode.isdigit() and len(barcode) in (8, 12, 13, 14)) else ''
        
        offer = {
            "@type": "Offer",
            "price": str(v.get("price", "0")),
            "priceCurrency": "USD",
            "priceValidUntil": price_valid_until,
            "availability": f"https://schema.org/{'InStock' if v.get('inventory_quantity', 1) > 0 else 'OutOfStock'}",
            "url": f"{SITE}/products/{p.get('handle', '')}?variant={v.get('id', '')}",
            "seller": {"@type": "Organization", "name": BRAND},
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
        }
        if gtin:
            offer["gtin"] = gtin
        if sku:
            offer["mpn"] = sku
            offer["sku"] = sku
        
        offers_list.append(offer)

    return {
        "@context": "https://schema.org/",
        "@type": "Product",
        "name": p.get("title", ""),
        "description": desc or f"{vendor} {p.get('title', '')}",
        "url": f"{SITE}/products/{p.get('handle', '')}",
        "image": [img["src"] for img in (p.get("images") or [])[:3] if img.get("src")],
        "brand": {"@type": "Brand", "name": vendor},
        "sku": str(p.get("id", "")),
        "offers": offers_list
    }



def _collection_schema(c: Dict) -> Dict:
    desc = re.sub(r'<[^>]+>', '', c.get("body_html") or "").strip()[:160]
    return {
        "@context": "https://schema.org/",
        "@type": "CollectionPage",
        "name": c.get("title", ""),
        "description": desc or c.get("title", ""),
        "url": f"{SITE}/collections/{c.get('handle', '')}",
        "isPartOf": {"@type": "WebSite", "name": BRAND, "url": SITE}
    }


def _page_schema(p: Dict) -> Dict:
    desc = re.sub(r'<[^>]+>', '', p.get("body_html") or "").strip()[:160]
    return {
        "@context": "https://schema.org/",
        "@type": "WebPage",
        "name": p.get("title", ""),
        "description": desc or p.get("title", ""),
        "url": f"{SITE}/pages/{p.get('handle', '')}",
        "isPartOf": {"@type": "WebSite", "name": BRAND, "url": SITE}
    }


def _article_schema(a: Dict, blog_handle: str) -> Dict:
    desc = re.sub(r'<[^>]+>', '', a.get("excerpt_html") or "").strip()[:160]
    return {
        "@context": "https://schema.org/",
        "@type": "BlogPosting",
        "headline": a.get("title", ""),
        "description": desc or a.get("title", ""),
        "url": f"{SITE}/blogs/{blog_handle}/{a.get('handle', '')}",
        "datePublished": a.get("published_at", ""),
        "dateModified": a.get("updated_at", ""),
        "image": (a.get("image") or {}).get("src", ""),
        "author": {"@type": "Person", "name": a.get("author", BRAND)},
        "publisher": {
            "@type": "Organization",
            "name": BRAND,
            "logo": {"@type": "ImageObject", "url": f"{SITE}/logo.png"}
        }
    }


SCHEMA_GENERATORS = {
    "product":    (lambda r, _: _product_schema(r),    "product",    "Product"),
    "collection": (lambda r, _: _collection_schema(r), "collection", "CollectionPage"),
    "page":       (lambda r, _: _page_schema(r),       "page",       "WebPage"),
}


# ── Metafield operations ──────────────────────────────────────────────────────

def get_metafields(resource_type: str, rid: int) -> List[Dict]:
    url  = f"{BASE}/{resource_type}s/{rid}/metafields.json"
    resp = _req("get", url, params={"namespace": "json_ld_schema", "limit": 250})
    return resp.json().get("metafields", []) if resp else []


def delete_metafield(mf_id: int) -> bool:
    from shopify_graphql import delete_metafield_graphql
    return delete_metafield_graphql(mf_id)


def upsert_schema_metafield(resource_type: str, rid: int, key: str, schema: Dict,
                             existing_mf: Optional[Dict] = None) -> bool:
    from shopify_graphql import set_metafield_graphql
    return set_metafield_graphql(resource_type, rid, key, schema)


# ── Core fix logic ────────────────────────────────────────────────────────────

def fix_resource(resource_type: str, resource: Dict, extra=None) -> int:
    """
    Check all json_ld_schema metafields on a resource.
    Delete nulls, regenerate invalids.
    Returns number of fixes applied.
    """
    rid   = resource["id"]
    title = resource.get("title", str(rid))
    mfs   = resource.get("metafields")
    if mfs is None:
        mfs = get_metafields(resource_type, rid)
    fixes = 0

    for mf in mfs:
        if mf.get("namespace") != "json_ld_schema":
            continue
        stats["scanned"] += 1
        raw = mf.get("value")

        # Parse value — Shopify json metafields may come back as str or dict
        if isinstance(raw, str):
            try:
                schema = json.loads(raw)
            except json.JSONDecodeError:
                schema = None
        else:
            schema = raw  # already parsed by requests

        issues = _issues(schema)
        if not issues:
            continue

        logger.warning(f"[{resource_type}] '{title}' — {issues}")

        # Regenerate correct schema
        if resource_type == "article":
            blog_handle = extra or "blog"
            new_schema = _article_schema(resource, blog_handle)
            key = "blogposting"
        elif resource_type == "product":
            new_schema = _product_schema(resource)
            key = "product"
        elif resource_type == "collection":
            new_schema = _collection_schema(resource)
            key = "collectionpage"
        elif resource_type == "page":
            new_schema = _page_schema(resource)
            key = "webpage"
        else:
            logger.warning(f"No generator for type {resource_type} — deleting bad metafield")
            delete_metafield(mf["id"])
            fixes += 1
            if "null" in str(issues):
                stats["null_fixed"] += 1
            else:
                stats["invalid_fixed"] += 1
            continue

        new_issues = _issues(new_schema)
        if new_issues:
            logger.error(f"Generated schema still invalid for '{title}': {new_issues}")
            stats["errors"] += 1
            continue

        if upsert_schema_metafield(resource_type, rid, key, new_schema, existing_mf=mf):
            fixes += 1
            if schema is None:
                stats["null_fixed"] += 1
                logger.info(f"[FIXED null] {resource_type} '{title}'")
            else:
                stats["invalid_fixed"] += 1
                logger.info(f"[FIXED invalid] {resource_type} '{title}' — was: {issues}")
        else:
            stats["errors"] += 1
            logger.error(f"Failed to fix {resource_type} '{title}'")

    return fixes


# ── Main ──────────────────────────────────────────────────────────────────────

def run(mode: str, batch_size: int = 0, batch_index: int = 0, resource: str = "all"):
    hours = 48 if mode == "daily" else 0
    logger.info(f"Schema Fixer — mode={mode}")

    # Products
    if resource in ("all", "products"):
        logger.info("Scanning products...")
        from shopify_graphql import fetch_products_graphql
        products = fetch_products_graphql(hours)
        if mode in ('force', 'weekly') and batch_size > 0:
            start = batch_index * batch_size
            end = start + batch_size
            total_fetched = len(products)
            products = products[start:end]
            logger.info(f"Batch {batch_index}: fixing products {start} to {min(end, total_fetched)} of {total_fetched}")

        for p in products:
            fix_resource("product", p)

    # Collections
    if resource in ("all", "collections"):
        logger.info("Scanning collections...")
        from shopify_graphql import fetch_collections_graphql
        colls = fetch_collections_graphql(hours)
        for c in colls:
            fix_resource("collection", c)

    # Pages
    if resource in ("all", "pages"):
        logger.info("Scanning pages...")
        from shopify_graphql import fetch_pages_graphql
        pages = fetch_pages_graphql(hours)
        for p in pages:
            fix_resource("page", p)

    # Blog articles
    if resource in ("all", "blogs"):
        logger.info("Scanning blog articles...")
        from shopify_graphql import fetch_articles_graphql
        articles = fetch_articles_graphql(hours)
        for a in articles:
            fix_resource("article", a, extra=a["blog_handle"])

    # Report
    print("\n" + "=" * 60)
    print("SCHEMA FIXER REPORT")
    print("=" * 60)
    print(f"Mode:          {mode}")
    print(f"Scanned:       {stats['scanned']} metafields")
    print(f"Null fixed:    {stats['null_fixed']}")
    print(f"Invalid fixed: {stats['invalid_fixed']}")
    print(f"Errors:        {stats['errors']}")
    print("=" * 60)

    report = {
        "timestamp": datetime.now().isoformat(),
        "mode": mode,
        **stats
    }
    report_file = f"schema_fix_report_{ts}.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    logger.info(f"Report saved to {report_file}")

    if stats["errors"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--daily",  action="store_true")
    parser.add_argument("--weekly", action="store_true")
    parser.add_argument("--force",  action="store_true")
    parser.add_argument("--batch-size", type=int, default=0)
    parser.add_argument("--batch-index", type=int, default=0)
    parser.add_argument("--resource", type=str, default="all", choices=["all", "products", "collections", "pages", "blogs"])
    args = parser.parse_args()

    if args.daily:
        run("daily", batch_size=args.batch_size, batch_index=args.batch_index, resource=args.resource)
    elif args.weekly or args.force:
        mode = "force" if args.force else "weekly"
        run(mode, batch_size=args.batch_size, batch_index=args.batch_index, resource=args.resource)
    else:
        run("daily", batch_size=args.batch_size, batch_index=args.batch_index, resource=args.resource)

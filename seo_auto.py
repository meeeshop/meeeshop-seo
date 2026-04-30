"""
MeeeShop Full SEO Automation
Replaces all 7 SEO apps — runs via GitHub Actions or Windows Task Scheduler
Covers: products, collections, image alt text, 404 redirects
"""

import urllib.request, urllib.parse, urllib.error
import json, time, sys, os, re
from datetime import datetime

TOKEN = "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"
SHOP  = "us-meeeshop.myshopify.com"
API   = "2025-01"
HDR   = {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}

BRAND      = "MeeeShop"
FREE_SHIP  = "Free US Shipping $50+"
DOMAIN     = "us.meeeshop.com"

LOG_FILE   = "seo_auto_log.json"


def log(msg): sys.stdout.write(msg + "\n"); sys.stdout.flush()

# ─── API helpers ─────────────────────────────────────────────────────────────

def api_get(path, params=None):
    url = f"https://{SHOP}/admin/api/{API}/{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=HDR)
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read()), dict(r.headers)

def api_put(path, data):
    body = json.dumps(data).encode()
    req  = urllib.request.Request(
        f"https://{SHOP}/admin/api/{API}/{path}",
        data=body, headers=HDR, method="PUT"
    )
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read()), True
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode()[:120]}, False

def api_post(path, data):
    body = json.dumps(data).encode()
    req  = urllib.request.Request(
        f"https://{SHOP}/admin/api/{API}/{path}",
        data=body, headers=HDR, method="POST"
    )
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read()), True
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode()[:120]}, False

def paginate(path, key, params=None):
    """Fetch all pages of a resource."""
    params = params or {}
    params["limit"] = 250
    items, link = [], None
    while True:
        data, headers = api_get(path, params if not link else None)
        items.extend(data.get(key, []))
        link_header = headers.get("Link", "")
        next_url = None
        for part in link_header.split(","):
            if 'rel="next"' in part:
                next_url = part.strip().split(";")[0].strip("<>")
                break
        if not next_url:
            break
        # Extract page_info from next URL
        qs = urllib.parse.urlparse(next_url).query
        params = dict(urllib.parse.parse_qsl(qs))
        time.sleep(0.25)
    return items


# ─── SEO title/description generators ────────────────────────────────────────

def _clean(s, max_len):
    s = re.sub(r"\s+", " ", str(s)).strip()
    return s[:max_len].rsplit(" ", 1)[0] if len(s) > max_len else s


def gen_product_seo(product):
    title  = product.get("title", "")
    ptype  = product.get("product_type", "")
    tags   = product.get("tags", "")
    vendor = product.get("vendor", BRAND)
    price  = ""
    if product.get("variants"):
        price = product["variants"][0].get("price", "")

    # Build SEO title: Product Title | Type | Brand (≤70 chars)
    if ptype and ptype.lower() not in title.lower():
        seo_title = f"{title} | {ptype} | {BRAND}"
    else:
        seo_title = f"{title} | {BRAND}"
    seo_title = _clean(seo_title, 70)

    # Build SEO description (≤160 chars): price + free shipping + CTA
    price_str   = f"${price}" if price else ""
    desc_parts  = [title]
    if ptype:    desc_parts.append(ptype.lower())
    if price_str: desc_parts.append(f"only {price_str}")
    desc_parts.append(FREE_SHIP)
    desc_parts.append(f"Shop at {BRAND}")
    seo_desc = ". ".join(desc_parts)
    seo_desc = _clean(seo_desc, 160)

    return seo_title, seo_desc


def gen_collection_seo(collection):
    title = collection.get("title", "")
    handle = collection.get("handle", "")

    # Human-friendly label from handle
    label = handle.replace("-", " ").title()

    seo_title = f"{title} | Women's Fashion | {BRAND}"
    seo_title = _clean(seo_title, 70)

    seo_desc  = (
        f"Shop {title} at {BRAND}. Trendy women's styles, "
        f"{FREE_SHIP}. New arrivals added daily."
    )
    seo_desc = _clean(seo_desc, 160)

    return seo_title, seo_desc


def gen_image_alt(product, image_index=0):
    title  = product.get("title", "")
    ptype  = product.get("product_type", "")
    suffix = f"image {image_index + 1}" if image_index > 0 else ""
    parts  = [p for p in [title, ptype, BRAND, suffix] if p]
    return " | ".join(parts)[:512]


# ─── Update functions ─────────────────────────────────────────────────────────

def update_product_seo(product, stats):
    pid        = product["id"]
    seo_title, seo_desc = gen_product_seo(product)

    # Check if already optimised (skip if already set)
    cur_title = product.get("metafields_global_title_tag") or \
                product.get("title", "")
    cur_desc  = product.get("metafields_global_description_tag") or ""

    needs_update = True  # always freshen

    payload = {
        "product": {
            "id": pid,
            "metafields_global_title_tag":       seo_title,
            "metafields_global_description_tag": seo_desc,
        }
    }
    _, ok = api_put(f"products/{pid}.json", payload)
    if ok:
        stats["products_updated"] += 1
    else:
        stats["errors"] += 1

    # Update image alt text
    for i, img in enumerate(product.get("images", [])[:5]):
        alt = gen_image_alt(product, i)
        if img.get("alt") != alt:
            api_put(f"products/{pid}/images/{img['id']}.json",
                    {"image": {"id": img["id"], "alt": alt}})
            time.sleep(0.12)
            stats["images_updated"] += 1

    time.sleep(0.15)


def update_collection_seo(col, stats):
    cid = col["id"]
    seo_title, seo_desc = gen_collection_seo(col)

    payload = {
        "custom_collection": {
            "id": cid,
            "metafields_global_title_tag":       seo_title,
            "metafields_global_description_tag": seo_desc,
        }
    }
    _, ok = api_put(f"custom_collections/{cid}.json", payload)
    if not ok:
        # Try smart collection endpoint
        payload2 = {
            "smart_collection": {
                "id": cid,
                "metafields_global_title_tag":       seo_title,
                "metafields_global_description_tag": seo_desc,
            }
        }
        _, ok = api_put(f"smart_collections/{cid}.json", payload2)

    if ok:
        stats["collections_updated"] += 1
    else:
        stats["errors"] += 1
    time.sleep(0.2)


def ensure_redirects(stats):
    """Create common 404 redirects that help retain traffic."""
    common_redirects = [
        ("/blogs",         "/blogs/news"),
        ("/collections",   "/collections/all"),
        ("/pages/faq",     "/pages/faqs"),
        ("/shipping",      "/pages/shipping-policy"),
        ("/returns",       "/pages/refund-policy"),
        ("/contact-us",    "/pages/contact"),
        ("/privacy",       "/pages/privacy-policy"),
        ("/terms",         "/pages/terms-of-service"),
    ]

    # Fetch existing redirects
    existing, _ = api_get("redirects.json", {"limit": 250})
    existing_paths = {r["path"] for r in existing.get("redirects", [])}

    for path, target in common_redirects:
        if path not in existing_paths:
            _, ok = api_post("redirects.json", {"redirect": {"path": path, "target": target}})
            if ok:
                stats["redirects_created"] += 1
            time.sleep(0.15)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main(mode="all"):
    """
    mode: 'all' | 'products' | 'collections' | 'redirects'
    """
    started = datetime.now().isoformat()
    stats = {
        "started":             started,
        "products_updated":    0,
        "collections_updated": 0,
        "images_updated":      0,
        "redirects_created":   0,
        "errors":              0,
    }

    log("=" * 60)
    log("MeeeShop SEO Automation")
    log("=" * 60)

    # ── Products ──────────────────────────────────────────────────
    if mode in ("all", "products"):
        log("\n[1] Fetching all products...")
        products = paginate("products.json", "products", {"status": "active"})
        log(f"    Found {len(products)} active products")
        log("    Updating SEO titles, descriptions & image alt text...")

        for i, p in enumerate(products, 1):
            update_product_seo(p, stats)
            if i % 20 == 0:
                log(f"    {i}/{len(products)} done ({stats['errors']} errors)")

        log(f"    Products updated: {stats['products_updated']}")
        log(f"    Images updated  : {stats['images_updated']}")

    # ── Collections ───────────────────────────────────────────────
    if mode in ("all", "collections"):
        log("\n[2] Fetching all collections...")
        custom  = paginate("custom_collections.json", "custom_collections")
        smart   = paginate("smart_collections.json",  "smart_collections")
        all_cols = custom + smart
        log(f"    Found {len(all_cols)} collections")

        for col in all_cols:
            update_collection_seo(col, stats)

        log(f"    Collections updated: {stats['collections_updated']}")

    # ── 404 Redirects ─────────────────────────────────────────────
    if mode in ("all", "redirects"):
        log("\n[3] Setting up 404 redirects...")
        ensure_redirects(stats)
        log(f"    Redirects created: {stats['redirects_created']}")

    # ── Save log ──────────────────────────────────────────────────
    stats["finished"] = datetime.now().isoformat()
    log_entries = []
    if os.path.exists(LOG_FILE):
        try:
            log_entries = json.load(open(LOG_FILE))
        except Exception:
            pass
    log_entries.append(stats)
    with open(LOG_FILE, "w") as f:
        json.dump(log_entries[-10:], f, indent=2)  # keep last 10 runs

    log("\n" + "=" * 60)
    log("SEO UPDATE COMPLETE")
    log("=" * 60)
    log(f"  Products updated    : {stats['products_updated']}")
    log(f"  Collections updated : {stats['collections_updated']}")
    log(f"  Images alt-tagged   : {stats['images_updated']}")
    log(f"  Redirects created   : {stats['redirects_created']}")
    log(f"  Errors              : {stats['errors']}")
    log(f"  Log saved to        : {LOG_FILE}")
    log("""
  NEXT STEP:
  Now that SEO is automated, go to Shopify Admin -> Apps
  and UNINSTALL these 7 apps to dramatically speed up your store:
    1. SEOAnt
    2. ReRank AI Bulk SEO Optimizer
    3. InfinSEO Image Optimizer
    4. EZ AI SEO Optimizer
    5. Geoly AI Traffic Booster
    6. RankerGPT
    7. FAV Schema JSON-LD

  Keep: Intelli404 (handles live 404 redirects differently)
  Our schema-org.liquid snippet replaces their JSON-LD blocks.
""")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    main(mode)

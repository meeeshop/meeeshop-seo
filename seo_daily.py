"""
MeeeShop SEO Automation
Fixes per Google standards:
  - Meta title  : Product Title | Category | MeeeShop  (max 60 chars)
  - Meta desc   : 150-160 char benefit-led sentence with CTA
  - Image alt   : Descriptive keyword-rich text (max 125 chars)
  - Title case  : Google-accepted capitalisation
  - Handle/URL  : clean slug + 301 redirect if changed
  - JSON-LD     : Injects structured data snippet into live theme (one-time)
"""
import os, re, json, time, argparse
import requests
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()

STORE  = os.getenv("SHOPIFY_STORE")
TOKEN  = os.getenv("SHOPIFY_ACCESS_TOKEN")
HEADS  = {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}
BASE   = f"https://{STORE}/admin/api/2024-01"
BRAND  = "MeeeShop"
SITE   = "https://us.meeeshop.com"


# ══════════════════════════════════════════════════════════════════════════════
# TEXT HELPERS
# ══════════════════════════════════════════════════════════════════════════════

SMALL_WORDS = {
    'a','an','the','and','but','or','for','nor','on','at','to','by',
    'in','of','up','as','if','so','yet','with','from','into','via',
    'per','than','over','also','plus','vs','w'
}

def title_case(text):
    words = text.strip().split()
    if not words:
        return text
    out = []
    for i, w in enumerate(words):
        if re.match(r'^[A-Z0-9]{3,}$', w):   # keep acronyms
            out.append(w)
        elif i == 0 or i == len(words) - 1:
            out.append(w.capitalize())
        elif w.lower() in SMALL_WORDS:
            out.append(w.lower())
        else:
            out.append(w.capitalize())
    return ' '.join(out)


def slugify(text):
    s = re.sub(r'[^a-z0-9\s-]', '', text.lower())
    s = re.sub(r'[\s_]+', '-', s.strip())
    return re.sub(r'-+', '-', s)[:70].strip('-')


def strip_html(html):
    return re.sub(r'<[^>]+>', ' ', html or '').strip()


def truncate(text, n):
    return text if len(text) <= n else text[:n-1].rsplit(' ', 1)[0] + '…'


# ── Category detection ────────────────────────────────────────────────────────
CATEGORIES = {
    ('dress','gown','midi','maxi','sundress','shift'):   ('Dresses',   'dress'),
    ('top','blouse','shirt','tee','tank','cami','tunic'):('Tops',      'top'),
    ('jean','pant','short','legging','jogger','trouser'):('Bottoms',   'bottom'),
    ('jacket','coat','blazer','sweater','hoodie','cardigan','pullover'):
                                                        ('Outerwear', 'layer'),
    ('skirt',):                                         ('Skirts',    'skirt'),
    ('romper','jumpsuit','bodysuit','playsuit'):         ('One-Pieces','one-piece'),
    ('bag','purse','handbag','tote','crossbody','sling'):('Bags',      'bag'),
    ('shoe','boot','heel','sandal','sneaker','flat'):    ('Shoes',     'shoe'),
}

def detect_cat(title):
    t = title.lower()
    for keys, (cat, word) in CATEGORIES.items():
        if any(k in t for k in keys):
            return cat, word
    return 'Women\'s Fashion', 'piece'


# ── Meta title (Google standard: ≤60 chars) ───────────────────────────────────
def build_meta_title(title):
    cat, _ = detect_cat(title)
    # Format: Product Title | Category | Brand
    full  = f"{title} | {cat} | {BRAND}"
    if len(full) <= 60:
        return full
    # Shorten: Product Title | Brand
    short = f"{title} | {BRAND}"
    if len(short) <= 60:
        return short
    # Truncate title
    max_title = 60 - len(f" | {BRAND}")
    return f"{title[:max_title].rsplit(' ', 1)[0]} | {BRAND}"


# ── Meta description (Google standard: 150-160 chars) ─────────────────────────
META_DESC_TEMPLATES = [
    "Shop the {title} at {brand} — affordable women's {word} with free US shipping on orders over $50. Easy 30-day returns.",
    "Discover the {title} at {brand}. Stylish, quality women's fashion delivered fast across the USA. Free shipping $50+.",
    "Get the {title} from {brand}. Trendy women's {word} at unbeatable prices. Free US shipping on $50+ orders. Shop now!",
    "The {title} is a must-have from {brand}. Quality women's fashion with free US shipping & easy returns. Order today!",
]

def build_meta_desc(title):
    _, word = detect_cat(title)
    import random
    tpl  = random.choice(META_DESC_TEMPLATES)
    desc = tpl.format(title=title, brand=BRAND, word=word)
    return truncate(desc, 160)


# ── Image alt text (Google standard: descriptive, ≤125 chars) ─────────────────
def build_alt(title, variant_hint='', idx=0):
    base = title
    if variant_hint:
        base += f" {variant_hint}"
    _, word = detect_cat(title)
    alt = f"{base} - Women's {word.capitalize()} | {BRAND}"
    if idx > 0:
        alt = f"{base} View {idx + 1} - Women's {word.capitalize()} | {BRAND}"
    return alt[:125]


# ── SEO description (product body_html) ───────────────────────────────────────
def build_description(product):
    title    = product['title']
    existing = strip_html(product.get('body_html', ''))
    _, word  = detect_cat(title)

    footer = (
        f"<p>Shop <strong>{title}</strong> and hundreds more styles at "
        f"<strong>{BRAND}</strong> — America's favourite women's fashion boutique. "
        f"Free shipping on US orders over $50. Easy 30-day returns.</p>"
    )

    if len(existing) >= 150:
        return (product.get('body_html') or '') + '\n' + footer

    return (
        f"<p>Elevate your wardrobe with the <strong>{title}</strong> — "
        f"a must-have {word} for every stylish woman. Designed for comfort "
        f"and versatility, it works seamlessly from day to night, office to weekend.</p>"
        f"<ul>"
        f"<li>Premium quality materials for all-day comfort</li>"
        f"<li>True-to-size fit that flatters every body type</li>"
        f"<li>Versatile styling — dress up or down for any occasion</li>"
        f"<li>Fast shipping across the USA</li>"
        f"</ul>"
        + footer
    )


# ══════════════════════════════════════════════════════════════════════════════
# SHOPIFY API HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _check_rate(r):
    lim  = r.headers.get('X-Shopify-Shop-Api-Call-Limit', '0/40')
    used = int(lim.split('/')[0])
    if used >= 36:
        time.sleep(0.6)


def api_get(path, params=None):
    r = requests.get(f"{BASE}{path}", headers=HEADS, params=params)
    r.raise_for_status(); _check_rate(r)
    return r.json()


def api_put(path, body):
    r = requests.put(f"{BASE}{path}", headers=HEADS, json=body)
    r.raise_for_status(); _check_rate(r)
    return r.json()


def api_post(path, body):
    r = requests.post(f"{BASE}{path}", headers=HEADS, json=body)
    _check_rate(r)
    return r


def fetch_products(updated_since=None):
    products, url = [], f"{BASE}/products.json?limit=250&status=active"
    if updated_since:
        url += f"&updated_at_min={updated_since}"
    while url:
        r = requests.get(url, headers=HEADS); r.raise_for_status(); _check_rate(r)
        products.extend(r.json().get('products', []))
        nxt = [p.split(';')[0].strip().strip('<>') for p in r.headers.get('Link','').split(',') if 'rel="next"' in p]
        url = nxt[0] if nxt else None
    return products


# ── Metafields (meta title + meta description) ────────────────────────────────
def get_metafields(pid):
    data = api_get(f"/products/{pid}/metafields.json")
    return {f"{m['namespace']}.{m['key']}": m for m in data.get('metafields', [])}


def upsert_metafield(pid, namespace, key, value, mf_type, existing_mfs):
    full_key = f"{namespace}.{key}"
    if full_key in existing_mfs:
        mid = existing_mfs[full_key]['id']
        api_put(f"/metafields/{mid}.json",
                {"metafield": {"id": mid, "value": value, "type": mf_type}})
    else:
        api_post(f"/products/{pid}/metafields.json",
                 {"metafield": {"namespace": namespace, "key": key,
                                "value": value, "type": mf_type}})


def set_seo_metafields(pid, meta_title, meta_desc, existing_mfs):
    upsert_metafield(pid, "global", "title_tag",       meta_title, "single_line_text_field", existing_mfs)
    upsert_metafield(pid, "global", "description_tag", meta_desc,  "multi_line_text_field",  existing_mfs)


# ── Image alt text ────────────────────────────────────────────────────────────
def update_image_alt(pid, iid, alt):
    r = requests.put(f"{BASE}/products/{pid}/images/{iid}.json",
                     headers=HEADS, json={"image": {"id": iid, "alt": alt}})
    _check_rate(r)
    return r.status_code == 200


# ── Redirects ─────────────────────────────────────────────────────────────────
def create_redirect(old, new):
    r = requests.get(f"{BASE}/redirects.json", headers=HEADS,
                     params={"path": f"/products/{old}"})
    if r.json().get('redirects'):
        return False
    api_post("/redirects.json",
             {"redirect": {"path": f"/products/{old}", "target": f"/products/{new}"}})
    return True


# ══════════════════════════════════════════════════════════════════════════════
# JSON-LD THEME INJECTION  (one-time, idempotent)
# ══════════════════════════════════════════════════════════════════════════════

JSONLD_SNIPPET = r"""{% comment %}meeeshop-jsonld v1 — auto-generated, do not remove{% endcomment %}
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@graph": [
    {
      "@type": "Organization",
      "@id": "{{ shop.url }}/#organization",
      "name": {{ shop.name | json }},
      "url": "{{ shop.url }}",
      "logo": {
        "@type": "ImageObject",
        "url": "{{ shop.url }}/cdn/shop/files/logo.png"
      },
      "sameAs": ["https://www.instagram.com/meeeshop","https://www.tiktok.com/@meeeshop"]
    },
    {
      "@type": "WebSite",
      "@id": "{{ shop.url }}/#website",
      "url": "{{ shop.url }}",
      "name": {{ shop.name | json }},
      "publisher": {"@id": "{{ shop.url }}/#organization"},
      "potentialAction": {
        "@type": "SearchAction",
        "target": {"@type": "EntryPoint", "urlTemplate": "{{ shop.url }}/search?q={search_term_string}"},
        "query-input": "required name=search_term_string"
      }
    }
    {%- if template.name == 'product' -%}
    ,{
      "@type": "Product",
      "@id": "{{ shop.url }}/products/{{ product.handle }}",
      "name": {{ product.title | json }},
      "url": "{{ shop.url }}/products/{{ product.handle }}",
      "description": {{ product.description | strip_html | truncate: 500 | json }},
      "brand": {"@type": "Brand", "name": {{ shop.name | json }}},
      "image": [{% for img in product.images %}"{{ img | image_url: width: 1200 }}"{% unless forloop.last %},{% endunless %}{% endfor %}],
      "offers": {
        "@type": "AggregateOffer",
        "priceCurrency": "USD",
        "lowPrice": "{{ product.price_min | money_without_currency | remove: ',' }}",
        "highPrice": "{{ product.price_max | money_without_currency | remove: ',' }}",
        "offerCount": {{ product.variants.size }},
        "offers": [
          {%- for v in product.variants -%}
          {
            "@type": "Offer",
            "name": {{ v.title | json }},
            "sku": {{ v.sku | json }},
            "price": "{{ v.price | money_without_currency | remove: ',' }}",
            "priceCurrency": "USD",
            "availability": "https://schema.org/{% if v.available %}InStock{% else %}OutOfStock{% endif %}",
            "url": "{{ shop.url }}/products/{{ product.handle }}?variant={{ v.id }}",
            "seller": {"@type": "Organization", "name": {{ shop.name | json }}}
          }{%- unless forloop.last -%},{%- endunless -%}
          {%- endfor -%}
        ]
      }
    }
    ,{
      "@type": "BreadcrumbList",
      "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "Home", "item": "{{ shop.url }}"},
        {%- if collection -%}
        {"@type": "ListItem", "position": 2, "name": {{ collection.title | json }}, "item": "{{ shop.url }}/collections/{{ collection.handle }}"},
        {"@type": "ListItem", "position": 3, "name": {{ product.title | json }}}
        {%- else -%}
        {"@type": "ListItem", "position": 2, "name": {{ product.title | json }}}
        {%- endif -%}
      ]
    }
    {%- endif -%}
    {%- if template.name == 'collection' -%}
    ,{
      "@type": "CollectionPage",
      "name": {{ collection.title | json }},
      "url": "{{ shop.url }}/collections/{{ collection.handle }}",
      "description": {{ collection.description | strip_html | json }},
      "publisher": {"@id": "{{ shop.url }}/#organization"}
    }
    ,{
      "@type": "BreadcrumbList",
      "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "Home", "item": "{{ shop.url }}"},
        {"@type": "ListItem", "position": 2, "name": {{ collection.title | json }}, "item": "{{ shop.url }}/collections/{{ collection.handle }}"}
      ]
    }
    {%- endif -%}
    {%- if template.name == 'index' -%}
    ,{
      "@type": "WebPage",
      "@id": "{{ shop.url }}/#homepage",
      "url": "{{ shop.url }}",
      "name": {{ shop.name | json }},
      "isPartOf": {"@id": "{{ shop.url }}/#website"},
      "about": {"@id": "{{ shop.url }}/#organization"}
    }
    {%- endif -%}
  ]
}
</script>"""


def get_live_theme_id():
    for t in api_get("/themes.json").get('themes', []):
        if t.get('role') == 'main':
            return t['id']
    return None


def get_asset(theme_id, key):
    r = requests.get(f"{BASE}/themes/{theme_id}/assets.json",
                     headers=HEADS, params={"asset[key]": key})
    if r.status_code == 200:
        return r.json().get('asset', {}).get('value', '')
    return None


def put_asset(theme_id, key, value):
    r = requests.put(f"{BASE}/themes/{theme_id}/assets.json",
                     headers=HEADS, json={"asset": {"key": key, "value": value}})
    _check_rate(r)
    return r.status_code in (200, 201)


def inject_jsonld(theme_id):
    """Create JSON-LD snippet and include it in theme.liquid. Idempotent."""
    SNIPPET_KEY = "snippets/meeeshop-jsonld.liquid"
    MARKER      = "meeeshop-jsonld"

    # 1. Upload the snippet file
    if put_asset(theme_id, SNIPPET_KEY, JSONLD_SNIPPET):
        print("  JSON-LD snippet uploaded to theme")
    else:
        print("  ! Could not upload JSON-LD snippet")
        return False

    # 2. Add render tag to layout/theme.liquid (before </head>)
    layout = get_asset(theme_id, "layout/theme.liquid")
    if not layout:
        print("  ! Could not read layout/theme.liquid")
        return False

    if MARKER in layout:
        print("  JSON-LD already present in theme.liquid — skipped")
        return True

    tag    = "{% render 'meeeshop-jsonld' %}"
    layout = layout.replace("</head>", f"  {tag}\n</head>", 1)

    if put_asset(theme_id, "layout/theme.liquid", layout):
        print("  JSON-LD render tag added to layout/theme.liquid")
        return True

    print("  ! Could not update layout/theme.liquid")
    return False


# ══════════════════════════════════════════════════════════════════════════════
# CORE PRODUCT PROCESSOR
# ══════════════════════════════════════════════════════════════════════════════

def process(product, stats, log):
    pid        = product['id']
    old_title  = product['title']
    old_handle = product['handle']
    old_desc   = strip_html(product.get('body_html', ''))
    changes    = []
    missing    = []

    # ── 1. Title Case ─────────────────────────────────────────────────────────
    new_title    = title_case(old_title)
    prod_updates = {}
    if new_title != old_title:
        prod_updates['title'] = new_title
        stats['titles'] += 1
        changes.append(f"title: '{old_title}' -> '{new_title}'")

    # ── 2. Body description ───────────────────────────────────────────────────
    if len(old_desc) < 150:
        missing.append(f"description (was {len(old_desc)} chars)")
        prod_updates['body_html'] = build_description(product)
        stats['descriptions'] += 1
        changes.append("description: added SEO body")

    # ── 3. URL handle + redirect ──────────────────────────────────────────────
    final_title  = prod_updates.get('title', old_title)
    ideal_handle = slugify(final_title)
    if ideal_handle and ideal_handle != old_handle and len(ideal_handle) > 4:
        missing.append(f"handle (was '{old_handle}')")
        prod_updates['handle'] = ideal_handle
        if create_redirect(old_handle, ideal_handle):
            stats['redirects'] += 1
            changes.append(f"redirect: /products/{old_handle} -> /products/{ideal_handle}")
        stats['handles'] += 1
        changes.append(f"handle: '{old_handle}' -> '{ideal_handle}'")

    # Apply product updates
    if prod_updates:
        try:
            api_put(f"/products/{pid}.json", {"product": prod_updates})
            stats['products'] += 1
        except Exception as e:
            print(f"    ! Update failed: {e}")
            return

    # ── 4. Meta title + Meta description ─────────────────────────────────────
    display_title = prod_updates.get('title', old_title)
    meta_title    = build_meta_title(display_title)
    meta_desc     = build_meta_desc(display_title)

    try:
        existing_mfs = get_metafields(pid)
        cur_mtitle   = existing_mfs.get('global.title_tag',       {}).get('value', '')
        cur_mdesc    = existing_mfs.get('global.description_tag', {}).get('value', '')

        if not cur_mtitle:
            missing.append("meta title (missing)")
        if not cur_mdesc:
            missing.append("meta description (missing)")

        if cur_mtitle != meta_title:
            set_seo_metafields(pid, meta_title, meta_desc, existing_mfs)
            stats['meta_titles'] += 1
            stats['meta_descs']  += 1
            changes.append(f"meta title: '{meta_title}'")
            changes.append(f"meta desc:  '{meta_desc[:80]}...'")
        elif cur_mdesc != meta_desc:
            upsert_metafield(pid, "global", "description_tag", meta_desc,
                             "multi_line_text_field", existing_mfs)
            stats['meta_descs'] += 1
            changes.append(f"meta desc updated")
    except Exception as e:
        print(f"    ! Metafields error: {e}")

    # ── 5. Image alt text ─────────────────────────────────────────────────────
    colors = []
    for v in product.get('variants', []):
        opt = v.get('option1') or ''
        if opt and opt.lower() not in ('default title', 'default', ''):
            colors.append(opt)

    img_alts_fixed = 0
    for i, img in enumerate(product.get('images', [])):
        hint = colors[i] if i < len(colors) else ''
        alt  = build_alt(display_title, hint, i)
        if img.get('alt', '') != alt:
            if not img.get('alt'):
                missing.append(f"img[{i}] alt (missing)")
            if update_image_alt(pid, img['id'], alt):
                stats['alts'] += 1
                img_alts_fixed += 1
                changes.append(f"img[{i}] alt: '{alt}'")

    # ── Log entry ─────────────────────────────────────────────────────────────
    entry = {
        "product": old_title,
        "url":     f"{SITE}/products/{old_handle}",
        "missing": missing,
        "fixed":   changes,
    }
    log.append(entry)

    if missing:
        print(f"  Missing: {', '.join(missing)}")
    if changes:
        for c in changes[:4]:          # print first 4 changes
            print(f"  + {c}")
        if len(changes) > 4:
            print(f"  + ...and {len(changes)-4} more")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--all',        action='store_true', help='Full catalog scan')
    ap.add_argument('--hours',      type=int, default=25, help='Lookback window')
    ap.add_argument('--limit',      type=int, default=0,  help='Max products (0=all)')
    ap.add_argument('--skip-jsonld',action='store_true', help='Skip JSON-LD injection')
    args = ap.parse_args()

    print("=== MeeeShop SEO Automation ===\n")

    # ── JSON-LD theme injection (idempotent — safe to run every time) ─────────
    if not args.skip_jsonld:
        print("Checking JSON-LD structured data in theme...")
        tid = get_live_theme_id()
        if tid:
            inject_jsonld(tid)
        else:
            print("  ! Could not find live theme")
        print()

    # ── Product SEO ───────────────────────────────────────────────────────────
    if args.all:
        print("Mode: FULL CATALOG (fixing all missing/broken SEO fields)")
        since = None
    else:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=args.hours)
        since  = cutoff.strftime('%Y-%m-%dT%H:%M:%SZ')
        print(f"Mode: SMART DAILY (products updated since {since})")

    products = fetch_products(since)
    if args.limit:
        products = products[:args.limit]
    print(f"Products to check: {len(products)}\n")

    stats = {
        'products': 0, 'titles': 0, 'descriptions': 0,
        'meta_titles': 0, 'meta_descs': 0,
        'handles': 0, 'redirects': 0, 'alts': 0
    }
    log = []

    for i, p in enumerate(products, 1):
        mfs        = get_metafields(p['id'])
        cur_mtitle = mfs.get('global.title_tag',       {}).get('value', '')
        cur_mdesc  = mfs.get('global.description_tag', {}).get('value', '')
        needs_seo  = (
            title_case(p['title']) != p['title']
            or len(strip_html(p.get('body_html', ''))) < 150
            or not cur_mtitle
            or not cur_mdesc
            or any(len(img.get('alt', '')) < 10 for img in p.get('images', []))
        )
        if not needs_seo:
            print(f"[{i}/{len(products)}] OK  {p['title'][:55]}")
            continue
        print(f"[{i}/{len(products)}] FIX {p['title'][:55]}")
        process(p, stats, log)

    # ── Report ────────────────────────────────────────────────────────────────
    print("\n--- SEO Report -------------------------------------------")
    labels = {
        'products':     'Products updated',
        'titles':       'Title case fixes',
        'descriptions': 'Descriptions added',
        'meta_titles':  'Meta titles set',
        'meta_descs':   'Meta descs set',
        'handles':      'Handles updated',
        'redirects':    'Redirects created',
        'alts':         'Image alts fixed',
    }
    for k, label in labels.items():
        print(f"  {label:<22}: {stats[k]}")
    print("--------------------------------------------------")

    # ── Detailed change log ───────────────────────────────────────────────────
    if log:
        print("\n--- Products Fixed ---")
        for entry in log:
            print(f"\n  Product : {entry['product']}")
            print(f"  URL     : {entry['url']}")
            if entry['missing']:
                print(f"  Missing : {', '.join(entry['missing'])}")
            for fix in entry['fixed']:
                print(f"  Fixed   : {fix}")

    report = {
        **stats,
        "run_at":   datetime.now(timezone.utc).isoformat(),
        "mode":     "all" if args.all else "daily",
        "products_fixed": log,
    }
    fname = f"seo_report_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    with open(fname, 'w') as f:
        json.dump(report, f, indent=2)
    print(f"\nFull report saved: {fname}")


if __name__ == "__main__":
    main()

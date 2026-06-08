"""
MeeeShop SEO Automation v2.0+
Google-optimized product, collection, page, and blog SEO with 7-day returns

Workflow modes:
  --daily   : Products + Pages + Collections + Blog posts updated in last 48hrs
  --weekly  : All items missed by daily + add missing descriptions
  --force   : Complete store overhaul (normalize all SEO fields)

Enhancements:
  - Meta title  : Product | Category | us.meeeshop.com (max 60 chars, keyword-rich)
  - Meta desc   : 155 chars, keyword-rich, 7-day returns, free shipping mention
  - Image alt   : [Product] [type keyword] (category) - shop at us.meeeshop (max 125 chars)
  - Description : Natural keyword embedding + size chart (auto-detect existing) + features
  - Size charts : Auto-detect existing table, create standard if missing
  - JSON-LD     : Product, BreadcrumbList, CollectionPage, FAQPage, LocalBusiness
  - Social      : Pinterest & YouTube only (removed Instagram/TikTok)
  - Resources   : Products, Pages, Collections, Blog Posts
"""
import os, re, json, time, argparse, sys
import requests
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from secrets_manager import inject_to_env, get_secret
inject_to_env()

STORE  = get_secret("SHOPIFY_STORE")
TOKEN  = get_secret("SHOPIFY_ACCESS_TOKEN")
HEADS  = {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}
BASE   = f"https://{STORE}/admin/api/2024-01"
BRAND  = "us.meeeshop.com"
SITE   = "https://us.meeeshop.com"
RETURN_POLICY = "7-day return policy"
DISPLAY_BRAND = "us.meeeshop"  # For human-readable text (not in meta title)

# Return policy is 7 days ONLY. Any other duration (30-day, 14-day, 60-day, etc.)
# triggers an overwrite to the 7-day policy.
STALE_RETURN_RE = re.compile(r'\b(?!7[\s-]*day)\d+[\s-]*day[\s-]*(return|refund|exchange|policy)', re.IGNORECASE)

def has_stale_return_policy(text):
    """True if text mentions any return policy other than 7-day."""
    if not text:
        return False
    return bool(STALE_RETURN_RE.search(text))


# ══════════════════════════════════════════════════════════════════════════════
# TEXT HELPERS
# ══════════════════════════════════════════════════════════════════════════════

SMALL_WORDS = {
    'a','an','the','and','but','or','for','nor','on','at','to','by',
    'in','of','up','as','if','so','yet','with','from','into','via',
    'per','than','over','also','plus','vs','w'
}

ACRONYMS = {'USA','UK','US','UV','XL','XS','XXL','XXXL','2XL','3XL','NYC','LA','NY','DJ','TV','PC'}

def title_case(text):
    words = text.strip().split()
    if not words:
        return text
    out = []
    for i, w in enumerate(words):
        upper = w.upper()
        if upper in ACRONYMS:           # known acronyms stay uppercase
            out.append(upper)
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
    # Format: Product Title | Category | Brand (with .com for SEO)
    full  = f"{title} | {cat} | {BRAND}"
    if len(full) <= 60:
        return full
    # Shorten: Product Title | Brand (with .com)
    short = f"{title} | {BRAND}"
    if len(short) <= 60:
        return short
    # Truncate title to fit
    max_title = 60 - len(f" | {BRAND}")
    truncated_title = title[:max_title].rsplit(' ', 1)[0] if ' ' in title[:max_title] else title[:max_title-1]
    return f"{truncated_title} | {BRAND}"


# ── Extract keywords naturally from title/description ──────────────────────────
def extract_keywords(text):
    """Extract meaningful keywords (2+ chars) from text for natural embedding."""
    stopwords = {'and','the','a','an','or','for','of','in','to','is','was','are'}
    words = re.findall(r'\b[a-z]+\b', text.lower())
    return [w for w in words if w not in stopwords and len(w) > 2][:3]

# ── Meta description (Google standard: 155 chars) ──────────────────────────────
META_DESC_TEMPLATES = [
    "Shop {keywords_str} {word} at {brand}. Quality women's fashion with free US shipping & 7-day returns. Affordable, stylish, fast delivery.",
    "Discover {keywords_str} {word} at {brand} — premium women's wear for comfort & style. Free US shipping. 7-day returns.",
    "Get {keywords_str} women's {word} from {brand}. Trendy, affordable styles at great prices. Free shipping, 7-day returns. Shop today!",
    "Premium {keywords_str} {word} from {brand}: quality women's fashion with free shipping & 7-day returns. Shop now!",
]

def build_meta_desc(title):
    """Deterministic meta description: same title always produces same output (so validation can use exact match)."""
    _, word = detect_cat(title)
    keywords = extract_keywords(title)
    keywords_str = ' '.join(keywords) if keywords else (title.split()[0] if title.split() else "women's")
    # Deterministic template selection: pick by hash of title (no randomness)
    idx  = sum(ord(c) for c in title) % len(META_DESC_TEMPLATES)
    tpl  = META_DESC_TEMPLATES[idx]
    desc = tpl.format(title=title, brand=BRAND, word=word, keywords_str=keywords_str)
    return truncate(desc, 155)


# ── Image alt text (Google standard: descriptive, ≤125 chars) ─────────────────
def build_alt(title, variant_hint='', idx=0):
    cat, word = detect_cat(title)
    keywords = extract_keywords(title)
    keywords_str = ' '.join(keywords) if keywords else ''
    # Include product type keyword naturally in ALT text
    if variant_hint and variant_hint.lower() != 'default':
        alt = f"{keywords_str} {title} {variant_hint} ({word}) - shop at {DISPLAY_BRAND}" if keywords_str else f"{title} {variant_hint} ({word}) - shop at {DISPLAY_BRAND}"
    else:
        alt = f"{keywords_str} {title} ({word}) - shop at {DISPLAY_BRAND}" if keywords_str else f"{title} ({word}) - shop at {DISPLAY_BRAND}"
    if idx > 0:
        alt = f"{keywords_str} {title} view {idx + 1} ({word}) - shop at {DISPLAY_BRAND}" if keywords_str else f"{title} view {idx + 1} ({word}) - shop at {DISPLAY_BRAND}"
    return alt[:125].strip()


# ── Detect existing size table in HTML ────────────────────────────────────────
def has_size_table(html):
    """Check if HTML already contains a size/measurement table."""
    return bool(re.search(r'<table[^>]*>.*?<t[hd][^>]*>.*?(size|bust|waist|hip|length|chest|sleeve)', html or '', re.IGNORECASE | re.DOTALL))


def extract_size_table(html):
    """Extract the existing size table block (including any 'Size Chart' heading before it). Returns HTML string or ''."""
    if not html:
        return ''
    # Match optional <h2/h3> heading containing 'size' immediately followed by a <table>
    m = re.search(
        r'(<h[1-6][^>]*>[^<]*size[^<]*</h[1-6]>\s*)?<table[\s\S]*?</table>',
        html, re.IGNORECASE
    )
    if not m:
        return ''
    block = m.group(0)
    # Confirm this table is actually a size table
    if not has_size_table(block):
        return ''
    return block

# ── Build size chart based on product type ────────────────────────────────────
def build_size_chart(word):
    """Create appropriate size chart based on product category."""
    # Standard women's clothing measurements (S/M/L)
    size_chart = (
        f"<h3>Size Chart</h3>"
        f"<table style='border-collapse: collapse; width: 100%;'>"
        f"<tr style='border: 1px solid #ddd;'>"
        f"<th style='border: 1px solid #ddd; padding: 8px; text-align: left;'>Size</th>"
        f"<th style='border: 1px solid #ddd; padding: 8px; text-align: left;'>Bust</th>"
        f"<th style='border: 1px solid #ddd; padding: 8px; text-align: left;'>Waist</th>"
        f"<th style='border: 1px solid #ddd; padding: 8px; text-align: left;'>Hip</th>"
        f"</tr>"
        f"<tr style='border: 1px solid #ddd;'>"
        f"<td style='border: 1px solid #ddd; padding: 8px;'>S</td>"
        f"<td style='border: 1px solid #ddd; padding: 8px;'>35-36</td>"
        f"<td style='border: 1px solid #ddd; padding: 8px;'>27-28</td>"
        f"<td style='border: 1px solid #ddd; padding: 8px;'>35-37</td>"
        f"</tr>"
        f"<tr style='border: 1px solid #ddd;'>"
        f"<td style='border: 1px solid #ddd; padding: 8px;'>M</td>"
        f"<td style='border: 1px solid #ddd; padding: 8px;'>37-38</td>"
        f"<td style='border: 1px solid #ddd; padding: 8px;'>29-30</td>"
        f"<td style='border: 1px solid #ddd; padding: 8px;'>38-39</td>"
        f"</tr>"
        f"<tr style='border: 1px solid #ddd;'>"
        f"<td style='border: 1px solid #ddd; padding: 8px;'>L</td>"
        f"<td style='border: 1px solid #ddd; padding: 8px;'>39-40</td>"
        f"<td style='border: 1px solid #ddd; padding: 8px;'>31-32</td>"
        f"<td style='border: 1px solid #ddd; padding: 8px;'>40-41</td>"
        f"</tr>"
        f"</table>"
    )
    return size_chart

# ── SEO description with keywords + size chart ───────────────────────────────
def build_description(product, force=False):
    title    = product['title']
    html_body = product.get('body_html', '')
    existing = strip_html(html_body)
    cat, word = detect_cat(title)
    keywords = extract_keywords(title)
    keywords_str = ' '.join(keywords) if keywords else ''

    intro = (
        f"<p><strong>Discover the {keywords_str} {title} at {DISPLAY_BRAND}.</strong> This {word} combines "
        f"exceptional quality with style, perfect for women looking for women's {word}s. "
        f"Enjoy free US shipping and easy returns on every order.</p>"
    )

    features = (
        f"<h3>Product Features</h3>"
        f"<ul>"
        f"<li>Premium quality materials for lasting durability and comfort</li>"
        f"<li>Stylish design that works for everyday wear and special occasions</li>"
        f"<li>Perfect for women who value quality and fashion</li>"
        f"<li>Free shipping on all US orders</li>"
        f"<li>{RETURN_POLICY}</li>"
        f"<li>Shop {word}s for women at {DISPLAY_BRAND}</li>"
        f"</ul>"
    )

    why_choose = (
        f"<h3>Why Choose {keywords_str} {title} at {DISPLAY_BRAND}?</h3>"
        f"<p>Looking for women's fashion? Our curated selection of {word}s for women features "
        f"quality that lasts. Whether you're shopping for everyday essentials or something special, "
        f"we have options for every style and budget.</p>"
        f"<p><strong>Shop {word}s for women. Free US shipping. {RETURN_POLICY}. "
        f"Shop {DISPLAY_BRAND} today.</strong></p>"
    )

    # Preserve existing size table verbatim; otherwise build the standard one
    existing_table = extract_size_table(html_body)
    if existing_table:
        size_chart = existing_table
    else:
        size_chart = build_size_chart(word)

    if not force and len(existing) >= 500:
        return (product.get('body_html') or '')

    return intro + features + why_choose + size_chart


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
    r.raise_for_status(); _check_rate(r)
    return r.json()


def fetch_products(created_since=None):
    """Fetch active products created since cutoff (catches new dropship imports by any vendor)."""
    products, url = [], f"{BASE}/products.json?limit=250&status=active"
    if created_since:
        url += f"&created_at_min={created_since}"
    while url:
        r = requests.get(url, headers=HEADS); r.raise_for_status(); _check_rate(r)
        products.extend(r.json().get('products', []))
        nxt = [p.split(';')[0].strip().strip('<>') for p in r.headers.get('Link','').split(',') if 'rel="next"' in p]
        url = nxt[0] if nxt else None
    return products


def fetch_pages(published_since=None):
    """Fetch pages published since cutoff."""
    pages, url = [], f"{BASE}/pages.json?limit=250"
    if published_since:
        url += f"&published_at_min={published_since}"
    while url:
        r = requests.get(url, headers=HEADS); r.raise_for_status(); _check_rate(r)
        pages.extend(r.json().get('pages', []))
        nxt = [p.split(';')[0].strip().strip('<>') for p in r.headers.get('Link','').split(',') if 'rel="next"' in p]
        url = nxt[0] if nxt else None
    return pages


def fetch_collections(created_since=None):
    """Fetch custom collections created since cutoff."""
    collections, url = [], f"{BASE}/custom_collections.json?limit=250"
    if created_since:
        url += f"&created_at_min={created_since}"
    while url:
        r = requests.get(url, headers=HEADS); r.raise_for_status(); _check_rate(r)
        collections.extend(r.json().get('custom_collections', []))
        nxt = [p.split(';')[0].strip().strip('<>') for p in r.headers.get('Link','').split(',') if 'rel="next"' in p]
        url = nxt[0] if nxt else None
    return collections


def fetch_articles(published_since=None):
    """Fetch blog articles published since cutoff."""
    articles, url = [], f"{BASE}/blogs.json?limit=250"

    blogs = []
    while url:
        r = requests.get(url, headers=HEADS); r.raise_for_status(); _check_rate(r)
        blogs.extend(r.json().get('blogs', []))
        nxt = [p.split(';')[0].strip().strip('<>') for p in r.headers.get('Link','').split(',') if 'rel="next"' in p]
        url = nxt[0] if nxt else None

    # Fetch articles from each blog
    for blog in blogs:
        blog_handle = blog.get('handle')
        article_url = f"{BASE}/blogs/{blog['id']}/articles.json?limit=250"
        if published_since:
            article_url += f"&published_at_min={published_since}"
        while article_url:
            r = requests.get(article_url, headers=HEADS); r.raise_for_status(); _check_rate(r)
            fetched_articles = r.json().get('articles', [])
            for article in fetched_articles:
                article['blog_handle'] = blog_handle
            articles.extend(fetched_articles)
            nxt = [p.split(';')[0].strip().strip('<>') for p in r.headers.get('Link','').split(',') if 'rel="next"' in p]
            article_url = nxt[0] if nxt else None

    return articles


# ── Metafields (meta title + meta description) ────────────────────────────────
def get_metafields(resource_path, rid):
    """Get metafields for any resource (products, pages, custom_collections, blogs/{id}/articles)."""
    data = api_get(f"/{resource_path}/{rid}/metafields.json")
    return {f"{m['namespace']}.{m['key']}": m for m in data.get('metafields', [])}


def upsert_metafield(resource_path, rid, namespace, key, value, mf_type, existing_mfs):
    """Upsert metafield for any resource."""
    full_key = f"{namespace}.{key}"
    if full_key in existing_mfs:
        mid = existing_mfs[full_key]['id']
        api_put(f"/metafields/{mid}.json",
                {"metafield": {"id": mid, "value": value, "type": mf_type}})
    else:
        api_post(f"/{resource_path}/{rid}/metafields.json",
                 {"metafield": {"namespace": namespace, "key": key,
                                "value": value, "type": mf_type}})


def set_seo_metafields(resource_path, rid, meta_title, meta_desc, existing_mfs):
    """Set SEO metafields (title + desc) for any resource."""
    upsert_metafield(resource_path, rid, "global", "title_tag",       meta_title, "single_line_text_field", existing_mfs)
    upsert_metafield(resource_path, rid, "global", "description_tag", meta_desc,  "multi_line_text_field",  existing_mfs)


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

JSONLD_SNIPPET = r"""{% comment %}meeeshop-jsonld v3 — auto-generated, do not remove{% endcomment %}
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@graph": [
    {
      "@type": "Organization",
      "@id": "{{ shop.url }}/#organization",
      "name": "MeeeShop",
      "url": "{{ shop.url }}",
      "logo": {"@type": "ImageObject", "url": "{{ shop.url }}/cdn/shop/files/logo.png"},
      "description": "Premium women's fashion with free US shipping and 7-day returns",
      "contactPoint": {"@type": "ContactPoint", "contactType": "Customer Service", "email": "support@meeeshop.com"},
      "sameAs": ["https://pinterest.com/meeeshop", "https://www.youtube.com/@meeeshop"]
    },
    {
      "@type": "LocalBusiness",
      "@id": "{{ shop.url }}/#localbusiness",
      "name": "MeeeShop",
      "image": "{{ shop.url }}/cdn/shop/files/logo.png",
      "description": "Women's fashion boutique - dresses, tops, bottoms, outerwear, shoes & more",
      "url": "{{ shop.url }}",
      "priceRange": "$$",
      "areaServed": "US"
    },
    {
      "@type": "WebSite",
      "@id": "{{ shop.url }}/#website",
      "url": "{{ shop.url }}",
      "name": "MeeeShop - Women's Fashion Store",
      "publisher": {"@id": "{{ shop.url }}/#organization"},
      "potentialAction": {
        "@type": "SearchAction",
        "target": {"@type": "EntryPoint", "urlTemplate": "{{ shop.url }}/search?q={search_term_string}"},
        "query-input": "required name=search_term_string"
      }
    }
    {%- if template.name == 'product' and product != blank -%}
    ,{
      "@type": "Product",
      "@id": "{{ shop.url }}/products/{{ product.handle }}",
      "name": {{ product.title | json }},
      "url": "{{ shop.url }}/products/{{ product.handle }}",
      "description": {{ product.description | strip_html | truncate: 500 | json }},
      "brand": {"@type": "Brand", "name": "MeeeShop"},
      "image": [{% for img in product.images %}"{{ img | image_url: width: 1200 }}"{% unless forloop.last %},{% endunless %}{% endfor %}],
      "offers": [
        {%- for v in product.variants -%}
        {
          "@type": "Offer",
          "name": {{ v.title | json }},
          "sku": {{ v.sku | default: "" | json }},
          {%- if v.barcode != blank -%}
          "gtin": {{ v.barcode | json }},
          {%- endif -%}
          "price": "{{ v.price | money_without_currency | remove: ',' }}",
          "priceCurrency": "USD",
          "availability": "https://schema.org/{% if v.available %}InStock{% else %}OutOfStock{% endif %}",
          "url": "{{ shop.url }}/products/{{ product.handle }}?variant={{ v.id }}",
          "seller": {"@type": "Organization", "name": "MeeeShop"},
          "shippingDetails": {
            "@type": "OfferShippingDetails",
            "shippingAddress": {
              "@type": "DefinedRegion",
              "addressCountry": "US"
            },
            "shippingRate": {
              "@type": "MonetaryAmount",
              "value": "0.00",
              "currency": "USD"
            }
          },
          "hasMerchantReturnPolicy": {
            "@type": "MerchantReturnPolicy",
            "applicableCountry": "US",
            "returnPolicyCategory": "https://schema.org/MerchantReturnFiniteReturnPeriod",
            "merchantReturnDays": 7,
            "returnMethod": "https://schema.org/ReturnByMail",
            "returnFees": "https://schema.org/FreeReturn"
          }
        }{%- unless forloop.last -%},{%- endunless -%}
        {%- endfor -%}
      ]
    }
    ,{
      "@type": "BreadcrumbList",
      "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "Home", "item": "{{ shop.url }}"},
        {%- if collection != blank -%}
        {"@type": "ListItem", "position": 2, "name": {{ collection.title | json }}, "item": "{{ shop.url }}/collections/{{ collection.handle }}"},
        {"@type": "ListItem", "position": 3, "name": {{ product.title | json }}, "item": "{{ shop.url }}/products/{{ product.handle }}"}
        {%- else -%}
        {"@type": "ListItem", "position": 2, "name": {{ product.title | json }}, "item": "{{ shop.url }}/products/{{ product.handle }}"}
        {%- endif -%}
      ]
    }
    {%- endif -%}
    {%- if template.name == 'collection' and collection != blank -%}
    ,{
      "@type": "CollectionPage",
      "name": {{ collection.title | json }},
      "url": "{{ shop.url }}/collections/{{ collection.handle }}",
      "description": {{ collection.description | strip_html | default: collection.title | json }},
      "publisher": {"@id": "{{ shop.url }}/#organization"},
      "mainEntity": {
        "@type": "ItemList",
        "itemListElement": [
          {%- paginate collection.products by 250 -%}
          {%- for p in collection.products -%}
          {
            "@type": "ListItem",
            "position": {{ forloop.index }},
            "item": {
              "@type": "Product",
              "name": {{ p.title | json }},
              "url": "{{ shop.url }}/products/{{ p.handle }}",
              "image": "{{ p.featured_image | image_url: width: 800 }}",
              "offers": {
                "@type": "AggregateOffer",
                "priceCurrency": "USD",
                "lowPrice": "{{ p.price_min | money_without_currency | remove: ',' }}",
                "highPrice": "{{ p.price_max | money_without_currency | remove: ',' }}",
                "offerCount": {{ p.variants.size }},
                "availability": "https://schema.org/{% if p.available %}InStock{% else %}OutOfStock{% endif %}"
              }
            }
          }{%- unless forloop.last -%},{%- endunless -%}
          {%- endfor -%}
          {%- endpaginate -%}
        ]
      }
    }
    ,{
      "@type": "BreadcrumbList",
      "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "Home", "item": "{{ shop.url }}"},
        {"@type": "ListItem", "position": 2, "name": {{ collection.title | json }}, "item": "{{ shop.url }}/collections/{{ collection.handle }}"}
      ]
    }
    {%- endif -%}
    {%- if template.name == 'article' and article != blank -%}
    ,{
      "@type": "BlogPosting",
      "@id": "{{ shop.url }}{{ article.url }}",
      "headline": {{ article.title | json }},
      "description": {{ article.excerpt | default: article.title | strip_html | truncate: 160 | json }},
      "url": "{{ shop.url }}{{ article.url }}",
      "datePublished": "{{ article.published_at | date: '%Y-%m-%dT%H:%M:%SZ' }}",
      "dateModified": "{{ article.updated_at | date: '%Y-%m-%dT%H:%M:%SZ' }}",
      {%- if article.image != blank -%}
      "image": "{{ article.image | image_url: width: 1200 }}",
      {%- endif -%}
      "author": {"@type": "Person", "name": {{ article.author | json }}},
      "publisher": {
        "@type": "Organization",
        "name": "MeeeShop",
        "logo": {"@type": "ImageObject", "url": "{{ shop.url }}/cdn/shop/files/logo.png"}
      },
      "isPartOf": {"@id": "{{ shop.url }}/#website"}
    }
    ,{
      "@type": "BreadcrumbList",
      "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "Home", "item": "{{ shop.url }}"},
        {"@type": "ListItem", "position": 2, "name": {{ blog.title | json }}, "item": "{{ shop.url }}/blogs/{{ blog.handle }}"},
        {"@type": "ListItem", "position": 3, "name": {{ article.title | json }}, "item": "{{ shop.url }}{{ article.url }}"}
      ]
    }
    {%- endif -%}
    {%- if template.name == 'index' -%}
    ,{
      "@type": "WebPage",
      "@id": "{{ shop.url }}/#homepage",
      "url": "{{ shop.url }}",
      "name": "MeeeShop - Women's Fashion",
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
    ROBOTS_TAG  = '<meta name="robots" content="max-image-preview:large">'

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

    changed = False

    if MARKER not in layout:
        tag = "{% render 'meeeshop-jsonld' %}"
        layout = layout.replace("</head>", f"  {tag}\n</head>", 1)
        changed = True
        print("  JSON-LD render tag added to layout/theme.liquid")

    if "max-image-preview:large" not in layout:
        layout = layout.replace("</head>", f"  {ROBOTS_TAG}\n</head>", 1)
        changed = True
        print("  Discover robots meta tag added to layout/theme.liquid")

    if changed:
        if put_asset(theme_id, "layout/theme.liquid", layout):
            print("  theme.liquid updated successfully")
            return True
        else:
            print("  ! Could not update layout/theme.liquid")
            return False
    else:
        print("  JSON-LD & Robots tags already present in theme.liquid — skipped")
        return True



# ══════════════════════════════════════════════════════════════════════════════
# SEO VALIDATION (strict template compliance check)
# ══════════════════════════════════════════════════════════════════════════════

def validate_seo(item, item_type, existing_mfs):
    """Strict template validation. Returns list of {field, before, after, [_img_id, _img_idx]} dicts."""
    mismatches = []
    title = item.get('title', '')

    # ── Meta title (exact match) ──────────────────────────────────────────────
    expected_meta_title = build_meta_title(title)
    cur_meta_title = existing_mfs.get('global.title_tag', {}).get('value', '')
    if cur_meta_title != expected_meta_title:
        mismatches.append({"field": "meta_title", "before": cur_meta_title, "after": expected_meta_title})

    # ── Meta desc (content checks + no stale return policy) ───────────────────
    cur_meta_desc = existing_mfs.get('global.description_tag', {}).get('value', '')
    desc_ok = (
        "7-day return" in cur_meta_desc
        and "free" in cur_meta_desc.lower()
        and DISPLAY_BRAND in cur_meta_desc
        and 0 < len(cur_meta_desc) <= 155
        and not has_stale_return_policy(cur_meta_desc)
    )
    if not desc_ok:
        new_meta_desc = build_meta_desc(title)
        mismatches.append({"field": "meta_desc", "before": cur_meta_desc, "after": new_meta_desc})

    # ── Product-only: body_html + image ALTs ──────────────────────────────────
    if item_type == "product":
        body_html = item.get('body_html', '') or ''
        plain_len = len(strip_html(body_html))
        has_table = has_size_table(body_html)
        # Required template markers + no stale (non-7-day) return policy anywhere
        required_markers = [
            'Discover the',
            'Product Features',
            'Premium quality materials',
            'Why Choose',
            RETURN_POLICY,
        ]
        has_all_markers = all(m in body_html for m in required_markers)
        has_stale_body  = has_stale_return_policy(body_html)
        body_ok = has_all_markers and not has_stale_body and plain_len >= 500 and has_table
        if not body_ok:
            new_desc = build_description(item, force=True)
            mismatches.append({
                "field": "body_html",
                "before": f"{plain_len} chars, table={has_table}, markers={has_all_markers}, stale={has_stale_body}",
                "after": f"{len(strip_html(new_desc))} chars + table"
            })

        # Image ALTs: check each image
        colors = []
        for v in item.get('variants', []):
            opt = v.get('option1') or ''
            if opt and opt.lower() not in ('default title', 'default', ''):
                colors.append(opt)
        for i, img in enumerate(item.get('images', [])):
            hint = colors[i] if i < len(colors) else ''
            expected_alt = build_alt(title, hint, i)
            cur_alt = img.get('alt', '') or ''
            if cur_alt != expected_alt:
                mismatches.append({
                    "field": f"img_alt[{i}]",
                    "before": cur_alt,
                    "after": expected_alt,
                    "_img_id": img['id'],
                    "_img_idx": i
                })

    return mismatches


# ══════════════════════════════════════════════════════════════════════════════
# CORE PRODUCT PROCESSOR
# ══════════════════════════════════════════════════════════════════════════════

def process(product, stats, log, existing_mfs=None, force=False):
    pid        = product['id']
    old_title  = product['title']
    old_handle = product['handle']
    changes    = []
    missing    = []

    # ── 1. Title Case ─────────────────────────────────────────────────────────
    new_title    = title_case(old_title)
    prod_updates = {}
    if new_title != old_title:
        prod_updates['title'] = new_title
        stats['titles'] += 1
        changes.append({"field": "title", "before": old_title, "after": new_title})

    # ── 2. Body description: rewrite in force/weekly mode OR if stale/missing template ─────
    body_html = product.get('body_html', '') or ''
    plain_len = len(strip_html(body_html))
    has_table = has_size_table(body_html)
    required_markers = ['Discover the', 'Product Features', 'Premium quality materials',
                        'Why Choose', RETURN_POLICY]
    has_all_markers = all(m in body_html for m in required_markers)
    has_stale_body  = has_stale_return_policy(body_html)
    needs_body_rewrite = force or plain_len < 500 or not has_table or has_stale_body or not has_all_markers
    if needs_body_rewrite:
        missing.append(f"body_html ({plain_len} chars, table={has_table}, stale={has_stale_body}, markers={has_all_markers})")
        new_body = build_description(product, force=True)
        prod_updates['body_html'] = new_body
        stats['descriptions'] += 1
        changes.append({
            "field": "body_html",
            "before": f"{plain_len} chars",
            "after": f"{len(strip_html(new_body))} chars + table"
        })

    # ── 3. URL handle + redirect ──────────────────────────────────────────────
    final_title  = prod_updates.get('title', old_title)
    ideal_handle = slugify(final_title)
    if ideal_handle and ideal_handle != old_handle and len(ideal_handle) > 4:
        missing.append(f"handle (was '{old_handle}')")
        prod_updates['handle'] = ideal_handle
        if create_redirect(old_handle, ideal_handle):
            stats['redirects'] += 1
        stats['handles'] += 1
        changes.append({"field": "handle", "before": old_handle, "after": ideal_handle})

    # Apply product updates
    if prod_updates:
        try:
            api_put(f"/products/{pid}.json", {"product": prod_updates})
            stats['products'] += 1
        except Exception as e:
            print(f"    ! Update failed: {e}")
            return

    # ── 4. Fetch metafields if not provided ───────────────────────────────────
    if existing_mfs is None:
        try:
            existing_mfs = get_metafields("products", pid)
        except Exception as e:
            print(f"    ! Metafields fetch error: {e}")
            existing_mfs = {}

    # ── 5. Strict validation + fix ────────────────────────────────────────────
    display_title = prod_updates.get('title', old_title)
    product_with_new_title = {**product, 'title': display_title}
    mismatches = validate_seo(product_with_new_title, "product", existing_mfs)

    meta_fix_needed = False
    new_meta_title = build_meta_title(display_title)
    new_meta_desc = build_meta_desc(display_title)

    for m in mismatches:
        if m['field'] == 'meta_title':
            missing.append("meta_title mismatch")
            meta_fix_needed = True
            stats['meta_titles'] += 1
            changes.append({"field": "meta_title", "before": m['before'], "after": m['after']})
        elif m['field'] == 'meta_desc':
            missing.append("meta_desc mismatch")
            if not meta_fix_needed:
                stats['meta_descs'] += 1
            changes.append({
                "field": "meta_desc",
                "before": m['before'][:80] + "..." if len(m['before']) > 80 else m['before'],
                "after": m['after'][:80] + "..."
            })
        elif m['field'] == 'body_html':
            # Already handled above
            pass
        elif m['field'].startswith('img_alt'):
            i   = m['_img_idx']
            iid = m['_img_id']
            if not m['before']:
                missing.append(f"img[{i}] alt (missing)")
            if update_image_alt(pid, iid, m['after']):
                stats['alts'] += 1
                changes.append({"field": f"img_alt[{i}]", "before": m['before'][:50], "after": m['after'][:50]})

    # In force mode, always rewrite both meta fields even if they already pass validation
    if force and not meta_fix_needed:
        cur_mt = existing_mfs.get('global.title_tag', {}).get('value', '')
        cur_md = existing_mfs.get('global.description_tag', {}).get('value', '')
        if cur_mt != new_meta_title or cur_md != new_meta_desc:
            meta_fix_needed = True
            stats['meta_titles'] += 1
            stats['meta_descs'] += 1
            changes.append({"field": "meta_title", "before": cur_mt, "after": new_meta_title})
            changes.append({"field": "meta_desc", "before": cur_md[:80], "after": new_meta_desc[:80]})

    # Fix meta fields if needed
    if meta_fix_needed:
        try:
            set_seo_metafields("products", pid, new_meta_title, new_meta_desc, existing_mfs)
        except Exception as e:
            print(f"    ! Meta update error: {e}")
    elif any(m['field'] == 'meta_desc' for m in mismatches):
        try:
            upsert_metafield("products", pid, "global", "description_tag", new_meta_desc,
                             "multi_line_text_field", existing_mfs)
        except Exception as e:
            print(f"    ! Meta desc update error: {e}")

    # ── Log entry ─────────────────────────────────────────────────────────────
    entry = {
        "product": old_title,
        "url":     f"{SITE}/products/{old_handle}",
        "missing": missing,
        "fixed":   changes,
    }
    log.append(entry)

    if missing:
        print(f"  Missing: {', '.join(missing[:4])}")
    if changes:
        for c in changes[:3]:
            b = str(c['before'])[:30]
            a = str(c['after'])[:30]
            print(f"  + {c['field']}: '{b}' -> '{a}'")
        if len(changes) > 3:
            print(f"  + ...and {len(changes)-3} more")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(description='SEO automation: daily/weekly/force modes')
    ap.add_argument('--daily',       action='store_true', help='Daily mode: last 48hrs (default)')
    ap.add_argument('--weekly',      action='store_true', help='Weekly mode: last 7 days, skip recent')
    ap.add_argument('--force',       action='store_true', help='Force mode: entire catalog, normalize all')
    ap.add_argument('--hours',       type=int, default=0,  help='Custom lookback (overrides mode)')
    ap.add_argument('--limit',       type=int, default=0,  help='Max products (0=all, non-force only)')
    ap.add_argument('--batch-size',  type=int, default=0,  help='For force mode: products per batch job (0=no batching)')
    ap.add_argument('--batch-index', type=int, default=0,  help='For force mode: which batch to process (0-based)')
    ap.add_argument('--skip-jsonld', action='store_true', help='Skip JSON-LD injection')
    args = ap.parse_args()

    print("=== MeeeShop SEO Automation v2.0 ===\n")

    # ── Determine mode ────────────────────────────────────────────────────────
    if args.force:
        mode = 'force'
        since = None
        print("Mode: FORCE (entire catalog, normalize all SEO fields)")
        if args.batch_size > 0:
            print(f"Batch: index={args.batch_index}, size={args.batch_size} (products only; pages/collections/articles always fully processed)")
        print("Processing: Products, Pages, Collections, Blog Posts\n")
    elif args.weekly:
        mode = 'weekly'
        since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime('%Y-%m-%dT%H:%M:%SZ')
        print("Mode: WEEKLY (overwrite all SEO for items added/published in last 7 days)")
        print("Processing: Products, Pages, Collections, Blog Posts\n")
    elif args.hours:
        mode = 'custom'
        since = (datetime.now(timezone.utc) - timedelta(hours=args.hours)).strftime('%Y-%m-%dT%H:%M:%SZ')
        print(f"Mode: CUSTOM ({args.hours}h lookback)")
        print("Processing: Products, Pages, Collections, Blog Posts\n")
    else:
        mode = 'daily'
        since = (datetime.now(timezone.utc) - timedelta(hours=48)).strftime('%Y-%m-%dT%H:%M:%SZ')
        print("Mode: DAILY (products created in last 48h; pages/collections created + articles published in last 48h)")
        print("Processing: Products, Pages, Collections, Blog Posts\n")

    print(f"Cutoff: {since or 'none (all resources)'}\n")

    # ── JSON-LD theme injection (idempotent) ──────────────────────────────────
    if not args.skip_jsonld:
        print("Injecting JSON-LD structured data...")
        tid = get_live_theme_id()
        if tid:
            inject_jsonld(tid)
        else:
            print("  ! Could not find live theme")
        print()

    # ── Fetch all resources (products, pages, collections, articles) ──────────
    # Products: created_at_min — catches new dropship imports (Trendsi, Cemi Cari, etc.)
    # Pages/Collections: created_at_min — new pages/collections published since cutoff
    # Articles: published_at_min — new blog posts published since cutoff
    print("Fetching products...")
    products = fetch_products(since)
    total_fetched = len(products)
    if mode == 'force' and args.batch_size > 0:
        start = args.batch_index * args.batch_size
        end   = start + args.batch_size
        products = products[start:end]
        print(f"  Fetched {total_fetched} products total; processing batch {args.batch_index} [{start}:{end}] = {len(products)} products")
    elif args.limit:
        products = products[:args.limit]
    print(f"  Found {len(products)} products\n")

    print("Fetching pages...")
    pages = fetch_pages(since)
    print(f"  Found {len(pages)} pages\n")

    print("Fetching collections...")
    collections = fetch_collections(since)
    print(f"  Found {len(collections)} collections\n")

    print("Fetching articles...")
    articles = fetch_articles(since)
    print(f"  Found {len(articles)} articles\n")

    total_items = len(products) + len(pages) + len(collections) + len(articles)
    print(f"Total items to process: {total_items}\n")

    stats = {
        'products': 0, 'pages': 0, 'collections': 0, 'articles': 0,
        'titles': 0, 'descriptions': 0,
        'meta_titles': 0, 'meta_descs': 0,
        'handles': 0, 'redirects': 0, 'alts': 0
    }
    log = []

    # ── Process products ──────────────────────────────────────────────────────
    print("Processing products...")
    for i, p in enumerate(products, 1):
        mfs        = get_metafields("products", p['id'])
        mismatches = validate_seo(p, "product", mfs)
        title_wrong = title_case(p['title']) != p['title']
        needs_seo   = bool(mismatches) or title_wrong
        if not needs_seo and mode not in ('force', 'weekly'):
            print(f"  [{i}/{len(products)}] OK  {p['title'][:55]}")
            continue
        print(f"  [{i}/{len(products)}] FIX {p['title'][:55]}")
        process(p, stats, log, existing_mfs=mfs, force=(mode in ('force', 'weekly')))

    # ── Process pages ─────────────────────────────────────────────────────────
    if pages:
        print("\nProcessing pages...")
        for i, page in enumerate(pages, 1):
            title = page['title']
            mfs = get_metafields("pages", page['id'])

            # Strict validation
            cur_mtitle = mfs.get('global.title_tag', {}).get('value', '')
            cur_mdesc  = mfs.get('global.description_tag', {}).get('value', '')
            expected_mt = build_meta_title(title)
            desc_ok = (
                "7-day return" in cur_mdesc
                and "free" in cur_mdesc.lower()
                and DISPLAY_BRAND in cur_mdesc
                and 0 < len(cur_mdesc) <= 155
                and not has_stale_return_policy(cur_mdesc)
            )
            mt_ok = (cur_mtitle == expected_mt)
            needs_seo = not mt_ok or not desc_ok
            if not needs_seo and mode not in ('force', 'weekly'):
                print(f"  [{i}/{len(pages)}] OK  {title[:55]}")
                continue

            print(f"  [{i}/{len(pages)}] FIX {title[:55]}")
            new_meta_title = expected_mt
            new_meta_desc = truncate(
                f"{title} - {DISPLAY_BRAND}. Premium women's fashion with free US shipping & 7-day returns.",
                155
            )
            try:
                set_seo_metafields("pages", page['id'], new_meta_title, new_meta_desc, mfs)
                stats['meta_titles'] += 1
                stats['meta_descs'] += 1
                stats['pages'] += 1
                log.append({
                    'type': 'page',
                    'title': title,
                    'url': f"{SITE}/pages/{page['handle']}",
                    'fixed': [
                        {"field": "meta_title", "before": cur_mtitle, "after": new_meta_title},
                        {"field": "meta_desc", "before": cur_mdesc[:60], "after": new_meta_desc[:60]},
                    ]
                })
            except Exception as e:
                print(f"    ! Error processing page: {e}")

    # ── Process collections ───────────────────────────────────────────────────
    if collections:
        print("\nProcessing collections...")
        for i, coll in enumerate(collections, 1):
            title = coll['title']
            mfs = get_metafields("custom_collections", coll['id'])

            # Strict validation
            cur_mtitle = mfs.get('global.title_tag', {}).get('value', '')
            cur_mdesc  = mfs.get('global.description_tag', {}).get('value', '')
            expected_mt = build_meta_title(title)
            desc_ok = (
                "7-day return" in cur_mdesc
                and "free" in cur_mdesc.lower()
                and DISPLAY_BRAND in cur_mdesc
                and 0 < len(cur_mdesc) <= 155
                and not has_stale_return_policy(cur_mdesc)
            )
            mt_ok = (cur_mtitle == expected_mt)
            needs_seo = not mt_ok or not desc_ok
            if not needs_seo and mode not in ('force', 'weekly'):
                print(f"  [{i}/{len(collections)}] OK  {title[:55]}")
                continue

            print(f"  [{i}/{len(collections)}] FIX {title[:55]}")
            new_meta_title = expected_mt
            new_meta_desc = truncate(
                f"Shop {title} at {DISPLAY_BRAND}. Premium women's fashion with free US shipping & 7-day returns.",
                155
            )
            try:
                set_seo_metafields("custom_collections", coll['id'], new_meta_title, new_meta_desc, mfs)
                stats['meta_titles'] += 1
                stats['meta_descs'] += 1
                stats['collections'] += 1
                log.append({
                    'type': 'collection',
                    'title': title,
                    'url': f"{SITE}/collections/{coll['handle']}",
                    'fixed': [
                        {"field": "meta_title", "before": cur_mtitle, "after": new_meta_title},
                        {"field": "meta_desc", "before": cur_mdesc[:60], "after": new_meta_desc[:60]},
                    ]
                })
            except Exception as e:
                print(f"    ! Error processing collection: {e}")

    # ── Process articles ──────────────────────────────────────────────────────
    if articles:
        print("\nProcessing articles...")
        for i, article in enumerate(articles, 1):
            title = article['title']
            blog_id = article.get('blog_id')
            blog_handle = article.get('blog_handle')
            art_id  = article['id']

            if not blog_id or not blog_handle:
                print(f"  [{i}/{len(articles)}] SKIP {title[:55]} (no blog_id or blog_handle)")
                continue

            try:
                mfs = get_metafields(f"blogs/{blog_id}/articles", art_id)
            except Exception as e:
                print(f"  ! Could not fetch metafields for article {title}: {e}")
                continue

            # Strict validation
            cur_mtitle = mfs.get('global.title_tag', {}).get('value', '')
            cur_mdesc  = mfs.get('global.description_tag', {}).get('value', '')
            expected_mt = build_meta_title(title)
            desc_ok = (
                "7-day return" in cur_mdesc
                and "free" in cur_mdesc.lower()
                and DISPLAY_BRAND in cur_mdesc
                and 0 < len(cur_mdesc) <= 155
                and not has_stale_return_policy(cur_mdesc)
            )
            mt_ok = (cur_mtitle == expected_mt)
            needs_seo = not mt_ok or not desc_ok
            if not needs_seo and mode not in ('force', 'weekly'):
                print(f"  [{i}/{len(articles)}] OK  {title[:55]}")
                continue

            print(f"  [{i}/{len(articles)}] FIX {title[:55]}")
            new_meta_title = expected_mt
            new_meta_desc = truncate(
                f"{title} - {DISPLAY_BRAND} Blog. Women's fashion tips & styling guides with free shipping & 7-day returns.",
                155
            )
            try:
                set_seo_metafields(f"blogs/{blog_id}/articles", art_id, new_meta_title, new_meta_desc, mfs)
                stats['meta_titles'] += 1
                stats['meta_descs'] += 1
                stats['articles'] += 1
                log.append({
                    'type': 'article',
                    'title': title,
                    'url': f"{SITE}/blogs/{blog_handle}/{article['handle']}",
                    'fixed': [
                        {"field": "meta_title", "before": cur_mtitle, "after": new_meta_title},
                        {"field": "meta_desc", "before": cur_mdesc[:60], "after": new_meta_desc[:60]},
                    ]
                })
            except Exception as e:
                print(f"    ! Error processing article: {e}")

    # ── Report ────────────────────────────────────────────────────────────────
    print("\n" + "─"*60)
    print("SEO Automation Report")
    print("─"*60)
    labels = {
        'products':     'Products updated',
        'pages':        'Pages updated',
        'collections':  'Collections updated',
        'articles':     'Articles updated',
        'titles':       'Title case fixes',
        'descriptions': 'Descriptions added',
        'meta_titles':  'Meta titles set',
        'meta_descs':   'Meta descs set',
        'handles':      'Handles updated',
        'redirects':    'Redirects created',
        'alts':         'Image alts fixed',
    }
    for k, label in labels.items():
        if k in stats:
            print(f"  {label:<22}: {stats[k]}")
    print("─"*60)

    # ── Detailed change log ───────────────────────────────────────────────────
    if log:
        print("\n--- Items Fixed ---")
        for entry in log:
            item_name = entry.get('product') or entry.get('title', 'Unknown')
            print(f"\n  Item    : {item_name}")
            print(f"  URL     : {entry['url']}")
            if entry.get('missing'):
                print(f"  Missing : {', '.join(entry['missing'][:3])}")
            for fix in entry.get('fixed', []):
                if isinstance(fix, dict):
                    b = str(fix.get('before', ''))[:40]
                    a = str(fix.get('after', ''))[:40]
                    print(f"  Fixed [{fix['field']}]: '{b}' -> '{a}'")
                else:
                    print(f"  Fixed   : {fix}")

    report = {
        **stats,
        "run_at":      datetime.now(timezone.utc).isoformat(),
        "mode":        mode,
        "batch_index": args.batch_index if mode == 'force' else None,
        "batch_size":  args.batch_size  if mode == 'force' else None,
        "products_fixed": log,
    }
    batch_suffix = f"_b{args.batch_index}" if (mode == 'force' and args.batch_size > 0) else ""
    fname = f"seo_report_{datetime.now().strftime('%Y%m%d_%H%M')}{batch_suffix}.json"
    with open(fname, 'w') as f:
        json.dump(report, f, indent=2)
    print(f"\nFull report saved: {fname}")


if __name__ == "__main__":
    main()

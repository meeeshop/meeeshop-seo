"""Remove all competing JSON-LD schema sources from theme, leaving only meeeshop-jsonld.liquid."""
import sys, requests, re, time

sys.path.insert(0, '.')
from secrets_manager import inject_to_env, get_secret
inject_to_env()

STORE    = get_secret('SHOPIFY_STORE')
TOKEN    = get_secret('SHOPIFY_ACCESS_TOKEN')
THEME_ID = get_secret('LIVE_THEME_ID')
HEADERS  = {'X-Shopify-Access-Token': TOKEN, 'Content-Type': 'application/json'}
BASE     = f'https://{STORE}/admin/api/2024-01'

JSONLD_RE = re.compile(
    r'<script\s+type=["\']application/ld\+json["\'][^>]*>.*?</script>',
    re.DOTALL | re.IGNORECASE
)
COMMENT_JSONLD_RE = re.compile(
    r'<!--\s*<script[^>]*ld\+json.*?</script>\s*-->',
    re.DOTALL | re.IGNORECASE
)


def get_asset(key):
    r = requests.get(f'{BASE}/themes/{THEME_ID}/assets.json',
                     headers=HEADERS, params={'asset[key]': key})
    return r.json().get('asset', {}).get('value', '') if r.status_code == 200 else None


def put_asset(key, value):
    r = requests.put(f'{BASE}/themes/{THEME_ID}/assets.json',
                     headers=HEADERS,
                     json={'asset': {'key': key, 'value': value}})
    return r.status_code in (200, 201)


def strip_jsonld(content):
    cleaned = JSONLD_RE.sub('', content)
    cleaned = COMMENT_JSONLD_RE.sub('', cleaned)
    return cleaned


# Snippets that are purely schema — blank them entirely
BLANK = [
    'snippets/json-ld.liquid',
    'snippets/meee-schema-org.liquid',
    'snippets/rocket-seo.liquid',
]

# Files that have schema mixed with other content — strip only the ld+json blocks
STRIP = [
    'sections/main-collection-product-grid.liquid',
    'sections/main-article.liquid',
    'sections/main-product.liquid',
    'sections/header.liquid',
    'sections/featured-product.liquid',
    'snippets/breadcrumbs.liquid',
    'snippets/schema-markup.liquid',
]

PLACEHOLDER = '{%- comment -%}Schema removed — meeeshop-jsonld.liquid is the single source{%- endcomment -%}'

print('=' * 60)
print('STRIPPING COMPETING SCHEMA SOURCES')
print('=' * 60)

for key in BLANK:
    val = get_asset(key)
    if val is None:
        print(f'SKIP (not found): {key}')
        continue
    if put_asset(key, PLACEHOLDER):
        print(f'[OK] Blanked: {key}')
    else:
        print(f'[!] Failed:  {key}')
    time.sleep(0.5)

for key in STRIP:
    val = get_asset(key)
    if val is None:
        print(f'SKIP (not found): {key}')
        continue
    cleaned = strip_jsonld(val)
    if cleaned == val:
        print(f'[=] No schema found: {key}')
        continue
    removed = len(val) - len(cleaned)
    if put_asset(key, cleaned):
        print(f'[OK] Stripped {removed} chars: {key}')
    else:
        print(f'[!] Failed: {key}')
    time.sleep(0.5)

print()
print('[DONE] meeeshop-jsonld.liquid is now the only schema source.')

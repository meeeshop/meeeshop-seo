"""
MeeeShop SEO Automation v2.0+
Google-optimized product, collection, page, and blog SEO with 7-day returns

Workflow modes:
  --daily   : Products + Pages + Collections + Blog posts added/published in last 24hrs
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

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from secrets_manager import inject_to_env, get_secret
    inject_to_env()
except Exception:
    def get_secret(name):
        return os.getenv(name)

try:
    from shopify_graphql import run_graphql, parse_gid
except Exception:
    pass

try:
    from google_question_fetcher import GoogleQuestionFetcher
except ImportError:
    try:
        from scripts.google_question_fetcher import GoogleQuestionFetcher
    except Exception:
        GoogleQuestionFetcher = None

try:
    STORE = get_secret("SHOPIFY_STORE") or os.getenv("SHOPIFY_STORE", "us-meeeshop.myshopify.com")
    TOKEN = get_secret("SHOPIFY_ACCESS_TOKEN") or os.getenv("SHOPIFY_ACCESS_TOKEN", "")
except Exception:
    STORE = os.getenv("SHOPIFY_STORE", "us-meeeshop.myshopify.com")
    TOKEN = os.getenv("SHOPIFY_ACCESS_TOKEN", "")
HEADS  = {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}
BASE   = f"https://{STORE}/admin/api/2024-01"
BRAND  = "us.meeeshop.com"
SITE   = "https://us.meeeshop.com"
RETURN_POLICY = "7-day return policy"
DISPLAY_BRAND = "us.meeeshop"  # For human-readable text (not in meta title)

# Return policy is 7 days ONLY. Any other duration (30-day, 14-day, 60-day, etc.)
# triggers an overwrite to the 7-day policy.

# ── Google Search Console & Indexing API Integration ──────────────────────────
GSC_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
OAUTH_ENDPOINT = "https://oauth2.googleapis.com/token"

def get_gsc_oauth_token():
    try:
        raw = get_secret("GOOGLE_SA_KEY_JSON")
        sa_key = json.loads(raw)
    except Exception as e:
        local = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "google_sa_key.json")
        if os.path.exists(local):
            with open(local, "r", encoding="utf-8") as f:
                sa_key = json.load(f)
        else:
            print("WARNING: Google Service Account key not found. GSC/Indexing integration disabled.")
            return None
            
    try:
        import base64
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.backends import default_backend
    except ImportError:
        print("WARNING: 'cryptography' package missing. GSC/Indexing integration disabled.")
        return None

    try:
        now     = int(time.time())
        header  = {"alg": "RS256", "typ": "JWT"}
        payload = {"iss": sa_key["client_email"], "scope": GSC_SCOPE + " https://www.googleapis.com/auth/indexing",
                    "aud": OAUTH_ENDPOINT, "exp": now + 3600, "iat": now}

        def _b64url(data):
            return base64.urlsafe_b64encode(
                json.dumps(data, separators=(",", ":")).encode()
            ).rstrip(b"=").decode()

        signing_input = f"{_b64url(header)}.{_b64url(payload)}".encode()
        pk  = serialization.load_pem_private_key(
            sa_key["private_key"].encode(), password=None, backend=default_backend()
        )
        sig = pk.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
        jwt = f"{signing_input.decode()}.{base64.urlsafe_b64encode(sig).rstrip(b'=').decode()}"

        resp = requests.post(OAUTH_ENDPOINT,
                             data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                                   "assertion": jwt},
                             timeout=15)
        resp.raise_for_status()
        return resp.json()["access_token"]
    except Exception as e:
        print(f"WARNING: GSC OAuth failed: {e}")
        return None

def generate_long_tail_keywords(handle: str) -> list[str]:
    """Construct logical medium/long tail keywords by combining handle terms."""
    if not handle:
        return []
    words = handle.lower().replace('_', '-').split('-')
    
    # Brands check
    brands = {'judy-blue', 'judy', 'pol', 'zsv', 'kancan', 'vervet', 'gilli'}
    brand_found = None
    for b in brands:
        if b in handle.lower():
            brand_found = b.replace('-', ' ').title()
            break
            
    # Generic clothing words we can use as nouns
    clothing_nouns = {
        'jeans', 'blouse', 'top', 'dress', 'skirt', 'jacket', 'coat', 'blazer', 'sweater',
        'hoodie', 'cardigan', 'pullover', 'romper', 'jumpsuit', 'bodysuit', 'playsuit',
        'bag', 'purse', 'handbag', 'tote', 'crossbody', 'shoe', 'boot', 'heel', 'sandal', 'sneaker'
    }
    
    noun_found = next((w for w in words if w in clothing_nouns), None)
    if not noun_found:
        noun_found = words[-1] if words else 'item'
        
    ignore = {
        'and', 'the', 'for', 'with', 'new', 'hot', 'best', 'shop', 'meeeshop', 'us',
        'tie', 'front', 'side', 'back', 'neck', 'sleeve', 'sleeves', 'size', 'fit',
        'mr', 'mrs', 'jaqueline', 'styling', 'tips'
    }
    if brand_found:
        for b_word in brand_found.lower().split():
            ignore.add(b_word)
    ignore.add(noun_found)
    
    descriptors = [w for w in words if w not in ignore and len(w) > 2]
    
    generated = []
    # 1. Combination: Brand + Noun (e.g. Pol Blouse)
    if brand_found:
        generated.append(f"{brand_found} {noun_found}")
        # 2. Combination: Brand + Descriptor + Noun (e.g. Pol Boho Blouse)
        if descriptors:
            generated.append(f"{brand_found} {descriptors[-1]} {noun_found}")
            if len(descriptors) > 1:
                # 3. Combination: Brand + Multiple Descriptors + Noun (e.g. Pol Block Print Blouse)
                generated.append(f"{brand_found} {descriptors[0]} {descriptors[1]} {noun_found}")
                
    # 4. Combination: Descriptor + Noun (e.g. Boho Blouse)
    if descriptors:
        generated.append(f"{descriptors[-1]} {noun_found}")
        if len(descriptors) > 1:
            # 5. Combination: Double Descriptor + Noun (e.g. Floral Boho Blouse)
            generated.append(f"{descriptors[-2]} {descriptors[-1]} {noun_found}")
            
    unique = []
    for g in generated:
        g_clean = g.strip().lower()
        if g_clean not in unique:
            unique.append(g_clean)
            
    return unique[:3]


def fetch_google_search_keywords(handle: str, limit: int = 3) -> list[str]:
    """
    Generate a base query from handle terms (e.g. 'judy blue flare jeans') 
    and fetch real autocomplete suggestions directly from Google Search.
    """
    if not handle:
        return []
    words = handle.lower().replace('_', '-').split('-')
    
    # Brands check
    brands = {'judy-blue', 'judy', 'pol', 'zsv', 'kancan', 'vervet', 'gilli'}
    brand_found = None
    for b in brands:
        if b in handle.lower():
            brand_found = b.replace('-', ' ').title()
            break
            
    # Generic clothing words we can use as nouns
    clothing_nouns = {
        'jeans', 'blouse', 'top', 'dress', 'skirt', 'jacket', 'coat', 'blazer', 'sweater',
        'hoodie', 'cardigan', 'pullover', 'romper', 'jumpsuit', 'bodysuit', 'playsuit',
        'bag', 'purse', 'handbag', 'tote', 'crossbody', 'shoe', 'boot', 'heel', 'sandal', 'sneaker'
    }
    
    noun_found = next((w for w in words if w in clothing_nouns), None)
    if not noun_found:
        noun_found = words[-1] if words else 'item'
        
    ignore = {
        'and', 'the', 'for', 'with', 'new', 'hot', 'best', 'shop', 'meeeshop', 'us',
        'tie', 'front', 'side', 'back', 'neck', 'sleeve', 'sleeves', 'size', 'fit',
        'mr', 'mrs', 'jaqueline', 'styling', 'tips'
    }
    if brand_found:
        for b_word in brand_found.lower().split():
            ignore.add(b_word)
    ignore.add(noun_found)
    
    descriptors = [w for w in words if w not in ignore and len(w) > 2]
    
    # Construct a highly relevant base query: e.g. "Judy Blue flare jeans"
    query_parts = []
    if brand_found:
        query_parts.append(brand_found.lower())
    if descriptors:
        query_parts.extend(descriptors[:2])
    query_parts.append(noun_found)
    
    base_query = " ".join(query_parts)
    print(f"  [Google Search] Querying autocomplete suggestions for: '{base_query}'")
    
    import urllib.parse
    url = f"http://suggestqueries.google.com/complete/search?client=chrome&q={urllib.parse.quote_plus(base_query)}"
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if len(data) > 1 and isinstance(data[1], list):
                suggestions = data[1]
                # Filter suggestions to ensure they don't contain other brands from our list
                other_brands = {'zenana', 'flying monkey', 'kancan', 'vervet', 'gilli', 'pol', 'judy blue'}
                if brand_found:
                    other_brands.discard(brand_found.lower())
                    
                cleaned = []
                for s in suggestions:
                    s_clean = s.strip().lower()
                    # Exclude competitor brands, non-US location terms, competitor retailers, and local brick-and-mortar terms
                    if any(ob in s_clean for ob in other_brands):
                        continue
                    if hasattr(GoogleQuestionFetcher, "is_fashion_relevant") and not GoogleQuestionFetcher.is_fashion_relevant(s_clean, allowed_brand=brand_found or handle):
                        continue
                    if GoogleQuestionFetcher.has_non_us_location(s_clean):
                        continue
                    if GoogleQuestionFetcher.has_competitor_retailer(s_clean, allowed_brand=brand_found or handle):
                        continue
                    if GoogleQuestionFetcher.has_local_intent(s_clean):
                        continue
                    if s_clean not in cleaned:
                        cleaned.append(s_clean)
                
                if cleaned:
                    return cleaned[:limit]
    except Exception as e:
        print(f"  [Google Search] Autocomplete request failed: {e}")
        
    return [
        kw for kw in generate_long_tail_keywords(handle) 
        if (not hasattr(GoogleQuestionFetcher, "is_fashion_relevant") or GoogleQuestionFetcher.is_fashion_relevant(kw, allowed_brand=handle))
        and not GoogleQuestionFetcher.has_non_us_location(kw) 
        and not GoogleQuestionFetcher.has_competitor_retailer(kw, allowed_brand=handle)
        and not GoogleQuestionFetcher.has_local_intent(kw)
    ][:limit]


def fetch_gsc_keywords(page_url: str, limit: int = 3) -> list[str]:
    """Fetch top search queries for a specific page URL with rank 8-20, low CTR, and high impressions."""
    token = get_gsc_oauth_token()
    parts = page_url.strip('/').split('/')
    handle = parts[-1] if parts else ""

    if not token:
        # Fallback if GSC integration disabled/failed
        return fetch_google_search_keywords(handle, limit)
        
    import urllib.parse
    try:
        list_url = "https://www.googleapis.com/webmasters/v3/sites"
        list_resp = requests.get(list_url, headers={"Authorization": f"Bearer {token}"}, timeout=15)
        list_resp.raise_for_status()
        sites = list_resp.json().get("siteEntry", [])
        
        store_domain = urllib.parse.urlparse(SITE).netloc.lower()
        site_url = None
        for site in sites:
            candidate = site.get("siteUrl", "")
            if store_domain in candidate.lower():
                site_url = candidate
                break
        if not site_url:
            site_url = SITE + "/"
            
        encoded_site = urllib.parse.quote_plus(site_url)
        query_url = f"https://www.googleapis.com/webmasters/v3/sites/{encoded_site}/searchAnalytics/query"
        
        end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        start_date = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
        
        payload = {
            "startDate": start_date,
            "endDate": end_date,
            "dimensions": ["query"],
            "dimensionFilterGroups": [{
                "filters": [{
                    "dimension": "page",
                    "operator": "equals",
                    "expression": page_url
                }]
            }],
            "rowLimit": 100
        }
        
        resp = requests.post(
            query_url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
            timeout=20
        )
        resp.raise_for_status()
        rows = resp.json().get("rows", [])
        
        candidates = []
        for row in rows:
            query = row.get("keys", [None])[0]
            if query:
                position = row.get("position", 0)
                ctr = row.get("ctr", 0)
                impressions = row.get("impressions", 0)
                if 8.0 <= position <= 20.0 and ctr < 0.05 and (not hasattr(GoogleQuestionFetcher, "is_fashion_relevant") or GoogleQuestionFetcher.is_fashion_relevant(query, allowed_brand=handle)) and not GoogleQuestionFetcher.has_non_us_location(query) and not GoogleQuestionFetcher.has_competitor_retailer(query, allowed_brand=handle) and not GoogleQuestionFetcher.has_local_intent(query):
                    candidates.append((query, impressions))
                    
        candidates.sort(key=lambda x: x[1], reverse=True)
        queries = [c[0] for c in candidates[:limit]]
        if queries:
            print(f"  [GSC] Found low-hanging keywords for {page_url}: {queries}")
        else:
            # Fallback if exact page yields no results: search Google Autocomplete Suggest queries
            if handle:
                queries = fetch_google_search_keywords(handle, limit)
                queries = [
                    q for q in queries 
                    if (not hasattr(GoogleQuestionFetcher, "is_fashion_relevant") or GoogleQuestionFetcher.is_fashion_relevant(q, allowed_brand=handle))
                    and not GoogleQuestionFetcher.has_non_us_location(q) 
                    and not GoogleQuestionFetcher.has_competitor_retailer(q, allowed_brand=handle)
                    and not GoogleQuestionFetcher.has_local_intent(q)
                ]
                if queries:
                    print(f"  [Google Search] Suggestions found for handle: {queries}")
        return queries
    except Exception as e:
        print(f"  [GSC] Failed to fetch queries for {page_url}: {e}")
        # Fallback on exception
        return fetch_google_search_keywords(handle, limit)

def trigger_url_indexing(url: str):
    """
    Sends instant index ping via IndexNow protocol (supported by Bing, Yandex, Naver)
    and relies on XML sitemaps for Googlebot crawl per Google Search guidelines.
    """
    try:
        indexnow_key = get_secret("INDEXNOW_KEY")
        if indexnow_key:
            payload = {
                "host": "us.meeeshop.com",
                "key": indexnow_key,
                "keyLocation": f"https://us.meeeshop.com/{indexnow_key}.txt",
                "urlList": [url]
            }
            resp = requests.post(
                "https://api.indexnow.org/indexnow",
                headers={"Content-Type": "application/json; charset=utf-8"},
                json=payload,
                timeout=10
            )
            if resp.status_code in (200, 202):
                print(f"  [IndexNow] Instant crawl ping sent for {url}")
            else:
                print(f"  [IndexNow] Ping status HTTP {resp.status_code} for {url}")
        else:
            print(f"  [Sitemap] URL scheduled for Googlebot crawl via sitemap.xml: {url}")
    except Exception as e:
        print(f"  [Indexing] Error pinging IndexNow for {url}: {e}")

def trigger_google_indexing(url: str):
    """Legacy alias: delegates to trigger_url_indexing to avoid Google API spam flags."""
    trigger_url_indexing(url)

STALE_RETURN_RE = re.compile(r'\b(?!7[\s-]*day)\d+[\s-]*day[\s-]*(return|refund|exchange|policy)', re.IGNORECASE)

def has_stale_return_policy(text):
    """True if text mentions any return policy other than 7-day."""
    if not text:
        return False
    return bool(STALE_RETURN_RE.search(text))


def clean_return_policy(text):
    """Replace any stale return policies with the required 7-day policy."""
    if not text:
        return text
    return STALE_RETURN_RE.sub(RETURN_POLICY, text)


# ══════════════════════════════════════════════════════════════════════════════
# TEXT HELPERS
# ══════════════════════════════════════════════════════════════════════════════

SMALL_WORDS = {
    'a','an','the','and','but','or','for','nor','on','at','to','by',
    'in','of','up','as','if','so','yet','with','from','into','via',
    'per','than','over','also','plus','vs','w'
}

ACRONYMS = {'USA','UK','US','UV','XL','XS','XXL','XXXL','2XL','3XL','NYC','LA','NY','DJ','TV','PC'}

def standardize_product_title(title, vendor='', product_type=''):
    """
    Standardize product title according to [Brand] + [Style/Model] + [Category] + [Key Feature]
    Removes supplier codes, prevents duplication, and ensures category keyword presence.
    """
    if not title:
        return title
    original = title.strip()
    v_clean = (vendor or '').strip()
    if v_clean.upper() == 'YMI JEANS':
        v_clean = 'YMI'
    elif v_clean.upper() == 'ORANGE FARM CLOTHING':
        v_clean = 'Orange Farm'
    blocked_suppliers = (
        'CCWHOLESALECLOTHING', 'CC WHOLESALE CLOTHING', 'CC WHOLESALE', 'WHOLESALE',
        'ATHINA RETAIL', 'ATHINA', 'BOHO CLOTHING AND ACCESSORIES', 'BOHO CLOTHING',
        'AILI\'S CORNER', 'AILIS CORNER', 'SUPREME FASHION', 'COTTONWAYS',
        'SHOPBASICBAE', 'BASIC BAE', 'HELLODAY.US', 'HELLO DAY', 'ELLISONYOUNG.COM', 'ELLISONYOUNG',
        'LUCKY FEET SHOES', 'SPUN BAMBOO', 'TRENDSI', 'D&J', 'UNKNOWN', 'OTHER', 'DEFAULT', '',
        'MKF DROPSHIP', 'GLEE + CO', 'GLEE AND CO', 'ORANGE FARM CLOTHING', 'ORANGE FARM',
        'GRACE+EMMA', 'GRACE AND EMMA', 'GRACE & EMMA', 'ARTEMIS VINTAGE', 'ARTEMIS',
        'INDIE & CO.', 'INDIE AND CO.', 'INDIE & CO', 'INDIE AND CO', 'HEY JOANIE',
        'PRETTY SIMPLE', 'MADELINE LOVE', 'MISSFINCHNYC', 'MISS FINCH NYC', 'SNOSKINS',
        'ALYTH ACTIVE', 'DIZZY-LIZZIE', 'DIZZY LIZZIE', 'TROPHY YOGA', 'VAILA SHOES', 'VAILA',
        'BOTORI EQUESTRIAN', 'BOTORI', 'VALENTINE', 'TYCHE', 'DIOSA', 'CEFIAN', 'SOVELLA'
    )
    if v_clean.upper() in blocked_suppliers:
        v_clean = ''
    elif v_clean.upper() == 'MKF DROPSHIP':
        v_clean = 'MKF Collection'
    
    # Remove awkward symbols, brackets, supplier codes, and wholesale distributor prefixes
    cleaned = re.sub(r'^\*+|\*+$', '', original).strip()
    cleaned = re.sub(r'\[.*?\]', '', cleaned).strip()
    cleaned = re.sub(r'\b(Hj\d{3}|HJ\d{3})\b', '', cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r'\b(?:Clearance|New|Sale)\s+', '', cleaned, flags=re.IGNORECASE).strip()
    
    # Comprehensive removal of all 31 wholesale suppliers from titles
    wholesale_patterns = [
        r'\bBoho Clothing and Accessories\b[\s\-\:\—]*',
        r'\bBoho Clothing\b[\s\-\:\—]*',
        r'\bAili\'s Corner\b[\s\-\:\—]*',
        r'\bAilis Corner\b[\s\-\:\—]*',
        r'\bSUPREME FASHION\b[\s\-\:\—]*',
        r'\bSupreme Fashion\b[\s\-\:\—]*',
        r'\bCottonways\b[\s\-\:\—]*',
        r'\bShopbasicbae\b[\s\-\:\—]*',
        r'\bBasic Bae\b[\s\-\:\—]*',
        r'\bHelloday\.us\b[\s\-\:\—]*',
        r'\bHello Day\b[\s\-\:\—]*',
        r'\bEllisonyoung\.com\b[\s\-\:\—]*',
        r'\bEllisonyoung\b[\s\-\:\—]*',
        r'\bLucky Feet Shoes\b[\s\-\:\—]*',
        r'\bSpun Bamboo\b[\s\-\:\—]*',
        r'\bCCWHOLESALECLOTHING\b[\s\-\:\—]*',
        r'\bCC\s+WHOLESALE\s+CLOTHING\b[\s\-\:\—]*',
        r'\bCC\s+WHOLESALE\b[\s\-\:\—]*',
        r'\bATHINA\s+RETAIL\b[\s\-\:\—]*',
        r'\bATHINA\b[\s\-\:\—]*',
        r'\bTrendsi\b[\s\-\:\—]*',
        r'\bMKF\s+Dropship\b[\s\-\:\—]*',
        r'\bglee\s*\+\s*co\b[\s\-\:\—]*',
        r'\bGlee\s+and\s+Co\b[\s\-\:\—]*',
        r'\bOrange\s+Farm\s+Clothing\b[\s\-\:\—]*',
        r'\bOrange\s+Farm\b[\s\-\:\—]*',
        r'\bGrace\s*\+\s*Emma\b[\s\-\:\—]*',
        r'\bGrace\s+and\s+Emma\b[\s\-\:\—]*',
        r'\bArtemis\s+Vintage\b[\s\-\:\—]*',
        r'\bArtemis\b[\s\-\:\—]*',
        r'\bIndie\s*&\s*Co\.?\b[\s\-\:\—]*',
        r'\bIndie\s+and\s+Co\.?\b[\s\-\:\—]*',
        r'\bHey\s+Joanie\b[\s\-\:\—]*',
        r'\bPretty\s+Simple\b[\s\-\:\—]*',
        r'\bMadeline\s+Love\b[\s\-\:\—]*',
        r'\bMissFinchNYC\b[\s\-\:\—]*',
        r'\bMiss\s+Finch\s+NYC\b[\s\-\:\—]*',
        r'\bSnoSkins\b[\s\-\:\—]*',
        r'\bAlyth\s+Active\b[\s\-\:\—]*',
        r'\bDizzy\-Lizzie\b[\s\-\:\—]*',
        r'\bDizzy\s+Lizzie\b[\s\-\:\—]*',
        r'\bTrophy\s+Yoga\b[\s\-\:\—]*',
        r'\bVaila\s+Shoes\b[\s\-\:\—]*',
        r'\bVaila\b[\s\-\:\—]*',
        r'\bBOTORI\s+Equestrian\b[\s\-\:\—]*',
        r'\bBOTORI\b[\s\-\:\—]*',
        r'\bVALENTINE\b[\s\-\:\—]*',
        r'\bTYCHE\b[\s\-\:\—]*',
        r'\bDIOSA\b[\s\-\:\—]*',
        r'\bCEFIAN\b[\s\-\:\—]*',
        r'\bSovella\b[\s\-\:\—]*'
    ]
    for pat in wholesale_patterns:
        cleaned = re.sub(pat, '', cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r'[\s\-–—:\.]+$', '', cleaned).strip()
    cleaned = re.sub(r'^[\s\.\,\*\-\–\—\:\_]+', '', cleaned).strip()
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    
    # Ensure recognized brand is prefixed ONLY if it is a popular consumer brand
    recognized_brands_to_prefix = {
        'JUDY BLUE', 'YMI', 'RISEN', 'EMORY PARK', 'FLYING TOMATO',
        'RETROLICIOUS', 'DOWNEAST', 'HYFVE', 'BUKI', 'GOAL FIVE',
        'ELASTIQUE ATHLETICS', 'MKF COLLECTION'
    }
    if v_clean and v_clean.upper() in recognized_brands_to_prefix:
        has_brand = False
        for v_part in [v_clean, v_clean.split()[0]]:
            if cleaned.lower().startswith(v_part.lower()):
                has_brand = True
                break
        if not has_brand:
            cleaned = f"{v_clean} {cleaned}"
            
    # Ensure category keywords
    ptype_lower = (product_type or '').lower()
    c_lower = cleaned.lower()
    if ('jean' in ptype_lower or 'denim' in ptype_lower) and 'jean' not in c_lower and 'short' not in c_lower and 'pant' not in c_lower and 'jacket' not in c_lower and 'vest' not in c_lower:
        cleaned += " Jeans"
    elif 'dress' in ptype_lower and 'dress' not in c_lower and 'set' not in c_lower:
        cleaned += " Dress"
    elif ('top' in ptype_lower or 'shirt' in ptype_lower) and 'top' not in c_lower and 'shirt' not in c_lower and 'blouse' not in c_lower and 'sweater' not in c_lower and 'tee' not in c_lower and 'tank' not in c_lower:
        cleaned += " Top"
    elif ('tote' in ptype_lower or 'bag' in ptype_lower or 'handbag' in ptype_lower) and 'bag' not in c_lower and 'tote' not in c_lower and 'handbag' not in c_lower:
        cleaned += " Handbag"

    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return title_case(cleaned)


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



BLOCKED_HANDLE_PATTERNS = [
    r'boho-clothing-and-accessories',
    r'boho-clothing',
    r'ailis-corner',
    r'aili-s-corner',
    r'supreme-fashion',
    r'cottonways',
    r'shopbasicbae',
    r'basic-bae',
    r'basicbae',
    r'helloday-us',
    r'hellodayus',
    r'helloday',
    r'hello-day',
    r'ellisonyoung-com',
    r'ellisonyoungcom',
    r'ellisonyoung',
    r'lucky-feet-shoes',
    r'spun-bamboo',
    r'ccwholesaleclothing',
    r'cc-wholesale-clothing',
    r'cc-wholesale',
    r'athina-retail',
    r'athina',
    r'trendsi',
    r'mkf-dropship',
    r'glee-co',
    r'glee-and-co',
    r'orange-farm-clothing',
    r'orange-farm',
    r'grace-emma',
    r'grace-and-emma',
    r'artemis-vintage',
    r'artemis',
    r'indie-co',
    r'indie-and-co',
    r'hey-joanie',
    r'pretty-simple',
    r'madeline-love',
    r'missfinchnyc',
    r'miss-finch-nyc',
    r'snoskins',
    r'alyth-active',
    r'dizzy-lizzie',
    r'trophy-yoga',
    r'vaila-shoes',
    r'vaila',
    r'botori-equestrian',
    r'botori',
    r'valentine',
    r'tyche',
    r'diosa',
    r'cefian',
    r'sovella'
]


def slugify(text):
    if not text:
        return ""
    s = re.sub(r'[^a-z0-9\s-]', '', text.lower())
    s = re.sub(r'[\s_]+', '-', s.strip())
    for pat in BLOCKED_HANDLE_PATTERNS:
        s = re.sub(rf'(?:^|-){pat}(?:-|$)', '-', s, flags=re.IGNORECASE).strip('-')
    s = re.sub(r'-+', '-', s)
    return s[:70].strip('-')


def strip_html(html):
    return re.sub(r'<[^>]+>', ' ', html or '').strip()


def truncate(text, n):
    return text if len(text) <= n else text[:n-1].rsplit(' ', 1)[0] + '…'


# ── Category detection ────────────────────────────────────────────────────────
APPAREL_CATEGORIES = {'Dresses', 'Tops', 'Bottoms', 'Outerwear', 'Skirts', 'One-Pieces'}

CATEGORIES = {
    ('dress','gown','midi','maxi','sundress','shift'):   ('Dresses',   'dress'),
    ('top','blouse','shirt','tee','tank','cami','tunic','sweater','cardigan','pullover','hoodie'):('Tops',      'top'),
    ('jean','pant','short','shorties','legging','jogger','trouser','bottom','denim'):('Bottoms',   'bottom'),
    ('jacket','coat','blazer','outerwear','vest','trench'): ('Outerwear', 'layer'),
    ('skirt',):                                         ('Skirts',    'skirt'),
    ('romper','jumpsuit','bodysuit','playsuit','set','onesie'): ('One-Pieces','one-piece'),
    ('bag','purse','handbag','tote','crossbody','sling','backpack','clutch','satchel','wallet','fanny','duffel'):('Bags', 'bag'),
    ('shoe','boot','heel','sandal','sneaker','flat','mule','slide','footwear','clog'): ('Shoes', 'shoe'),
    ('hat','cap','beanie','jewelry','necklace','earring','bracelet','ring','belt','sunglasses','scarf','accessory','accessories','headband','hair'): ('Accessories', 'accessory')
}

def detect_cat(title, product_type='', tags=''):
    t = title.lower()
    pt = (product_type or '').lower()
    tg = (tags or '').lower()
    search_str = f"{t} {pt} {tg}"
    for keys, (cat, word) in CATEGORIES.items():
        if any(k in search_str for k in keys):
            return cat, word
    return 'Women\'s Fashion', 'piece'


# ── Meta title (Google standard: ≤60 chars, US intent & sizing focused) ────────
def build_meta_title(title, product_type='', tags=''):
    cat, word = detect_cat(title, product_type, tags)
    
    # Extract style keyword (e.g., Boho, Vintage, Casual, Floral, Summer)
    style_keywords = {'boho', 'vintage', 'floral', 'summer', 'casual', 'elegant', 'chic', 'retro', 'cozy', 'oversized', 'knit', 'denim', 'linen', 'silk', 'lace', 'print', 'solid'}
    title_lower = title.lower()
    tag_lower = (tags or '').lower()
    found_style = next((s.title() for s in style_keywords if s in title_lower or s in tag_lower), cat)
    
    # Dynamic sizing hint based on category
    sizing = "XS-3XL" if cat in ('Dresses', 'Tops', 'Bottoms', 'Outerwear', 'One-Pieces', 'Skirts') else "One Size"
    
    # 1. Preferred High-CTR Long-Tail Format: [Title] - [Style] | US Size [Sizing] | Free Shipping
    full = f"{title} - {found_style} | US Size {sizing} | Free Shipping"
    if len(full) <= 60:
        res = full
    elif len(f"{title} | US Size {sizing} | Free US Shipping") <= 60:
        res = f"{title} | US Size {sizing} | Free US Shipping"
    elif len(f"{title} | Free US Shipping") <= 60:
        res = f"{title} | Free US Shipping"
    else:
        max_title_len = 60 - len(" | Free US Shipping")
        truncated_title = title[:max_title_len].rsplit(' ', 1)[0] if ' ' in title[:max_title_len] else title[:max_title_len-1]
        res = f"{truncated_title} | Free US Shipping"
        
    return GoogleQuestionFetcher.remove_disallowed_terms(res, allowed_brand=title)[:60]



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

def build_meta_desc(title, product_type='', tags='', gsc_keywords=None):
    """Deterministic meta description: same title always produces same output (so validation can use exact match)."""
    _, word = detect_cat(title, product_type, tags)
    keywords = extract_keywords(title)
    keywords_str = ' '.join(keywords) if keywords else (title.split()[0] if title.split() else "women's")
    # Deterministic template selection: pick by hash of title (no randomness)
    idx  = sum(ord(c) for c in title) % len(META_DESC_TEMPLATES)
    tpl  = META_DESC_TEMPLATES[idx]
    desc = tpl.format(title=title, brand=BRAND, word=word, keywords_str=keywords_str)
    
    if gsc_keywords:
        kw_suffix = f" Perfect for {', '.join(gsc_keywords)}."
        desc = truncate(desc, 155 - len(kw_suffix)) + kw_suffix
        
    return GoogleQuestionFetcher.remove_disallowed_terms(truncate(desc, 155), allowed_brand=title)[:155]


# ── Image alt text (Google standard: descriptive, ≤125 chars) ─────────────────
def build_alt(title, variant_hint='', idx=0, product_type='', tags='', gsc_keywords=None):
    """
    Build highly descriptive, search-intent rich image alt text for US women's fashion.
    Caps length strictly at 125 chars (Google Image Search standard).
    Follows Google Search guidelines: natural visual description per image view without word stuffing.
    """
    cat, word = detect_cat(title, product_type, tags)
    
    parts = [title.strip()]
    if variant_hint and variant_hint.lower() not in ('default', 'default title', ''):
        parts.append(f"in {variant_hint.strip()}")
    if idx > 0:
        parts.append(f"view {idx + 1}")
    
    # Extract natural US female fashion intent descriptors from tags/title
    tags_str = (tags if isinstance(tags, str) else ", ".join(tags)).lower()
    full_text = f"{title} {tags_str} {product_type}".lower()
    
    intent_descriptors = []
    if any(k in full_text for k in ['high waist', 'high rise', 'high-waisted']):
        intent_descriptors.append("High-Waisted")
    elif any(k in full_text for k in ['curvy', 'plus size', 'tummy control']):
        intent_descriptors.append("Curvy Fit")
    elif any(k in full_text for k in ['stretch', 'elastic']):
        intent_descriptors.append("Comfort Stretch")
    elif any(k in full_text for k in ['oversized', 'relaxed', 'loose']):
        intent_descriptors.append("Relaxed Fit")

    if any(k in full_text for k in ['boho', 'bohemian']):
        intent_descriptors.append("Boho Style")
    elif any(k in full_text for k in ['office', 'work', 'blazer']):
        intent_descriptors.append("Casual Office Outfit")
    elif any(k in full_text for k in ['summer', 'vacation', 'beach', 'resort']):
        intent_descriptors.append("Summer Outfit Idea")
    elif any(k in full_text for k in ['fall', 'winter', 'knit']):
        intent_descriptors.append("Fall Wardrobe Essential")

    base_alt = " ".join(parts)
    if intent_descriptors and intent_descriptors[0].lower() not in base_alt.lower():
        base_alt += f" - {intent_descriptors[0]}"
    
    # Seamlessly integrate ONE top relevant GSC search term if not already present (no raw comma lists)
    if gsc_keywords:
        top_kw = (gsc_keywords[0] if isinstance(gsc_keywords, list) and gsc_keywords else str(gsc_keywords)).strip()
        if top_kw and top_kw.lower() not in base_alt.lower():
            space_left = 125 - len(base_alt) - len(" - ")
            if space_left >= len(top_kw):
                base_alt += f" - {top_kw.title()}"

    if word.lower() not in base_alt.lower() and len(base_alt) <= 110:
        base_alt += f" ({word})"

    return base_alt[:125].strip().rstrip('-').strip()


def build_collection_alt(title):
    clean_title = title.strip()
    alt = f"{clean_title} - US Women's Fashion & Styling Guide Collection"
    if len(alt) > 125:
        alt = f"{clean_title} Collection - US Women's Fashion"
    return alt[:125].strip()


def build_article_alt(title):
    clean_title = title.strip()
    alt = f"{clean_title} - US Women's Fashion & Outfit Style Guide"
    if len(alt) > 125:
        alt = f"{clean_title} - Women's Fashion Style Guide"
    return alt[:125].strip()


def find_file_id_by_filename(filename):
    """Search Shopify files to find the corresponding GID (MediaImage or GenericFile)."""
    from shopify_graphql import run_graphql
    clean_name = filename.split('?')[0].split('/')[-1]
    query = """
    query($queryStr: String) {
      files(first: 5, query: $queryStr) {
        edges {
          node {
            id
          }
        }
      }
    }
    """
    try:
        res = run_graphql(query, {"queryStr": f"filename:{clean_name}"})
        edges = res.get("data", {}).get("files", {}).get("edges", [])
        if edges:
            return edges[0]["node"]["id"]
    except Exception as e:
        print(f"Warning: Failed to search file '{clean_name}': {e}", file=sys.stderr)
    return None


def rename_shopify_file(file_id, new_filename):
    """Rename a Shopify file via fileUpdate mutation."""
    from shopify_graphql import run_graphql
    query = """
    mutation fileUpdate($files: [FileUpdateInput!]!) {
      fileUpdate(files: $files) {
        files { id }
        userErrors { field message }
      }
    }
    """
    try:
        res = run_graphql(query, {"files": [{"id": file_id, "filename": new_filename}]})
        errors = res.get("data", {}).get("fileUpdate", {}).get("userErrors", [])
        if errors:
            print(f"[GraphQL] Errors updating filename for {file_id}: {errors}", file=sys.stderr)
            return False
        return True
    except Exception as e:
        print(f"[GraphQL] Exception updating filename for {file_id}: {e}", file=sys.stderr)
        return False


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


def remove_clothing_size_table(html):
    """Remove any clothing size table (containing bust, waist, hip, etc.) and its heading."""
    if not html:
        return ""
    
    # 1. Match clothing-specific terms inside tables
    clothing_terms = re.compile(r'\b(bust|waist|hip|sleeve|inseam|rise|underwire|chest)\b', re.IGNORECASE)
    
    def replacement(match):
        table_html = match.group(0)
        if clothing_terms.search(table_html):
            return ""
        return table_html
        
    cleaned = re.sub(r'<table[\s\S]*?</table>', replacement, html)
    
    # 2. Clean up orphaned headings like <h3>Size Chart</h3> immediately followed by another heading/tag or end of string
    cleaned = re.sub(
        r'(<h[1-6][^>]*>[^<]*size[^<]*</h[1-6]>\s*|<p[^>]*>\s*<strong>\s*size[^<]*chart[^<]*</strong>\s*</p>\s*)'
        r'(?=<h|<p|<ul>|<li>|<div>|<!--|$)',
        '', cleaned, flags=re.IGNORECASE
    )
    return cleaned.strip()


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



# ── Clean legacy raw query injections ─────────────────────────────────────────
def clean_legacy_query_injections(html: str) -> str:
    """Strip legacy raw '<p>Perfect if you are looking for...</p>' blocks and inline duplicate patterns."""
    if not html:
        return ""
    # 1. Strip standalone paragraphs where the paragraph starts with or consists mainly of 'Perfect if you are looking for'
    cleaned = re.sub(
        r'<p\b[^>]*>\s*Perfect\s+if\s+you\s+are\s+looking\s+for(?:(?!</p>)[\s\S])*?</p>\s*',
        '',
        html,
        flags=re.IGNORECASE
    )
    # 2. Strip inline sentence inside any remaining paragraph
    cleaned = re.sub(
        r'\s*Perfect\s+if\s+you\s+are\s+looking\s+for(?:(?!</p>)[^.?!])*[.?!]',
        '',
        cleaned,
        flags=re.IGNORECASE
    )
    return re.sub(r'\n{3,}', '\n\n', cleaned).strip()


# ── Build category-specific styling tips ──────────────────────────────────────
def build_styling_tips(title, category, word, relevant_keywords=None):
    """Generate dynamic, actionable styling tips for the product incorporating vetted fashion terms."""
    tips_by_cat = {
        'Dresses': [
            f"<strong>Day to Night:</strong> Pair this {word} with clean white sneakers and a denim jacket for casual daytime outings, or elevate with block heels and delicate jewelry for an evening look.",
            f"<strong>Layering:</strong> Elevate the silhouette by layering with a tailored blazer or lightweight knit cardigan during cooler evenings.",
            f"<strong>Accessories:</strong> Complete the ensemble with a structured shoulder bag and minimalist gold or silver accents."
        ],
        'Tops': [
            f"<strong>Effortless Tuck:</strong> Front-tuck this {word} into high-waisted denim or tailored trousers for an elongated, flattering silhouette.",
            f"<strong>Work to Weekend:</strong> Layer under a blazer with tailored pants for the office, or style with relaxed shorts and sandals for weekend brunch.",
            f"<strong>Shoe Pairing:</strong> Complements everyday loafers, clean leather sneakers, or strappy kitten heels."
        ],
        'Bottoms': [
            f"<strong>Balanced Proportions:</strong> Pair these {word}s with a fitted ribbed top, tucked-in blouse, or cropped sweater.",
            f"<strong>Footwear Versatility:</strong> Styles effortlessly with ankle boots, pointed-toe heels, or minimalist sneakers.",
            f"<strong>Finishing Touches:</strong> Accentuate the waistline with a classic belt and a coordinated crossbody bag."
        ],
        'Outerwear': [
            f"<strong>Chic Layering:</strong> Drape this {word} over a monochrome outfit or knit dress for instant polish and sophistication.",
            f"<strong>Texture Play:</strong> Contrast the silhouette with chunky knit scarves and leather boots during cooler seasons.",
            f"<strong>Versatile Fit:</strong> Wear open for a relaxed aesthetic or belt/button it for structured definition."
        ],
        'Skirts': [
            f"<strong>Feminine Silhouette:</strong> Pair with a tucked-in bodysuit or relaxed blouse to highlight the waist.",
            f"<strong>Footwear:</strong> Style with boots in autumn/winter or slide sandals during warm sunny days.",
            f"<strong>Layering:</strong> Top off with a cropped jacket or lightweight cardigan."
        ],
        'One-Pieces': [
            f"<strong>Instant Outfit:</strong> Cinch the waist with a statement belt and slip into heeled mules for an effortlessly elevated ensemble.",
            f"<strong>Casual Appeal:</strong> Layer a fitted tee underneath or throw on a casual denim jacket and slip-on sneakers."
        ],
        'Bags': [
            f"<strong>Daily Staple:</strong> An essential everyday accessory that pairs seamlessly with casual denim, tailored workwear, and evening dresses.",
            f"<strong>Color Harmony:</strong> Coordinates easily with neutral footwear and polished jewelry accents."
        ],
        'Shoes': [
            f"<strong>Style Anchor:</strong> An effortless anchor piece that completes midi dresses, cropped trousers, or relaxed denim.",
            f"<strong>All-Day Comfort:</strong> Designed for versatility and comfort whether commuting, dining out, or shopping."
        ]
    }
    
    tips = list(tips_by_cat.get(category, [
        f"<strong>Everyday Style:</strong> Easily style this {word} with your go-to wardrobe essentials for a chic, balanced aesthetic.",
        f"<strong>Versatile Pairings:</strong> Dress up with tailored accents or keep it relaxed with casual staples and comfortable footwear."
    ]))
    
    if relevant_keywords:
        for kw in relevant_keywords:
            kw_clean = kw.strip()
            if not kw_clean:
                continue
            tip_str = f"<strong>Style Inspiration:</strong> Ideal if you are styling for an effortless {kw_clean} look. Pair with versatile accessories for a polished finish."
            if not any(kw_clean.lower() in t.lower() for t in tips):
                tips.append(tip_str)
                if len(tips) >= 4:
                    break

    html = ["<h3>Styling Tips & Outfit Ideas</h3>", "<ul>"]
    for tip in tips:
        html.append(f"  <li>{tip}</li>")
    html.append("</ul>")
    return "\n".join(html)


def integrate_styling_tips(body_html: str, title: str, category: str, word: str, relevant_keywords=None) -> str:
    """
    Ensure styling tips exist in body_html.
    If Styling Tips section already exists, append new relevant keywords as list items (without duplicates).
    If it does not exist, build and append a new Styling Tips section.
    """
    body = body_html or ""
    st_pattern = re.compile(
        r'(<h3>(?:Styling\s+Tips[^<]*|Outfit\s+Ideas[^<]*)</h3>\s*<ul\b[^>]*>)([\s\S]*?)(</ul>)',
        re.IGNORECASE
    )
    match = st_pattern.search(body)
    if match:
        prefix = match.group(1)
        ul_content = match.group(2)
        suffix = match.group(3)
        if relevant_keywords:
            new_items = []
            existing_items = re.findall(r'<li\b[^>]*>([\s\S]*?)</li>', ul_content, re.IGNORECASE)
            existing_text = " ".join(existing_items).lower()
            for kw in relevant_keywords:
                kw_clean = kw.strip()
                if not kw_clean:
                    continue
                if kw_clean.lower() in existing_text:
                    continue
                new_item = f"  <li><strong>Style Inspiration:</strong> Ideal if you are styling for an effortless {kw_clean} look. Pair with versatile accessories for a polished finish.</li>"
                new_items.append(new_item)
                existing_text += " " + kw_clean.lower()
            if new_items:
                if len(existing_items) + len(new_items) <= 5:
                    combined_ul = ul_content.rstrip() + "\n" + "\n".join(new_items) + "\n"
                    updated_section = prefix + combined_ul + suffix
                    body = body[:match.start()] + updated_section + body[match.end():]
        return body
    else:
        st_html = build_styling_tips(title, category, word, relevant_keywords=relevant_keywords)
        if "<h3>Frequently Asked Questions</h3>" in body:
            parts = body.split("<h3>Frequently Asked Questions</h3>", 1)
            return parts[0].strip() + "\n\n" + st_html + "\n\n<h3>Frequently Asked Questions</h3>" + parts[1]
        else:
            sep = "\n\n" if body.strip() else ""
            return body.strip() + sep + st_html


# ── Build category-specific Q&As ──────────────────────────────────────────────
def build_templated_qa(title, cat, word):
    """Generate 3 high-quality deterministic Q&As for the product page."""
    # Define category-specific Q&A templates
    qa_templates = {
        'Dresses': [
            ("What is the fit and sizing of the {title}?", 
             "The {title} runs true to size. Please refer to our detailed size chart above (S/M/L) to find your perfect measurements."),
            ("What occasions are suitable for this {word}?", 
             "The {title} is designed for versatile everyday styling. Depending on the occasion, it can easily be dressed up with layers or worn as a relaxed statement piece."),
            ("What is the return policy for the {title}?", 
             "We offer a 7-day return policy for the {title} to ensure you are completely satisfied with your purchase.")
        ],
        'Tops': [
            ("How does the {title} fit?", 
             "The {title} is designed for a comfortable, regular fit. We recommend checking the bust and waist measurements in our size guide before ordering."),
            ("How should I wash and care for this {word}?", 
             "To maintain the fabric quality, we recommend hand washing or machine washing on a delicate cycle with cold water, then hanging or lying flat to dry."),
            ("What is the shipping cost and return policy?", 
             "We offer free US shipping on orders over $50 and a hassle-free 7-day return policy on all eligible purchases.")
        ],
        'Bottoms': [
            ("What is the rise and length of the {title}?", 
             "The {title} features a mid-to-high rise cut designed to sit comfortably at your waist. Check our sizing table for specific waist and hip measurements."),
            ("Is the fabric of this {word} stretchy?", 
             "The {title} is crafted with high-quality materials designed for both durability and comfort, providing a natural shape and comfortable wear throughout the day."),
            ("Can I return the {title} if it doesn't fit?", 
             "Yes! We accept returns within 7 days of delivery. Please ensure the {word} is in its original, unworn condition with tags attached.")
        ],
        'Outerwear': [
            ("How heavy is the {title}?", 
             "The {title} is a premium medium-weight {word} designed for easy layering. It provides the perfect balance of warmth and breathability for transitional weather."),
            ("Does this {word} fit true to size?", 
             "Yes, the {title} fits true to size for standard layering. If you prefer an oversized fit, we suggest ordering one size up."),
            ("What returns and shipping options are available?", 
             "This item qualifies for free US shipping (orders $50+) and is backed by our standard 7-day return policy.")
        ],
        'Skirts': [
            ("What is the length of the {title}?", 
             "The {title} is cut to a classic silhouette. Detailed waist and hip measurements are available in our sizing guide to ensure an accurate fit."),
            ("How do I style this skirt?", 
             "This skirt pairs beautifully with tucked-in tees, blouses, or cardigans for an elevated office or weekend look."),
            ("What is the return policy for the {title}?", 
             "We offer an easy 7-day return window. Contact us within 7 days of receiving your item to start a return.")
        ],
        'One-Pieces': [
            ("What is the fit profile of the {title}?", 
             "The {title} is cut for a modern, contoured fit that flatters your natural silhouette. Refer to our size guide for bust, waist, and hip details."),
            ("How do I care for this {word}?", 
             "We suggest washing the {title} inside out in cold water on a gentle cycle, then hang drying to preserve the fabric and fit."),
            ("Is shipping free for this item?", 
             "Yes, free US shipping is automatically applied to all orders over $50, and returns are accepted within 7 days.")
        ],
        'Bags': [
            ("What are the dimensions of the {title}?", 
             "The {title} is a spacious, daily-use bag designed to carry your essentials. It features durable construction and secure closures."),
            ("Are there interior pockets in this {word}?", 
             "Yes, the {title} includes convenient compartments to keep your small items organized and easy to access on the go."),
            ("What is MeeeShop's return policy?", 
             "We offer a 7-day return policy. If you're not completely in love with your {title}, simply contact support within 7 days of delivery.")
        ],
        'Shoes': [
            ("Is the {title} comfortable for all-day wear?", 
             "The {title} is crafted with cushioned footbeds and premium support, making it comfortable for daily walking and extended wear."),
            ("Does this shoe run narrow or wide?", 
             "The {title} fits true to size for standard widths. If you typically wear a half-size, we recommend sizing up to the nearest whole size."),
            ("What is the return policy for footwear?", 
             "Footwear must be in unworn condition and in their original packaging to qualify for our standard 7-day return window.")
        ],
        'default': [
            ("What is the sizing fit for the {title}?", 
             "The {title} runs true to standard US fashion sizing. Please check the measurements in our size guide to find your perfect fit."),
            ("What are the care instructions for this {word}?", 
             "We recommend washing in cold water with similar colors and hang drying or laying flat to preserve the color and texture of the fabric."),
            ("What shipping and return policies apply?", 
             "All orders over $50 qualify for free shipping. We also provide a standard 7-day return policy on all unworn items.")
        ]
    }
    
    selected_qa = qa_templates.get(cat, qa_templates['default'])
    formatted_qa = []
    for q, a in selected_qa:
        formatted_qa.append((q.format(title=title, word=word), a.format(title=title, word=word)))
    return formatted_qa


def build_qa_html(qa_list):
    """Build the HTML representation of the Q&A section."""
    html = "<h3>Frequently Asked Questions</h3>"
    html += "<div class='meeeshop-qa-section' style='margin-top: 15px;'>"
    for q, a in qa_list:
        html += f"<p><strong>Q: {q}</strong><br/>A: {a}</p>"
    html += "</div>"
    return html


# ── SEO description with keywords + size chart ───────────────────────────────
def build_description(product, force=False, gsc_keywords=None):
    title    = product['title']
    html_body = clean_legacy_query_injections(product.get('body_html', '') or '')
    cat, word = detect_cat(title)
    
    if cat not in APPAREL_CATEGORIES:
        html_body = remove_clothing_size_table(html_body)
        
    existing = strip_html(html_body)

    # Filter and vet GSC/Google suggestions to only fashion-relevant terms
    vetted_keywords = []
    if gsc_keywords:
        for kw in gsc_keywords:
            kw_str = str(kw).strip()
            if not kw_str:
                continue
            if hasattr(GoogleQuestionFetcher, 'is_fashion_relevant'):
                if GoogleQuestionFetcher.is_fashion_relevant(kw_str, allowed_brand=title):
                    vetted_keywords.append(kw_str)
            elif not GoogleQuestionFetcher.has_non_us_location(kw_str):
                vetted_keywords.append(kw_str)

    # Detect if product already has a custom/storytelling description
    if len(existing) >= 200 and not ("Discover the" in html_body and "Why Choose" in html_body):
        # Preserve the custom description, clean return policies
        cleaned_body = clean_return_policy(html_body)
        if cat not in APPAREL_CATEGORIES:
            final_body = cleaned_body.strip()
        else:
            if not has_size_table(cleaned_body):
                size_chart = build_size_chart(word)
                final_body = cleaned_body.strip() + "\n\n" + size_chart
            else:
                final_body = cleaned_body

        # Seamlessly integrate vetted keywords into styling tips without duplicate sections or tips
        final_body = integrate_styling_tips(final_body, title, cat, word, relevant_keywords=vetted_keywords)

        if "Frequently Asked Questions" not in final_body:
            qa_list = build_templated_qa(title, cat, word)
            qa_html = build_qa_html(qa_list)
            final_body = final_body.strip() + "\n\n" + qa_html

        return clean_legacy_query_injections(final_body)

    keywords = extract_keywords(title)
    keywords_str = ' '.join(keywords) if keywords else ''

    intro = (
        f"<p><strong>Discover the {title} at {DISPLAY_BRAND}.</strong> This {word} combines "
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
        f"<h3>Why Choose the {title} at {DISPLAY_BRAND}?</h3>"
        f"<p>Looking for women's fashion? Our curated selection of {word}s for women features "
        f"quality that lasts. Whether you're shopping for everyday essentials or something special, "
        f"we have options for every style and budget.</p>"
        f"<p><strong>Shop {word}s for women. Free US shipping. {RETURN_POLICY}. "
        f"Shop {DISPLAY_BRAND} today.</strong></p>"
    )

    # Preserve existing size table verbatim; otherwise build standard one for apparel
    existing_table = extract_size_table(html_body)
    if cat not in APPAREL_CATEGORIES:
        size_chart = ''
    else:
        if existing_table:
            size_chart = existing_table
        else:
            size_chart = build_size_chart(word)

    styling_tips = build_styling_tips(title, cat, word, relevant_keywords=vetted_keywords)

    if not force and len(existing) >= 500:
        final_body = integrate_styling_tips(html_body, title, cat, word, relevant_keywords=vetted_keywords)
    else:
        final_body = intro + features + why_choose + "\n\n" + styling_tips + ("\n\n" + size_chart if size_chart else "")

    if "Frequently Asked Questions" not in final_body:
        qa_list = build_templated_qa(title, cat, word)
        qa_html = build_qa_html(qa_list)
        final_body = final_body.strip() + "\n\n" + qa_html

    return clean_legacy_query_injections(final_body)



# ══════════════════════════════════════════════════════════════════════════════
# SHOPIFY API HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _check_rate(r):
    lim  = r.headers.get('X-Shopify-Shop-Api-Call-Limit', '0/40')
    used = int(lim.split('/')[0])
    if used >= 36:
        time.sleep(0.6)


def api_request(method, path_or_url, max_retries=5, **kwargs):
    """Make HTTP request to Shopify API with exponential backoff on 429 / rate limit."""
    url = path_or_url if path_or_url.startswith("http") else f"{BASE}{path_or_url}"
    
    headers = kwargs.pop("headers", HEADS)
    
    backoff = 5
    for attempt in range(max_retries):
        try:
            r = requests.request(method, url, headers=headers, **kwargs)
            
            # If 429 rate limit hit, backoff and retry
            if r.status_code == 429:
                retry_after = float(r.headers.get("Retry-After", backoff))
                print(f"  [Rate Limit 429] Waiting {retry_after}s before retry {attempt + 1}/{max_retries}...")
                time.sleep(retry_after)
                backoff = min(backoff * 2, 60)
                continue
                
            r.raise_for_status()
            _check_rate(r)
            return r
        except requests.exceptions.RequestException as e:
            if attempt < max_retries - 1:
                print(f"  [Request Error] {e}. Retrying in {backoff}s...")
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)
            else:
                raise e


def api_get(path, params=None):
    r = api_request("GET", path, params=params)
    return r.json()


def api_put(path, body):
    r = api_request("PUT", path, json=body)
    return r.json()


def api_post(path, body):
    r = api_request("POST", path, json=body)
    return r.json()


def fetch_products(created_since=None):
    """Fetch active products created since cutoff (catches new dropship imports by any vendor)."""
    products, url = [], f"{BASE}/products.json?limit=250&status=active"
    if created_since:
        url += f"&created_at_min={created_since}"
    while url:
        r = api_request("GET", url)
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
        r = api_request("GET", url)
        pages.extend(r.json().get('pages', []))
        nxt = [p.split(';')[0].strip().strip('<>') for p in r.headers.get('Link','').split(',') if 'rel="next"' in p]
        url = nxt[0] if nxt else None
    return pages


def fetch_collections(created_since=None):
    """Fetch both custom and smart collections created since cutoff."""
    collections = []
    
    # 1. Fetch custom collections
    url = f"{BASE}/custom_collections.json?limit=250"
    if created_since:
        url += f"&created_at_min={created_since}"
    while url:
        r = api_request("GET", url)
        for c in r.json().get('custom_collections', []):
            c['_type'] = 'custom_collections'
            collections.append(c)
        nxt = [p.split(';')[0].strip().strip('<>') for p in r.headers.get('Link','').split(',') if 'rel="next"' in p]
        url = nxt[0] if nxt else None

    # 2. Fetch smart collections
    url = f"{BASE}/smart_collections.json?limit=250"
    if created_since:
        url += f"&created_at_min={created_since}"
    while url:
        r = api_request("GET", url)
        for c in r.json().get('smart_collections', []):
            c['_type'] = 'smart_collections'
            collections.append(c)
        nxt = [p.split(';')[0].strip().strip('<>') for p in r.headers.get('Link','').split(',') if 'rel="next"' in p]
        url = nxt[0] if nxt else None

    return collections


def fetch_articles(published_since=None):
    """Fetch blog articles published since cutoff."""
    articles, url = [], f"{BASE}/blogs.json?limit=250"

    blogs = []
    while url:
        r = api_request("GET", url)
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
            r = api_request("GET", article_url)
            fetched_articles = r.json().get('articles', [])
            for article in fetched_articles:
                article['blog_handle'] = blog_handle
            articles.extend(fetched_articles)
            nxt = [p.split(';')[0].strip().strip('<>') for p in r.headers.get('Link','').split(',') if 'rel="next"' in p]
            article_url = nxt[0] if nxt else None

    return articles


# ── Metafields (meta title + meta description) ────────────────────────────────
def set_seo_metafields_graphql(resource_type: str, resource_id: int, meta_title: str, meta_desc: str) -> bool:
    """Set SEO metafields (title + desc) in a single GraphQL mutation."""
    from shopify_graphql import make_gid, run_graphql
    
    # Normalize resource type for GraphQL make_gid
    if "collection" in resource_type.lower():
        gql_type = "collection"
    elif "blog" in resource_type.lower() or "article" in resource_type.lower():
        gql_type = "article"
    elif "page" in resource_type.lower():
        gql_type = "page"
    elif "product" in resource_type.lower():
        gql_type = "product"
    else:
        gql_type = resource_type

    owner_id = make_gid(gql_type, resource_id)
    
    # 1. Update native resource.seo fields if supported (product, collection, page)
    try:
        if gql_type == "product":
            q_native = "mutation productUpdate($input: ProductInput!) { productUpdate(input: $input) { product { id } userErrors { field message } } }"
            run_graphql(q_native, {"input": {"id": owner_id, "seo": {"title": meta_title, "description": meta_desc}}})
        elif gql_type == "collection":
            q_native = "mutation collectionUpdate($input: CollectionInput!) { collectionUpdate(input: $input) { collection { id } userErrors { field message } } }"
            run_graphql(q_native, {"input": {"id": owner_id, "seo": {"title": meta_title, "description": meta_desc}}})
        elif gql_type == "page":
            q_native = "mutation pageUpdate($input: PageInput!) { pageUpdate(input: $input) { page { id } userErrors { field message } } }"
            run_graphql(q_native, {"input": {"id": owner_id, "seo": {"title": meta_title, "description": meta_desc}}})
    except Exception as ne:
        print(f"[GraphQL Warning] Failed updating native SEO for {owner_id}: {ne}", file=sys.stderr)

    # 2. Update global.title_tag and global.description_tag metafields
    query = """
    mutation metafieldsSet($metafields: [MetafieldsSetInput!]!) {
      metafieldsSet(metafields: $metafields) {
        metafields { id }
        userErrors { field message }
      }
    }
    """
    variables = {
      "metafields": [
        {
          "ownerId": owner_id,
          "namespace": "global",
          "key": "title_tag",
          "type": "single_line_text_field",
          "value": meta_title
        },
        {
          "ownerId": owner_id,
          "namespace": "global",
          "key": "description_tag",
          "type": "multi_line_text_field",
          "value": meta_desc
        }
      ]
    }
    try:
        res = run_graphql(query, variables)
        errors = res.get("data", {}).get("metafieldsSet", {}).get("userErrors", [])
        if errors:
            print(f"[GraphQL] Errors setting SEO metafields for {owner_id}: {errors}", file=sys.stderr)
            return False
        return True
    except Exception as e:
        print(f"[GraphQL] Exception setting SEO metafields for {owner_id}: {e}", file=sys.stderr)
        return False


def set_seo_metafields(resource_path, rid, meta_title, meta_desc, existing_mfs=None):
    """Bridge function to set SEO metafields (title + desc) for any resource via GraphQL."""
    success = set_seo_metafields_graphql(resource_path, rid, meta_title, meta_desc)
    if not success:
        raise RuntimeError(f"Failed to set SEO metafields for {resource_path} {rid}")


# ── Image alt text ────────────────────────────────────────────────────────────
def update_image_alt(pid, iid, alt, src=None, idx=0):
    """Update product image alt text and filename via GraphQL."""
    from shopify_graphql import make_gid, run_graphql
    product_gid = make_gid("product", pid)
    media_gid = f"gid://shopify/MediaImage/{iid}"
    
    # 1. Update Alt Text via productUpdateMedia
    query = """
    mutation productUpdateMedia($productId: ID!, $media: [UpdateMediaInput!]!) {
      productUpdateMedia(productId: $productId, media: $media) {
        media { id alt }
        userErrors { field message }
      }
    }
    """
    variables = {
        "productId": product_gid,
        "media": [
            {
                "id": media_gid,
                "alt": alt
            }
        ]
    }
    success = True
    try:
        res = run_graphql(query, variables)
        errors = res.get("data", {}).get("productUpdateMedia", {}).get("userErrors", [])
        if errors:
            print(f"[GraphQL] Errors updating image alt for {media_gid}: {errors}", file=sys.stderr)
            success = False
    except Exception as e:
        print(f"[GraphQL] Exception updating image alt for {media_gid}: {e}", file=sys.stderr)
        success = False

    # 2. Update Filename via fileUpdate if src (CDN URL) is provided
    if src and success:
        # Extract original filename and extension
        clean_url = src.split('?')[0]
        base = clean_url.split('/')[-1]
        if '.' in base:
            ext = base.rsplit('.', 1)[1].lower()
            # Generate optimized filename slug from the new alt text
            slug = slugify(alt)
            # Ensure unique filename by appending a portion of the media image ID
            media_suffix = str(iid)[-6:] if iid else str(int(time.time() * 1000))[-6:]
            if idx > 0:
                slug = f"{slug[:50].strip('-')}-view-{idx+1}-{media_suffix}"
            else:
                slug = f"{slug[:50].strip('-')}-{media_suffix}"
            new_filename = f"{slug}.{ext}"
            
            # Always replace old filename with the new clean Google-supported filename if different
            current_name = base.rsplit('.', 1)[0].lower()
            if base.lower() != new_filename.lower():
                query_file = """
                mutation fileUpdate($files: [FileUpdateInput!]!) {
                  fileUpdate(files: $files) {
                    files { id }
                    userErrors { field message }
                  }
                }
                """
                variables_file = {
                    "files": [
                        {
                            "id": media_gid,
                            "filename": new_filename
                        }
                    ]
                }
                try:
                    res_file = run_graphql(query_file, variables_file)
                    errors_file = res_file.get("data", {}).get("fileUpdate", {}).get("userErrors", [])
                    if errors_file:
                        print(f"[GraphQL] Errors updating filename for {media_gid}: {errors_file}", file=sys.stderr)
                    else:
                        print(f"  + Filename updated: '{base}' -> '{new_filename}'")
                except Exception as e:
                    print(f"[GraphQL] Exception updating filename for {media_gid}: {e}", file=sys.stderr)

    return success


# ── Redirects ─────────────────────────────────────────────────────────────────
def create_redirect(old, new):
    try:
        r = api_request("GET", f"/redirects.json", params={"path": f"/products/{old}"})
        if r.json().get('redirects'):
            return False
        api_post("/redirects.json",
                 {"redirect": {"path": f"/products/{old}", "target": f"/products/{new}"}})
        return True
    except Exception:
        return False


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
        }{%- unless forloop.last -%},{%- endunless -%}
        {%- endfor -%}
      ]
    }
    {%- if product.description contains 'Frequently Asked Questions' -%}
    ,{
      "@type": "FAQPage",
      "@id": "{{ shop.url }}/products/{{ product.handle }}#faq",
      "mainEntity": [
        {%- assign word = 'piece' -%}
        {%- assign cat = 'default' -%}
        {%- assign title_lower = product.title | downcase -%}
        {%- if title_lower contains 'dress' or title_lower contains 'gown' or title_lower contains 'midi' or title_lower contains 'maxi' or title_lower contains 'sundress' or title_lower contains 'shift' -%}
          {%- assign cat = 'Dresses' -%}{%- assign word = 'dress' -%}
        {%- elsif title_lower contains 'top' or title_lower contains 'blouse' or title_lower contains 'shirt' or title_lower contains 'tee' or title_lower contains 'tank' or title_lower contains 'cami' or title_lower contains 'tunic' -%}
          {%- assign cat = 'Tops' -%}{%- assign word = 'top' -%}
        {%- elsif title_lower contains 'jean' or title_lower contains 'pant' or title_lower contains 'short' or title_lower contains 'legging' or title_lower contains 'jogger' or title_lower contains 'trouser' -%}
          {%- assign cat = 'Bottoms' -%}{%- assign word = 'bottom' -%}
        {%- elsif title_lower contains 'jacket' or title_lower contains 'coat' or title_lower contains 'blazer' or title_lower contains 'sweater' or title_lower contains 'hoodie' or title_lower contains 'cardigan' or title_lower contains 'pullover' -%}
          {%- assign cat = 'Outerwear' -%}{%- assign word = 'layer' -%}
        {%- elsif title_lower contains 'skirt' -%}
          {%- assign cat = 'Skirts' -%}{%- assign word = 'skirt' -%}
        {%- elsif title_lower contains 'romper' or title_lower contains 'jumpsuit' or title_lower contains 'bodysuit' or title_lower contains 'playsuit' -%}
          {%- assign cat = 'One-Pieces' -%}{%- assign word = 'one-piece' -%}
        {%- elsif title_lower contains 'bag' or title_lower contains 'purse' or title_lower contains 'handbag' or title_lower contains 'tote' or title_lower contains 'crossbody' or title_lower contains 'sling' -%}
          {%- assign cat = 'Bags' -%}{%- assign word = 'bag' -%}
        {%- elsif title_lower contains 'shoe' or title_lower contains 'boot' or title_lower contains 'heel' or title_lower contains 'sandal' or title_lower contains 'sneaker' or title_lower contains 'flat' -%}
          {%- assign cat = 'Shoes' -%}{%- assign word = 'shoe' -%}
        {%- endif -%}
        {%- if cat == 'Dresses' -%}
          {
            "@type": "Question",
            "name": "What is the fit and sizing of the {{ product.title | escape }}?",
            "acceptedAnswer": {
              "@type": "Answer",
              "text": "The {{ product.title | escape }} runs true to size. Please refer to our detailed size chart above (S/M/L) to find your perfect measurements."
            }
          },
          {
            "@type": "Question",
            "name": "What occasions are suitable for this dress?",
            "acceptedAnswer": {
              "@type": "Answer",
              "text": "The {{ product.title | escape }} is designed for versatile everyday styling. Depending on the occasion, it can easily be dressed up with layers or worn as a relaxed statement piece."
            }
          },
          {
            "@type": "Question",
            "name": "What is the return policy for the {{ product.title | escape }}?",
            "acceptedAnswer": {
              "@type": "Answer",
              "text": "We offer a 7-day return policy for the {{ product.title | escape }} to ensure you are completely satisfied with your purchase."
            }
          }
        {%- elsif cat == 'Tops' -%}
          {
            "@type": "Question",
            "name": "How does the {{ product.title | escape }} fit?",
            "acceptedAnswer": {
              "@type": "Answer",
              "text": "The {{ product.title | escape }} is designed for a comfortable, regular fit. We recommend checking the bust and waist measurements in our size guide before ordering."
            }
          },
          {
            "@type": "Question",
            "name": "How should I wash and care for this top?",
            "acceptedAnswer": {
              "@type": "Answer",
              "text": "To maintain the fabric quality, we recommend hand washing or machine washing on a delicate cycle with cold water, then hanging or lying flat to dry."
            }
          },
          {
            "@type": "Question",
            "name": "What is the shipping cost and return policy?",
            "acceptedAnswer": {
              "@type": "Answer",
              "text": "We offer free US shipping on orders over $50 and a hassle-free 7-day return policy on all eligible purchases."
            }
          }
        {%- elsif cat == 'Bottoms' -%}
          {
            "@type": "Question",
            "name": "What is the rise and length of the {{ product.title | escape }}?",
            "acceptedAnswer": {
              "@type": "Answer",
              "text": "The {{ product.title | escape }} features a mid-to-high rise cut designed to sit comfortably at your waist. Check our sizing table for specific waist and hip measurements."
            }
          },
          {
            "@type": "Question",
            "name": "Is the fabric of this bottom stretchy?",
            "acceptedAnswer": {
              "@type": "Answer",
              "text": "The {{ product.title | escape }} is crafted with high-quality materials designed for both durability and comfort, providing a natural shape and comfortable wear throughout the day."
            }
          },
          {
            "@type": "Question",
            "name": "Can I return the {{ product.title | escape }} if it doesn't fit?",
            "acceptedAnswer": {
              "@type": "Answer",
              "text": "Yes! We accept returns within 7 days of delivery. Please ensure the bottom is in its original, unworn condition with tags attached."
            }
          }
        {%- elsif cat == 'Outerwear' -%}
          {
            "@type": "Question",
            "name": "How heavy is the {{ product.title | escape }}?",
            "acceptedAnswer": {
              "@type": "Answer",
              "text": "The {{ product.title | escape }} is a premium medium-weight layer designed for easy layering. It provides the perfect balance of warmth and breathability for transitional weather."
            }
          },
          {
            "@type": "Question",
            "name": "Does this layer fit true to size?",
            "acceptedAnswer": {
              "@type": "Answer",
              "text": "Yes, the {{ product.title | escape }} fits true to size for standard layering. If you prefer an oversized fit, we suggest ordering one size up."
            }
          },
          {
            "@type": "Question",
            "name": "What returns and shipping options are available?",
            "acceptedAnswer": {
              "@type": "Answer",
              "text": "This item qualifies for free US shipping (orders $50+) and is backed by our standard 7-day return policy."
            }
          }
        {%- elsif cat == 'Skirts' -%}
          {
            "@type": "Question",
            "name": "What is the length of the {{ product.title | escape }}?",
            "acceptedAnswer": {
              "@type": "Answer",
              "text": "The {{ product.title | escape }} is cut to a classic silhouette. Detailed waist and hip measurements are available in our sizing guide to ensure an accurate fit."
            }
          },
          {
            "@type": "Question",
            "name": "How do I style this skirt?",
            "acceptedAnswer": {
              "@type": "Answer",
              "text": "This skirt pairs beautifully with tucked-in tees, blouses, or cardigans for an elevated office or weekend look."
            }
          },
          {
            "@type": "Question",
            "name": "What is the return policy for the {{ product.title | escape }}?",
            "acceptedAnswer": {
              "@type": "Answer",
              "text": "We offer an easy 7-day return window. Contact us within 7 days of receiving your item to start a return."
            }
          }
        {%- elsif cat == 'One-Pieces' -%}
          {
            "@type": "Question",
            "name": "What is the fit profile of the {{ product.title | escape }}?",
            "acceptedAnswer": {
              "@type": "Answer",
              "text": "The {{ product.title | escape }} is cut for a modern, contoured fit that flatters your natural silhouette. Refer to our size guide for bust, waist, and hip details."
            }
          },
          {
            "@type": "Question",
            "name": "How do I care for this one-piece?",
            "acceptedAnswer": {
              "@type": "Answer",
              "text": "We suggest washing the {{ product.title | escape }} inside out in cold water on a gentle cycle, then hang drying to preserve the fabric and fit."
            }
          },
          {
            "@type": "Question",
            "name": "Is shipping free for this item?",
            "acceptedAnswer": {
              "@type": "Answer",
              "text": "Yes, free US shipping is automatically applied to all orders over $50, and returns are accepted within 7 days."
            }
          }
        {%- elsif cat == 'Bags' -%}
          {
            "@type": "Question",
            "name": "What are the dimensions of the {{ product.title | escape }}?",
            "acceptedAnswer": {
              "@type": "Answer",
              "text": "The {{ product.title | escape }} is a spacious, daily-use bag designed to carry your essentials. It features durable construction and secure closures."
            }
          },
          {
            "@type": "Question",
            "name": "Are there interior pockets in this bag?",
            "acceptedAnswer": {
              "@type": "Answer",
              "text": "Yes, the {{ product.title | escape }} includes convenient compartments to keep your small items organized and easy to access on the go."
            }
          },
          {
            "@type": "Question",
            "name": "What is MeeeShop's return policy?",
            "acceptedAnswer": {
              "@type": "Answer",
              "text": "We offer a 7-day return policy. If you're not completely in love with your {{ product.title | escape }}, simply contact support within 7 days of delivery."
            }
          }
        {%- elsif cat == 'Shoes' -%}
          {
            "@type": "Question",
            "name": "Is the {{ product.title | escape }} comfortable for all-day wear?",
            "acceptedAnswer": {
              "@type": "Answer",
              "text": "The {{ product.title | escape }} is crafted with cushioned footbeds and premium support, making it comfortable for daily walking and extended wear."
            }
          },
          {
            "@type": "Question",
            "name": "Does this shoe run narrow or wide?",
            "acceptedAnswer": {
              "@type": "Answer",
              "text": "The {{ product.title | escape }} fits true to size for standard widths. If you typically wear a half-size, we recommend sizing up to the nearest whole size."
            }
          },
          {
            "@type": "Question",
            "name": "What is the return policy for footwear?",
            "acceptedAnswer": {
              "@type": "Answer",
              "text": "Footwear must be in unworn condition and in their original packaging to qualify for our standard 7-day return window."
            }
          }
        {%- else -%}
          {
            "@type": "Question",
            "name": "What is the sizing fit for the {{ product.title | escape }}?",
            "acceptedAnswer": {
              "@type": "Answer",
              "text": "The {{ product.title | escape }} runs true to standard US fashion sizing. Please check the measurements in our size guide to find your perfect fit."
            }
          },
          {
            "@type": "Question",
            "name": "What are the care instructions for this piece?",
            "acceptedAnswer": {
              "@type": "Answer",
              "text": "We recommend washing in cold water with similar colors and hang drying or laying flat to preserve the color and texture of the fabric."
            }
          },
          {
            "@type": "Question",
            "name": "What shipping and return policies apply?",
            "acceptedAnswer": {
              "@type": "Answer",
              "text": "All orders over $50 qualify for free shipping. We also provide a standard 7-day return policy on all unworn items."
            }
          }
        {%- endif -%}
      ]
    }
    {%- endif -%}
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
    try:
        r = api_request("GET", f"/themes/{theme_id}/assets.json", params={"asset[key]": key})
        if r.status_code == 200:
            return r.json().get('asset', {}).get('value', '')
    except Exception:
        return None
    return None


def put_asset(theme_id, key, value):
    try:
        r = api_request("PUT", f"/themes/{theme_id}/assets.json", json={"asset": {"key": key, "value": value}})
        return r.status_code in (200, 201)
    except Exception:
        return False


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

def validate_seo(item, item_type, existing_mfs, gsc_keywords=None):
    """Strict template validation. Returns list of {field, before, after, [_img_id, _img_idx]} dicts."""
    mismatches = []
    title = item.get('title', '')

    if item_type == "product":
        ptype = item.get('product_type', '')
        tags = item.get('tags', '')
    else:
        ptype = ''
        tags = ''

    # ── Meta title (exact match) ──────────────────────────────────────────────
    expected_meta_title = build_meta_title(title, ptype, tags)
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
        and not GoogleQuestionFetcher.has_non_us_location(cur_meta_desc)
        and not GoogleQuestionFetcher.has_competitor_retailer(cur_meta_desc, allowed_brand=title)
    )
    if not desc_ok:
        new_meta_desc = build_meta_desc(title, ptype, tags, gsc_keywords=gsc_keywords)
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

        # Allow custom descriptions (length >= 200, without SEO template markers) if they have a table and no stale return policy
        is_custom = len(strip_html(body_html)) >= 200 and not ("Discover the" in body_html and "Why Choose" in body_html)
        if is_custom:
            body_ok = has_table and not has_stale_body
        else:
            body_ok = has_all_markers and not has_stale_body and plain_len >= 500 and has_table

        if not body_ok:
            new_desc = build_description(item, force=True, gsc_keywords=gsc_keywords)
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
            matching_var = next((v for v in item.get('variants', []) if v.get('image_id') == img.get('id')), None)
            if matching_var and matching_var.get('option1') and matching_var.get('option1').lower() not in ('default title', 'default', ''):
                hint = matching_var.get('option1')
            else:
                hint = colors[i] if i < len(colors) else ''
            expected_alt = build_alt(title, hint, i, ptype, tags, gsc_keywords=gsc_keywords)
            cur_alt = img.get('alt', '') or ''
            if cur_alt != expected_alt:
                mismatches.append({
                    "field": f"img_alt[{i}]",
                    "before": cur_alt,
                    "after": expected_alt,
                    "_img_id": img['id'],
                    "_img_idx": i
                })

        # Handle validation: ensure no blocked supplier names in URL handles
        cur_handle = item.get('handle', '')
        if any(re.search(pat, cur_handle, re.IGNORECASE) for pat in BLOCKED_HANDLE_PATTERNS):
            mismatches.append({
                "field": "handle",
                "before": cur_handle,
                "after": slugify(title)
            })

    return mismatches


# ══════════════════════════════════════════════════════════════════════════════
# CORE PRODUCT PROCESSOR
# ══════════════════════════════════════════════════════════════════════════════

def process(product, stats, log, existing_mfs=None, force=False, only_images=False, dry_run=False):
    pid        = product['id']
    old_title  = product['title']
    old_handle = product['handle']
    changes    = []
    missing    = []

    gsc_kw = fetch_gsc_keywords(f"{SITE}/products/{old_handle}")
    if gsc_kw:
        print(f"  [GSC] Found queries to integrate: {gsc_kw}")
    else:
        print(f"  [GSC] No queries found for handle '{old_handle}' in position 8-20 with CTR < 5%")

    prod_updates = {}
    if gsc_kw and not only_images:
        existing_tags = [t.strip() for t in product.get('tags', '').split(',') if t.strip()]
        new_tags = list(dict.fromkeys(existing_tags + [kw.title() for kw in gsc_kw]))
        new_tags_str = ', '.join(new_tags)
        if new_tags_str != product.get('tags', ''):
            prod_updates['tags'] = new_tags_str
            changes.append({"field": "tags", "before": product.get('tags', ''), "after": new_tags_str})
            print(f"  + Added keywords to product tags: {gsc_kw}")
    if not only_images:
        # ── 1. Title Standardization & SEO Formula ──────────────────────────────
        new_title = standardize_product_title(old_title, product.get('vendor', ''), product.get('product_type', ''))
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

        # Allow custom descriptions to bypass complete overwrite, only rewriting if force or missing table/stale return
        is_custom = len(strip_html(body_html)) >= 200 and not ("Discover the" in body_html and "Why Choose" in body_html)
        
        # Stop unnecessary body rewrites on existing products to avoid spam signals.
        # Only rewrite if explicitly forced, or if the product has basically no description.
        needs_body_rewrite = force or plain_len < 50

        if needs_body_rewrite:
            missing.append(f"body_html ({plain_len} chars, table={has_table}, stale={has_stale_body}, markers={has_all_markers}, custom={is_custom})")
            new_body = build_description(product, force=True, gsc_keywords=gsc_kw)
            prod_updates['body_html'] = new_body
            stats['descriptions'] += 1
            changes.append({
                "field": "body_html",
                "before": f"{plain_len} chars",
                "after": f"{len(strip_html(new_body))} chars + table"
            })
            if gsc_kw:
                print(f"  + Injected GSC keywords (bolded in description): {gsc_kw}")

        # ── 3. URL handle + redirect ──────────────────────────────────────────────
        final_title  = prod_updates.get('title', old_title)
        ideal_handle = slugify(final_title)
        has_blocked_handle = any(re.search(pat, old_handle, re.IGNORECASE) for pat in BLOCKED_HANDLE_PATTERNS)
        if ideal_handle and (ideal_handle != old_handle or has_blocked_handle) and len(ideal_handle) > 4:
            missing.append(f"handle (was '{old_handle}')")
            prod_updates['handle'] = ideal_handle
            if dry_run:
                print(f"    [DRY-RUN] Would create redirect: '{old_handle}' -> '{ideal_handle}'")
                stats['redirects'] += 1
            else:
                if create_redirect(old_handle, ideal_handle):
                    stats['redirects'] += 1
            stats['handles'] += 1
            changes.append({"field": "handle", "before": old_handle, "after": ideal_handle})

    # Apply product updates
    if prod_updates:
        if dry_run:
            print(f"    [DRY-RUN] Would update product JSON: {prod_updates}")
            stats['products'] += 1
        else:
            try:
                api_put(f"/products/{pid}.json", {"product": prod_updates})
                stats['products'] += 1
            except Exception as e:
                print(f"    ! Update failed: {e}")
                return

    # ── 4. Fetch metafields if not provided ───────────────────────────────────
    if existing_mfs is None:
        existing_mfs = {}

    # ── 5. Strict validation + fix ────────────────────────────────────────────
    display_title = prod_updates.get('title', old_title)
    product_with_new_title = {**product, 'title': display_title}
    mismatches = validate_seo(product_with_new_title, "product", existing_mfs, gsc_keywords=gsc_kw)

    meta_fix_needed = False
    new_meta_title = build_meta_title(display_title, product.get('product_type', ''), product.get('tags', ''))
    new_meta_desc = build_meta_desc(display_title, product.get('product_type', ''), product.get('tags', ''), gsc_keywords=gsc_kw)

    for m in mismatches:
        if m['field'] == 'meta_title':
            if not only_images:
                missing.append("meta_title mismatch")
                meta_fix_needed = True
                stats['meta_titles'] += 1
                changes.append({"field": "meta_title", "before": m['before'], "after": m['after']})
        elif m['field'] == 'meta_desc':
            if not only_images:
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
            img_src = next((img['src'] for img in product.get('images', []) if img.get('id') == iid), None)
            if dry_run:
                print(f"    [DRY-RUN] Would update image alt/filename for {iid}: alt='{m['after']}'")
                stats['alts'] += 1
                changes.append({"field": f"img_alt[{i}]", "before": m['before'][:50], "after": m['after'][:50]})
            else:
                if update_image_alt(pid, iid, m['after'], img_src, idx=i):
                    stats['alts'] += 1
                    changes.append({"field": f"img_alt[{i}]", "before": m['before'][:50], "after": m['after'][:50]})

    # In force mode, always rewrite both meta fields even if they already pass validation
    if force and not only_images and not meta_fix_needed:
        cur_mt = existing_mfs.get('global.title_tag', {}).get('value', '')
        cur_md = existing_mfs.get('global.description_tag', {}).get('value', '')
        if cur_mt != new_meta_title or cur_md != new_meta_desc:
            meta_fix_needed = True
            stats['meta_titles'] += 1
            stats['meta_descs'] += 1
            changes.append({"field": "meta_title", "before": cur_mt, "after": new_meta_title})
            changes.append({"field": "meta_desc", "before": cur_md[:80], "after": new_meta_desc[:80]})

    # Fix meta fields if needed
    if not only_images:
        if meta_fix_needed:
            if dry_run:
                print(f"    [DRY-RUN] Would set SEO metafields: title='{new_meta_title}', desc='{new_meta_desc}'")
            else:
                try:
                    set_seo_metafields("products", pid, new_meta_title, new_meta_desc, existing_mfs)
                except Exception as e:
                    print(f"    ! Meta update error: {e}")
        elif any(m['field'] == 'meta_desc' for m in mismatches):
            if dry_run:
                print(f"    [DRY-RUN] Would set SEO metafields: title='{new_meta_title}', desc='{new_meta_desc}'")
            else:
                try:
                    set_seo_metafields("products", pid, new_meta_title, new_meta_desc)
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
        
        # Trigger Google Indexing API crawl
        final_handle = prod_updates.get('handle', old_handle)
        if dry_run:
            print(f"  [DRY-RUN] Would trigger indexing for {SITE}/products/{final_handle}")
        else:
            trigger_google_indexing(f"{SITE}/products/{final_handle}")

# ══════════════════════════════════════════════════════════════════════════════
# LOG HELPERS FOR SKIP HISTORY
# ══════════════════════════════════════════════════════════════════════════════

def load_recently_updated_ids(filepath: str = "seo_update_log.json") -> set:
    """
    Return a set of resource IDs (integers) that were successfully processed/updated.
    Searches recursively for all seo_update_log.json files in the workspace.
    """
    from pathlib import Path
    log_files = []
    if os.path.exists(filepath):
        log_files.append(Path(filepath))

    for p in Path(".").glob("**/seo_update_log.json"):
        if p.resolve() not in [lf.resolve() for lf in log_files]:
            log_files.append(p)

    processed_ids = set()
    for lf in log_files:
        try:
            logs = json.loads(lf.read_text(encoding="utf-8"))
            if not isinstance(logs, list):
                continue
            for entry in logs:
                if not isinstance(entry, dict):
                    continue
                ids = entry.get("processed_ids", [])
                for item_id in ids:
                    processed_ids.add(int(item_id))
        except Exception:
            pass
    return processed_ids


def save_update_log(processed_ids: set, stats: dict, mode: str, args, filepath: str = "seo_update_log.json"):
    from pathlib import Path
    log_path = Path(filepath)
    logs = []
    if log_path.exists():
        try:
            logs = json.loads(log_path.read_text(encoding="utf-8"))
        except Exception:
            logs = []

    existing_timestamps = {entry.get("timestamp") for entry in logs if isinstance(entry, dict)}

    # Merge logs from other files
    for p in Path(".").glob("**/seo_update_log.json"):
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
        except Exception:
            pass

    logs.sort(key=lambda entry: entry.get("timestamp") or "")

    logs.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "batch_index": args.batch_index if mode == 'force' else None,
        "batch_size": args.batch_size if mode == 'force' else None,
        "summary": stats,
        "processed_ids": sorted(list(processed_ids))
    })

    log_path.write_text(json.dumps(logs, indent=2), encoding="utf-8")
    print(f"[Log] Saved consolidated log to {filepath}")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(description='SEO automation: daily/weekly/force modes')
    ap.add_argument('--daily',       action='store_true', help='Daily mode: last 24hrs (default)')
    ap.add_argument('--weekly',      action='store_true', help='Weekly mode: last 7 days, skip recent')
    ap.add_argument('--force',       action='store_true', help='Force mode: entire catalog, normalize all')
    ap.add_argument('--hours',       type=int, default=0,  help='Custom lookback (overrides mode)')
    ap.add_argument('--limit',       type=int, default=0,  help='Max products (0=all, non-force only)')
    ap.add_argument('--batch-size',  type=int, default=0,  help='For force mode: products per batch job (0=no batching)')
    ap.add_argument('--batch-index', type=int, default=0,  help='For force mode: which batch to process (0-based)')
    ap.add_argument('--resource',    type=str, default='all', choices=['all', 'products', 'collections', 'pages', 'blogs'], help='Resource type to validate/optimize')
    ap.add_argument('--skip-jsonld', action='store_true', help='Skip JSON-LD injection')
    ap.add_argument('--only-images', action='store_true', help='Only update image ALTs and filenames, skip descriptions/meta/handles')
    ap.add_argument('--handle',      type=str, default=None, help='Filter by a specific handle (product or blog handle)')
    ap.add_argument('--dry-run',     action='store_true', help='Dry-run mode: do not write to Shopify or Google Indexing APIs')
    args = ap.parse_args()

    print("=== MeeeShop SEO Automation v2.0 ===\n")

    # ── Determine mode ────────────────────────────────────────────────────────
    if args.force:
        mode = 'force'
        since = None
        print("Mode: FORCE (entire catalog, normalize all SEO fields)")
        if args.batch_size > 0:
            print(f"Batch: index={args.batch_index}, size={args.batch_size} (resource={args.resource})")
        print(f"Processing: {args.resource.capitalize()}\n")
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
        since = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime('%Y-%m-%dT%H:%M:%SZ')
        print("Mode: DAILY (products, pages, collections created + articles published in last 24h)")
        print("Processing: Products, Pages, Collections, Blog Posts\n")

    print(f"Cutoff: {since or 'none (all resources)'}\n")

    # ── Load recently processed/updated GIDs to skip ──────────────────────────
    skip_ids = set()
    if not args.force:
        try:
            skip_ids = load_recently_updated_ids()
            if skip_ids:
                print(f"[Skip] {len(skip_ids)} item(s) already processed in previous runs — will skip\n")
        except Exception as e:
            print(f"Warning: Failed to load skip history: {e}")

    # Track successfully processed/validated IDs in this run
    processed_ids = set()

    # ── JSON-LD theme injection (idempotent) ──────────────────────────────────
    if not args.skip_jsonld:
        print("Injecting JSON-LD structured data...")
        tid = get_live_theme_id()
        if tid:
            inject_jsonld(tid)
        else:
            print("  ! Could not find live theme")
        print()

    # Calculate lookback hours for GraphQL
    hours = 0
    if args.handle:
        hours = 0
        args.force = True
        print(f"[Handle Override] Specific handle '{args.handle}' requested — bypassing creation cutoff and recent skip locks.\n")
    elif args.hours:
        hours = args.hours
    elif mode == 'daily':
        hours = 24
    elif mode == 'weekly':
        hours = 168

    products = []
    if args.resource in ('all', 'products'):
        print("Fetching products...")
        from shopify_graphql import fetch_products_graphql
        products = fetch_products_graphql(hours, query_by_updated=False, handle=args.handle)
        if args.handle:
            products = [p for p in products if p.get('handle') == args.handle]
        else:
            total_fetched = len(products)
            if mode == 'force' and args.batch_size > 0:
                start = args.batch_index * args.batch_size
                end   = start + args.batch_size
                products = products[start:end]
                print(f"  Fetched {total_fetched} products total; processing batch {args.batch_index} [{start}:{end}] = {len(products)} products")
            elif args.limit:
                products = products[:args.limit]
        print(f"  Found {len(products)} products\n")

    pages = []
    if args.resource in ('all', 'pages') and not args.only_images:
        print("Fetching pages...")
        from shopify_graphql import fetch_pages_graphql
        pages = fetch_pages_graphql(hours, handle=args.handle)
        if args.handle:
            pages = [p for p in pages if p.get('handle') == args.handle]
        print(f"  Found {len(pages)} pages\n")

    collections = []
    if args.resource in ('all', 'collections'):
        print("Fetching collections...")
        from shopify_graphql import fetch_collections_graphql
        collections = fetch_collections_graphql(hours, handle=args.handle)
        if args.handle:
            collections = [c for c in collections if c.get('handle') == args.handle]
        print(f"  Found {len(collections)} collections\n")

    articles = []
    if args.resource in ('all', 'blogs'):
        print("Fetching articles...")
        from shopify_graphql import fetch_articles_graphql
        articles = fetch_articles_graphql(hours)
        if args.handle:
            articles = [a for a in articles if a.get('handle') == args.handle]
        print(f"  Found {len(articles)} articles\n")

    # Filter by handle message if specified
    if args.handle:
        print(f"Filtered by handle '{args.handle}': {len(products)} products, {len(pages)} pages, {len(collections)} collections, {len(articles)} articles remaining.")

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
        if p['id'] in skip_ids:
            print(f"  [{i}/{len(products)}] SKIP (recent) {p['title'][:55]}")
            continue

        mfs        = {f"{m['namespace']}.{m['key']}": m for m in p.get('metafields', [])}
        mismatches = validate_seo(p, "product", mfs)
        title_wrong = title_case(p['title']) != p['title']
        if args.only_images:
            needs_seo = any(m['field'].startswith('img_alt') for m in mismatches)
        else:
            needs_seo = bool(mismatches) or title_wrong
        if not needs_seo and mode not in ('force', 'weekly'):
            print(f"  [{i}/{len(products)}] OK  {p['title'][:55]}")
            processed_ids.add(p['id'])
            continue
        print(f"  [{i}/{len(products)}] FIX {p['title'][:55]}")
        process(p, stats, log, existing_mfs=mfs, force=(mode in ('force', 'weekly')), only_images=args.only_images, dry_run=args.dry_run)
        processed_ids.add(p['id'])

    # ── Process pages ─────────────────────────────────────────────────────────
    if pages and not args.only_images:
        print("\nProcessing pages...")
        for i, page in enumerate(pages, 1):
            if page['id'] in skip_ids:
                print(f"  [{i}/{len(pages)}] SKIP (recent) {page['title'][:55]}")
                continue

            title = page['title']
            mfs        = {f"{m['namespace']}.{m['key']}": m for m in page.get('metafields', [])}

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
                and not GoogleQuestionFetcher.has_non_us_location(cur_mdesc)
                and not GoogleQuestionFetcher.has_competitor_retailer(cur_mdesc, allowed_brand=title)
            )
            mt_ok = (cur_mtitle == expected_mt)
            needs_seo = not mt_ok or not desc_ok
            if not needs_seo and mode not in ('force', 'weekly'):
                print(f"  [{i}/{len(pages)}] OK  {title[:55]}")
                processed_ids.add(page['id'])
                continue

            print(f"  [{i}/{len(pages)}] FIX {title[:55]}")
            page_url = f"{SITE}/pages/{page['handle']}"
            gsc_kw = fetch_gsc_keywords(page_url)
            if gsc_kw:
                print(f"  [GSC] Found queries to integrate: {gsc_kw}")
            else:
                print(f"  [GSC] No queries found for page handle '{page['handle']}' in position 8-20 with CTR < 5%")
            kw_suffix = f" {', '.join(gsc_kw)}." if gsc_kw else ""

            new_meta_title = expected_mt
            new_meta_desc = truncate(
                f"{title} - {DISPLAY_BRAND}.{kw_suffix} Premium women's fashion with free US shipping & 7-day returns.",
                155
            )
            if args.dry_run:
                print(f"    [DRY-RUN] Would set page SEO metafields: title='{new_meta_title}', desc='{new_meta_desc}'")
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
                processed_ids.add(page['id'])
            else:
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
                    processed_ids.add(page['id'])
                except Exception as e:
                    print(f"    ! Error processing page: {e}")

    # ── Process collections ───────────────────────────────────────────────────
    if collections:
        print("\nProcessing collections...")
        for i, coll in enumerate(collections, 1):
            if coll['id'] in skip_ids:
                print(f"  [{i}/{len(collections)}] SKIP (recent) {coll['title'][:55]}")
                continue

            title = coll['title']
            coll_type = coll.get('_type', 'custom_collections')
            mfs        = {f"{m['namespace']}.{m['key']}": m for m in coll.get('metafields', [])}

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
                and not GoogleQuestionFetcher.has_non_us_location(cur_mdesc)
                and not GoogleQuestionFetcher.has_competitor_retailer(cur_mdesc, allowed_brand=title)
            )
            mt_ok = (cur_mtitle == expected_mt)

            # Collection image processing
            coll_image = coll.get('image')
            image_ok = True
            expected_img_alt = None
            if coll_image:
                expected_img_alt = build_collection_alt(title)
                cur_img_alt = coll_image.get('altText') or ''
                if cur_img_alt != expected_img_alt:
                    image_ok = False

            if args.only_images:
                needs_seo = not image_ok if coll_image else False
            else:
                needs_seo = not mt_ok or not desc_ok or (not image_ok if coll_image else False)

            if not needs_seo and mode not in ('force', 'weekly'):
                print(f"  [{i}/{len(collections)}] OK  {title[:55]}")
                processed_ids.add(coll['id'])
                continue

            print(f"  [{i}/{len(collections)}] FIX {title[:55]}")
            coll_changes = []

            # Update meta fields if not only_images
            if not args.only_images:
                coll_url = f"{SITE}/collections/{coll['handle']}"
                gsc_kw = fetch_gsc_keywords(coll_url)
                if gsc_kw:
                    print(f"  [GSC] Found queries to integrate: {gsc_kw}")
                else:
                    print(f"  [GSC] No queries found for collection handle '{coll['handle']}' in position 8-20 with CTR < 5%")
                kw_suffix = f" {', '.join(gsc_kw)}." if gsc_kw else ""

                new_meta_title = expected_mt
                new_meta_desc = truncate(
                    f"Shop {title} at {DISPLAY_BRAND}.{kw_suffix} Premium women's fashion with free US shipping & 7-day returns.",
                    155
                )
                if args.dry_run:
                    print(f"    [DRY-RUN] Would set collection SEO metafields: title='{new_meta_title}', desc='{new_meta_desc}'")
                    stats['meta_titles'] += 1
                    stats['meta_descs'] += 1
                    stats['collections'] += 1
                    coll_changes.extend([
                        {"field": "meta_title", "before": cur_mtitle, "after": new_meta_title},
                        {"field": "meta_desc", "before": cur_mdesc[:60], "after": new_meta_desc[:60]}
                    ])
                else:
                    try:
                        # 1. Update native collection.seo fields
                        q_update_coll_seo = """
                        mutation collectionUpdate($input: CollectionInput!) {
                          collectionUpdate(input: $input) {
                            collection { id }
                            userErrors { field message }
                          }
                        }
                        """
                        var_coll_seo = {
                            "input": {
                                "id": f"gid://shopify/Collection/{coll['id']}",
                                "seo": {
                                    "title": new_meta_title,
                                    "description": new_meta_desc
                                }
                            }
                        }
                        run_graphql(q_update_coll_seo, var_coll_seo)

                        # 2. Update global.title_tag and global.description_tag metafields
                        set_seo_metafields(coll_type, coll['id'], new_meta_title, new_meta_desc, mfs)
                        stats['meta_titles'] += 1
                        stats['meta_descs'] += 1
                        stats['collections'] += 1
                        coll_changes.extend([
                            {"field": "meta_title", "before": cur_mtitle, "after": new_meta_title},
                            {"field": "meta_desc", "before": cur_mdesc[:60], "after": new_meta_desc[:60]}
                        ])
                    except Exception as e:
                        print(f"    ! Error processing collection metafields: {e}")

            # Update collection image alt and filename
            if coll_image and (not image_ok or mode in ('force', 'weekly')):
                if args.dry_run:
                    print(f"    [DRY-RUN] Would update collection image alt for {coll['id']}: alt='{expected_img_alt}'")
                    stats['alts'] += 1
                    coll_changes.append({"field": "image_alt", "before": coll_image.get('altText') or '', "after": expected_img_alt})
                else:
                    try:
                        # 1. Update Alt text via collectionUpdate mutation
                        q_update_coll = """
                        mutation collectionUpdate($input: CollectionInput!) {
                          collectionUpdate(input: $input) {
                            collection { id }
                            userErrors { field message }
                          }
                        }
                        """
                        variables = {
                            "input": {
                                "id": f"gid://shopify/Collection/{coll['id']}",
                                "image": {
                                  "altText": expected_img_alt
                                }
                            }
                        }
                        res = run_graphql(q_update_coll, variables)
                        errs = res.get("data", {}).get("collectionUpdate", {}).get("userErrors", [])
                        if errs:
                            print(f"    ! Error updating collection image alt: {errs}")
                        else:
                            stats['alts'] += 1
                            coll_changes.append({"field": "image_alt", "before": coll_image.get('altText') or '', "after": expected_img_alt})
                            print(f"  + image_alt: '{coll_image.get('altText') or ''}' -> '{expected_img_alt}'")

                        # 2. Try to rename image filename if possible
                        src = coll_image.get('url')
                        if src:
                            clean_url = src.split('?')[0]
                            base = clean_url.split('/')[-1]
                            if '.' in base:
                                ext = base.rsplit('.', 1)[1].lower()
                                slug = slugify(expected_img_alt)
                                img_id = parse_gid(coll_image.get('id'))
                                media_suffix = str(img_id)[-6:] if img_id else str(int(time.time() * 1000))[-6:]
                                new_filename = f"{slug[:50].strip('-')}-{media_suffix}.{ext}"
                                if base.lower() != new_filename.lower():
                                    # Search standard files to find GenericFile/MediaImage ID
                                    file_id = find_file_id_by_filename(base)
                                    if file_id:
                                        if rename_shopify_file(file_id, new_filename):
                                            print(f"  + Filename updated: '{base}' -> '{new_filename}'")
                                    else:
                                        print(f"  (Note: collection image '{base}' not found in standard files for renaming)")
                    except Exception as e:
                        print(f"    ! Error updating collection image: {e}")

            if coll_changes:
                log.append({
                    'type': 'collection',
                    'title': title,
                    'url': f"{SITE}/collections/{coll['handle']}",
                    'fixed': coll_changes
                })
            processed_ids.add(coll['id'])

    # ── Process articles ──────────────────────────────────────────────────────
    if articles:
        print("\nProcessing articles...")
        for i, article in enumerate(articles, 1):
            if article['id'] in skip_ids:
                print(f"  [{i}/{len(articles)}] SKIP (recent) {article['title'][:55]}")
                continue

            title = article['title']
            blog_id = article.get('blog_id')
            blog_handle = article.get('blog_handle')
            art_id  = article['id']

            if not blog_id or not blog_handle:
                print(f"  [{i}/{len(articles)}] SKIP {title[:55]} (no blog_id or blog_handle)")
                continue

            mfs        = {f"{m['namespace']}.{m['key']}": m for m in article.get('metafields', [])}

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

            # Article image processing
            art_image = article.get('image')
            image_ok = True
            expected_img_alt = None
            if art_image:
                expected_img_alt = build_article_alt(title)
                cur_img_alt = art_image.get('altText') or ''
                if cur_img_alt != expected_img_alt:
                    image_ok = False

            if args.only_images:
                needs_seo = not image_ok if art_image else False
            else:
                needs_seo = not mt_ok or not desc_ok or (not image_ok if art_image else False)

            if not needs_seo and mode not in ('force', 'weekly'):
                print(f"  [{i}/{len(articles)}] OK  {title[:55]}")
                processed_ids.add(article['id'])
                continue

            print(f"  [{i}/{len(articles)}] FIX {title[:55]}")
            art_changes = []

            # Update meta fields if not only_images
            if not args.only_images:
                new_meta_title = expected_mt
                article_url = f"{SITE}/blogs/{blog_handle}/{article['handle']}"
                gsc_kw = fetch_gsc_keywords(article_url)
                if gsc_kw:
                    print(f"  [GSC] Found queries to integrate: {gsc_kw}")
                else:
                    print(f"  [GSC] No queries found for article handle '{article['handle']}' in position 8-20 with CTR < 5%")
                kw_suffix = f" {', '.join(gsc_kw)}." if gsc_kw else ""
                new_meta_desc = truncate(
                    f"{title} - {DISPLAY_BRAND} Blog.{kw_suffix} Women's fashion tips & styling guides with free shipping & 7-day returns.",
                    155
                )
                if args.dry_run:
                    print(f"    [DRY-RUN] Would set article SEO metafields: title='{new_meta_title}', desc='{new_meta_desc}'")
                    stats['meta_titles'] += 1
                    stats['meta_descs'] += 1
                    stats['articles'] += 1
                    art_changes.extend([
                        {"field": "meta_title", "before": cur_mtitle, "after": new_meta_title},
                        {"field": "meta_desc", "before": cur_mdesc[:60], "after": new_meta_desc[:60]}
                    ])
                else:
                    try:
                        set_seo_metafields(f"blogs/{blog_id}/articles", art_id, new_meta_title, new_meta_desc, mfs)
                        stats['meta_titles'] += 1
                        stats['meta_descs'] += 1
                        stats['articles'] += 1
                        art_changes.extend([
                            {"field": "meta_title", "before": cur_mtitle, "after": new_meta_title},
                            {"field": "meta_desc", "before": cur_mdesc[:60], "after": new_meta_desc[:60]}
                        ])
                    except Exception as e:
                        print(f"    ! Error processing article metafields: {e}")

            # Update article image alt and filename
            if art_image and (not image_ok or mode in ('force', 'weekly')):
                if args.dry_run:
                    print(f"    [DRY-RUN] Would update article image alt for {art_id}: alt='{expected_img_alt}'")
                    stats['alts'] += 1
                    art_changes.append({"field": "image_alt", "before": art_image.get('altText') or '', "after": expected_img_alt})
                else:
                    try:
                        # 1. Update Alt text via articleUpdate mutation
                        q_update_art = """
                        mutation articleUpdate($id: ID!, $article: ArticleUpdateInput!) {
                          articleUpdate(id: $id, article: $article) {
                            article { id }
                            userErrors { field message }
                          }
                        }
                        """
                        variables = {
                            "id": f"gid://shopify/Article/{art_id}",
                            "article": {
                                "image": {
                                    "altText": expected_img_alt
                                }
                            }
                        }
                        res = run_graphql(q_update_art, variables)
                        errs = res.get("data", {}).get("articleUpdate", {}).get("userErrors", [])
                        if errs:
                            print(f"    ! Error updating article image alt: {errs}")
                        else:
                            stats['alts'] += 1
                            art_changes.append({"field": "image_alt", "before": art_image.get('altText') or '', "after": expected_img_alt})
                            print(f"  + image_alt: '{art_image.get('altText') or ''}' -> '{expected_img_alt}'")

                        # 2. Try to rename image filename if possible
                        src = art_image.get('src')
                        if src:
                            clean_url = src.split('?')[0]
                            base = clean_url.split('/')[-1]
                            if '.' in base:
                                ext = base.rsplit('.', 1)[1].lower()
                                slug = slugify(expected_img_alt)
                                img_id = parse_gid(art_image.get('id'))
                                media_suffix = str(img_id)[-6:] if img_id else str(int(time.time() * 1000))[-6:]
                                new_filename = f"{slug[:50].strip('-')}-{media_suffix}.{ext}"
                                if base.lower() != new_filename.lower():
                                    # Search standard files to find GenericFile/MediaImage ID
                                    file_id = find_file_id_by_filename(base)
                                    if file_id:
                                        if rename_shopify_file(file_id, new_filename):
                                            print(f"  + Filename updated: '{base}' -> '{new_filename}'")
                                    else:
                                        print(f"  (Note: article image '{base}' not found in standard files for renaming)")
                    except Exception as e:
                        print(f"    ! Error updating article image: {e}")

            if art_changes:
                log.append({
                    'type': 'article',
                    'title': title,
                    'url': f"{SITE}/blogs/{blog_handle}/{article['handle']}",
                    'fixed': art_changes
                })
                # Trigger Google Indexing API crawl
                if args.dry_run:
                    print(f"  [DRY-RUN] Would trigger indexing for {SITE}/blogs/{blog_handle}/{article['handle']}")
                else:
                    trigger_google_indexing(f"{SITE}/blogs/{blog_handle}/{article['handle']}")
            processed_ids.add(article['id'])

    # ── Report ────────────────────────────────────────────────────────────────
    print("\n" + "-"*60)
    print("SEO Automation Report")
    print("-"*60)
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
    print("-"*60)

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
    resource_suffix = f"_{args.resource}" if args.resource != "all" else ""
    fname = f"seo_report_{datetime.now().strftime('%Y%m%d_%H%M')}{resource_suffix}{batch_suffix}.json"
    with open(fname, 'w') as f:
        json.dump(report, f, indent=2)
    print(f"\nFull report saved: {fname}")

    # Save processed GIDs log
    if not args.force:
        try:
            save_update_log(processed_ids, stats, mode, args)
        except Exception as e:
            print(f"Warning: Failed to save skip history: {e}")



if __name__ == "__main__":
    main()

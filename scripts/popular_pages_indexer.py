#!/usr/bin/env python3
"""
popular_pages_indexer.py — Re-index popular/trending pages from Google Search Console
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Queries the Google Search Console API to find the top viewed/clicked URLs on
us.meeeshop.com in search results over the last 14 days, and automatically
submits them to Google Indexing API and IndexNow to prioritize crawls and keep
rankings fresh.
"""

import os
import sys
import json
import time
import urllib.parse
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── path setup ────────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from secrets_manager import inject_to_env, get_secret
from article_deduplicator import ArticleDeduplicator
from utils import get_category_style_phrase

inject_to_env()

# Configure stdout and stderr to handle UTF-8 output properly on Windows
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')

# ── credentials ───────────────────────────────────────────────────────────────
SHOP      = get_secret("SHOPIFY_STORE")
STORE_URL = get_secret("STORE_BASE_URL").rstrip("/")

# ── Google OAuth / API constants ──────────────────────────────────────────────
OAUTH_ENDPOINT = "https://oauth2.googleapis.com/token"
GSC_SCOPE      = "https://www.googleapis.com/auth/webmasters.readonly"
INDEXING_SCOPE = "https://www.googleapis.com/auth/indexing"
INDEXING_ENDPOINT = "https://indexing.googleapis.com/v3/urlNotifications:publish"

# ── IndexNow Constants ────────────────────────────────────────────────────────
INDEXNOW_KEY = "c5def3bf8d13211be2bacf8d13211be2"
KEY_FILE_NAME = f"{INDEXNOW_KEY}.txt"

# ── Google OAuth2 Helper ──────────────────────────────────────────────────────
def get_oauth_token(sa_key: dict, scope: str) -> str:
    try:
        import base64
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.backends import default_backend
    except ImportError:
        sys.exit("ERROR: 'cryptography' package missing — run: pip install cryptography")

    now     = int(time.time())
    header  = {"alg": "RS256", "typ": "JWT"}
    payload = {"iss": sa_key["client_email"], "scope": scope,
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

# ── Fetch GSC Analytics (Pages & Queries) ────────────────────────────────────
def fetch_gsc_analytics(sa_key: dict, days: int = 14, page_limit: int = 50, query_limit: int = 50) -> tuple[list[dict], list[dict]]:
    print(f"Fetching search analytics over the last {days} days from Google Search Console...")
    pages = []
    queries = []
    try:
        token = get_oauth_token(sa_key, GSC_SCOPE)
        
        # Query GSC verified sites list to find the matching property
        list_url = "https://www.googleapis.com/webmasters/v3/sites"
        list_resp = requests.get(list_url, headers={"Authorization": f"Bearer {token}"}, timeout=15)
        list_resp.raise_for_status()
        sites = list_resp.json().get("siteEntry", [])
        
        store_domain = urllib.parse.urlparse(STORE_URL).netloc.lower()
        site_url = None
        for site in sites:
            candidate = site.get("siteUrl", "")
            if store_domain in candidate.lower():
                site_url = candidate
                break
                
        if not site_url:
            site_url = STORE_URL + "/"
            
        encoded_site = urllib.parse.quote_plus(site_url)
        query_url = f"https://www.googleapis.com/webmasters/v3/sites/{encoded_site}/searchAnalytics/query"
        
        end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        start_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
        
        # 1. Query Top Pages
        page_payload = {
            "startDate": start_date,
            "endDate": end_date,
            "dimensions": ["page"],
            "rowLimit": page_limit
        }
        resp_pages = requests.post(
            query_url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=page_payload,
            timeout=20
        )
        if resp_pages.status_code == 200:
            for row in resp_pages.json().get("rows", []):
                pages.append({
                    "url": row.get("keys", [""])[0],
                    "clicks": int(row.get("clicks", 0)),
                    "impressions": int(row.get("impressions", 0)),
                    "ctr": float(row.get("ctr", 0)),
                    "position": float(row.get("position", 0))
                })

        # 2. Query Top Queries
        query_payload = {
            "startDate": start_date,
            "endDate": end_date,
            "dimensions": ["query"],
            "rowLimit": query_limit
        }
        resp_queries = requests.post(
            query_url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=query_payload,
            timeout=20
        )
        if resp_queries.status_code == 200:
            for row in resp_queries.json().get("rows", []):
                queries.append({
                    "query": row.get("keys", [""])[0],
                    "clicks": int(row.get("clicks", 0)),
                    "impressions": int(row.get("impressions", 0)),
                    "ctr": float(row.get("ctr", 0)),
                    "position": float(row.get("position", 0))
                })

    except Exception as e:
        print(f"[ERROR] Failed to fetch search analytics data from GSC: {e}")

    # Display Top Queries in exact requested log format
    print("\n" + "=" * 70)
    print(f"  TOP {len(queries)} GOOGLE SEARCH CONSOLE QUERIES (Clicks | Impressions)")
    print("=" * 70)
    for q in queries:
        print(f"  {q['query']:<45} \t{q['clicks']}\t{q['impressions']}")
    print("=" * 70 + "\n")

    return pages, queries

# ── Search Storefront Resources for Queries ──────────────────────────────────
def search_store_resources(queries: list[dict]) -> set[str]:
    """
    Looks up products, collections, pages, and blog articles matching the top GSC search queries.
    Returns a set of full store URLs to re-index.
    """
    print("Searching store for products, pages, and articles matching top search queries...")
    matched_urls = set()
    TOKEN = get_secret("SHOPIFY_ACCESS_TOKEN")
    if not TOKEN:
        print("[WARNING] SHOPIFY_ACCESS_TOKEN missing, skipping resource lookup.")
        return matched_urls

    headers = {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}
    admin_base = f"https://{SHOP}/admin/api/2024-10"

    for item in queries:
        q = item["query"].strip()
        if len(q) < 3:
            continue
        try:
            # Query Shopify REST Search API or GraphQL for products/pages/blogs matching keyword
            search_endpoint = f"{admin_base}/products.json?title={urllib.parse.quote(q)}&limit=5"
            r = requests.get(search_endpoint, headers=headers, timeout=10)
            if r.status_code == 200:
                products = r.json().get("products", [])
                for p in products:
                    handle = p.get("handle")
                    if handle:
                        matched_urls.add(f"{STORE_URL}/products/{handle}")

            # Also query articles
            article_endpoint = f"{admin_base}/articles.json?limit=10"
            ra = requests.get(article_endpoint, headers=headers, timeout=10)
            if ra.status_code == 200:
                articles = ra.json().get("articles", [])
                q_words = set(q.lower().split())
                for art in articles:
                    title = art.get("title", "").lower()
                    if any(w in title for w in q_words if len(w) > 3):
                        handle = art.get("handle")
                        if handle:
                            matched_urls.add(f"{STORE_URL}/blogs/news/{handle}")
        except Exception as e:
            print(f"  [!] Error searching store resources for '{q}': {e}")

    print(f"Discovered {len(matched_urls)} matching store resource URLs from search query lookup.")
    return matched_urls

# ── Identify Long-Tail Question Queries for Blog Creation ──────────────────────
def identify_longtail_question_queries(queries: list[dict]) -> list[dict]:
    """
    Filters search queries that indicate question intent (what, how, why, style, outfit, flattering, etc.)
    or high impressions opportunities, strictly EXCLUDING size chart/sizing queries.
    """
    question_triggers = [
        "what", "how", "why", "outfit", "style", "wear", "best",
        "versus", "vs", "flattering", "types", "guide", "look", "combination"
    ]
    candidates = []
    for q in queries:
        q_text = q["query"].lower().strip()
        
        # Explicitly exclude size chart and sizing queries
        if "size chart" in q_text or "sizing" in q_text or "size" in q_text:
            continue

        # Trigger if contains question/style triggers or high impressions (>= 15) with 0/low clicks
        if any(w in q_text for w in question_triggers) or (q["impressions"] >= 15 and q["clicks"] == 0):
            candidates.append(q)

    # Sort candidates by impressions & clicks
    candidates.sort(key=lambda x: (x["clicks"], x["impressions"]), reverse=True)
    return candidates

# ── Generate Blog Articles from Long-Tail Queries ─────────────────────────────
def generate_blogs_from_longtail(queries: list[dict], max_blogs: int = 1, dry_run: bool = False) -> list[str]:
    new_blog_urls = []
    if not queries or max_blogs <= 0:
        return new_blog_urls

    print(f"\nFound {len(queries)} potential long-tail question/trend queries for blog creation.")
    selected = queries[:max_blogs]

    # Initialize deduplication engine against live store
    TOKEN = get_secret("SHOPIFY_ACCESS_TOKEN")
    admin_base = f"https://{SHOP}/admin/api/2024-10"
    headers = {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}
    dedup = ArticleDeduplicator(admin_base, headers)
    dedup.load_live_index()

    for i, item in enumerate(selected, 1):
        q = item["query"]
        category_topic = get_category_style_phrase({"title": q, "product_type": q})
        print(f"\n[{i}/{len(selected)}] Preparing blog post for long-tail query: '{q}' → category topic: '{category_topic}' (Impressions: {item['impressions']}, Clicks: {item['clicks']})")

        if dedup.is_duplicate_title(q) or dedup.is_duplicate_title(category_topic):
            print(f"  [Dedup] SKIP — Article for search query / topic '{q}' ('{category_topic}') already exists on Shopify.")
            continue

        try:
            import subprocess
            cmd = [
                sys.executable,
                str(Path(__file__).parent / "blog_daily.py"),
                "--count", "1",
                "--topic", category_topic,
            ]
            if dry_run:
                cmd.append("--dry-run")
            else:
                cmd.append("--publish")

            print(f"  Executing blog_daily workflow command: {' '.join(cmd)}")
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            print(res.stdout)
            if res.stderr:
                print(f"[LOG] {res.stderr}")

            if res.returncode == 0:
                mode_str = "dry-run preview" if dry_run else "published live"
                print(f"  ✓ Blog article creation ({mode_str}) completed for topic '{category_topic}'!")
        except Exception as e:
            print(f"  [ERROR] Failed to run blog generation for query '{q}': {e}")

    return new_blog_urls

# ── Submit to Google Indexing API ────────────────────────────────────────────
def submit_to_google_indexing(urls: list[str], sa_key: dict, dry_run: bool = False):
    if not urls:
        return
    
    print("\nSubmitting trending & matched URLs to Google Indexing API...")
    if dry_run:
        print("[DRY-RUN] Skipping API calls for Google Indexing.")
        return
        
    try:
        token = get_oauth_token(sa_key, INDEXING_SCOPE)
        for i, url in enumerate(urls, 1):
            try:
                resp = requests.post(
                    INDEXING_ENDPOINT,
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    json={"url": url, "type": "URL_UPDATED"},
                    timeout=15
                )
                if resp.status_code == 200:
                    print(f"  [{i:>3}/{len(urls)}] [OK] Google Indexing: {url}")
                elif resp.status_code == 429:
                    print(f"  [{i:>3}/{len(urls)}] [QUOTA EXCEEDED] Google Indexing: stopping submissions.")
                    break
                else:
                    print(f"  [{i:>3}/{len(urls)}] [ERROR {resp.status_code}] Google Indexing: {resp.text}")
            except Exception as e:
                print(f"  [{i:>3}/{len(urls)}] [ERROR] Google Indexing: {e}")
            time.sleep(0.2)
    except Exception as e:
        print(f"[ERROR] Failed to authenticate for Google Indexing: {e}")

# ── Submit to IndexNow ────────────────────────────────────────────────────────
def submit_to_indexnow(urls: list[str], dry_run: bool = False):
    if not urls:
        return
        
    print("\nSubmitting trending & matched URLs to IndexNow...")
    domain = urllib.parse.urlparse(STORE_URL).netloc
    key_location = f"{STORE_URL}/{KEY_FILE_NAME}"
    
    payload = {
        "host": domain,
        "key": INDEXNOW_KEY,
        "keyLocation": key_location,
        "urlList": urls
    }
    
    if dry_run:
        print("[DRY-RUN] IndexNow payload prepared, skipping API call.")
        return
        
    endpoint = "https://api.indexnow.org/indexnow"
    try:
        resp = requests.post(endpoint, json=payload, headers={"Content-Type": "application/json; charset=utf-8"}, timeout=15)
        if resp.status_code in (200, 202):
            print(f"[OK] IndexNow submission successful (HTTP {resp.status_code})!")
        else:
            print(f"[WARNING] IndexNow submission failed with HTTP status {resp.status_code}: {resp.text}")
    except Exception as e:
        print(f"[ERROR] Connection error during IndexNow submission: {e}")

# ── Main Execution ───────────────────────────────────────────────────────────
def main():
    import argparse
    parser = argparse.ArgumentParser(description="Re-index popular pages & search queries from Google Search Console")
    parser.add_argument("--dry-run", action="store_true", help="Dry run mode, do not call indexing APIs or publish blogs")
    parser.add_argument("--limit", type=int, default=50, help="Number of popular pages to process (default: 50)")
    parser.add_argument("--query-limit", type=int, default=50, help="Number of top search queries to retrieve and log (default: 50)")
    parser.add_argument("--days", type=int, default=14, help="Search analytics lookback days (default: 14)")
    parser.add_argument("--generate-blogs", action="store_true", help="Generate blog articles for long-tail question queries")
    parser.add_argument("--max-blogs", type=int, default=1, help="Maximum number of blog articles to generate per run (default: 1)")
    args = parser.parse_args()

    print("=" * 70)
    print("  Popular Pages & Search Query Indexer + Blog Automation")
    print("=" * 70)
    
    # Load Google Service Account credentials
    try:
        raw = get_secret("GOOGLE_SA_KEY_JSON")
        sa_key = json.loads(raw)
    except Exception as e:
        print(f"Error loading GOOGLE_SA_KEY_JSON: {e}. Checking local key file...")
        local = Path(__file__).parent.parent / "google_sa_key.json"
        if local.exists():
            sa_key = json.loads(local.read_text(encoding="utf-8"))
        else:
            print("ERROR: Google Service Account key not found. Exiting.")
            sys.exit(1)
            
    # 1. Fetch top pages & search queries from GSC
    gsc_pages, gsc_queries = fetch_gsc_analytics(
        sa_key, days=args.days, page_limit=args.limit, query_limit=args.query_limit
    )
    
    # Collect direct GSC popular page URLs
    gsc_urls = [p["url"] for p in gsc_pages if p["url"].startswith(STORE_URL)]
    print(f"Collected {len(gsc_urls)} direct popular page URLs from Search Console.")

    # 2. Search store for relevant products, pages, and blog articles matching queries
    matched_urls = search_store_resources(gsc_queries)
    
    # 3. Combine all store URLs to re-index
    urls_to_index = sorted(list(set(gsc_urls).union(matched_urls)))
    print(f"\nTotal unique store URLs targeted for re-indexing: {len(urls_to_index)}")

    # 4. Generate long-tail blog posts if requested
    if args.generate_blogs:
        longtail_candidates = identify_longtail_question_queries(gsc_queries)
        generate_blogs_from_longtail(longtail_candidates, max_blogs=args.max_blogs, dry_run=args.dry_run)

    # 5. Submit to Google Indexing API
    submit_to_google_indexing(urls_to_index, sa_key, dry_run=args.dry_run)
    
    # 6. Submit to IndexNow (Bing/Baidu/DuckDuckGo)
    submit_to_indexnow(urls_to_index, dry_run=args.dry_run)
    
    print("\n[OK] Popular Pages & Search Query Indexer run completed successfully!")
    print("=" * 70)

if __name__ == "__main__":
    main()


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

# ── Fetch GSC Top Pages ───────────────────────────────────────────────────────
def fetch_top_gsc_pages(sa_key: dict, days: int = 14, limit: int = 50) -> list[str]:
    print(f"Fetching top pages by impressions/clicks over the last {days} days from Google Search Console...")
    try:
        token = get_oauth_token(sa_key, GSC_SCOPE)
        
        # Query GSC verified sites list to find the matching property (e.g. sc-domain:us.meeeshop.com)
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
        
        payload = {
            "startDate": start_date,
            "endDate": end_date,
            "dimensions": ["page"],
            "rowLimit": limit
        }
        
        resp = requests.post(
            query_url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
            timeout=20
        )
        resp.raise_for_status()
        
        rows = resp.json().get("rows", [])
        urls = []
        print(f"Discovered {len(rows)} popular pages in GSC Search Analytics:")
        for i, row in enumerate(rows, 1):
            page_url = row.get("keys", [None])[0]
            if page_url:
                clicks = row.get("clicks", 0)
                impressions = row.get("impressions", 0)
                print(f"  [{i:>2}] URL: {page_url} (Clicks: {clicks}, Impressions: {impressions})")
                urls.append(page_url)
                
        return urls
    except Exception as e:
        print(f"[ERROR] Failed to fetch search analytics data: {e}")
        return []

# ── Submit to Google Indexing API ────────────────────────────────────────────
def submit_to_google_indexing(urls: list[str], sa_key: dict, dry_run: bool = False):
    if not urls:
        return
    
    print("\nSubmitting trending URLs to Google Indexing API...")
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
        
    print("\nSubmitting trending URLs to IndexNow...")
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
    parser = argparse.ArgumentParser(description="Re-index popular pages from Google Search Console")
    parser.add_argument("--dry-run", action="store_true", help="Dry run mode, do not call indexing APIs")
    parser.add_argument("--limit", type=int, default=30, help="Number of popular pages to process (default: 30)")
    parser.add_argument("--days", type=int, default=14, help="Search analytics lookback days (default: 14)")
    args = parser.parse_args()

    print("=" * 70)
    print("  Popular Pages Indexer & Re-submitter")
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
            
    # 1. Fetch top pages from GSC
    top_urls = fetch_top_gsc_pages(sa_key, days=args.days, limit=args.limit)
    
    if not top_urls:
        print("No trending URLs discovered in Search Console. Exiting.")
        sys.exit(0)
        
    # 2. Filter URLs to only include store pages (discard external/subdomain sites if any)
    store_urls = [u for u in top_urls if u.startswith(STORE_URL)]
    print(f"\nFiltered down to {len(store_urls)} store-specific URLs for re-indexing.")
    
    # 3. Submit to Google Indexing API
    submit_to_google_indexing(store_urls, sa_key, dry_run=args.dry_run)
    
    # 4. Submit to IndexNow (Bing/Baidu/DuckDuckGo)
    submit_to_indexnow(store_urls, dry_run=args.dry_run)
    
    print("\n[OK] Popular Pages Indexer run completed successfully!")
    print("=" * 70)

if __name__ == "__main__":
    main()

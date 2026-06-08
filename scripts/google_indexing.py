#!/usr/bin/env python3
"""
google_indexing.py — Google Indexing API automation for MeeeShop
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Submits newly published Shopify blog articles AND product pages
to the Google Indexing API so they appear in Search (and are
eligible for Discover) within hours instead of days/weeks.

Requirements (one-time manual setup):
  1. Google Cloud project with "Web Search Indexing API" enabled
  2. Service account JSON key stored as GitHub secret: GOOGLE_SA_KEY_JSON
  3. Service account email added as Owner in Google Search Console

Usage:
  python google_indexing.py               # index blogs published today
  python google_indexing.py --days 3      # index blogs from last 3 days
  python google_indexing.py --products    # also index product pages
  python google_indexing.py --dry-run     # print URLs only, no API calls
  python google_indexing.py --limit 50    # cap URLs submitted (default 200)

Google Indexing API quota:
  - Free tier: 200 URL submissions per day per project
  - Blogs + products combined must stay under 200/day

Exit codes:
  0 = success (even if 0 URLs found)
  1 = fatal error (bad credentials, quota exceeded, etc.)
"""

import os
import sys
import json
import time
import argparse
import textwrap
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import requests

# ── add parent dir so secrets_manager is importable ───────────────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from secrets_manager import inject_to_env, get_secret

inject_to_env()

# ── constants ─────────────────────────────────────────────────────────────────
INDEXING_API_ENDPOINT = "https://indexing.googleapis.com/v3/urlNotifications:publish"
OAUTH_TOKEN_ENDPOINT  = "https://oauth2.googleapis.com/token"
INDEXING_SCOPE        = "https://www.googleapis.com/auth/indexing"

SHOP      = get_secret("SHOPIFY_STORE")
TOKEN     = get_secret("SHOPIFY_ACCESS_TOKEN")
API_VER   = "2024-10"
BASE      = f"https://{SHOP}/admin/api/{API_VER}"
HEADERS   = {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}
STORE_URL = get_secret("STORE_BASE_URL")  # e.g. https://us.meeeshop.com

if not TOKEN:
    sys.exit("ERROR: SHOPIFY_ACCESS_TOKEN not set.")

# ── load Google Service Account key ───────────────────────────────────────────

def _load_sa_key() -> dict:
    """
    Load service account JSON key from:
      1. GOOGLE_SA_KEY_JSON env var (GitHub Actions secret — entire JSON as string)
      2. GOOGLE_SA_KEY_FILE env var (path to local .json file)
      3. google_sa_key.json file in repo root (local dev only, gitignored)
    """
    # Option 1: JSON string in environment variable (GitHub Actions)
    raw = os.environ.get("GOOGLE_SA_KEY_JSON", "").strip()
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            sys.exit(f"ERROR: GOOGLE_SA_KEY_JSON is not valid JSON: {e}")

    # Option 2: File path in environment variable
    key_path = os.environ.get("GOOGLE_SA_KEY_FILE", "").strip()
    if key_path and Path(key_path).exists():
        return json.loads(Path(key_path).read_text(encoding="utf-8"))

    # Option 3: Local fallback file (never commit this!)
    local = Path(__file__).parent.parent / "google_sa_key.json"
    if local.exists():
        print(f"  [WARN] Using local key file: {local} — do NOT commit this file!")
        return json.loads(local.read_text(encoding="utf-8"))

    sys.exit(
        "ERROR: Google Service Account key not found.\n"
        "  Set GOOGLE_SA_KEY_JSON GitHub secret with the full JSON content of your key file.\n"
        "  See GOOGLE_INDEXING_SETUP.md for instructions."
    )


# ── JWT + OAuth2 token ────────────────────────────────────────────────────────

def _get_access_token(sa_key: dict) -> str:
    """
    Generate a short-lived OAuth2 access token using the service account's
    private key (RS256 JWT → exchange for Bearer token).
    """
    try:
        import base64, hashlib
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.backends import default_backend
    except ImportError:
        sys.exit(
            "ERROR: 'cryptography' package missing.\n"
            "  Run: pip install cryptography"
        )

    now = int(time.time())
    header  = {"alg": "RS256", "typ": "JWT"}
    payload = {
        "iss":   sa_key["client_email"],
        "scope": INDEXING_SCOPE,
        "aud":   OAUTH_TOKEN_ENDPOINT,
        "exp":   now + 3600,
        "iat":   now,
    }

    def _b64url(data: dict) -> str:
        import base64, json as _json
        return base64.urlsafe_b64encode(_json.dumps(data, separators=(",",":")).encode()).rstrip(b"=").decode()

    signing_input = f"{_b64url(header)}.{_b64url(payload)}".encode()

    private_key = serialization.load_pem_private_key(
        sa_key["private_key"].encode(),
        password=None,
        backend=default_backend(),
    )
    signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())

    import base64
    sig_b64 = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()
    jwt_token = f"{signing_input.decode()}.{sig_b64}"

    # Exchange JWT for access token
    resp = requests.post(
        OAUTH_TOKEN_ENDPOINT,
        data={
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion":  jwt_token,
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


# ── Shopify data fetchers ─────────────────────────────────────────────────────

def _shopify_get(url: str, params: dict = None) -> dict:
    for attempt in range(4):
        try:
            r = requests.get(url, headers=HEADERS, params=params, timeout=20)
            if r.status_code == 429:
                wait = int(float(r.headers.get("Retry-After", 4)))
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r.json()
        except requests.exceptions.ConnectionError:
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"GET {url} failed after 4 attempts")


def fetch_recent_articles(days: int = 1) -> list[dict]:
    """Return articles published within the last `days` days across all blogs."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_str = cutoff.strftime("%Y-%m-%dT%H:%M:%S%z")

    blogs = _shopify_get(f"{BASE}/blogs.json").get("blogs", [])
    articles = []

    for blog in blogs:
        blog_id = blog["id"]
        blog_handle = blog.get("handle", str(blog_id))

        # Shopify API: published_at_min filter
        data = _shopify_get(
            f"{BASE}/blogs/{blog_id}/articles.json",
            params={
                "limit":             250,
                "published_at_min":  cutoff_str,
                "published_status":  "published",
                "fields":            "id,title,handle,published_at,blog_id",
            },
        )
        for art in data.get("articles", []):
            art["_blog_handle"] = blog_handle
            articles.append(art)

    return articles


def build_article_url(article: dict) -> str:
    """Construct the canonical public URL of a Shopify article."""
    blog_handle    = article.get("_blog_handle", "news")
    article_handle = article.get("handle", str(article.get("id", "")))
    base = STORE_URL.rstrip("/")
    return f"{base}/blogs/{blog_handle}/{article_handle}"


def fetch_product_urls(limit: int = 100) -> list[str]:
    """Return the public URL for each published product."""
    data = _shopify_get(
        f"{BASE}/products.json",
        params={"limit": limit, "published_status": "published", "fields": "handle"},
    )
    base = STORE_URL.rstrip("/")
    return [f"{base}/products/{p['handle']}" for p in data.get("products", []) if p.get("handle")]


# ── Google Indexing API ───────────────────────────────────────────────────────

def submit_url(url: str, token: str, notification_type: str = "URL_UPDATED") -> dict:
    """
    Submit a single URL to the Google Indexing API.
    notification_type: "URL_UPDATED" (index/re-index) or "URL_DELETED" (remove)
    Returns the API response dict.
    """
    resp = requests.post(
        INDEXING_API_ENDPOINT,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type":  "application/json",
        },
        json={"url": url, "type": notification_type},
        timeout=15,
    )
    return {"status": resp.status_code, "body": resp.json(), "url": url}


def submit_urls_batch(urls: list[str], token: str, dry_run: bool = False) -> dict:
    """
    Submit a list of URLs to Google Indexing API with rate limiting.
    Returns summary dict: {submitted, success, failed, skipped, errors}
    """
    if not urls:
        print("  No URLs to submit.")
        return {"submitted": 0, "success": 0, "failed": 0, "skipped": 0, "errors": []}

    submitted = 0
    success   = 0
    failed    = 0
    errors    = []

    print(f"\n  Submitting {len(urls)} URL(s) to Google Indexing API…")
    print(f"  {'[DRY-RUN] ' if dry_run else ''}Mode: URL_UPDATED")
    print()

    for i, url in enumerate(urls, 1):
        prefix = f"  [{i:>3}/{len(urls)}]"
        if dry_run:
            print(f"{prefix} [DRY-RUN] {url}")
            submitted += 1
            success   += 1
            continue

        result = submit_url(url, token)
        submitted += 1

        status = result["status"]
        body   = result["body"]

        if status == 200:
            notify_time = body.get("urlNotificationMetadata", {}).get("latestUpdate", {}).get("notifyTime", "")
            print(f"{prefix} ✓ OK  {url}")
            if notify_time:
                print(f"             → notifyTime: {notify_time}")
            success += 1

        elif status == 429:
            print(f"{prefix} ⚠ QUOTA EXCEEDED — stopping early (Google daily limit reached)")
            errors.append({"url": url, "status": status, "error": "Quota exceeded"})
            failed += 1
            break  # No point retrying — daily quota is exhausted

        elif status == 403:
            err_msg = body.get("error", {}).get("message", "Permission denied")
            print(f"{prefix} ✗ 403 PERMISSION DENIED: {err_msg}")
            print("             → Service account may not be Owner in Google Search Console")
            errors.append({"url": url, "status": status, "error": err_msg})
            failed += 1
            break  # Auth issue affects all URLs — stop early

        else:
            err_msg = body.get("error", {}).get("message", str(body))[:120]
            print(f"{prefix} ✗ {status}: {err_msg}")
            errors.append({"url": url, "status": status, "error": err_msg})
            failed += 1

        # Polite rate limiting: 10 req/s max, add small delay
        time.sleep(0.15)

    return {
        "submitted": submitted,
        "success":   success,
        "failed":    failed,
        "skipped":   len(urls) - submitted,
        "errors":    errors,
    }


# ── main ──────────────────────────────────────────────────────────────────────

def run(days: int = 1, include_products: bool = False,
        dry_run: bool = False, limit: int = 200):

    print(f"\n{'='*62}")
    print(f"  MeeeShop Google Indexing API — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  Blogs: last {days} day(s) | Products: {include_products} | Dry-run: {dry_run}")
    print(f"{'='*62}\n")

    # 1. Collect URLs
    urls = []

    print(f"Fetching recently published blog articles (last {days} day(s))…")
    articles = fetch_recent_articles(days=days)
    blog_urls = [build_article_url(a) for a in articles]
    print(f"  Found {len(blog_urls)} article(s):")
    for u in blog_urls:
        print(f"    • {u}")

    urls.extend(blog_urls)

    if include_products:
        print(f"\nFetching product URLs…")
        product_urls = fetch_product_urls(limit=100)
        print(f"  Found {len(product_urls)} product(s)")
        urls.extend(product_urls)

    # 2. Deduplicate + cap
    urls = list(dict.fromkeys(urls))  # preserve order, remove dupes
    if len(urls) > limit:
        print(f"\n  [WARN] {len(urls)} URLs exceed limit {limit}. Truncating to {limit}.")
        print(f"         Increase --limit or split into multiple runs.")
        urls = urls[:limit]

    if not urls:
        print("\nNothing to index — no new articles or products found.")
        print("Tip: run with --days 7 to widen the window, or --products to include products.")
        return

    # 3. Authenticate (skip in dry-run)
    if dry_run:
        token = "DRY_RUN_TOKEN"
        print(f"\n[DRY-RUN] Skipping OAuth2 authentication.")
    else:
        print(f"\nAuthenticating with Google (OAuth2 service account)…")
        sa_key = _load_sa_key()
        print(f"  Service account: {sa_key.get('client_email', 'unknown')}")
        token = _get_access_token(sa_key)
        print(f"  ✓ Access token acquired")

    # 4. Submit
    summary = submit_urls_batch(urls, token, dry_run=dry_run)

    # 5. Print summary
    print(f"\n{'─'*62}")
    print(f"  Summary:")
    print(f"    URLs collected : {len(urls)}")
    print(f"    Submitted      : {summary['submitted']}")
    print(f"    ✓ Success      : {summary['success']}")
    print(f"    ✗ Failed       : {summary['failed']}")
    if summary["skipped"]:
        print(f"    ⊝ Skipped      : {summary['skipped']}")
    if summary["errors"]:
        print(f"\n  Errors:")
        for e in summary["errors"]:
            print(f"    • [{e['status']}] {e['url']}: {e['error']}")
    print(f"{'─'*62}")

    if summary["failed"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(
        description="Submit Shopify blog articles (and optionally products) to Google Indexing API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
        Examples:
          python google_indexing.py                   # today's blogs
          python google_indexing.py --days 3          # last 3 days of blogs
          python google_indexing.py --products        # blogs + all products
          python google_indexing.py --dry-run         # test without API calls
          python google_indexing.py --limit 50        # cap at 50 URLs
        """),
    )
    ap.add_argument("--days",     type=int,  default=1,     help="Lookback window in days (default: 1)")
    ap.add_argument("--products", action="store_true",      help="Also index product pages")
    ap.add_argument("--dry-run",  action="store_true",      help="Print URLs only, no API calls")
    ap.add_argument("--limit",    type=int,  default=200,   help="Max URLs to submit per run (default: 200)")
    args = ap.parse_args()

    run(
        days=args.days,
        include_products=args.products,
        dry_run=args.dry_run,
        limit=args.limit,
    )

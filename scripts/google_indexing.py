#!/usr/bin/env python3
"""
google_indexing.py — Google Indexing API automation for MeeeShop
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Submits newly published Shopify blog articles, product pages, and
collection pages to the Google Indexing API so they appear in Search
(and are eligible for Discover) within hours instead of days/weeks.

Logs every step to console AND to a JSON log file:
  google_indexing_YYYYMMDD_HHMMSS.json

Sections logged:
  [AUTH]        — OAuth2 service account authentication
  [BLOGS]       — blog articles found per blog
  [PRODUCTS]    — products found
  [COLLECTIONS] — collection pages found
  [SUBMIT]      — per-URL submission result + Google notifyTime
  [SUMMARY]     — totals, success/fail counts, quota remaining

Setup (one-time):
  1. Enable "Web Search Indexing API" in Google Cloud Console
  2. python scripts/add_google_sa_key.py --key-file google_sa_key.json
  3. Add service account as Owner in Google Search Console
  4. Commit updated secrets.enc

Usage:
  python google_indexing.py               # blogs from last 1 day
  python google_indexing.py --days 3      # blogs from last 3 days
  python google_indexing.py --products    # + all product pages
  python google_indexing.py --collections # + all collection pages
  python google_indexing.py --dry-run     # log only, no API calls
  python google_indexing.py --limit 50    # cap at 50 URLs

Google Indexing API quota:
  Free tier: 200 URL submissions per day per project
"""

import os
import sys
import json
import time
import logging
import argparse
import textwrap
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

# ── path setup ────────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from secrets_manager import inject_to_env, get_secret

inject_to_env()

# ── load all credentials from vault ──────────────────────────────────────────
SHOP      = get_secret("SHOPIFY_STORE")
TOKEN     = get_secret("SHOPIFY_ACCESS_TOKEN")
STORE_URL = get_secret("STORE_BASE_URL").rstrip("/")
API_VER   = "2024-10"
BASE      = f"https://{SHOP}/admin/api/{API_VER}"
SHP_HDR   = {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}

if not TOKEN:
    sys.exit("ERROR: SHOPIFY_ACCESS_TOKEN not set in secrets vault.")

# ── Google API constants ──────────────────────────────────────────────────────
INDEXING_API_ENDPOINT = "https://indexing.googleapis.com/v3/urlNotifications:publish"
OAUTH_TOKEN_ENDPOINT  = "https://oauth2.googleapis.com/token"
INDEXING_SCOPE        = "https://www.googleapis.com/auth/indexing"


# ─────────────────────────────────────────────────────────────────────────────
# LOGGING SETUP
# ─────────────────────────────────────────────────────────────────────────────

def setup_logger(log_path: Path) -> logging.Logger:
    """Configure logger that writes to both console and JSON-friendly file."""
    logger = logging.getLogger("google_indexing")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    fmt = logging.Formatter("[%(asctime)s] %(levelname)-7s %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")

    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    # File handler (plain text, mirrors console)
    fh = logging.FileHandler(log_path.with_suffix(".log"), encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    return logger


# ─────────────────────────────────────────────────────────────────────────────
# JSON RUN REPORT  (saved as google_indexing_YYYYMMDD_HHMMSS.json)
# ─────────────────────────────────────────────────────────────────────────────

class RunReport:
    """Collects all events during a run and writes them to a JSON log file."""

    def __init__(self, json_path: Path):
        self.path = json_path
        self.data: dict = {
            "run_at":       datetime.now(timezone.utc).isoformat(),
            "store":        SHOP,
            "store_url":    STORE_URL,
            "auth":         {},
            "discovery":    {"blogs": [], "products": [], "collections": []},
            "submissions":  [],
            "summary":      {},
        }

    def save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)

    # ── auth ──────────────────────────────────────────────────────────────────
    def set_auth(self, success: bool, service_account: str = "",
                 error: str = "", dry_run: bool = False):
        self.data["auth"] = {
            "success":         success,
            "dry_run":         dry_run,
            "service_account": service_account,
            "error":           error,
            "timestamp":       datetime.now(timezone.utc).isoformat(),
        }
        self.save()

    # ── discovery ─────────────────────────────────────────────────────────────
    def add_blog(self, blog_title: str, blog_handle: str, article_count: int,
                 articles: list):
        self.data["discovery"]["blogs"].append({
            "blog_title":    blog_title,
            "blog_handle":   blog_handle,
            "article_count": article_count,
            "articles":      articles,
        })
        self.save()

    def set_products(self, count: int, urls: list[str]):
        self.data["discovery"]["products"] = {
            "count": count,
            "urls":  urls,
        }
        self.save()

    def set_collections(self, count: int, urls: list[str]):
        self.data["discovery"]["collections"] = {
            "count": count,
            "urls":  urls,
        }
        self.save()

    # ── submission ────────────────────────────────────────────────────────────
    def add_submission(self, url: str, url_type: str, status: int,
                       success: bool, notify_time: str = "",
                       error: str = "", dry_run: bool = False):
        self.data["submissions"].append({
            "url":         url,
            "type":        url_type,
            "http_status": status,
            "success":     success,
            "notify_time": notify_time,
            "error":       error,
            "dry_run":     dry_run,
            "submitted_at": datetime.now(timezone.utc).isoformat(),
        })
        self.save()

    # ── summary ───────────────────────────────────────────────────────────────
    def set_summary(self, total: int, success: int, failed: int,
                    skipped: int, quota_used: int, dry_run: bool):
        self.data["summary"] = {
            "total_urls":        total,
            "submitted":         total - skipped,
            "success":           success,
            "failed":            failed,
            "skipped":           skipped,
            "quota_used_today":  quota_used,
            "quota_remaining":   max(0, 200 - quota_used),
            "dry_run":           dry_run,
            "completed_at":      datetime.now(timezone.utc).isoformat(),
        }
        self.save()


# ─────────────────────────────────────────────────────────────────────────────
# SERVICE ACCOUNT KEY LOADER
# ─────────────────────────────────────────────────────────────────────────────

def load_sa_key(log: logging.Logger) -> dict:
    """
    Load Google Service Account JSON from secrets.enc vault.
    Fallback: google_sa_key.json in repo root (local dev only, gitignored).
    """
    log.info("[AUTH] Loading Google Service Account key from secrets vault...")
    try:
        raw = get_secret("GOOGLE_SA_KEY_JSON")
        parsed = json.loads(raw)
        log.info("[AUTH] SA key loaded from secrets.enc vault OK")
        log.info("[AUTH]   service_account : %s", parsed.get("client_email", "?"))
        log.info("[AUTH]   project_id      : %s", parsed.get("project_id", "?"))
        log.info("[AUTH]   key_id          : %s...", parsed.get("private_key_id", "?")[:12])
        return parsed
    except KeyError:
        log.warning("[AUTH] GOOGLE_SA_KEY_JSON not found in vault — trying local fallback")
    except Exception as e:
        log.warning("[AUTH] Could not load from vault: %s — trying local fallback", e)

    local = Path(__file__).parent.parent / "google_sa_key.json"
    if local.exists():
        log.warning("[AUTH] Using local google_sa_key.json — run add_google_sa_key.py to move into vault")
        return json.loads(local.read_text(encoding="utf-8"))

    log.error("[AUTH] FATAL: Google SA key not found in vault or locally")
    sys.exit(
        "ERROR: GOOGLE_SA_KEY_JSON not in secrets.enc.\n"
        "  Run: python scripts/add_google_sa_key.py --key-file google_sa_key.json"
    )


# ─────────────────────────────────────────────────────────────────────────────
# OAUTH2 AUTHENTICATION
# ─────────────────────────────────────────────────────────────────────────────

def get_access_token(sa_key: dict, log: logging.Logger,
                     report: RunReport) -> str:
    """Exchange service account private key for a short-lived Bearer token."""
    log.info("[AUTH] Requesting OAuth2 access token from Google...")
    try:
        import base64
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.backends import default_backend
    except ImportError:
        log.error("[AUTH] 'cryptography' package missing — run: pip install cryptography")
        sys.exit(1)

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
        import json as _j
        return base64.urlsafe_b64encode(
            _j.dumps(data, separators=(",", ":")).encode()
        ).rstrip(b"=").decode()

    signing_input = f"{_b64url(header)}.{_b64url(payload)}".encode()
    private_key = serialization.load_pem_private_key(
        sa_key["private_key"].encode(), password=None, backend=default_backend()
    )
    signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    sig_b64   = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()
    jwt_token = f"{signing_input.decode()}.{sig_b64}"

    try:
        resp = requests.post(
            OAUTH_TOKEN_ENDPOINT,
            data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                  "assertion": jwt_token},
            timeout=15,
        )
        resp.raise_for_status()
        token = resp.json()["access_token"]
        log.info("[AUTH] OAuth2 token acquired successfully")
        log.info("[AUTH]   expires_in : %s seconds", resp.json().get("expires_in", "?"))
        report.set_auth(
            success=True,
            service_account=sa_key.get("client_email", ""),
        )
        return token

    except requests.HTTPError as e:
        body = ""
        try:
            body = resp.json()
        except Exception:
            body = resp.text
        log.error("[AUTH] FAILED to get access token: %s", e)
        log.error("[AUTH] Google response: %s", body)
        report.set_auth(
            success=False,
            service_account=sa_key.get("client_email", ""),
            error=str(e),
        )
        sys.exit("ERROR: Could not authenticate with Google. Check service account key and permissions.")


# ─────────────────────────────────────────────────────────────────────────────
# SHOPIFY DATA FETCHERS
# ─────────────────────────────────────────────────────────────────────────────

def _shopify_get(url: str, params: dict = None) -> dict:
    """Shopify GET with rate-limit handling and retry."""
    for attempt in range(4):
        try:
            r = requests.get(url, headers=SHP_HDR, params=params, timeout=20)
            if r.status_code == 429:
                wait = int(float(r.headers.get("Retry-After", 4)))
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r.json()
        except requests.exceptions.ConnectionError:
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"GET {url} failed after 4 attempts")


def fetch_recent_articles(days: int, log: logging.Logger,
                          report: RunReport) -> list[dict]:
    """Fetch all published articles across all blogs within the lookback window."""
    cutoff     = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_str = cutoff.strftime("%Y-%m-%dT%H:%M:%S%z")

    log.info("[BLOGS] Fetching all blogs from Shopify...")
    blogs = _shopify_get(f"{BASE}/blogs.json").get("blogs", [])
    log.info("[BLOGS] Found %d blog(s) total", len(blogs))

    all_articles = []

    for blog in blogs:
        blog_id     = blog["id"]
        blog_title  = blog.get("title", "Unknown")
        blog_handle = blog.get("handle", str(blog_id))

        log.info("[BLOGS]   Scanning blog: '%s' (handle: %s, id: %s)",
                 blog_title, blog_handle, blog_id)

        data = _shopify_get(
            f"{BASE}/blogs/{blog_id}/articles.json",
            params={
                "limit":            250,
                "published_at_min": cutoff_str,
                "published_status": "published",
                "fields":           "id,title,handle,published_at,blog_id",
            },
        )
        articles = data.get("articles", [])

        if not articles:
            log.info("[BLOGS]     No articles found in last %d day(s)", days)
        else:
            log.info("[BLOGS]     Found %d article(s):", len(articles))
            article_log = []
            for art in articles:
                art["_blog_handle"] = blog_handle
                art["_blog_title"]  = blog_title
                pub_at = art.get("published_at", "unknown")
                url    = f"{STORE_URL}/blogs/{blog_handle}/{art.get('handle', art['id'])}"
                log.info("[BLOGS]       + [%s] %s", pub_at[:10], art.get("title", "?"))
                log.info("[BLOGS]         URL: %s", url)
                article_log.append({
                    "id":           art["id"],
                    "title":        art.get("title", ""),
                    "handle":       art.get("handle", ""),
                    "published_at": pub_at,
                    "url":          url,
                })
                all_articles.append(art)

            report.add_blog(blog_title, blog_handle, len(articles), article_log)

    log.info("[BLOGS] Total articles to submit: %d", len(all_articles))
    return all_articles


def build_article_url(article: dict) -> str:
    blog_handle    = article.get("_blog_handle", "news")
    article_handle = article.get("handle", str(article.get("id", "")))
    return f"{STORE_URL}/blogs/{blog_handle}/{article_handle}"


def fetch_products(log: logging.Logger, report: RunReport,
                   limit: int = 200) -> list[str]:
    """Fetch all published product URLs from Shopify."""
    log.info("[PRODUCTS] Fetching published products from Shopify (limit %d)...", limit)
    data = _shopify_get(
        f"{BASE}/products.json",
        params={
            "limit":            limit,
            "published_status": "published",
            "fields":           "id,title,handle,product_type,status",
        },
    )
    products = data.get("products", [])
    urls = []
    log.info("[PRODUCTS] Found %d product(s):", len(products))
    for p in products:
        if p.get("handle"):
            url = f"{STORE_URL}/products/{p['handle']}"
            log.info("[PRODUCTS]   + %-60s  (%s)", p.get("title", "?")[:60],
                     p.get("product_type", "—"))
            log.debug("[PRODUCTS]     URL: %s", url)
            urls.append(url)

    report.set_products(len(urls), urls)
    log.info("[PRODUCTS] Total product URLs collected: %d", len(urls))
    return urls


def fetch_collections(log: logging.Logger, report: RunReport) -> list[str]:
    """Fetch all published custom and smart collection URLs from Shopify."""
    log.info("[COLLECTIONS] Fetching collections from Shopify...")
    urls = []

    # Custom collections
    data_custom = _shopify_get(
        f"{BASE}/custom_collections.json",
        params={"limit": 250, "published_status": "published",
                "fields": "id,title,handle"},
    )
    custom = data_custom.get("custom_collections", [])
    log.info("[COLLECTIONS]   Custom collections: %d", len(custom))

    # Smart collections
    data_smart = _shopify_get(
        f"{BASE}/smart_collections.json",
        params={"limit": 250, "published_status": "published",
                "fields": "id,title,handle"},
    )
    smart = data_smart.get("smart_collections", [])
    log.info("[COLLECTIONS]   Smart collections : %d", len(smart))

    for col in custom + smart:
        if col.get("handle"):
            url = f"{STORE_URL}/collections/{col['handle']}"
            log.info("[COLLECTIONS]   + %-60s", col.get("title", "?")[:60])
            log.debug("[COLLECTIONS]     URL: %s", url)
            urls.append(url)

    report.set_collections(len(urls), urls)
    log.info("[COLLECTIONS] Total collection URLs collected: %d", len(urls))
    return urls


# ─────────────────────────────────────────────────────────────────────────────
# GOOGLE INDEXING API SUBMISSION
# ─────────────────────────────────────────────────────────────────────────────

def classify_url(url: str) -> str:
    """Return a human-readable type label for a URL."""
    if "/blogs/" in url:
        return "article"
    if "/products/" in url:
        return "product"
    if "/collections/" in url:
        return "collection"
    return "page"


def submit_urls_batch(urls: list[str], token: str,
                      log: logging.Logger, report: RunReport,
                      dry_run: bool = False) -> dict:
    """Submit all URLs to Google Indexing API with per-URL logging."""

    if not urls:
        log.warning("[SUBMIT] No URLs to submit — nothing to do.")
        return {"submitted": 0, "success": 0, "failed": 0, "skipped": 0}

    total     = len(urls)
    submitted = 0
    success   = 0
    failed    = 0

    log.info("[SUBMIT] ══════════════════════════════════════════")
    log.info("[SUBMIT] Starting submission of %d URL(s)...", total)
    log.info("[SUBMIT] Mode: %s", "DRY-RUN (no API calls)" if dry_run else "LIVE (URL_UPDATED)")
    log.info("[SUBMIT] ══════════════════════════════════════════")

    for i, url in enumerate(urls, 1):
        url_type = classify_url(url)
        prefix   = f"[SUBMIT] [{i:>3}/{total}] [{url_type:>10}]"

        if dry_run:
            log.info("%s [DRY-RUN] %s", prefix, url)
            report.add_submission(url, url_type, 0, True, dry_run=True)
            submitted += 1
            success   += 1
            continue

        try:
            resp = requests.post(
                INDEXING_API_ENDPOINT,
                headers={"Authorization": f"Bearer {token}",
                         "Content-Type": "application/json"},
                json={"url": url, "type": "URL_UPDATED"},
                timeout=15,
            )
            body   = resp.json()
            status = resp.status_code
            submitted += 1

            if status == 200:
                meta        = body.get("urlNotificationMetadata", {})
                latest      = meta.get("latestUpdate", {})
                notify_time = latest.get("notifyTime", "")
                log.info("%s OK  %s", prefix, url)
                if notify_time:
                    log.info("[SUBMIT]              Google notifyTime: %s", notify_time)
                report.add_submission(url, url_type, status, True,
                                      notify_time=notify_time)
                success += 1

            elif status == 429:
                err = body.get("error", {}).get("message", "Quota exceeded")
                log.error("%s QUOTA EXCEEDED: %s", prefix, err)
                log.error("[SUBMIT]   Google daily limit (200/day) reached — stopping.")
                log.error("[SUBMIT]   Remaining URLs will not be submitted today.")
                report.add_submission(url, url_type, status, False, error=err)
                failed += 1
                break  # Quota exhausted — no point continuing

            elif status == 403:
                err = body.get("error", {}).get("message", "Permission denied")
                log.error("%s 403 PERMISSION DENIED: %s", prefix, err)
                log.error("[SUBMIT]   The service account is NOT added as Owner in")
                log.error("[SUBMIT]   Google Search Console. See GOOGLE_INDEXING_SETUP.md")
                report.add_submission(url, url_type, status, False, error=err)
                failed += 1
                break  # Auth issue — all other URLs will fail too

            elif status == 400:
                err = body.get("error", {}).get("message", str(body))[:200]
                log.warning("%s 400 BAD REQUEST: %s", prefix, err)
                log.warning("[SUBMIT]   URL may be malformed or not eligible for indexing.")
                report.add_submission(url, url_type, status, False, error=err)
                failed += 1

            else:
                err = body.get("error", {}).get("message", str(body))[:200]
                log.error("%s ERROR %s: %s", prefix, status, err)
                report.add_submission(url, url_type, status, False, error=err)
                failed += 1

        except requests.exceptions.RequestException as e:
            log.error("%s NETWORK ERROR: %s", prefix, e)
            report.add_submission(url, url_type, 0, False, error=str(e))
            failed += 1

        # Polite rate limiting (Google allows ~10 req/s burst)
        time.sleep(0.15)

    skipped = total - submitted
    return {
        "total":     total,
        "submitted": submitted,
        "success":   success,
        "failed":    failed,
        "skipped":   skipped,
    }


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def run(days: int = 1, include_products: bool = False,
        include_collections: bool = False,
        dry_run: bool = False, limit: int = 200):

    run_ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_base = Path(f"google_indexing_{run_ts}")
    report   = RunReport(log_base.with_suffix(".json"))
    log      = setup_logger(log_base)

    # ── banner ─────────────────────────────────────────────────────────────
    log.info("=" * 65)
    log.info("  MeeeShop Google Indexing API — %s",
             datetime.now().strftime("%Y-%m-%d %H:%M UTC"))
    log.info("  Store       : %s", SHOP)
    log.info("  Store URL   : %s", STORE_URL)
    log.info("  Lookback    : last %d day(s)", days)
    log.info("  Products    : %s", include_products)
    log.info("  Collections : %s", include_collections)
    log.info("  Dry-run     : %s", dry_run)
    log.info("  URL limit   : %d (Google quota: 200/day)", limit)
    log.info("  Log file    : %s", log_base.with_suffix(".json"))
    log.info("=" * 65)

    # ── 1. Authenticate ────────────────────────────────────────────────────
    if dry_run:
        log.info("[AUTH] DRY-RUN mode — skipping OAuth2 authentication")
        report.set_auth(success=True, service_account="dry-run", dry_run=True)
        token = "DRY_RUN_TOKEN"
    else:
        sa_key = load_sa_key(log)
        token  = get_access_token(sa_key, log, report)

    # ── 2. Discover URLs ───────────────────────────────────────────────────
    all_urls      = []
    url_meta      = {}   # url -> type label

    # Blog articles
    log.info("-" * 65)
    articles  = fetch_recent_articles(days, log, report)
    blog_urls = [build_article_url(a) for a in articles]
    for u in blog_urls:
        url_meta[u] = "article"
    all_urls.extend(blog_urls)

    # Products
    if include_products:
        log.info("-" * 65)
        product_urls = fetch_products(log, report, limit=250)
        for u in product_urls:
            url_meta[u] = "product"
        all_urls.extend(product_urls)

    # Collections
    if include_collections:
        log.info("-" * 65)
        collection_urls = fetch_collections(log, report)
        for u in collection_urls:
            url_meta[u] = "collection"
        all_urls.extend(collection_urls)

    # ── 3. Deduplicate + cap ───────────────────────────────────────────────
    log.info("-" * 65)
    before_dedup = len(all_urls)
    all_urls = list(dict.fromkeys(all_urls))
    if len(all_urls) < before_dedup:
        log.info("[DEDUP] Removed %d duplicate URL(s)", before_dedup - len(all_urls))

    if len(all_urls) > limit:
        log.warning("[LIMIT] %d URLs exceed --limit %d — truncating to %d",
                    len(all_urls), limit, limit)
        log.warning("[LIMIT] Increase --limit or run again with --days for the rest")
        all_urls = all_urls[:limit]

    if not all_urls:
        log.info("[SUBMIT] No URLs to submit.")
        log.info("[SUBMIT] Tips:")
        log.info("[SUBMIT]   - Use --days 7 to widen the lookback window")
        log.info("[SUBMIT]   - Use --products to also index product pages")
        log.info("[SUBMIT]   - Use --collections to also index collection pages")
        report.set_summary(0, 0, 0, 0, 0, dry_run)
        return

    log.info("[URLS] Total URLs to submit: %d", len(all_urls))
    articles_count   = sum(1 for u in all_urls if url_meta.get(u) == "article")
    products_count   = sum(1 for u in all_urls if url_meta.get(u) == "product")
    collections_count = sum(1 for u in all_urls if url_meta.get(u) == "collection")
    log.info("[URLS]   Articles   : %d", articles_count)
    log.info("[URLS]   Products   : %d", products_count)
    log.info("[URLS]   Collections: %d", collections_count)

    # ── 4. Submit ──────────────────────────────────────────────────────────
    log.info("-" * 65)
    result = submit_urls_batch(all_urls, token, log, report, dry_run=dry_run)

    # ── 5. Final summary ───────────────────────────────────────────────────
    log.info("=" * 65)
    log.info("[SUMMARY] Run complete")
    log.info("[SUMMARY]   Total URLs collected   : %d", result["total"])
    log.info("[SUMMARY]   Submitted to Google    : %d", result["submitted"])
    log.info("[SUMMARY]   Successfully indexed   : %d", result["success"])
    log.info("[SUMMARY]   Failed                 : %d", result["failed"])
    if result["skipped"]:
        log.info("[SUMMARY]   Skipped (quota/limit) : %d", result["skipped"])
    log.info("[SUMMARY]   Google quota used today: ~%d / 200", result["submitted"])
    log.info("[SUMMARY]   Google quota remaining : ~%d", max(0, 200 - result["submitted"]))
    log.info("[SUMMARY]   Log saved to           : %s", log_base.with_suffix(".json"))
    log.info("[SUMMARY]   Verify indexing at     : https://search.google.com/search-console/")
    log.info("=" * 65)

    report.set_summary(
        total=result["total"],
        success=result["success"],
        failed=result["failed"],
        skipped=result["skipped"],
        quota_used=result["submitted"],
        dry_run=dry_run,
    )

    if result["failed"] > 0 and not dry_run:
        sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(
        description="Submit Shopify URLs to Google Indexing API with full logging",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
        Examples:
          python google_indexing.py                    # today's blog articles
          python google_indexing.py --days 3           # last 3 days of articles
          python google_indexing.py --products         # blogs + all products
          python google_indexing.py --collections      # blogs + all collections
          python google_indexing.py --products --collections  # everything
          python google_indexing.py --dry-run          # log only, no API calls
          python google_indexing.py --limit 50         # cap at 50 URLs
        """),
    )
    ap.add_argument("--days",        type=int, default=1,
                    help="Lookback window in days for blog articles (default: 1)")
    ap.add_argument("--products",    action="store_true",
                    help="Also submit all published product pages")
    ap.add_argument("--collections", action="store_true",
                    help="Also submit all published collection pages")
    ap.add_argument("--dry-run",     action="store_true",
                    help="Log URLs without making any API calls to Google")
    ap.add_argument("--limit",       type=int, default=200,
                    help="Max URLs to submit per run (Google quota: 200/day, default: 200)")
    args = ap.parse_args()

    run(
        days=args.days,
        include_products=args.products,
        include_collections=args.collections,
        dry_run=args.dry_run,
        limit=args.limit,
    )

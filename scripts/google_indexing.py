#!/usr/bin/env python3
"""
google_indexing.py — Google Indexing API automation for MeeeShop
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Submits newly published Shopify blog articles, product pages, and
collection pages to the Google Indexing API for fast crawling.

SMART DEDUPLICATION:
  - Tracks every submitted URL in indexing_history.json
  - By default skips URLs already submitted within --skip-hours (default 48)
  - URLs skipped due to quota are saved to a pending queue
  - Next run automatically prioritises the pending queue first
  - Use --force to resubmit everything regardless of history
  - Use --pending-only to only process the quota backlog

HISTORY PERSISTENCE (GitHub Actions):
  - History file is uploaded/downloaded as artifact "google-indexing-history"
  - Persists across workflow runs without polluting git history

Usage:
  python google_indexing.py                    # new articles from last 1 day
  python google_indexing.py --days 7           # articles from last 7 days
  python google_indexing.py --products         # + all products
  python google_indexing.py --collections      # + all collections
  python google_indexing.py --pending-only     # only submit quota backlog
  python google_indexing.py --force            # resubmit all, ignore history
  python google_indexing.py --skip-hours 24   # custom skip window
  python google_indexing.py --dry-run          # log only, no API calls
  python google_indexing.py --limit 150        # cap at 150 (leave buffer)

Google Indexing API quota: 200 submissions / day / project (free tier)
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

# ── credentials (all from secrets.enc vault) ──────────────────────────────────
SHOP      = get_secret("SHOPIFY_STORE")
TOKEN     = get_secret("SHOPIFY_ACCESS_TOKEN")
STORE_URL = get_secret("STORE_BASE_URL").rstrip("/")
API_VER   = "2024-10"
BASE      = f"https://{SHOP}/admin/api/{API_VER}"
SHP_HDR   = {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}

if not TOKEN:
    sys.exit("ERROR: SHOPIFY_ACCESS_TOKEN not set in secrets vault.")

# ── Google API constants ──────────────────────────────────────────────────────
INDEXING_ENDPOINT = "https://indexing.googleapis.com/v3/urlNotifications:publish"
OAUTH_ENDPOINT    = "https://oauth2.googleapis.com/token"
INDEXING_SCOPE    = "https://www.googleapis.com/auth/indexing"

# ── history file (downloaded as artifact in CI, local in dev) ─────────────────
HISTORY_FILE = Path("indexing_history.json")


# ─────────────────────────────────────────────────────────────────────────────
# SUBMISSION HISTORY  (tracks submitted + pending queue)
# ─────────────────────────────────────────────────────────────────────────────

class SubmissionHistory:
    """
    Persistent record of URL submissions.

    Structure of indexing_history.json:
    {
      "submitted": {
        "https://url": "2026-06-08T10:00:00+00:00",   # last submit time
        ...
      },
      "pending": [
        "https://url-skipped-due-to-quota",
        ...
      ],
      "stats": {
        "total_submitted_all_time": 302,
        "last_run_at": "2026-06-08T10:00:00+00:00"
      }
    }
    """

    def __init__(self, path: Path = HISTORY_FILE):
        self.path = path
        self._data: dict = {"submitted": {}, "pending": [], "stats": {}}
        self._load()

    def _load(self):
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
                # Ensure all keys exist (backward compat)
                self._data.setdefault("submitted", {})
                self._data.setdefault("pending", [])
                self._data.setdefault("stats", {})
            except Exception:
                self._data = {"submitted": {}, "pending": [], "stats": {}}

    def save(self):
        self._data["stats"]["last_run_at"] = datetime.now(timezone.utc).isoformat()
        self._data["stats"]["total_submitted_all_time"] = len(self._data["submitted"])
        self.path.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    # ── submitted tracking ────────────────────────────────────────────────────

    def was_submitted_within(self, url: str, hours: int) -> bool:
        """True if URL was successfully submitted within the last `hours` hours."""
        last = self._data["submitted"].get(url)
        if not last:
            return False
        try:
            last_dt = datetime.fromisoformat(last)
            cutoff  = datetime.now(timezone.utc) - timedelta(hours=hours)
            return last_dt > cutoff
        except Exception:
            return False

    def mark_submitted(self, url: str):
        self._data["submitted"][url] = datetime.now(timezone.utc).isoformat()
        # Remove from pending if it was there
        if url in self._data["pending"]:
            self._data["pending"].remove(url)

    def get_last_submitted_at(self, url: str) -> str:
        return self._data["submitted"].get(url, "")

    # ── pending queue ─────────────────────────────────────────────────────────

    def add_pending(self, url: str):
        """Add URL to pending queue (quota-skipped from a previous run)."""
        if url not in self._data["pending"]:
            self._data["pending"].append(url)

    def get_pending(self) -> list:
        return list(self._data["pending"])

    def clear_pending(self):
        self._data["pending"] = []

    # ── reporting helpers ─────────────────────────────────────────────────────

    def total_ever_submitted(self) -> int:
        return len(self._data["submitted"])

    def pending_count(self) -> int:
        return len(self._data["pending"])

    def summary(self) -> dict:
        return {
            "history_file":          str(self.path),
            "total_ever_submitted":  self.total_ever_submitted(),
            "pending_count":         self.pending_count(),
            "last_run_at":           self._data["stats"].get("last_run_at", "never"),
        }


# ─────────────────────────────────────────────────────────────────────────────
# LOGGING SETUP
# ─────────────────────────────────────────────────────────────────────────────

def setup_logger(log_path: Path) -> logging.Logger:
    logger = logging.getLogger("google_indexing")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    fmt = logging.Formatter("[%(asctime)s] %(levelname)-7s %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    fh = logging.FileHandler(log_path.with_suffix(".log"), encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    return logger


# ─────────────────────────────────────────────────────────────────────────────
# JSON RUN REPORT
# ─────────────────────────────────────────────────────────────────────────────

class RunReport:
    def __init__(self, json_path: Path):
        self.path = json_path
        self.data: dict = {
            "run_at":      datetime.now(timezone.utc).isoformat(),
            "store":       SHOP,
            "store_url":   STORE_URL,
            "auth":        {},
            "history":     {},
            "discovery":   {"blogs": [], "products": [], "collections": []},
            "dedup":       {},
            "submissions": [],
            "pending":     {},
            "summary":     {},
        }

    def save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)

    def set_auth(self, success: bool, service_account: str = "",
                 error: str = "", dry_run: bool = False):
        self.data["auth"] = {
            "success": success, "dry_run": dry_run,
            "service_account": service_account, "error": error,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.save()

    def set_history_stats(self, stats: dict):
        self.data["history"] = stats
        self.save()

    def add_blog(self, blog_title, blog_handle, article_count, articles):
        self.data["discovery"]["blogs"].append({
            "blog_title": blog_title, "blog_handle": blog_handle,
            "article_count": article_count, "articles": articles,
        })
        self.save()

    def set_products(self, count, urls):
        self.data["discovery"]["products"] = {"count": count, "urls": urls}
        self.save()

    def set_collections(self, count, urls):
        self.data["discovery"]["collections"] = {"count": count, "urls": urls}
        self.save()

    def set_dedup(self, total_found, skipped_recent, pending_loaded,
                  to_submit, force_mode, skip_hours):
        self.data["dedup"] = {
            "total_found":    total_found,
            "skipped_recent": skipped_recent,
            "pending_loaded": pending_loaded,
            "to_submit":      to_submit,
            "force_mode":     force_mode,
            "skip_hours":     skip_hours,
        }
        self.save()

    def add_submission(self, url, url_type, status, success,
                       notify_time="", error="", dry_run=False, skipped=False,
                       skip_reason="", last_submitted=""):
        self.data["submissions"].append({
            "url": url, "type": url_type,
            "http_status": status, "success": success,
            "notify_time": notify_time, "error": error,
            "dry_run": dry_run, "skipped": skipped,
            "skip_reason": skip_reason,
            "last_submitted_at": last_submitted,
            "submitted_at": datetime.now(timezone.utc).isoformat(),
        })
        self.save()

    def set_pending(self, added_to_queue: list, cleared: list):
        self.data["pending"] = {
            "added_to_queue": added_to_queue,
            "cleared_from_queue": cleared,
        }
        self.save()

    def set_summary(self, total, submitted, success, failed, skipped_recent,
                    pending_loaded, added_to_pending, quota_used, dry_run):
        self.data["summary"] = {
            "total_urls_found":    total,
            "submitted":           submitted,
            "success":             success,
            "failed":              failed,
            "skipped_recent":      skipped_recent,
            "pending_loaded":      pending_loaded,
            "added_to_pending":    added_to_pending,
            "quota_used_today":    quota_used,
            "quota_remaining":     max(0, 200 - quota_used),
            "dry_run":             dry_run,
            "completed_at":        datetime.now(timezone.utc).isoformat(),
        }
        self.save()


# ─────────────────────────────────────────────────────────────────────────────
# SERVICE ACCOUNT KEY LOADER
# ─────────────────────────────────────────────────────────────────────────────

def load_sa_key(log: logging.Logger) -> dict:
    log.info("[AUTH] Loading Google Service Account key from secrets vault...")
    try:
        raw    = get_secret("GOOGLE_SA_KEY_JSON")
        parsed = json.loads(raw)
        log.info("[AUTH] SA key loaded from secrets.enc vault OK")
        log.info("[AUTH]   service_account : %s", parsed.get("client_email", "?"))
        log.info("[AUTH]   project_id      : %s", parsed.get("project_id", "?"))
        log.info("[AUTH]   key_id          : %s...", parsed.get("private_key_id", "?")[:12])
        return parsed
    except KeyError:
        log.warning("[AUTH] GOOGLE_SA_KEY_JSON not in vault — trying local fallback")
    except Exception as e:
        log.warning("[AUTH] Vault load error: %s — trying local fallback", e)

    local = Path(__file__).parent.parent / "google_sa_key.json"
    if local.exists():
        log.warning("[AUTH] Using local google_sa_key.json (run add_google_sa_key.py to vault it)")
        return json.loads(local.read_text(encoding="utf-8"))

    sys.exit(
        "ERROR: GOOGLE_SA_KEY_JSON not found.\n"
        "  Run: python scripts/add_google_sa_key.py --key-file google_sa_key.json"
    )


# ─────────────────────────────────────────────────────────────────────────────
# OAUTH2 AUTHENTICATION
# ─────────────────────────────────────────────────────────────────────────────

def get_access_token(sa_key: dict, log: logging.Logger, report: RunReport) -> str:
    log.info("[AUTH] Requesting OAuth2 access token from Google...")
    try:
        import base64
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.backends import default_backend
    except ImportError:
        sys.exit("ERROR: 'cryptography' package missing — run: pip install cryptography")

    now     = int(time.time())
    header  = {"alg": "RS256", "typ": "JWT"}
    payload = {"iss": sa_key["client_email"], "scope": INDEXING_SCOPE,
                "aud": OAUTH_ENDPOINT, "exp": now + 3600, "iat": now}

    def _b64url(data):
        import json as _j
        return base64.urlsafe_b64encode(
            _j.dumps(data, separators=(",", ":")).encode()
        ).rstrip(b"=").decode()

    signing_input = f"{_b64url(header)}.{_b64url(payload)}".encode()
    pk  = serialization.load_pem_private_key(
        sa_key["private_key"].encode(), password=None, backend=default_backend()
    )
    sig = pk.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    jwt = f"{signing_input.decode()}.{base64.urlsafe_b64encode(sig).rstrip(b'=').decode()}"

    try:
        resp = requests.post(OAUTH_ENDPOINT,
                             data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                                   "assertion": jwt},
                             timeout=15)
        resp.raise_for_status()
        rj   = resp.json()
        log.info("[AUTH] OAuth2 token acquired successfully")
        log.info("[AUTH]   expires_in : %s seconds", rj.get("expires_in", "?"))
        report.set_auth(True, sa_key.get("client_email", ""))
        return rj["access_token"]
    except requests.HTTPError as e:
        try:
            body = resp.json()
        except Exception:
            body = resp.text
        log.error("[AUTH] FAILED: %s", e)
        log.error("[AUTH] Google response: %s", body)
        report.set_auth(False, sa_key.get("client_email", ""), str(e))
        sys.exit("ERROR: Could not authenticate with Google. Check SA key and GSC permissions.")


# ─────────────────────────────────────────────────────────────────────────────
# SHOPIFY DATA FETCHERS
# ─────────────────────────────────────────────────────────────────────────────

def _shopify_get(url: str, params: dict = None) -> dict:
    for attempt in range(4):
        try:
            r = requests.get(url, headers=SHP_HDR, params=params, timeout=20)
            if r.status_code == 429:
                time.sleep(int(float(r.headers.get("Retry-After", 4))))
                continue
            r.raise_for_status()
            return r.json()
        except requests.exceptions.ConnectionError:
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"GET {url} failed after 4 attempts")


def fetch_recent_articles(days: int, log: logging.Logger,
                          report: RunReport) -> list[dict]:
    cutoff     = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_str = cutoff.strftime("%Y-%m-%dT%H:%M:%S%z")

    log.info("[BLOGS] Fetching blogs from Shopify (articles published since %s)...",
             cutoff.strftime("%Y-%m-%d"))
    blogs = _shopify_get(f"{BASE}/blogs.json").get("blogs", [])
    log.info("[BLOGS] Found %d blog(s)", len(blogs))

    all_articles = []
    for blog in blogs:
        blog_id     = blog["id"]
        blog_title  = blog.get("title", "Unknown")
        blog_handle = blog.get("handle", str(blog_id))
        log.info("[BLOGS]   Scanning: '%s' (handle=%s)", blog_title, blog_handle)

        data     = _shopify_get(f"{BASE}/blogs/{blog_id}/articles.json",
                                params={"limit": 250, "published_at_min": cutoff_str,
                                        "published_status": "published",
                                        "fields": "id,title,handle,published_at,blog_id"})
        articles = data.get("articles", [])
        if not articles:
            log.info("[BLOGS]     No articles in window")
        else:
            log.info("[BLOGS]     Found %d article(s):", len(articles))
            art_log = []
            for art in articles:
                art["_blog_handle"] = blog_handle
                art["_blog_title"]  = blog_title
                url = f"{STORE_URL}/blogs/{blog_handle}/{art.get('handle', art['id'])}"
                log.info("[BLOGS]       [%s] %s", art.get("published_at", "?")[:10],
                         art.get("title", "?"))
                log.debug("[BLOGS]         URL: %s", url)
                art_log.append({"id": art["id"], "title": art.get("title", ""),
                                 "handle": art.get("handle", ""),
                                 "published_at": art.get("published_at", ""),
                                 "url": url})
                all_articles.append(art)
            report.add_blog(blog_title, blog_handle, len(articles), art_log)

    log.info("[BLOGS] Total articles found: %d", len(all_articles))
    return all_articles


def build_article_url(article: dict) -> str:
    return f"{STORE_URL}/blogs/{article.get('_blog_handle','news')}/{article.get('handle', str(article.get('id','')))}"


def fetch_products(log: logging.Logger, report: RunReport, limit: int = 250) -> list[str]:
    log.info("[PRODUCTS] Fetching published products (limit=%d)...", limit)
    data     = _shopify_get(f"{BASE}/products.json",
                            params={"limit": limit, "published_status": "published",
                                    "fields": "id,title,handle,product_type"})
    products = data.get("products", [])
    urls     = []
    log.info("[PRODUCTS] Found %d product(s):", len(products))
    for p in products:
        if p.get("handle"):
            url = f"{STORE_URL}/products/{p['handle']}"
            log.info("[PRODUCTS]   + %-60s  (%s)",
                     p.get("title", "?")[:60], p.get("product_type", "—"))
            log.debug("[PRODUCTS]     URL: %s", url)
            urls.append(url)
    report.set_products(len(urls), urls)
    log.info("[PRODUCTS] Total product URLs: %d", len(urls))
    return urls


def fetch_collections(log: logging.Logger, report: RunReport) -> list[str]:
    log.info("[COLLECTIONS] Fetching collections from Shopify...")
    urls = []
    for endpoint, label in [("custom_collections", "custom"), ("smart_collections", "smart")]:
        data  = _shopify_get(f"{BASE}/{endpoint}.json",
                             params={"limit": 250, "published_status": "published",
                                     "fields": "id,title,handle"})
        items = data.get(endpoint, [])
        log.info("[COLLECTIONS]   %s: %d", label, len(items))
        for col in items:
            if col.get("handle"):
                url = f"{STORE_URL}/collections/{col['handle']}"
                log.info("[COLLECTIONS]   + %-60s", col.get("title", "?")[:60])
                log.debug("[COLLECTIONS]     URL: %s", url)
                urls.append(url)
    report.set_collections(len(urls), urls)
    log.info("[COLLECTIONS] Total collection URLs: %d", len(urls))
    return urls


# ─────────────────────────────────────────────────────────────────────────────
# SMART DEDUPLICATION
# ─────────────────────────────────────────────────────────────────────────────

def classify_url(url: str) -> str:
    if "/blogs/" in url:   return "article"
    if "/products/" in url: return "product"
    if "/collections/" in url: return "collection"
    return "page"


def deduplicate(urls: list[str], history: SubmissionHistory,
                log: logging.Logger, report: RunReport,
                force: bool, skip_hours: int,
                pending_only: bool, limit: int) -> tuple[list[str], list[str]]:
    """
    Apply smart dedup logic. Returns (urls_to_submit, urls_added_to_pending).

    Priority order:
      1. Pending queue from previous runs (quota skipped) — submitted first
      2. New URLs not in history
      3. URLs last submitted more than skip_hours ago (if force=False)
    """
    log.info("[DEDUP] ── Deduplication & Prioritisation ──────────────────────────")

    pending_queue = history.get_pending()
    log.info("[DEDUP] Pending queue from previous runs: %d URL(s)", len(pending_queue))
    if pending_queue:
        for u in pending_queue:
            log.info("[DEDUP]   [PENDING] %s", u)

    if force:
        log.info("[DEDUP] --force mode: skipping history checks, submitting all %d URL(s)", len(urls))
        report.set_dedup(len(urls), 0, len(pending_queue), len(urls), True, skip_hours)
        return urls[:limit], []

    if pending_only:
        if not pending_queue:
            log.info("[DEDUP] --pending-only: queue is empty, nothing to submit")
            report.set_dedup(0, 0, 0, 0, False, skip_hours)
            return [], []
        log.info("[DEDUP] --pending-only mode: submitting %d queued URL(s) only", len(pending_queue))
        # Add any new URLs to pending for next time, plus any pending URLs exceeding the limit
        new_urls = [u for u in urls if u not in pending_queue]
        if len(pending_queue) > limit:
            new_urls.extend(pending_queue[limit:])
        if new_urls:
            log.info("[DEDUP]   Also found %d new/over-limit URL(s) — added to pending for next run", len(new_urls))
        report.set_dedup(len(urls), 0, len(pending_queue), len(pending_queue[:limit]), False, skip_hours)
        return pending_queue[:limit], new_urls

    # Normal mode: new discovered URLs get top priority, then fill quota limit from pending queue
    to_submit     = []
    skipped_urls  = []
    skipped_count = 0

    # 1. Newly discovered URLs from this run get top priority
    for url in urls:
        if len(to_submit) >= limit:
            break

        if history.was_submitted_within(url, skip_hours):
            last = history.get_last_submitted_at(url)
            log.info("[DEDUP] SKIP (submitted %sh ago): %s",
                     skip_hours, url)
            log.debug("[DEDUP]       last submitted: %s", last[:19])
            report.add_submission(url, classify_url(url), 0, False,
                                  skipped=True,
                                  skip_reason=f"submitted within last {skip_hours}h",
                                  last_submitted=last)
            skipped_count += 1
            skipped_urls.append(url)
        else:
            to_submit.append(url)

    # 2. Fill remaining quota capacity from pending backlog queue
    for url in pending_queue:
        if len(to_submit) >= limit:
            break
        if url not in to_submit and url not in skipped_urls:
            to_submit.append(url)

    log.info("[DEDUP] Skipped (submitted within %dh) : %d URL(s)", skip_hours, skipped_count)
    log.info("[DEDUP] Pending queue loaded            : %d URL(s)", len(pending_queue))
    log.info("[DEDUP] Queued for submission           : %d URL(s)", len(to_submit))

    # URLs beyond limit go to pending
    over_limit = [u for u in urls if u not in to_submit and u not in skipped_urls]
    report.set_dedup(len(urls), skipped_count, len(pending_queue), len(to_submit), False, skip_hours)
    return to_submit, over_limit


# ─────────────────────────────────────────────────────────────────────────────
# GOOGLE INDEXING API SUBMISSION
# ─────────────────────────────────────────────────────────────────────────────

def submit_urls_batch(urls: list[str], token: str,
                      history: SubmissionHistory,
                      log: logging.Logger, report: RunReport,
                      dry_run: bool = False) -> dict:

    if not urls:
        log.warning("[SUBMIT] No URLs to submit.")
        return {"total": 0, "submitted": 0, "success": 0, "failed": 0,
                "skipped": 0, "quota_exhausted": False, "not_submitted": []}

    total     = len(urls)
    submitted = 0
    success   = 0
    failed    = 0
    quota_hit = False
    not_submitted = []   # URLs quota-stopped before we got to them

    log.info("[SUBMIT] ══════════════════════════════════════════════════════════")
    log.info("[SUBMIT] Starting submission of %d URL(s)...", total)
    log.info("[SUBMIT] Mode: %s", "DRY-RUN (no API calls)" if dry_run else "LIVE (URL_UPDATED)")
    log.info("[SUBMIT] ══════════════════════════════════════════════════════════")

    for i, url in enumerate(urls, 1):
        url_type = classify_url(url)
        prefix   = f"[SUBMIT] [{i:>3}/{total}] [{url_type:>10}]"

        if dry_run:
            log.info("%s [DRY-RUN] %s", prefix, url)
            report.add_submission(url, url_type, 0, True, dry_run=True)
            history.mark_submitted(url)
            submitted += 1
            success   += 1
            continue

        try:
            resp   = requests.post(
                INDEXING_ENDPOINT,
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
                notify_time = meta.get("latestUpdate", {}).get("notifyTime", "")
                log.info("%s OK  %s", prefix, url)
                if notify_time:
                    log.info("[SUBMIT]              Google notifyTime: %s", notify_time)
                report.add_submission(url, url_type, status, True,
                                      notify_time=notify_time)
                history.mark_submitted(url)
                success += 1

            elif status == 429:
                err = body.get("error", {}).get("message", "Quota exceeded")
                log.warning("%s QUOTA EXCEEDED: %s", prefix, err)
                log.warning("[SUBMIT]   Daily limit (200/day) reached — stopping early")
                log.warning("[SUBMIT]   Remaining %d URL(s) added to pending queue",
                          total - (submitted - 1))
                report.add_submission(url, url_type, status, False, error=err, skip_reason="quota_exceeded")
                quota_hit = True
                # Add remaining URLs (including this one) to pending without incrementing failed count
                not_submitted.extend(urls[i - 1:])
                break

            elif status == 403:
                err = body.get("error", {}).get("message", "Permission denied")
                log.error("%s 403 PERMISSION DENIED: %s", prefix, err)
                log.error("[SUBMIT]   Service account is NOT added as Owner in GSC")
                log.error("[SUBMIT]   See GOOGLE_INDEXING_SETUP.md — Step 4")
                report.add_submission(url, url_type, status, False, error=err)
                not_submitted.extend(urls[i - 1:])
                failed += 1
                break

            elif status == 400:
                err = body.get("error", {}).get("message", str(body))[:200]
                log.warning("%s 400 BAD REQUEST: %s", prefix, err)
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

        time.sleep(0.15)  # polite rate limiting

    return {
        "total":           total,
        "submitted":       submitted,
        "success":         success,
        "failed":          failed,
        "skipped":         0,
        "quota_exhausted": quota_hit,
        "not_submitted":   not_submitted,
    }


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def run(days: int = 1, include_products: bool = False,
        include_collections: bool = False,
        dry_run: bool = False, force: bool = False,
        pending_only: bool = False,
        skip_hours: int = 48, limit: int = 200):

    run_ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_base = Path(f"google_indexing_{run_ts}")
    report   = RunReport(log_base.with_suffix(".json"))
    log      = setup_logger(log_base)
    history  = SubmissionHistory()

    # ── banner ─────────────────────────────────────────────────────────────
    log.info("=" * 65)
    log.info("  MeeeShop Google Indexing API — %s",
             datetime.now().strftime("%Y-%m-%d %H:%M UTC"))
    log.info("  Store         : %s", SHOP)
    log.info("  Store URL     : %s", STORE_URL)
    log.info("  Lookback      : last %d day(s)", days)
    log.info("  Products      : %s", include_products)
    log.info("  Collections   : %s", include_collections)
    log.info("  Dry-run       : %s", dry_run)
    log.info("  Force         : %s", force)
    log.info("  Pending-only  : %s", pending_only)
    log.info("  Skip if < %dh : yes", skip_hours)
    log.info("  URL limit     : %d (Google quota: 200/day)", limit)
    log.info("=" * 65)

    # ── history stats ──────────────────────────────────────────────────────
    h_stats = history.summary()
    log.info("[HISTORY] Submission history loaded:")
    log.info("[HISTORY]   ever submitted   : %d URLs", h_stats["total_ever_submitted"])
    log.info("[HISTORY]   pending queue    : %d URLs (quota-skipped from prev runs)",
             h_stats["pending_count"])
    log.info("[HISTORY]   last run at      : %s", h_stats["last_run_at"])
    log.info("[HISTORY]   history file     : %s", h_stats["history_file"])
    report.set_history_stats(h_stats)

    # ── authenticate ───────────────────────────────────────────────────────
    if dry_run:
        log.info("[AUTH] DRY-RUN — skipping OAuth2 authentication")
        report.set_auth(True, "dry-run", dry_run=True)
        token = "DRY_RUN_TOKEN"
    else:
        sa_key = load_sa_key(log)
        token  = get_access_token(sa_key, log, report)

    # ── discover URLs ──────────────────────────────────────────────────────
    log.info("-" * 65)
    all_urls = []

    articles  = fetch_recent_articles(days, log, report)
    blog_urls = [build_article_url(a) for a in articles]
    all_urls.extend(blog_urls)

    if include_products:
        log.info("-" * 65)
        all_urls.extend(fetch_products(log, report, limit=250))

    if include_collections:
        log.info("-" * 65)
        all_urls.extend(fetch_collections(log, report))

    # Deduplicate preserving order
    all_urls = list(dict.fromkeys(all_urls))
    log.info("-" * 65)
    log.info("[URLS] Total unique URLs discovered: %d", len(all_urls))

    # ── smart dedup + prioritisation ───────────────────────────────────────
    to_submit, over_limit = deduplicate(
        all_urls, history, log, report,
        force=force, skip_hours=skip_hours,
        pending_only=pending_only, limit=limit,
    )

    if not to_submit and not pending_only:
        log.info("[SUBMIT] Nothing to submit — all URLs already submitted within %dh", skip_hours)
        log.info("[SUBMIT] Use --force to resubmit everything, or --days N to look further back")

    # ── submit ─────────────────────────────────────────────────────────────
    log.info("-" * 65)
    result = submit_urls_batch(to_submit, token, history, log, report, dry_run=dry_run)

    # ── update pending queue ───────────────────────────────────────────────
    added_to_pending = []

    # Clear URLs from pending that were successfully submitted
    cleared_pending = [u for u in history.get_pending()
                       if u not in result["not_submitted"]]
    if cleared_pending:
        history.clear_pending()
        log.info("[PENDING] Cleared %d URL(s) from pending queue (now submitted)",
                 len(cleared_pending))

    # Add quota-skipped URLs to pending queue for next run
    quota_skipped = result.get("not_submitted", [])
    for url in quota_skipped:
        history.add_pending(url)
        added_to_pending.append(url)

    # Add over-limit URLs to pending
    for url in over_limit:
        history.add_pending(url)
        added_to_pending.append(url)

    if added_to_pending:
        log.info("[PENDING] Added %d URL(s) to pending queue for next run:",
                 len(added_to_pending))
        for u in added_to_pending[:10]:
            log.info("[PENDING]   + %s", u)
        if len(added_to_pending) > 10:
            log.info("[PENDING]   ... and %d more", len(added_to_pending) - 10)

    report.set_pending(added_to_pending, cleared_pending)

    # Save updated history
    history.save()
    log.info("[HISTORY] History saved (%d total URLs ever submitted, %d pending)",
             history.total_ever_submitted(), history.pending_count())

    # ── final summary ──────────────────────────────────────────────────────
    skipped_recent = sum(
        1 for s in report.data["submissions"]
        if s.get("skipped") and not s.get("dry_run")
    )

    log.info("=" * 65)
    log.info("[SUMMARY] Run complete")
    log.info("[SUMMARY]   URLs discovered          : %d", len(all_urls))
    log.info("[SUMMARY]   Skipped (< %2dh ago)     : %d", skip_hours, skipped_recent)
    log.info("[SUMMARY]   Submitted to Google      : %d", result["submitted"])
    log.info("[SUMMARY]   Successfully indexed     : %d", result["success"])
    log.info("[SUMMARY]   Failed                   : %d", result["failed"])
    log.info("[SUMMARY]   Added to pending queue   : %d", len(added_to_pending))
    log.info("[SUMMARY]   Pending queue total now  : %d", history.pending_count())
    log.info("[SUMMARY]   Google quota used today  : ~%d / 200", result["submitted"])
    log.info("[SUMMARY]   Google quota remaining   : ~%d", max(0, 200 - result["submitted"]))
    log.info("[SUMMARY]   History file             : %s", str(HISTORY_FILE))
    log.info("[SUMMARY]   JSON report              : %s", str(log_base.with_suffix('.json')))
    log.info("[SUMMARY]   Verify at                : https://search.google.com/search-console/")
    log.info("=" * 65)

    if added_to_pending:
        log.info("")
        log.info("[NEXT RUN] %d URL(s) queued for next run (quota backlog).", len(added_to_pending))
        log.info("[NEXT RUN] They will be submitted first automatically.")
        log.info("[NEXT RUN] Or run manually: python google_indexing.py --pending-only")

    report.set_summary(
        total=len(all_urls),
        submitted=result["submitted"],
        success=result["success"],
        failed=result["failed"],
        skipped_recent=skipped_recent,
        pending_loaded=len(history.get_pending()),
        added_to_pending=len(added_to_pending),
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
        description="Submit Shopify URLs to Google Indexing API with smart dedup + pending queue",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
        Examples:
          python google_indexing.py                    # today's articles (skip if < 48h ago)
          python google_indexing.py --days 7           # last 7 days articles
          python google_indexing.py --products         # + all products
          python google_indexing.py --collections      # + all collections
          python google_indexing.py --pending-only     # only submit quota backlog
          python google_indexing.py --force            # resubmit ALL, ignore history
          python google_indexing.py --force --products --collections  # full force run
          python google_indexing.py --skip-hours 24   # skip if submitted < 24h ago
          python google_indexing.py --dry-run          # log only, no API calls
          python google_indexing.py --limit 150        # cap at 150 (leave quota buffer)
        """),
    )
    ap.add_argument("--days",         type=int,  default=1,
                    help="Lookback window in days for blog articles (default: 1)")
    ap.add_argument("--products",     action="store_true",
                    help="Also submit all published product pages")
    ap.add_argument("--collections",  action="store_true",
                    help="Also submit all published collection pages")
    ap.add_argument("--force",        action="store_true",
                    help="Ignore history — resubmit all URLs regardless of when last submitted")
    ap.add_argument("--pending-only", action="store_true",
                    help="Only submit URLs from the quota-skipped pending queue")
    ap.add_argument("--skip-hours",   type=int,  default=48,
                    help="Skip URLs submitted within this many hours (default: 48)")
    ap.add_argument("--dry-run",      action="store_true",
                    help="Log URLs without making any API calls to Google")
    ap.add_argument("--limit",        type=int,  default=200,
                    help="Max URLs per run (Google quota: 200/day, default: 200)")
    args = ap.parse_args()

    run(
        days=args.days,
        include_products=args.products,
        include_collections=args.collections,
        dry_run=args.dry_run,
        force=args.force,
        pending_only=args.pending_only,
        skip_hours=args.skip_hours,
        limit=args.limit,
    )

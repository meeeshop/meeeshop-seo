#!/usr/bin/env python3
"""
article_deduplicator.py — Shared article deduplication for MeeeShop blog workflows
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Prevents blog_daily.py and weekly_trend_blog.py from ever creating:
  - An article with the same TITLE as an existing live/draft article
  - An article with the same URL HANDLE as an existing article
  - The same product being featured again in the same format within a cooldown window

STRATEGY:
  1. LiveIndex   — fetches all existing article handles+titles from Shopify once per run
  2. TitleCache  — normalised title fingerprints (strips punctuation, lowercase, year-agnostic)
  3. HandleCache — exact handle set
  4. ProductFormatCache — (product_handle, format) seen within PRODUCT_FORMAT_COOLDOWN days
  5. Suffix      — if a generated title/handle collides, appends a date-based suffix to make it unique

Usage:
    from article_deduplicator import ArticleDeduplicator

    dedup = ArticleDeduplicator(base_url, shopify_headers)
    dedup.load_live_index()          # call once at run start

    # Before publishing:
    title, handle = dedup.make_unique(title, handle)  # returns unique pair

    # After publishing (so the same run can't duplicate itself):
    dedup.register(title, handle)
"""

import re
import json
import time
import requests
from datetime import datetime, timedelta
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
# Number of days before the same (product_handle × format) combo is allowed again
PRODUCT_FORMAT_COOLDOWN_DAYS = 30


class ArticleDeduplicator:
    """
    Thread-safe (within a single process) deduplication engine.

    Parameters
    ----------
    base_url : str
        Shopify Admin API base URL, e.g. "https://store.myshopify.com/admin/api/2024-10"
    headers  : dict
        Shopify request headers (must include X-Shopify-Access-Token)
    history_path : Path | None
        Path to the JSON file that tracks (product_handle × format) cooldowns.
        Defaults to <script_dir>/../article_publish_history.json
    """

    def __init__(self, base_url: str, headers: dict, history_path: Path | None = None):
        self.base_url   = base_url.rstrip("/")
        self.headers    = headers
        self._titles: set[str]  = set()   # normalised title fingerprints from live store
        self._handles: set[str] = set()   # exact handles from live store
        self._registered_titles: set[str]  = set()  # added during this run
        self._registered_handles: set[str] = set()  # added during this run

        if history_path is None:
            here = Path(__file__).resolve().parent
            history_path = here.parent / "article_publish_history.json"
        self.history_path = history_path
        self._history: dict = {}   # {f"{product_handle}::{format}": "YYYY-MM-DD"}

    # ── Fingerprinting ─────────────────────────────────────────────────────────
    @staticmethod
    def _fingerprint(title: str) -> str:
        """
        Normalise a title for fuzzy comparison:
        - lowercase
        - remove punctuation
        - collapse whitespace
        - strip years (e.g. 2024/2025/2026) so same topic with different year still matches
        """
        t = title.lower()
        t = re.sub(r"\b20\d\d\b", "", t)        # strip years
        t = re.sub(r"[^\w\s]", " ", t)           # remove punctuation
        t = re.sub(r"\s+", " ", t).strip()       # collapse whitespace
        return t

    @staticmethod
    def _to_handle(text: str) -> str:
        """Convert a title/string to a Shopify-style url slug."""
        t = text.lower()
        t = re.sub(r"[^\w\s-]", "", t)
        t = re.sub(r"[\s_]+", "-", t)
        t = re.sub(r"-+", "-", t)
        return t.strip("-")[:80]

    def _get(self, url: str, params: dict = None) -> requests.Response:
        """Robust GET request with exponential backoff on HTTP 429 rate limits."""
        for attempt in range(5):
            try:
                r = requests.get(url, headers=self.headers, params=params, timeout=25)
                if r.status_code == 429:
                    wait = int(float(r.headers.get("Retry-After", 4))) + (2 ** attempt)
                    print(f"  [Dedup] Rate limited (429) on {url} — waiting {wait}s…")
                    time.sleep(wait)
                    continue
                r.raise_for_status()
                return r
            except Exception as e:
                time.sleep(3 * (attempt + 1))
        raise RuntimeError(f"GET {url} failed after 5 attempts")

    # ── Live index loader ──────────────────────────────────────────────────────
    def load_live_index(self, verbose: bool = True) -> int:
        """
        Fetch ALL article titles+handles from every blog on the live store.
        Returns the total number of articles indexed.
        """
        if verbose:
            print("[Dedup] Loading live article index from Shopify…")

        # Fetch all blogs first
        try:
            r = self._get(f"{self.base_url}/blogs.json")
            blogs = r.json().get("blogs", [])
        except Exception as e:
            print(f"  [Dedup] Warning — could not load blogs: {e}")
            return 0

        total = 0
        for blog in blogs:
            blog_id    = blog["id"]
            blog_title = blog.get("title", blog_id)
            page_info  = None
            while True:
                params: dict = {"limit": 250, "fields": "id,title,handle,published_at"}
                if page_info:
                    params["page_info"] = page_info
                try:
                    r = self._get(f"{self.base_url}/blogs/{blog_id}/articles.json", params=params)
                    articles = r.json().get("articles", [])
                except Exception as e:
                    print(f"  [Dedup] Warning — could not load articles for blog '{blog_title}': {e}")
                    break

                for art in articles:
                    self._titles.add(self._fingerprint(art.get("title", "")))
                    h = art.get("handle", "")
                    if h:
                        self._handles.add(h.lower())
                total += len(articles)

                link_hdr = r.headers.get("Link", "")
                nxt = re.search(r'<([^>]+)>;\s*rel="next"', link_hdr)
                if nxt and len(articles) == 250:
                    pi = re.search(r"page_info=([^&]+)", nxt.group(1))
                    page_info = pi.group(1) if pi else None
                    if not page_info:
                        break
                else:
                    break

        if verbose:
            print(f"  [Dedup] Indexed {total} articles "
                  f"({len(self._handles)} handles, {len(self._titles)} unique fingerprints)")
        self._load_history()
        return total

    # ── History (product × format cooldown) ───────────────────────────────────
    def _load_history(self):
        """Load the product×format cooldown history from disk."""
        if self.history_path.exists():
            try:
                with open(self.history_path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                    if isinstance(raw, dict):
                        self._history = raw
            except Exception as e:
                print(f"  [Dedup] Warning loading history: {e}")
                self._history = {}

    def _save_history(self):
        """Persist the product×format cooldown history to disk."""
        try:
            self.history_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.history_path, "w", encoding="utf-8") as f:
                json.dump(self._history, f, indent=2)
        except Exception as e:
            print(f"  [Dedup] Warning saving history: {e}")

    def _clean_history(self):
        """Remove history entries older than PRODUCT_FORMAT_COOLDOWN_DAYS."""
        cutoff = datetime.now() - timedelta(days=PRODUCT_FORMAT_COOLDOWN_DAYS)
        self._history = {
            k: v for k, v in self._history.items()
            if datetime.strptime(v, "%Y-%m-%d") >= cutoff
        }

    def check_product_format_cooldown(self, product_handle: str, article_format: str) -> bool:
        """
        Returns True if this (product_handle × format) combo is within cooldown period
        (i.e. has been published recently and should be SKIPPED).
        """
        key = f"{product_handle}::{article_format}"
        if key not in self._history:
            return False
        try:
            last_date = datetime.strptime(self._history[key], "%Y-%m-%d")
            return (datetime.now() - last_date).days < PRODUCT_FORMAT_COOLDOWN_DAYS
        except Exception:
            return False

    def record_product_format(self, product_handle: str, article_format: str, dry_run: bool = False):
        """Record that this (product_handle × format) was published today."""
        if dry_run:
            return
        key = f"{product_handle}::{article_format}"
        self._history[key] = datetime.now().strftime("%Y-%m-%d")
        self._clean_history()
        self._save_history()

    # ── Title / handle uniqueness ──────────────────────────────────────────────
    def is_duplicate_title(self, title: str) -> bool:
        """Return True if a normalised version of this title is already indexed."""
        fp = self._fingerprint(title)
        return fp in self._titles or fp in self._registered_titles

    def is_duplicate_handle(self, handle: str) -> bool:
        """Return True if this handle already exists on the live store or this run."""
        h = handle.lower()
        return h in self._handles or h in self._registered_handles

    def make_unique_handle(self, handle: str) -> str:
        """
        If the handle collides, append a date suffix and increment until unique.
        e.g.  "style-guide-jeans"  →  "style-guide-jeans-jul-2026"
               (if that also collides) →  "style-guide-jeans-jul-2026-2"
        """
        date_suffix = datetime.now().strftime("%b-%Y").lower()
        base = self._to_handle(handle)
        candidate = f"{base}-{date_suffix}"
        counter = 2
        while self.is_duplicate_handle(candidate):
            candidate = f"{base}-{date_suffix}-{counter}"
            counter += 1
            if counter > 99:
                # Safety valve: timestamp
                candidate = f"{base}-{int(time.time())}"
                break
        return candidate

    def make_unique_title(self, title: str) -> str:
        """
        If the title fingerprint collides, append a formatted month-year.
        e.g.  "How to Style Jeans"  →  "How to Style Jeans — July 2026"
               (if collides)         →  "How to Style Jeans — July 2026 (2)"
        """
        if not self.is_duplicate_title(title):
            return title
        date_label = datetime.now().strftime("%B %Y")
        candidate  = f"{title} — {date_label}"
        counter    = 2
        while self.is_duplicate_title(candidate):
            candidate = f"{title} — {date_label} ({counter})"
            counter  += 1
            if counter > 99:
                candidate = f"{title} — {int(time.time())}"
                break
        return candidate

    def make_unique(self, title: str, handle: str) -> tuple[str, str]:
        """
        One-stop call: returns a (title, handle) pair guaranteed to be unique.
        Also ensures the handle is derived from the (possibly modified) title.
        """
        unique_title  = self.make_unique_title(title)
        # If title changed, re-derive the handle from the new title
        if unique_title != title:
            base_handle = self._to_handle(unique_title)
        else:
            base_handle = handle or self._to_handle(title)

        unique_handle = self.make_unique_handle(base_handle)
        return unique_title, unique_handle

    def register(self, title: str, handle: str):
        """
        Mark a title+handle as used (called AFTER publishing so subsequent
        articles in the same run don't collide with it).
        """
        self._registered_titles.add(self._fingerprint(title))
        self._registered_handles.add(handle.lower())

    # ── Convenience: full pre-publish check ───────────────────────────────────
    def resolve(
        self,
        title: str,
        handle: str,
        product_handle: str | None = None,
        article_format: str | None = None,
        dry_run: bool = False,
    ) -> tuple[str, str] | None:
        """
        Full pre-publish resolution:
          1. Check product×format cooldown → return None if should skip
          2. Make title and handle unique
          3. Log the decision

        Returns (unique_title, unique_handle) or None if article should be skipped.
        """
        # 1. Product×format cooldown
        if product_handle and article_format:
            if self.check_product_format_cooldown(product_handle, article_format):
                print(f"  [Dedup] SKIP — '{product_handle}' × '{article_format}' "
                      f"published within last {PRODUCT_FORMAT_COOLDOWN_DAYS} days")
                return None

        # 2. Make unique
        orig_title, orig_handle = title, handle
        unique_title, unique_handle = self.make_unique(title, handle)

        if unique_title != orig_title:
            print(f"  [Dedup] Title collision — renamed:")
            print(f"          '{orig_title}'")
            print(f"       →  '{unique_title}'")
        if unique_handle != orig_handle:
            print(f"  [Dedup] Handle collision — renamed:")
            print(f"          '{orig_handle}'")
            print(f"       →  '{unique_handle}'")
        if unique_title == orig_title and unique_handle == orig_handle:
            print(f"  [Dedup] OK — title and handle are unique")

        return unique_title, unique_handle

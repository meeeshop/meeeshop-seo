#!/usr/bin/env python3
"""
revert_injected_links.py — Strip all injected internal links from corrupted articles.

Removes all <a href="...meeeshop.com..."> tags injected by internal_linker.py,
restoring article body_html to clean text.

Usage:
  python revert_injected_links.py --dry-run    # Preview changes only
  python revert_injected_links.py --apply      # Actually revert articles
  python revert_injected_links.py --apply --all  # All articles (not just known affected)
"""

import os, sys, re, argparse, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from secrets_manager import inject_to_env, get_secret

inject_to_env()

import requests

STORE = get_secret("SHOPIFY_STORE")
TOKEN = get_secret("SHOPIFY_ACCESS_TOKEN")
HEADS = {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}
BASE  = f"https://{STORE}/admin/api/2024-01"
SITE  = "https://us.meeeshop.com"

# Shopify REST: 2 req/s burst, ~40 req/10s sustained
REQUEST_DELAY = 0.6   # seconds between GET requests
UPDATE_DELAY  = 1.0   # seconds between PUT requests (writes are more expensive)
MAX_RETRIES   = 5


def _request(method: str, url: str, **kwargs) -> requests.Response:
    """Make a request with automatic 429/5xx retry + exponential backoff."""
    for attempt in range(MAX_RETRIES):
        r = requests.request(method, url, headers=HEADS, **kwargs)
        if r.status_code == 429:
            retry_after = int(r.headers.get("Retry-After", 4))
            wait = max(retry_after, 2 ** attempt)
            print(f"  [RATE LIMIT] 429 — waiting {wait}s before retry {attempt+1}/{MAX_RETRIES}...")
            time.sleep(wait)
            continue
        if r.status_code >= 500:
            wait = 2 ** attempt
            print(f"  [SERVER ERROR] {r.status_code} — waiting {wait}s before retry {attempt+1}/{MAX_RETRIES}...")
            time.sleep(wait)
            continue
        return r
    r.raise_for_status()
    return r


# Articles known to be corrupted (from the run log)
AFFECTED_TITLES = [
    "How to Style 2026's Boldest Dress Colors for Any Occasion",
    "How to Build a Capsule Wardrobe Women Will Love in 2026: Finding the Perfect Dress for Every Occasion",
    "5 Stunning Outfits You Can Build Around Asymmetrical Ruffle Mini Dress for Women in 2026 (I Wore All 5 This Month)",
    "The Best Dresses for Women in 2026: Our Editor's Guide",
    "The Ultimate 2026 Dress Guide for Fall Office Parties",
    "Affordable Jeans That Look Expensive: Must-Haves This Fall",
    "Women's Spring Outfit Ideas 2026: Building a Versatile Wardrobe on a Budget with MeeeShop",
]


def strip_meeeshop_links(html: str) -> tuple[str, int]:
    """
    Remove all <a href="...meeeshop..."> tags, keeping the inner text intact.
    Returns (cleaned_html, count_removed).
    """
    count = [0]

    def remove_link(m):
        href = m.group(1)
        inner = m.group(2)
        if "meeeshop.com" in href or "us.meeeshop" in href:
            count[0] += 1
            return inner  # Keep anchor text, drop the <a> tag
        return m.group(0)  # Not a meeeshop link — leave it alone

    # Match <a href="...">...</a> — handles single/double quotes and extra attrs
    pattern = r'<a\s[^>]*href=["\']([^"\']*)["\'][^>]*>(.*?)</a>'
    cleaned = re.sub(pattern, remove_link, html, flags=re.IGNORECASE | re.DOTALL)
    return cleaned, count[0]


def fetch_all_blogs():
    blogs = []
    url = f"{BASE}/blogs.json?limit=250"
    while url:
        r = _request("GET", url)
        r.raise_for_status()
        data = r.json()
        blogs.extend(data.get("blogs", []))
        link = r.headers.get("Link", "")
        url = None
        for part in link.split(","):
            if 'rel="next"' in part:
                url = part.split("<")[1].split(">")[0]
        time.sleep(REQUEST_DELAY)
    return blogs


def fetch_articles(blog_id: int):
    articles = []
    url = f"{BASE}/blogs/{blog_id}/articles.json?limit=250"
    while url:
        r = _request("GET", url)
        r.raise_for_status()
        data = r.json()
        articles.extend(data.get("articles", []))
        link = r.headers.get("Link", "")
        url = None
        for part in link.split(","):
            if 'rel="next"' in part:
                url = part.split("<")[1].split(">")[0]
        time.sleep(REQUEST_DELAY)
    return articles


def update_article(blog_id: int, article_id: int, body_html: str) -> bool:
    url = f"{BASE}/blogs/{blog_id}/articles/{article_id}.json"
    payload = {"article": {"id": article_id, "body_html": body_html}}
    r = _request("PUT", url, json=payload)
    time.sleep(UPDATE_DELAY)
    return r.status_code == 200


def main():
    parser = argparse.ArgumentParser(description="Revert injected internal links from corrupted articles")
    parser.add_argument("--dry-run", action="store_true", help="Preview without modifying Shopify")
    parser.add_argument("--apply", action="store_true", help="Actually revert articles")
    parser.add_argument("--all", action="store_true", help="Process ALL articles (not just known affected ones)")
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        print("Specify --dry-run or --apply")
        sys.exit(1)

    print(f"Mode: {'DRY RUN' if args.dry_run else 'APPLY'}")
    print(f"Scope: {'ALL articles' if args.all else f'{len(AFFECTED_TITLES)} known affected articles'}")
    print("=" * 70)

    blogs = fetch_all_blogs()
    total_reverted = 0
    total_failed = 0
    total_links_removed = 0

    for blog in blogs:
        blog_id = blog["id"]
        blog_title = blog.get("title", "")
        articles = fetch_articles(blog_id)

        for article in articles:
            title = article.get("title", "")
            body_html = article.get("body_html", "")
            article_id = article["id"]

            # Filter to known affected articles unless --all
            if not args.all and title not in AFFECTED_TITLES:
                continue

            if not body_html:
                continue

            cleaned_html, removed_count = strip_meeeshop_links(body_html)

            if removed_count == 0:
                if title in AFFECTED_TITLES:
                    print(f"  [SKIP] '{title}' — no meeeshop links found (already clean)")
                continue

            print(f"\n[{blog_title}] '{title}'")
            print(f"  Links to remove: {removed_count}")

            if args.apply:
                success = update_article(blog_id, article_id, cleaned_html)
                if success:
                    print(f"  ✓ Reverted ({removed_count} links removed)")
                    total_reverted += 1
                    total_links_removed += removed_count
                else:
                    print(f"  ✗ Failed to update article via API")
                    total_failed += 1
            else:
                print(f"  [DRY RUN] Would remove {removed_count} links")
                total_links_removed += removed_count

    print("\n" + "=" * 70)
    print(f"SUMMARY:")
    print(f"  Articles {'reverted' if args.apply else 'to revert'}: {total_reverted if args.apply else 'N/A (dry-run)'}")
    if args.apply and total_failed > 0:
        print(f"  Articles FAILED: {total_failed} (re-run script to retry)")
    print(f"  Total links {'removed' if args.apply else 'found'}: {total_links_removed}")
    print("=" * 70)

    if args.apply and total_failed > 0:
        sys.exit(1)  # Non-zero exit so workflow shows failure and can be retried


if __name__ == "__main__":
    main()

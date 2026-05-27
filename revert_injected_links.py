#!/usr/bin/env python3
"""
revert_injected_links.py — Restore corrupted articles by recreating them with fresh AI content.

For each article that contains injected meeeshop links, the script:
  1. Generates fresh AI content (before touching anything)
  2. Deletes the corrupted article
  3. Re-publishes with the same title + handle so the URL stays identical

Usage:
  python revert_injected_links.py --dry-run        # Preview only, no changes
  python revert_injected_links.py --apply          # Fix known corrupted articles
  python revert_injected_links.py --apply --all    # Fix ALL articles that contain meeeshop links
"""

import os, sys, re, time, argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from secrets_manager import inject_to_env, get_secret

inject_to_env()

import requests
import ai_client

STORE     = get_secret("SHOPIFY_STORE")
TOKEN     = get_secret("SHOPIFY_ACCESS_TOKEN")
HEADS     = {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}
BASE      = f"https://{STORE}/admin/api/2024-01"
STORE_URL = get_secret("STORE_BASE_URL") or f"https://{STORE}"

REQUEST_DELAY = 0.7
MAX_RETRIES   = 5

# Known corrupted articles — targeted fix without scanning everything
AFFECTED_TITLES = [
    "How to Style 2026's Boldest Dress Colors for Any Occasion",
    "How to Build a Capsule Wardrobe Women Will Love in 2026: Finding the Perfect Dress for Every Occasion",
    "5 Stunning Outfits You Can Build Around Asymmetrical Ruffle Mini Dress for Women in 2026 (I Wore All 5 This Month)",
    "The Best Dresses for Women in 2026: Our Editor's Guide",
    "The Ultimate 2026 Dress Guide for Fall Office Parties",
    "Affordable Jeans That Look Expensive: Must-Haves This Fall",
    "Women's Spring Outfit Ideas 2026: Building a Versatile Wardrobe on a Budget with MeeeShop",
    "Everything About Sizing & Measurements",
    "The Most Flattering Skirts for Curvy Women: Style Tips You Need",
    "Finding the Perfect Fit: Tips for Choosing the Right Size in Curvy Plus-Size Clothing",
    "Curvy Women's Jeans: Finding the Perfect Fit for Every Body",
    "Essential Tips For Plus Size Women Clothing.",
    "Trendy Plus Size Clothing",
    "Women Plus Size Outerwear",
    "Women's Fashion | New Styles that Make it your Wardrobe",
]


def _req(method: str, url: str, **kwargs) -> requests.Response:
    for attempt in range(MAX_RETRIES):
        r = requests.request(method, url, headers=HEADS, **kwargs)
        if r.status_code == 429:
            wait = max(int(r.headers.get("Retry-After", 4)), 2 ** attempt)
            print(f"  [RATE LIMIT] waiting {wait}s...")
            time.sleep(wait)
            continue
        if r.status_code >= 500:
            wait = 2 ** attempt
            print(f"  [SERVER ERROR] {r.status_code} — waiting {wait}s...")
            time.sleep(wait)
            continue
        return r
    r.raise_for_status()
    return r


def _has_injected_links(html: str) -> bool:
    return bool(re.search(r'<a\s[^>]*href=["\'][^"\']*meeeshop', html, re.IGNORECASE))


def fetch_all_blogs() -> list:
    r = _req("GET", f"{BASE}/blogs.json?limit=250")
    r.raise_for_status()
    time.sleep(REQUEST_DELAY)
    return r.json().get("blogs", [])


def fetch_articles(blog_id: int) -> list:
    articles = []
    url = f"{BASE}/blogs/{blog_id}/articles.json?limit=250"
    while url:
        r = _req("GET", url)
        r.raise_for_status()
        articles.extend(r.json().get("articles", []))
        link = r.headers.get("Link", "")
        url = None
        for part in link.split(","):
            if 'rel="next"' in part:
                url = part.split("<")[1].split(">")[0]
        time.sleep(REQUEST_DELAY)
    return articles


def delete_article(blog_id: int, article_id: int) -> bool:
    r = _req("DELETE", f"{BASE}/blogs/{blog_id}/articles/{article_id}.json")
    time.sleep(REQUEST_DELAY)
    return r.status_code == 200


def publish_article(blog_id: int, title: str, body_html: str, handle: str,
                    summary_html: str, tags: str) -> dict | None:
    payload = {
        "article": {
            "title":        title,
            "body_html":    body_html,
            "summary_html": summary_html,
            "tags":         tags,
            "published":    True,
            "handle":       handle,  # Same handle = same URL
        }
    }
    r = _req("POST", f"{BASE}/blogs/{blog_id}/articles.json", json=payload)
    time.sleep(REQUEST_DELAY)
    if r.status_code in (200, 201):
        return r.json().get("article", {})
    print(f"  [PUBLISH FAILED] {r.status_code}: {r.text[:300]}")
    return None


def _guess_keyword(title: str) -> str:
    stops = {"how", "to", "a", "an", "the", "for", "of", "in", "with", "your",
             "and", "or", "is", "are", "what", "tips", "guide", "best", "top",
             "about", "every", "finding", "perfect", "right", "our", "will",
             "new", "make", "styles", "that", "its", "from", "you", "its",
             "size", "plus"}
    words = [w for w in re.sub(r"[^a-zA-Z0-9 ]", " ", title).lower().split()
             if w not in stops and len(w) > 3]
    return " ".join(words[:5]) or "women's fashion"


def generate_content(title: str) -> tuple[str, str]:
    """Returns (body_html, summary_html)."""
    from datetime import datetime
    year  = datetime.now().year
    month = datetime.now().strftime("%B %Y")
    kw    = _guess_keyword(title)

    prompt = (
        f"You are a fashion editor at MeeeShop, a USA women's clothing boutique.\n"
        f"Write a {month} blog post titled: \"{title}\"\n"
        f"Target keyword: '{kw}'\n\n"
        f"Requirements:\n"
        f"- 650-850 words, helpful and specific women's fashion content\n"
        f"- First-person voice ('I', 'we', 'our customers tell us')\n"
        f"- Include personal experience and specific styling tips\n"
        f"- Mention free US shipping on orders $50+, easy 7-day returns, sizes XS-3X\n"
        f"- Use keyword '{kw}' 3-4 times naturally\n"
        f"- Mention the year {year} at least once\n"
        f"- Link to {STORE_URL} at least once with natural anchor text\n"
        f"- Do NOT inject links to individual product pages or category URLs\n"
        f"- Output ONLY clean HTML: <h1>, <h2>, <p>, <ul>, <li> — no markdown fences\n"
        f"- Sound warm and direct, not robotic\n"
    )

    raw = ai_client.generate(prompt, max_tokens=1400, temperature=0.7)

    if raw:
        raw = raw.strip()
        raw = re.sub(r"^```html?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw).strip()
        body = raw
    else:
        body = (
            f"<h1>{title}</h1>"
            f"<p>Our fashion editors are refreshing this guide with the latest tips for {kw} in {year}. "
            f"Explore our full collection at <a href='{STORE_URL}'>MeeeShop</a> — "
            f"free US shipping on orders $50+, sizes XS–3X.</p>"
        )

    # Extract first <p> text as summary
    m = re.search(r"<p[^>]*>(.*?)</p>", body, re.DOTALL | re.IGNORECASE)
    summary = f"<p>{re.sub(r'<[^>]+>', '', m.group(1)).strip()[:200]}</p>" if m else ""

    return body, summary


def main():
    parser = argparse.ArgumentParser(description="Restore corrupted articles by recreating with fresh AI content")
    parser.add_argument("--dry-run", action="store_true", help="Preview without changes")
    parser.add_argument("--apply",   action="store_true", help="Delete + recreate articles")
    parser.add_argument("--all",     action="store_true", help="Scan ALL articles (not just known list)")
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        print("Specify --dry-run or --apply")
        sys.exit(1)

    scope = "ALL articles with meeeshop links" if args.all else f"{len(AFFECTED_TITLES)} known affected articles"
    print(f"Mode:  {'DRY RUN' if args.dry_run else 'APPLY'}")
    print(f"Scope: {scope}")
    print("=" * 70)

    blogs      = fetch_all_blogs()
    total_ok   = 0
    total_fail = 0

    for blog in blogs:
        blog_id    = blog["id"]
        blog_title = blog.get("title", "")
        articles   = fetch_articles(blog_id)

        for article in articles:
            title      = article.get("title", "")
            body_html  = article.get("body_html", "") or ""
            article_id = article["id"]
            handle     = article.get("handle", "")
            summary    = article.get("summary_html", "") or ""
            tags       = article.get("tags", "") or ""

            # Scope filter
            if args.all:
                if not _has_injected_links(body_html):
                    continue
            else:
                if title not in AFFECTED_TITLES:
                    continue
                if not _has_injected_links(body_html):
                    print(f"  [SKIP] '{title}' — no meeeshop links found (already clean)")
                    continue

            print(f"\n[{blog_title}] '{title}'")
            print(f"  Handle: {handle}")

            if args.dry_run:
                kw = _guess_keyword(title)
                print(f"  [DRY RUN] Would recreate with keyword: '{kw}'")
                continue

            # 1. Generate fresh content BEFORE deleting
            print(f"  Generating fresh content...")
            new_body, new_summary = generate_content(title)
            print(f"  Generated {len(new_body)} chars")

            # 2. Delete corrupted article
            if not delete_article(blog_id, article_id):
                print(f"  [FAIL] Could not delete — skipping")
                total_fail += 1
                continue
            print(f"  Deleted (ID {article_id})")

            # 3. Re-publish with same handle
            new_art = publish_article(blog_id, title, new_body, handle, new_summary, tags)
            if new_art:
                print(f"  ✓ Recreated (new ID {new_art.get('id')}) — URL preserved")
                total_ok += 1
            else:
                print(f"  ✗ Re-publish failed — '{title}' is deleted but not restored!")
                total_fail += 1

    print("\n" + "=" * 70)
    print(f"SUMMARY: recreated={total_ok}  failed={total_fail}")
    print("=" * 70)

    if total_fail > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()

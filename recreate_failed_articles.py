#!/usr/bin/env python3
"""
recreate_failed_articles.py — Delete corrupted articles and re-publish with fresh AI content.

Used as a fallback when revert_injected_links.py fails to update an article via the API.
Keeps the same title (and thus the same URL handle) so no links are broken.

Usage:
  python recreate_failed_articles.py --dry-run    # Preview — no changes made
  python recreate_failed_articles.py --apply      # Delete + recreate each article
"""

import os, sys, re, time, random, argparse

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

REQUEST_DELAY = 0.8
MAX_RETRIES   = 5

# Articles that failed to revert (from revert_injected_links.py failures)
FAILED_ARTICLES = [
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


def _guess_keyword(title: str) -> str:
    """Extract a search keyword from the article title for AI prompt."""
    # Strip punctuation, lowercase
    t = re.sub(r"[^a-zA-Z0-9 ]", " ", title).lower()
    # Remove common stop words
    stops = {"how", "to", "a", "an", "the", "for", "of", "in", "with", "your",
             "and", "or", "is", "are", "what", "tips", "guide", "best", "top",
             "about", "every", "finding", "perfect", "right", "our", "will",
             "new", "make", "styles", "that", "its", "from", "you"}
    words = [w for w in t.split() if w not in stops and len(w) > 3]
    return " ".join(words[:5]) or "women's fashion"


def _build_ai_prompt(title: str, keyword: str) -> str:
    from datetime import datetime
    year = datetime.now().year
    return (
        f"You are a fashion editor at MeeeShop, a USA women's clothing boutique.\n"
        f"Rewrite the blog post titled: \"{title}\"\n"
        f"Target keyword: '{keyword}'\n"
        f"Store URL: {STORE_URL}\n\n"
        f"Requirements:\n"
        f"- 600-800 words of fresh, helpful women's fashion content\n"
        f"- Write as a first-person MeeeShop fashion editor ('I', 'we', 'our customers')\n"
        f"- Include personal experience, specific styling tips, body-type guidance\n"
        f"- Add trust signals: free US shipping on orders $50+, easy 7-day returns, sizes XS-3X\n"
        f"- Use keyword '{keyword}' 3-4 times naturally\n"
        f"- Mention the year {year} at least once\n"
        f"- Output ONLY clean HTML using <h1>, <h2>, <p>, <ul>, <li> tags\n"
        f"- Do NOT include meeeshop.com hyperlinks inside article text (product links are added separately)\n"
        f"- Sound warm, direct, and helpful — not robotic or AI-generated\n"
    )


def generate_content(title: str) -> str:
    keyword = _guess_keyword(title)
    prompt = _build_ai_prompt(title, keyword)
    raw = ai_client.generate(prompt, max_tokens=1200, temperature=0.7)
    if not raw:
        # Minimal fallback if AI fails
        return (
            f"<h1>{title}</h1>"
            f"<p>Stay tuned — our fashion editors are refreshing this guide with the latest tips for {keyword}. "
            f"In the meantime, explore our full collection at <a href='{STORE_URL}'>{STORE_URL}</a>.</p>"
        )
    # Strip markdown fences if AI wrapped output
    raw = raw.strip()
    raw = re.sub(r"^```html?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw).strip()
    return raw


def publish_article(blog_id: int, title: str, body_html: str, handle: str) -> dict | None:
    payload = {
        "article": {
            "title":     title,
            "body_html": body_html,
            "published": True,
            "handle":    handle,   # Force same handle → same URL
        }
    }
    r = _req("POST", f"{BASE}/blogs/{blog_id}/articles.json", json=payload)
    time.sleep(REQUEST_DELAY)
    if r.status_code in (200, 201):
        return r.json().get("article", {})
    print(f"  [PUBLISH FAILED] {r.status_code}: {r.text[:200]}")
    return None


def main():
    parser = argparse.ArgumentParser(description="Recreate corrupted articles with fresh AI content")
    parser.add_argument("--dry-run", action="store_true", help="Preview without changes")
    parser.add_argument("--apply",   action="store_true", help="Delete + recreate articles")
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        print("Specify --dry-run or --apply")
        sys.exit(1)

    print(f"Mode: {'DRY RUN' if args.dry_run else 'APPLY'}")
    print(f"Articles to recreate: {len(FAILED_ARTICLES)}")
    print("=" * 70)

    blogs    = fetch_all_blogs()
    total_ok = 0
    total_fail = 0

    for blog in blogs:
        blog_id    = blog["id"]
        blog_title = blog.get("title", "")
        articles   = fetch_articles(blog_id)

        for article in articles:
            title      = article.get("title", "")
            article_id = article["id"]
            handle     = article.get("handle", "")

            if title not in FAILED_ARTICLES:
                continue

            print(f"\n[{blog_title}] '{title}'")
            print(f"  Handle: {handle}  |  ID: {article_id}")

            if args.dry_run:
                keyword = _guess_keyword(title)
                print(f"  [DRY RUN] Would delete + recreate with keyword: '{keyword}'")
                continue

            # 1. Generate fresh content BEFORE deleting (so we don't delete then fail)
            print(f"  Generating fresh content...")
            body_html = generate_content(title)
            print(f"  Content: {len(body_html)} chars generated")

            # 2. Delete the corrupted article
            deleted = delete_article(blog_id, article_id)
            if not deleted:
                print(f"  [SKIP] Could not delete article — leaving as-is")
                total_fail += 1
                continue
            print(f"  Deleted (ID {article_id})")

            # 3. Re-publish with same handle
            new_art = publish_article(blog_id, title, body_html, handle)
            if new_art:
                print(f"  ✓ Recreated (new ID {new_art.get('id')}) — handle preserved: {handle}")
                total_ok += 1
            else:
                print(f"  ✗ Re-publish failed — article '{title}' is now deleted but not restored!")
                total_fail += 1

    print("\n" + "=" * 70)
    print(f"SUMMARY:")
    print(f"  Recreated: {total_ok}")
    print(f"  Failed:    {total_fail}")
    print("=" * 70)

    if total_fail > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()

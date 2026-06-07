#!/usr/bin/env python3
"""
sync_to_medium.py — Automate syndicating MeeeShop Shopify blogs to Medium
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Fetches recently published articles from Shopify and pushes them to Medium.
Includes the `canonicalUrl` parameter to protect your store's SEO and ensure 
all link juice and organic authority goes to us.meeeshop.com.

Usage:
  python scripts/sync_to_medium.py             # Sync articles from last 7 days
  python scripts/sync_to_medium.py --dry-run   # Preview what would be posted
  python scripts/sync_to_medium.py --days 30   # Sync articles from last 30 days
  python scripts/sync_to_medium.py --limit 5   # Max number of articles to push
  python scripts/sync_to_medium.py --force     # Push all existing articles (WARNING: Rate limits)
"""

import os
import sys
import time
import argparse
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── credentials ───────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
# Assuming secrets_manager.py is in the same directory
from secrets_manager import inject_to_env, get_secret
inject_to_env()

SHOP = get_secret("SHOPIFY_STORE")
SHOP_TOKEN = get_secret("SHOPIFY_ACCESS_TOKEN")
MEDIUM_TOKEN = get_secret("MEDIUM_INTEGRATION_TOKEN")  # You'll need to add this

API_VER = "2024-10"
SHOP_BASE = f"https://{SHOP}/admin/api/{API_VER}"
SHOP_HEADERS = {"X-Shopify-Access-Token": SHOP_TOKEN, "Content-Type": "application/json"}

MEDIUM_API = "https://api.medium.com/v1"
MEDIUM_HEADERS = {
    "Authorization": f"Bearer {MEDIUM_TOKEN}",
    "Content-Type": "application/json",
    "Accept": "application/json"
}

STORE_URL = get_secret("STORE_BASE_URL") or "https://us.meeeshop.com"

if not SHOP_TOKEN or not MEDIUM_TOKEN:
    sys.exit("ERROR: Missing SHOPIFY_ACCESS_TOKEN or MEDIUM_INTEGRATION_TOKEN.")

# ── Shopify Helpers ───────────────────────────────────────────────────────────
def fetch_articles(days: int, limit: int, force: bool) -> list:
    """Fetch articles from all Shopify blogs."""
    print(f"Fetching Shopify blogs...")
    r = requests.get(f"{SHOP_BASE}/blogs.json", headers=SHOP_HEADERS)
    r.raise_for_status()
    blogs = r.json().get("blogs", [])
    
    if not blogs:
        print("No blogs found on Shopify.")
        return []
        
    all_articles = []
    
    for blog in blogs:
        blog_id = blog["id"]
        blog_handle = blog["handle"]
        
        params = {"limit": 250}
        if not force:
            cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            params["published_at_min"] = cutoff_date
        
        r = requests.get(f"{SHOP_BASE}/blogs/{blog_id}/articles.json", headers=SHOP_HEADERS, params=params)
        r.raise_for_status()
        
        articles = r.json().get("articles", [])
        for art in articles:
            art["_full_url"] = f"{STORE_URL}/blogs/{blog_handle}/{art['handle']}"
            art["_blog_id"] = blog_id
            all_articles.append(art)
            
    # Sort newest first
    all_articles.sort(key=lambda x: x.get("published_at", ""), reverse=True)
    
    # Filter out already synced
    pending = []
    for art in all_articles:
        tags = [t.strip() for t in (art.get("tags") or "").split(",") if t.strip()]
        if "medium_synced" not in tags:
            pending.append(art)
            
    return pending[:limit]

def mark_as_synced(blog_id: int, article_id: int, existing_tags: str):
    """Add 'medium_synced' tag to Shopify article to prevent duplicate posting."""
    tags = [t.strip() for t in (existing_tags or "").split(",") if t.strip()]
    if "medium_synced" not in tags:
        tags.append("medium_synced")
        payload = {"article": {"id": article_id, "tags": ", ".join(tags)}}
        r = requests.put(f"{SHOP_BASE}/blogs/{blog_id}/articles/{article_id}.json", headers=SHOP_HEADERS, json=payload)
        if not r.ok:
            print(f"    [WARN] Failed to tag Shopify article as synced: {r.text}")

def fetch_sample_collections(limit=5) -> list:
    """Fetch a few store collections to link in the footer."""
    try:
        r = requests.get(f"{SHOP_BASE}/custom_collections.json", headers=SHOP_HEADERS, params={"limit": limit})
        if r.ok and r.json().get("custom_collections"):
            return r.json()["custom_collections"]
        r = requests.get(f"{SHOP_BASE}/smart_collections.json", headers=SHOP_HEADERS, params={"limit": limit})
        if r.ok and r.json().get("smart_collections"):
            return r.json()["smart_collections"]
    except Exception as e:
        print(f"    [WARN] Could not fetch collections for footer: {e}")
    return []

# ── Medium Helpers ────────────────────────────────────────────────────────────
def get_medium_user_id() -> str:
    """Get the Author ID associated with the Medium Token."""
    r = requests.get(f"{MEDIUM_API}/me", headers=MEDIUM_HEADERS)
    if r.status_code != 200:
        sys.exit(f"ERROR: Invalid Medium Token. Response: {r.text}")
    return r.json()["data"]["id"]

def publish_to_medium(user_id: str, title: str, content: str, canonical_url: str, tags: list, collection_links: list, dry_run: bool):
    """Publish the article to Medium."""
    # Medium has a max limit of 5 tags
    tags = tags[:5]
    
    # Append a small footer linking back to the store for extra CTR
    footer = f"<hr><p><em>This article originally appeared on <a href='{canonical_url}'>MeeeShop</a>, your destination for premium women's fashion in the USA.</em></p>"
    
    if collection_links:
        footer += f"<p><strong>Explore Our Collections:</strong> {' &bull; '.join(collection_links)}</p>"

    full_content = content + footer

    payload = {
        "title": title,
        "contentFormat": "html",
        "content": full_content,
        "tags": tags,
        "canonicalUrl": canonical_url,
        "publishStatus": "public" # Use "draft" if you want to manually review them first
    }
    
    if dry_run:
        print(f"  [DRY-RUN] Would post to Medium: '{title}'")
        print(f"  [DRY-RUN] Tags: {tags}")
        print(f"  [DRY-RUN] Canonical URL: {canonical_url}\n")
        return True
        
    r = requests.post(f"{MEDIUM_API}/users/{user_id}/posts", headers=MEDIUM_HEADERS, json=payload)
    if r.status_code in (200, 201):
        medium_url = r.json()["data"]["url"]
        print(f"  [SUCCESS] Published to Medium: {medium_url}")
        return True
    elif r.status_code == 429:
        print(f"  [FAILED] Medium API Rate Limit (429). Response: {r.text}")
        print(f"           Medium caps publishing at ~10 posts/day [1].")
        print(f"           Stopping today's run gracefully. Please resume tomorrow.")
        return "RATE_LIMIT"
    else:
        print(f"  [FAILED] Medium API Error ({r.status_code}): {r.text}")
        return False

# ── Main ──────────────────────────────────────────────────────────────────────
def run(days: int, limit: int, force: bool, dry_run: bool):
    print(f"\n{'='*60}")
    print(f"  MeeeShop Medium Syndication — {datetime.now().strftime('%Y-%m-%d')}")
    mode_str = "ALL ARTICLES (FORCE)" if force else f"Looking back {days} days"
    print(f"  Mode: {mode_str} | Limit: {limit} | Dry-run: {dry_run}")
    print(f"{'='*60}\n")

    user_id = get_medium_user_id()
    
    collections_data = fetch_sample_collections(5)
    collection_links = [
        f"<a href='{STORE_URL}/collections/{c['handle']}'>{c['title']}</a>" 
        for c in collections_data if c.get("handle")
    ]

    articles = fetch_articles(days, limit, force)
    
    if not articles:
        print(f"No unsynced articles found matching criteria.")
        return
        
    print(f"Found {len(articles)} unsynced article(s). Syndicating to Medium...\n")
    
    for i, art in enumerate(articles, 1):
        title = art.get("title")
        body = art.get("body_html")
        canonical_url = art.get("_full_url")
        blog_id = art.get("_blog_id")
        article_id = art.get("id")
        raw_tags = art.get("tags") or ""
        
        # Grab tags from Shopify and add targeted audience tags
        existing_tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
        medium_tags = list(dict.fromkeys(existing_tags + ["Womens Fashion", "Style", "Fashion", "Boutique"]))
        
        print(f"[{i}/{len(articles)}] Syndicating: '{title}'")
        success = publish_to_medium(user_id, title, body, canonical_url, medium_tags, collection_links, dry_run)
        
        if success == "RATE_LIMIT":
            print("\n🚨 Account rate-limited by Medium. Stopping gracefully so GitHub Action succeeds.")
            break
            
        if success and not dry_run:
            mark_as_synced(blog_id, article_id, raw_tags)
            
        time.sleep(2) # Prevent Medium API rate limits

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Post Shopify blogs to Medium.")
    ap.add_argument("--days", type=int, default=7, help="Sync articles published in the last X days.")
    ap.add_argument("--limit", type=int, default=10, help="Max articles to fetch (Medium API limit is 10/day).")
    ap.add_argument("--force", action="store_true", help="Post ALL available articles (ignores --days).")
    ap.add_argument("--dry-run", action="store_true", help="Print plan, do not post to Medium.")
    args = ap.parse_args()
    
    run(days=args.days, limit=args.limit, force=args.force, dry_run=args.dry_run)
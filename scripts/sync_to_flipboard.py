#!/usr/bin/env python3
#!/usr/bin/env python3
"""
sync_to_flipboard.py — Automate flipping Shopify blogs to Flipboard
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Uses Playwright browser automation to log into Flipboard and "flip"
newly published Shopify articles into a specific Flipboard magazine.

Flipboard acts as a directory — it links directly to your Shopify store,
so canonical URLs are inherently handled and all SEO juice goes to your domain.

Usage:
  python scripts/sync_to_flipboard.py             # Sync articles from last 7 days
  python scripts/sync_to_flipboard.py --dry-run   # Preview what would be posted
  python scripts/sync_to_flipboard.py --headed    # Run with a visible browser (good for first run/captchas)
"""

import logging
import os
import sys
import time
import argparse
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
except ImportError:
    sys.exit("Playwright not installed. Please run: pip install playwright && playwright install chromium")

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

def handle_exception(exc_type, exc_value, exc_traceback):
    logging.error("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))
sys.excepthook = handle_exception

# ── credentials ───────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from secrets_manager import inject_to_env, get_secret
inject_to_env()

SHOP = get_secret("SHOPIFY_STORE")
SHOP_TOKEN = get_secret("SHOPIFY_ACCESS_TOKEN")
STORE_URL = get_secret("STORE_BASE_URL") or "https://us.meeeshop.com"

FLIPBOARD_EMAIL = get_secret("FLIPBOARD_EMAIL")
FLIPBOARD_PASSWORD = get_secret("FLIPBOARD_PASSWORD")
FLIPBOARD_MAGAZINE = get_secret("FLIPBOARD_MAGAZINE") or "MeeeShop Style Guide" # Fallback name

API_VER = "2024-10"
SHOP_BASE = f"https://{SHOP}/admin/api/{API_VER}"
SHOP_HEADERS = {"X-Shopify-Access-Token": SHOP_TOKEN, "Content-Type": "application/json"}

if not all([SHOP_TOKEN, FLIPBOARD_EMAIL, FLIPBOARD_PASSWORD, SHOP]):
    logging.error("Missing one or more required secrets: SHOPIFY_STORE, SHOPIFY_ACCESS_TOKEN, FLIPBOARD_EMAIL, FLIPBOARD_PASSWORD")
    sys.exit(1)

# ── Shopify Helpers ───────────────────────────────────────────────────────────
def fetch_articles(days: int, limit: int) -> list:
    """Fetch articles from all Shopify blogs."""
    logging.info("Fetching Shopify blogs...")
    r = requests.get(f"{SHOP_BASE}/blogs.json", headers=SHOP_HEADERS)
    r.raise_for_status()
    blogs = r.json().get("blogs", [])
    logging.info(f"Found {len(blogs)} blog(s): {[b.get('title') for b in blogs]}")
    
    all_articles = []
    for blog in blogs:
        blog_id = blog["id"]
        blog_handle = blog["handle"]
        
        cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        params = {"limit": 250, "published_at_min": cutoff_date}
        
        logging.info(f"  Fetching articles from '{blog['title']}'...")
        r = requests.get(f"{SHOP_BASE}/blogs/{blog_id}/articles.json", headers=SHOP_HEADERS, params=params)
        r.raise_for_status()
        
        articles_batch = r.json().get("articles", [])
        for art in articles_batch:
            art["_full_url"] = f"{STORE_URL}/blogs/{blog_handle}/{art['handle']}"
            art["_blog_id"] = blog_id
            all_articles.append(art)
            
    all_articles.sort(key=lambda x: x.get("published_at", ""), reverse=True)
    
    # Filter out already synced
    pending = []
    for art in all_articles:
        tags = [t.strip() for t in (art.get("tags") or "").split(",") if t.strip()]
        if "flipboard_synced" not in tags:
            pending.append(art)
            
    return pending[:limit]

def mark_as_synced(blog_id: int, article_id: int, existing_tags: str):
    """Add 'flipboard_synced' tag to Shopify article to prevent duplicate posting."""
    tags = [t.strip() for t in (existing_tags or "").split(",") if t.strip()]
    if "flipboard_synced" not in tags:
        tags.append("flipboard_synced")
        payload = {"article": {"id": article_id, "tags": ", ".join(tags)}}
        r = requests.put(f"{SHOP_BASE}/blogs/{blog_id}/articles/{article_id}.json", headers=SHOP_HEADERS, json=payload)
        if not r.ok:
            logging.warning(f"Failed to tag Shopify article as synced: {r.text}")

# ── Flipboard Automation ──────────────────────────────────────────────────────
def test_flipboard_login(headless: bool = True):
    """Tests Flipboard login without posting."""
    logging.info("--- Starting Flipboard Login Test (Dry Run) ---")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = context.new_page()
            logging.info("Navigating to Flipboard sign-in page...")
            page.goto("https://flipboard.com/signin")
            
            page.fill('input[name="username"], input[type="email"]', FLIPBOARD_EMAIL)
            page.fill('input[name="password"], input[type="password"]', FLIPBOARD_PASSWORD)
            page.click('button[type="submit"]')
            
            logging.info("Waiting for login confirmation...")
            page.wait_for_selector('button[aria-label="Profile"], button[aria-label="Create a Flip"]', timeout=20000)
            logging.info("✅ Flipboard login successful.")
            browser.close()
            logging.info("--- Flipboard Login Test Finished ---")
            return True
    except PlaywrightTimeoutError:
        logging.error("❌ Flipboard login failed. Credentials may be wrong or a CAPTCHA is present.")
        logging.error("Run with the --headed flag locally to solve CAPTCHAs manually.")
        return False
    except Exception as e:
        logging.error(f"❌ An unexpected error occurred during login test: {e}")
        return False

def flip_articles(articles: list, headless: bool):
    """Use Playwright to log in and flip articles."""
    logging.info("Starting browser automation to post to Flipboard...")
    
    with sync_playwright() as p:
        # Launch browser. Use headless=False if you need to solve captchas manually on the first run.
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        
        # 1. Log in to Flipboard
        logging.info("Logging into Flipboard...")
        page.goto("https://flipboard.com/signin")
        
        try:
            # Flipboard's login flow
            page.fill('input[name="username"], input[type="email"]', FLIPBOARD_EMAIL)
            page.fill('input[name="password"], input[type="password"]', FLIPBOARD_PASSWORD)
            page.click('button[type="submit"]')
            
            # Wait for successful login (avatar or main feed appears)
            page.wait_for_selector('button[aria-label="Profile"], button[aria-label="Create a Flip"]', timeout=15000)
            logging.info("✓ Successfully logged in.")
        except PlaywrightTimeoutError:
            logging.error("Login failed or took too long. If there's a Captcha, run with --headed flag to solve it manually.")
            browser.close()
            return
            
        # 2. Flip each article
        for i, art in enumerate(articles, 1):
            url = art["_full_url"]
            title = art["title"]
            logging.info(f"[{i}/{len(articles)}] Flipping: '{title}'")
            
            try:
                # Click the Create/Pencil icon
                page.click('button[aria-label="Create a Flip"], [aria-label="Create"]')
                
                # Wait for the input field to appear and paste the URL
                page.wait_for_selector('input[placeholder*="URL"], textarea[placeholder*="URL"]')
                page.fill('input[placeholder*="URL"], textarea[placeholder*="URL"]', url)
                
                # Flipboard auto-fetches the preview. Wait for the "Next" or "Flip" button to activate.
                page.wait_for_timeout(3000) # Give Flipboard a moment to scrape the Open Graph tags
                
                # Sometimes there's a "Next" button, sometimes it goes straight to magazine selection
                if page.is_visible('button:has-text("Next")'):
                    page.click('button:has-text("Next")')
                    page.wait_for_timeout(1000)
                
                # Select Magazine
                page.wait_for_selector(f'text={FLIPBOARD_MAGAZINE}')
                page.click(f'text={FLIPBOARD_MAGAZINE}')
                
                # Click the final Add / Flip button
                page.click('button:has-text("Add"), button:has-text("Flip")')
                
                # Wait for success toast/notification
                page.wait_for_timeout(2000)
                logging.info(f"  ✓ Flipped successfully.")
                
                # Update Shopify Tag
                mark_as_synced(art["_blog_id"], art["id"], art.get("tags", ""))
                
            except Exception as e:
                logging.error(f"  FAILED to flip article. Error: {str(e)}")
                
            time.sleep(2) # Brief pause between flips to act human

        browser.close()
        logging.info("Browser automation finished.")

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Automate flipping Shopify blogs to Flipboard.")
    ap.add_argument("--days", type=int, default=7, help="Sync articles published in the last X days.")
    ap.add_argument("--limit", type=int, default=10, help="Max articles to flip per run.")
    ap.add_argument("--dry-run", action="store_true", help="Print plan, do not flip.")
    ap.add_argument("--headed", action="store_true", help="Show browser window (helpful for initial setup).")
    args = ap.parse_args()
    
    logging.info("="*60)
    logging.info(f" MeeeShop Flipboard Syndication — {datetime.now().strftime('%Y-%m-%d')}")
    logging.info("="*60)

    articles = fetch_articles(args.days, args.limit)
    
    if not articles:
        logging.info("No new unsynced articles found matching criteria. Exiting.")
        sys.exit(0)
        
    logging.info(f"Found {len(articles)} unsynced article(s) to process.")
    
    if args.dry_run:
        logging.info("--- DRY RUN MODE ---")
        test_flipboard_login(headless=not args.headed)
        logging.info("Articles that would be flipped:")
        for art in articles:
            logging.info(f"  - '{art['title']}' ({art['_full_url']})")
        logging.info("--- END DRY RUN ---")
    else:
        logging.info("--- LIVE MODE ---")
        flip_articles(articles, headless=not args.headed)
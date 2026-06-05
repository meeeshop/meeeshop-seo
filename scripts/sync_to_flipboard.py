#!/usr/bin/env python3
"""
sync_to_flipboard.py — Automate flipping Shopify blogs to Flipboard
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Uses Selenium browser automation to log into Flipboard and "flip"
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
import json
import sys
import time
import argparse
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.chrome.options import Options
    from webdriver_manager.chrome import ChromeDriverManager
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException
except ImportError:
    sys.exit("Selenium not installed. Please run: pip install selenium webdriver-manager")

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
try:
    FLIPBOARD_MAGAZINE = get_secret("FLIPBOARD_MAGAZINE")
    if FLIPBOARD_MAGAZINE == "MeeeShop Style Guide":
        FLIPBOARD_MAGAZINE = "Trending Clothing Tips & Styles For Women"
except KeyError:
    FLIPBOARD_MAGAZINE = "Trending Clothing Tips & Styles For Women"

API_VER = "2024-10"
SHOP_BASE = f"https://{SHOP}/admin/api/{API_VER}"
SHOP_HEADERS = {"X-Shopify-Access-Token": SHOP_TOKEN, "Content-Type": "application/json"}

# ── routing ───────────────────────────────────────────────────────────────────
MAGAZINE_ROUTING = {
    "dress": "Women's Dresses",
    "skirt": "Women's Dresses",
    "jean": "Women's Jeans & Bottoms",
    "denim": "Women's Jeans & Bottoms",
    "pant": "Women's Jeans & Bottoms",
    "trouser": "Women's Jeans & Bottoms",
    "bottom": "Women's Jeans & Bottoms",
    "legging": "Women's Jeans & Bottoms",
    "short": "Women's Jeans & Bottoms",
    "plus": "Curvy | Plus Size Styles & Tips",
    "curvy": "Curvy | Plus Size Styles & Tips",
    "bag": "Handbags",
    "handbag": "Handbags",
    "purse": "Handbags",
    "shoe": "Women's footwear",
    "boot": "Women's footwear",
    "sandal": "Women's footwear",
    "sneaker": "Women's footwear",
    "vegan": "Veganism | Eco-Friendly & Sustainable",
    "eco": "Veganism | Eco-Friendly & Sustainable",
    "sustainable": "Veganism | Eco-Friendly & Sustainable",
    "top": "Trending Clothing Tips & Styles For Women",
    "blouse": "Trending Clothing Tips & Styles For Women",
    "shirt": "Trending Clothing Tips & Styles For Women",
    "sweater": "Trending Clothing Tips & Styles For Women",
    "cardigan": "Trending Clothing Tips & Styles For Women",
    "jacket": "Trending Clothing Tips & Styles For Women",
    "coat": "Trending Clothing Tips & Styles For Women",
    "outerwear": "Trending Clothing Tips & Styles For Women",
    "activewear": "Trending Clothing Tips & Styles For Women",
    "swimwear": "Trending Clothing Tips & Styles For Women"
}

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
def get_browser(headless=True):
    """Create a selenium webdriver mimicking a real browser."""
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    options.add_argument("--window-size=1920,1080")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    
    # Override navigator.webdriver flag
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    })
    return driver

def load_session_cookies(driver):
    if FLIPBOARD_SESSION:
        try:
            driver.get("https://flipboard.com/404")
            time.sleep(1)
            cookies = json.loads(FLIPBOARD_SESSION)
            for cookie in cookies:
                if 'sameSite' in cookie and cookie['sameSite'] not in ['Strict', 'Lax', 'None']:
                    del cookie['sameSite']
                if 'expiry' in cookie:
                    cookie['expiry'] = int(cookie['expiry'])
                driver.add_cookie(cookie)
            logging.info("Injected saved session cookies.")
        except Exception as e:
            logging.error(f"Failed to load FLIPBOARD_SESSION JSON: {e}")

def perform_login(driver):
    """Helper to log into Flipboard using human-like interaction to bypass Captchas."""
    logging.info("Navigating to Flipboard sign-in page...")
    driver.get("https://flipboard.com/signin")
    time.sleep(3) # Let bot protection settle
    
    logging.info("Entering credentials like a human...")
    email_loc = driver.find_element(By.CSS_SELECTOR, 'input[name="username"], input[type="email"]')
    email_loc.click()
    time.sleep(0.5)
    for char in FLIPBOARD_EMAIL:
        email_loc.send_keys(char)
        time.sleep(0.1)
    
    time.sleep(1)
    
    pass_loc = driver.find_element(By.CSS_SELECTOR, 'input[name="password"], input[type="password"]')
    pass_loc.click()
    time.sleep(0.5)
    for char in FLIPBOARD_PASSWORD:
        pass_loc.send_keys(char)
        time.sleep(0.1)
    
    time.sleep(1)
    driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]').click()
    
    logging.info("Waiting for login confirmation...")
    WebDriverWait(driver, 20).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, '[aria-label="Profile"], [aria-label="Create a Flip"], [aria-label="Create"], a[href^="/@"]'))
    )

def test_flipboard_login(headless: bool = True):
    """Tests Flipboard login without posting."""
    logging.info("--- Starting Flipboard Login Test (Dry Run) ---")
    driver = None
    try:
        driver = get_browser(headless)
        load_session_cookies(driver)
        
        logging.info("Attempting to load Flipboard...")
        driver.get("https://flipboard.com/")
        try:
            WebDriverWait(driver, 7).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, '[aria-label="Profile"], [aria-label="Create a Flip"], [aria-label="Create"], a[href^="/@"]'))
            )
            logging.info("✅ Login successful (likely via saved session).")
        except TimeoutException:
            logging.info("Session login failed or expired. Falling back to credential login.")
            perform_login(driver)
            logging.info("✅ Login successful (via credentials).")
            
        logging.info("--- Flipboard Login Test Finished ---")
        return True
    except Exception as e:
        logging.error(f"❌ An unexpected error occurred during login test: {e}")
        return False
    finally:
        if driver:
            driver.quit()

def flip_articles(articles: list, headless: bool):
    """Use Playwright to log in and flip articles."""
    logging.info("Starting browser automation to post to Flipboard...")
    driver = get_browser(headless)

    try:
        load_session_cookies(driver)
        
        logging.info("Attempting to log in...")
        driver.get("https://flipboard.com/")
        try:
            WebDriverWait(driver, 7).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, '[aria-label="Profile"], [aria-label="Create a Flip"], [aria-label="Create"], a[href^="/@"]'))
            )
            logging.info("✅ Login successful (likely via saved session).")
        except TimeoutException:
            logging.info("Session login failed or expired. Falling back to credential login.")
            try:
                perform_login(driver)
                logging.info("✅ Login successful (via credentials).")
            except Exception as e:
                logging.error(f"❌ Login with credentials also failed: {e}")
                logging.error("You must run 'python scripts/save_flipboard_session.py' locally to create a valid session file.")
                return
            
        # 2. Flip each article
        for i, art in enumerate(articles, 1):
            url = art["_full_url"]
            title = art["title"]
            logging.info(f"[{i}/{len(articles)}] Flipping: '{title}'")
            
            # Determine target magazine
            tags = [t.strip().lower() for t in (art.get("tags") or "").split(",") if t.strip()]
            target_mag = FLIPBOARD_MAGAZINE
            for tag in tags:
                for kw, mag in MAGAZINE_ROUTING.items():
                    if kw in tag:
                        target_mag = mag
                        break
                if target_mag != FLIPBOARD_MAGAZINE:
                    break
                    
            logging.info(f"  Routing to Magazine: '{target_mag}'")
            
            try:
                # Click the Create/Pencil icon
                create_btn = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, '[aria-label="Create a Flip"], [aria-label="Create"]'))
                )
                create_btn.click()
                
                # Wait for the input field to appear and paste the URL
                url_input = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, 'input[placeholder*="URL"], textarea[placeholder*="URL"]'))
                )
                url_input.send_keys(url)
                
                # Flipboard auto-fetches the preview. Wait for the "Next" or "Flip" button to activate.
                time.sleep(4)
                
                # Sometimes there's a "Next" button, sometimes it goes straight to magazine selection
                try:
                    next_btn = driver.find_element(By.XPATH, '//button[contains(text(), "Next")]')
                    if next_btn.is_displayed():
                        next_btn.click()
                        time.sleep(2)
                except:
                    pass
                
                # Select Magazine
                try:
                    mag_btn = WebDriverWait(driver, 4).until(
                        EC.element_to_be_clickable((By.XPATH, f'//*[contains(text(), "{target_mag}")]'))
                    )
                    mag_btn.click()
                except TimeoutException:
                    logging.warning(f"  Magazine '{target_mag}' not found. Falling back to '{FLIPBOARD_MAGAZINE}'")
                    mag_btn = WebDriverWait(driver, 5).until(
                        EC.element_to_be_clickable((By.XPATH, f'//*[contains(text(), "{FLIPBOARD_MAGAZINE}")]'))
                    )
                    mag_btn.click()
                
                # Click the final Add / Flip button
                flip_btn = driver.find_element(By.XPATH, '//*[contains(text(), "Add") or contains(text(), "Flip")]')
                flip_btn.click()
                
                # Wait for success toast/notification
                time.sleep(3)
                logging.info(f"  ✓ Flipped successfully.")
                
                # Update Shopify Tag
                mark_as_synced(art["_blog_id"], art["id"], art.get("tags", ""))
                
            except Exception as e:
                logging.error(f"  FAILED to flip article. Error: {str(e)}")
                
            time.sleep(2) # Brief pause between flips to act human

    finally:
        driver.quit()
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
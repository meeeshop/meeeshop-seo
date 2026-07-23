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
import random
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
FLIPBOARD_SESSION = get_secret("FLIPBOARD_SESSION")
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
            
    all_articles.sort(key=lambda x: x.get("published_at") or "", reverse=True)
    
    # Filter out already synced
    pending = []
    for art in all_articles:
        tags = [t.strip() for t in (art.get("tags") or "").split(",") if t.strip()]
        if "flipboard_synced" not in tags:
            pending.append(art)
            
    return pending[:limit]

def fetch_old_articles(limit: int) -> list:
    """Fetch previously synced Shopify articles to re-flip."""
    logging.info("Fetching Shopify blogs to locate old articles...")
    try:
        r = requests.get(f"{SHOP_BASE}/blogs.json", headers=SHOP_HEADERS)
        r.raise_for_status()
        blogs = r.json().get("blogs", [])
    except Exception as e:
        logging.error(f"Failed to fetch blogs for old articles: {e}")
        return []
        
    all_articles = []
    for blog in blogs:
        blog_id = blog["id"]
        blog_handle = blog["handle"]
        
        # Fetch up to 250 articles (no date limit, to get old ones)
        params = {"limit": 250}
        logging.info(f"  Fetching articles from '{blog['title']}' for re-flipping...")
        try:
            r = requests.get(f"{SHOP_BASE}/blogs/{blog_id}/articles.json", headers=SHOP_HEADERS, params=params)
            r.raise_for_status()
            articles_batch = r.json().get("articles", [])
        except Exception as e:
            logging.warning(f"  Failed to fetch articles from blog {blog_id}: {e}")
            continue
            
        for art in articles_batch:
            art["_full_url"] = f"{STORE_URL}/blogs/{blog_handle}/{art['handle']}"
            art["_blog_id"] = blog_id
            all_articles.append(art)
            
    # Filter to only those already synced
    synced_articles = []
    for art in all_articles:
        tags = [t.strip() for t in (art.get("tags") or "").split(",") if t.strip()]
        if "flipboard_synced" in tags:
            synced_articles.append(art)
            
    if not synced_articles:
        # Fallback to all articles if none are marked synced yet
        synced_articles = all_articles
        
    if not synced_articles:
        return []
        
    # Return a random selection of old articles to keep it dynamic
    sample_size = min(limit, len(synced_articles))
    return random.sample(synced_articles, sample_size)

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
    try:
        email_loc = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'input[name="username"], input[type="email"], input[name="email"]'))
        )
    except TimeoutException:
        try:
            # Broaden the search for the email login button
            email_btn = driver.find_element(By.XPATH, '//*[(self::button or self::a) and (contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "email") or contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "log in"))]')
            driver.execute_script("arguments[0].click();", email_btn)
        except Exception as e:
            logging.warning(f"Could not find email login button: {type(e).__name__}")
            
        email_loc = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'input[name="username"], input[type="email"], input[name="email"]'))
        )
    driver.execute_script("arguments[0].click();", email_loc)
    time.sleep(0.5)
    for char in FLIPBOARD_EMAIL:
        email_loc.send_keys(char)
        time.sleep(0.1)
    
    time.sleep(1)
    pass_loc = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, 'input[name="password"], input[type="password"]'))
    )
    driver.execute_script("arguments[0].click();", pass_loc)
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
        if driver:
            try:
                driver.save_screenshot("login_test_failure.png")
                with open("login_test_failure.html", "w", encoding="utf-8") as f:
                    f.write(driver.page_source)
            except Exception: pass
        logging.error(f"❌ An unexpected error occurred during login test: {e}")
        return False
    finally:
        if driver:
            driver.quit()
            
def find_magazine_element(driver, target_mag):
    """Locate all flip magazine buttons inside the popup specifically, supporting both main site modal and share popout."""
    # 1. Main site popup selectors
    buttons = driver.find_elements(By.CSS_SELECTOR, 'button[data-vars-button-name="flip-compose-magazine"]')
    
    # 2. Bookmarklet popout selectors
    if not buttons:
        buttons = driver.find_elements(By.CSS_SELECTOR, 'div.magazine-selection__magazine, .magazine-selection__magazine')
        
    for btn in buttons:
        try:
            txt = driver.execute_script("return arguments[0].textContent;", btn)
            if txt:
                txt_clean = txt.strip()
                # Remove "Created..." suffix to get clean name for logging
                name = txt_clean.split("Created")[0].strip()
                if target_mag.lower() in name.lower() or name.lower() in target_mag.lower():
                    return btn, name
        except Exception:
            pass
    return None, None

def handle_flip_popup(driver, target_mag):
    """Helper to handle the magazine selection popup and submitting the flip."""
    # Check if we are already on the magazine selection screen
    magazine_visible = False
    try:
        mags = driver.find_elements(By.CSS_SELECTOR, 'button[data-vars-button-name="flip-compose-magazine"], div.magazine-selection__magazine, .magazine-selection__magazine')
        if any(m.is_displayed() for m in mags):
            magazine_visible = True
            logging.info("  [Trace] Magazine list is already visible. Skipping 'Next' button.")
    except Exception:
        pass

    if not magazine_visible:
        # Sometimes there's a "Next" button, sometimes it goes straight to magazine selection
        try:
            logging.info("  [Trace] Checking for 'Next' button...")
            next_btns = driver.find_elements(By.CSS_SELECTOR, 'button[data-vars-button-name="submit"]')
            visible_next_btns = [b for b in next_btns if b.is_displayed() and "next" in b.text.lower()]
            if visible_next_btns:
                logging.info("  [Trace] 'Next' button displayed, clicking...")
                visible_next_btns[0].click()
                time.sleep(2)
            else:
                next_btn = driver.find_element(By.XPATH, '//*[(self::button or @role="button") and contains(translate(text(),"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"), "next")]')
                if next_btn.is_displayed():
                    logging.info("  [Trace] 'Next' button displayed, clicking...")
                    next_btn.click()
                    time.sleep(2)
                else:
                    logging.info("  [Trace] 'Next' button found but not displayed.")
        except Exception as e:
            logging.info(f"  [Trace] No 'Next' button found ({type(e).__name__}). Proceeding to magazine selection.")
    
    # Select Magazine
    logging.info(f"  [Trace] Looking for target magazine '{target_mag}'...")
    
    # Wait for the magazine list to render
    logging.info("  [Trace] Waiting for magazine list to appear...")
    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((
                By.CSS_SELECTOR, 
                'button[data-vars-button-name="flip-compose-magazine"], div.magazine-selection__magazine, .magazine-selection__magazine'
            ))
        )
    except Exception as e:
        logging.warning(f"  [Trace] Timeout waiting for magazine list to render: {e}")
    
    # Check if there is an "Expand" button/link and click it to reveal all magazines
    try:
        expand_btns = driver.find_elements(By.XPATH, '//*[(self::button or self::a or self::span or self::div) and (translate(text(), "EXPAND", "expand")="expand" or contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "expand"))]')
        for btn in expand_btns:
            if btn.is_displayed():
                logging.info("  [Trace] Found 'Expand' button, clicking to reveal all magazines...")
                try:
                    driver.execute_script("arguments[0].click();", btn)
                except Exception:
                    btn.click()
                time.sleep(2) # Let the list expand
                break
    except Exception as e:
        logging.info(f"  [Trace] Error trying to click Expand button: {e}")

    mag_clicked = False
    clicked_name = ""
    
    def safe_click_mag(el, name):
        logging.info(f"  [Trace] Clicking magazine match: '{name}'")
        try:
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
            time.sleep(0.5)
            el.click()
        except Exception:
            driver.execute_script("arguments[0].click();", el)
            
    # 1. Try exact/partial match for target_mag (avoiding footwear)
    btn, name = find_magazine_element(driver, target_mag)
    if btn:
        if "footwear" in target_mag.lower() or "footwear" not in name.lower():
            safe_click_mag(btn, name)
            mag_clicked = True
            clicked_name = name
    
    # 2. Try fallback FLIPBOARD_MAGAZINE
    if not mag_clicked:
        logging.warning(f"  Magazine '{target_mag}' not found. Falling back to '{FLIPBOARD_MAGAZINE}'")
        btn, name = find_magazine_element(driver, FLIPBOARD_MAGAZINE)
        if btn and "footwear" not in name.lower():
            safe_click_mag(btn, name)
            mag_clicked = True
            clicked_name = name
                
    # 3. Try any known magazine except footwear
    if not mag_clicked:
        known_mags = set(MAGAZINE_ROUTING.values())
        known_mags.add(FLIPBOARD_MAGAZINE)
        logging.warning("  [Trace] Fallback not found. Trying ANY known magazine (avoiding footwear)...")
        for km in known_mags:
            if "footwear" in km.lower():
                continue
            btn, name = find_magazine_element(driver, km)
            if btn and "footwear" not in name.lower():
                safe_click_mag(btn, name)
                mag_clicked = True
                clicked_name = name
                break
                
    # 4. Try first available option
    if not mag_clicked:
        logging.warning("  [Trace] Could not identify specific magazine. Clicking first available option...")
        buttons = driver.find_elements(By.CSS_SELECTOR, 'button[data-vars-button-name="flip-compose-magazine"]')
        if not buttons:
            buttons = driver.find_elements(By.CSS_SELECTOR, 'div.magazine-selection__magazine, .magazine-selection__magazine')
        if buttons:
            btn = buttons[0]
            try:
                name = driver.execute_script("return arguments[0].textContent;", btn).split("Created")[0].strip()
            except Exception:
                name = "First available magazine"
            safe_click_mag(btn, name)
            mag_clicked = True
            clicked_name = name

    if not mag_clicked:
        logging.warning("  [Trace] Still could not identify any magazine to click. Relying on auto-selected default (if any).")
    
    time.sleep(2) # Let selection register
    
    logging.info("  [Trace] Looking for final Next/Add/Flip/Done button...")
    submit_btn = None
    try:
        btns = driver.find_elements(By.CSS_SELECTOR, 'button[data-vars-button-name="submit"], button.share-flip__button-primary')
        visible_btns = [b for b in btns if b.is_displayed()]
        if visible_btns:
            submit_btn = visible_btns[0]
    except Exception:
        pass
        
    button_clicked = False
    if submit_btn:
        logging.info("  [Trace] Found final submit button, clicking...")
        try:
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", submit_btn)
            time.sleep(0.5)
            submit_btn.click()
            button_clicked = True
        except Exception:
            try:
                driver.execute_script("arguments[0].click();", submit_btn)
                button_clicked = True
            except Exception as e:
                logging.warning(f"  [Trace] Failed to click final submit button: {e}")
                
    if not button_clicked:
        logging.warning("  [Trace] Falling back to generic final button search via XPath...")
        flip_btns = driver.find_elements(By.XPATH, '//*[(self::button or @role="button" or self::a) and (contains(translate(text(),"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"), "next") or contains(translate(text(),"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"), "add") or contains(translate(text(),"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"), "flip") or contains(translate(text(),"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"), "create") or contains(translate(text(),"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"), "done") or contains(translate(text(),"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"), "save"))] | //*[contains(@aria-label, "Next") or contains(@aria-label, "Add") or contains(@aria-label, "Flip") or contains(@aria-label, "Done")]')
        visible_btns = [b for b in flip_btns if b.is_displayed() and not b.get_attribute("disabled")]
        if visible_btns:
            target_btn = visible_btns[-1]
            logging.info("  [Trace] Found final button via XPath, clicking...")
            try:
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", target_btn)
                time.sleep(0.5)
                target_btn.click()
                button_clicked = True
            except Exception:
                try:
                    driver.execute_script("arguments[0].click();", target_btn)
                    button_clicked = True
                except Exception as e:
                    logging.warning(f"  [Trace] Failed to click final XPath button: {e}")
                    
    if not button_clicked:
        logging.info("  [Trace] No obvious submit button found. Flipboard may have auto-flipped upon magazine selection.")
        if mag_clicked:
            button_clicked = True
                
    if button_clicked:
        # Wait for success toast/notification or modal close
        logging.info("  [Trace] Waiting 3s for success confirmation...")
        time.sleep(3)
        
        # Check if modal is still open
        modal_still_open = False
        try:
            modals = driver.find_elements(By.CSS_SELECTOR, 'div[role="dialog"], .modal, .magazine-selection')
            if any(m.is_displayed() for m in modals):
                modal_still_open = True
        except Exception:
            pass

        # Check for success toast
        saw_toast = False
        try:
            toasts = driver.find_elements(By.XPATH, '//*[contains(text(), "Flipped") or contains(text(), "Added to") or contains(text(), "Saved to")]')
            if any(t.is_displayed() for t in toasts):
                saw_toast = True
                logging.info(f"  [Trace] Found success toast notification.")
        except Exception:
            pass
            
        # DEBUG SCREENSHOT to verify it actually worked
        debug_time = int(time.time())
        try:
            driver.save_screenshot(f"debug_flip_{debug_time}.png")
        except Exception:
            pass

        if modal_still_open and not saw_toast:
            logging.warning("  ✗ Modal is still open and no success toast seen. Flip likely failed.")
            return False
            
        logging.info("  ✓ Flipped successfully.")
        return True
    else:
        logging.warning("  ✗ Failed to click any submit/done button in popup.")
        return False

def reflip_trending(driver, limit):
    logging.info(f"--- Starting Reflip of Trending Articles (limit={limit}) ---")
    topic_mag_map = {
        "womensfashion": FLIPBOARD_MAGAZINE,
        "streetstyle": FLIPBOARD_MAGAZINE,
        "dresses": "Women's Dresses",
        "jeans": "Women's Jeans & Bottoms",
        "handbags": "Handbags",
        "shoes": "Women's footwear",
        "plussize": "Curvy | Plus Size Styles & Tips",
        "outerwear": "Trending Clothing Tips & Styles For Women",
        "sustainablefashion": "Veganism | Eco-Friendly & Sustainable",
        "veganfashion": "Veganism | Eco-Friendly & Sustainable",
        "activewear": "Trending Clothing Tips & Styles For Women",
        "swimwear": "Trending Clothing Tips & Styles For Women",
        "accessories": "Trending Clothing Tips & Styles For Women",
        "jewelry": "Trending Clothing Tips & Styles For Women"
    }
    
    topics = list(topic_mag_map.keys())
    # Shuffle topics initially to randomize rotation
    random.shuffle(topics)
    
    successful_flips = 0
    attempt = 0
    max_attempts = 15
    topic_idx = 0
    
    import urllib.parse
    import xml.etree.ElementTree as ET

    def fetch_trending_candidates(topic: str) -> list:
        """
        Fetch trending articles for a topic using Flipboard's RSS feed.
        Flipboard exposes https://flipboard.com/topic/{topic}.rss which returns
        external article URLs — far more reliable than scraping the JS-rendered page.
        """
        rss_url = f"https://flipboard.com/topic/{topic}.rss"
        try:
            resp = requests.get(rss_url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            if not resp.ok:
                logging.warning(f"  [RSS] HTTP {resp.status_code} for topic RSS: {rss_url}")
                return []
            root = ET.fromstring(resp.text)
            items = root.findall(".//item")
            candidates = []
            for item in items:
                title_el = item.find("title")
                link_el  = item.find("link")
                title = (title_el.text or "").strip() if title_el is not None else ""
                link  = (link_el.text  or "").strip() if link_el  is not None else ""
                if title and link and len(title) > 10 and "flipboard.com" not in link:
                    candidates.append((link, title))
            logging.info(f"  [RSS] Found {len(candidates)} external articles for topic '{topic}'")
            return candidates
        except ET.ParseError as pe:
            logging.warning(f"  [RSS] Failed to parse RSS for '{topic}': {pe}")
            return []
        except Exception as e:
            logging.warning(f"  [RSS] Error fetching RSS for '{topic}': {e}")
            return []

    while successful_flips < limit and attempt < max_attempts:
        attempt += 1
        topic = topics[topic_idx % len(topics)]
        topic_idx += 1
        
        target_mag = topic_mag_map.get(topic, FLIPBOARD_MAGAZINE)
        logging.info(f"[{successful_flips + 1}/{limit}] Attempt {attempt}: topic='{topic}' -> mag='{target_mag}'")
        
        try:
            candidates = fetch_trending_candidates(topic)

            if not candidates:
                logging.warning(f"  No candidates found for topic '{topic}'. Skipping.")
                continue

            # Pick a random article from the top results
            article_url, article_title = random.choice(candidates[:min(8, len(candidates))])
            logging.info(f"  [Trace] Selected: '{article_title}' — {article_url}")

            # Use the proven share.flipboard.com popout (same as our blog articles)
            encoded_url   = urllib.parse.quote(article_url,   safe="")
            encoded_title = urllib.parse.quote(article_title, safe="")
            popout_url = (
                f"https://share.flipboard.com/bookmarklet/popout"
                f"?v=2&title={encoded_title}&url={encoded_url}"
            )

            logging.info(f"  [Trace] Opening share popout...")
            driver.get(popout_url)
            time.sleep(4)

            if handle_flip_popup(driver, target_mag):
                successful_flips += 1
                logging.info(
                    f"  ✓ Flipped '{article_title}' -> '{target_mag}' "
                    f"({successful_flips}/{limit})"
                )
            else:
                logging.warning(f"  ✗ Flip failed for '{article_title}'.")

        except Exception as e:
            logging.error(f"  Error during trending flip attempt: {e}")

        time.sleep(4)
    logging.info(f"--- Finished Reflip. Flipped {successful_flips}/{limit} in {attempt} attempts. ---")

def flip_articles(articles: list, headless: bool, do_reflip: bool = False, reflip_limit: int = 3):
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
                try:
                    driver.save_screenshot("flipboard_login_error.png")
                    with open("flipboard_login_error.html", "w", encoding="utf-8") as f:
                        f.write(driver.page_source)
                except Exception: pass
                logging.error("You must run 'python scripts/save_flipboard_session.py' locally to create a valid session file.")
                sys.exit(1)
            
        # 2. Flip each article
        for i, art in enumerate(articles, 1):
            url = art["_full_url"]
            title = art["title"]
            logging.info(f"[{i}/{len(articles)}] Flipping: '{title}'")
            
            # Reset state for each article to ensure no stuck popups from previous runs
            driver.get("https://flipboard.com/")
            driver.refresh()
            time.sleep(3)
            
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
                try:
                    # Click the Create/Pencil icon
                    logging.info("  [Trace] Waiting for Create/Pencil icon to appear...")
                    time.sleep(2) # Give DOM a moment
                    
                    xpath = '//*[@aria-label="CREATE A FLIP"] | //*[@title="CREATE A FLIP"] | //*[contains(text(), "CREATE A FLIP")] | //*[@aria-label="Create a Flip"] | //*[@title="Create a Flip"] | //*[contains(text(), "Create a Flip")] | //*[@aria-label="CREATE"] | //*[@aria-label="Create"] | //button[contains(@aria-label, "Create") or contains(@aria-label, "Flip")] | //a[contains(@aria-label, "Create") or contains(@aria-label, "Flip")]'
                    
                    create_btns = driver.find_elements(By.XPATH, xpath)
                    visible_btns = [b for b in create_btns if b.is_displayed()]
                    
                    if visible_btns:
                        # Sort by Y-coordinate to ensure we click the one in the header, not a feed article
                        visible_btns.sort(key=lambda b: b.location['y'])
                        target_btn = visible_btns[0]
                        logging.info(f"  [Trace] Found {len(visible_btns)} Create/Pencil icons. Clicking the top-most one via JS...")
                        driver.execute_script("arguments[0].click();", target_btn)
                    else:
                        logging.warning("  [Trace] No visible Create/Pencil buttons found!")
                    
                    # Wait for the input field to appear and paste the URL
                    logging.info("  [Trace] Waiting for URL input field...")
                    url_input = WebDriverWait(driver, 5).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, 'input[placeholder*="URL" i], textarea[placeholder*="URL" i], input[placeholder*="link" i], textarea[placeholder*="link" i], input[type="url"], input[placeholder*="share" i], textarea[placeholder*="share" i], input[aria-label*="link" i], input[aria-label*="URL" i], textarea[aria-label*="link" i]'))
                    )
                    logging.info("  [Trace] Found URL input field, sending URL...")
                    url_input.send_keys(url)
                    
                    # Wait for the "Next" button to activate
                    logging.info("  [Trace] Waiting 4s for preview auto-fetch...")
                    time.sleep(4)
                    
                except Exception as ex:
                    logging.warning(f"  [Trace] URL input field did not appear ({type(ex).__name__}). Wrong button clicked?")
                    logging.info("  [Trace] Fallback: Navigating directly to Flipboard Share Popout URL...")
                    import urllib.parse
                    encoded_url = urllib.parse.quote(url)
                    encoded_title = urllib.parse.quote(title)
                    driver.get(f"https://share.flipboard.com/bookmarklet/popout?v=2&title={encoded_title}&url={encoded_url}")
                    time.sleep(4) # Let the share popout load
                
                if handle_flip_popup(driver, target_mag):
                    # Update Shopify Tag
                    mark_as_synced(art["_blog_id"], art["id"], art.get("tags", ""))
                else:
                    raise RuntimeError("Failed to complete flip inside popup modal.")
                
            except Exception as e:
                logging.error(f"  FAILED to flip article. Error: {str(e)}")
                
                # Debugging: Save screenshot and page source to figure out the UI
                debug_time = int(time.time())
                screenshot_file = f"flipboard_error_{debug_time}.png"
                html_file = f"flipboard_error_{debug_time}.html"
                try:
                    driver.save_screenshot(screenshot_file)
                    with open(html_file, "w", encoding="utf-8") as f:
                        f.write(driver.page_source)
                    logging.info(f"  [Debug] Saved screenshot to {screenshot_file} and HTML to {html_file}")
                except Exception as debug_e:
                    logging.error(f"  [Debug] Failed to save debug files: {debug_e}")
                
            time.sleep(2) # Brief pause between flips to act human
        
        if do_reflip:
            reflip_trending(driver, reflip_limit)

    finally:
        driver.quit()
        logging.info("Browser automation finished.")

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Automate flipping Shopify blogs to Flipboard.")
    ap.add_argument("--days", type=int, default=7, help="Sync articles published in the last X days.")
    ap.add_argument("--limit", type=int, default=10, help="Max articles to flip per run.")
    ap.add_argument("--dry-run", action="store_true", help="Print plan, do not flip.")
    ap.add_argument("--headed", action="store_true", help="Show browser window (helpful for initial setup).")
    ap.add_argument("--no-reflip", dest="reflip", action="store_false", help="Disable finding and re-flipping trending articles.")
    ap.add_argument("--reflip-limit", type=int, default=10, help="Max trending articles to re-flip.")
    ap.set_defaults(reflip=True)
    args = ap.parse_args()
    
    logging.info("="*60)
    logging.info(f" MeeeShop Flipboard Syndication — {datetime.now().strftime('%Y-%m-%d')}")
    logging.info("="*60)

    articles = fetch_articles(args.days, args.limit)
    
    is_fallback = False
    if not articles:
        logging.info("No new unsynced articles found matching criteria. Falling back to fetching old articles to re-flip...")
        articles = fetch_old_articles(limit=2)
        is_fallback = True
        
    if not articles and not args.reflip:
        logging.info("No new or old articles found matching criteria and reflip is disabled. Exiting.")
        sys.exit(0)
        
    if articles:
        if is_fallback:
            logging.info(f"Found {len(articles)} old article(s) to re-flip.")
        else:
            logging.info(f"Found {len(articles)} unsynced article(s) to process.")
            
    # Randomize trending articles count slightly for variability
    reflip_limit = args.reflip_limit
    if args.reflip and reflip_limit >= 2:
        reflip_limit = random.randint(max(2, reflip_limit - 2), reflip_limit)
    
    if args.dry_run:
        logging.info("--- DRY RUN MODE ---")
        test_flipboard_login(headless=not args.headed)
        if articles:
            if is_fallback:
                logging.info("Old articles that would be re-flipped:")
            else:
                logging.info("Articles that would be flipped:")
            for art in articles:
                logging.info(f"  - '{art['title']}' ({art['_full_url']})")
        if args.reflip:
            logging.info(f"Would also reflip up to {reflip_limit} trending articles.")
        logging.info("--- END DRY RUN ---")
    else:
        logging.info("--- LIVE MODE ---")
        flip_articles(articles, headless=not args.headed, do_reflip=args.reflip, reflip_limit=reflip_limit)
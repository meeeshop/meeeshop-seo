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
            
def handle_flip_popup(driver, target_mag):
    """Helper to handle the magazine selection popup and submitting the flip."""
    # Sometimes there's a "Next" button, sometimes it goes straight to magazine selection
    try:
        logging.info("  [Trace] Checking for 'Next' button...")
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
    time.sleep(2) # Wait for popup to render
    
    elements = driver.find_elements(By.XPATH, '//div | //span | //button | //h3 | //h4 | //p | //a')
    available_mags = []
    for el in elements:
        try:
            txt = driver.execute_script("return arguments[0].textContent;", el)
            if txt:
                txt = txt.strip()
                if len(txt) > 3:
                    available_mags.append((txt, el))
        except:
            pass
    
    mag_clicked = False
    
    def safe_click_mag(el, name):
        logging.info(f"  [Trace] Clicking magazine match: '{name}'")
        try:
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
            time.sleep(0.5)
            el.click()
        except Exception:
            driver.execute_script("arguments[0].click();", el)
    
    # 1. Try exact/partial match for target_mag (avoiding footwear)
    for txt, el in available_mags:
        if target_mag.lower() in txt.lower() and "footwear" not in txt.lower():
            safe_click_mag(el, txt)
            mag_clicked = True
            break
    
    # 2. Try fallback FLIPBOARD_MAGAZINE
    if not mag_clicked:
        logging.warning(f"  Magazine '{target_mag}' not found. Falling back to '{FLIPBOARD_MAGAZINE}'")
        for txt, el in available_mags:
            if FLIPBOARD_MAGAZINE.lower() in txt.lower() and "footwear" not in txt.lower():
                safe_click_mag(el, txt)
                mag_clicked = True
                break
                
    # 3. Try any known magazine except footwear
    if not mag_clicked:
        known_mags = set(MAGAZINE_ROUTING.values())
        known_mags.add(FLIPBOARD_MAGAZINE)
        logging.warning("  [Trace] Fallback not found. Trying ANY known magazine (avoiding footwear)...")
        for txt, el in available_mags:
            if "footwear" in txt.lower():
                continue
            for km in known_mags:
                if km.lower() in txt.lower() and "footwear" not in km.lower():
                    safe_click_mag(el, txt)
                    mag_clicked = True
                    break
            if mag_clicked:
                break
                
    # 4. Try any available item (since user simplified to 1 magazine)
    if not mag_clicked:
        logging.warning("  [Trace] Could not identify specific magazine. Clicking first available option for single-magazine setup...")
        mag_rows = driver.find_elements(By.CSS_SELECTOR, 'button[aria-label], div[role="button"], li[role="menuitem"], div[role="checkbox"]')
        for row in mag_rows:
            try:
                txt = driver.execute_script("return arguments[0].textContent;", row)
                if txt and len(txt.strip()) > 3 and txt.strip().lower() not in ["close", "cancel", "back", "next", "add", "flip"]:
                    safe_click_mag(row, txt.strip())
                    mag_clicked = True
                    break
            except: pass
                
    if not mag_clicked:
        logging.warning("  [Trace] Still could not identify any magazine to click. Relying on auto-selected default (if any).")
    
    time.sleep(2) # Let selection register
    
    # Click the final Next / Add / Flip / Done button
    logging.info("  [Trace] Looking for final Next/Add/Flip/Done button...")
    time.sleep(1) # Let UI settle
    flip_btns = driver.find_elements(By.XPATH, '//*[(self::button or @role="button" or self::a) and (contains(translate(text(),"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"), "next") or contains(translate(text(),"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"), "add") or contains(translate(text(),"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"), "flip") or contains(translate(text(),"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"), "create") or contains(translate(text(),"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"), "done") or contains(translate(text(),"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"), "save"))] | //*[contains(@aria-label, "Next") or contains(@aria-label, "Add") or contains(@aria-label, "Flip") or contains(@aria-label, "Done")]')
    
    if flip_btns:
        # Prefer enabled buttons that are displayed
        enabled_btns = [b for b in flip_btns if b.is_displayed() and not b.get_attribute("disabled")]
        target_btn = enabled_btns[-1] if enabled_btns else flip_btns[-1]
        
        logging.info("  [Trace] Found final button, clicking...")
        try:
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", target_btn)
            time.sleep(0.5)
            target_btn.click()
        except Exception:
            driver.execute_script("arguments[0].click();", target_btn)
    else:
        logging.warning("  [Trace] Could not find final button via XPath! Trying generic fallback...")
        # UI sometimes auto-saves on magazine selection now
        all_btns = driver.find_elements(By.XPATH, '//button[not(@disabled)]')
        fallback_btn = None
        for b in reversed(all_btns):
            try:
                if b.is_displayed() and b.text.strip().lower() in ["add", "done", "save", "next", "flip"]:
                    fallback_btn = b
                    break
            except: pass
        
        if fallback_btn:
            try:
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", fallback_btn)
                time.sleep(0.5)
                fallback_btn.click()
            except Exception:
                driver.execute_script("arguments[0].click();", fallback_btn)
            logging.info("  [Trace] Clicked fallback button by text.")
        else:
            logging.info("  [Trace] No obvious submit button found. Flipboard may have auto-flipped upon magazine selection.")
    
    # Wait for success toast/notification
    logging.info("  [Trace] Waiting 3s for success confirmation...")
    time.sleep(3)
    logging.info(f"  ✓ Flipped successfully.")

def reflip_trending(driver, limit):
    logging.info(f"--- Starting Reflip of Trending Articles (limit={limit}) ---")
    topic_mag_map = {
        "womensfashion": FLIPBOARD_MAGAZINE,
        "streetstyle": FLIPBOARD_MAGAZINE,
        "dresses": "Women's Dresses",
        "jeans": "Women's Jeans & Bottoms",
        "handbags": "Handbags",
        "shoes": "Women's footwear",
        "plussize": "Curvy | Plus Size Styles & Tips"
    }
    
    topics = list(topic_mag_map.keys())
    
    for i in range(limit):
        topic = random.choice(topics)
        target_mag = topic_mag_map.get(topic, FLIPBOARD_MAGAZINE)
        logging.info(f"[{i+1}/{limit}] Finding trending article in topic '{topic}' -> to mag '{target_mag}'...")
        
        try:
            driver.get(f"https://flipboard.com/topic/{topic}")
            time.sleep(6) # Let the feed load fully
            
            # Scroll down slightly to make sure articles render
            driver.execute_script("window.scrollBy(0, 500);")
            time.sleep(2)
            
            xpath = '//button[contains(@aria-label, "Flip") or contains(@title, "Flip") or @aria-label="Add to Magazine"] | //button//*[local-name()="svg" and contains(@aria-label, "Flip")]/ancestor::button'
            flip_btns = driver.find_elements(By.XPATH, xpath)
            
            visible_btns = [b for b in flip_btns if b.is_displayed()]
            
            if not visible_btns:
                fallback_xpath = '//article//button[contains(@class, "flip") or contains(@aria-label, "Add") or contains(@aria-label, "Save")]'
                article_btns = driver.find_elements(By.XPATH, fallback_xpath)
                visible_btns = [b for b in article_btns if b.is_displayed()]
            
            if not visible_btns:
                logging.warning(f"  [Trace] Could not find article flip buttons on topic '{topic}'. Skipping.")
                continue
                
            btn = random.choice(visible_btns[:min(5, len(visible_btns))])
            
            logging.info("  [Trace] Clicking Flip button on a trending article...")
            try:
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
                time.sleep(1)
                driver.execute_script("arguments[0].click();", btn)
            except Exception:
                btn.click()
                
            time.sleep(3)
            
            handle_flip_popup(driver, target_mag)
            
        except Exception as e:
            logging.error(f"Failed to reflip trending article: {e}")
            
        time.sleep(4)
        
    logging.info("--- Finished Reflip of Trending Articles ---")

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
                return
            
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
                
                # Sometimes there's a "Next" button, sometimes it goes straight to magazine selection
                try:
                    logging.info("  [Trace] Checking for 'Next' button...")
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
                time.sleep(2) # Wait for popup to render
                
                elements = driver.find_elements(By.XPATH, '//div | //span | //button | //h3 | //h4 | //p | //a')
                available_mags = []
                for el in elements:
                    try:
                        txt = driver.execute_script("return arguments[0].textContent;", el)
                        if txt:
                            txt = txt.strip()
                            if len(txt) > 3:
                                available_mags.append((txt, el))
                    except:
                        pass
                
                mag_clicked = False
                
                def safe_click_mag(el, name):
                    logging.info(f"  [Trace] Clicking magazine match: '{name}'")
                    try:
                        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
                        time.sleep(0.5)
                        el.click()
                    except Exception:
                        driver.execute_script("arguments[0].click();", el)
                
                # 1. Try exact/partial match for target_mag (avoiding footwear)
                for txt, el in available_mags:
                    if target_mag.lower() in txt.lower() and "footwear" not in txt.lower():
                        safe_click_mag(el, txt)
                        mag_clicked = True
                        break
                
                # 2. Try fallback FLIPBOARD_MAGAZINE
                if not mag_clicked:
                    logging.warning(f"  Magazine '{target_mag}' not found. Falling back to '{FLIPBOARD_MAGAZINE}'")
                    for txt, el in available_mags:
                        if FLIPBOARD_MAGAZINE.lower() in txt.lower() and "footwear" not in txt.lower():
                            safe_click_mag(el, txt)
                            mag_clicked = True
                            break
                            
                # 3. Try any known magazine except footwear
                if not mag_clicked:
                    known_mags = set(MAGAZINE_ROUTING.values())
                    known_mags.add(FLIPBOARD_MAGAZINE)
                    logging.warning("  [Trace] Fallback not found. Trying ANY known magazine (avoiding footwear)...")
                    for txt, el in available_mags:
                        if "footwear" in txt.lower():
                            continue
                        for km in known_mags:
                            if km.lower() in txt.lower() and "footwear" not in km.lower():
                                safe_click_mag(el, txt)
                                mag_clicked = True
                                break
                        if mag_clicked:
                            break
                            
                # 4. Try any available item (since user simplified to 1 magazine)
                if not mag_clicked:
                    logging.warning("  [Trace] Could not identify specific magazine. Clicking first available option for single-magazine setup...")
                    mag_rows = driver.find_elements(By.CSS_SELECTOR, 'button[aria-label], div[role="button"], li[role="menuitem"], div[role="checkbox"]')
                    for row in mag_rows:
                        try:
                            txt = driver.execute_script("return arguments[0].textContent;", row)
                            if txt and len(txt.strip()) > 3 and txt.strip().lower() not in ["close", "cancel", "back", "next", "add", "flip"]:
                                safe_click_mag(row, txt.strip())
                                mag_clicked = True
                                break
                        except: pass
                            
                if not mag_clicked:
                    logging.warning("  [Trace] Still could not identify any magazine to click. Relying on auto-selected default (if any).")
                
                time.sleep(2) # Let selection register
                
                # Click the final Next / Add / Flip / Done button
                logging.info("  [Trace] Looking for final Next/Add/Flip/Done button...")
                time.sleep(1) # Let UI settle
                flip_btns = driver.find_elements(By.XPATH, '//*[(self::button or @role="button" or self::a) and (contains(translate(text(),"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"), "next") or contains(translate(text(),"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"), "add") or contains(translate(text(),"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"), "flip") or contains(translate(text(),"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"), "create") or contains(translate(text(),"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"), "done") or contains(translate(text(),"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"), "save"))] | //*[contains(@aria-label, "Next") or contains(@aria-label, "Add") or contains(@aria-label, "Flip") or contains(@aria-label, "Done")]')
                
                if flip_btns:
                    # Prefer enabled buttons that are displayed
                    enabled_btns = [b for b in flip_btns if b.is_displayed() and not b.get_attribute("disabled")]
                    target_btn = enabled_btns[-1] if enabled_btns else flip_btns[-1]
                    
                    logging.info("  [Trace] Found final button, clicking...")
                    try:
                        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", target_btn)
                        time.sleep(0.5)
                        target_btn.click()
                    except Exception:
                        driver.execute_script("arguments[0].click();", target_btn)
                else:
                    logging.warning("  [Trace] Could not find final button via XPath! Trying generic fallback...")
                    # UI sometimes auto-saves on magazine selection now
                    all_btns = driver.find_elements(By.XPATH, '//button[not(@disabled)]')
                    fallback_btn = None
                    for b in reversed(all_btns):
                        try:
                            if b.is_displayed() and b.text.strip().lower() in ["add", "done", "save", "next", "flip"]:
                                fallback_btn = b
                                break
                        except: pass
                    
                    if fallback_btn:
                        try:
                            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", fallback_btn)
                            time.sleep(0.5)
                            fallback_btn.click()
                        except Exception:
                            driver.execute_script("arguments[0].click();", fallback_btn)
                        logging.info("  [Trace] Clicked fallback button by text.")
                    else:
                        logging.info("  [Trace] No obvious submit button found. Flipboard may have auto-flipped upon magazine selection.")
                
                # Wait for success toast/notification
                logging.info("  [Trace] Waiting 3s for success confirmation...")
                time.sleep(3)
                logging.info(f"  ✓ Flipped successfully.")
                
                # Update Shopify Tag
                mark_as_synced(art["_blog_id"], art["id"], art.get("tags", ""))
                
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
    ap.add_argument("--reflip", action="store_true", help="Also find and re-flip trending articles related to our niche to boost magazine visibility.")
    ap.add_argument("--reflip-limit", type=int, default=3, help="Max trending articles to re-flip.")
    args = ap.parse_args()
    
    logging.info("="*60)
    logging.info(f" MeeeShop Flipboard Syndication — {datetime.now().strftime('%Y-%m-%d')}")
    logging.info("="*60)

    articles = fetch_articles(args.days, args.limit)
    
    if not articles and not args.reflip:
        logging.info("No new unsynced articles found matching criteria and reflip is disabled. Exiting.")
        sys.exit(0)
        
    if articles:
        logging.info(f"Found {len(articles)} unsynced article(s) to process.")
    
    if args.dry_run:
        logging.info("--- DRY RUN MODE ---")
        test_flipboard_login(headless=not args.headed)
        if articles:
            logging.info("Articles that would be flipped:")
            for art in articles:
                logging.info(f"  - '{art['title']}' ({art['_full_url']})")
        if args.reflip:
            logging.info(f"Would also reflip up to {args.reflip_limit} trending articles.")
        logging.info("--- END DRY RUN ---")
    else:
        logging.info("--- LIVE MODE ---")
        flip_articles(articles, headless=not args.headed, do_reflip=args.reflip, reflip_limit=args.reflip_limit)
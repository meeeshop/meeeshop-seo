#!/usr/bin/env python3
"""
sync_to_flipboard.py — Automate flipping Shopify blogs to Flipboard
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Optimized for US Women Shoppers & Aligned with MeeeShop Blog Automation:
  1. STEP 1 (FIRST): Flip 2-3 trending high-authority women's fashion articles
     strictly matching our product types (dresses, denim, curvy, outerwear, vegan).
  2. STEP 2 (LAST): Flip newly published / staggered MeeeShop store articles
     so MeeeShop content sits at the VERY TOP of magazines and followers' feeds.
  3. Clean HTML entities & high-CTR fashion hashtags (#Style #OOTD #WomensFashion).
  4. Multi-stage staggered syndication across targeted category magazines.

Usage:
  python scripts/sync_to_flipboard.py             # Live sync (Trending first, MeeeShop last)
  python scripts/sync_to_flipboard.py --dry-run   # Preview flips without posting
  python scripts/sync_to_flipboard.py --headed    # Run with visible browser
"""

import logging
import os
import json
import sys
import time
import random
import argparse
import requests
import html
import re
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

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

# ── Category to Flipboard Magazine Routing ─────────────────────────────────────
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
    "blazer": "Trending Clothing Tips & Styles For Women",
    "activewear": "Trending Clothing Tips & Styles For Women",
    "swimwear": "Trending Clothing Tips & Styles For Women"
}

# ── Curated Trending Topic Feeds Matching Women's Fashion & Product Lines ──────
TRENDING_TOPIC_CONFIGS = [
    {
        "topics": ["streetstyle", "fashion-trends", "capsule-wardrobe", "fall-fashion", "summer-fashion"],
        "target_mag": "Trending Clothing Tips & Styles For Women",
        "hashtags": "#WomensFashion #StreetStyle #OutfitInspo #FashionTrends #Style"
    },
    {
        "topics": ["denim", "jeans"],
        "target_mag": "Women's Jeans & Bottoms",
        "hashtags": "#DenimOutfits #Jeans #CasualChic #OutfitIdeas #Style"
    },
    {
        "topics": ["plus-size", "plussize"],
        "target_mag": "Curvy | Plus Size Styles & Tips",
        "hashtags": "#PlusSizeFashion #CurvyStyle #BodyPositive #StyleInspo"
    },
    {
        "topics": ["sustainable-fashion", "sustainablefashion"],
        "target_mag": "Veganism | Eco-Friendly & Sustainable",
        "hashtags": "#SustainableFashion #EcoFriendly #ConsciousStyle #SlowFashion"
    },
    {
        "topics": ["capsule-wardrobe", "fashion-trends", "fall-fashion"],
        "target_mag": "Women's Dresses",
        "hashtags": "#Dresses #DressStyle #OOTD #SummerOutfits #Style"
    }
]

EXCLUDE_TOPIC_WORDS = [
    "men's", "menswear", "mens", "male", "guys", "his ", "groom", "boy", "father", "husband", "men fashion", "men shoes",
    "politics", "election", "biden", "trump", "crypto", "bitcoin", "tech", "gadget", "gaming",
    "football", "nba", "nfl", "pga", "bmw", "golf", "uniform", "tucson", "hyundai", "car ", "auto", "nascar"
]

POSITIVE_FASHION_WORDS = [
    "style", "fashion", "dress", "skirt", "jean", "denim", "outfit", "wardrobe", "wear", "chic",
    "trend", "jacket", "coat", "blazer", "pant", "trouser", "top", "blouse", "knit", "sweater",
    "cardigan", "curvy", "plus size", "fall", "summer", "spring", "winter", "staple", "capsule", "looks"
]

if not all([SHOP_TOKEN, FLIPBOARD_EMAIL, FLIPBOARD_PASSWORD, SHOP]):
    logging.error("Missing required secrets: SHOPIFY_STORE, SHOPIFY_ACCESS_TOKEN, FLIPBOARD_EMAIL, FLIPBOARD_PASSWORD")
    sys.exit(1)

UTM_TRACKING = "utm_source=flipboard&utm_medium=syndication&utm_campaign=flipboard_daily"

# ── Shopify & Caption Helpers ──────────────────────────────────────────────────
def clean_html_text(raw_html: str) -> str:
    """Strip HTML tags, unescape HTML entities, and condense whitespace."""
    if not raw_html:
        return ""
    unescaped = html.unescape(raw_html)
    clean = re.sub(r'<[^>]+>', ' ', unescaped)
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean

def generate_flip_caption(art: dict) -> str:
    """Generate an engaging caption with high-traffic, category-matched fashion hashtags."""
    title = html.unescape(art.get("title", ""))
    summary = clean_html_text(art.get("summary_html", ""))
    body = clean_html_text(art.get("body_html", ""))

    excerpt = summary if summary else body
    if len(excerpt) > 130:
        excerpt = excerpt[:127] + "..."

    tags = [t.strip().lower() for t in (art.get("tags") or "").split(",") if t.strip()]
    text_corpus = f"{title} {excerpt} {' '.join(tags)}".lower()

    # Product-type specific hashtag prioritization
    if any(k in text_corpus for k in ["cardigan", "sweater", "knitwear", "knit", "pullover"]):
        hashtags = ["#Cardigans", "#SweaterStyle", "#Knitwear", "#OutfitIdeas"]
    elif any(k in text_corpus for k in ["blazer", "jacket", "coat", "outerwear", "shacket"]):
        hashtags = ["#BlazerStyle", "#Jackets", "#Outerwear", "#ChicStyle"]
    elif any(k in text_corpus for k in ["dress", "maxi", "midi", "sundress"]):
        hashtags = ["#Dresses", "#DressStyle", "#OOTD", "#SummerOutfits"]
    elif any(k in text_corpus for k in ["skirt"]):
        hashtags = ["#Skirts", "#SkirtStyle", "#OOTD", "#OutfitInspo"]
    elif any(k in text_corpus for k in ["jean", "denim"]):
        hashtags = ["#Jeans", "#DenimOutfits", "#CasualStyle", "#DenimStyle"]
    elif any(k in text_corpus for k in ["pant", "trouser", "slack"]):
        hashtags = ["#TailoredPants", "#Trousers", "#WorkwearStyle", "#Chic"]
    elif any(k in text_corpus for k in ["plus", "curvy"]):
        hashtags = ["#PlusSizeFashion", "#CurvyStyle", "#BodyPositive", "#StyleInspo"]
    elif any(k in text_corpus for k in ["vegan", "eco", "sustainable", "plant-based"]):
        hashtags = ["#SustainableFashion", "#EcoFriendly", "#ConsciousStyle", "#SlowFashion"]
    elif any(k in text_corpus for k in ["top", "blouse", "shirt", "tee"]):
        hashtags = ["#WomensTops", "#BlouseStyle", "#EverydayStyle", "#OOTD"]
    elif any(k in text_corpus for k in ["bag", "handbag", "purse"]):
        hashtags = ["#Handbags", "#Accessories", "#BoutiqueBags"]
    elif any(k in text_corpus for k in ["shoe", "boot", "sandal", "sneaker", "footwear"]):
        hashtags = ["#Footwear", "#ShoeStyle", "#ChicShoes"]
    else:
        hashtags = ["#Style", "#FashionTrends", "#WomenStyle", "#OutfitIdeas"]

    unique_tags = list(dict.fromkeys(hashtags))
    hashtag_str = " ".join(unique_tags)

    if excerpt:
        return f"{excerpt} {hashtag_str}"
    else:
        return f"{title} {hashtag_str}"

def determine_staggered_target(art: dict):
    """
    Determine target magazine and next tag based on staggering stage.
    Stage 1: Main Magazine ('Trending Clothing Tips & Styles For Women') -> tag 'flipboard_mag1_synced'
    Stage 2: Category Magazine ('Women's Dresses', 'Women's Jeans & Bottoms', etc.) -> tag 'flipboard_mag2_synced'
    Stage 3: Lifestyle / Topic Magazine -> tag 'flipboard_synced' (complete)
    """
    tags = [t.strip() for t in (art.get("tags") or "").split(",") if t.strip()]
    tags_lower = [t.lower() for t in tags]

    if "flipboard_mag2_synced" in tags_lower:
        stage = 3
        tag_to_apply = "flipboard_synced"
        if any(k in t for t in tags_lower for k in ["plus", "curvy"]):
            target_mag = "Curvy | Plus Size Styles & Tips"
        elif any(k in t for t in tags_lower for k in ["vegan", "eco", "sustainable"]):
            target_mag = "Veganism | Eco-Friendly & Sustainable"
        else:
            target_mag = FLIPBOARD_MAGAZINE
    elif "flipboard_mag1_synced" in tags_lower:
        stage = 2
        tag_to_apply = "flipboard_mag2_synced"
        target_mag = FLIPBOARD_MAGAZINE
        for t in tags_lower:
            for kw, mag in MAGAZINE_ROUTING.items():
                if kw in t:
                    target_mag = mag
                    break
            if target_mag != FLIPBOARD_MAGAZINE:
                break
        if target_mag == FLIPBOARD_MAGAZINE:
            title_handle = f"{art.get('title','')} {art.get('handle','')}".lower()
            for kw, mag in MAGAZINE_ROUTING.items():
                if kw in title_handle:
                    target_mag = mag
                    break
    else:
        stage = 1
        tag_to_apply = "flipboard_mag1_synced"
        target_mag = FLIPBOARD_MAGAZINE

    return stage, target_mag, tag_to_apply

def fetch_articles(days: int, limit: int) -> list:
    """Fetch Shopify articles for staggered multi-stage magazine syndication."""
    logging.info(f"Fetching Shopify articles from last {days} days for staggered syndication...")
    r = requests.get(f"{SHOP_BASE}/blogs.json", headers=SHOP_HEADERS)
    r.raise_for_status()
    blogs = r.json().get("blogs", [])
    logging.info(f"Found {len(blogs)} blog(s)")

    all_articles = []
    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    for blog in blogs:
        blog_id = blog["id"]
        blog_handle = blog["handle"]
        if blog_handle == "announcements":
            continue
        params = {"limit": 250, "published_at_min": cutoff_date}
        try:
            r = requests.get(f"{SHOP_BASE}/blogs/{blog_id}/articles.json", headers=SHOP_HEADERS, params=params)
            r.raise_for_status()
            for art in r.json().get("articles", []):
                art["_full_url"] = f"{STORE_URL}/blogs/{blog_handle}/{art['handle']}?{UTM_TRACKING}"
                art["_blog_id"] = blog_id
                all_articles.append(art)
        except Exception as e:
            logging.warning(f"  Failed to fetch articles from blog {blog_id}: {e}")

    all_articles.sort(key=lambda x: x.get("published_at") or "", reverse=True)

    pending = []
    now = datetime.now(timezone.utc)
    for art in all_articles:
        tags = [t.strip().lower() for t in (art.get("tags") or "").split(",") if t.strip()]
        if "flipboard_synced" in tags:
            continue

        pub_at_str = art.get("published_at") or ""
        try:
            pub_at = datetime.fromisoformat(pub_at_str.replace("Z", "+00:00"))
            age_days = (now - pub_at).total_seconds() / 86400.0
        except Exception:
            age_days = 0.0

        stage, target_mag, next_tag = determine_staggered_target(art)
        art["_stagger_stage"] = stage
        art["_target_mag"] = target_mag
        art["_next_tag"] = next_tag
        art["_caption"] = generate_flip_caption(art)

        # Stage 1: unsynced -> immediate flip
        if stage == 1:
            pending.append(art)
        # Stage 2: mag1 synced -> wait 1+ days before mag2 flip
        elif stage == 2 and age_days >= 1.0:
            pending.append(art)
        # Stage 3: mag2 synced -> wait 3+ days before mag3 flip
        elif stage == 3 and age_days >= 3.0:
            pending.append(art)

    logging.info(f"Found {len(pending)} MeeeShop article(s) ready for staggered flip.")
    return pending[:limit]

def fetch_old_articles(limit: int = 2) -> list:
    """
    Fetch high-performing evergreen Shopify articles (> 7 days old) across different
    categories for safe daily syndication on non-publishing days (June Strategy).
    """
    logging.info("Fetching evergreen Shopify articles (>7 days old) across categories...")
    try:
        r = requests.get(f"{SHOP_BASE}/blogs.json", headers=SHOP_HEADERS)
        r.raise_for_status()
        blogs = [b for b in r.json().get("blogs", []) if b.get("handle") != "announcements"]
    except Exception as e:
        logging.error(f"Failed to fetch blogs for evergreen articles: {e}")
        return []

    articles_by_cat = {}
    now = datetime.now(timezone.utc)

    for blog in blogs:
        b_id = blog["id"]
        b_handle = blog["handle"]
        params = {"limit": 50}
        try:
            r = requests.get(f"{SHOP_BASE}/blogs/{b_id}/articles.json", headers=SHOP_HEADERS, params=params)
            r.raise_for_status()
            articles_batch = r.json().get("articles", [])
        except Exception:
            continue

        for art in articles_batch:
            pub_at_str = art.get("published_at") or ""
            try:
                pub_at = datetime.fromisoformat(pub_at_str.replace("Z", "+00:00"))
                age_days = (now - pub_at).total_seconds() / 86400.0
            except Exception:
                age_days = 0

            # Eligible if published > 7 days ago
            if age_days >= 7:
                target_mag = FLIPBOARD_MAGAZINE
                title_text = f"{art.get('title','')} {art.get('tags','')}".lower()
                for kw, mag in MAGAZINE_ROUTING.items():
                    if kw in title_text or kw in b_handle:
                        target_mag = mag
                        break

                art["_full_url"] = f"{STORE_URL}/blogs/{b_handle}/{art['handle']}?{UTM_TRACKING}"
                art["_blog_id"] = b_id
                art["_stagger_stage"] = 3
                art["_target_mag"] = target_mag
                art["_next_tag"] = "flipboard_synced"
                art["_caption"] = generate_flip_caption(art)
                art["_cat_handle"] = b_handle

                if b_handle not in articles_by_cat:
                    articles_by_cat[b_handle] = []
                articles_by_cat[b_handle].append(art)

    if not articles_by_cat:
        return []

    # Select limit articles from different categories to ensure diversity
    available_cats = list(articles_by_cat.keys())
    random.shuffle(available_cats)

    selected = []
    for cat in available_cats:
        if len(selected) >= limit:
            break
        art_choice = random.choice(articles_by_cat[cat])
        selected.append(art_choice)

    logging.info(f"Selected {len(selected)} diverse evergreen MeeeShop article(s) for daily syndication.")
    return selected

def mark_as_synced(blog_id: int, article_id: int, existing_tags: str, tag_to_add: str = "flipboard_synced"):
    """Add progressive flipboard tag (e.g. flipboard_mag1_synced, flipboard_mag2_synced, or flipboard_synced)."""
    tags = [t.strip() for t in (existing_tags or "").split(",") if t.strip()]
    if tag_to_add not in tags:
        tags.append(tag_to_add)
        payload = {"article": {"id": article_id, "tags": ", ".join(tags)}}
        r = requests.put(f"{SHOP_BASE}/blogs/{blog_id}/articles/{article_id}.json", headers=SHOP_HEADERS, json=payload)
        if not r.ok:
            logging.warning(f"Failed to tag Shopify article with '{tag_to_add}': {r.text}")
        else:
            logging.info(f"  [Shopify] Tagged article #{article_id} with '{tag_to_add}'.")

# ── Flipboard Browser Automation ───────────────────────────────────────────────
def human_delay(min_sec: float = 1.0, max_sec: float = 3.0):
    """Pause execution with a random delay to emulate human thinking time."""
    time.sleep(random.uniform(min_sec, max_sec))

def human_type(element, text: str):
    """Type text into a web element with variable keystroke timing."""
    for char in text:
        element.send_keys(char)
        time.sleep(random.uniform(0.03, 0.11))
        if char in [" ", ".", ",", "#"]:
            time.sleep(random.uniform(0.08, 0.22))

def human_scroll(driver, distance: int = 400):
    """Smooth scroll down the page mimicking a human reading a feed."""
    steps = random.randint(3, 6)
    step_dist = distance // steps
    for _ in range(steps):
        driver.execute_script(f"window.scrollBy(0, {step_dist + random.randint(-15, 15)});")
        time.sleep(random.uniform(0.2, 0.5))

def pre_flip_browse_behavior(driver):
    """Simulate a real fashion user browsing Flipboard feeds before making a flip."""
    try:
        logging.info("  [Stealth] Simulating natural user feed browsing on Flipboard...")
        topic = random.choice(["style", "fashion", "jeans", "dresses", "curvy", "streetstyle"])
        driver.get(f"https://flipboard.com/topic/{topic}")
        human_delay(2.5, 4.5)
        human_scroll(driver, random.randint(300, 500))
        human_delay(2.0, 3.5)
    except Exception as e:
        logging.info(f"  [Stealth] Pre-flip browse note: {e}")

def get_browser(headless=True):
    """Create a stealth Chrome webdriver mimicking a real desktop browser."""
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

    options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    options.add_experimental_option('useAutomationExtension', False)

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)

    stealth_js = """
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
    Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
    window.chrome = { runtime: {} };
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) => (
        parameters.name === 'notifications' ?
        Promise.resolve({ state: Notification.permission }) :
        originalQuery(parameters)
    );
    """
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": stealth_js})
    return driver

def load_session_cookies(driver):
    if FLIPBOARD_SESSION:
        try:
            driver.get("https://flipboard.com/404")
            human_delay(1.0, 2.0)
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
    human_delay(3.0, 5.0)

    logging.info("Entering credentials with human typing timing...")
    try:
        email_loc = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'input[name="username"], input[type="email"], input[name="email"]'))
        )
    except TimeoutException:
        try:
            email_btn = driver.find_element(By.XPATH, '//*[(self::button or self::a) and (contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "email") or contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "log in"))]')
            driver.execute_script("arguments[0].click();", email_btn)
            human_delay(1.0, 2.0)
        except Exception as e:
            logging.warning(f"Could not find email login button: {type(e).__name__}")

        email_loc = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'input[name="username"], input[type="email"], input[name="email"]'))
        )

    try:
        driver.execute_script("arguments[0].click();", email_loc)
    except Exception:
        email_loc.click()

    human_delay(0.5, 1.2)
    human_type(email_loc, FLIPBOARD_EMAIL)
    human_delay(1.0, 2.0)

    pass_loc = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, 'input[name="password"], input[type="password"]'))
    )
    try:
        driver.execute_script("arguments[0].click();", pass_loc)
    except Exception:
        pass_loc.click()

    human_delay(0.5, 1.0)
    human_type(pass_loc, FLIPBOARD_PASSWORD)
    human_delay(1.0, 2.0)

    submit_btn = driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]')
    try:
        submit_btn.click()
    except Exception:
        driver.execute_script("arguments[0].click();", submit_btn)

    logging.info("Waiting for login confirmation...")
    WebDriverWait(driver, 20).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, '[aria-label="Profile"], [aria-label="Create a Flip"], [aria-label="Create"], a[href^="/@"]'))
    )
    human_delay(2.0, 4.0)

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
    buttons = driver.find_elements(By.CSS_SELECTOR, 'button[data-vars-button-name="flip-compose-magazine"]')
    if not buttons:
        buttons = driver.find_elements(By.CSS_SELECTOR, 'div.magazine-selection__magazine, .magazine-selection__magazine')

    for btn in buttons:
        try:
            txt = driver.execute_script("return arguments[0].textContent;", btn)
            if txt:
                txt_clean = txt.strip()
                name = txt_clean.split("Created")[0].strip()
                if target_mag.lower() in name.lower() or name.lower() in target_mag.lower():
                    return btn, name
        except Exception:
            pass
    return None, None

def handle_flip_popup(driver, target_mag, caption=None):
    """Helper to handle the magazine selection popup and submitting the flip."""
    if caption:
        try:
            comment_fields = driver.find_elements(By.CSS_SELECTOR, 'textarea[placeholder*="comment" i], textarea[placeholder*="say" i], textarea[placeholder*="note" i], textarea[placeholder*="caption" i], textarea.share-flip__comment')
            for cf in comment_fields:
                if cf.is_displayed() and not cf.get_attribute("value"):
                    logging.info("  [Trace] Injecting caption into comment field...")
                    cf.send_keys(caption)
                    time.sleep(0.5)
                    break
        except Exception as e:
            logging.info(f"  [Trace] Could not inject comment field: {e}")

    magazine_visible = False
    try:
        mags = driver.find_elements(By.CSS_SELECTOR, 'button[data-vars-button-name="flip-compose-magazine"], div.magazine-selection__magazine, .magazine-selection__magazine')
        if any(m.is_displayed() for m in mags):
            magazine_visible = True
            logging.info("  [Trace] Magazine list is already visible. Skipping 'Next' button.")
    except Exception:
        pass

    if not magazine_visible:
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

    logging.info(f"  [Trace] Looking for target magazine '{target_mag}'...")
    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((
                By.CSS_SELECTOR, 
                'button[data-vars-button-name="flip-compose-magazine"], div.magazine-selection__magazine, .magazine-selection__magazine'
            ))
        )
    except Exception as e:
        logging.warning(f"  [Trace] Timeout waiting for magazine list to render: {e}")

    # Check for Expand button to reveal full list of magazines
    try:
        expand_btns = driver.find_elements(By.XPATH, '//*[(self::button or self::a or self::span or self::div) and (translate(text(), "EXPAND", "expand")="expand" or contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "expand"))]')
        for btn in expand_btns:
            if btn.is_displayed():
                logging.info("  [Trace] Found 'Expand' button, clicking to reveal all magazines...")
                try:
                    driver.execute_script("arguments[0].click();", btn)
                except Exception:
                    btn.click()
                time.sleep(2)
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

    # 1. Target Magazine
    btn, name = find_magazine_element(driver, target_mag)
    if btn:
        if "footwear" in target_mag.lower() or "footwear" not in name.lower():
            safe_click_mag(btn, name)
            mag_clicked = True
            clicked_name = name

    # 2. Fallback FLIPBOARD_MAGAZINE
    if not mag_clicked:
        logging.warning(f"  Magazine '{target_mag}' not found. Falling back to '{FLIPBOARD_MAGAZINE}'")
        btn, name = find_magazine_element(driver, FLIPBOARD_MAGAZINE)
        if btn and "footwear" not in name.lower():
            safe_click_mag(btn, name)
            mag_clicked = True
            clicked_name = name

    # 3. Any known fashion magazine
    if not mag_clicked:
        known_mags = set(MAGAZINE_ROUTING.values())
        known_mags.add(FLIPBOARD_MAGAZINE)
        for km in known_mags:
            if "footwear" in km.lower():
                continue
            btn, name = find_magazine_element(driver, km)
            if btn and "footwear" not in name.lower():
                safe_click_mag(btn, name)
                mag_clicked = True
                clicked_name = name
                break

    # 4. First available option
    if not mag_clicked:
        buttons = driver.find_elements(By.CSS_SELECTOR, 'button[data-vars-button-name="flip-compose-magazine"], div.magazine-selection__magazine, .magazine-selection__magazine')
        if buttons:
            btn = buttons[0]
            try:
                name = driver.execute_script("return arguments[0].textContent;", btn).split("Created")[0].strip()
            except Exception:
                name = "First available magazine"
            safe_click_mag(btn, name)
            mag_clicked = True
            clicked_name = name

    time.sleep(2)

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

    if not button_clicked and mag_clicked:
        button_clicked = True

    if button_clicked:
        logging.info("  [Trace] Waiting 3s for success confirmation...")
        time.sleep(3)

        modal_still_open = False
        try:
            modals = driver.find_elements(By.CSS_SELECTOR, 'div[role="dialog"], .modal, .magazine-selection')
            if any(m.is_displayed() for m in modals):
                modal_still_open = True
        except Exception:
            pass

        saw_toast = False
        try:
            toasts = driver.find_elements(By.XPATH, '//*[contains(text(), "Flipped") or contains(text(), "Added to") or contains(text(), "Saved to")]')
            if any(t.is_displayed() for t in toasts):
                saw_toast = True
                logging.info(f"  [Trace] Found success toast notification.")
        except Exception:
            pass

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

# ── STEP 1: Flip Trending Women's Fashion Articles (Matching Product Lines) ────
def reflip_trending_women_fashion(driver, limit: int = 3):
    """
    Step 1: Flips 2-3 trending high-authority women's fashion articles matching
    our product lines FIRST so magazines are active and curated before store articles are flipped.
    """
    logging.info(f"\n{'='*70}")
    logging.info(f"  STEP 1: Curating {limit} Trending Women's Fashion Articles FIRST")
    logging.info(f"{'='*70}")

    shuffled_configs = list(TRENDING_TOPIC_CONFIGS)
    random.shuffle(shuffled_configs)

    successful_flips = 0
    attempt = 0
    max_attempts = 15

    def fetch_curated_fashion_candidates(topics: list) -> list:
        """Fetches and filters strictly women's fashion articles from Flipboard RSS feeds."""
        candidates = []
        for topic in topics:
            rss_url = f"https://flipboard.com/topic/{topic}.rss"
            try:
                resp = requests.get(rss_url, timeout=10, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
                if not resp.ok:
                    continue
                root = ET.fromstring(resp.text)
                for item in root.findall(".//item"):
                    title = (item.find("title").text or "").strip() if item.find("title") is not None else ""
                    link = (item.find("link").text or "").strip() if item.find("link") is not None else ""
                    title_clean = html.unescape(title)
                    t_normalized = title_clean.lower().replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')

                    if title_clean and link and len(title_clean) > 12 and "flipboard.com" not in link:
                        # Exclude non-women's fashion
                        if not any(re.search(r'\b' + re.escape(ex.strip()) + r'\b', t_normalized) or ex in t_normalized for ex in EXCLUDE_TOPIC_WORDS):
                            # Ensure positive fashion relevance
                            if any(pw in t_normalized for pw in POSITIVE_FASHION_WORDS):
                                candidates.append((link, title_clean))
            except Exception:
                pass
        return candidates

    for cfg in shuffled_configs:
        if successful_flips >= limit or attempt >= max_attempts:
            break
        attempt += 1
        target_mag = cfg["target_mag"]
        hashtags = cfg["hashtags"]
        logging.info(f"[{successful_flips + 1}/{limit}] Sourcing trending content for '{target_mag}'...")

        candidates = fetch_curated_fashion_candidates(cfg["topics"])
        if not candidates:
            logging.warning(f"  No valid candidates found for topics {cfg['topics']}. Trying next category...")
            continue

        article_url, article_title = random.choice(candidates[:min(10, len(candidates))])
        logging.info(f"  Selected: '{article_title}'")
        trending_caption = f"{article_title} {hashtags}"

        try:
            encoded_url = urllib.parse.quote(article_url, safe="")
            encoded_title = urllib.parse.quote(article_title, safe="")
            encoded_comment = urllib.parse.quote(trending_caption, safe="")
            popout_url = (
                f"https://share.flipboard.com/bookmarklet/popout"
                f"?v=2&title={encoded_title}&url={encoded_url}&comment={encoded_comment}"
            )
            driver.get(popout_url)
            time.sleep(4)

            if handle_flip_popup(driver, target_mag, caption=trending_caption):
                successful_flips += 1
                logging.info(f"  ✓ Successfully flipped trending piece -> '{target_mag}' ({successful_flips}/{limit})")
            else:
                logging.warning(f"  ✗ Trending flip failed for '{article_title}'.")
        except Exception as e:
            logging.error(f"  Error during trending flip attempt: {e}")

        time.sleep(random.uniform(3.0, 5.0))

    logging.info(f"--- Step 1 Finished: Curated {successful_flips}/{limit} trending articles. ---\n")

# ── STEP 2: Flip MeeeShop Store Articles (Remain at TOP of Magazine) ───────────
def flip_articles(articles: list, headless: bool, do_reflip: bool = True, reflip_limit: int = 3):
    """
    Executes full Flipboard syndication sequence:
      1. Flip trending women's fashion articles FIRST
      2. Flip MeeeShop store articles LAST so they stay at the very top of feeds!
    """
    logging.info("Starting stealth browser automation for Flipboard syndication...")
    driver = get_browser(headless)

    try:
        load_session_cookies(driver)

        logging.info("Attempting Flipboard login check...")
        driver.get("https://flipboard.com/")
        try:
            WebDriverWait(driver, 7).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, '[aria-label="Profile"], [aria-label="Create a Flip"], [aria-label="Create"], a[href^="/@"]'))
            )
            logging.info("✅ Login successful (via saved session).")
        except TimeoutException:
            logging.info("Session expired. Falling back to credential login.")
            try:
                perform_login(driver)
                logging.info("✅ Login successful (via credentials).")
            except Exception as e:
                logging.error(f"❌ Login with credentials failed: {e}")
                sys.exit(1)

        # Human browse simulation
        pre_flip_browse_behavior(driver)

        # STEP 1 (FIRST): Flip Trending Women's Fashion Articles
        if do_reflip and reflip_limit > 0:
            reflip_trending_women_fashion(driver, limit=reflip_limit)
            logging.info("Pausing before flipping MeeeShop store articles...")
            time.sleep(random.uniform(5.0, 8.0))

        # STEP 2 (LAST): Flip MeeeShop Store Articles
        if articles:
            logging.info(f"\n{'='*70}")
            logging.info(f"  STEP 2: Flipping {len(articles)} MeeeShop Store Articles (To Remain at TOP)")
            logging.info(f"{'='*70}")

            for i, art in enumerate(articles, 1):
                url = art["_full_url"]
                title = html.unescape(art["title"])
                target_mag = art.get("_target_mag", FLIPBOARD_MAGAZINE)
                next_tag = art.get("_next_tag", "flipboard_synced")
                stage = art.get("_stagger_stage", 1)
                caption = art.get("_caption", f"{title} #Style #FashionTrends")

                logging.info(f"[{i}/{len(articles)}] Flipping Stage {stage}: '{title}' -> Mag: '{target_mag}'")
                logging.info(f"  Caption: {caption}")

                driver.get("https://flipboard.com/")
                driver.refresh()
                time.sleep(3)

                try:
                    # Attempt via main site Create/Pencil icon
                    try:
                        time.sleep(2)
                        xpath = '//*[@aria-label="CREATE A FLIP"] | //*[@title="CREATE A FLIP"] | //*[contains(text(), "CREATE A FLIP")] | //*[@aria-label="Create a Flip"] | //*[@title="Create a Flip"] | //*[contains(text(), "Create a Flip")] | //*[@aria-label="CREATE"] | //*[@aria-label="Create"] | //button[contains(@aria-label, "Create") or contains(@aria-label, "Flip")] | //a[contains(@aria-label, "Create") or contains(@aria-label, "Flip")]'
                        create_btns = driver.find_elements(By.XPATH, xpath)
                        visible_btns = [b for b in create_btns if b.is_displayed()]

                        if visible_btns:
                            visible_btns.sort(key=lambda b: b.location['y'])
                            driver.execute_script("arguments[0].click();", visible_btns[0])

                        url_input = WebDriverWait(driver, 5).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, 'input[placeholder*="URL" i], textarea[placeholder*="URL" i], input[placeholder*="link" i], textarea[placeholder*="link" i], input[type="url"], input[placeholder*="share" i], textarea[placeholder*="share" i], input[aria-label*="link" i], input[aria-label*="URL" i], textarea[aria-label*="link" i]'))
                        )
                        url_input.send_keys(url)
                        time.sleep(4)
                    except Exception:
                        # Reliable Share Popout fallback
                        encoded_url = urllib.parse.quote(url, safe="")
                        encoded_title = urllib.parse.quote(title, safe="")
                        encoded_comment = urllib.parse.quote(caption, safe="")
                        driver.get(f"https://share.flipboard.com/bookmarklet/popout?v=2&title={encoded_title}&url={encoded_url}&comment={encoded_comment}")
                        time.sleep(4)

                    if handle_flip_popup(driver, target_mag, caption=caption):
                        mark_as_synced(art["_blog_id"], art["id"], art.get("tags", ""), tag_to_add=next_tag)
                        logging.info(f"  [OK] Successfully syndicated MeeeShop article: '{title}'")
                    else:
                        raise RuntimeError("Failed to complete flip inside popup modal.")

                except Exception as e:
                    logging.error(f"  FAILED to flip article '{title}': {e}")
                    debug_time = int(time.time())
                    try:
                        driver.save_screenshot(f"flipboard_error_{debug_time}.png")
                        with open(f"flipboard_error_{debug_time}.html", "w", encoding="utf-8") as f:
                            f.write(driver.page_source)
                    except Exception:
                        pass

                time.sleep(random.uniform(2.5, 4.5))

    finally:
        driver.quit()
        logging.info("Flipboard syndication workflow completed.")

# ── Main Entrypoint ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Automate flipping Shopify blogs to Flipboard.")
    ap.add_argument("--days", type=int, default=14, help="Sync articles published in the last X days.")
    ap.add_argument("--limit", type=int, default=5, help="Max MeeeShop articles to flip per run.")
    ap.add_argument("--dry-run", action="store_true", help="Print plan, do not flip.")
    ap.add_argument("--headed", action="store_true", help="Show browser window.")
    ap.add_argument("--no-reflip", dest="reflip", action="store_false", help="Disable curating trending fashion articles.")
    ap.add_argument("--reflip-limit", type=int, default=3, help="Max trending fashion articles to curate first.")
    ap.set_defaults(reflip=True)
    args = ap.parse_args()

    logging.info("="*70)
    logging.info(f"  MeeeShop Flipboard Syndication & Audience Growth")
    logging.info(f"  Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    logging.info("="*70)

    articles = fetch_articles(args.days, args.limit)

    is_fallback = False
    if not articles:
        logging.info("No new unsynced articles found. Falling back to older articles (30+ days old) for periodic re-flipping...")
        articles = fetch_old_articles(limit=2)
        is_fallback = True

    if not articles and not args.reflip:
        logging.info("No articles found and trending curation is disabled. Exiting.")
        sys.exit(0)

    reflip_limit = args.reflip_limit
    if args.reflip and reflip_limit >= 2:
        reflip_limit = random.randint(max(2, reflip_limit - 1), reflip_limit)

    if args.dry_run:
        logging.info("\n--- DRY RUN PREVIEW MODE ---")
        test_flipboard_login(headless=not args.headed)
        if args.reflip:
            logging.info(f"\n[Step 1 Preview]: Would curate {reflip_limit} trending women's fashion articles FIRST across magazines.")
        if articles:
            logging.info(f"\n[Step 2 Preview]: Would flip {len(articles)} MeeeShop articles LAST (so they sit at the TOP):")
            for art in articles:
                stage = art.get("_stagger_stage", 1)
                target_mag = art.get("_target_mag", FLIPBOARD_MAGAZINE)
                caption = art.get("_caption", "")
                logging.info(f"  - [Stage {stage}] '{html.unescape(art['title'])}' -> Mag: '{target_mag}'")
                logging.info(f"    URL: {art['_full_url']}")
                logging.info(f"    Caption: {caption}")
        logging.info("--- END DRY RUN ---\n")
    else:
        logging.info("\n--- LIVE SYNDICATION MODE ---")
        flip_articles(articles, headless=not args.headed, do_reflip=args.reflip, reflip_limit=reflip_limit)
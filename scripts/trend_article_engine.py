#!/usr/bin/env python3
"""
trend_article_engine.py — MeeeShop Trend-Driven Article Automation
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

WHAT IT DOES:
  1. DISCOVER  — Fetches all product categories & types from the Shopify store
  2. RESEARCH  — Searches Flipboard for trending articles (past 7 days) per category
                 using RSS feeds + public search API (no login required)
  3. LOG       — Writes a timestamped research log to logs/trend_research_YYYYMMDD.json
  4. GENERATE  — Mix-and-matches research data to produce ORIGINAL, editorial-quality
                 articles aligned to WhoWhatWear / Refinery29 standards
  5. PUBLISH   — Publishes to Shopify with correct blog, handle, SEO title, meta desc,
                 featured image collage, and 2026-trend tags

HANDLE ALIGNMENT:
  The article handle, title, and content are derived from the same research topic —
  so there is no mismatch between URL, headline, and body.

USAGE:
  python trend_article_engine.py                  # full run: research + generate + publish 1
  python trend_article_engine.py --count 3        # publish 3 articles
  python trend_article_engine.py --research-only  # only run step 1-3 (no publishing)
  python trend_article_engine.py --dry-run        # generate + log but do NOT publish
  python trend_article_engine.py --from-log       # skip research, use latest log
"""

import os, sys, re, time, json, random, argparse, hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote_plus, urljoin
from PIL import Image, ImageDraw, ImageFilter
from io import BytesIO
import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup

# ── Path setup ─────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT   = SCRIPT_DIR.parent
LOG_DIR     = REPO_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(REPO_ROOT))

import ai_client
from secrets_manager import inject_to_env, get_secret
inject_to_env()

# ── Shopify credentials ────────────────────────────────────────────────────────
SHOP    = get_secret("SHOPIFY_STORE")
TOKEN   = get_secret("SHOPIFY_ACCESS_TOKEN")
API_VER = "2024-10"
BASE    = f"https://{SHOP}/admin/api/{API_VER}"
HEADERS = {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}
STORE_URL = get_secret("STORE_BASE_URL") or f"https://{SHOP}"

if not TOKEN:
    sys.exit("ERROR: SHOPIFY_ACCESS_TOKEN not set.")

YEAR  = datetime.now().year
MONTH = datetime.now().strftime("%B %Y")
TODAY = datetime.now().strftime("%Y-%m-%d")

# ── Pen names ──────────────────────────────────────────────────────────────────
PEN_NAMES = [
    "Elena Vance, MeeeShop Lead Stylist",
    "Seraphina Croft, MeeeShop Fashion Editor",
    "Audrey Sterling, MeeeShop Style Director",
    "Maya Devereaux, MeeeShop Fashion Consultant",
    "Vivienne Vance, MeeeShop Senior Stylist",
    "Genevieve Thorne, MeeeShop Trend Forecaster",
]

# ── Flipboard topic map per product category ───────────────────────────────────
# Maps each product type keyword → Flipboard RSS/search topics to query
FLIPBOARD_TOPIC_MAP = {
    "jean":       ["jeans", "denim", "denim-fashion", "womens-jeans", "dark-wash-jeans"],
    "dress":      ["dresses", "summer-dress", "midi-dress", "womens-fashion", "dress-style"],
    "top":        ["womens-tops", "blouses", "fashion", "style", "summer-tops"],
    "blouse":     ["blouses", "womens-tops", "fashion", "office-style"],
    "skirt":      ["skirts", "midi-skirt", "mini-skirt", "womens-fashion"],
    "pant":       ["trousers", "womens-pants", "fashion", "wide-leg-pants"],
    "jacket":     ["jackets", "blazers", "outerwear", "womens-fashion", "layering"],
    "coat":       ["coats", "outerwear", "trench-coat", "womens-fashion"],
    "sweater":    ["sweaters", "knitwear", "cozy-fashion", "fall-fashion"],
    "cardigan":   ["cardigans", "layering", "cozy-fashion", "knitwear"],
    "swimwear":   ["swimwear", "bikini", "beach-fashion", "summer-style"],
    "activewear": ["activewear", "athleisure", "workout-style", "gym-fashion"],
    "accessory":  ["accessories", "fashion-accessories", "style", "womens-style"],
}

# ── Article angle templates tied to handle patterns ────────────────────────────
# Each angle produces a coherent handle + title + content topic
ARTICLE_ANGLES = [
    {
        "handle_prefix": "how-to-style",
        "title_template": "How to Style {keyword} in {year}: {n} Outfits That Work",
        "format": "outfit_formula",
        "content_focus": "outfit formulas and styling recipes using {keyword} as the base piece",
    },
    {
        "handle_prefix": "what-to-wear-with",
        "title_template": "What to Wear With {keyword}: The Complete Pairing Guide for {year}",
        "format": "buying_guide",
        "content_focus": "top + layer + accessory combinations that work with {keyword}",
    },
    {
        "handle_prefix": "best",
        "title_template": "The Best {keyword} for Women in {year}: Honest Picks from Our Editors",
        "format": "buying_guide",
        "content_focus": "what makes a great {keyword}, honest review and styling breakdown",
    },
    {
        "handle_prefix": "how-to-care-for",
        "title_template": "How to Care for {keyword}: The Washing and Storage Guide That Saves Your Clothes",
        "format": "care_guide",
        "content_focus": "step-by-step washing, drying, stain removal, and storage for {keyword}",
    },
    {
        "handle_prefix": "sizing-guide",
        "title_template": "{keyword} Sizing Guide for Women: Find Your Perfect Fit XS to 3X",
        "format": "sizing_guide",
        "content_focus": "how to measure yourself, size chart, body-shape fit breakdown for {keyword}",
    },
    {
        "handle_prefix": "trending",
        "title_template": "Trending {keyword} Styles in {year}: What's Actually Worth Buying",
        "format": "trend_report",
        "content_focus": "2026 trending {keyword} silhouettes, colours, and styling formulas",
    },
    {
        "handle_prefix": "how-to-look-taller-in",
        "title_template": "How to Look Taller in {keyword}: The Styling Tricks That Actually Work",
        "format": "problem_solver",
        "content_focus": "proportion tricks, rise selection, tuck-in formulas to add visual height with {keyword}",
    },
    {
        "handle_prefix": "outfit-ideas",
        "title_template": "{keyword} Outfit Ideas for Every Occasion in {year}",
        "format": "outfit_formula",
        "content_focus": "5 complete outfit formulas with {keyword} for work, weekend, evening, travel, brunch",
    },
    {
        "handle_prefix": "how-to-wash",
        "title_template": "How to Wash {keyword} Without Ruining Them: The Right Way",
        "format": "care_guide",
        "content_focus": "machine wash vs hand wash, temperature, detergent, drying, inside-out technique for {keyword}",
    },
    {
        "handle_prefix": "quiet-luxury",
        "title_template": "The Quiet Luxury {keyword} Look for {year}: How to Dress Expensive on Any Budget",
        "format": "trend_report",
        "content_focus": "quiet luxury styling with {keyword}: dark wash, no logos, clean lines, elevated basics",
    },
]

# ── EEAT + Editorial Rules ─────────────────────────────────────────────────────
EEAT_RULES = (
    "EDITORIAL VOICE & E-E-A-T (non-negotiable for Google Discover + organic traffic):\n\n"

    "VOICE: Write as a trusted stylist friend — warm, direct, specific. Second person ('your jeans', 'your wardrobe').\n"
    "MeeeShop sells CLOTHING ONLY — no shoes. All styling cues must use: tops, blazers, cardigans, jackets, belts, bags, earrings, scarves, hats.\n\n"

    "OPENING HOOK (required — this is your Google Discover click driver):\n"
    "✅ GOOD: 'The single-roll cuff is everywhere right now — here is exactly what actually works.'\n"
    "✅ GOOD: 'If your dark wash jeans still smell musty after washing, a second wash is rarely the answer.'\n"
    "❌ BAD: 'Jeans are a timeless wardrobe staple that women everywhere love.'\n"
    "❌ BAD: 'In today's fashion world, finding the perfect piece can be challenging.'\n\n"

    "SPECIFIC RECS (required — name categories with descriptors):\n"
    "✅ 'A relaxed linen button-down in ecru — untucked, one button open at the collar.'\n"
    "✅ 'Layer a cropped blazer in camel or ivory — it balances the proportions instantly.'\n"
    "✅ 'A structured mini tote in chocolate brown anchors the quiet luxury look.'\n"
    "❌ 'Accessorize to complete the outfit.' — TOO VAGUE\n\n"

    "2026 TREND CONTEXT (weave in 1-2 naturally):\n"
    "• Cigarette/stovepipe jeans replacing wide-leg as 2026 dominant denim silhouette\n"
    "• Quiet luxury: dark indigo, no logos, clean wash denim with tucked linen top\n"
    "• Linen top + dark wash jean = the heat-proof summer formula\n"
    "• All-black even in summer — trending on Flipboard #Style (8.4M followers)\n"
    "• Oversized blazer over a simple tank + straight-leg = office-to-evening 2026 formula\n\n"

    "BANNED PHRASES: elevate your look | effortlessly chic | perfect for any occasion | "
    "versatile wardrobe staple | timeless classic | fashion-forward | style game | "
    "take your look to the next level | complete your outfit | fashion journey\n\n"

    "TRUST SIGNAL (include once, in CTA or intro): "
    "Free US shipping on orders $50+. Easy 7-day returns. Sizes XS–3X.\n\n"
)


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 1 — SHOPIFY: GET PRODUCT TYPES & CATEGORIES
# ══════════════════════════════════════════════════════════════════════════════

def _req(method: str, url: str, **kw):
    """Shopify API request with rate-limit retry."""
    for attempt in range(5):
        try:
            r = getattr(requests, method)(url, headers=HEADERS, timeout=30, **kw)
            if r.status_code == 429:
                wait = int(float(r.headers.get("Retry-After", 4)))
                print(f"  [Shopify] Rate limited — waiting {wait}s…")
                time.sleep(wait)
                continue
            return r
        except requests.exceptions.ConnectionError:
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"{method.upper()} {url} failed after 5 attempts")


def fetch_store_product_types() -> dict:
    """
    Fetch all products from Shopify and extract:
    - All unique product_type values
    - Sample products per type (for collage generation later)
    - Tag cloud from all products (for keyword expansion)

    Returns a dict keyed by product_type with sample products list.
    """
    print("\n━━ PHASE 1: Fetching Shopify product catalogue ━━")
    all_products = []
    page_info = None
    fields = "id,title,handle,product_type,vendor,tags,variants,images"

    while True:
        params = {"limit": 250, "fields": fields}
        if page_info:
            params["page_info"] = page_info

        r = _req("get", f"{BASE}/products.json", params=params)
        r.raise_for_status()
        batch = r.json().get("products", [])
        all_products.extend(batch)

        # Pagination via Link header
        link_hdr = r.headers.get("Link", "")
        next_match = re.search(r'<([^>]+)>;\s*rel="next"', link_hdr)
        if next_match and len(batch) == 250:
            next_url = next_match.group(1)
            pi_match = re.search(r"page_info=([^&]+)", next_url)
            page_info = pi_match.group(1) if pi_match else None
            if not page_info:
                break
        else:
            break

    # Group by product_type
    type_map: dict[str, list] = {}
    tag_cloud: list[str] = []

    for p in all_products:
        ptype = (p.get("product_type") or "Uncategorized").strip()
        if ptype not in type_map:
            type_map[ptype] = []
        if len(type_map[ptype]) < 5:   # keep max 5 sample products per type
            type_map[ptype].append(p)
        # Collect tags
        raw_tags = p.get("tags", "")
        if raw_tags:
            tag_cloud.extend([t.strip().lower() for t in raw_tags.split(",")])

    tag_freq = {}
    for t in tag_cloud:
        tag_freq[t] = tag_freq.get(t, 0) + 1
    top_tags = [t for t, _ in sorted(tag_freq.items(), key=lambda x: -x[1])[:50]]

    print(f"  Found {len(all_products)} products across {len(type_map)} product types")
    for ptype, prods in sorted(type_map.items()):
        print(f"    • {ptype}: {len(prods)} samples")

    return {"types": type_map, "top_tags": top_tags, "total": len(all_products)}


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 2 — FLIPBOARD: RESEARCH TRENDING TOPICS (past 7 days)
# ══════════════════════════════════════════════════════════════════════════════

FLIPBOARD_RSS_BASE = "https://flipboard.com/topic/{topic}/feed.rss"
FLIPBOARD_SEARCH   = "https://flipboard.com/search.json"
CUTOFF_DAYS        = 7       # only articles from past 7 days
MAX_ARTICLES_PER_TOPIC = 12  # max articles to keep per Flipboard topic

def _parse_rss_date(date_str: str) -> datetime | None:
    """Parse RSS pubDate into a timezone-aware datetime."""
    if not date_str:
        return None
    formats = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S GMT",
        "%a, %d %b %Y %H:%M:%S +0000",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def _fetch_flipboard_rss(topic: str) -> list[dict]:
    """Fetch and parse a Flipboard RSS topic feed, returning articles from past 7 days."""
    url = FLIPBOARD_RSS_BASE.format(topic=topic.lower().replace(" ", "-"))
    cutoff = datetime.now(timezone.utc) - timedelta(days=CUTOFF_DAYS)

    try:
        r = requests.get(url, timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (compatible; MeeeShop SEO bot/1.0)"
        })
        if r.status_code != 200:
            return []

        root = ET.fromstring(r.content)
        ns = {"media": "http://search.yahoo.com/mrss/",
              "content": "http://purl.org/rss/1.0/modules/content/"}
        articles = []

        for item in root.iter("item"):
            title_el  = item.find("title")
            link_el   = item.find("link")
            desc_el   = item.find("description")
            pub_el    = item.find("pubDate")
            author_el = item.find("author")

            title = title_el.text.strip() if title_el is not None and title_el.text else ""
            link  = link_el.text.strip()  if link_el  is not None and link_el.text  else ""
            desc  = desc_el.text.strip()  if desc_el  is not None and desc_el.text  else ""
            pub_raw = pub_el.text if pub_el is not None else ""

            # Strip HTML from desc
            desc = re.sub(r"<[^>]+>", "", desc).strip()

            pub_dt = _parse_rss_date(pub_raw)
            if pub_dt and pub_dt < cutoff:
                continue   # too old

            if not title or len(title) < 10:
                continue

            articles.append({
                "title":     title,
                "link":      link,
                "summary":   desc[:400] if desc else "",
                "published": pub_raw,
                "topic":     topic,
                "source":    "flipboard-rss",
            })

            if len(articles) >= MAX_ARTICLES_PER_TOPIC:
                break

        return articles

    except Exception as e:
        print(f"    [Flipboard RSS] {topic}: {e}")
        return []


def _fetch_flipboard_search(keyword: str) -> list[dict]:
    """
    Use Flipboard's public search JSON endpoint (no auth needed).
    Falls back gracefully if unavailable.
    """
    try:
        r = requests.get(
            FLIPBOARD_SEARCH,
            params={"q": keyword, "locale": "en_US"},
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0 (compatible; MeeeShop SEO bot/1.0)"}
        )
        if r.status_code != 200:
            return []

        data = r.json()
        items = []

        # Extract sections → items
        for section in data.get("sections", []):
            for item in section.get("items", []):
                if item.get("type") != "article":
                    continue
                title   = item.get("title", "").strip()
                excerpt = item.get("excerpt", "").strip()
                source  = item.get("source_domain", "")
                url     = item.get("canonical_url", "")

                if not title or len(title) < 10:
                    continue

                items.append({
                    "title":     title,
                    "link":      url,
                    "summary":   excerpt[:400],
                    "published": "",
                    "topic":     keyword,
                    "source":    f"flipboard-search:{source}",
                })

                if len(items) >= MAX_ARTICLES_PER_TOPIC:
                    break
            if len(items) >= MAX_ARTICLES_PER_TOPIC:
                break

        return items

    except Exception as e:
        print(f"    [Flipboard Search] {keyword}: {e}")
        return []


def research_flipboard_per_category(type_map: dict) -> dict:
    """
    For each product type in the store, query relevant Flipboard topics.
    Returns a research dict keyed by product_type.
    """
    print("\n━━ PHASE 2: Researching Flipboard trending topics ━━")
    research: dict[str, dict] = {}

    for ptype, sample_products in type_map.items():
        ptype_lower = ptype.lower()

        # Identify which Flipboard topics to query
        topics_to_query: list[str] = []
        for key, topics in FLIPBOARD_TOPIC_MAP.items():
            if key in ptype_lower:
                topics_to_query = topics
                break

        if not topics_to_query:
            # Generic fallback
            topics_to_query = ["womens-fashion", "style", "fashion"]

        print(f"\n  [{ptype}] Querying {len(topics_to_query)} Flipboard topics…")
        all_articles: list[dict] = []

        for topic in topics_to_query:
            print(f"    → {topic}", end=" ", flush=True)
            rss_articles = _fetch_flipboard_rss(topic)
            print(f"({len(rss_articles)} RSS articles)", flush=True)
            # Download full article content for each RSS article
            for art in rss_articles:
                if "link" in art and art["link"]:
                    art["full_content"] = download_article_content(art["link"])
            all_articles.extend(rss_articles)
            time.sleep(0.5)   # polite crawl delay

        # Also try a direct search for the ptype
        search_kw = f"women {ptype_lower} style 2026"
        search_articles = _fetch_flipboard_search(search_kw)
        for art in search_articles:
            if "link" in art and art["link"]:
                art["full_content"] = download_article_content(art["link"])
        all_articles.extend(search_articles)

        # Deduplicate by title similarity
        seen_titles: set[str] = set()
        unique: list[dict] = []
        for art in all_articles:
            key = re.sub(r"\W+", "", art["title"].lower())[:40]
            if key not in seen_titles:
                seen_titles.add(key)
                unique.append(art)

        # Extract trending keywords/angles from titles and full content
        all_titles = [a["title"] for a in unique]
        trending_angles = _extract_trending_angles(all_titles, ptype_lower)
        # Keyword extraction from full content
        keyword_data = {"long_tail": [], "zero_search": []}
        for art in unique:
            if art.get("full_content"):
                kw = extract_keywords(art["full_content"])
                keyword_data["long_tail"].extend(kw.get("long_tail", []))
                keyword_data["zero_search"].extend(kw.get("zero_search", []))

        research[ptype] = {
            "product_type":      ptype,
            "sample_products":   [{"id": p["id"], "title": p["title"], "handle": p["handle"]}
                                   for p in sample_products],
            "articles_found":    len(unique),
            "flipboard_articles": unique[:30],   # store max 30 per type
            "trending_angles":   trending_angles,
            "topics_queried":    topics_to_query,
            "keywords":          keyword_data,
        }
        print(f"    Total unique articles: {len(unique)} | Trending angles: {trending_angles[:3]}")

    return research


def _extract_trending_angles(titles: list[str], ptype: str) -> list[str]:
    """
    Extract actionable content angles from a list of article titles.
    Returns a deduplicated list of short angle descriptions.
    """
    angles: list[str] = []
    keyword_patterns = [
        (r"how to (style|wear|pair|cuff|wash|care|clean|remove|look)", "how-to"),
        (r"(best|top) .{3,30} (jeans|dress|top|skirt|pant|jacket|coat)", "best-of"),
        (r"outfit (ideas|formula|inspiration)", "outfit-ideas"),
        (r"(trend|trending|2026)", "trend-report"),
        (r"(sizing|size guide|fit guide)", "sizing-guide"),
        (r"(care|washing|cleaning|stain|smell|pilling)", "care-guide"),
        (r"(quiet luxury|minimalist|clean aesthetic)", "quiet-luxury"),
        (r"(petite|plus size|curvy|tall)", "body-positive"),
    ]

    for title in titles:
        title_lower = title.lower()
        for pattern, angle_type in keyword_patterns:
            if re.search(pattern, title_lower):
                # Build a clean angle from the title
                clean = title.strip()
                clean = re.sub(r"\s*[\|\-—:]\s*.+$", "", clean)  # remove source suffix
                clean = clean[:80]
                if clean and clean not in angles:
                    angles.append(clean)
                break

    # Always ensure we have at least 3 generic angles for the ptype
    generic = [
        f"How to style {ptype} for every occasion in {YEAR}",
        f"The best {ptype} for women in {YEAR}: editor's picks",
        f"Trending {ptype} styles in {YEAR}: what's worth buying",
    ]
    for g in generic:
        if g not in angles:
            angles.append(g)

    return angles[:10]


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 3 — LOG: Write research to timestamped JSON log
# ══════════════════════════════════════════════════════════════════════════════

def save_research_log(research: dict, store_info: dict) -> Path:
    """Save research to a timestamped JSON log file."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOG_DIR / f"trend_research_{ts}.json"

    log_data = {
        "generated_at":  datetime.now().isoformat(),
        "date":          TODAY,
        "store":         SHOP,
        "total_products": store_info.get("total", 0),
        "product_types_found": list(research.keys()),
        "research":      research,
    }

    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(log_data, f, indent=2, ensure_ascii=False)

    print(f"\n  [LOG] Research saved → {log_path}")
    return log_path


def load_latest_log() -> dict | None:
    """Load the most recent trend research log."""
    logs = sorted(LOG_DIR.glob("trend_research_*.json"), reverse=True)
    if not logs:
        print("  [LOG] No existing research logs found.")
        return None
    print(f"  [LOG] Loading latest log: {logs[0].name}")
    with open(logs[0], encoding="utf-8") as f:
        return json.load(f)


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 4 — GENERATE: Mix-and-match research into original articles
# ══════════════════════════════════════════════════════════════════════════════

def _slugify(text: str) -> str:
    """Convert a title/phrase to a URL-safe handle slug."""
    text = text.lower()
    text = re.sub(r"[''\"'']", "", text)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")[:80]


def _pick_article_angle(ptype: str, research_data: dict, used_angles: set, all_products_pool: list) -> dict | None:
    """
    Pick a fresh article angle for a given product type.
    Mixes the trending angles from Flipboard with our ARTICLE_ANGLES templates.
    Incorporates extracted keywords and avoids repeating angles already used in this run.
    """
    trending_angles = research_data.get("trending_angles", [])
    flipboard_articles = research_data.get("flipboard_articles", [])
    keyword_data = research_data.get("keywords", {"long_tail": [], "zero_search": []})

    # Build candidate angles from ARTICLE_ANGLES templates
    ptype_clean = ptype.lower().strip()
    singular = ptype_clean.rstrip("s") if ptype_clean.endswith("s") else ptype_clean

    candidates = []
    for angle in ARTICLE_ANGLES:
        # Base keyword is the product type singular
        keyword_raw = singular
        # Enrich with a trending angle if available
        if trending_angles:
            trend_hint = random.choice(trending_angles)
            words = trend_hint.split()[:4]
            enriched = " ".join(words).strip(".,!?:")
            if len(enriched) > 5:
                keyword_raw = enriched.lower()
        # Further enrich with a long‑tail keyword if we have any
        if keyword_data["long_tail"]:
            lt_kw = random.choice(keyword_data["long_tail"]).lower()
            keyword_raw = lt_kw

        handle_slug = f"{angle['handle_prefix']}-{_slugify(keyword_raw)}"
        angle_key = f"{ptype}:{angle['handle_prefix']}"
        if angle_key in used_angles:
            continue

        title = angle["title_template"].format(
            keyword=keyword_raw.title(),
            year=YEAR,
            n=random.choice([3, 5, 7]),
        )

        candidates.append({
            "handle_slug":    handle_slug,
            "title":          title,
            "format":         angle["format"],
            "content_focus":  angle["content_focus"].format(keyword=keyword_raw),
            "angle_key":      angle_key,
            "ptype":          ptype,
            "ptype_clean":    ptype_clean,
            "singular":       singular,
        })

    if not candidates:
        return None

    # Relevance scoring using Flipboard titles and keyword overlap
    flip_titles_lower = [a["title"].lower() for a in flipboard_articles]
    def relevance_score(c: dict) -> int:
        score = 0
        for ft in flip_titles_lower:
            if c["format"] in ft or c["handle_slug"].split("-")[0] in ft:
                score += 1
            if any(kw.lower() in ft for kw in keyword_data["long_tail"]):
                score += 1
        return score

    candidates.sort(key=relevance_score, reverse=True)
    return candidates[0]


def _build_article_prompt(angle: dict, product: dict, research_data: dict, matching_products: list) -> str:
    """
    Build a comprehensive AI prompt from the research data + angle + product.
    The prompt guarantees handle/title/content alignment.
    """
    ptype_clean = angle["ptype_clean"]
    title       = angle["title"]
    fmt         = angle["format"]
    focus       = angle["content_focus"]

    display_name = (product.get("title") or ptype_clean).strip()
    price        = (product.get("variants") or [{}])[0].get("price", "49")
    
    # Build styling instructions for the collage items to tie image & text together
    match_instr = ""
    if matching_products:
        clean_matches = [get_product_display_name(m) for m in matching_products]
        matches_str = " and ".join([f"'{m_title}' (${m['variants'][0]['price'] if m.get('variants') else '49'})" for m_title, m in zip(clean_matches, matching_products)])
        match_instr = (
            f"- We are featuring a styling lookbook collage showing this product paired with: {matches_str}.\n"
            f"- In the styling or outfit sections of your article, you MUST explicitly mention these matching pieces by name, explaining how to style them together with the main featured product to create a complete, cohesive outfit (e.g., 'pair it with the {clean_matches[0]}' or 'complete this look using the {clean_matches[1]}').\n"
        )

    # Distil 3-5 key insights from Flipboard research
    flip_articles = research_data.get("flipboard_articles", [])[:5]
    research_context = ""
    if flip_articles:
        snippets = []
        for art in flip_articles:
            if art.get("title") or art.get("summary"):
                snippets.append(f'  • "{art["title"]}" — {art["summary"][:100]}')
        if snippets:
            research_context = (
                f"FLIPBOARD RESEARCH CONTEXT (past 7 days — use to make article feel current):\n"
                + "\n".join(snippets[:5]) + "\n\n"
            )

    trending_angles = research_data.get("trending_angles", [])
    angles_str = "\n".join(f"  • {a}" for a in trending_angles[:4])
    trend_context = (
        f"TRENDING ANGLES THIS WEEK (from Flipboard — weave 1-2 in naturally):\n{angles_str}\n\n"
        if trending_angles else ""
    )

    # Format-specific structure
    fmt_instructions = {
        "outfit_formula": (
            f"FORMAT: 5-Look Outfit Formula (WhoWhatWear editorial style)\n"
            f"Structure:\n"
            f"1. <h1> {title}\n"
            f"2. <p> Hook — open with a SPECIFIC styling insight about {ptype_clean} that surprises the reader. "
            f"NOT 'This piece is so versatile!' — instead reveal something unexpected. (70 words)\n"
            f"3. Five looks as <h2> — EACH must have an evocative creative occasion name:\n"
            f"   e.g. 'Look 1: The Power Lunch', 'Look 2: Sunday Farmers Market', "
            f"'Look 3: Date Night That Doesn't Look Like You Tried Too Hard'\n"
            f"   Each look (80-90 words) MUST include:\n"
            f"   • Specific top or layer: silhouette + fabric + color\n"
            f"   • Layering piece (blazer/cardigan/jacket) with color and weight where relevant\n"
            f"   • Bag: style + color\n"
            f"   • One accessory (belt, earrings, scarf) with the reason it works\n"
            f"   • No shoes — MeeeShop sells clothing only\n"
            f"   • WHERE to wear this and WHY it works for that context\n"
            f"4. <h2> Honest Fit Notes (50 words — petite, curvy, tall specific advice)\n"
            f"5. <p> CTA: price of {display_name}, free US shipping on $50+, 7-day returns. No HTML links.\n"
            f"Target: 800-950 words."
        ),
        "buying_guide": (
            f"FORMAT: Honest Buying Guide (Refinery29 depth)\n"
            f"Structure:\n"
            f"1. <h1> {title}\n"
            f"2. <p> Hook — open with a specific question customers ask every week about {ptype_clean}. (80 words)\n"
            f"3. <h2> What Actually Makes a Good {ptype_clean.title()}? "
            f"(4 real criteria as <ul><li> — fabric, construction, fit consistency, washing durability)\n"
            f"4. <h2> Why {display_name} Made Our Edit: Honest Breakdown "
            f"(120 words — fabric drape, cut reality for different body shapes, price-to-quality. No HTML links.)\n"
            f"5. <h2> 3 Real-Life Outfit Recipes (H3 each with creative occasion name. "
            f"Specify top+fabric+color, blazer/cardigan, bag, accessory. No shoes. 70 words each.)\n"
            f"6. <h2> Who This Works For (and Who Should Skip It) (60 words — honest trade-offs)\n"
            f"7. <h2> Sizing: Buy Your Size or Size Up? (40 words — specific verdict)\n"
            f"8. <p> CTA: price, free US shipping on $50+, 7-day returns. No HTML links.\n"
            f"Target: 800-950 words."
        ),
        "trend_report": (
            f"FORMAT: {MONTH} Trend Report (grounded in real 2026 data)\n"
            f"Structure:\n"
            f"1. <h1> {title}\n"
            f"2. <p> Intro — what is actually happening in {ptype_clean} fashion RIGHT NOW. "
            f"Be specific about what changed vs last year. (70 words, confident stylist voice)\n"
            f"3. Five trends as <h2> with opinionated trend names + 90-word descriptions:\n"
            f"   - Trend 1: feature {display_name} — explain why it fits 2026\n"
            f"   - Trend 2: Cigarette/stovepipe silhouette — why it's replacing wide-leg\n"
            f"   - Trend 3: Quiet Luxury — dark indigo, no logos, clean lines\n"
            f"   - Trend 4: Linen + {ptype_clean} formula — heat-proof summer styling\n"
            f"   - Trend 5: one more real {MONTH} micro-trend for US women shoppers\n"
            f"   Each: what it is, why it's trending NOW, specific styling formula, who it suits\n"
            f"4. <h2> How to Mix Two Trends Without Looking Overdone (60 words — one focal piece rule)\n"
            f"5. <p> CTA: shop {display_name}, price, free US shipping on $50+. No HTML links.\n"
            f"Target: 800-950 words."
        ),
        "care_guide": (
            f"FORMAT: Practical Care & Washing Guide (problem-first, actionable)\n"
            f"Structure:\n"
            f"1. <h1> {title}\n"
            f"2. <p> Hook — open with the #1 care mistake women make that ruins {ptype_clean}. "
            f"Problem-first, direct. (70 words)\n"
            f"3. <h2> Reading Your Care Label: What Those Symbols Actually Mean\n"
            f"4. <h2> The Right Way to Wash {display_name}\n"
            f"   <h3> Machine Washing (exact: temperature, cycle, detergent, inside-out?)\n"
            f"   <h3> Hand Washing (when + how — water temp, no wringing)\n"
            f"   DENIM SPECIFICS (if applicable): wash inside out, cold only, no fabric softener, "
            f"skip dryer, freezer odor hack\n"
            f"5. <h2> Drying Without Damage (WHY heat damages fabric, specific hang-dry steps)\n"
            f"6. <h2> Storage Tips That Preserve the Fit (fold vs hang — specific to this garment type)\n"
            f"7. <blockquote> A Stylist Tip with one specific care hack most people don't know\n"
            f"8. <p> CTA: shop {display_name}, free US shipping on $50+, 7-day returns. No HTML links.\n"
            f"Target: 750-900 words."
        ),
        "sizing_guide": (
            f"FORMAT: Inclusive Sizing & Fit Guide\n"
            f"Structure:\n"
            f"1. <h1> {title}\n"
            f"2. <p> Hook — 'Ordering {ptype_clean} online is a gamble until you know the three measurements that matter most.' (70 words)\n"
            f"3. <h2> How to Measure Yourself in 3 Steps (waist, hips, inseam/length — specific instructions)\n"
            f"4. <h2> MeeeShop Size Chart: XS to 3X Decoded "
            f"(<table> with size/waist/hip/inseam in inches — realistic US measurements)\n"
            f"5. <h2> Fit by Body Shape:\n"
            f"   <h3> Petite (under 5'4\"): what works, length/rise advice\n"
            f"   <h3> Hourglass: how this cut balances hip-to-waist ratio\n"
            f"   <h3> Straight/Athletic: how to create curves with {ptype_clean}\n"
            f"   <h3> Curvy/Full-Figured (1X-3X): hip room, waistband gap, stretch factor\n"
            f"6. <h2> High Rise vs Mid Rise vs Low Rise — Which Fits Your Body Best? "
            f"(40 words per rise)\n"
            f"7. <h2> Final Verdict: Buy Your Size or Size Up? (honest recommendation for {display_name})\n"
            f"8. <p> CTA: free US shipping on $50+, 7-day returns, sizes XS-3X. No HTML links.\n"
            f"Target: 800-950 words."
        ),
        "problem_solver": (
            f"FORMAT: Problem-Solver Article (reader-first empathy)\n"
            f"Structure:\n"
            f"1. <h1> {title}\n"
            f"2. <p> Opening — validate the reader's exact frustration. Start with their problem, "
            f"not a generic intro. (80 words, second-person, warm and direct)\n"
            f"3. <h2> Why It Keeps Happening (and It's Not Your Fault) "
            f"(60 words — the real structural/industry reason behind {focus})\n"
            f"4. <h2> The Fix: Why {display_name} Solves This "
            f"(120 words — specific cut, fabric, construction details that solve the problem. No HTML links.)\n"
            f"5. <h2> 3 Outfit Recipes That Prove It "
            f"(H3 each with creative occasion name. Specify top+fabric, blazer/cardigan, bag, accessory. No shoes. 70 words each.)\n"
            f"6. <h2> 4 Styling Rules That Actually Change Things "
            f"(specific bullet tips — not generic. E.g., 'Always half-tuck rather than full-tuck when unsure about proportions')\n"
            f"7. <p> CTA: price, free US shipping on $50+, 7-day returns, sizes XS-3X. No HTML links.\n"
            f"Target: 750-900 words."
        ),
    }

    fmt_instr = fmt_instructions.get(fmt, fmt_instructions["buying_guide"])

    prompt = (
        f"You are a fashion editor at MeeeShop, a USA women's clothing boutique.\n"
        f"Write a {MONTH} blog article. Topic: '{title}'\n"
        f"Primary focus: {ptype_clean} (featured product: {display_name} — ${price})\n\n"
        f"{EEAT_RULES}"
        f"{research_context}"
        f"{trend_context}"
        f"CRITICAL RULE: This article's URL handle will be '{angle['handle_slug']}'. "
        f"The title, H1, H2 sections, and body MUST all be about '{focus}'. "
        f"There must be ZERO mismatch between handle, title, and content.\n\n"
        f"SEO RULES:\n"
        f"- Include primary keyword '{ptype_clean}' 3-4 times naturally\n"
        f"{match_instr}"
        f"- H1 must include year {YEAR} or 'for Women'\n"
        f"- At least 2 H2s must contain LSI keywords related to {ptype_clean} styling\n"
        f"- Do NOT write any HTML <a> links in the body\n"
        f"- Max 2 uses of the full product name '{display_name}' — use pronouns after that\n"
        f"- Include a Shoppers' Q&A section before the CTA:\n"
        f"  <h2>Shoppers' Q&A</h2>\n"
        f"  <h3>Is {display_name} worth the price?</h3><p>[40-50 word stylist answer]</p>\n"
        f"  <h3>How do I wash this {ptype_clean}?</h3><p>[40-50 word care answer]</p>\n"
        f"  <h3>How do I choose my size?</h3><p>[40-50 word sizing answer]</p>\n\n"
        f"Store info: Free US shipping on orders $50+. Easy 7-day returns. Sizes XS-3X.\n\n"
        f"{fmt_instr}\n\n"
        f"ORIGINALITY: This article must be 100% original — inspired by but NOT copied from Flipboard. "
        f"All outfit recipes, styling formulas, care steps, and trend observations must be your own editorial voice.\n\n"
        f"At the END of your response append a <seometa> block:\n"
        f"<seometa>\n"
        f"SEO_TITLE: [50-60 chars, keyword near start, year or 'for Women']\n"
        f"META_DESC: [140-155 chars, action-oriented, includes keyword, ends with CTA]\n"
        f"IMG_ALT: [10-15 words, describes styling scene, includes keyword + 'women', no quotes]\n"
        f"SUGGESTED_HANDLE: [{angle['handle_slug']}]\n"
        f"SUGGESTED_TAGS: [comma-separated: 5-8 relevant tags including year]\n"
        f"</seometa>\n"
        f"Output ONLY clean HTML + the <seometa> block. No markdown code fences."
    )
    return prompt


def _parse_seometa(raw: str) -> dict:
    """Extract SEO metadata from <seometa>...</seometa> block."""
    meta = {"seo_title": "", "meta_desc": "", "img_alt": "",
            "suggested_handle": "", "suggested_tags": []}

    m = re.search(r"<seometa>(.*?)</seometa>", raw, re.DOTALL | re.IGNORECASE)
    if not m:
        return meta

    block = m.group(1)
    for line in block.splitlines():
        line = line.strip()
        if line.upper().startswith("SEO_TITLE:"):
            meta["seo_title"] = line.split(":", 1)[1].strip().strip('"')
        elif line.upper().startswith("META_DESC:"):
            meta["meta_desc"] = line.split(":", 1)[1].strip().strip('"')
        elif line.upper().startswith("IMG_ALT:"):
            meta["img_alt"] = line.split(":", 1)[1].strip().strip('"')
        elif line.upper().startswith("SUGGESTED_HANDLE:"):
            meta["suggested_handle"] = line.split(":", 1)[1].strip().strip('"[]')
        elif line.upper().startswith("SUGGESTED_TAGS:"):
            raw_tags = line.split(":", 1)[1].strip().strip('"[]')
            meta["suggested_tags"] = [t.strip() for t in raw_tags.split(",") if t.strip()]

    return meta


def _clean_html(raw: str) -> str:
    """Strip AI wrapper markers and seometa block from content."""
    raw = raw.strip()
    raw = re.sub(r"^```html?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw)
    raw = re.sub(r"<seometa>.*?</seometa>", "", raw, flags=re.DOTALL | re.IGNORECASE)
    return raw.strip()


def clean_product_title(title: str) -> str:
    """Removes formatting chars like *, quotes, and trailing details."""
    t = re.sub(r'[*"\']', '', title)
    t = re.sub(r'\s*\([^)]+\)\s*$', '', t)
    t = re.sub(r'\s*-\s*[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s*$', '', t)
    return t.strip()


def get_product_display_name(product: dict) -> str:
    """Returns a clean display name with vendor (if not already in title)."""
    vendor = (product.get("vendor") or "").strip()
    title = product.get("title", "").strip()
    clean_title = clean_product_title(title)
    if vendor and vendor.lower() not in clean_title.lower():
        return f"{vendor} {clean_title}"
    return clean_title


def get_clean_product_type(product: dict) -> str:
    """Infers a clean singular product type name from title or type."""
    title = product.get("title", "").lower()
    ptype = (product.get("product_type") or "").lower()
    
    # Specific overrides
    if "skort" in title:
        return "skort"
    if "jort" in title:
        return "jort"
    if "short" in title:
        return "shorts"
    if "jean" in title:
        return "jeans"
    if "denim" in title:
        return "denim"
    if "jacket" in title:
        return "jacket"
    if "coat" in title:
        return "coat"
    if "cardigan" in title:
        return "cardigan"
    if "sweater" in title:
        return "sweater"
    if "dress" in title:
        return "dress"
    if "blouse" in title:
        return "blouse"
    if "shirt" in title:
        return "shirt"
    if "tee" in title or "t-shirt" in title:
        return "t-shirt"
    if "top" in title:
        return "top"
    if "pant" in title:
        return "pants"
    if "skirt" in title:
        return "skirt"
    if "bag" in title or "handbag" in title:
        return "handbag"
        
    # Standardizations
    if "jean" in ptype or "denim" in ptype:
        return "jeans"
    if "dress" in ptype:
        return "dress"
    if "top" in ptype or "blouse" in ptype or "shirt" in ptype:
        return "top"
    if "sweater" in ptype or "cardigan" in ptype or "knit" in ptype:
        return "knitwear"
    if "skirt" in ptype:
        return "skirt"
    if "pant" in ptype:
        return "pants"
    if "bag" in ptype or "handbag" in ptype:
        return "handbag"
        
    return ptype if ptype else "apparel"


def product_img_url(product: dict) -> str | None:
    images = product.get("images", [])
    return images[0]["src"] if images else None


def make_product_card(product: dict, keyword: str = "",
                      label: str = "FEATURED PICK — IN STOCK NOW") -> str:
    import html
    raw_title = product["title"]
    escaped_title = html.escape(raw_title)
    price  = product["variants"][0]["price"] if product.get("variants") else "0"
    handle = product.get("handle", "")
    ptype  = (product.get("product_type") or "women's fashion").lower()
    url    = f"{STORE_URL}/products/{handle}?utm_source=blog&utm_medium=featured_card&utm_campaign=meeeshop" if handle else STORE_URL
    img    = product_img_url(product)

    # Keyword-rich ALT text for inline product image
    alt = f"{raw_title} — {ptype} for women at MeeeShop"
    if keyword:
        alt = f"{raw_title} — {keyword}, {ptype} at MeeeShop"

    alt_clean = alt.replace('"', "'")

    img_html = (
        f'<a href="{url}"><img src="{img}" alt="{alt_clean}" '
        f'style="width:220px;height:220px;object-fit:cover;border-radius:10px;flex-shrink:0;" loading="lazy" /></a>'
        if img else ""
    )

    return f"""
<div style="background:#f8f6f3;border-radius:14px;padding:24px 28px;margin:32px 0;
            display:flex;flex-wrap:wrap;gap:24px;align-items:center;
            border:1px solid #eee;font-family:sans-serif;">
  {img_html}
  <div style="flex:1;min-width:200px;">
    <p style="font-size:11px;color:#999;margin:0 0 6px;text-transform:uppercase;letter-spacing:1.5px;font-weight:600;">{label}</p>
    <h3 style="font-size:18px;font-weight:700;margin:0 0 8px;color:#1a1a1a;line-height:1.3;">{escaped_title}</h3>
    <p style="font-size:26px;font-weight:800;color:#1a1a1a;margin:0 0 6px;">${price}</p>
    <p style="font-size:12px;color:#777;margin:0 0 18px;">
      Free US shipping on orders $50+ &nbsp;&bull;&nbsp; 7-day easy returns &nbsp;&bull;&nbsp; Sizes XS–3X
    </p>
    <a href="{url}"
       style="background:#1a1a1a;color:#ffffff;padding:13px 30px;text-decoration:none;
              border-radius:8px;font-size:14px;font-weight:700;letter-spacing:0.5px;
              display:inline-block;">
      Shop Now &rarr;
    </a>
  </div>
</div>
"""


def inject_product_card(html_body: str, product: dict, keyword: str = "") -> str:
    card = make_product_card(product, keyword)
    insert_after = re.search(r"</h1>\s*(<p>.*?</p>)", html_body, re.DOTALL | re.IGNORECASE)
    if insert_after:
        pos = insert_after.end()
        return html_body[:pos] + "\n" + card + html_body[pos:]
    pos = html_body.find("</p>")
    if pos != -1:
        return html_body[:pos+4] + "\n" + card + html_body[pos+4:]
    return card + html_body


def make_related_products_section(products: list, exclude_handle: str, keyword: str = "", matching_products: list = None) -> str:
    import html
    
    if matching_products:
        picks = matching_products
        section_title = "Shop Styled Pairings from This Article"
        cta_text = "Shop the Look"
    else:
        related = [p for p in products if p.get("handle") != exclude_handle and p.get("images")]
        if not related:
            related = [p for p in products if p.get("handle") != exclude_handle]
        picks = random.sample(related, min(3, len(related)))
        section_title = "You Might Also Love"
        cta_text = "Shop Similar"

    cards_html = ""
    for p in picks:
        raw_title  = p["title"]
        clean_title = clean_product_title(raw_title)
        escaped_title = html.escape(clean_title)
        price  = p["variants"][0]["price"] if p.get("variants") else "0"
        handle = p.get("handle", "")
        ptype  = (p.get("product_type") or "women's fashion").lower()
        url    = f"https://{SHOP}/products/{handle}?utm_source=blog&utm_medium=related_card&utm_campaign=meeeshop"
        img    = product_img_url(p)
        alt    = f"{clean_title} — {ptype} for women at MeeeShop"
        if keyword:
            alt = f"{clean_title} — shop {keyword} at MeeeShop"
        
        alt_clean = alt.replace('"', "'")

        img_tag = (
            f'<a href="{url}"><img src="{img}" alt="{alt_clean}" '
            f'style="width:100%;height:200px;object-fit:cover;border-radius:10px;margin-bottom:12px;" loading="lazy" /></a>'
            if img else ""
        )
        cards_html += f"""
  <div style="flex:1;min-width:200px;max-width:260px;font-family:sans-serif;text-align:center;">
    {img_tag}
    <p style="font-size:14px;font-weight:700;color:#1a1a1a;margin:0 0 4px;line-height:1.3;">{escaped_title}</p>
    <p style="font-size:16px;font-weight:800;color:#1a1a1a;margin:0 0 12px;">${price}</p>
    <a href="{url}"
       style="background:#f0ede8;color:#1a1a1a;padding:9px 20px;text-decoration:none;
              border-radius:6px;font-size:13px;font-weight:600;display:inline-block;">
      {cta_text}
    </a>
  </div>"""

    if not cards_html:
        return ""

    return f"""
<div style="margin:48px 0;padding:32px;background:#fafafa;border-radius:14px;border:1px solid #eee;">
  <h2 style="font-size:20px;font-weight:700;color:#1a1a1a;margin:0 0 24px;text-align:center;">
    {section_title}
  </h2>
  <div style="display:flex;flex-wrap:wrap;gap:24px;justify-content:center;">
    {cards_html}
  </div>
</div>
"""


def select_styling_matches(main_product: dict, pool: list, num_matches: int = 2) -> list[dict]:
    main_type = (main_product.get("product_type") or "").lower()
    main_id = main_product.get("id")
    
    # Categorize broad clothing types
    is_top = any(x in main_type for x in ["top", "blouse", "shirt", "tee"])
    is_bottom = any(x in main_type for x in ["jean", "pant", "skirt", "legging", "short"])
    is_one_piece = any(x in main_type for x in ["dress", "jumpsuit", "romper"])
    
    matches = []
    
    # Try to find items of complementary types first
    complementary_pool = []
    for p in pool:
        if p.get("id") == main_id or not p.get("images"):
            continue
        ptype = (p.get("product_type") or "").lower()
        
        if is_top:
            if any(x in ptype for x in ["jean", "pant", "skirt", "jacket", "coat", "cardigan", "accessory"]):
                complementary_pool.append(p)
        elif is_bottom:
            if any(x in ptype for x in ["top", "blouse", "shirt", "tee", "sweater", "jacket", "coat", "cardigan"]):
                complementary_pool.append(p)
        elif is_one_piece:
            if any(x in ptype for x in ["jacket", "coat", "cardigan", "accessory", "shoe", "bag"]):
                complementary_pool.append(p)
        else:
            complementary_pool.append(p)
            
    if len(complementary_pool) >= num_matches:
        matches = random.sample(complementary_pool, num_matches)
    else:
        fallback_pool = [p for p in pool if p.get("id") != main_id and p.get("images")]
        if len(fallback_pool) >= num_matches:
            matches = random.sample(fallback_pool, num_matches)
        else:
            matches = fallback_pool
            
    return matches


def crop_to_fit(img, target_w, target_h):
    """Helper to crop and resize an image to fit target bounds cleanly (center crop)."""
    img_ratio = img.width / img.height
    target_ratio = target_w / target_h
    
    if img_ratio > target_ratio:
        # Image is wider
        new_h = target_h
        new_w = int(img.width * (target_h / img.height))
        img_resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        crop_x = (new_w - target_w) // 2
        return img_resized.crop((crop_x, 0, crop_x + target_w, target_h))
    else:
        # Image is taller
        new_w = target_w
        new_h = int(img.height * (target_w / img.width))
        img_resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        crop_y = (new_h - target_h) // 2
        return img_resized.crop((0, crop_y, target_w, crop_y + target_h))


def generate_outfit_collage(main_product: dict, matching_products: list) -> Path | None:
    """
    Downloads the featured images of the main product and matches,
    creates a beautiful side-by-side outfit collage (1200x630),
    and saves it locally.
    """
    images_to_load = []
    
    main_imgs = main_product.get("images", [])
    if main_imgs:
        images_to_load.append(main_imgs[0]["src"])
        
    for p in matching_products:
        imgs = p.get("images", [])
        if imgs:
            images_to_load.append(imgs[0]["src"])
            
    if not images_to_load:
        return None
        
    print(f"  Downloading {len(images_to_load)} images to create styling collage...")
    downloaded_imgs = []
    for url in images_to_load:
        try:
            r = requests.get(url, timeout=15)
            if r.status_code == 200:
                img = Image.open(BytesIO(r.content))
                downloaded_imgs.append(img)
            else:
                print(f"    [!] Failed to download {url[:60]}... (HTTP {r.status_code})")
        except Exception as e:
            print(f"    [!] Error downloading {url[:60]}...: {e}")
            
    if not downloaded_imgs:
        return None
        
    canvas_w, canvas_h = 1200, 630
    collage = Image.new("RGB", (canvas_w, canvas_h), (255, 255, 255))
    
    num_imgs = len(downloaded_imgs)
    
    try:
        if num_imgs == 1:
            img = downloaded_imgs[0]
            img_ratio = img.width / img.height
            target_ratio = canvas_w / canvas_h
            
            if img_ratio > target_ratio:
                new_h = canvas_h
                new_w = int(img.width * (canvas_h / img.height))
                img_resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                crop_x = (new_w - canvas_w) // 2
                img_cropped = img_resized.crop((crop_x, 0, crop_x + canvas_w, canvas_h))
            else:
                new_w = canvas_w
                new_h = int(img.height * (canvas_w / img.width))
                img_resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                crop_y = (new_h - canvas_h) // 2
                img_cropped = img_resized.crop((0, crop_y, canvas_w, crop_y + canvas_h))
                
            collage.paste(img_cropped, (0, 0))
            
        elif num_imgs == 2:
            spacing = 25
            col_w = (canvas_w - (3 * spacing)) // 2
            col_h = canvas_h - (2 * spacing)
            
            for i, img in enumerate(downloaded_imgs):
                img_resized = crop_to_fit(img, col_w, col_h)
                left = spacing + i * (col_w + spacing)
                top = spacing
                collage.paste(img_resized, (left, top))
                
        else:
            spacing = 20
            col_w = (canvas_w - (4 * spacing)) // 3
            col_h = canvas_h - (2 * spacing)
            
            for i, img in enumerate(downloaded_imgs[:3]):
                img_resized = crop_to_fit(img, col_w, col_h)
                left = spacing + i * (col_w + spacing)
                top = spacing
                collage.paste(img_resized, (left, top))
                
        temp_path = Path("collage_temp.jpg")
        collage.save(temp_path, "JPEG", quality=92)
        print(f"  ✓ Collage generated locally: {temp_path.absolute()}")
        return temp_path
    except Exception as e:
        print(f"  [!] Failed to generate image collage: {e}")
        return None


def upload_image_to_shopify(filepath: Path, filename: str) -> str | None:
    """Uploads the generated collage to Shopify Files and fetches its CDN URL."""
    print(f"  Uploading {filename} to Shopify Files...")
    graphql_url = f"https://{SHOP}/admin/api/{API_VER}/graphql.json"
    
    staged_mut = f"""
    mutation {{
      stagedUploadsCreate(input: [{{
        resource: FILE,
        filename: "{filename}",
        mimeType: "image/jpeg",
        httpMethod: POST
      }}]) {{
        stagedTargets {{
          url
          resourceUrl
          parameters {{
            name
            value
          }}
        }}
      }}
    }}
    """
    try:
        r = requests.post(graphql_url, headers=HEADERS, json={"query": staged_mut}, timeout=30)
        r.raise_for_status()
        data = r.json()
        target = data["data"]["stagedUploadsCreate"]["stagedTargets"][0]
        
        # Upload the file to staging
        with open(filepath, "rb") as f:
            files = {"file": (filename, f, "image/jpeg")}
            params = {p["name"]: p["value"] for p in target["parameters"]}
            upload_resp = requests.post(target["url"], data=params, files=files, timeout=30)
            upload_resp.raise_for_status()
            
        # Create file reference in Shopify
        create_mut = """
        mutation fileCreate($files: [FileCreateInput!]!) {
          fileCreate(files: $files) {
            files {
              id
              fileStatus
            }
            userErrors {
              message
            }
          }
        }
        """
        variables = {
            "files": [
                {
                    "originalSource": target["resourceUrl"],
                    "contentType": "FILE"
                }
            ]
        }
        r = requests.post(graphql_url, headers=HEADERS, json={"query": create_mut, "variables": variables}, timeout=30)
        r.raise_for_status()
        create_data = r.json()
        
        user_errors = create_data.get("data", {}).get("fileCreate", {}).get("userErrors", [])
        if user_errors:
            print(f"  [!] Shopify fileCreate user errors: {user_errors}")
            return None
            
        file_id = create_data["data"]["fileCreate"]["files"][0]["id"]
        
        # Wait for file compilation
        public_url = None
        for _ in range(15):
            time.sleep(2)
            query_file = f"""
            query {{
              node(id: "{file_id}") {{
                ... on GenericFile {{
                  url
                  fileStatus
                }}
              }}
            }}
            """
            r = requests.post(graphql_url, headers=HEADERS, json={"query": query_file}, timeout=30)
            r.raise_for_status()
            node_data = r.json()
            node = node_data.get("data", {}).get("node", {})
            if node.get("fileStatus") == "READY":
                public_url = node.get("url")
                break
                
        if public_url:
            cdn_url = public_url.split("?")[0]
            print(f"  ✓ Uploaded successfully: {cdn_url}")
            return cdn_url
        else:
            print("  [!] Timeout waiting for image compilation on Shopify CDN.")
            return None
    except Exception as e:
        print(f"  [!] Failed to upload image to Shopify: {e}")
        return None


def generate_articles_from_research(
    research: dict,
    type_map: dict,
    count: int = 1,
    dry_run: bool = False,
    publish: bool = False,
) -> list[dict]:
    """
    Generate and optionally publish `count` original articles from research data.
    Returns a list of article result dicts.
    """
    print(f"\n━━ PHASE 4: Generating {count} original article(s) ━━")

    # Flatten product types into a prioritized pool
    # Prioritise types with the most Flipboard article data
    type_pool = sorted(
        research.items(),
        key=lambda kv: kv[1].get("articles_found", 0),
        reverse=True,
    )

    used_angles: set[str] = set()
    results: list[dict] = [] # type: ignore
    pen_names_cycle = PEN_NAMES.copy()
    random.shuffle(pen_names_cycle)

    for i in range(count):
        print(f"\n  ─ Article {i+1}/{count} ─")

        # Pick a product type (cycle through pool)
        ptype, research_data = type_pool[i % len(type_pool)]

        # Pick a sample product
        sample_products_meta = research_data.get("sample_products", [])
        if not sample_products_meta:
            print(f"  [SKIP] No sample products for {ptype}")
            continue

        # Re-fetch a full product for image + price
        prod_meta = random.choice(sample_products_meta)
        prod_handle = prod_meta.get("handle", "")
        try:
            r = _req("get", f"{BASE}/products.json",
                     params={"handle": prod_handle, "fields": "id,title,handle,product_type,variants,images"})
            r.raise_for_status()
            prods = r.json().get("products", [])
            product = prods[0] if prods else {"title": prod_meta["title"], "handle": prod_handle,
                                               "variants": [{"price": "49"}], "images": []}
        except Exception:
            product = {"title": prod_meta["title"], "handle": prod_handle,
                       "variants": [{"price": "49"}], "images": []}

        # Flatten all products from type_map for collage + angle selection
        all_products_flat = [p for p_type_list in type_map.values() for p in p_type_list]

        # Select styling matches for collage and prompt
        matching_products = select_styling_matches(product, all_products_flat, num_matches=2)

        # Pick an article angle
        angle = _pick_article_angle(ptype, research_data, used_angles, all_products_flat)
        if not angle:
            print(f"  [SKIP] No fresh angles remaining for {ptype}")
            continue

        used_angles.add(angle["angle_key"])

        # Generate featured image collage
        img_url = None
        collage_path = generate_outfit_collage(product, matching_products)
        if collage_path and collage_path.exists():
            if not dry_run:
                ts = int(time.time())
                filename = f"styling_collage_{product['id']}_{ts}.jpg"
                img_url = upload_image_to_shopify(collage_path, filename)
                try:
                    collage_path.unlink()
                except Exception:
                    pass
            else:
                img_url = f"file:///{collage_path.absolute().as_posix()}"
        if not img_url:
            print("  [WARN] Could not create collage, falling back to single product image.")

        print(f"  Product type : {ptype}")
        print(f"  Product      : {product.get('title', prod_handle)}")
        print(f"  Angle        : {angle['title']}")
        print(f"  Format       : {angle['format']}")
        print(f"  Handle       : {angle['handle_slug']}")

        # Build prompt
        prompt = _build_article_prompt(angle, product, research_data, matching_products)

        # Generate with AI
        print(f"  Generating content via AI…")
        raw = ai_client.generate(prompt, max_tokens=2000, temperature=0.72)

        if not raw:
            print(f"  [WARN] AI returned nothing for '{angle['title']}' — skipping")
            continue

        html_body  = _clean_html(raw)
        seometa    = _parse_seometa(raw)
        pen_name   = pen_names_cycle[i % len(pen_names_cycle)]
        
        # Inject product card and related products section
        html_body = inject_product_card(html_body, product, ptype)
        html_body += make_related_products_section(all_products_flat, product.get("handle", ""), ptype, matching_products)

        # SEO meta fallbacks
        if not seometa["seo_title"] or len(seometa["seo_title"]) > 70:
            seometa["seo_title"] = f"{angle['title'][:55]} | MeeeShop"
        if not seometa["meta_desc"] or len(seometa["meta_desc"]) > 165:
            seometa["meta_desc"] = (
                f"Discover {angle['ptype_clean']} styling tips for women in {YEAR}. "
                f"Shop MeeeShop — free US shipping on $50+, 7-day returns, sizes XS–3X."
            )[:155]
        if not seometa["img_alt"]:
            seometa["img_alt"] = f"{ptype} outfit ideas for women {YEAR} — MeeeShop fashion guide"

        # Tags
        base_tags = [
            "women fashion", "MeeeShop", f"fashion {YEAR}", angle["ptype_clean"],
            "USA fashion", f"denim trends {YEAR}", "quiet luxury", "style tips",
        ]
        tags = list(dict.fromkeys(base_tags + seometa["suggested_tags"]))[:25]

        result = {
            "angle":       angle,
            "ptype":       ptype,
            "product":     product,
            "title":       angle["title"],
            "handle":      angle["handle_slug"],
            "html_body":   html_body,
            "seometa":     seometa,
            "tags":        tags,
            "img_url":     img_url,
            "pen_name":    pen_name,
            "word_count":  len(re.sub(r"<[^>]+>", "", html_body).split()),
        }
        results.append(result)

        print(f"  Generated    : {result['word_count']} words")
        print(f"  SEO title    : {seometa['seo_title']}")
        print(f"  Handle       : {angle['handle_slug']}")

        if dry_run:
            print(f"  [DRY RUN] Saving as draft preview — no live publish")
            _save_dry_run_preview(result)
        elif publish:
            _publish_to_shopify(result, published=True)
        else:
            # Default: save as Shopify DRAFT (published=False) for human review
            _publish_to_shopify(result, published=False)
            print(f"  [DRAFT] Saved to Shopify as draft — review in admin before publishing")

    return results


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 5 — PUBLISH: Push to Shopify
# ══════════════════════════════════════════════════════════════════════════════

def _get_or_create_blog(ptype: str, all_blogs: list) -> dict:
    """Route article to the correct Shopify blog by product type."""
    ptype_lower = ptype.lower()
    target = None

    if any(x in ptype_lower for x in ["jean", "denim"]):
        target = "jeans"
    elif "dress" in ptype_lower:
        target = "dresses"
    elif any(x in ptype_lower for x in ["skirt", "skort"]):
        target = "skirts"
    elif any(x in ptype_lower for x in ["pant", "legging", "short"]):
        target = "pants"
    elif any(x in ptype_lower for x in ["top", "blouse", "shirt", "tee", "tank"]):
        target = "shirts & tops"
    elif any(x in ptype_lower for x in ["jacket", "coat", "blazer", "outerwear"]):
        target = "coats & jackets"
    elif any(x in ptype_lower for x in ["sweater", "cardigan", "knit"]):
        target = "cardigans & sweaters"
    elif "swimwear" in ptype_lower:
        target = "swimwear"
    elif "activewear" in ptype_lower:
        target = "activewear"

    if target:
        for blog in all_blogs:
            if target in blog.get("title", "").lower():
                return blog

    # Fallback: Women's Clothing or first non-system blog
    for blog in all_blogs:
        t = blog.get("title", "").lower()
        if "women" in t and "cloth" in t:
            return blog
    for blog in all_blogs:
        t = blog.get("title", "").lower()
        if "announcement" not in t and "tip" not in t:
            return blog

    return all_blogs[0] if all_blogs else {"id": 0, "title": "Fallback"}


def _publish_to_shopify(result: dict, published: bool = True) -> bool:
    """Publish or draft the generated article to Shopify.
    
    Args:
        result: Article result dict.
        published: True = publish live. False = save as draft in Shopify admin.
    """
    angle     = result["angle"]
    seometa   = result["seometa"]
    pen_name  = result["pen_name"]

    # Get all blogs
    r = _req("get", f"{BASE}/blogs.json")
    r.raise_for_status()
    all_blogs = r.json().get("blogs", [])

    blog = _get_or_create_blog(result["ptype"], all_blogs)
    blog_id = blog["id"]

    article_payload = {
        "article": {
            "title":         result["title"],
            "author":        pen_name,
            "body_html":     result["html_body"],
            "summary_html":  seometa["meta_desc"],
            "tags":          ", ".join(result["tags"]),
            "published":     published,
            "handle":        result["handle"],
            "metafields": [
                {"namespace": "seo", "key": "title",
                 "value": seometa["seo_title"], "type": "single_line_text_field"},
                {"namespace": "seo", "key": "description",
                 "value": seometa["meta_desc"], "type": "single_line_text_field"},
            ],
        }
    }

    # Attach featured image
    if result.get("img_url"):
        article_payload["article"]["image"] = {
            "src": result["img_url"],
            "alt": seometa["img_alt"],
        }

    action = "Publishing" if published else "Saving as draft"
    print(f"  {action} to blog: '{blog.get('title')}' (id={blog_id})…")
    r = _req("post", f"{BASE}/blogs/{blog_id}/articles.json", json=article_payload)

    if r.status_code in (200, 201):
        art = r.json().get("article", {})
        art_id = art.get("id")
        art_handle = art.get("handle")
        status_icon = "✅" if published else "📝"
        status_word = "Published" if published else "Saved as draft"
        print(f"  {status_icon} {status_word}! Article ID={art_id} | Handle: {art_handle}")
        print(f"     Admin URL: https://{SHOP}/admin/blogs/{blog_id}/articles/{art_id}")
        if published:
            print(f"     Live URL:  {STORE_URL}/blogs/{blog.get('handle', 'news')}/{art_handle}")
        return True
    else:
        print(f"  ❌ Publish failed: {r.status_code} — {r.text[:200]}")
        return False


def _save_dry_run_preview(result: dict):
    """Save a dry-run preview to the logs directory."""
    preview_path = LOG_DIR / f"preview_{result['handle']}_{int(time.time())}.html"
    author_line = f"<!-- Author: {result['pen_name']} | Handle: {result['handle']} -->"
    meta_comment = (
        f"<!-- SEO Title: {result['seometa']['seo_title']} -->\n"
        f"<!-- Meta Desc: {result['seometa']['meta_desc']} -->\n"
        f"<!-- Tags: {', '.join(result['tags'])} -->\n"
    )
    full_html = f"<!DOCTYPE html><html><head><title>{result['title']}</title></head><body>\n"
    full_html += f"{author_line}\n{meta_comment}\n{result['html_body']}\n</body></html>"

    with open(preview_path, "w", encoding="utf-8") as f:
        f.write(full_html)
    print(f"  [DRY RUN] Preview saved → {preview_path}")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(
        description="MeeeShop Trend Article Engine — research Flipboard + generate + publish"
    )
    ap.add_argument("--count", type=int, default=1,
                    help="Number of articles to generate (default: 1)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Generate articles but do NOT publish or draft to Shopify — HTML preview only")
    ap.add_argument("--publish", action="store_true",
                    help="Publish articles live immediately (default: save as draft for review)")
    ap.add_argument("--research-only", action="store_true",
                    help="Only run research phases (1-3), do not generate articles")
    ap.add_argument("--from-log", action="store_true",
                    help="Skip research, load latest log and go straight to generation")
    ap.add_argument("--log-file", type=str, default=None,
                    help="Use a specific log file path instead of latest")
    args = ap.parse_args()

    print("\n" + "═" * 60)
    print("  MeeeShop Trend Article Engine")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')} | Count: {args.count}")
    if args.dry_run:       print("  MODE: DRY RUN (HTML preview only — no Shopify)")
    elif args.publish:     print("  MODE: PUBLISH LIVE")
    else:                  print("  MODE: DRAFT (saves to Shopify admin as draft)")
    if args.research_only: print("  MODE: RESEARCH ONLY")
    if args.from_log:      print("  MODE: FROM LOG (skip research)")
    print("═" * 60)

    # ── PHASES 1-3: Research ─────────────────────────────────────────────────
    if args.from_log or args.log_file:
        if args.log_file:
            log_path = Path(args.log_file)
            print(f"\n  Loading log: {log_path}")
            with open(log_path, encoding="utf-8") as f:
                log_data = json.load(f)
        else:
            log_data = load_latest_log()

        if not log_data:
            sys.exit("ERROR: No log data found. Run without --from-log first.")

        research = log_data.get("research", {})
        # Rebuild a minimal type_map from research sample_products for collage use
        type_map = {}
        for ptype, rdata in research.items():
            type_map[ptype] = rdata.get("sample_products", [])
        print(f"  Loaded research for {len(research)} product types from log.")

    else:
        # Phase 1: Shopify product types
        store_info = fetch_store_product_types()
        type_map   = store_info["types"]

        # Phase 2: Flipboard research
        research = research_flipboard_per_category(type_map)

        # Phase 3: Save log
        log_path = save_research_log(research, store_info)
        print(f"\n  Research log: {log_path}")

    if args.research_only:
        print("\n  ✅ Research complete. Use --from-log to generate articles.")
        return

    # ── PHASE 4-5: Generate + Publish/Draft ────────────────────────────────
    results = generate_articles_from_research(
        research=research,
        type_map=type_map,
        count=args.count,
        dry_run=args.dry_run,
        publish=args.publish,
    )

    # ── Summary ──────────────────────────────────────────────────────────────
    print("\n" + "═" * 60)
    if args.dry_run:
        mode_label = "previewed (dry run)"
    elif args.publish:
        mode_label = "published live"
    else:
        mode_label = "saved as draft in Shopify admin"
    print(f"  DONE — {len(results)} article(s) {mode_label}")
    for r in results:
        if args.dry_run:    status = "DRY RUN"
        elif args.publish:  status = "PUBLISHED"
        else:               status = "DRAFT"
        print(f"  [{status}] '{r['title'][:60]}' | Handle: {r['handle']}")
    print("═" * 60)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()

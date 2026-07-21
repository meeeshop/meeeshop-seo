#!/usr/bin/env python3
"""
weekly_trend_blog.py — Weekly Trend-Based Blog Automation for MeeeShop
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

WHAT IT DOES:
  1. DISCOVER  — Fetches product categories & types from Shopify.
  2. RESEARCH  — Queries Flipboard RSS feeds & search for topics in the past 48 hours.
  3. READ      — Downloads the full content of those trending articles.
  4. EXTRACT   — Extracts long-tail and zero search volume keywords from the text.
  5. MAP LINKS — Fetches Shopify collections & other articles to construct a keyword-to-URL map.
  6. GENERATE  — Formulates a prompt targeting USA women readers with engaging, educational content
                 (clothing care, stains, stinky smells, etc.) and uses AI to write the post.
  7. LINK      — Injects natural internal links into the HTML content based on the keyword-to-URL map.
  8. COLLAGE   — Creates a styled outfit collage using PIL from the main and complementary product images,
                 uploads to Shopify Files via GraphQL, and sets as featured image.
  9. PUBLISH   — Saves the article as a Shopify blog draft (or publishes it live).
"""

import os
import sys
import re
import time
import json
import random
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin
from io import BytesIO
import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from PIL import Image, ImageOps

# ── Path Setup ────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT   = SCRIPT_DIR.parent
LOG_DIR     = REPO_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(REPO_ROOT))

import ai_client
from secrets_manager import inject_to_env, get_secret
from utils import (
    download_article_content,
    extract_keywords,
    generate_collage,
    extract_handle_count,
    is_product_compatible,
    select_styling_matches
)
from internal_linker import (
    LinkMap,
    extract_existing_links,
    inject_link_into_html,
    clean_previous_widgets,
    fetch_all_collections,
    fetch_all_blogs,
    fetch_articles as linker_fetch_articles,
    COLLECTION_HANDLE_TO_ID,
    COLLECTION_ID_TO_PRODUCTS,
    fetch_products_for_collection
)

inject_to_env()

# ── Shopify credentials ────────────────────────────────────────────────────────
SHOP    = get_secret("SHOPIFY_STORE")
TOKEN   = get_secret("SHOPIFY_ACCESS_TOKEN")
API_VER = "2024-10"
BASE    = f"https://{SHOP}/admin/api/{API_VER}"
HEADERS = {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}
STORE_URL = get_secret("STORE_BASE_URL") or f"https://{SHOP}"
try:
    BRAND_NAME = get_secret("BRAND_NAME")
except KeyError:
    BRAND_NAME = "MeeeShop"

if not TOKEN:
    sys.exit("ERROR: SHOPIFY_ACCESS_TOKEN not set.")

YEAR  = datetime.now().year
MONTH = datetime.now().strftime("%B %Y")
TODAY = datetime.now().strftime("%Y-%m-%d")

# ── Pen names ──────────────────────────────────────────────────────────────────
PEN_NAMES = [
    f"Elena Vance, {BRAND_NAME} Lead Stylist",
    f"Seraphina Croft, {BRAND_NAME} Fashion Editor",
    f"Audrey Sterling, {BRAND_NAME} Style Director",
    f"Maya Devereaux, {BRAND_NAME} Fashion Consultant",
    f"Vivienne Vance, {BRAND_NAME} Senior Stylist",
    f"Genevieve Thorne, {BRAND_NAME} Trend Forecaster",
]

# ── Flipboard topic map per product category ───────────────────────────────────
FLIPBOARD_TOPIC_MAP = {
    "jean":       ["jeans", "denim", "womens-jeans", "dark-wash-jeans"],
    "dress":      ["dresses", "summer-dress", "midi-dress", "womens-fashion", "dress-style"],
    "top":        ["womens-tops", "blouses", "fashion", "style", "summer-tops"],
    "blouse":     ["blouses", "womens-tops", "fashion", "office-style"],
    "skirt":      ["skirts", "midi-skirt", "womens-fashion"],
    "pant":       ["trousers", "womens-pants", "fashion", "wide-leg-pants"],
    "jacket":     ["jackets", "blazers", "outerwear", "womens-fashion", "layering"],
    "coat":       ["coats", "outerwear", "womens-fashion"],
    "sweater":    ["sweaters", "knitwear", "cozy-fashion", "fall-fashion"],
    "cardigan":   ["cardigans", "layering", "cozy-fashion"],
    "swimwear":   ["swimwear", "beach-fashion", "summer-style"],
    "activewear": ["activewear", "athleisure", "workout-style"],
    "accessory":  ["accessories", "fashion-accessories", "style"],
}

# ── Helper for rate limits ─────────────────────────────────────────────────────
def _req(method: str, url: str, **kw):
    for attempt in range(5):
        try:
            r = getattr(requests, method)(url, headers=HEADERS, timeout=30, **kw)
            if r.status_code == 429:
                # Add exponential backoff to the wait time
                wait = int(float(r.headers.get("Retry-After", 4))) + (2 ** attempt)
                print(f"  [Shopify] Rate limited — waiting {wait}s…")
                time.sleep(wait)
                continue
            return r
        except requests.exceptions.ConnectionError:
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"{method.upper()} {url} failed after 5 attempts")

# ── Phase 1: Fetch product types ───────────────────────────────────────────────
def fetch_store_product_types() -> dict:
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

    type_map: dict[str, list] = {}
    for p in all_products:
        ptype = (p.get("product_type") or "Uncategorized").strip()
        if ptype not in type_map:
            type_map[ptype] = []
        if len(type_map[ptype]) < 10:
            type_map[ptype].append(p)

    print(f"  Found {len(all_products)} products across {len(type_map)} product types")
    return {"types": type_map, "all_products": all_products}

# ── Phase 2: Flipboard fetching + Google News fallback (48-hour cutoff) ─────────
FLIPBOARD_RSS_BASE  = "https://flipboard.com/topic/{topic}/feed.rss"
FLIPBOARD_SEARCH    = "https://flipboard.com/search.json"
GOOGLE_NEWS_RSS     = "https://news.google.com/rss/search"
CUTOFF_DAYS         = 2  # 48 hours

# --- Trusted fashion sources for Google News fallback -------------------------
GOOGLE_NEWS_FASHION_SITES = [
    "site:whowhatwear.com",
    "site:refinery29.com",
    "site:harpersbazaar.com",
    "site:elle.com",
    "site:instyle.com",
    "site:glamour.com",
    "site:cosmopolitan.com",
    "site:popsugar.com",
    "site:byrdie.com",
    "site:thecut.com",
]

def _parse_rss_date(date_str: str) -> datetime | None:
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
    url = FLIPBOARD_RSS_BASE.format(topic=topic.lower().replace(" ", "-"))
    cutoff = datetime.now(timezone.utc) - timedelta(days=CUTOFF_DAYS)
    try:
        r = requests.get(url, timeout=15, headers={
            "User-Agent": f"Mozilla/5.0 (compatible; {BRAND_NAME} SEO bot/1.0)"
        })
        if r.status_code != 200:
            return []
        root = ET.fromstring(r.content)
        articles = []
        for item in root.iter("item"):
            title_el  = item.find("title")
            link_el   = item.find("link")
            desc_el   = item.find("description")
            pub_el    = item.find("pubDate")

            title = title_el.text.strip() if title_el is not None and title_el.text else ""
            link  = link_el.text.strip()  if link_el  is not None and link_el.text  else ""
            desc  = desc_el.text.strip()  if desc_el  is not None and desc_el.text  else ""

            desc = re.sub(r"<[^>]+>", "", desc).strip()
            pub_dt = _parse_rss_date(pub_el.text if pub_el is not None else "")
            
            if pub_dt and pub_dt < cutoff:
                continue

            if not title or len(title) < 10:
                continue

            articles.append({
                "title":     title,
                "link":      link,
                "summary":   desc[:400],
                "published": pub_el.text if pub_el is not None else "",
                "topic":     topic,
                "source":    "flipboard-rss",
            })
            if len(articles) >= 10:
                break
        return articles
    except Exception as e:
        print(f"    [Flipboard RSS] {topic}: {e}")
        return []

def _fetch_flipboard_search(keyword: str) -> list[dict]:
    try:
        r = requests.get(
            FLIPBOARD_SEARCH,
            params={"q": keyword, "locale": "en_US"},
            timeout=15,
            headers={"User-Agent": f"Mozilla/5.0 (compatible; {BRAND_NAME} SEO bot/1.0)"}
        )
        if r.status_code != 200:
            return []
        data = r.json()
        items = []
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
                if len(items) >= 10:
                    break
            if len(items) >= 10:
                break
        return items
    except Exception as e:
        print(f"    [Flipboard Search] {keyword}: {e}")
        return []

# ── Google News RSS fallback ───────────────────────────────────────────────────
def _fetch_google_news(keyword: str, num_sites: int = 3) -> list[dict]:
    """Query Google News RSS for fashion articles (last 48 h, USA) from trusted sites.

    Uses the public Google News RSS endpoint — no API key needed. Tries a handful
    of trusted fashion publishers (Who What Wear, Refinery29, etc.) to surface
    relevant, high-quality trend articles.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=CUTOFF_DAYS)
    results = []
    site_filters = random.sample(GOOGLE_NEWS_FASHION_SITES, min(num_sites, len(GOOGLE_NEWS_FASHION_SITES)))

    for site_filter in site_filters:
        q = f"{keyword} women fashion {site_filter} when:2d"
        try:
            r = requests.get(
                GOOGLE_NEWS_RSS,
                params={"q": q, "hl": "en-US", "gl": "US", "ceid": "US:en"},
                timeout=15,
                headers={"User-Agent": f"Mozilla/5.0 (compatible; {BRAND_NAME} SEO bot/1.0)"},
            )
            if r.status_code != 200:
                continue
            root = ET.fromstring(r.content)
            for item in root.iter("item"):
                title_el = item.find("title")
                link_el  = item.find("link")
                pub_el   = item.find("pubDate")

                title = (title_el.text or "").strip() if title_el is not None else ""
                # Google News links are redirect URLs — grab the real URL from <link> text
                link  = (link_el.text or "").strip() if link_el is not None else ""

                if not title or len(title) < 10:
                    continue

                pub_dt = _parse_rss_date(pub_el.text if pub_el is not None else "")
                if pub_dt and pub_dt < cutoff:
                    continue

                results.append({
                    "title":       title,
                    "link":        link,
                    "summary":     "",
                    "published":   pub_el.text if pub_el is not None else "",
                    "topic":       keyword,
                    "source":      f"google-news:{site_filter}",
                    "full_content": "",
                })
                if len(results) >= 8:
                    break
            time.sleep(0.4)
        except Exception as e:
            print(f"    [Google News] {site_filter} / {keyword}: {e}")
    return results

def research_flipboard_per_category(type_map: dict) -> dict:
    print("\n━━ PHASE 2: Researching Flipboard trends (last 48 hours) ━━")
    research: dict[str, dict] = {}

    for ptype, sample_products in type_map.items():
        ptype_lower = ptype.lower()
        topics_to_query = []
        for key, topics in FLIPBOARD_TOPIC_MAP.items():
            if key in ptype_lower:
                topics_to_query = topics
                break
        if not topics_to_query:
            topics_to_query = ["womens-fashion", "style"]

        print(f"  [{ptype}] Querying Flipboard topics: {topics_to_query}")
        all_articles = []
        for topic in topics_to_query:
            rss_articles = _fetch_flipboard_rss(topic)
            all_articles.extend(rss_articles)
            time.sleep(0.3)

        # ── Flipboard search (Who What Wear / Refinery29 style) ──────────────
        queries = [
            f"Who What Wear {ptype_lower}",
            f"Refinery29 {ptype_lower}",
            f"women {ptype_lower} style trend"
        ]
        flipboard_search_found = 0
        for q in queries:
            print(f"    Searching Flipboard for: '{q}'...")
            search_articles = _fetch_flipboard_search(q)
            all_articles.extend(search_articles)
            flipboard_search_found += len(search_articles)

        # ── Google News fallback when Flipboard search is empty ───────────────
        if flipboard_search_found == 0:
            print(f"    [Fallback] Flipboard search empty — trying Google News for: '{ptype_lower}'...")
            gn_articles = _fetch_google_news(ptype_lower)
            all_articles.extend(gn_articles)
            if gn_articles:
                print(f"    [Google News] Found {len(gn_articles)} articles.")

        # Deduplicate
        seen = set()
        unique = []
        for a in all_articles:
            norm_title = re.sub(r"\W+", "", a["title"].lower())[:40]
            if norm_title not in seen:
                seen.add(norm_title)
                unique.append(a)

        # Slice to target subset for full text download
        target_articles = unique[:4]

        # Download content only for the target articles
        for art in target_articles:
            if art.get("link") and not art.get("full_content"):
                print(f"    [Scraper] Downloading trend reference: '{art['title'][:60]}...'")
                art["full_content"] = download_article_content(art["link"])

        # Extract keywords
        long_tail = []
        zero_search = []
        for a in target_articles:
            if a.get("full_content"):
                kws = extract_keywords(a["full_content"])
                long_tail.extend(kws.get("long_tail", []))
                zero_search.extend(kws.get("zero_search", []))

        # Always inject specific care/maintenance/stain topics for testing if none found
        if ptype_lower == "jean" or "jean" in ptype_lower:
            long_tail.extend(["how to maintain jeans", "how to care for jeans", "how to remove stinky smell", "how to clean stains", "how to remove piling"])
            zero_search.extend(["remove stinky smell from denim", "clean jeans stain naturally"])

        research[ptype] = {
            "product_type": ptype,
            "sample_products": [{"id": p["id"], "title": p["title"], "handle": p["handle"]} for p in sample_products],
            "articles": target_articles,
            "keywords": {
                "long_tail": list(set(long_tail))[:10],
                "zero_search": list(set(zero_search))[:10]
            }
        }
    return research

# ── Link Map Builder (Internal Links) ──────────────────────────────────────────
def build_linker_map() -> LinkMap:
    print("\n━━ PHASE 3: Building Internal Link Map ━━")
    link_map = LinkMap()
    
    # Collections
    collections = fetch_all_collections()
    for col in collections:
        title = col.get("title", "")
        handle = col.get("handle", "")
        cid = col.get("id")
        if handle and cid:
            COLLECTION_HANDLE_TO_ID[handle] = cid
        if title and handle:
            link_map.add_collection(title, handle)

    # Articles
    blogs = fetch_all_blogs()
    for blog in blogs:
        articles = linker_fetch_articles(blog["id"])
        for art in articles:
            title = art.get("title", "")
            blog_handle = blog.get("handle", "")
            art_handle = art.get("handle", "")
            if title and blog_handle and art_handle:
                link_map.add_article(title, blog_handle, art_handle)
                
    print(f"  Link map populated with {len(link_map.keyword_to_urls)} keywords.")
    return link_map

# ── In-Article Internal Link Injector ─────────────────────────────────────────
def inject_internal_links(html_body: str, link_map: LinkMap, article_title: str) -> str:
    from internal_linker import find_unlinked_keywords
    existing_links = extract_existing_links(html_body)
    suggestions = find_unlinked_keywords(html_body, existing_links, link_map, article_context=article_title)
    
    injected_count = 0
    modified_html = html_body
    for sugg in suggestions:
        if injected_count >= 3: # inject max 3 links
            break
        keyword = sugg["keyword"]
        url = sugg["url"]
        anchor_text = sugg["anchor_text"]
        
        # Avoid self-linking or redundant links
        if url.lower() in existing_links:
            continue
            
        new_html, was_injected = inject_link_into_html(modified_html, keyword, url, anchor_text)
        if was_injected:
            modified_html = new_html
            injected_count += 1
            print(f"  [Linker] Injected link for '{keyword}' -> {url}")
            existing_links.add(url.lower())
            
    return modified_html

# ── Collage generation & Shopify Upload ────────────────────────────────────────
def upload_image_to_shopify(filepath: Path, filename: str) -> str | None:
    print(f"  Uploading {filename} to Shopify Files via GraphQL...")
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
        target = r.json()["data"]["stagedUploadsCreate"]["stagedTargets"][0]
        
        with open(filepath, "rb") as f:
            form_data = []
            for p in target["parameters"]:
                form_data.append((p["name"], p["value"]))
            form_data.append(("file", (filename, f, "image/jpeg")))
            
            upload_resp = requests.post(target["url"], files=form_data, timeout=30)
            if upload_resp.status_code not in (200, 201):
                print(f"  [!] Staged upload failed with status {upload_resp.status_code}. Response body:")
                print(upload_resp.text)
            upload_resp.raise_for_status()
            
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
        
        file_id = create_data["data"]["fileCreate"]["files"][0]["id"]
        
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
            node = r.json().get("data", {}).get("node", {})
            if node.get("fileStatus") == "READY":
                cdn_url = node.get("url").split("?")[0]
                print(f"  ✓ Image ready: {cdn_url}")
                return cdn_url
        return None
    except Exception as e:
        print(f"  [!] Failed GraphQL image upload: {e}")
        return None

# ── Dynamic Product Card Injections ───────────────────────────────────────────
def make_product_card(product: dict, label: str = "FEATURED FAVORITE") -> str:
    title = product["title"]
    price = product["variants"][0]["price"] if product.get("variants") else "49"
    handle = product.get("handle", "")
    url = f"{STORE_URL}/products/{handle}?utm_source=blog&utm_medium=card"
    img = product["images"][0]["src"] if product.get("images") else ""
    
    img_html = f'<a href="{url}"><img src="{img}" alt="{title}" style="width:200px;height:200px;object-fit:cover;border-radius:8px;" /></a>' if img else ""
    
    return f"""
<div style="background:#f9f9f9;border:1px solid #eee;border-radius:12px;padding:20px;margin:24px 0;display:flex;gap:20px;align-items:center;font-family:sans-serif;">
  {img_html}
  <div>
    <p style="font-size:11px;color:#888;margin:0 0 4px;text-transform:uppercase;font-weight:bold;">{label}</p>
    <h3 style="margin:0 0 8px;font-size:16px;color:#111;">{title}</h3>
    <p style="font-size:20px;font-weight:bold;margin:0 0 12px;color:#111;">${price}</p>
    <a href="{url}" style="background:#111;color:#fff;padding:10px 20px;text-decoration:none;border-radius:6px;font-size:13px;font-weight:bold;display:inline-block;">Shop Now →</a>
  </div>
</div>
"""

def make_related_products_section(products: list) -> str:
    cards_html = ""
    for p in products:
        title = p["title"]
        price = p["variants"][0]["price"] if p.get("variants") else "49"
        handle = p.get("handle", "")
        url = f"{STORE_URL}/products/{handle}?utm_source=blog&utm_medium=related"
        img = p["images"][0]["src"] if p.get("images") else ""
        img_html = f'<a href="{url}"><img src="{img}" alt="{title}" style="width:100%;height:180px;object-fit:cover;border-radius:6px;margin-bottom:8px;" /></a>' if img else ""
        
        cards_html += f"""
<div style="flex:1;min-width:180px;max-width:220px;text-align:center;font-family:sans-serif;">
  {img_html}
  <h4 style="font-size:13px;margin:0 0 4px;color:#222;height:36px;overflow:hidden;">{title}</h4>
  <p style="font-size:14px;font-weight:bold;margin:0 0 8px;color:#111;">${price}</p>
  <a href="{url}" style="background:#eee;color:#222;padding:6px 12px;text-decoration:none;border-radius:4px;font-size:12px;font-weight:bold;display:inline-block;">View Product</a>
</div>
"""
    return f"""
<div style="margin:40px 0;padding:24px;border:1px solid #eaeaea;border-radius:12px;background:#fafafa;">
  <h3 style="font-size:18px;margin:0 0 20px;text-align:center;font-family:sans-serif;">Shop the Styled Lookbook</h3>
  <div style="display:flex;flex-wrap:wrap;gap:20px;justify-content:center;">
    {cards_html}
  </div>
</div>
"""

# ── Article Modes ──────────────────────────────────────────────────────
ARTICLE_MODES = [
    {
        "id": "fabric_care_guide",
        "title_pattern": "How to Wash & Care for {ptype} Without Ruining It",
        "angle": "fabric-care-maintenance",
        "description": "Deep-dive care & maintenance guide. Cover washing temperatures, hand vs machine wash, stain removal, odour elimination (especially denim/synthetic), preventing piling/fading, ironing & storage secrets.",
        "structure": "Intro hook (care secret) | TOC | Fabric type breakdown | Step-by-step wash guide | Stain removal table | Odour & piling prevention | Storage tips | FAQ (6 Qs) | Product recommendation woven throughout",
        "tone": "Knowledgeable friend who just saved your favourite piece",
        "title_examples": ["How to Wash Your Jeans (And When NOT To)", "The Right Way to Care for Your Midi Dress So It Lasts for Years"],
    },
    {
        "id": "outfit_ideas_occasions",
        "title_pattern": "{num} Outfit Ideas for {occasion} Using {ptype}",
        "angle": "occasion-based-outfit-inspiration",
        "description": "Curated outfit recipes for 5-7 real-life occasions (work, brunch, date night, weekend errands, travel, gym-to-street, wedding guest). Each outfit names the exact MeeeShop product + styling pairing + shoes + bag tip.",
        "structure": "Hook (relatable scenario) | TOC | 5-7 Occasion sections each with: outfit recipe + product card + styling notes | Mix & match matrix | FAQ | Related products",
        "tone": "Personal stylist texting you outfit ideas",
        "title_examples": ["7 Outfit Ideas for Every Weekend Plan This Summer", "5 Ways to Wear a Midi Dress From Brunch to Boardroom"],
    },
    {
        "id": "capsule_wardrobe",
        "title_pattern": "Build Your {season} Capsule Wardrobe with {num} {ptype} Staples",
        "angle": "capsule-wardrobe-minimalism",
        "description": "Teach readers how to build a seasonal capsule wardrobe around this product type. Show how {num} key pieces create 20+ outfits. Emphasise mix-and-match, cost-per-wear and avoiding impulse buys.",
        "structure": "Hook (why capsule?) | The formula (X pieces = Y outfits) | Each capsule piece with: what it is + why it works + how to style | The outfit matrix table | Budget breakdown | FAQ | MeeeShop product picks",
        "tone": "Thoughtful minimalist editor, warm and practical",
        "title_examples": ["Your Summer Capsule Wardrobe: 10 Pieces, 30 Outfits", "Build the Perfect Fall Wardrobe Around 1 Pair of Dark-Wash Jeans"],
    },
    {
        "id": "trend_report",
        "title_pattern": "The Biggest {ptype} Trends for {year} (And How to Wear Them)",
        "angle": "trend-forecast-real-life-translation",
        "description": "Identify 5-6 current/upcoming trends in this product category. For each trend: what it is, why it's hot right now, how real women can wear it, what to pair it with, and link to specific MeeeShop products.",
        "structure": "Trend intro hook | TOC | Each trend: name + why trending + how to wear + do's & don'ts + MeeeShop pick | Editor's top trend pick | FAQ | Related products",
        "tone": "Fashion editor sharing exclusive intel from the season's shows & street style",
        "title_examples": ["5 Dress Trends Taking Over Summer 2026", "The 6 Jean Silhouettes Fashion Editors Are Obsessed With Right Now"],
    },
    {
        "id": "styling_rules",
        "title_pattern": "{num} {ptype} Styling Rules Every Woman Should Know",
        "angle": "expert-styling-rules-secrets",
        "description": "Share {num} little-known but transformative styling rules specific to this product type. Rules should feel like insider secrets: proportion play, colour theory, layering hacks, footwear pairings, belt tricks, etc.",
        "structure": "Hook (surprising rule teaser) | TOC | Each rule: name + explanation + visual example + common mistake to avoid | Quick cheat sheet | FAQ | MeeeShop product picks",
        "tone": "Confident boutique owner who's seen every styling mistake and fix",
        "title_examples": ["11 Skirt Styling Rules Fashion Girls Swear By", "9 Handbag Styling Rules That Will Instantly Elevate Any Outfit"],
    },
    {
        "id": "body_type_guide",
        "title_pattern": "The Best {ptype} Styles for Every Body Type (2026 Guide)",
        "angle": "body-positive-proportion-styling",
        "description": "Modern, body-positive proportion guide. Instead of 'hiding' shapes, teach readers how specific {ptype} cuts/silhouettes work with different proportions. Cover petite, tall, curvy, straight-frame, pear, apple, hourglass.",
        "structure": "Hook (proportion over labels) | TOC | Each body proportion type: what to look for + what to avoid + MeeeShop picks + confidence tip | Universal rules | FAQ | Related products",
        "tone": "Inclusive, empowering stylist who celebrates all bodies",
        "title_examples": ["The Best Jeans for Every Body Type", "Which Dress Silhouette Flatters YOUR Proportions? A 2026 Guide"],
    },
    {
        "id": "one_item_multiple_ways",
        "title_pattern": "{num} Ways to Style the {main_product} (Work to Weekend)",
        "angle": "one-item-multiple-outfit-challenge",
        "description": "Deep-dive on one specific hero product. Show {num} completely different ways to style it across different occasions, seasons and moods. Include a 'What I packed for a 3-day trip using only this piece' section.",
        "structure": "Hero product spotlight | {num} styled looks each with: occasion + outfit recipe + styling notes + links | Travel packing tip | Seasonal transitions | FAQ | Related products",
        "tone": "Relatable blogger sharing her personal styling challenge diary",
        "title_examples": ["7 Ways I Styled My Soft Knit Babydoll This Week", "One Wide-Leg Jean, 9 Outfits: My Monday-to-Sunday Styling Diary"],
    },
    {
        "id": "shopping_guide_edit",
        "title_pattern": "The MeeeShop Editor's Edit: Best {ptype} to Shop Right Now",
        "angle": "curated-shopping-editors-picks",
        "description": "Curated 'editor's pick' shopping list of 8-10 {ptype} pieces. For each pick: why editors love it, how to style it, what makes it worth buying, who it's perfect for. Position MeeeShop as the trusted source.",
        "structure": "Editor intro (authority voice) | TOC | Each pick: product name + why we love it + styling recipe + who it's for | Value comparison (quality vs price) | FAQ | How to order",
        "tone": "Confident fashion editor curating her favourite finds like a magazine 'The Edit' feature",
        "title_examples": ["The 10 Best Midi Dresses to Shop This Summer", "Our Editor's Favourite Wide-Leg Jeans Right Now"],
    },
    {
        "id": "seasonal_transition",
        "title_pattern": "How to Transition Your {ptype} from {season1} to {season2}",
        "angle": "seasonal-transition-layering",
        "description": "Practical guide to making {ptype} work across two seasons through layering, fabric choices and styling tricks. Cover specific tips like: what to add, what to swap, colour palette shifts, footwear transitions.",
        "structure": "Seasonal challenge hook | TOC | The layering formula | 5-6 specific transition outfits | Fabric guide (what works in both seasons) | The 3 hero pieces to invest in | FAQ | MeeeShop picks",
        "tone": "Practical, cost-savvy stylist who hates re-buying the same thing every season",
        "title_examples": ["How to Wear Your Summer Dresses in Fall", "Transitioning Your Denim: Summer Jeans That Work All Year"],
    },
    {
        "id": "colour_palette_guide",
        "title_pattern": "The {season} Colour Palette for {ptype}: What's Trending & How to Wear It",
        "angle": "colour-theory-palette-guide",
        "description": "Explore the season's trending colour palette for this product type. Explain colour theory in plain language, how to use the trending shades, which neutrals they pair with, and how to incorporate a pop of colour without looking overwhelming.",
        "structure": "Colour trends hook | TOC | Top 5 trending colours (each: name, what it is, best pairings, avoid with) | Building a colour-cohesive outfit | Colour confidence tips for beginners | FAQ | MeeeShop colour picks",
        "tone": "Colour-obsessed art director turned stylist, approachable and inspiring",
        "title_examples": ["The 5 Dress Colours Every Stylish Woman Will Wear This Summer", "Butter Yellow, Powder Blue & Beyond: The Color Palette Dominating 2026"],
    },
    {
        "id": "stain_odour_rescue",
        "title_pattern": "How to Remove Stains & Odours from {ptype} (Without Ruining Them)",
        "angle": "problem-solving-stain-odour-removal",
        "description": "Emergency rescue guide for the most common {ptype} disasters: coffee, wine, sweat, makeup, oil, grass, mystery stains, musty smell. Provide step-by-step DIY methods using household products. Cover prevention tips too.",
        "structure": "Emergency hook (relatable stain disaster) | TOC | Stain type table (stain: method: products: time) | Step-by-step for each major stain type | Odour elimination deep dive | What NEVER to do | Prevention habits | FAQ | MeeeShop care picks",
        "tone": "Practical problem-solver sharing the cleaning secret your dry cleaner doesn't want you to know",
        "title_examples": ["How to Get Red Wine Out of Your Favourite Dress (And 9 Other Common Stains)", "Why Your Jeans Smell & How to Fix It For Good"],
    },
    {
        "id": "budget_style_guide",
        "title_pattern": "How to Look Expensive on a Budget: {ptype} Edition",
        "angle": "budget-savvy-high-low-styling",
        "description": "Teach readers how to dress like they spent a lot without actually doing so. Cover: quality markers to look for when buying, which {ptype} details signal luxury, high-low dressing, cost-per-wear calculations, and how MeeeShop finds offer designer looks for less.",
        "structure": "Budget-chic hook | TOC | The 5 markers of 'expensive-looking' {ptype} | High-low outfit formulas | Cost-per-wear breakdown | The 3 items worth spending more on | FAQ | MeeeShop picks (value champions)",
        "tone": "Savvy shopper who always looks like she spent double, sharing her secrets freely",
        "title_examples": ["How to Make a $40 Dress Look Like It Cost $200", "The Affordable Jean Brands That Look Designer (We're Obsessed)"],
    },
    {
        "id": "work_dress_code",
        "title_pattern": "What to Wear to Work: {ptype} Styling for Every Dress Code",
        "angle": "workplace-dress-code-styling",
        "description": "Guide women through styling {ptype} for different workplace dress codes: business formal, business casual, smart casual, creative casual and work-from-home chic. Show how one piece can work across multiple codes with different styling.",
        "structure": "Dress code confusion hook | TOC | Each dress code: definition + {ptype} picks + complete outfit recipe + what to avoid | Day-to-dinner transition tips | WFH to in-office styling | FAQ | MeeeShop office picks",
        "tone": "Career-oriented fashion advisor who wants women to feel powerful and appropriate at work",
        "title_examples": ["How to Wear Wide-Leg Trousers to Every Kind of Office", "Office-Ready Dresses for Every Dress Code (Business Formal to Casual)"],
    },
    {
        "id": "weekend_lifestyle",
        "title_pattern": "Your Perfect Weekend Outfit Formula with {ptype}",
        "angle": "effortless-weekend-lifestyle-content",
        "description": "Relaxed, lifestyle-led guide to effortless weekend dressing with {ptype}. Cover different weekend scenarios: farmers market, brunch, road trip, day at the beach, movie night, Sunday errands. Make it feel like a fun Saturday morning read.",
        "structure": "Relatable weekend scenario hook | TOC | 6 weekend scenarios each with: vibe + outfit recipe + why it works + MeeeShop product | The 'lazy Sunday' formula | Packing light for a weekend trip | FAQ | Related products",
        "tone": "Your stylish best friend texting you 'what are you wearing today?' energy",
        "title_examples": ["Your Ultimate Weekend Outfit Guide for Every Saturday Plan", "Effortless Brunch Outfits That Feel Expensive But Aren't"],
    },
    {
        "id": "travel_packing_guide",
        "title_pattern": "The Ultimate Travel Packing Guide: {ptype} That Work Everywhere",
        "angle": "travel-packing-versatile-wardrobe",
        "description": "Guide to packing {ptype} for travel. Cover wrinkle-resistant fabrics, versatile pieces that create multiple outfits, how to pack to avoid damage, destination-specific styling (city, beach, mountain, Euro trip), and a packing list template.",
        "structure": "Overpacking regret hook | TOC | The travel {ptype} formula | Destination guides (3-4 destinations with packing list) | Packing techniques | Anti-wrinkle care tips | FAQ | MeeeShop travel picks",
        "tone": "Well-travelled fashion editor sharing hard-learned suitcase wisdom",
        "title_examples": ["Pack Like a Pro: The Only 5 Dresses You Need for a 2-Week Trip", "The Travel Jean: What Makes a Jean Perfect for Every Destination"],
    },
    {
        "id": "handbag_guide",
        "title_pattern": "The Complete Guide to Choosing & Styling {ptype} for Any Occasion",
        "angle": "handbag-buying-styling-functionality-guide",
        "description": "Comprehensive handbag guide covering: how to choose the right size/shape/strap for your body and lifestyle, matching bags to outfits without being matchy-matchy, organisation tips to stop the 'black hole' effect, and which bag styles every woman needs. Applicable to handbags AND clothing accessories.",
        "structure": "Bag chaos hook | TOC | How to choose by body proportions | The 5 essential bag silhouettes | Outfit-to-bag matching guide | Organisation masterclass | Investment vs. budget picks | FAQ | MeeeShop bag/accessory picks",
        "tone": "Organised, practical stylist who knows how a great bag completes the look",
        "title_examples": ["Which Handbag Shape Is Right for You? A Complete Styling Guide", "11 Handbag Rules Every Stylish Woman Should Know"],
    },
    {
        "id": "grwm_personal_story",
        "title_pattern": "Get Ready With Me: How I Built {num} Outfits Around the {main_product}",
        "angle": "personal-story-GRWM-relatable-content",
        "description": "First-person narrative GRWM-style article. The MeeeShop stylist (pen name) shares her personal experience styling the hero product for different real-life situations across a week. Include styling decisions, mishaps, compliments received, and honest tips.",
        "structure": "Personal intro (why this piece caught my eye) | Day-by-day styling diary (Mon-Sat) | Styling lessons learned | Honest review of fit/fabric | How to shop it | FAQ | Related products",
        "tone": "Warm, funny, relatable first-person voice like a fashion-obsessed best friend",
        "title_examples": ["Get Ready With Me: I Wore the Same Dress 6 Ways This Week", "My Honest Review: I Tested This Viral Midi Skirt for 7 Days Straight"],
    },
    {
        "id": "plus_size_curvy_guide",
        "title_pattern": "The Best {ptype} for Curvy & Plus-Size Women: A Celebration of Your Shape",
        "angle": "inclusive-plus-size-curvy-styling",
        "description": "Inclusive, empowering guide to finding and styling {ptype} for curvy and plus-size bodies. Focus on fit principles, what features to look for (elastic waistbands, stretch fabric, adjustable closures), confidence boosting, and celebrating your shape. Feature MeeeShop products available in extended sizes.",
        "structure": "Body-celebration hook | TOC | Key fit principles for curvy proportions | What to look for in {ptype} | Style formulas that always work | Common fit problems + solutions | Confidence tips | FAQ | MeeeShop plus-size picks",
        "tone": "Body-positive champion who is passionate about every woman feeling fabulous",
        "title_examples": ["The Best Wide-Leg Jeans for Curvy Women (That Actually Fit)", "Celebrating Your Curves: The Dress Styles That Will Make You Feel Amazing"],
    },
    {
        "id": "age_decade_guide",
        "title_pattern": "How to Wear {ptype} in Your 30s, 40s & 50s: The Modern Style Guide",
        "angle": "age-inclusive-decade-styling",
        "description": "Modern, age-positive guide to styling {ptype} across different life decades. Reject the idea of 'dressing your age' and instead focus on dressing for your lifestyle, energy and confidence. Give specific styling advice and product picks for women in their 30s, 40s, and 50s+.",
        "structure": "Age-positive hook (reject old rules) | TOC | 30s: bold experimentation guide | 40s: elevated confidence guide | 50s+: effortless chic guide | Universal rules that work at any age | FAQ | MeeeShop picks for each decade",
        "tone": "Liberating, modern stylist who believes age is irrelevant when it comes to great style",
        "title_examples": ["Style Has No Age Limit: How to Wear Midi Skirts in Your 30s, 40s & 50s", "Jeans at 50? Absolutely. Here's How to Make Them Look Incredible"],
    },
    {
        "id": "gift_guide",
        "title_pattern": "The Best {ptype} Gift Ideas for the Stylish Woman in Your Life",
        "angle": "gift-guide-shopping-helper",
        "description": "Gift guide featuring {ptype} as the perfect present. Organise by budget (Under $50, $50-$100, $100+), occasion (birthday, holidays, Mother's Day, just because) and recipient personality (the minimalist, the trendsetter, the comfort lover, the professional). Each recommendation links directly to MeeeShop.",
        "structure": "Gift stress hook | TOC | By budget sections | By recipient personality | Gifting etiquette (size tips, gift wrapping ideas) | How to include a gift note | FAQ (returns, sizing) | MeeeShop product picks",
        "tone": "Helpful gift concierge who takes the stress out of finding the perfect fashion present",
        "title_examples": ["The Best Fashion Gifts for Women (For Every Budget)", "What to Gift the Woman Who Has Everything: 10 MeeeShop Picks"],
    },
    {
        "id": "splurge_vs_save",
        "title_pattern": "Splurge vs. Save: The Best {ptype} Dupes & Alternatives",
        "angle": "designer-dupes-budget-conscious-luxury",
        "description": "Inspired by Who What Wear & Refinery29. Compare luxury/designer trends or key classic pieces with budget-friendly, high-quality MeeeShop alternatives. Highlight material composition, silhouette details, and style flexibility to show how readers can get the high-end look for less.",
        "structure": "The luxury trend hook (why designer is trending) | TOC | Splurge vs. Save comparison sections with: designer details + MeeeShop alternative + product card + how to style | Material/craftsmanship comparison | Cost-per-wear breakdown | FAQ | Related products",
        "tone": "Savvy, trend-conscious fashion finder who knows quality doesn't have to break the bank",
        "title_examples": ["Splurge vs. Save: The Best Wide-Leg Jeans Dupes", "Designer Skirt Dupes: Get the Runway Look for Under $60"],
    },
    {
        "id": "three_piece_formula",
        "title_pattern": "The Easy 3-Piece Outfit Formula Involving {ptype} That Editors Swear By",
        "angle": "three-piece-outfit-styling-rules",
        "description": "Inspired by Who What Wear. Teach the foolproof 'three-piece outfit rule' (Base + Bottom + Third Piece/Statement Item) built around {ptype}. Give concrete examples of how to layer and accessorise to look instantly put-together.",
        "structure": "Hook (the styling rule explained) | TOC | Formula breakdown (Piece 1, Piece 2, Piece 3) | 5 repeatable outfit recipes using the formula | The accessory checklist | Common mistakes that break the formula | FAQ | MeeeShop picks",
        "tone": "Cool, authoritative fashion editor sharing a secret styling recipe",
        "title_examples": ["The 3-Piece Outfit Rule for Midi Dresses We Can't Stop Wearing", "This 3-Piece Outfit Formula Makes Any Pair of Pants Look Instantly Chic"],
    },
    {
        "id": "french_scandi_aesthetic",
        "title_pattern": "How to Get the Coveted {season} French-Girl Look with {ptype}",
        "angle": "aesthetic-style-guide-global-inspiration",
        "description": "Inspired by Vogue & Who What Wear. Explore highly sought-after global style aesthetics (French-Girl Chic, Scandi-Minimalism, Coastal Grandmother, Quiet Luxury) using {ptype} as the centerpiece. Teach readers how to mimic the effortless styling of these global fashion capitals.",
        "structure": "Aesthetic mood-setter hook | TOC | The Core Elements of the Aesthetic | 4 styled looks matching the aesthetic | Color palette & fabric choices | How to accessorise like a Parisian/Scandi | FAQ | MeeeShop aesthetic picks",
        "tone": "Chic, worldly travel & style writer who understands effortless global style",
        "title_examples": ["How to Style Your Tops for the Ultimate French-Girl Vibe", "The Scandi-Style Guide: Styling Wide-Leg Pants Effortlessly"],
    },
    {
        "id": "editors_wishlist",
        "title_pattern": "What's in Our Editors' Carts This Week: {season} {ptype} Edition",
        "angle": "editors-curated-wishlist-cart",
        "description": "Inspired by Cosmopolitan & Who What Wear. A highly personal, behind-the-scenes look at what MeeeShop style editors are actually adding to their personal carts right now. Highlight real reasons why they are buying, personal sizing choices, and styling plans.",
        "structure": "Behind-the-scenes hook (our editors' group chat secrets) | TOC | Editor 1's pick + personal review + product card | Editor 2's pick + personal styling plan + product card | Editor 3's pick... | The 'Will Sell Out Fast' warning list | FAQ | Related products",
        "tone": "Fun, conversational, and trendy—like a peek into a fashion editor's group chat",
        "title_examples": ["What's in My Cart: The 5 Dresses I'm Buying for Summer", "Our Editors' Wishlist: The Skirts We are Snagging Before They Sell Out"],
    },
    {
        "id": "runway_to_real_life",
        "title_pattern": "Runway to Real Life: How to Wear {season} {ptype} Trends",
        "angle": "runway-fashion-translation-wearable",
        "description": "Inspired by Vogue. Translate high-fashion, couture, or designer runway trends into wearable, comfortable, and realistic everyday street-style looks using MeeeShop's collection. Bridge the gap between high fashion and everyday utility.",
        "structure": "Runway inspiration hook (trends from Milan/Paris) | TOC | Trend 1: From Runway to Street (with MeeeShop pick) | Trend 2: Bold prints made wearable | Trend 3: Oversized proportions styled right | Real-life do's and don'ts | FAQ | Shop the runway edit",
        "tone": "Vibrant, design-fluent fashion critic who loves making high-end style accessible",
        "title_examples": ["Runway to Real Life: The Dress Trends We're Taking to the Streets", "How to Wear Runway Denim Trends in Your Everyday Life"],
    },
    {
        "id": "we_tried_it_review",
        "title_pattern": "We Tried It: I Wore the MeeeShop {main_product} for a Week",
        "angle": "honest-editor-wear-test-review",
        "description": "Inspired by Refinery29. An honest, first-hand review and wear-test of a hero MeeeShop product. Cover how it feels during a busy workday, styling versatility, washing results, and the exact fit/sizing feedback.",
        "structure": "The hype hook (the piece everyone is talking about) | TOC | First impressions (fabric, feel, fit) | Day-by-day wear log (different styling options) | The ultimate verdict (comfort, value, style) | Pros & cons list | Sizing recommendation | FAQ | Related products",
        "tone": "Completely honest, transparent, and detailed style investigator",
        "title_examples": ["We Tried It: Testing Our Best-Selling Denim for 7 Days Straight", "I Wore This Midi Dress to 5 Different Occasions: An Honest Review"],
    },
]

# Seasons and occasions for dynamic title generation
_SEASONS = ["Summer", "Fall", "Winter", "Spring", "Year-Round"]
_OCCASIONS = ["Brunch", "Date Night", "Work", "Weekend", "Travel", "a Wedding", "Summer Parties", "Holiday Events"]
_NUMS = ["5", "7", "9", "10", "11", "12"]


def _pick_article_mode(ptype: str) -> dict:
    """Pick a random article mode. Bias certain modes toward certain product types."""
    ptype_l = ptype.lower()
    # Weight handbag-specific mode higher for bag product types
    weights = [1] * len(ARTICLE_MODES)
    for idx, mode in enumerate(ARTICLE_MODES):
        mid = mode["id"]
        if "handbag" in ptype_l or "bag" in ptype_l or "purse" in ptype_l:
            if mid == "handbag_guide":
                weights[idx] = 5
        if any(x in ptype_l for x in ["jean", "denim"]):
            if mid in ("fabric_care_guide", "stain_odour_rescue", "capsule_wardrobe"):
                weights[idx] = 4
        if "dress" in ptype_l:
            if mid in ("occasion_based", "trend_report", "body_type_guide", "seasonal_transition"):
                weights[idx] = 3
        if any(x in ptype_l for x in ["top", "blouse", "shirt"]):
            if mid in ("one_item_multiple_ways", "work_dress_code", "colour_palette_guide"):
                weights[idx] = 3

    total = sum(weights)
    r = random.random() * total
    cumulative = 0
    for idx, w in enumerate(weights):
        cumulative += w
        if r < cumulative:
            return ARTICLE_MODES[idx]
    return random.choice(ARTICLE_MODES)


# ── AI Prompt Construction ──────────────────────────────────────────────────────
def _build_article_prompt(main_product: dict, research_data: dict, matching_products: list, mode: dict | None = None, original_handle_hint: str | None = None) -> tuple[str, dict]:
    ptype = research_data["product_type"]
    kws = research_data["keywords"]
    long_tail = kws.get("long_tail", [])
    zero_search = kws.get("zero_search", [])
    articles = research_data.get("articles", [])
    m_names = [m["title"] for m in matching_products]

    if mode is None:
        mode = _pick_article_mode(ptype)

    if original_handle_hint:
        words = original_handle_hint.split("-")
        title_hint = " ".join(w.capitalize() for w in words if w)
    else:
        # Resolve dynamic placeholders in title pattern
        season = random.choice(_SEASONS)
        season2 = random.choice([s for s in _SEASONS if s != season])
        occasion = random.choice(_OCCASIONS)
        num = random.choice(_NUMS)
        title_hint = (
            mode["title_pattern"]
            .replace("{ptype}", ptype)
            .replace("{main_product}", main_product["title"])
            .replace("{season}", season)
            .replace("{season1}", season)
            .replace("{season2}", season2)
            .replace("{occasion}", occasion)
            .replace("{num}", num)
            .replace("{year}", str(YEAR))
        )

    # Research context from trending articles
    research_context = ""
    if articles:
        research_context = "TRENDING ARTICLE REFERENCES (Who What Wear, Refinery29, Harper's Bazaar, Elle — last 48h):\n"
        for idx, art in enumerate(articles[:4]):
            title = art.get("title", "")
            summary = art.get("summary", "")
            snippet = (art.get("full_content") or "")[:2500]
            src = art.get("source", "")
            research_context += f"Ref #{idx+1} [{src}]:\n  Title: {title}\n  Summary: {summary}\n  Snippet: {snippet}\n\n"

    prompt = f"""You are {random.choice(PEN_NAMES)}, an expert fashion editor writing for {BRAND_NAME} — a premium women's clothing boutique based in the USA.

Your mission today: Write a **100% original, highly engaging** blog article in the style of Who What Wear & Refinery29, adapted for {BRAND_NAME}'s audience.

────────── LEARNING & SYNTHESIZING FROM SOURCES ──────────
You MUST review the "TRENDING ARTICLE REFERENCES" below. Do NOT copy their text or commit plagiarism. Instead:
- Analyze their structure, key points, trending facts, fashion terminology, and hooks.
- Synthesize this research to create a brand-new, unique perspective or advice angle.
- Ensure your article is richer, more detailed, and offers higher value than the sources.

────────── ARTICLE MODE ──────────
Mode: {mode['id']}
Angle: {mode['angle']}
Title Suggestion: {title_hint}
Content Brief: {mode['description']}
Required Structure: {mode['structure']}
Writing Tone: {mode['tone']}
Title Examples (for inspiration, do NOT copy): {'; '.join(mode.get('title_examples', []))}

────────── PRODUCT CONTEXT ──────────
Hero Product: {main_product['title']} (Type: {ptype})
Complementary Products to naturally mention: {', '.join(m_names)}
Store URL base: {STORE_URL}

────────── SEO KEYWORDS ──────────
Weave these naturally — never stuff them:
Long-tail: {', '.join(long_tail[:5])}
Zero-Search-Volume: {', '.join(zero_search[:5])}

────────── TREND RESEARCH ──────────
{research_context if research_context else 'No external trend references available — use your expert fashion knowledge for {MONTH}.'}

────────── MANDATORY EDITORIAL & VISUAL STYLING RULES ──────────
1. Target audience: Women in the USA, ages 25-55. Speak directly to her.
2. Open with a STRONG hook — surprising stat, relatable pain point, bold statement, or intriguing question. NO generic 'In today's world...' openers.
3. Include a Table of Contents (HTML anchor links) after the intro. The Table of Contents MUST be formatted as a structured bulleted list (using `<ul>` and `<li>`) or numbered list (using `<ol>` and `<li>`), wrapped in a styled container (e.g. `<div style="background:#f9f9f9; border:1px solid #eaeaea; padding:15px; border-radius:8px; margin:20px 0;"><p style="font-weight:bold; margin-top:0;">Table of Contents</p><ul style="margin:0; padding-left:20px; line-height:1.6;">...</ul></div>`). Never output it as a single paragraph or plain text.
4. Use H2 and H3 headers. Every section must provide REAL, actionable value.
5. Include at least one numbered list OR bullet-point checklist with 5+ items.
6. Mention the hero product AND at least one complementary product NATURALLY within the article body (not just in promotional sections).
7. End with an FAQ section containing 5-6 specific, realistic questions women ask about this topic, with detailed answers.
8. DO NOT be generic. Every tip must be specific. "Pair with white sneakers" is boring. "Try the {m_names[0] if m_names else 'MeeeShop top'} in cream for a tonal, editorial moment" is great.
9. Article length: Aim for 900-1200 words of body content (excluding product cards added separately).
10. PREMIUM HTML STYLING: Make the article visually outstanding and premium. Use these HTML elements:
    - **Styled Blockquotes**: Use `<blockquote>` with elegant borders and styling (e.g. `<blockquote style="border-left: 4px solid #111; padding-left: 20px; font-style: italic; margin: 30px 0; color: #555;">...</blockquote>`).
    - **Key Takeaway Cards / Callout Boxes**: Insert styled `div`s for editor's tips or warnings (e.g. `<div style="background: #faf5f5; border-left: 4px solid #d9534f; padding: 15px 20px; margin: 20px 0; border-radius: 4px;"><strong>Editor's Note:</strong> ...</div>`).
    - **Comparison / Styling Recipe Cards**: Create side-by-side recipe or match guides with inline style (using border-radius, clean fonts, subtle colors).
11. LIST FORMATTING (CRITICAL): NEVER write numbered items, tips, or Q&A as a single paragraph of text. ALWAYS use proper HTML list elements:
    - For numbered steps/tips/ideas, use `<ol><li>…</li></ol>`.
12. OUTFIT / ITEM COUNT ALIGNMENT (CRITICAL): The title/handle specifies {extract_handle_count(original_handle_hint or title_hint)} outfits/items/rules. You MUST structure the body with exactly {extract_handle_count(original_handle_hint or title_hint)} distinct outfit formulas/sections (e.g. 'Outfit 1', 'Outfit 2', ... 'Outfit {extract_handle_count(original_handle_hint or title_hint)}') to match the handle and title count, featuring the hero product and all complementary products provided ({', '.join(m_names)}).
    - For unordered items/checklists, use `<ul><li>…</li></ul>`.
    - For the FAQ section, wrap each Q&A in its own `<div>` block. Use a `<strong>` or `<h3>` for the question and a `<p>` for the answer, NEVER inline them like "Q: ... A: ..." in one paragraph.
    - Example of WRONG format: "Here are tips: 1. Do X 2. Do Y 3. Do Z"
    - Example of CORRECT format: `<ol><li>Do X</li><li>Do Y</li><li>Do Z</li></ol>`

At the very end, append this block:
<seometa>
SEO_TITLE: [50-60 chars, include main keyword near start, current year or 'for Women']
META_DESC: [140-155 chars, benefit-first, end with CTA]
IMG_ALT: [10-15 words describing the featured image styling scene]
SUGGESTED_HANDLE: [url-slug-format]
SUGGESTED_TAGS: [comma-separated list of 6-8 relevant tags]
ARTICLE_MODE: {mode['id']}
</seometa>

Output ONLY clean HTML body content then the <seometa> block. No markdown fences. Start with the first HTML tag.
"""
    if original_handle_hint:
        prompt += f"""

────────── MANDATORY HANDLE & TITLE ENFORCEMENT ──────────
1. You MUST write this article specifically about: "{title_hint}".
2. You MUST use the exact title: "{title_hint}" as the main heading and the article title.
3. In the <seometa> section, you MUST output:
   SEO_TITLE: {title_hint}
   SUGGESTED_HANDLE: {original_handle_hint}
"""
    return prompt, mode

def _parse_seometa(raw: str) -> dict:
    meta = {"seo_title": "", "meta_desc": "", "img_alt": "", "suggested_handle": "", "suggested_tags": []}
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

def _slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[-\s]+", "-", text)
    return text.strip("-")

def generate_fallback_content(
    main_product: dict,
    matching_products: list,
    rdata: dict,
    mode: dict,
    original_handle_hint: str | None = None
) -> str:
    ptype = rdata.get("product_type", "Fashion Staples").strip()
    prod_title = main_product["title"]
    
    if original_handle_hint:
        suggested_handle = original_handle_hint
        words = original_handle_hint.split("-")
        title = " ".join(w.capitalize() for w in words if w)
    else:
        season = random.choice(_SEASONS)
        season2 = random.choice([s for s in _SEASONS if s != season])
        occasion = random.choice(_OCCASIONS)
        num = random.choice(_NUMS)
        title = (
            mode["title_pattern"]
            .replace("{ptype}", ptype)
            .replace("{main_product}", prod_title)
            .replace("{season}", season)
            .replace("{season1}", season)
            .replace("{season2}", season2)
            .replace("{occasion}", occasion)
            .replace("{num}", num)
            .replace("{year}", str(YEAR))
        )
        suggested_handle = _slugify(title)
        
    articles = rdata.get("articles", [])
    ref_summaries = []
    if articles:
        for art in articles[:3]:
            art_title = art.get("title", "Fashion Trends")
            summary = art.get("summary", "") or art.get("full_content", "")
            if summary:
                summary = re.sub(r"<[^>]+>", "", summary)
                summary = summary[:200] + "..." if len(summary) > 200 else summary
            else:
                summary = "Exploring modern trends and versatile styles for the current season."
            ref_summaries.append((art_title, summary))
            
    is_care = mode.get("id") in ("fabric_care_guide", "stain_odour_rescue")
    
    if is_care:
        intro_p = f"Maintaining the premium look and feel of your wardrobe staples is essential. The {prod_title} is a key foundation piece, and knowing how to properly care for and wash it ensures it remains in pristine condition for years to come. Whether you're dealing with standard laundry cycles or trying to remove tough stains and odours, this guide has you covered."
        
        toc = f"""
<div style="background:#f9f9f9; border:1px solid #eaeaea; padding:15px; border-radius:8px; margin:20px 0;">
  <p style="font-weight:bold; margin-top:0;">Table of Contents</p>
  <ul style="margin:0; padding-left:20px; line-height:1.6;">
    <li><a href="#trends" style="color:#111; text-decoration:underline;">Latest Care & Maintenance Insights</a></li>
    <li><a href="#hero" style="color:#111; text-decoration:underline;">Why Proper Care Matters for the {prod_title}</a></li>
    <li><a href="#guidelines" style="color:#111; text-decoration:underline;">Step-by-Step Washing Guidelines</a></li>
    <li><a href="#care" style="color:#111; text-decoration:underline;">Essential Longevity & Storage Secrets</a></li>
    <li><a href="#faq" style="color:#111; text-decoration:underline;">Frequently Asked Questions</a></li>
  </ul>
</div>
"""
        trends_content = ""
        if ref_summaries:
            trends_content += "<p>To give you the most relevant care advice, we analyzed the latest fabric care recommendations and expert laundry reports. Here are the key insights we've observed:</p>"
            trends_content += '<ul style="line-height:1.6; padding-left:20px;">'
            for art_title, summary in ref_summaries:
                trends_content += f'  <li style="margin-bottom:12px;"><strong>{art_title}</strong>: {summary}</li>'
            trends_content += "</ul>"
        else:
            trends_content += f"<p>Experts agree that the secret to garment longevity lies in minimizing washing frequency, utilizing low water temperatures, and avoiding harsh chemical detergents. This is particularly true for premium {ptype} items, which benefit from gentle handling.</p>"

        trends_html = f"""
<h2 id="trends" style="font-size:20px; margin-top:30px; border-bottom:1px solid #eee; padding-bottom:8px;">Latest Care & Maintenance Insights</h2>
{trends_content}
<blockquote style="border-left: 4px solid #111; padding-left: 20px; font-style: italic; margin: 30px 0; color: #555;">
  "True garment care is not just about cleaning; it's about preserving the fibers and shape so your favorites last a lifetime."
</blockquote>
"""
        hero_html = f"""
<h2 id="hero" style="font-size:20px; margin-top:30px; border-bottom:1px solid #eee; padding-bottom:8px;">Why Proper Care Matters for the {prod_title}</h2>
<p>The {prod_title} features high-quality fabric designed for comfort and durability. However, improper washing can lead to shrinkage, shape distortion, or fading. Following correct care guidelines helps maintain the premium texture and fit.</p>
<div style="background: #faf5f5; border-left: 4px solid #d9534f; padding: 15px 20px; margin: 20px 0; border-radius: 4px;">
  <strong>Care Tip:</strong> Always turn your garments inside out before washing to protect the exterior fibers from agitation and friction.
</div>
"""
        pairings_html = f"""
<h2 id="guidelines" style="font-size:20px; margin-top:30px; border-bottom:1px solid #eee; padding-bottom:8px;">Step-by-Step Washing Guidelines</h2>
<p>Ensure your items get the gentlest clean possible by following this simple step-by-step process:</p>
<ol style="line-height:1.6; margin-bottom:20px;">
  <li><strong>Prep the Garment:</strong> Empty pockets, close zippers, and turn the piece inside out.</li>
  <li><strong>Select the Right Cycle:</strong> Choose a delicate or gentle cycle on your washing machine.</li>
  <li><strong>Use Cold Water:</strong> Hot water can weaken fibers and cause shrinking. Keep it cool.</li>
  <li><strong>Add Gentle Detergent:</strong> Avoid bleach or harsh laundry additives.</li>
</ol>
"""
        care_html = f"""
<h2 id="care" style="font-size:20px; margin-top:30px; border-bottom:1px solid #eee; padding-bottom:8px;">Essential Longevity & Storage Secrets</h2>
<p>Once clean, how you dry and store your clothing plays a major role in keeping it looking new:</p>
<ul style="line-height:1.6; padding-left:20px; margin-bottom:20px;">
  <li><strong>Air Dry:</strong> Skip the dryer to avoid heat damage and piling. Lay flat or hang to air dry.</li>
  <li><strong>Steam Instead of Ironing:</strong> Use a fabric steamer to gently release creases without crushing fibers.</li>
  <li><strong>Proper Storage:</strong> Fold knits to prevent stretching, and hang structured items on padded hangers.</li>
</ul>
"""
        faq_html = f"""
<h2 id="faq" style="font-size:20px; margin-top:30px; border-bottom:1px solid #eee; padding-bottom:8px;">Frequently Asked Questions</h2>
<div style="margin-bottom: 15px;">
  <strong>Q: How often should you wash this product?</strong>
  <p style="margin-top:5px; margin-bottom:15px;">A: We recommend washing only after 3-5 wears unless stained, to preserve fabric integrity.</p>
</div>
<div style="margin-bottom: 15px;">
  <strong>Q: Can I tumble dry this item?</strong>
  <p style="margin-top:5px; margin-bottom:15px;">A: Air drying is strongly recommended. Tumble drying on high heat can shrink or degrade the fabric.</p>
</div>
<div style="margin-bottom: 15px;">
  <strong>Q: What is the best way to treat a stain?</strong>
  <p style="margin-top:5px; margin-bottom:15px;">A: Spot clean immediately using cold water and mild soap. Blot gently—do not rub.</p>
</div>
"""
    else:
        intro_p = f"When it comes to styling the perfect wardrobe, finding versatile pieces that balance comfort, durability, and high fashion is key. The {prod_title} has taken the fashion scene by storm, offering a flawless fit that transitions effortlessly from day to night. Whether you're dressing for a casual weekend outing, a busy day at the office, or a special occasion, understanding how to maximize this staple is essential for any modern closet."
        
        toc = f"""
<div style="background:#f9f9f9; border:1px solid #eaeaea; padding:15px; border-radius:8px; margin:20px 0;">
  <p style="font-weight:bold; margin-top:0;">Table of Contents</p>
  <ul style="margin:0; padding-left:20px; line-height:1.6;">
    <li><a href="#trends" style="color:#111; text-decoration:underline;">Latest Fashion Trends & Insights</a></li>
    <li><a href="#hero" style="color:#111; text-decoration:underline;">The Hero Piece: Styling the {prod_title}</a></li>
    <li><a href="#pairings" style="color:#111; text-decoration:underline;">Styled Lookbook: Complete Outfit Recipes</a></li>
    <li><a href="#care" style="color:#111; text-decoration:underline;">Essential Style & Care Secrets</a></li>
    <li><a href="#faq" style="color:#111; text-decoration:underline;">Frequently Asked Questions</a></li>
  </ul>
</div>
"""
        trends_content = ""
        if ref_summaries:
            trends_content += "<p>To give you the most relevant style advice, we analyzed the latest fashion discourse and expert reports from across the industry. Here are the key trend movements we've observed:</p>"
            trends_content += '<ul style="line-height:1.6; padding-left:20px;">'
            for art_title, summary in ref_summaries:
                trends_content += f'  <li style="margin-bottom:12px;"><strong>{art_title}</strong>: {summary}</li>'
            trends_content += "</ul>"
        else:
            trends_content += f"<p>This season is all about effortless styling, smart layering, and investing in high-quality basics. Fashion editors agree that the secret to a premium look lies in how you style your core {ptype} items, prioritizing fabric texture, proportion play, and complementary color palettes.</p>"
            
        trends_html = f"""
<h2 id="trends" style="font-size:20px; margin-top:30px; border-bottom:1px solid #eee; padding-bottom:8px;">Latest Fashion Trends & Insights</h2>
{trends_content}
<blockquote style="border-left: 4px solid #111; padding-left: 20px; font-style: italic; margin: 30px 0; color: #555;">
  "True style is not about buying a new wardrobe every season; it's about knowing how to make your core pieces speak a new language."
</blockquote>
"""
        hero_html = f"""
<h2 id="hero" style="font-size:20px; margin-top:30px; border-bottom:1px solid #eee; padding-bottom:8px;">The Hero Piece: Styling the {prod_title}</h2>
<p>The {prod_title} is designed to be the anchor of your wardrobe. Made with premium materials and featuring a thoughtful silhouette, it provides the perfect foundation for multiple looks.</p>
<div style="background: #faf5f5; border-left: 4px solid #d9534f; padding: 15px 20px; margin: 20px 0; border-radius: 4px;">
  <strong>Stylist Tip:</strong> When styling the {prod_title}, pay close attention to proportions. If you are wearing a relaxed-fit silhouette, pair it with a more tailored top to keep your look balanced and polished.
</div>
"""
        pairings_html = f"""
<h2 id="pairings" style="font-size:20px; margin-top:30px; border-bottom:1px solid #eee; padding-bottom:8px;">Styled Lookbook: Complete Outfit Recipes</h2>
<p>To help you integrate this piece into your daily rotation, our editors have put together {len(matching_products) + 1} gorgeous outfit recipes using MeeeShop favorites:</p>
"""
        for idx, p in enumerate(matching_products):
            pair_title = p["title"]
            pair_handle = p.get("handle", "")
            pair_url = f"{STORE_URL}/products/{pair_handle}"
            pairings_html += f"""
<div style="border: 1px solid #eaeaea; border-radius: 8px; padding: 15px; margin-bottom: 20px; background:#fff;">
  <h3 style="margin-top:0; font-size:16px; color:#111;">Recipe {idx+1}: The {pair_title} Pairing</h3>
  <p>Create a cohesive, high-end look by pairing the <strong>{prod_title}</strong> with the <a href="{pair_url}" style="color:#111; text-decoration:underline;">{pair_title}</a>. This combination creates a beautiful balance of textures and colors, perfect for transitional weather or a smart-casual dress code.</p>
</div>
"""
        care_html = f"""
<h2 id="care" style="font-size:20px; margin-top:30px; border-bottom:1px solid #eee; padding-bottom:8px;">Essential Style & Care Secrets</h2>
<p>Maintaining the premium look and feel of your clothing requires the right habits. Follow this checklist to ensure your wardrobe staples last for years:</p>
<ul style="line-height:1.6; padding-left:20px; margin-bottom:20px;">
  <li><strong>Wash Less:</strong> Only wash when necessary to preserve fabric integrity and prevent fading.</li>
  <li><strong>Use Cold Water:</strong> Always wash in cold water with a gentle detergent to avoid shrinkage.</li>
  <li><strong>Air Dry:</strong> Whenever possible, skip the dryer and lay your items flat to dry. This prevents piling and structural damage.</li>
  <li><strong>Steam, Don't Iron:</strong> Use a steamer to remove wrinkles gently without exposing delicate fibers to direct high heat.</li>
  <li><strong>Store Properly:</strong> Fold heavy knits and sweaters to prevent stretching, and hang structured items on padded hangers.</li>
</ul>
"""
        faq_html = f"""
<h2 id="faq" style="font-size:20px; margin-top:30px; border-bottom:1px solid #eee; padding-bottom:8px;">Frequently Asked Questions</h2>
<div style="margin-bottom: 15px;">
  <strong>Q: How does the {prod_title} fit?</strong>
  <p style="margin-top:5px; margin-bottom:15px;">A: It runs true to size with a comfortable, flattering stretch. If you prefer a tighter fit, we recommend sizing down.</p>
</div>
<div style="margin-bottom: 15px;">
  <strong>Q: What is the best way to wash this item?</strong>
  <p style="margin-top:5px; margin-bottom:15px;">A: We recommend machine washing on a cold, gentle cycle inside out, and laying flat to air dry.</p>
</div>
<div style="margin-bottom: 15px;">
  <strong>Q: Can this product be styled for formal events?</strong>
  <p style="margin-top:5px; margin-bottom:15px;">A: Absolutely! Pair it with a tailored blazer and premium heels to instantly elevate it for professional or evening occasions.</p>
</div>
<div style="margin-bottom: 15px;">
  <strong>Q: What fabrics are used in this product?</strong>
  <p style="margin-top:5px; margin-bottom:15px;">A: Crafted from a premium blend designed for breathability, softness, and long-lasting shape retention.</p>
</div>
"""
    
    long_tail = rdata.get("keywords", {}).get("long_tail", [])
    zero_search = rdata.get("keywords", {}).get("zero_search", [])
    suggested_tags = ["style", "fashion", ptype.lower()]
    if long_tail:
        suggested_tags.extend([t.lower() for t in long_tail[:3]])
    
    html_body = f"""<h1>{title}</h1>
<p>{intro_p}</p>
{toc}
{trends_html}
{hero_html}
{pairings_html}
{care_html}
{faq_html}"""
    
    meta_desc = f"Get the ultimate style guide for styling the {prod_title}. Discover trending pairings, care tips, and editor-approved fashion recipes."
    if is_care:
        meta_desc = f"Learn how to wash and care for the {prod_title} to preserve its premium quality. Step-by-step washing, cleaning, and storage secrets."
    meta_desc = meta_desc[:150]

    
    long_tail = rdata.get("keywords", {}).get("long_tail", [])
    zero_search = rdata.get("keywords", {}).get("zero_search", [])
    suggested_tags = ["style", "fashion", ptype.lower()]
    if long_tail:
        suggested_tags.extend([t.lower() for t in long_tail[:3]])
    
    html_body = f"""<h1>{title}</h1>
<p>{intro_p}</p>
{toc}
{trends_html}
{hero_html}
{pairings_html}
{care_html}
{faq_html}"""
    
    meta_desc = f"Get the ultimate style guide for styling the {prod_title}. Discover trending pairings, care tips, and editor-approved fashion recipes."
    meta_desc = meta_desc[:150]
    
    seometa = f"""
<seometa>
SEO_TITLE: {title[:55]}
META_DESC: {meta_desc}
IMG_ALT: A premium fashion collage featuring the {prod_title} and matching styling pieces from MeeeShop.
SUGGESTED_HANDLE: {suggested_handle}
SUGGESTED_TAGS: {", ".join(list(dict.fromkeys(suggested_tags))[:7])}
ARTICLE_MODE: {mode['id']}
</seometa>
"""
    return html_body + seometa

def _clean_html(raw: str) -> str:
    raw = raw.strip()
    raw = re.sub(r"^```html?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw)
    raw = re.sub(r"<seometa>.*?</seometa>", "", raw, flags=re.DOTALL | re.IGNORECASE)
    return raw.strip()

# ── Unified Content Generation Engine ──────────────────────────────────────────
def generate_single_article_content(
    main_product: dict,
    all_products_with_images: list,
    link_map: LinkMap,
    type_map: dict,
    research_cache: dict,
    force_format: str | None = None,
    dry_run: bool = False,
    original_handle_hint: str | None = None
) -> dict | None:
    """
    Generates all content and assets for a single blog article.
    This is the core content generation engine, designed to be called by other scripts.
    """
    print(f"  Generating content for product: '{main_product['title']}'")

    # 1. Get research data
    ptype = main_product.get("product_type") or "Uncategorized"
    ptype = ptype.strip()
    
    if ptype not in research_cache:
        print(f"  [Research] Fetching Flipboard research for product type: '{ptype}'...")
        sample_prods = type_map.get(ptype, [main_product])
        r = research_flipboard_per_category({ptype: sample_prods})
        research_cache[ptype] = r.get(ptype, {
            "product_type": ptype,
            "sample_products": [{"id": main_product["id"], "title": main_product["title"], "handle": main_product.get("handle", "")}],
            "articles": [],
            "keywords": {"long_tail": [], "zero_search": []}
        })
        
    rdata = research_cache[ptype]

    # 2. Select styling matches matching outfit count in handle/title
    target_count_text = original_handle_hint or ptype or ""
    outfit_count = extract_handle_count(target_count_text)
    num_matches = max(2, outfit_count - 1)
    matching_products = select_styling_matches(main_product, all_products_with_images, num_matches=num_matches, topic_context=target_count_text)
    print(f"  Styling Pairings ({len(matching_products)} products for {outfit_count} outfits/items): {[p['title'] for p in matching_products]}")

    # 3. Build AI prompt and generate content
    mode = None
    if force_format:
        for m in ARTICLE_MODES:
            if m["id"] == force_format:
                mode = m
                break
                
    prompt, chosen_mode = _build_article_prompt(main_product, rdata, matching_products, mode=mode, original_handle_hint=original_handle_hint)
    
    print(f"  Article Mode: {chosen_mode['id']}")
    print("  Generating new content with AI...")
    prompt = prompt.replace("MeeeShop", BRAND_NAME)
    raw_ai_response = ai_client.generate(prompt, max_tokens=3000, temperature=0.85)

    if not raw_ai_response:
        print("  [ERROR] AI content generation failed. Running fallback content generation...")
        raw_ai_response = generate_fallback_content(
            main_product=main_product,
            matching_products=matching_products,
            rdata=rdata,
            mode=chosen_mode,
            original_handle_hint=original_handle_hint
        )

    html_body = _clean_html(raw_ai_response)
    seometa = _parse_seometa(raw_ai_response)
    
    # 4. Fallbacks and assembly
    if original_handle_hint:
        suggested_handle = original_handle_hint
        words = original_handle_hint.split("-")
        new_title = " ".join(w.capitalize() for w in words if w)
    else:
        suggested_handle = seometa.get("suggested_handle") or f"style-guide-{main_product['handle']}"
        new_title = seometa.get("seo_title") or f"How to Wear & Style {main_product['title']}"
    meta_desc = seometa.get("meta_desc") or f"Expert styling guide and care tips for {main_product['title']}."
    img_alt = seometa.get("img_alt") or f"{main_product['title']} styling collage"
    new_tags = seometa.get("suggested_tags") or ["style", "fashion", ptype.lower()]

    # 5. Inject product cards and related products section
    card_html = make_product_card(main_product)
    toc_match = re.search(r"</ul>", html_body, re.IGNORECASE)
    if toc_match:
        pos = toc_match.end()
        html_body = html_body[:pos] + "\n" + card_html + html_body[pos:]
    else:
        p_match = re.search(r"</p>", html_body, re.IGNORECASE)
        if p_match:
            pos = p_match.end()
            html_body = html_body[:pos] + "\n" + card_html + html_body[pos:]
            
    html_body += "\n" + make_related_products_section([main_product] + matching_products)

    # 6. Inject natural internal links
    html_body = inject_internal_links(html_body, link_map, main_product["title"])

    # 7. Generate and upload featured image collage
    img_url = None
    image_bytes_list = []
    for p in [main_product] + matching_products:
        if p.get("images"):
            try:
                r = requests.get(p["images"][0]["src"], timeout=10)
                if r.status_code == 200:
                    image_bytes_list.append(r.content)
            except Exception as e:
                print(f"      [!] Error fetching product image: {e}")
                
    if image_bytes_list:
        try:
            collage_bytes = generate_collage(image_bytes_list)
            temp_path = Path("collage_temp.jpg")
            with open(temp_path, "wb") as f:
                f.write(collage_bytes)
            
            if not dry_run:
                ts = int(time.time())
                filename = f"content_collage_{main_product['id']}_{ts}.jpg"
                img_url = upload_image_to_shopify(temp_path, filename)
                try:
                    temp_path.unlink()
                except Exception:
                    pass
            else:
                img_url = f"file:///{temp_path.absolute().as_posix()}"
        except Exception as e:
            print(f"      [!] Collage build failed: {e}")
            
    if not img_url:
        print("      [!] Collage failed, fallback to main product image.")
        img_url = main_product["images"][0]["src"] if main_product.get("images") else None

    return {
        "html_body": html_body,
        "seo_title": new_title,
        "meta_desc": meta_desc,
        "suggested_handle": suggested_handle,
        "tags": new_tags,
        "img_url": img_url,
        "img_alt": img_alt,
        "chosen_mode": chosen_mode["id"],
        "author": random.choice(PEN_NAMES),
        "ptype": ptype,
    }

# ── Used Product Rotation Tracking ───────────────────────────────────────────
def load_used_products_history() -> dict:
    history_path = REPO_ROOT / "used_products_history.json"
    if not history_path.exists():
        return {}
    try:
        with open(history_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception as e:
        print(f"  [!] Warning loading used_products_history.json: {e}")
    return {}

def save_used_products_history(history: dict):
    history_path = REPO_ROOT / "used_products_history.json"
    try:
        with open(history_path, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)
    except Exception as e:
        print(f"  [!] Warning saving used_products_history.json: {e}")

def clean_old_history(history: dict, days: int = 7) -> dict:
    cleaned = {}
    cutoff = datetime.now() - timedelta(days=days)
    for handle, date_str in history.items():
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            if dt >= cutoff:
                cleaned[handle] = date_str
        except Exception:
            cleaned[handle] = date_str
    return cleaned

# ── Phase 4: Generate + Publish ───────────────────────────────────────────────
def generate_weekly_blogs(research: dict, all_products: list, link_map: LinkMap, count: int = 1, dry_run: bool = False, publish: bool = True):
    print(f"\n━━ PHASE 4: Generating {count} Weekly Trend Blog Article(s) ━━")
    
    product_history = load_used_products_history()
    product_history = clean_old_history(product_history, days=7)
    
    type_pool = list(research.keys())
    random.shuffle(type_pool)
    
    results = []
    all_products_with_images = [p for p in all_products if p.get("images")]
    
    for i in range(count):
        ptype = type_pool[i % len(type_pool)]
        
        prods_in_type = [p for p in all_products_with_images if p.get("product_type") == ptype]
        if not prods_in_type:
            prods_in_type = all_products_with_images
        if not prods_in_type:
            print(f"  [Skip] No products found with images.")
            continue
            
        unused_prods = [p for p in prods_in_type if p.get("handle") not in product_history]
        if unused_prods:
            main_product = random.choice(unused_prods)
            print(f"  [Rotation] Selected unused product: {main_product['title']}")
        else:
            print(f"  [Rotation] All products in category '{ptype}' have been featured recently. Resetting rotation.")
            main_product = random.choice(prods_in_type)

        if not dry_run:
            product_history[main_product["handle"]] = datetime.now().strftime("%Y-%m-%d")
            save_used_products_history(product_history)

        print(f"\n  Article {i+1} details:")
        print(f"    Product Type: {ptype}")
        print(f"    Main Product: {main_product['title']}")

        content_assets = generate_single_article_content(
            main_product=main_product,
            all_products_with_images=all_products_with_images,
            link_map=link_map,
            type_map=research,
            research_cache=research,
            dry_run=dry_run,
        )

        if not content_assets:
            print("    [!] Content generation failed.")
            continue
            
        html_body = content_assets["html_body"]
        seo_title = content_assets["seo_title"]
        meta_desc = content_assets["meta_desc"]
        suggested_handle = content_assets["suggested_handle"]
        tags = content_assets["tags"]
        img_url = content_assets["img_url"]
        img_alt = content_assets["img_alt"]
        author = content_assets["author"]
        chosen_mode_id = content_assets["chosen_mode"]
        
        BLOG_ROUTING = [
            (["jean", "denim"],                   None,                           "jeans-style-guide"),
            (["dress"],                            None,                           "dresses-style-guide"),
            (["skirt"],                            None,                           "womens-skirts-style-guide"),
            (["pant", "trouser", "legging"],       None,                           "womens-pants-style-guide"),
            (["top", "blouse", "shirt", "tee", "t-shirt", "tunic", "tank"], None, "womens-shirts-tops-style-guide"),
            (["cardigan", "sweater", "sweatshirt", "knit", "pullover"], None, "cardigans-sweaters-style-guide"),
            (["coat", "jacket", "blazer", "vest", "outerwear"], None, "coats-jackets-style-guide"),
            (["plus", "curvy"],                    ["plus_size_curvy_guide"],       "plus-size-curvy-clothing"),
            (["vegan", "eco", "sustainable"],      None,                           "everything-anything-about-vegan"),
            (["short", "romper", "jumpsuit", "set", "loungewear", "handbag", "bag", "purse", "accessory", "bottom"], None, "womens-clothing"),
        ]
        OUR_TIPS_HANDLE   = "our-tips"
        ANNOUNCEMENT_HANDLE = "announcements"

        blogs = fetch_all_blogs()
        blog_by_handle_lower = {b["handle"].lower(): b for b in blogs}

        ptype_l = ptype.lower()
        chosen_blog = None

        for kw_list, mode_ids, target_handle in BLOG_ROUTING:
            kw_match  = any(kw in ptype_l for kw in kw_list)
            mode_match = (mode_ids is None) or (chosen_mode_id in mode_ids)
            if kw_match and mode_match:
                chosen_blog = blog_by_handle_lower.get(target_handle.lower())
                if chosen_blog:
                    break

        if not chosen_blog:
            chosen_blog = blog_by_handle_lower.get(OUR_TIPS_HANDLE)
        if not chosen_blog:
            chosen_blog = next((b for b in blogs if b["handle"].lower() != ANNOUNCEMENT_HANDLE), blogs[0])
        
        blog = chosen_blog
        print(f"    Routing to blog: '{blog['title']}' (handle: {blog['handle']})")
                
        result = {
            "title": seo_title,
            "handle": suggested_handle,
            "html_body": html_body,
            "seo_title": seo_title,
            "meta_desc": meta_desc,
            "img_alt": img_alt,
            "img_url": img_url,
            "tags": tags,
            "blog_id": blog["id"],
            "blog_title": blog["title"]
        }
        results.append(result)
        
        if dry_run:
            preview_path = LOG_DIR / f"weekly_preview_{suggested_handle}_{int(time.time())}.html"
            with open(preview_path, "w", encoding="utf-8") as f:
                f.write(f"<!DOCTYPE html><html><head><title>{seo_title}</title></head><body>\n")
                f.write(f"<!-- SEO Title: {seo_title} -->\n<!-- Meta: {meta_desc} -->\n")
                if img_url:
                    f.write(f'<img src="{img_url}" alt="{img_alt}" style="max-width:600px; display:block; margin:20px 0;" />\n')
                f.write(html_body)
                f.write("\n</body></html>")
            print(f"    [Dry Run] Saved HTML preview -> {preview_path.absolute()}")
        else:
            published_live = publish
            article_payload = {
                "article": {
                    "title": seo_title,
                    "author": author,
                    "body_html": html_body,
                    "summary_html": meta_desc,
                    "tags": ", ".join(tags),
                    "published": published_live,
                    "handle": suggested_handle,
                    "metafields": [
                        {"namespace": "seo", "key": "title", "value": seo_title, "type": "single_line_text_field"},
                        {"namespace": "seo", "key": "description", "value": meta_desc, "type": "single_line_text_field"}
                    ]
                }
            }
            if img_url:
                article_payload["article"]["image"] = {
                    "src": img_url,
                    "alt": img_alt
                }
                
            print(f"    Saving to Shopify blog '{blog['title']}'...")
            r = _req("post", f"{BASE}/blogs/{blog['id']}/articles.json", json=article_payload)
            if r.status_code in (200, 201):
                art = r.json().get("article", {})
                print(f"    [Shopify] Success! Article ID: {art.get('id')} | Handle: {art.get('handle')}")
            else:
                print(f"    [!] Shopify Upload Failed: {r.status_code} - {r.text}")
                
    return results

def main():
    ap = argparse.ArgumentParser(description="MeeeShop Weekly Trend Blog Generator")
    ap.add_argument("--count", type=int, default=1, help="Number of articles to generate")
    ap.add_argument("--dry-run", action="store_true", help="Generate but do not publish to Shopify")
    ap.add_argument("--draft", action="store_true", help="Save article as draft (default: publish)")
    ap.add_argument("--publish", action="store_true", help="Publish immediately (default behavior)")
    args = ap.parse_args()
    
    print("="*60)
    print(" MeeeShop Weekly Trend Blog Generator")
    print(f" {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("="*60)
    
    store_info = fetch_store_product_types()
    type_map = store_info["types"]
    all_products = store_info["all_products"]
    
    available_types = list(type_map.keys())
    random.shuffle(available_types)
    target_types = available_types[:args.count]
    filtered_type_map = {ptype: type_map[ptype] for ptype in target_types if ptype in type_map}
    print(f"\n[Optimization] Selected {len(filtered_type_map)} target product type(s) for generation: {list(filtered_type_map.keys())}")
    
    research = research_flipboard_per_category(filtered_type_map)
    
    link_map = build_linker_map()
    
    generate_weekly_blogs(
        research=research,
        all_products=all_products,
        link_map=link_map,
        count=args.count,
        dry_run=args.dry_run,
        publish=not args.draft
    )
    
    print("\n✅ Execution Finished.")

if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
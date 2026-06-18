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
from PIL import Image

# ── Path Setup ────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT   = SCRIPT_DIR.parent
LOG_DIR     = REPO_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(REPO_ROOT))

import ai_client
from secrets_manager import inject_to_env, get_secret
from utils import download_article_content, extract_keywords, generate_collage
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
                wait = int(float(r.headers.get("Retry-After", 4)))
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

# ── Phase 2: Flipboard fetching with 48-hour cutoff ────────────────────────────
FLIPBOARD_RSS_BASE = "https://flipboard.com/topic/{topic}/feed.rss"
FLIPBOARD_SEARCH   = "https://flipboard.com/search.json"
CUTOFF_DAYS        = 2  # 48 hours

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
            "User-Agent": "Mozilla/5.0 (compatible; MeeeShop SEO bot/1.0)"
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
            headers={"User-Agent": "Mozilla/5.0 (compatible; MeeeShop SEO bot/1.0)"}
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
            for art in rss_articles:
                if art.get("link"):
                    art["full_content"] = download_article_content(art["link"])
            all_articles.extend(rss_articles)
            time.sleep(0.3)

        # Search queries specifically targeting Who What Wear and Refinery29 style
        queries = [
            f"Who What Wear {ptype_lower}",
            f"Refinery29 {ptype_lower}",
            f"women {ptype_lower} style trend"
        ]
        for q in queries:
            print(f"    Searching Flipboard for: '{q}'...")
            search_articles = _fetch_flipboard_search(q)
            for art in search_articles:
                if art.get("link"):
                    art["full_content"] = download_article_content(art["link"])
            all_articles.extend(search_articles)

        # Deduplicate
        seen = set()
        unique = []
        for a in all_articles:
            norm_title = re.sub(r"\W+", "", a["title"].lower())[:40]
            if norm_title not in seen:
                seen.add(norm_title)
                unique.append(a)

        # Extract keywords
        long_tail = []
        zero_search = []
        for a in unique:
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
            "articles": unique[:10],
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
def select_styling_matches(main_product: dict, pool: list, num_matches: int = 2) -> list[dict]:
    main_type = (main_product.get("product_type") or "").lower()
    main_id = main_product.get("id")
    is_top = any(x in main_type for x in ["top", "blouse", "shirt", "tee"])
    is_bottom = any(x in main_type for x in ["jean", "pant", "skirt", "legging", "short"])
    is_one_piece = any(x in main_type for x in ["dress", "jumpsuit", "romper"])
    
    complementary_pool = []
    for p in pool:
        if p.get("id") == main_id or not p.get("images"):
            continue
        ptype = (p.get("product_type") or "").lower()
        if is_top and any(x in ptype for x in ["jean", "pant", "skirt", "jacket", "coat", "cardigan"]):
            complementary_pool.append(p)
        elif is_bottom and any(x in ptype for x in ["top", "blouse", "shirt", "tee", "sweater", "jacket", "coat"]):
            complementary_pool.append(p)
        elif is_one_piece and any(x in ptype for x in ["jacket", "coat", "cardigan", "accessory", "bag"]):
            complementary_pool.append(p)
        else:
            complementary_pool.append(p)
            
    if len(complementary_pool) >= num_matches:
        return random.sample(complementary_pool, num_matches)
    
    fallback_pool = [p for p in pool if p.get("id") != main_id and p.get("images")]
    return random.sample(fallback_pool, min(num_matches, len(fallback_pool))) if fallback_pool else []

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
            files = {"file": (filename, f, "image/jpeg")}
            params = {p["name"]: p["value"] for p in target["parameters"]}
            upload_resp = requests.post(target["url"], data=params, files=files, timeout=30)
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

# ── AI Prompt Construction ───────────────────────────────────────────────────
def _build_article_prompt(main_product: dict, research_data: dict, matching_products: list) -> str:
    ptype = research_data["product_type"]
    kws = research_data["keywords"]
    long_tail = kws.get("long_tail", [])
    zero_search = kws.get("zero_search", [])
    articles = research_data.get("articles", [])

    m_names = [m["title"] for m in matching_products]
    
    # Format the research context from WhoWhatWear / Refinery29
    research_context = ""
    if articles:
        research_context += "TRENDING ARTICLE REFERENCE FROM WHO WHAT WEAR & REFINERY29:\n"
        for idx, art in enumerate(articles[:4]):
            title = art.get("title", "")
            summary = art.get("summary", "")
            content_snippet = art.get("full_content", "")[:600]
            research_context += f"Reference #{idx+1}:\nTitle: {title}\nSummary: {summary}\nContent Snippet: {content_snippet}\n\n"

    prompt = f"""
You are an expert fashion stylist and editor writing for MeeeShop, a premium clothing boutique catering to women in the USA.
Write a highly engaging, helpful, and 100% original blog post.

Featured Store Product: {main_product['title']} (Product Type: {ptype})
Complementary Products to Mention: {', '.join(m_names)}

Target Audience: USA women who want styling solutions, care guidance, and clothes longevity advice.
Topic/Theme: Help readers with practical solutions. Include tips such as cleaning stains, removing stinky odors, preventing piling, washing and maintaining fabrics.

SEO Keywords to weave in naturally:
Long-tail: {', '.join(long_tail[:5])}
Zero Search Volume: {', '.join(zero_search[:5])}

{research_context}

Editorial Guidelines & Style Analysis (Inspired by Who What Wear & Refinery29):
1. Title Style: Catchy, benefits-focused, or problem-solving (e.g. "How to Style {ptype}", "What to Wear with {ptype}", "How to Wash & Care for {ptype} Without Ruining It").
2. Content Style: Benefit-driven, authoritative but friendly boutique-owner or personal-stylist voice. Highly structured and readable.
3. Structure: 
   - A strong, benefit-driven intro paragraph that hooks the reader with a styling/care secret (no generic setups).
   - A clear "Table of Contents" at the top linking to the main H2 sections.
   - Deep H2 & H3 sections providing styling recipes and fabric care/maintenance (e.g., how to wash, remove stinky smells from denim, prevent piling, clean stains).
   - Bullet lists or numbered guides for actionable tips.
   - A helpful FAQs section with 5-6 common questions (answering footwear pairings, day-to-night transitions, sizing fit, fabric maintenance) and detailed answers.
4. Product Promotion: Weave the store products naturally into the text (e.g. "We recommend pairing it with the {m_names[0] if m_names else 'collection top'}" or "The {main_product['title']} is the perfect foundation...").
5. Ignore Google Discover constraints (no strict formatting hooks required, write in a warm, expert boutique-owner tone).

At the very end of your response, append a <seometa> block:
<seometa>
SEO_TITLE: [50-60 chars, keyword near start, year or 'for Women']
META_DESC: [140-155 chars, action-oriented description, ends with CTA]
IMG_ALT: [10-15 words, description of styling scene]
SUGGESTED_HANDLE: [slugified-title]
SUGGESTED_TAGS: [comma-separated tags]
</seometa>

Output ONLY clean HTML body content and the <seometa> block.
Do not use markdown code block fences (e.g., ```html). Start directly with HTML content.
"""
    return prompt

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

def _clean_html(raw: str) -> str:
    raw = raw.strip()
    raw = re.sub(r"^```html?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw)
    raw = re.sub(r"<seometa>.*?</seometa>", "", raw, flags=re.DOTALL | re.IGNORECASE)
    return raw.strip()

# ── Phase 4: Generate + Publish ───────────────────────────────────────────────
def generate_weekly_blogs(research: dict, all_products: list, link_map: LinkMap, count: int = 1, dry_run: bool = False, publish: bool = False):
    print(f"\n━━ PHASE 4: Generating {count} Weekly Trend Blog Article(s) ━━")
    
    type_pool = list(research.keys())
    random.shuffle(type_pool)
    
    results = []
    
    for i in range(count):
        ptype = type_pool[i % len(type_pool)]
        rdata = research[ptype]
        
        # Select main product
        prods_in_type = [p for p in all_products if p.get("product_type") == ptype and p.get("images")]
        if not prods_in_type:
            prods_in_type = [p for p in all_products if p.get("images")]
        if not prods_in_type:
            print(f"  [Skip] No products found with images.")
            continue
            
        main_product = random.choice(prods_in_type)
        matching_products = select_styling_matches(main_product, all_products, num_matches=2)
        
        print(f"\n  Article {i+1} details:")
        print(f"    Product Type: {ptype}")
        print(f"    Main Product: {main_product['title']}")
        print(f"    Styling Pairings: {[p['title'] for p in matching_products]}")
        
        # Build prompt
        prompt = _build_article_prompt(main_product, rdata, matching_products)
        print("    Querying AI generator...")
        raw_ai = ai_client.generate(prompt, max_tokens=2500, temperature=0.72)
        if not raw_ai:
            print("    [!] AI generation failed.")
            continue
            
        html_body = _clean_html(raw_ai)
        seometa = _parse_seometa(raw_ai)
        
        # Inject main product card
        card_html = make_product_card(main_product)
        # Place card after first paragraph or table of contents
        toc_match = re.search(r"</ul>", html_body, re.IGNORECASE)
        if toc_match:
            pos = toc_match.end()
            html_body = html_body[:pos] + "\n" + card_html + html_body[pos:]
        else:
            p_match = re.search(r"</p>", html_body, re.IGNORECASE)
            if p_match:
                pos = p_match.end()
                html_body = html_body[:pos] + "\n" + card_html + html_body[pos:]
                
        # Inject related products grid at the bottom
        html_body += "\n" + make_related_products_section([main_product] + matching_products)
        
        # Inject natural internal links
        html_body = inject_internal_links(html_body, link_map, main_product["title"])
        
        # Create featured collage image
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
                    filename = f"weekly_collage_{main_product['id']}_{ts}.jpg"
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

        # Format meta fallbacks
        suggested_handle = seometa.get("suggested_handle") or f"style-guide-{main_product['handle']}"
        seo_title = seometa.get("seo_title") or f"How to Wear & Style {main_product['title']}"
        meta_desc = seometa.get("meta_desc") or f"Expert styling guide and care tips for {main_product['title']}. Shop now at MeeeShop!"
        img_alt = seometa.get("img_alt") or f"{main_product['title']} styling collage"
        tags = seometa.get("suggested_tags") or ["style", "fashion", ptype.lower()]
        
        # Route to blog
        blogs = fetch_all_blogs()
        blog = blogs[0]
        # Route by type
        ptype_l = ptype.lower()
        for b in blogs:
            btitle = b["title"].lower()
            if ("jean" in ptype_l or "denim" in ptype_l) and "jean" in btitle:
                blog = b
                break
            elif "dress" in ptype_l and "dress" in btitle:
                blog = b
                break
                
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
            # Publish/Draft payload
            published_live = publish
            article_payload = {
                "article": {
                    "title": seo_title,
                    "author": random.choice(PEN_NAMES),
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
    ap.add_argument("--publish", action="store_true", help="Publish immediately (default: draft)")
    args = ap.parse_args()
    
    print("="*60)
    print(" MeeeShop Weekly Trend Blog Generator")
    print(f" {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("="*60)
    
    # Step 1: Discover product types
    store_info = fetch_store_product_types()
    type_map = store_info["types"]
    all_products = store_info["all_products"]
    
    # Step 2: Research Flipboard
    research = research_flipboard_per_category(type_map)
    
    # Step 3: Build link map for internal linking
    link_map = build_linker_map()
    
    # Step 4: Generate articles
    generate_weekly_blogs(
        research=research,
        all_products=all_products,
        link_map=link_map,
        count=args.count,
        dry_run=args.dry_run,
        publish=args.publish
    )
    
    print("\n✅ Execution Finished.")

if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()

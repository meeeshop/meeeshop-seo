#!/usr/bin/env python3
"""
generate_discover_blog.py — Dedicated Google Discover Blog Generation & Testing Engine
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Designed specifically for Google Discover feed qualification and testing:
  1. Seasonal & Timely Topic Engine: Generates current-season styling guides & trend debates.
  2. High-CTR Editorial Titles: Specific, curiosity-driven, and 100% compliant with Google Discover policies.
  3. Multi-Tier 1200px+ Lifestyle Imagery:
     - Tier 1: AI Photorealistic Editorial Lifestyle Generation (Imagen 3 / Flux / Pollinations)
     - Tier 2: Free Shopify Burst & Curated High-Res Lifestyle Fashion Stock
     - Tier 3: Store Media Files / Catalog Lifestyle Shoot Fallback (1200x675 landscape, zero cutouts)
  4. Native Structured Data: Generates FAQPage JSON-LD in article.metafields.json_ld_schema.faq
     rendered automatically by meeeshop-jsonld.liquid without theme code changes.
  5. E-E-A-T Stylist Attribution: Real stylist persona bylines linked to verified bio pages.
  6. Multi-Protocol Instant Ping: IndexNow ping and Pinterest-compatible tagging for fast syndication.
  7. Parallel Isolation: Runs completely independently from existing blog scripts.
"""

import os
import sys
import json
import time
import random
import requests
import io
import re
import argparse
from datetime import datetime
from PIL import Image, ImageOps
from io import BytesIO
from urllib.parse import quote_plus
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from cryptography.fernet import Fernet

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

MIN_COLLECTION_PRODUCTS = 20

# ── Category & Template Registry (11 Active Channels, Announcements strictly excluded) ──
CATEGORY_REGISTRY = {
    "dresses-style-guide": {
        "name": "Dresses",
        "aliases": ["dresses", "dress", "womens-dresses"],
        "template_suffix": "dresses",
        "product_keywords": ["dress", "maxi", "midi", "mini", "gown", "slip dress", "wrap dress", "sundress"],
        "collection_handles": ["womens-dresses", "womens-casual-dresses", "midi-dresses", "mini-dresses", "womens-maxi-dresses"],
        "seasonal_hooks": [
            "Transitional Layering Formulas for Late Summer to Fall",
            "Midi Dress and Boot Pairings We're Seeing Everywhere",
            "Flattering Proportions: Styling Slip Dresses for Day and Night",
            "How to Style Casual Maxi Dresses Without Looking Overdressed",
            "The 3 Dress Silhouettes That Flatter Every Body Proportion"
        ]
    },
    "jeans-style-guide": {
        "name": "Jeans",
        "aliases": ["jeans", "denim", "womens-jeans"],
        "template_suffix": "jeans",
        "product_keywords": ["jean", "denim", "jort", "wide leg", "flare", "straight leg", "high waist"],
        "collection_handles": ["womens-jeans", "womens-new-denim", "wide-leg-jeans", "straight-leg-jeans", "judy-blue-womens-jeans", "risen-womens-jeans-collection"],
        "seasonal_hooks": [
            "Wide-Leg vs Straight-Leg Denim: Which Cut flatters Your Frame?",
            "How to Style Barrel and Wide-Leg Jeans with Everyday Footwear",
            "The Shoe and Denim Hemline Pairing Guide for Fall",
            "How to Elevate Dark Wash Denim for an Effortless Polished Look",
            "Finding the Perfect High-Rise Stretch Denim for All-Day Comfort"
        ]
    },
    "womens-shirts-tops-style-guide": {
        "name": "Women's Shirts & Tops",
        "aliases": ["shirts", "tops", "shirts-tops", "womens-shirts-tops", "blouses"],
        "template_suffix": "women-s-shirts-tops",
        "product_keywords": ["top", "blouse", "shirt", "tee", "t-shirt", "tank", "tunic", "cami", "button-down"],
        "collection_handles": ["womens-tops", "womens-t-shirts", "womens-camis-tanks-tops", "womens-knit-tops", "long-sleeve-tops", "v-neck-tops"],
        "seasonal_hooks": [
            "How to Style an Oversized Button-Down for Relaxed Elegance",
            "Essential Layering Tops for Your Capsule Wardrobe",
            "Elevating a Basic White Tee into a Statement Outfit",
            "How to Layer Lightweight Knit Tops Under Blazers and Jackets",
            "Flattering Sleeve Cuts and Necklines for Balanced Silhouettes"
        ]
    },
    "womens-pants-style-guide": {
        "name": "Women's Pants",
        "aliases": ["pants", "trousers", "womens-pants", "bottoms"],
        "template_suffix": "women-s-pants",
        "product_keywords": ["pant", "trouser", "legging", "jogger", "slack", "linen pant", "wide leg pant"],
        "collection_handles": ["womens-pants-leggings", "womens-bottoms", "womens-loungewear"],
        "seasonal_hooks": [
            "How to Style Tailored Trousers with Sneakers for a Weekend Look",
            "Wide-Leg Pants Styling Formulas for Balanced Body Proportions",
            "Transitioning Lightweight Linen and Cotton Pants into Autumn",
            "How to Choose Comfortable Structured Pants for All-Day Wear",
            "High-Waisted Trousers: How to Elongate Your Legs Effortlessly"
        ]
    },
    "womens-skirts-style-guide": {
        "name": "Women's Skirts",
        "aliases": ["skirts", "skirt", "womens-skirts"],
        "template_suffix": "women-s-skirts",
        "product_keywords": ["skirt", "skort", "midi skirt", "mini skirt", "maxi skirt", "denim skirt"],
        "collection_handles": ["womens-skirts", "womens-bottoms"],
        "seasonal_hooks": [
            "How to Style Midi Skirts Across Changing Seasons",
            "Denim and Knit Skirt Formulas for Modern Everyday Looks",
            "Footwear Pairings for Pleated, A-Line, and Column Skirts",
            "Building a Versatile Wardrobe Around Essential Skirt Cuts",
            "How to Style a Silk or Satin Skirt for Casual Daytime Outfits"
        ]
    },
    "cardigans-sweaters-style-guide": {
        "name": "Cardigans & Sweaters",
        "aliases": ["cardigans", "sweaters", "cardigans-sweaters", "knitwear", "knits"],
        "template_suffix": "cardigans-sweaters",
        "product_keywords": ["sweater", "cardigan", "knit", "pullover", "knitwear", "turtleneck", "crewneck"],
        "collection_handles": ["womens-sweaters", "womens-sweatshirts-hoodies", "womens-knit-tops", "womens-tops"],
        "seasonal_hooks": [
            "How to Style Cropped and Relaxed Cardigans with High-Rise Bottoms",
            "Chunky Knit vs Fine-Gauge Sweaters: Layering Proportions",
            "How to Prevent Sweater Pilling and Maintain Knitwear Softness",
            "Effortless French-Tuck Styling Formulas for Oversized Sweaters",
            "Cozy Color Palettes and Textures for Autumn Knitwear"
        ]
    },
    "coats-jackets-style-guide": {
        "name": "Coats & Jackets",
        "aliases": ["coats", "jackets", "coats-jackets", "outerwear", "blazers"],
        "template_suffix": "coats-jackets",
        "product_keywords": ["jacket", "coat", "blazer", "outerwear", "shacket", "vest", "denim jacket", "trench"],
        "collection_handles": ["womens-outerwear", "womens-blazers-vests-jackets", "womens-coats-jackets"],
        "seasonal_hooks": [
            "How to Style an Oversized Blazer Without Overwhelming Your Frame",
            "Transitional Jacket Formulas for Cool Mornings and Warm Afternoons",
            "The Classic Denim Jacket: Modern Styling Rules for This Year",
            "Choosing the Right Outerwear Length for Dresses vs Pants",
            "Shackets and Utility Jackets: Casual Layering Masterclass"
        ]
    },
    "plus-size-curvy-clothing": {
        "name": "Plus Size | Curvy Clothing",
        "aliases": ["plus-size", "curvy", "plus-size-curvy", "curvy-clothing"],
        "template_suffix": "plus-size",
        "product_keywords": ["curvy", "plus size", "plus", "1x", "2x", "3x", "stretch"],
        "collection_handles": ["womens-curvy-plus-size-clothing", "womens-dresses", "womens-jeans", "womens-tops"],
        "seasonal_hooks": [
            "Flattering Denim and Dress Silhouettes That Celebrate Curvy Frames",
            "How to Find the Perfect Balance in Stretch Denim and High Rises",
            "Layering and Proportion Secrets for Curvy Silhouette Styling",
            "Building an Empowering and Versatile Plus-Size Capsule Wardrobe",
            "3-Piece Outfit Formulas for Curvy Proportions That Never Fail"
        ]
    },
    "womens-clothing": {
        "name": "Women's Clothing",
        "aliases": ["womens-clothing", "clothing", "apparel", "general"],
        "template_suffix": "women-s-clothing",
        "product_keywords": ["dress", "top", "jean", "pant", "jacket", "skirt", "jumpsuit", "romper"],
        "collection_handles": ["womens-best-selling-collection", "womens-new-collection", "womens-dresses", "womens-tops"],
        "seasonal_hooks": [
            "The 3-Piece Outfit Rule: How to Always Look Put Together",
            "Curating an Intentional Boutique Capsule Wardrobe This Season",
            "Mixing Textures and Neutral Palettes for High-End Casual Looks",
            "Effortless Day-to-Evening Transitions with Minimal Changes",
            "Modern Proportions: How to Balance Fitted and Relaxed Garments"
        ]
    },
    "everything-anything-about-vegan": {
        "name": "Veganism",
        "aliases": ["vegan", "veganism", "sustainable", "cruelty-free"],
        "template_suffix": "veganism",
        "product_keywords": ["linen", "cotton", "bamboo", "cruelty-free", "sustainable", "plant-based"],
        "collection_handles": ["womens-tops", "womens-dresses", "womens-new-collection"],
        "seasonal_hooks": [
            "Styling Breathable Natural Plant Fibers (Organic Cotton and Linen)",
            "How to Build a Sustainable and Cruelty-Free Wardrobe",
            "Caring for Natural Fabrics to Extend the Lifespan of Your Clothes",
            "Minimalist Plant-Based Textile Styling for Everyday Living",
            "Conscious Boutique Fashion: Choosing Quality Over Fast Fashion"
        ]
    },
    "our-tips": {
        "name": "Our Tips",
        "aliases": ["tips", "our-tips", "care", "advice"],
        "template_suffix": "our-tips",
        "product_keywords": ["top", "dress", "jean", "pant", "sweater"],
        "collection_handles": ["womens-tops", "womens-dresses", "womens-sweaters", "womens-new-collection"],
        "seasonal_hooks": [
            "How to Spot High-Quality Stitching and Fabric Construction",
            "Fabric Shrinkage and Garment Care Habits That Save Your Clothes",
            "Closet Editing and Organization Habits for a Stress-Free Morning",
            "How to Care for Delicates and Boutique Knits at Home",
            "Fitting Room Secrets: How to Know If a Garment Really Fits"
        ]
    }
}

# ── Stylist Personas for E-E-A-T Compliance ──
AUTHORS = {
    "Audrey Sterling, MeeeShop Style Director": "/pages/audrey-sterling-style-director",
    "Elena Vance, MeeeShop Lead Stylist": "/pages/elena-vance-lead-stylist",
    "Seraphina Croft, MeeeShop Fashion Editor": "/pages/seraphina-croft-fashion-editor",
    "Vivienne Vance, MeeeShop Senior Stylist": "/pages/vivienne-vance-senior-stylist",
    "Genevieve Thorne, MeeeShop Trend Forecaster": "/pages/genevieve-thorne-trend-forecaster",
    "Maya Devereaux, MeeeShop Fashion Consultant": "/pages/maya-devereaux-fashion-consultant"
}

AI_CLICHES = [
    "In today's fast-paced digital age", "In today's fast-paced world", "Embark on a journey",
    "delve into", "take a deep dive", "Tapestry", "robust", "multifaceted", "testament",
    "unlock", "elevate", "In conclusion", "it's important to note", "game changer",
    "effortlessly chic", "timeless classic", "fashion-forward", "style game", "without further ado",
    "9-to-5", "9 to 5", "boardroom to break room"
]

ENCRYPTED_SECRETS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "secrets.enc")

# ── Secrets Loader ─────────────────────────────────────────────────────────────
def load_all_secrets():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        from secrets_manager import get_all_secrets, inject_to_env
        inject_to_env()
        secrets = get_all_secrets()
        if secrets and secrets.get("SHOPIFY_ACCESS_TOKEN"):
            return secrets
    except Exception:
        pass

    primary_key = (os.environ.get("ENCRYPTION_KEY_PRIMARY") or os.environ.get("DECRYPTION_KEY_PRIMARY", "")).strip()
    fallback_key = (os.environ.get("ENCRYPTION_KEY_FALLBACK") or os.environ.get("DECRYPTION_KEY_FALLBACK", "")).strip()

    if not primary_key or not fallback_key:
        env_store = os.environ.get("SHOPIFY_STORE_URL") or os.environ.get("SHOPIFY_STORE")
        env_token = os.environ.get("SHOPIFY_ACCESS_TOKEN")
        if env_store and env_token:
            return {"SHOPIFY_STORE_URL": env_store, "SHOPIFY_ACCESS_TOKEN": env_token, "GEMINI_API_KEY": os.environ.get("GEMINI_API_KEY", "")}
        print("Error: Primary and Fallback encryption keys are required.", file=sys.stderr)
        sys.exit(1)

    if not os.path.exists(ENCRYPTED_SECRETS_FILE):
        print(f"Error: Encrypted file '{ENCRYPTED_SECRETS_FILE}' not found.", file=sys.stderr)
        sys.exit(1)

    with open(ENCRYPTED_SECRETS_FILE, "r", encoding="utf-8") as f:
        encrypted_data = json.load(f)

    decrypted_secrets = {}
    for key, val in encrypted_data.items():
        try:
            inner = Fernet(primary_key.encode("utf-8")).decrypt(val.encode("utf-8"))
            decrypted_val = Fernet(fallback_key.encode("utf-8")).decrypt(inner).decode("utf-8")
            decrypted_secrets[key] = decrypted_val
        except Exception:
            pass

    return decrypted_secrets

def get_shopify_session(store_url, access_token):
    session = requests.Session()
    session.headers.update({
        "X-Shopify-Access-Token": access_token,
        "Content-Type": "application/json"
    })
    retries = Retry(total=5, backoff_factor=1.5, status_forcelist=[429, 500, 502, 503, 504])
    session.mount('https://', HTTPAdapter(max_retries=retries))
    return session

# ── Dynamic Category Selection ────────────────────────────────────────────────
def get_shopify_blogs(session, store_url):
    resp = session.get(f"{store_url}/admin/api/2024-10/blogs.json")
    resp.raise_for_status()
    all_blogs = resp.json().get('blogs', [])
    return [b for b in all_blogs if b.get('handle') != 'announcements']

def resolve_target_category(session, store_url, blogs, requested_category="auto"):
    req_clean = (requested_category or "auto").strip().lower()

    if req_clean not in ["auto", "", "all", "none"]:
        for handle, meta in CATEGORY_REGISTRY.items():
            if req_clean == handle.lower() or req_clean in [a.lower() for a in meta["aliases"]]:
                matched_blog = next((b for b in blogs if b.get("handle") == handle), None)
                if matched_blog:
                    return matched_blog, meta

    blog_stats = []
    for b in blogs:
        handle = b.get("handle", "")
        if handle == "announcements" or handle not in CATEGORY_REGISTRY:
            continue
        meta = CATEGORY_REGISTRY[handle]
        try:
            count_resp = session.get(f"{store_url}/admin/api/2024-10/blogs/{b['id']}/articles/count.json")
            count = count_resp.json().get("count", 0) if count_resp.status_code == 200 else 99
        except Exception:
            count = 99
        blog_stats.append({"blog": b, "meta": meta, "count": count})

    blog_stats.sort(key=lambda x: x["count"])
    candidates = blog_stats[:min(4, len(blog_stats))]
    chosen = random.choice(candidates)
    return chosen["blog"], chosen["meta"]

# ── Collection Link Resolution (>= 20 Products Rule) ──────────────────────────
def fetch_verified_collections(session, store_url, category_meta):
    collections = []
    keywords = [k.lower() for k in category_meta.get("product_keywords", [])] + [category_meta["name"].lower()]

    try:
        graphql_query = """
        query {
          collections(first: 250) {
            edges {
              node {
                handle
                title
                productsCount {
                  count
                }
              }
            }
          }
        }
        """
        g_resp = session.post(f"{store_url}/admin/api/2024-10/graphql.json", json={"query": graphql_query}, timeout=20)
        valid_colls = {}
        if g_resp.status_code == 200:
            for e in g_resp.json().get("data", {}).get("collections", {}).get("edges", []):
                node = e["node"]
                handle = node["handle"]
                count = node.get("productsCount", {}).get("count", 0)
                if count >= MIN_COLLECTION_PRODUCTS and handle not in ["all-products_do_not_delete", "all"]:
                    valid_colls[handle] = {"title": node["title"], "url": f"/collections/{handle}", "count": count}

        matched = []
        for ch in category_meta.get("collection_handles", []):
            if ch in valid_colls and valid_colls[ch] not in matched:
                matched.append(valid_colls[ch])

        for h, info in valid_colls.items():
            if info not in matched:
                text = f"{h} {info['title']}".lower()
                if any(kw in text for kw in keywords):
                    matched.append(info)

        if len(matched) < 2:
            fallbacks = ["womens-new-collection", "womens-best-selling-collection", "womens-tops", "womens-dresses"]
            for fb in fallbacks:
                if fb in valid_colls and valid_colls[fb] not in matched:
                    matched.append(valid_colls[fb])
                    if len(matched) >= 3:
                        break

        collections = matched[:3]
    except Exception as e:
        print(f"Warning: Error fetching verified collections: {e}")

    return collections

# ── Deduplication Helper ───────────────────────────────────────────────────────
def get_all_existing_titles(session, store_url, blogs):
    titles = []
    for b in blogs:
        try:
            url = f"{store_url}/admin/api/2024-10/blogs/{b['id']}/articles.json?limit=250&fields=id,title"
            resp = session.get(url)
            if resp.status_code == 200:
                for a in resp.json().get('articles', []):
                    if a.get('title'):
                        titles.append(a['title'].strip())
        except Exception:
            pass
    return list(set(titles))

# ── Google Discover Content Generation ─────────────────────────────────────────
def generate_discover_article(category_meta, collections, existing_titles, topic_override=None):
    from ai_client import generate as ai_generate

    category_name = category_meta["name"]
    seasonal_hooks = category_meta.get("seasonal_hooks", [f"How to Style {category_name} for Everyday Elegance"])

    # 1. Determine Topic with Season/Trend Context
    existing_lower = {t.lower().strip() for t in existing_titles}
    if topic_override:
        topic = topic_override.strip()
    else:
        available_hooks = [h for h in seasonal_hooks if h.lower().strip() not in existing_lower]
        if available_hooks:
            topic = random.choice(available_hooks)
        else:
            qualifiers = [
                "Transitional Styling Formulas",
                "How to Balance Proportions for Everyday Chic",
                "Effortless Casual Outfit Ideas",
                "Footwear and Layering Guide",
                "Capsule Wardrobe Essentials"
            ]
            topic = f"How to Style {category_name}: {random.choice(qualifiers)}"

    print(f"[*] Discover Topic Angle Selected: '{topic}'")

    # 2. Contextual internal linking
    context = ""
    if collections:
        context += "Here are our verified store collections. Insert a MAXIMUM of 2 to 3 internal links across the entire article using exact HTML anchor tags:\n"
        for c in collections:
            context += f"- {c['title']} (URL: {c['url']})\n"

    # 3. AI Editorial Styling Prompt
    prompt = f"""
Act as a senior fashion director and boutique stylist at MeeeShop (USA). Write a comprehensive, Google Discover-eligible styling guide for women: "{topic}".

STRICT STRUCTURE AND CONTENT REQUIREMENTS:
1. Introduction (120-150 words): Relatable real-world scene (morning commute, coffee run, event dressing) explaining why fabric quality and proportion balance matter.
2. <h2>1. Mastering Proportions & Silhouette Balance</h2>:
   Detailed stylist advice paragraph + 3 specific outfit formulas formatted as a bulleted checklist (<ul><li>).
3. <h2>2. Textile Selection, Color Harmonies & Footwear</h2>:
   In-depth advice covering specific fabric blends (e.g. breathable organic cotton, linen, high-recovery stretch denim, fine knitwear) and exact shoe pairing rules.
4. <blockquote>Memorable stylist rule-of-thumb takeaway quote</blockquote>
5. <h2>Frequently Asked Questions</h2>:
   You MUST include EXACTLY 3 complete, well-explained Q&As using this exact format:
   <div class="faq-item">
     <p><strong>Q: [Insert shopper question]?</strong></p>
     <p>A: [Insert comprehensive stylist answer].</p>
   </div>
6. Internal Links: Naturally link 2-3 of these active store collections using exact HTML anchor tags (<a href="...">...</a>):
{context}
7. Length: Write ~750 to 950 words of rich, complete, valuable editorial content.
8. Forbidden Phrases: Do NOT use phrases like {", ".join(AI_CLICHES[:8])}.
9. Output: Return ONLY clean, valid raw HTML. Do NOT include markdown code blocks.
"""

    html_content = ai_generate(prompt, max_tokens=2200, temperature=0.7)
    if not html_content:
        raise RuntimeError("AI content generation failed across all providers.")

    html_content = html_content.strip()
    if html_content.startswith("```html"):
        html_content = html_content[7:]
    if html_content.startswith("```"):
        html_content = html_content[3:]
    if html_content.endswith("```"):
        html_content = html_content[:-3]
    html_content = re.sub(r'<!DOCTYPE[^>]*>', '', html_content, flags=re.IGNORECASE).strip()
    html_content = re.sub(r'<html[^>]*>', '', html_content, flags=re.IGNORECASE).strip()
    html_content = re.sub(r'</html>', '', html_content, flags=re.IGNORECASE).strip()
    html_content = re.sub(r'<head>.*?</head>', '', html_content, flags=re.DOTALL | re.IGNORECASE).strip()
    html_content = re.sub(r'<body[^>]*>', '', html_content, flags=re.IGNORECASE).strip()
    html_content = re.sub(r'</body>', '', html_content, flags=re.IGNORECASE).strip()
    html_content = re.sub(r'<meta[^>]*>', '', html_content, flags=re.IGNORECASE).strip()

    # Clean unclosed sentences
    if not html_content.endswith((".", "</p>", "</ul>", "</blockquote>", "</div>", ">")):
        last_p = max(html_content.rfind("."), html_content.rfind("</p>"), html_content.rfind("</div>"))
        if last_p > len(html_content) - 150:
            html_content = html_content[:last_p + 1]
            if not html_content.endswith("</p>") and "<p>" in html_content:
                html_content += "</p>"

    # Extract H1 and clean title
    article_title = topic
    if "<h1>" in html_content and "</h1>" in html_content:
        h1_start = html_content.find("<h1>") + 4
        h1_end = html_content.find("</h1>")
        article_title = html_content[h1_start:h1_end].strip()
        html_content = html_content[:html_content.find("<h1>")] + html_content[h1_end + 5:]
        html_content = html_content.strip()

    # Intelligent Word-Boundary SEO Title Truncation (50-60 chars)
    raw_seo_title = f"{article_title} | MeeeShop Style Guide"
    if len(raw_seo_title) <= 60:
        seo_title = raw_seo_title
    else:
        truncated = raw_seo_title[:57]
        last_space = truncated.rfind(' ')
        seo_title = (truncated[:last_space] if last_space > 35 else truncated) + '...'

    meta_desc = f"Expert styling advice for {category_name.lower()}: learn how to balance proportions, choose quality fabrics, and style effortless outfits with free US shipping!"[:155]

    # Robust FAQ Extraction across multiple formats
    faq_items = []
    # Pattern 1: <p><strong>Q: ...</strong></p><p>A: ...</p>
    q_matches = re.findall(r'<p><strong>(?:Q:|Question:)?\s*(.*?)</strong></p>\s*<p>(?:A:|Answer:)?\s*(.*?)</p>', html_content, re.DOTALL | re.IGNORECASE)
    for q, a in q_matches:
        q_clean = re.sub(r'<[^>]+>', '', q).strip()
        a_clean = re.sub(r'<[^>]+>', '', a).strip()
        if q_clean and a_clean and len(q_clean) > 8:
            faq_items.append({"question": q_clean, "answer": a_clean})

    # Pattern 2: <h3>Q: ...</h3><p>...
    if not faq_items:
        h3_matches = re.findall(r'<h[34]>(?:Q:|Question:)?\s*(.*?)</h[34]>\s*<p>(?:A:|Answer:)?\s*(.*?)</p>', html_content, re.DOTALL | re.IGNORECASE)
        for q, a in h3_matches:
            q_clean = re.sub(r'<[^>]+>', '', q).strip()
            a_clean = re.sub(r'<[^>]+>', '', a).strip()
            if q_clean and a_clean and len(q_clean) > 8:
                faq_items.append({"question": q_clean, "answer": a_clean})

    return article_title, seo_title, meta_desc, html_content, faq_items

# ── Shopify Free Image Library & Curated HD Lifestyle Photography ──────────────
SHOPIFY_FREE_LIFESTYLE_LIBRARY = {
    "dresses-style-guide": [
        "https://images.unsplash.com/photo-1496747611176-843222e1e57c?auto=format&fit=crop&w=1600&h=900&q=85",
        "https://images.unsplash.com/photo-1515372039744-b8f02a3ae446?auto=format&fit=crop&w=1600&h=900&q=85",
        "https://images.unsplash.com/photo-1492707892479-7bc8d5a4ee93?auto=format&fit=crop&w=1600&h=900&q=85"
    ],
    "jeans-style-guide": [
        "https://images.unsplash.com/photo-1541099649105-f69ad21f3246?auto=format&fit=crop&w=1600&h=900&q=85",
        "https://images.unsplash.com/photo-1582418702059-97ebafb35d09?auto=format&fit=crop&w=1600&h=900&q=85",
        "https://images.unsplash.com/photo-1576995853123-5a10305d93c0?auto=format&fit=crop&w=1600&h=900&q=85"
    ],
    "womens-shirts-tops-style-guide": [
        "https://images.unsplash.com/photo-1485968579580-b6d095142e6e?auto=format&fit=crop&w=1600&h=900&q=85",
        "https://images.unsplash.com/photo-1503342217505-b0a15ec3261c?auto=format&fit=crop&w=1600&h=900&q=85",
        "https://images.unsplash.com/photo-1564257631407-4deb1f99d992?auto=format&fit=crop&w=1600&h=900&q=85"
    ],
    "womens-pants-style-guide": [
        "https://images.unsplash.com/photo-1509631179647-0177331693ae?auto=format&fit=crop&w=1600&h=900&q=85",
        "https://images.unsplash.com/photo-1594633312681-425c7b97ccd1?auto=format&fit=crop&w=1600&h=900&q=85",
        "https://images.unsplash.com/photo-1485230895905-ec40ba36b9bc?auto=format&fit=crop&w=1600&h=900&q=85"
    ],
    "womens-skirts-style-guide": [
        "https://images.unsplash.com/photo-1583496661160-fb5886a0aaaa?auto=format&fit=crop&w=1600&h=900&q=85",
        "https://images.unsplash.com/photo-1508427953056-b00b8d78ebf5?auto=format&fit=crop&w=1600&h=900&q=85",
        "https://images.unsplash.com/photo-1515886657613-9f3515b0c78f?auto=format&fit=crop&w=1600&h=900&q=85"
    ],
    "cardigans-sweaters-style-guide": [
        "https://images.unsplash.com/photo-1576871337632-b9aef4c17ab9?auto=format&fit=crop&w=1600&h=900&q=85",
        "https://images.unsplash.com/photo-1434389677669-e08b4cac3105?auto=format&fit=crop&w=1600&h=900&q=85",
        "https://images.unsplash.com/photo-1516762689617-e1cffcef479d?auto=format&fit=crop&w=1600&h=900&q=85"
    ],
    "coats-jackets-style-guide": [
        "https://images.unsplash.com/photo-1544441893-675973e31985?auto=format&fit=crop&w=1600&h=900&q=85",
        "https://images.unsplash.com/photo-1539571696357-5a69c17a67c6?auto=format&fit=crop&w=1600&h=900&q=85",
        "https://images.unsplash.com/photo-1483985988355-763728e1935b?auto=format&fit=crop&w=1600&h=900&q=85"
    ],
    "plus-size-curvy-clothing": [
        "https://images.unsplash.com/photo-1569388330292-79cc1ec67270?auto=format&fit=crop&w=1600&h=900&q=85",
        "https://images.unsplash.com/photo-1581044777550-4cfa60707c03?auto=format&fit=crop&w=1600&h=900&q=85",
        "https://images.unsplash.com/photo-1529139574466-a303027c1d8b?auto=format&fit=crop&w=1600&h=900&q=85"
    ],
    "womens-clothing": [
        "https://images.unsplash.com/photo-1490481651871-ab68de25d43d?auto=format&fit=crop&w=1600&h=900&q=85",
        "https://images.unsplash.com/photo-1469334031218-e382a71b716b?auto=format&fit=crop&w=1600&h=900&q=85",
        "https://images.unsplash.com/photo-1445205170230-053b83016050?auto=format&fit=crop&w=1600&h=900&q=85"
    ],
    "everything-anything-about-vegan": [
        "https://images.unsplash.com/photo-1537832816519-689ad163238b?auto=format&fit=crop&w=1600&h=900&q=85",
        "https://images.unsplash.com/photo-1508427953056-b00b8d78ebf5?auto=format&fit=crop&w=1600&h=900&q=85",
        "https://images.unsplash.com/photo-1512436991641-6745cdb1723f?auto=format&fit=crop&w=1600&h=900&q=85"
    ],
    "our-tips": [
        "https://images.unsplash.com/photo-1558769132-cb1aea458c5e?auto=format&fit=crop&w=1600&h=900&q=85",
        "https://images.unsplash.com/photo-1582533561751-ef6f6ab93a2e?auto=format&fit=crop&w=1600&h=900&q=85",
        "https://images.unsplash.com/photo-1489987707025-afc232f7ea0f?auto=format&fit=crop&w=1600&h=900&q=85"
    ]
}

def fetch_shopify_free_lifestyle_image(category_handle, title):
    """
    Picks crystal-clear, high-resolution lifestyle photography from Shopify's free fashion image library
    matching the exact category, formatted to 1200x675 landscape with maximum sharpness.
    """
    urls = SHOPIFY_FREE_LIFESTYLE_LIBRARY.get(category_handle, SHOPIFY_FREE_LIFESTYLE_LIBRARY["womens-clothing"])
    selected_url = random.choice(urls)

    for url in [selected_url] + urls:
        try:
            resp = requests.get(url, timeout=15)
            if resp.status_code == 200 and len(resp.content) > 15000:
                img = Image.open(BytesIO(resp.content)).convert("RGB")
                fitted = ImageOps.fit(img, (1200, 675), method=Image.Resampling.LANCZOS)
                out = BytesIO()
                fitted.save(out, format="JPEG", quality=95, optimize=True)
                print(f"  [OK] Picked high-resolution photoshoot image from Shopify free image library (1200x675)")
                return out.getvalue()
        except Exception as e:
            print(f"Warning: Failed downloading stock photo: {e}")

    return None

def fetch_store_lifestyle_media(session, store_url, category_meta):
    """Fallback: Shopify Store Media Library / High-Res Catalog Shoot (1200x675)"""
    colls = category_meta.get("collection_handles", [])
    query = """
    query getStoreImages($handle: String!) {
      collectionByHandle(handle: $handle) {
        products(first: 10) {
          edges {
            node {
              images(first: 3) {
                edges {
                  node {
                    url(transform: {maxWidth: 1600})
                    width
                    height
                  }
                }
              }
            }
          }
        }
      }
    }
    """
    for ch in colls:
        try:
            resp = session.post(f"{store_url}/admin/api/2024-10/graphql.json", json={"query": query, "variables": {"handle": ch}}, timeout=15)
            if resp.status_code == 200:
                c_data = resp.json().get("data", {}).get("collectionByHandle")
                if c_data and c_data.get("products"):
                    for p_edge in c_data["products"]["edges"]:
                        for im_edge in p_edge["node"]["images"]["edges"]:
                            im_url = im_edge["node"]["url"]
                            if im_url and not im_url.lower().endswith('.svg'):
                                r = requests.get(im_url, timeout=12)
                                if r.status_code == 200:
                                    img = Image.open(BytesIO(r.content))
                                    if img.width >= 800:
                                        fitted = ImageOps.fit(img.convert("RGB"), (1200, 675), method=Image.Resampling.LANCZOS)
                                        out = BytesIO()
                                        fitted.save(out, format="JPEG", quality=95, optimize=True)
                                        print(f"  [OK] Formatted high-res store media photo to 1200x675 landscape")
                                        return out.getvalue()
        except Exception:
            pass
    return None

def resolve_discover_lifestyle_image(session, store_url, title, category_meta, blog_handle):
    """Resolves 1200px+ Lifestyle Imagery from Shopify Free Image Library with Store Media Fallback"""
    print(f"[*] Resolving 1200px+ crystal-clear lifestyle featured imagery for '{title}'...")
    
    # 1. Primary: Curated Shopify Free Image Library (Burst / High-Res Stock)
    img_bytes = fetch_shopify_free_lifestyle_image(blog_handle, title)
    if img_bytes:
        return img_bytes

    # 2. Fallback: Store Media / High-Res Shoot
    img_bytes = fetch_store_lifestyle_media(session, store_url, category_meta)
    if img_bytes:
        return img_bytes

    return None

# ── Shopify Article Publishing & FAQ Schema Injection ─────────────────────────
def publish_discover_article(session, store_url, blog_id, blog_handle, title, seo_title, meta_desc, html_content, author_name, template_suffix, faq_items, image_bytes=None, draft=True, indexnow_key=None):
    author_url = AUTHORS.get(author_name, "/pages/audrey-sterling-style-director")

    author_footer = (
        f'<hr style="margin-top: 32px; margin-bottom: 24px; border: 0; border-top: 1px solid #eaeaea;" />\n'
        f'<p style="font-size: 0.95rem; color: #555; font-style: italic;">'
        f'Written by <strong><a href="{author_url}" style="color: #222; text-decoration: underline;">{author_name}</a></strong>. '
        f'Explore more styling guides and fashion insights on our <a href="{author_url}">Author Bio</a> page.'
        f'</p>'
    )
    full_html = html_content + f"\n{author_footer}"

    tags = "AI_Generated, Needs_Review, Google_Discover_Experiment" if draft else "Google_Discover_Experiment, Google_Discover_Ready, Fashion_Guide"

    article_payload = {
        "article": {
            "title": title,
            "author": author_name,
            "tags": tags,
            "body_html": full_html,
            "summary_html": meta_desc,
            "published": not draft,
            "template_suffix": template_suffix
        }
    }

    alt_text = f"{title} - {template_suffix.replace('-', ' ').title()} outfit formulas and boutique fashion guide at MeeeShop"
    if image_bytes:
        import base64
        b64_img = base64.b64encode(image_bytes).decode('utf-8')
        article_payload["article"]["image"] = {
            "attachment": b64_img,
            "alt": alt_text
        }

    # 1. Create Article on Shopify
    url = f"{store_url}/admin/api/2024-10/blogs/{blog_id}/articles.json"
    resp = session.post(url, json=article_payload)
    resp.raise_for_status()
    article = resp.json().get('article', {})
    article_id = article.get('id')

    print(f"  [OK] Created article on Shopify (ID: {article_id})")

    # 2. Attach SEO Metafields (global.title_tag & global.description_tag)
    metafields_url = f"{store_url}/admin/api/2024-10/blogs/{blog_id}/articles/{article_id}/metafields.json"
    session.post(metafields_url, json={
        "metafield": {"namespace": "global", "key": "title_tag", "value": seo_title[:60], "type": "single_line_text_field"}
    })
    session.post(metafields_url, json={
        "metafield": {"namespace": "global", "key": "description_tag", "value": meta_desc[:155], "type": "single_line_text_field"}
    })

    # 3. Attach Native FAQPage Schema in json_ld_schema.faq
    article_full_url = f"{store_url.rstrip('/')}/blogs/{blog_handle}/{article.get('handle', '')}"
    if faq_items:
        faq_schema = {
            "@type": "FAQPage",
            "@id": f"{article_full_url}#faq",
            "mainEntity": [
                {
                    "@type": "Question",
                    "name": item["question"],
                    "acceptedAnswer": {
                        "@type": "Answer",
                        "text": item["answer"]
                    }
                }
                for item in faq_items
            ]
        }
        session.post(metafields_url, json={
            "metafield": {
                "namespace": "json_ld_schema",
                "key": "faq",
                "value": json.dumps(faq_schema),
                "type": "json"
            }
        })
        print(f"  [OK] Injected FAQPage Schema ({len(faq_items)} Q&As) into json_ld_schema.faq")

    # 4. Instant IndexNow Submission
    if not draft and indexnow_key:
        try:
            host = store_url.replace("https://", "").replace("http://", "").split("/")[0]
            requests.post(
                "https://api.indexnow.org/indexnow",
                json={"host": host, "key": indexnow_key, "keyLocation": f"https://{host}/{indexnow_key}.txt", "urlList": [article_full_url]},
                headers={"Content-Type": "application/json; charset=utf-8"},
                timeout=10
            )
            print(f"  [OK] Submitted {article_full_url} to IndexNow")
        except Exception as e:
            print(f"  [IndexNow Notice]: {e}")

    return article

# ── Main Controller ────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="MeeeShop Google Discover Blog Generation & Testing Engine")
    parser.add_argument("--dry-run", action="store_true", help="Generate content and test without publishing to Shopify")
    parser.add_argument("--category", type=str, default="auto", help="Target blog category handle or 'auto'")
    parser.add_argument("--draft", action="store_true", help="Save as draft in Shopify Admin")
    parser.add_argument("--publish", action="store_true", help="Publish immediately live")
    parser.add_argument("--topic", type=str, default=None, help="Custom topic override")
    args = parser.parse_args()

    is_draft = not args.publish if args.publish else (args.draft or os.environ.get("DRAFT_MODE", "false").lower() in ["true", "1", "yes"])
    is_dry_run = args.dry_run

    print(f"\n{'='*75}")
    print(f"  MeeeShop Google Discover Experiment Pipeline")
    print(f"  Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"  Mode     : {'DRY RUN' if is_dry_run else ('DRAFT' if is_draft else 'LIVE PUBLISH')}")
    print(f"{'='*75}\n")

    secrets = load_all_secrets()
    gemini_key = secrets.get("GEMINI_API_KEY")
    shopify_store = (secrets.get("SHOPIFY_STORE_URL") or f"https://{secrets.get('SHOPIFY_STORE', '')}").rstrip('/')
    shopify_token = secrets.get("SHOPIFY_ACCESS_TOKEN")
    indexnow_key = secrets.get("INDEXNOW_KEY")

    if not all([shopify_store, shopify_token]):
        print("Error: Missing SHOPIFY_STORE_URL or SHOPIFY_ACCESS_TOKEN.", file=sys.stderr)
        sys.exit(1)

    session = get_shopify_session(shopify_store, shopify_token)

    # 1. Fetch Active Category Blogs
    blogs = get_shopify_blogs(session, shopify_store)
    if not blogs:
        sys.exit("Error: No active category blogs found.")

    # 2. Select Target Category & Template
    req_cat = os.environ.get("CATEGORY") or args.category
    chosen_blog, category_meta = resolve_target_category(session, shopify_store, blogs, req_cat)
    blog_id = chosen_blog['id']
    blog_handle = chosen_blog['handle']
    template_suffix = category_meta['template_suffix']

    print(f"[*] Target Blog Channel: {chosen_blog['title']} (/blogs/{blog_handle})")
    print(f"[*] Template Suffix    : {template_suffix}")

    # 3. Load Existing Titles for Deduplication
    existing_titles = get_all_existing_titles(session, shopify_store, blogs)
    print(f"[*] Indexed {len(existing_titles)} existing articles to ensure zero duplicate topics.")

    # 4. Fetch Verified Collections (>= 20 Products Rule)
    collections = fetch_verified_collections(session, shopify_store, category_meta)
    print(f"[*] Found {len(collections)} verified collection links with >= 20 products:")
    for c in collections:
        print(f"    - {c['title']} ({c['url']}, Active: {c['count']})")

    # 5. Generate Discover Article Content
    title, seo_title, meta_desc, html_content, faq_items = generate_discover_article(
        category_meta, collections, existing_titles, topic_override=args.topic
    )

    # 6. Resolve 1200px+ Crystal-Clear Lifestyle Imagery from Shopify Free Image Library
    image_bytes = resolve_discover_lifestyle_image(session, shopify_store, title, category_meta, blog_handle)

    # 7. Select E-E-A-T Stylist Persona
    author_name = random.choice(list(AUTHORS.keys()))
    print(f"[*] Assigned E-E-A-T Stylist: {author_name}")

    if is_dry_run:
        print(f"\n{'='*75}")
        print("  DRY RUN PREVIEW (No changes made to Shopify)")
        print(f"{'='*75}")
        print(f"Title          : {title}")
        print(f"SEO Title Tag  : {seo_title}")
        print(f"Meta Desc      : {meta_desc}")
        print(f"Author         : {author_name}")
        print(f"Image Size     : {len(image_bytes) if image_bytes else 0} bytes")
        print(f"FAQ Count      : {len(faq_items)} Q&As parsed for FAQPage schema")
        print(f"Word Count     : ~{len(html_content.split())} words")
        print(f"\nHTML Preview (First 350 chars):\n{html_content[:350]}...\n")
        return

    # 8. Publish to Shopify
    article = publish_discover_article(
        session=session,
        store_url=shopify_store,
        blog_id=blog_id,
        blog_handle=blog_handle,
        title=title,
        seo_title=seo_title,
        meta_desc=meta_desc,
        html_content=html_content,
        author_name=author_name,
        template_suffix=template_suffix,
        faq_items=faq_items,
        image_bytes=image_bytes,
        draft=is_draft,
        indexnow_key=indexnow_key
    )

    print(f"\n{'='*75}")
    print(f"  ✅ SUCCESS: Google Discover article created successfully!")
    print(f"  - Article ID     : {article.get('id')}")
    print(f"  - Title          : {article.get('title')}")
    print(f"  - Blog           : {chosen_blog['title']} (/blogs/{blog_handle})")
    print(f"  - Status         : {'Draft (in Admin)' if is_draft else 'Published Live'}")
    print(f"  - Tagging        : Google_Discover_Experiment")
    print(f"  - Schema         : FAQPage + BlogPosting injected")
    print(f"{'='*75}\n")

if __name__ == "__main__":
    main()

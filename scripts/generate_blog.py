#!/usr/bin/env python3
"""
generate_blog.py — Full-Featured Google Discover & Multi-Category Blog Automation
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
100% Google Discover Eligible & Compliant with Google Search Essentials:
  - Multi-Category Support: Balanced rotation & targeting across all 11 active category blogs
    (Announcements is strictly EXCLUDED — reserved for store-related news only)
  - Resilient Model Cascade: Dynamically discovers and falls back across available Gemini models
  - Original Editorial Style: High-value first-person stylist voice, actionable advice, no single-product forced linking
  - Automatic Dawn OS 2.0 Template Suffix Mapping (article.dresses, article.jeans, etc.)
  - 1200x630 Google Discover Landscape Featured Images with descriptive 10-15 word ALT text
  - E-E-A-T Stylist Persona attribution with author bio links
  - Complete Shopify SEO Metafields (global.title_tag 50-60c, global.description_tag 140-155c)
  - Full Structured Data (JSON-LD BlogPosting schema)
  - Excerpt / summary_html population for RSS feeds and search snippets
  - High-intent structured HTML with styled blockquotes, bulleted lists, and zero body <meta> tags
  - IndexNow submission upon live publishing for fast search engine indexing
"""

import os
import sys
import json
import time
import random
import requests
import io
import re
from datetime import datetime
from PIL import Image, ImageOps
from io import BytesIO
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from cryptography.fernet import Fernet

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# ── Category & Template Registry for MeeeShop (11 Categories, Announcements Excluded) ──
CATEGORY_REGISTRY = {
    "dresses-style-guide": {
        "name": "Dresses",
        "aliases": ["dresses", "dress", "womens-dresses"],
        "template_suffix": "dresses",
        "product_keywords": ["dress", "maxi", "midi", "mini", "gown", "slip dress", "wrap dress", "sundress"],
        "collection_handles": ["womens-dresses", "casual-dresses", "maxi-dresses", "mini-dresses"],
        "topic_themes": [
            "How to style casual dresses for everyday boutique looks",
            "Best dress silhouettes for petite and tall body shapes",
            "Transitioning summer dresses into fall with smart layering",
            "Flattering midi and maxi dress outfit formulas for women",
            "Choosing the right dress neckline and length for your proportions"
        ]
    },
    "jeans-style-guide": {
        "name": "Jeans",
        "aliases": ["jeans", "denim", "womens-jeans"],
        "template_suffix": "jeans",
        "product_keywords": ["jean", "denim", "jort", "wide leg", "flare", "straight leg", "high waist"],
        "collection_handles": ["womens-jeans", "wide-leg-jeans", "flare-jeans", "skinny-jeans", "straight-leg-jeans"],
        "topic_themes": [
            "How to style wide leg and straight leg jeans in 2026",
            "Finding the best fitting jeans for your body shape and proportions",
            "Denim cuffing and hemline guide for ankle boots and sneakers",
            "High-waisted vs mid-rise jeans: which silhouette is more flattering?",
            "Elevating dark wash denim for casual office and evening looks"
        ]
    },
    "womens-shirts-tops-style-guide": {
        "name": "Women's Shirts & Tops",
        "aliases": ["shirts", "tops", "shirts-tops", "womens-shirts-tops", "blouses"],
        "template_suffix": "women-s-shirts-tops",
        "product_keywords": ["top", "blouse", "shirt", "tee", "t-shirt", "tank", "tunic", "cami", "button-down"],
        "collection_handles": ["womens-tops", "womens-blouses", "womens-t-shirts", "tank-tops"],
        "topic_themes": [
            "How to style button-down shirts and blouses for everyday chic",
            "Essential tops every woman needs in her capsule wardrobe",
            "Elevating a basic tee into a polished outfit with smart layering",
            "How to layer tops under blazers and cardigans effortlessly",
            "Flattering necklines and sleeve cuts for different silhouettes"
        ]
    },
    "womens-pants-style-guide": {
        "name": "Women's Pants",
        "aliases": ["pants", "trousers", "womens-pants", "bottoms"],
        "template_suffix": "women-s-pants",
        "product_keywords": ["pant", "trouser", "legging", "jogger", "slack", "linen pant", "wide leg pant"],
        "collection_handles": ["womens-pants", "wide-leg-pants", "womens-trousers", "womens-bottoms"],
        "topic_themes": [
            "How to style wide leg pants without looking shorter",
            "Chic linen pants outfit ideas for warm weather and travel",
            "Styling tailored trousers for casual chic and work outfits",
            "Finding comfortable pants that look structured and flattering",
            "Proportion rules for styling wide-leg vs slim trousers"
        ]
    },
    "womens-skirts-style-guide": {
        "name": "Women's Skirts",
        "aliases": ["skirts", "skirt", "womens-skirts"],
        "template_suffix": "women-s-skirts",
        "product_keywords": ["skirt", "skort", "midi skirt", "mini skirt", "maxi skirt", "denim skirt"],
        "collection_handles": ["womens-skirts", "midi-skirts", "maxi-skirts", "denim-skirts"],
        "topic_themes": [
            "How to style midi skirts for effortless year-round outfits",
            "Building a versatile capsule wardrobe around essential skirts",
            "Styling denim skirts for casual day-to-night looks",
            "Flattering skirt proportions and footwear pairing guidelines",
            "How to wear mini and maxi skirts with confidence"
        ]
    },
    "cardigans-sweaters-style-guide": {
        "name": "Cardigans & Sweaters",
        "aliases": ["cardigans", "sweaters", "cardigans-sweaters", "knitwear", "knits"],
        "template_suffix": "cardigans-sweaters",
        "product_keywords": ["sweater", "cardigan", "knit", "pullover", "knitwear", "turtleneck", "crewneck"],
        "collection_handles": ["womens-sweaters", "womens-cardigans", "knitwear"],
        "topic_themes": [
            "How to style cardigans for modern outfits without looking dated",
            "Slimming sweater cuts, knit textures, and flattering necklines",
            "Layering chunky and lightweight knits across transitional seasons",
            "Cozy chic sweater outfit ideas for work and weekends",
            "How to prevent sweater pilling and keep knitwear looking new"
        ]
    },
    "coats-jackets-style-guide": {
        "name": "Coats & Jackets",
        "aliases": ["coats", "jackets", "coats-jackets", "outerwear", "blazers"],
        "template_suffix": "coats-jackets",
        "product_keywords": ["jacket", "coat", "blazer", "outerwear", "shacket", "vest", "denim jacket", "trench"],
        "collection_handles": ["womens-jackets", "womens-coats", "womens-outerwear", "womens-blazers"],
        "topic_themes": [
            "How to style an oversized blazer for effortless modern looks",
            "Essential transitional jackets every modern wardrobe needs",
            "Denim jacket styling formulas for spring and autumn",
            "Choosing outerwear lengths that balance your outfit proportions",
            "Styling tailored coats for polished day-to-evening transitions"
        ]
    },
    "plus-size-curvy-clothing": {
        "name": "Plus Size | Curvy Clothing",
        "aliases": ["plus-size", "curvy", "plus-size-curvy", "curvy-clothing"],
        "template_suffix": "plus-size",
        "product_keywords": ["curvy", "plus size", "plus", "1x", "2x", "3x", "stretch"],
        "collection_handles": ["plus-size", "curvy-clothing", "plus-size-dresses", "curvy-jeans"],
        "topic_themes": [
            "Flattering dress and denim silhouettes for curvy women",
            "Finding the perfect fit and stretch in curvy plus size clothing",
            "Styling tips that celebrate and accentuate natural curves",
            "Building an empowering plus size capsule wardrobe",
            "Proportion and layering hacks for curvy figures"
        ]
    },
    "womens-clothing": {
        "name": "Women's Clothing",
        "aliases": ["womens-clothing", "clothing", "apparel", "general"],
        "template_suffix": "women-s-clothing",
        "product_keywords": ["dress", "top", "jean", "pant", "jacket", "skirt", "jumpsuit", "romper"],
        "collection_handles": ["womens-new-collection", "womens-clothing", "best-sellers"],
        "topic_themes": [
            "Building a versatile 2026 boutique capsule wardrobe",
            "3-piece outfit formulas that always look put together",
            "French-girl inspired everyday fashion essentials for modern women",
            "Seasonal wardrobe color palettes and styling pairing strategies",
            "How to look expensive on a budget with boutique styling staples"
        ]
    },
    "everything-anything-about-vegan": {
        "name": "Veganism",
        "aliases": ["vegan", "veganism", "sustainable", "cruelty-free"],
        "template_suffix": "veganism",
        "product_keywords": ["linen", "cotton", "bamboo", "cruelty-free", "sustainable", "plant-based"],
        "collection_handles": ["womens-clothing", "womens-tops", "womens-dresses"],
        "topic_themes": [
            "How to build an ethical and sustainable vegan wardrobe",
            "Styling breathable natural plant-based fabrics (linen & organic cotton)",
            "Cruelty-free boutique fashion staples for conscious dressing",
            "Caring for natural vegan textiles to maximize garment longevity",
            "Sustainable minimalist outfit ideas for mindful living"
        ]
    },
    "our-tips": {
        "name": "Our Tips",
        "aliases": ["tips", "our-tips", "care", "advice"],
        "template_suffix": "our-tips",
        "product_keywords": ["top", "dress", "jean", "pant", "sweater"],
        "collection_handles": ["womens-clothing", "womens-tops"],
        "topic_themes": [
            "How to spot high quality clothing stitching and fabric before buying",
            "Predicting fabric shrinkage and behavior before you wash",
            "How to organize your closet to save 15 minutes every morning",
            "Fabric care masterclass: preventing color fading, pilling, and stretching",
            "Stain removal and garment care hacks for your favorite boutique clothes"
        ]
    }
}

# ── Stylist Personas for E-E-A-T Compliance ────────────────────────────────────
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
    "effortlessly chic", "timeless classic", "fashion-forward", "style game", "without further ado"
]

ENCRYPTED_SECRETS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "secrets.enc")

# ── Secrets & Auth ─────────────────────────────────────────────────────────────
def load_all_secrets():
    """Load secrets from secrets_manager or decrypt secrets.enc via Double-Fernet."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        from secrets_manager import get_all_secrets, inject_to_env
        inject_to_env()
        secrets = get_all_secrets()
        if secrets and secrets.get("SHOPIFY_ACCESS_TOKEN"):
            return secrets
    except Exception as e:
        print(f"Notice: secrets_manager helper unavailable ({e}), trying direct env & secrets.enc...")

    primary_key = (
        os.environ.get("ENCRYPTION_KEY_PRIMARY") or
        os.environ.get("DECRYPTION_KEY_PRIMARY", "")
    ).strip()
    fallback_key = (
        os.environ.get("ENCRYPTION_KEY_FALLBACK") or
        os.environ.get("DECRYPTION_KEY_FALLBACK", "")
    ).strip()

    if not primary_key or not fallback_key:
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
        except Exception as e:
            print(f"Warning: Failed to decrypt secret '{key}': {e}", file=sys.stderr)

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

# ── Category & Blog Selection ──────────────────────────────────────────────────
def get_shopify_blogs(session, store_url):
    resp = session.get(f"{store_url}/admin/api/2024-10/blogs.json")
    resp.raise_for_status()
    all_blogs = resp.json().get('blogs', [])
    # Strictly filter out Announcements so it is never used for automated blog generation
    return [b for b in all_blogs if b.get('handle') != 'announcements']

def resolve_target_category(session, store_url, blogs, requested_category="auto"):
    """
    Selects the target blog category among the 11 active categories (Announcements excluded).
    If 'auto', calculates article counts across categories and selects
    under-represented categories to maintain balanced coverage across all categories.
    """
    req_clean = (requested_category or "auto").strip().lower()

    # 1. Check if user requested a specific category or alias
    if req_clean not in ["auto", "", "all", "none"]:
        for handle, meta in CATEGORY_REGISTRY.items():
            if req_clean == handle.lower() or req_clean in [a.lower() for a in meta["aliases"]]:
                matched_blog = next((b for b in blogs if b.get("handle") == handle), None)
                if matched_blog:
                    print(f"[*] Target category explicitly selected: '{meta['name']}' (Handle: {handle})")
                    return matched_blog, meta

    # 2. Balanced Auto-Selection: Query article counts across all 11 active category blogs
    print("[*] Calculating balanced category rotation across active blogs...")
    blog_stats = []
    for b in blogs:
        handle = b.get("handle", "")
        if handle == "announcements":
            continue
        meta = CATEGORY_REGISTRY.get(handle)
        if not meta:
            continue
        try:
            count_resp = session.get(f"{store_url}/admin/api/2024-10/blogs/{b['id']}/articles/count.json")
            count = count_resp.json().get("count", 0) if count_resp.status_code == 200 else 99
        except Exception:
            count = 99
        blog_stats.append({
            "blog": b,
            "meta": meta,
            "count": count
        })

    # Sort blogs by lowest article count first
    blog_stats.sort(key=lambda x: x["count"])
    print("  Category article distribution:")
    for s in blog_stats:
        print(f"    - {s['meta']['name']} ({s['blog']['handle']}): {s['count']} articles")

    # Pick randomly among the bottom 4 lowest-count categories for healthy variety
    lowest_candidates = blog_stats[:min(4, len(blog_stats))]
    chosen = random.choice(lowest_candidates)
    print(f"[*] Auto-selected under-represented category: '{chosen['meta']['name']}' (Count: {chosen['count']})")
    return chosen["blog"], chosen["meta"]

# ── Product & Collection Context ───────────────────────────────────────────────
def fetch_category_shopify_data(session, store_url, category_meta):
    """
    Fetches active products and collections specifically relevant to the chosen category.
    Selects 3 compatible products with valid raster images for the 1200x630 featured collage.
    """
    products = []
    collections = []
    keywords = [k.lower() for k in category_meta.get("product_keywords", [])]

    try:
        # Fetch active products pool
        prod_resp = session.get(f"{store_url}/admin/api/2024-10/products.json?status=active&limit=100")
        prod_resp.raise_for_status()
        all_prods = prod_resp.json().get('products', [])

        # Filter products with valid raster images (exclude SVGs)
        prods_with_imgs = []
        for p in all_prods:
            valid_src = None
            for im in p.get('images', []):
                s = im.get('src', '')
                if s and not s.lower().endswith('.svg') and '.svg?' not in s.lower():
                    valid_src = s
                    break
            if valid_src:
                p['_valid_img'] = valid_src
                prods_with_imgs.append(p)

        # Match products by category keywords
        matched_prods = []
        for p in prods_with_imgs:
            text = f"{p.get('title', '')} {p.get('product_type', '')} {' '.join(p.get('tags', []))}".lower()
            if any(kw in text for kw in keywords):
                matched_prods.append(p)

        pool = matched_prods if len(matched_prods) >= 3 else prods_with_imgs
        if pool:
            sample_size = min(3, len(pool))
            featured = random.sample(pool, sample_size)
            for p in featured:
                handle = p.get('handle')
                price = p.get('variants', [{}])[0].get('price', '49') if p.get('variants') else '49'
                products.append({
                    "id": p.get('id'),
                    "title": p.get('title'),
                    "handle": handle,
                    "url": f"/products/{handle}",
                    "image_url": p.get('_valid_img'),
                    "price": price,
                    "product_type": p.get('product_type', 'Apparel')
                })

        # Fetch relevant collections
        coll_handles = category_meta.get("collection_handles", [])
        for ch in coll_handles:
            collections.append({
                "title": ch.replace("-", " ").title(),
                "url": f"/collections/{ch}"
            })

        # Also pull live custom collections as fallback
        if len(collections) < 3:
            c_resp = session.get(f"{store_url}/admin/api/2024-10/custom_collections.json?limit=10")
            if c_resp.status_code == 200:
                for c in c_resp.json().get('custom_collections', []):
                    h = c.get('handle')
                    if h and not any(col['url'] == f"/collections/{h}" for col in collections):
                        collections.append({
                            "title": c.get('title'),
                            "url": f"/collections/{h}"
                        })

    except Exception as e:
        print(f"Warning: Error fetching category data: {e}")

    return products, collections

# ── Deduplication & History ────────────────────────────────────────────────────
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

# ── Robust Multi-Model Gemini Caller ───────────────────────────────────────────
def call_gemini_with_backoff(client, prompt, retries=2):
    """
    Calls Google GenAI client with automatic model discovery and error fallback.
    Tries modern available model candidates in cascade.
    """
    try:
        available_models = [m.name.replace("models/", "") for m in client.models.list()]
    except Exception:
        available_models = []

    priority = [
        "gemini-3.6-flash",
        "gemini-3.6-pro",
        "gemini-3.1-flash",
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-1.5-flash",
        "gemini-1.5-pro"
    ]

    models_to_try = [p for p in priority if p in available_models]
    if not models_to_try:
        models_to_try = priority + [m for m in available_models if m not in priority]

    for model_name in models_to_try:
        for attempt in range(retries):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt
                )
                if response and response.text and len(response.text.strip()) > 10:
                    return response.text.strip()
            except Exception as e:
                err_str = str(e)
                if "404" in err_str or "NOT_FOUND" in err_str:
                    print(f"  [Model Notice]: {model_name} not available. Trying next model...")
                    break
                elif "429" in err_str or "Quota" in err_str or "503" in err_str:
                    time.sleep(2 * (attempt + 1))
                else:
                    print(f"  [Model Notice]: {model_name} error: {err_str[:80]}")
                    break

    raise RuntimeError("All Gemini model candidates failed or returned empty.")

# ── High-Quality Content Generation Engine (Original Style) ───────────────────
def generate_blog_content(api_key, category_meta, collections, existing_titles):
    """
    Generates high-value, Google Discover-ready blog content in the original
    conversational first-person stylist voice, without single-product forced linking.
    """
    from google import genai
    client = genai.Client(api_key=api_key)

    category_name = category_meta["name"]
    sample_themes = "\n".join(f"- {t}" for t in category_meta.get("topic_themes", []))

    # Exclusion list for anti-duplication
    exclusion_text = ""
    if existing_titles:
        sample_exclusions = existing_titles[:250]
        exclusion_text = "DO NOT use or rephrase any of these already covered topics:\n" + "\n".join(f"- {t}" for t in sample_exclusions) + "\n"

    # Step 1: Generate Specific Trending Question for Category
    topic_prompt = f"""
Act as an expert SEO strategist and boutique fashion editor for MeeeShop, a women's clothing brand in the USA.
Provide ONE specific, highly trending 'People Also Ask' style question that women shoppers in the USA are currently searching for regarding {category_name}.
It should be a practical, helpful styling question, NOT a product-specific pitch.

Core category focus areas:
{sample_themes}

{exclusion_text}

Return ONLY the generated question as a clean single-line string (no markdown, no quotes, no extra text, English only).
"""

    topic_raw = call_gemini_with_backoff(client, topic_prompt)
    topic = topic_raw.strip().strip('"').strip("'").split("\n")[0].strip()

    # Safety deduplication check
    if any(topic.lower() == t.lower() for t in existing_titles):
        print("  [Notice]: Topic already exists. Selecting fresh theme variant...")
        topic = random.choice(category_meta.get("topic_themes", [topic]))

    print(f"[*] Trending Topic Selected for {category_name}: '{topic}'")

    # Step 2: Store collections context for natural internal linking
    context = ""
    if collections:
        context += "Here are our store collections. To ensure natural SEO, you MUST insert a MAXIMUM of 2 to 3 internal links to our collections across the entire article using exact HTML anchor tags (e.g. <a href='/collections/...'>...</a>). Select only the most relevant ones. ONLY link to these specific URLs. DO NOT hallucinate collection URLs:\n"
        for c in collections:
            context += f"- {c['title']} (URL: {c['url']})\n"

    # Step 3: Write Article Body (Original High-Value Stylist Voice)
    article_prompt = f"""
Act as an expert fashion and lifestyle consultant at MeeeShop. Write an in-depth, SEO-optimized blog article answering this question: "{topic}".

STRICT GUIDELINES:
1. Target Audience: Women shoppers in the USA searching for authentic style advice.
2. Tone: Active, conversational, first-person stylist voice. Speak from real-world styling and fitting room experience.
3. Rhythm: Ensure "burstiness". Mix short, punchy sentences with longer explanations. Do not use monotonous sentence structures.
4. Forbidden Words (AI Telltales): Do NOT use any of these phrases: {", ".join(AI_CLICHES)}.
5. Modern Layout & Formatting (CRITICAL):
   - The first line MUST be the <h1> title.
   - Use engaging <h2> subheadings.
   - Break up walls of text. Use <blockquote> for key takeaways, stylist tips, or quotes.
   - Use bulleted lists (<ul><li>) with relevant emojis for easy scanning.
   - Bold important phrases.
   - The article must genuinely help the reader with actionable styling guidance and NOT sound like a sales pitch.
   - Do NOT insert single product links or specific vendor item names into the body text. Keep the focus on styling formulas and wardrobe advice.
   - Interlink provided collections naturally within the text using HTML anchor tags.
6. Language: Pure English only. Do NOT output any foreign characters, non-English words, or broken tokens.
7. Output Format: Return ONLY valid HTML. Do not wrap in ```html markdown blocks.

{context}
"""

    html_content = call_gemini_with_backoff(client, article_prompt).strip()

    if html_content.startswith("```html"):
        html_content = html_content[7:]
    if html_content.startswith("```"):
        html_content = html_content[3:]
    if html_content.endswith("```"):
        html_content = html_content[:-3]
    html_content = re.sub(r'<meta[^>]*>', '', html_content, flags=re.IGNORECASE).strip()

    # Extract <h1> title and strip from body to avoid double H1 in Dawn theme
    article_title = topic
    if "<h1>" in html_content and "</h1>" in html_content:
        h1_start = html_content.find("<h1>") + 4
        h1_end = html_content.find("</h1>")
        article_title = html_content[h1_start:h1_end].strip()
        html_content = html_content[:html_content.find("<h1>")] + html_content[h1_end + 5:]
        html_content = html_content.strip()

    # Generate 50-60 char SEO Title and 140-155 char Meta Description
    seo_title = f"{article_title} | MeeeShop {datetime.now().year}"[:60]
    meta_desc = f"Discover expert styling tips and fit advice for {category_name} at MeeeShop. Explore our curated boutique guide with fast US shipping & easy returns!"[:155]

    return article_title, seo_title, meta_desc, html_content

# ── 1200x630 Google Discover Image Generation ──────────────────────────────────
def generate_1200x630_collage(products):
    """
    Creates a 1200x630 Google Discover eligible landscape 3-panel collage.
    Center featured image: TALLER (380x600) with white border.
    Side images: SHORTER (360x500), vertically centered.
    Background: Premium cream (#F8F6F3).
    """
    image_urls = [
        p['image_url'] for p in products 
        if p.get('image_url') and not p['image_url'].lower().endswith('.svg') and '.svg?' not in p['image_url'].lower()
    ]
    if not image_urls:
        return None

    images = []
    for url in image_urls[:3]:
        try:
            resp = requests.get(url, timeout=12)
            if resp.status_code == 200:
                images.append(Image.open(BytesIO(resp.content)).convert("RGB"))
        except Exception as e:
            print(f"Warning: Failed downloading product image ({url}): {e}")

    if not images:
        return None

    CANVAS_W, CANVAS_H = 1200, 630
    BG_COLOR = (248, 246, 243)
    BORDER_COLOR = (255, 255, 255)

    canvas = Image.new("RGB", (CANVAS_W, CANVAS_H), BG_COLOR)

    feat_img = images[0]
    left_img = images[1] if len(images) > 1 else images[0]
    right_img = images[2] if len(images) > 2 else (images[1] if len(images) > 1 else images[0])

    # Left tile
    fitted_left = ImageOps.fit(left_img, (360, 500), method=Image.Resampling.LANCZOS)
    canvas.paste(fitted_left, (20, (CANVAS_H - 500) // 2))

    # Right tile
    fitted_right = ImageOps.fit(right_img, (360, 500), method=Image.Resampling.LANCZOS)
    canvas.paste(fitted_right, (820, (CANVAS_H - 500) // 2))

    # Center tile (Featured with white border)
    inner_feat = ImageOps.fit(feat_img, (368, 588), method=Image.Resampling.LANCZOS)
    bordered_feat = ImageOps.expand(inner_feat, border=6, fill=BORDER_COLOR)
    canvas.paste(bordered_feat, (410, (CANVAS_H - 600) // 2))

    out_buf = BytesIO()
    canvas.save(out_buf, format="JPEG", quality=92, optimize=True)
    return out_buf.getvalue()

def generate_article_featured_image(api_key, title, category_name, products):
    """
    Attempts AI image generation (16:9 1200px+), falling back to
    the 1200x630 3-panel product styling collage.
    """
    print(f"[*] Creating 1200x630 Google Discover featured image for '{title}'...")
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        prompt = (
            f"High quality editorial lifestyle photography for a women's fashion article about {category_name}. "
            f"Subject: {title}. "
            f"Cinematic lighting, warm boutique aesthetic, modern USA fashion styling, 16:9 aspect ratio, 1200px resolution. "
            f"No text, no watermarks, realistic and relatable."
        )
        for m in ["imagen-3.0-generate-001", "imagen-3.0-fast-generate-001"]:
            try:
                resp = client.models.generate_images(
                    model=m,
                    prompt=prompt,
                    config=dict(number_of_images=1, aspect_ratio="16:9", output_mime_type="image/jpeg")
                )
                if hasattr(resp, 'generated_images') and resp.generated_images:
                    print(f"  [OK] Successfully generated AI featured image with {m}")
                    return resp.generated_images[0].image.image_bytes
            except Exception:
                pass
    except Exception:
        pass

    # Reliable 1200x630 Discover collage fallback
    print("  [OK] Building 1200x630 Google Discover 3-panel outfit collage...")
    return generate_1200x630_collage(products)

# ── IndexNow Submission ────────────────────────────────────────────────────────
def submit_to_indexnow(store_url, article_url, indexnow_key):
    """Submits newly published article URL to IndexNow protocol (Bing, Yandex, Seznam)."""
    if not indexnow_key:
        return
    try:
        host = store_url.replace("https://", "").replace("http://", "").split("/")[0]
        payload = {
            "host": host,
            "key": indexnow_key,
            "keyLocation": f"https://{host}/{indexnow_key}.txt",
            "urlList": [article_url]
        }
        resp = requests.post(
            "https://api.indexnow.org/indexnow",
            json=payload,
            headers={"Content-Type": "application/json; charset=utf-8"},
            timeout=10
        )
        if resp.status_code in [200, 202]:
            print(f"  [OK] Submitted {article_url} to IndexNow (Status: {resp.status_code})")
        else:
            print(f"  [IndexNow Notice]: Status {resp.status_code} ({resp.text[:100]})")
    except Exception as e:
        print(f"  [IndexNow Notice]: {e}")

# ── Shopify Article Publishing & Metafields ────────────────────────────────────
def publish_shopify_article_complete(session, store_url, blog_id, blog_handle, title, seo_title, meta_desc, html_content, author_name, template_suffix, image_bytes=None, draft=True, indexnow_key=None):
    """
    Publishes article to Shopify with complete SEO Metafields, summary_html excerpt,
    JSON-LD structured data, and exact OS 2.0 template suffix.
    """
    author_url = AUTHORS.get(author_name, "/pages/audrey-sterling-style-director")

    # Inject author attribution footer
    author_footer = (
        f'<hr style="margin-top: 32px; margin-bottom: 24px; border: 0; border-top: 1px solid #eaeaea;" />\n'
        f'<p style="font-size: 0.95rem; color: #555; font-style: italic;">'
        f'Written by <strong><a href="{author_url}" style="color: #222; text-decoration: underline;">{author_name}</a></strong>. '
        f'Explore more curated styling insights and fashion guides on our <a href="{author_url}">Author Bio</a> page.'
        f'</p>'
    )
    full_html = html_content + f"\n{author_footer}"

    tags = "AI_Generated, Needs_Review" if draft else "Google_Discover_Ready, Fashion_Guide"

    article_payload = {
        "article": {
            "title": title,
            "author": author_name,
            "tags": tags,
            "body_html": full_html,
            "summary_html": meta_desc,  # Feeds RSS/Atom feeds, search previews, and sitemaps
            "published": not draft,
            "template_suffix": template_suffix
        }
    }

    # Descriptive 10-15 word ALT text for Discover
    alt_text = f"{title} - {template_suffix.replace('-', ' ').title()} outfit ideas and women's fashion guide at MeeeShop"
    if image_bytes:
        import base64
        b64_img = base64.b64encode(image_bytes).decode('utf-8')
        article_payload["article"]["image"] = {
            "attachment": b64_img,
            "alt": alt_text
        }

    # Step 1: Create Article
    url = f"{store_url}/admin/api/2024-10/blogs/{blog_id}/articles.json"
    resp = session.post(url, json=article_payload)
    resp.raise_for_status()
    article = resp.json().get('article', {})
    article_id = article.get('id')

    print(f"  [OK] Article record created on Shopify (ID: {article_id})")

    # Step 2: Set SEO Metafields (global.title_tag, global.description_tag, json_ld_schema)
    metafields_url = f"{store_url}/admin/api/2024-10/blogs/{blog_id}/articles/{article_id}/metafields.json"

    # 1. Title Tag
    session.post(metafields_url, json={
        "metafield": {
            "namespace": "global",
            "key": "title_tag",
            "value": seo_title[:60],
            "type": "single_line_text_field"
        }
    })

    # 2. Description Tag
    session.post(metafields_url, json={
        "metafield": {
            "namespace": "global",
            "key": "description_tag",
            "value": meta_desc[:155],
            "type": "single_line_text_field"
        }
    })

    # 3. Complete Structured Data Schema
    article_full_url = f"{store_url.rstrip('/')}/blogs/{blog_handle}/{article.get('handle', '')}"
    img_src = article.get('image', {}).get('src', '')
    schema_payload = {
        "@context": "https://schema.org/",
        "@type": "BlogPosting",
        "headline": seo_title,
        "description": meta_desc,
        "image": img_src,
        "datePublished": article.get("created_at", datetime.utcnow().isoformat() + "Z"),
        "dateModified": article.get("updated_at", datetime.utcnow().isoformat() + "Z"),
        "author": {
            "@type": "Person",
            "name": author_name,
            "url": f"{store_url.rstrip('/')}{author_url}"
        },
        "publisher": {
            "@type": "Organization",
            "name": "MeeeShop",
            "logo": {
                "@type": "ImageObject",
                "url": f"{store_url.rstrip('/')}/cdn/shop/files/logo.png"
            }
        },
        "url": article_full_url
    }

    session.post(metafields_url, json={
        "metafield": {
            "namespace": "json_ld_schema",
            "key": "blogposting",
            "value": json.dumps(schema_payload),
            "type": "json"
        }
    })
    print("  [OK] Attached SEO Title, Meta Description & JSON-LD BlogPosting Metafields")

    # Step 3: Fast IndexNow Notification (If published live)
    if not draft:
        submit_to_indexnow(store_url, article_full_url, indexnow_key)

    return article

def process_existing_approved_drafts(session, store_url, blog_id, template_suffix):
    """Publishes any pending drafts marked 'Approved'."""
    url = f"{store_url}/admin/api/2024-10/blogs/{blog_id}/articles.json?limit=50"
    resp = session.get(url)
    if resp.status_code != 200:
        return
    articles = resp.json().get('articles', [])
    for article in articles:
        tags = [t.strip() for t in article.get('tags', '').split(',')]
        if 'Approved' in tags and not article.get('published_at'):
            print(f"Publishing approved draft: '{article['title']}'")
            new_tags = [t for t in tags if t not in ['Approved', 'Needs_Review']] + ['Google_Discover_Ready']
            payload = {
                "article": {
                    "id": article['id'],
                    "tags": ", ".join(new_tags),
                    "published": True,
                    "template_suffix": template_suffix
                }
            }
            update_url = f"{store_url}/admin/api/2024-10/blogs/{blog_id}/articles/{article['id']}.json"
            session.put(update_url, json=payload)

# ── Main Execution Workflow ────────────────────────────────────────────────────
def main():
    print(f"\n{'='*70}")
    print(f"  MeeeShop SEO & Google Discover Blog Automation")
    print(f"  Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"{'='*70}\n")

    # Load credentials
    secrets = load_all_secrets()
    gemini_key = secrets.get("GEMINI_API_KEY")
    shopify_store = secrets.get("SHOPIFY_STORE_URL") or f"https://{secrets.get('SHOPIFY_STORE', '')}"
    shopify_token = secrets.get("SHOPIFY_ACCESS_TOKEN")
    indexnow_key = secrets.get("INDEXNOW_KEY")

    if not all([gemini_key, shopify_store, shopify_token]):
        print("Error: Missing required secrets (GEMINI_API_KEY, SHOPIFY_STORE_URL, SHOPIFY_ACCESS_TOKEN).", file=sys.stderr)
        sys.exit(1)

    shopify_store = shopify_store.rstrip('/')
    session = get_shopify_session(shopify_store, shopify_token)

    # 1. Fetch Shopify Blogs (Announcements excluded)
    print("[*] Fetching active category blog channels...")
    blogs = get_shopify_blogs(session, shopify_store)
    if not blogs:
        print("Error: No category blogs found on Shopify store.", file=sys.stderr)
        sys.exit(1)

    # 2. Select Target Category & Template
    requested_category = os.environ.get("CATEGORY", "auto")
    chosen_blog, category_meta = resolve_target_category(session, shopify_store, blogs, requested_category)
    blog_id = chosen_blog['id']
    blog_handle = chosen_blog['handle']
    template_suffix = category_meta['template_suffix']

    print(f"\n[*] Target Blog Selected:")
    print(f"  - Blog Title       : {chosen_blog['title']}")
    print(f"  - Blog Handle      : {blog_handle}")
    print(f"  - Blog ID          : {blog_id}")
    print(f"  - Template Suffix  : {template_suffix} (templates/article.{template_suffix}.json)")

    # 3. Publish any approved drafts in this category
    process_existing_approved_drafts(session, shopify_store, blog_id, template_suffix)

    # 4. Fetch Existing Titles for Anti-Duplication
    print("\n[*] Loading existing article titles for anti-duplication...")
    existing_titles = get_all_existing_titles(session, shopify_store, blogs)
    print(f"  [OK] {len(existing_titles)} existing articles indexed to prevent duplicate topics")

    # 5. Fetch Collections & Products for Chosen Category
    print(f"\n[*] Fetching collection and product context for '{category_meta['name']}'...")
    products, collections = fetch_category_shopify_data(session, shopify_store, category_meta)
    print(f"  [OK] Found {len(products)} category products & {len(collections)} collection links")

    # 6. Generate Content (Original High-Value Editorial Style)
    print(f"\n[*] Generating Google Discover eligible article content...")
    title, seo_title, meta_desc, html_content = generate_blog_content(
        gemini_key, category_meta, collections, existing_titles
    )

    # 7. Generate 1200x630 Discover Image (AI or 3-Panel Collage)
    image_bytes = generate_article_featured_image(gemini_key, title, category_meta['name'], products)

    # 8. Select E-E-A-T Stylist Persona
    author_name = random.choice(list(AUTHORS.keys()))
    print(f"[*] Assigned E-E-A-T Stylist Author: {author_name}")

    # 9. Publish Article to Shopify
    is_draft = os.environ.get("DRAFT_MODE", "false").lower() in ["true", "1", "yes"]
    status_str = "DRAFT (Requires review in Admin)" if is_draft else "LIVE (Published immediately)"

    print(f"\n[*] Publishing article to Shopify ({status_str})...")
    article = publish_shopify_article_complete(
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
        image_bytes=image_bytes,
        draft=is_draft,
        indexnow_key=indexnow_key
    )

    print(f"\n{'='*70}")
    print(f"  [OK] SUCCESS: Blog post created successfully!")
    print(f"  - Article Title   : {article.get('title')}")
    print(f"  - Article ID      : {article.get('id')}")
    print(f"  - Blog Category   : {chosen_blog['title']} (/blogs/{blog_handle})")
    print(f"  - Template Suffix : {template_suffix}")
    print(f"  - Status          : {'Draft' if is_draft else 'Published Live'}")
    print(f"  - Discover Image  : 1200x630 Landscape")
    print(f"  - SEO Metafields  : Populated (Title Tag & Description Tag)")
    print(f"{'='*70}\n")

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
generate_blog.py — Full-Featured Google Discover & Multi-Category Blog Automation
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
100% Google Discover Eligible & Compliant with Google Search Essentials:
  - Multi-Category Support: Balanced rotation & targeting for all 12 Shopify blog categories
  - Automatic Dawn OS 2.0 Template Suffix Mapping (article.dresses, article.jeans, etc.)
  - 1200x630 Google Discover Landscape Featured Images with descriptive 10-15 word ALT text
  - E-E-A-T Stylist Persona attribution with author bio links
  - Complete Shopify SEO Metafields (global.title_tag 50-60c, global.description_tag 140-155c)
  - Full Structured Data (JSON-LD BlogPosting schema)
  - Excerpt / summary_html population for RSS feeds and search snippets
  - High-intent structured HTML with styled Q&A/FAQ, blockquotes, and zero body <meta> tags
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

# ── Category & Template Registry for MeeeShop ──────────────────────────────────
CATEGORY_REGISTRY = {
    "dresses-style-guide": {
        "name": "Dresses",
        "aliases": ["dresses", "dress", "womens-dresses"],
        "template_suffix": "dresses",
        "product_keywords": ["dress", "maxi", "midi", "mini", "gown", "slip dress", "wrap dress", "sundress"],
        "collection_handles": ["womens-dresses", "casual-dresses", "maxi-dresses", "mini-dresses"],
        "topic_themes": [
            "how to style casual dresses for everyday wear",
            "best dress silhouettes for petite and tall frames",
            "transitioning summer dresses into fall with layers",
            "flattering midi and maxi dress outfit formulas",
            "choosing the right dress length and neckline for your body shape"
        ]
    },
    "jeans-style-guide": {
        "name": "Jeans",
        "aliases": ["jeans", "denim", "womens-jeans"],
        "template_suffix": "jeans",
        "product_keywords": ["jean", "denim", "jort", "wide leg", "flare", "straight leg", "high waist"],
        "collection_handles": ["womens-jeans", "wide-leg-jeans", "flare-jeans", "skinny-jeans", "straight-leg-jeans"],
        "topic_themes": [
            "how to style wide leg and straight leg jeans in 2026",
            "finding the best fitting jeans for your body shape",
            "denim cuffing and hemline guide for ankle boots and sneakers",
            "high-waisted vs mid-rise jeans: which is more flattering?",
            "elevating dark wash denim for casual work and evening outfits"
        ]
    },
    "womens-shirts-tops-style-guide": {
        "name": "Women's Shirts & Tops",
        "aliases": ["shirts", "tops", "shirts-tops", "womens-shirts-tops", "blouses"],
        "template_suffix": "women-s-shirts-tops",
        "product_keywords": ["top", "blouse", "shirt", "tee", "t-shirt", "tank", "tunic", "cami", "button-down"],
        "collection_handles": ["womens-tops", "womens-blouses", "womens-t-shirts", "tank-tops"],
        "topic_themes": [
            "how to style button-down shirts and blouses for everyday chic",
            "essential tops every woman needs in her capsule wardrobe",
            "elevating a basic graphic tee into a polished outfit",
            "layering tops under blazers and cardigans effortlessly",
            "flattering top silhouettes and neckline styling guide"
        ]
    },
    "womens-pants-style-guide": {
        "name": "Women's Pants",
        "aliases": ["pants", "trousers", "womens-pants", "bottoms"],
        "template_suffix": "women-s-pants",
        "product_keywords": ["pant", "trouser", "legging", "jogger", "slack", "linen pant", "wide leg pant"],
        "collection_handles": ["womens-pants", "wide-leg-pants", "womens-trousers", "womens-bottoms"],
        "topic_themes": [
            "how to style wide leg pants without looking shorter",
            "chic linen pants outfit ideas for warm weather and vacations",
            "styling tailored trousers for casual, office, and evening looks",
            "finding comfortable pants that look structured and flattering",
            "proportion rules for styling wide-leg vs slim trousers"
        ]
    },
    "womens-skirts-style-guide": {
        "name": "Women's Skirts",
        "aliases": ["skirts", "skirt", "womens-skirts"],
        "template_suffix": "women-s-skirts",
        "product_keywords": ["skirt", "skort", "midi skirt", "mini skirt", "maxi skirt", "denim skirt"],
        "collection_handles": ["womens-skirts", "midi-skirts", "maxi-skirts", "denim-skirts"],
        "topic_themes": [
            "how to style midi skirts for effortless year-round outfits",
            "building a capsule wardrobe around versatile skirt styles",
            "styling denim skirts for casual day-to-night looks",
            "flattering skirt proportions and top pairing guidelines",
            "how to wear mini and maxi skirts with confidence"
        ]
    },
    "cardigans-sweaters-style-guide": {
        "name": "Cardigans & Sweaters",
        "aliases": ["cardigans", "sweaters", "cardigans-sweaters", "knitwear", "knits"],
        "template_suffix": "cardigans-sweaters",
        "product_keywords": ["sweater", "cardigan", "knit", "pullover", "knitwear", "turtleneck", "crewneck"],
        "collection_handles": ["womens-sweaters", "womens-cardigans", "knitwear"],
        "topic_themes": [
            "how to style cardigans without looking dated",
            "slimming sweater cuts, knit textures, and necklines",
            "layering chunky and lightweight knits across seasons",
            "cozy chic sweater outfit ideas for work and weekends",
            "how to prevent sweater pilling and keep knitwear looking new"
        ]
    },
    "coats-jackets-style-guide": {
        "name": "Coats & Jackets",
        "aliases": ["coats", "jackets", "coats-jackets", "outerwear", "blazers"],
        "template_suffix": "coats-jackets",
        "product_keywords": ["jacket", "coat", "blazer", "outerwear", "shacket", "vest", "denim jacket", "trench"],
        "collection_handles": ["womens-jackets", "womens-coats", "womens-outerwear", "womens-blazers"],
        "topic_themes": [
            "how to style an oversized blazer for effortless modern outfits",
            "essential transitional jackets every wardrobe needs",
            "denim jacket styling formulas for spring and autumn",
            "choosing outerwear lengths that balance your outfit proportions",
            "styling coats and jackets for polished day-to-evening looks"
        ]
    },
    "plus-size-curvy-clothing": {
        "name": "Plus Size | Curvy Clothing",
        "aliases": ["plus-size", "curvy", "plus-size-curvy", "curvy-clothing"],
        "template_suffix": "plus-size",
        "product_keywords": ["curvy", "plus size", "plus", "1x", "2x", "3x", "stretch"],
        "collection_handles": ["plus-size", "curvy-clothing", "plus-size-dresses", "curvy-jeans"],
        "topic_themes": [
            "flattering dress and denim silhouettes for curvy women",
            "finding the perfect fit and stretch in curvy plus size clothing",
            "styling tips that celebrate and accentuate natural curves",
            "building an empowering plus size capsule wardrobe",
            "proportion and layering hacks for curvy figures"
        ]
    },
    "womens-clothing": {
        "name": "Women's Clothing",
        "aliases": ["womens-clothing", "clothing", "apparel", "general"],
        "template_suffix": "women-s-clothing",
        "product_keywords": ["dress", "top", "jean", "pant", "jacket", "skirt", "jumpsuit", "romper"],
        "collection_handles": ["womens-new-collection", "womens-clothing", "best-sellers"],
        "topic_themes": [
            "building a versatile 2026 boutique capsule wardrobe",
            "3-piece outfit formulas that always look put together",
            "french-girl inspired effortless everyday fashion essentials",
            "seasonal wardrobe color palettes and pairing strategies",
            "how to look expensive on a budget with boutique styling staples"
        ]
    },
    "everything-anything-about-vegan": {
        "name": "Veganism",
        "aliases": ["vegan", "veganism", "sustainable", "cruelty-free"],
        "template_suffix": "veganism",
        "product_keywords": ["linen", "cotton", "bamboo", "cruelty-free", "sustainable", "plant-based"],
        "collection_handles": ["womens-clothing", "womens-tops", "womens-dresses"],
        "topic_themes": [
            "how to build an ethical and sustainable vegan wardrobe",
            "styling breathable natural plant-based fabrics (linen & organic cotton)",
            "cruelty-free boutique fashion staples for conscious dressing",
            "caring for natural vegan textiles to maximize garment life",
            "sustainable minimalist outfit ideas for modern living"
        ]
    },
    "announcements": {
        "name": "Announcements",
        "aliases": ["announcements", "news", "updates", "arrivals"],
        "template_suffix": "announcements",
        "product_keywords": ["dress", "top", "jean", "jacket", "new"],
        "collection_handles": ["womens-new-collection", "womens-clothing"],
        "topic_themes": [
            "2026 fashion trends preview: our latest curated boutique edit",
            "solving everyday wardrobe dilemmas with new seasonal arrivals",
            "stylist picks: versatile pieces you will wear on repeat",
            "fresh seasonal outfit inspirations from our newest collection"
        ]
    },
    "our-tips": {
        "name": "Our Tips",
        "aliases": ["tips", "our-tips", "care", "advice"],
        "template_suffix": "our-tips",
        "product_keywords": ["top", "dress", "jean", "pant", "sweater"],
        "collection_handles": ["womens-clothing", "womens-tops"],
        "topic_themes": [
            "how to spot high quality clothing stitching and fabric before buying",
            "predicting fabric shrinkage and behavior before you wash",
            "how to organize your closet to save 15 minutes every morning",
            "fabric care masterclass: preventing color fading, pilling, and stretching",
            "stain removal and garment care hacks for your favorite boutique clothes"
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
    return resp.json().get('blogs', [])

def resolve_target_category(session, store_url, blogs, requested_category="auto"):
    """
    Selects the target blog category.
    If 'auto', calculates article counts across categories and selects
    under-represented categories to maintain balanced coverage across all 12 blogs.
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

    # 2. Balanced Auto-Selection: Query article counts across all blogs
    print("[*] Calculating balanced category rotation across all blogs...")
    blog_stats = []
    for b in blogs:
        handle = b.get("handle", "")
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
    Selects 3 compatible products (1 primary + 2 styling matches) with images.
    """
    products = []
    collections = []
    keywords = [k.lower() for k in category_meta.get("product_keywords", [])]

    try:
        # Fetch active products pool
        prod_resp = session.get(f"{store_url}/admin/api/2024-10/products.json?status=active&limit=100")
        prod_resp.raise_for_status()
        all_prods = prod_resp.json().get('products', [])
        prods_with_imgs = [p for p in all_prods if p.get('images')]

        # Filter products matching category keywords
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
                img_url = None
                for im in p.get('images', []):
                    src = im.get('src', '')
                    if src and not src.lower().endswith('.svg') and '.svg?' not in src.lower():
                        img_url = src
                        break
                price = p.get('variants', [{}])[0].get('price', '49') if p.get('variants') else '49'
                products.append({
                    "id": p.get('id'),
                    "title": p.get('title'),
                    "handle": handle,
                    "url": f"/products/{handle}",
                    "image_url": img_url,
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

# ── Content Generation with Gemini ─────────────────────────────────────────────
def call_gemini_with_backoff(client, model_name, prompt, retries=3):
    for attempt in range(retries):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt
            )
            return response.text
        except Exception as e:
            if '429' in str(e) or 'Quota' in str(e) or '503' in str(e):
                wait_time = (2 ** attempt) * 4
                print(f"Rate limited by Gemini ({e}). Waiting {wait_time}s...")
                time.sleep(wait_time)
            else:
                raise e
    raise RuntimeError("Max retries exceeded calling Gemini API")

def get_best_text_model(client):
    try:
        models_iterable = client.models.list()
        available = [m.name for m in models_iterable]
        priority = ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-3.1-flash", "gemini-2.0-flash"]
        for p in priority:
            for m in available:
                if p in m and "preview" not in m:
                    return m.replace("models/", "")
        for p in priority:
            for m in available:
                if p in m:
                    return m.replace("models/", "")
        if available:
            return available[0].replace("models/", "")
    except Exception as e:
        print(f"Warning: Model listing fallback: {e}")
    return "gemini-2.5-flash"

def generate_blog_content(api_key, category_meta, products, collections, existing_titles):
    from google import genai
    client = genai.Client(api_key=api_key)
    model_name = get_best_text_model(client)
    print(f"Selected Gemini Model: {model_name}")

    category_name = category_meta["name"]
    sample_themes = "\n".join(f"- {t}" for t in category_meta.get("topic_themes", []))

    # Exclusion list
    exclusion_text = ""
    if existing_titles:
        sample_exclusions = existing_titles[:250]
        exclusion_text = "DO NOT use or rephrase any of these already covered titles:\n" + "\n".join(f"- {t}" for t in sample_exclusions) + "\n"

    # Step 1: Generate Specific Trending Topic for Category
    topic_prompt = f"""
Act as an expert boutique fashion editor for MeeeShop, a modern women's fashion boutique in the USA.
We are writing a featured blog post for our '{category_name}' category.

Here are core themes for this category:
{sample_themes}

{exclusion_text}

Provide ONE specific, highly trending 'People Also Ask' style question that women shoppers in the USA are actively searching for regarding {category_name}.
It should be practical, helpful, and editorial (e.g. fit guidance, styling formula, silhouette comparison, occasion guide, or care tips).
Do NOT include vendor brand names. Do NOT use clickbait or exaggerated phrases.

Return ONLY a valid JSON object in this exact format (no markdown, no backticks):
{{"topic": "The generated question", "seo_title": "Clean 50-60 character SEO Title", "meta_desc": "Action-oriented 140-155 character Meta Description"}}
"""

    topic_resp = call_gemini_with_backoff(client, model_name, topic_prompt).strip()
    try:
        clean_json = topic_resp
        if clean_json.startswith("```json"):
            clean_json = clean_json[7:]
        if clean_json.startswith("```"):
            clean_json = clean_json[3:]
        if clean_json.endswith("```"):
            clean_json = clean_json[:-3]
        topic_data = json.loads(clean_json.strip())
        topic = topic_data.get("topic", "").strip()
        seo_title = topic_data.get("seo_title", topic)[:60].strip()
        meta_desc = topic_data.get("meta_desc", "")[:155].strip()
    except Exception as e:
        print(f"Warning: JSON topic parsing fallback ({e})")
        topic = topic_resp.split("\n")[0].replace('"', '').replace('{', '').replace('}', '').strip()
        seo_title = f"{topic} | MeeeShop Guide"[:60]
        meta_desc = f"Discover expert styling tips and fit advice for {category_name} at MeeeShop. Explore our curated boutique guide with fast US shipping!"[:155]

    print(f"Generated Topic: {topic}")
    print(f"SEO Title: {seo_title}")
    print(f"Meta Description: {meta_desc}")

    # Step 2: Build Context & Products Showcase
    current_year = datetime.now().year
    coll_links_context = "Here are our store collections. You MUST insert 2 to 3 natural internal links using exact HTML <a href='...'>anchor tags</a>:\n"
    for c in collections[:4]:
        coll_links_context += f"- {c['title']} (URL: {c['url']})\n"

    prod_context = ""
    if products:
        prod_context = "Here are 3 featured boutique pieces to subtly reference in your styling examples:\n"
        for p in products:
            prod_context += f"- {p['title']} (${p['price']}) (URL: {p['url']})\n"

    # Step 3: Write Discover-Optimized Article Body
    article_prompt = f"""
Act as a senior fashion stylist at MeeeShop. Write an in-depth, Google Discover-eligible blog article answering: "{topic}".

STRICT GUIDELINES:
1. Target Audience: Women shoppers in the USA searching for authentic style advice.
2. Tone & Voice: Warm, conversational, first-person stylist voice. Speak from real-world fitting room experience.
3. Banned AI Phrases: NEVER use any of these phrases: {", ".join(AI_CLICHES)}.
4. HTML Structure (Strict Google Discover & OS 2.0 Compliance):
   - The first line MUST be the <h1> title.
   - Opening Hook: Start with a punchy, relatable paragraph validating the shopper's problem.
   - Use 2 to 3 informative <h2> headings and detailed sub-paragraphs.
   - Include at least one styled <blockquote> for a 'Stylist Tip' or 'Key Takeaway'.
   - Include bulleted lists (<ul><li>) with emojis for scannable outfit formulas.
   - Include a dedicated FAQ/Q&A section answering 2-3 specific shopper questions using <details><summary><strong>Question</strong></summary><p>Answer</p></details>.
   - Subtle Product Integration: In the styling advice, naturally mention the featured boutique pieces as styling examples.
   - Internal Linking: Include 2 to 3 natural links to the provided collections.
   - Do NOT output any <meta> tags in the body HTML.
   - Do NOT wrap in ```html markdown blocks. Output pure HTML.

{coll_links_context}
{prod_context}
"""

    html_content = call_gemini_with_backoff(client, model_name, article_prompt).strip()

    if html_content.startswith("```html"):
        html_content = html_content[7:]
    if html_content.startswith("```"):
        html_content = html_content[3:]
    if html_content.endswith("```"):
        html_content = html_content[:-3]
    html_content = html_content.strip()

    # Clean any accidental <meta> tags inside body
    html_content = re.sub(r'<meta[^>]*>', '', html_content, flags=re.IGNORECASE).strip()

    # Extract <h1> and strip from body to prevent double H1 in Dawn theme
    article_title = topic
    if "<h1>" in html_content and "</h1>" in html_content:
        h1_start = html_content.find("<h1>") + 4
        h1_end = html_content.find("</h1>")
        article_title = html_content[h1_start:h1_end].strip()
        html_content = html_content[:html_content.find("<h1>")] + html_content[h1_end + 5:]
        html_content = html_content.strip()

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
    Attempts AI editorial image generation (16:9 1200px+), falling back to
    the 1200x630 3-panel product styling collage.
    """
    print(f"[*] Creating 1200x630 Google Discover featured image for '{title}'...")
    from google import genai
    client = genai.Client(api_key=api_key)

    prompt = (
        f"High quality editorial lifestyle photography for a women's fashion article about {category_name}. "
        f"Subject: {title}. "
        f"Cinematic lighting, warm boutique aesthetic, modern USA fashion styling, 16:9 aspect ratio, 1200px resolution. "
        f"No text, no watermarks, realistic and relatable."
    )

    models_to_try = ["imagen-3.0-generate-001", "imagen-3.0-fast-generate-001"]
    for m in models_to_try:
        try:
            resp = client.models.generate_images(
                model=m,
                prompt=prompt,
                config=dict(number_of_images=1, aspect_ratio="16:9", output_mime_type="image/jpeg")
            )
            if hasattr(resp, 'generated_images') and resp.generated_images:
                print(f"  ✓ Successfully generated AI featured image with {m}")
                return resp.generated_images[0].image.image_bytes
        except Exception as e:
            print(f"  [Notice] AI model {m} unavailable ({e})")

    # Fallback to high-res 1200x630 Discover collage
    print("  ✓ Building 1200x630 Google Discover 3-panel outfit collage...")
    collage_bytes = generate_1200x630_collage(products)
    return collage_bytes

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
            print(f"  ✓ Submitted {article_url} to IndexNow (Status: {resp.status_code})")
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

    print(f"  ✓ Article record created on Shopify (ID: {article_id})")

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
    print("  ✓ Attached SEO Title, Meta Description & JSON-LD BlogPosting Metafields")

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

    # 1. Fetch Shopify Blogs
    print("[*] Fetching available Shopify blog categories...")
    blogs = get_shopify_blogs(session, shopify_store)
    if not blogs:
        print("Error: No blogs found on Shopify store.", file=sys.stderr)
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
    print(f"  ✓ {len(existing_titles)} existing articles indexed to prevent duplicate topics")

    # 5. Fetch Products & Collections for Chosen Category
    print(f"\n[*] Fetching product and collection context for '{category_meta['name']}'...")
    products, collections = fetch_category_shopify_data(session, shopify_store, category_meta)
    print(f"  ✓ Found {len(products)} category products & {len(collections)} collection links")

    # 6. Generate Content with Gemini
    print(f"\n[*] Generating Google Discover eligible article content with Gemini...")
    title, seo_title, meta_desc, html_content = generate_blog_content(
        gemini_key, category_meta, products, collections, existing_titles
    )

    # 7. Generate 1200x630 Discover Image
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
    print(f"  ✅ SUCCESS: Blog post created successfully!")
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

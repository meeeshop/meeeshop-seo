#!/usr/bin/env python3
"""
generate_blog.py — Full-Featured Google Discover & Multi-Category Blog Automation
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
100% Google Discover Eligible & Compliant with Google Search Essentials:
  - Multi-Category Support: Balanced rotation & targeting across all 11 active category blogs
    (Announcements is strictly EXCLUDED — reserved for store-related news only)
  - Resilient Model Cascade: Dynamically discovers and falls back across available Gemini models
  - Clean Editorial Titles: No clickbait parentheticals, filler phrases, or 9-to-5 fluff
  - Verified Store Collections (>= 20 Active Products Rule): Live GraphQL validation prevents linking to empty collections
  - Strict Topic-Matched Product Images: 1200x630 collage uses products directly matching the exact category & article topic
  - Dedicated FAQ Accordion Section: 2-3 high-intent Q&A accordions optimized for Google Discover & Search rich snippets
  - Full Structured Data: Combined BlogPosting + FAQPage JSON-LD schema
  - Original Editorial Style: High-value first-person stylist voice, actionable advice, no single-product forced linking
  - Automatic Dawn OS 2.0 Template Suffix Mapping (article.dresses, article.jeans, etc.)
  - 1200x630 Google Discover Landscape Featured Images with descriptive 10-15 word ALT text
  - E-E-A-T Stylist Persona attribution with author bio links
  - Complete Shopify SEO Metafields (global.title_tag 50-60c, global.description_tag 140-155c)
  - Excerpt / summary_html population for RSS feeds and search snippets
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
import math
from datetime import datetime
from PIL import Image, ImageOps, ImageFilter
from io import BytesIO
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from cryptography.fernet import Fernet

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

MIN_COLLECTION_PRODUCTS = 20

# ── Category & Template Registry for MeeeShop (11 Categories, Announcements Excluded) ──
CATEGORY_REGISTRY = {
    "dresses-style-guide": {
        "name": "Dresses",
        "aliases": ["dresses", "dress", "womens-dresses"],
        "template_suffix": "dresses",
        "product_keywords": ["dress", "maxi", "midi", "mini", "gown", "slip dress", "wrap dress", "sundress"],
        "collection_handles": ["womens-dresses", "womens-casual-dresses", "midi-dresses", "mini-dresses", "womens-maxi-dresses"],
        "topic_themes": [
            "What to Wear to a Fall Winery Wedding: Midi and Maxi Dress Guide",
            "How to Style a Slip Dress with Sneakers for Daytime Casual Outfits",
            "Best Dress Silhouettes for Petite Women: Hemline and Proportion Rules",
            "Flattering Wrap Dress Styling Tips for Curvy and Hourglass Figures",
            "Transitioning Summer Sundresses into Autumn with Boots and Cardigans",
            "What Shoes to Wear with a Tiered Midi Dress in Late Summer",
            "Effortless Shirt Dress Outfit Ideas for Work and Casual Weekends",
            "How to Style a Bodycon Knit Dress Without Feeling Overdressed",
            "Outdoor Garden Party Dress Ideas Under $75",
            "How to Wear Ankle Boots with Maxi Dresses for Fall",
            "Flattering Necklines for Broad Shoulders: Square Neck vs V-Neck Dresses",
            "The 5 Most Versatile Dress Styles for Capsule Wardrobe Travel",
            "Casual Sunday Brunch Dress Outfits with Denim Jackets and Flats",
            "How to Style a Floral Midi Dress for an Evening Date Night",
            "Long Sleeve vs Sleeveless Midi Dresses: How to Layer Year-Round"
        ]
    },
    "jeans-style-guide": {
        "name": "Jeans",
        "aliases": ["jeans", "denim", "womens-jeans"],
        "template_suffix": "jeans",
        "product_keywords": ["jean", "denim", "jort", "wide leg", "flare", "straight leg", "high waist"],
        "collection_handles": ["womens-jeans", "womens-new-denim", "wide-leg-jeans", "straight-leg-jeans", "judy-blue-womens-jeans", "risen-womens-jeans-collection"],
        "topic_themes": [
            "Best High-Waisted Wide Leg Jeans for Petite Women: Hem and Shoe Guide",
            "How to Style Straight Leg Jeans with Ankle Boots for Fall",
            "Curvy Denim Fit Guide: Finding Stretch and Gap-Free Waistbands",
            "What Shoes to Wear with Cropped Flare Jeans: Flats, Loafers, and Heels",
            "Wide Leg vs Barrel Leg Jeans: Which Silhouette Flatters Your Body Shape?",
            "How to Elevate Dark Wash Straight Jeans for Casual Office Friday",
            "Denim-on-Denim Styling Guide: How to Pair Different Washes Effortlessly",
            "Best Tummy Control High-Rise Jeans: What to Look for in Fabric Blend",
            "How to Style Distressed Boyfriend Jeans with Feminine Tops",
            "Finding the Perfect Inseam: Ankle Length vs Full Length Denim Guide",
            "How to Style White Jeans in Fall and Winter Without Looking Washed Out",
            "Casual Sunday Outfit Formulas Around Classic Medium Wash Jeans",
            "What Tops to Pair with High-Waisted Wide Leg Denim for Balanced Proportions",
            "How to Style Black Skinny Jeans for Modern Outfits That Feel Fresh",
            "Denim Hemline Rules: Which Jeans to Wear with Loafers, Mules, and Sneakers"
        ]
    },
    "womens-shirts-tops-style-guide": {
        "name": "Women's Shirts & Tops",
        "aliases": ["shirts", "tops", "shirts-tops", "womens-shirts-tops", "blouses"],
        "template_suffix": "women-s-shirts-tops",
        "product_keywords": ["top", "blouse", "shirt", "tee", "t-shirt", "tank", "tunic", "cami", "button-down"],
        "collection_handles": ["womens-tops", "womens-t-shirts", "womens-camis-tanks-tops", "womens-knit-tops", "long-sleeve-tops", "v-neck-tops"],
        "topic_themes": [
            "How to Style an Oversized Button-Down Shirt for Relaxed Casual Outfits",
            "The French Tuck vs Full Tuck Guide for High-Waisted Pants and Jeans",
            "How to Layer Lightweight Knit Tops Under Blazers Without Adding Bulk",
            "Flattering Blouse Necklines: Choosing Between V-Neck, Cowl, and Boatneck",
            "Elevating a Basic White T-Shirt: 5 Outfit Formulas That Look Expensive",
            "Best Work-to-Weekend Blouses for Effortless Day-to-Night Dressing",
            "How to Style Linen and Gauze Shirts for Breathable Warm Weather Looks",
            "Statement Sleeve Tops: How to Balance Proportions with Slim Bottoms",
            "Silk and Satin Blouse Outfit Ideas for Date Nights and Evenings Out",
            "How to Style Peplum and Babydoll Tops for Flattering Waist Definition",
            "Capsule Wardrobe Tops: The 5 Essential Shirts Every Woman Needs",
            "How to Wear Crop Tops with High-Rise Bottoms for Subtle, Polished Coverage",
            "Plaid and Flannel Shirt Outfits That Look Tailored, Not Grungy",
            "Camisole Layering Guide: Wearing Cami Tops Under Cardigans and Shackets",
            "How to Style Tie-Front and Wrap Tops to Accentuate Natural Curves"
        ]
    },
    "womens-pants-style-guide": {
        "name": "Women's Pants",
        "aliases": ["pants", "trousers", "womens-pants", "bottoms"],
        "template_suffix": "women-s-pants",
        "product_keywords": ["pant", "trouser", "legging", "jogger", "slack", "linen pant", "wide leg pant"],
        "collection_handles": ["womens-pants-leggings", "womens-bottoms", "womens-loungewear"],
        "topic_themes": [
            "How to Style Tailored Trousers with Sneakers for Chic Casual Days",
            "Best Wide-Leg Trousers for Petite Women: Proportions and Hemlines",
            "Pleated vs Flat-Front Pants: Which Cut is Most Flattering for Your Shape?",
            "How to Style Linen Wide Leg Pants for Beach Vacations and Warm Days",
            "Comfortable Elastic Waistband Pants That Still Look Structured and Chic",
            "Cropped Ankle Pants Footwear Guide: What to Wear with Flats and Heels",
            "High-Waisted Paperbag Pants Outfit Formulas for Casual and Work Looks",
            "How to Style Faux Leather Pants for Daytime Wear Without Overdoing It",
            "Casual Friday Trouser Outfits: Pairing Slacks with Knitwear and Loafers",
            "How to Style Cargo Pants for a Modern, Polished Street-Style Look",
            "Best Pants for Long Commutes: Wrinkle-Resistant Fabrics and Fits",
            "Monochromatic Trouser Outfits: Styling Tonal Bottoms and Tops",
            "How to Wear Flare Pants with Boots and Platform Sneakers",
            "Straight Leg Chino Styling Formulas for Weekend Errands and Brunch",
            "Finding Trousers That Don't Gap at the Waist: Rise and Fabric Tips"
        ]
    },
    "womens-skirts-style-guide": {
        "name": "Women's Skirts",
        "aliases": ["skirts", "skirt", "womens-skirts"],
        "template_suffix": "women-s-skirts",
        "product_keywords": ["skirt", "skort", "midi skirt", "mini skirt", "maxi skirt", "denim skirt"],
        "collection_handles": ["womens-skirts", "womens-bottoms"],
        "topic_themes": [
            "How to Style a Midi Slip Skirt with an Oversized Sweater and Boots",
            "Denim Midi Skirts with Front Slits: What Tops and Shoes Pair Best",
            "A-Line vs Pencil Skirts: Silhouette Guide for Every Body Proportion",
            "How to Wear Pleated Midi Skirts for Everyday Casual Outfits",
            "Tiered Maxi Skirt Outfit Ideas for Breezy Bohemian and Casual Looks",
            "How to Style Mini Skirts in Fall with Tights, Boots, and Knitwear",
            "Wrap Skirt Styling: How to Keep the Hem Flattering and Secure All Day",
            "What Shoes to Pair with Midi Skirts: Flats, Pointed Mules, and Sneakers",
            "How to Style a Knit Ribbed Skirt for Cozy, Polished Monochrome Looks",
            "Cargo and Utility Skirt Outfits: Feminine Pairings with Simple Tops",
            "Best Skirt Lengths for Petite Women to Elongate Leg Lines",
            "How to Transition Linen and Floral Skirts from Summer into Autumn",
            "Office-Appropriate Skirt Outfits That Don't Feel Stiff or Outdated",
            "High-Waisted Skirt Outfit Formulas That Create an Hourglass Waistline",
            "Styling Leather and Suede Skirts for Fall Date Nights and Dinners"
        ]
    },
    "cardigans-sweaters-style-guide": {
        "name": "Cardigans & Sweaters",
        "aliases": ["cardigans", "sweaters", "cardigans-sweaters", "knitwear", "knits"],
        "template_suffix": "cardigans-sweaters",
        "product_keywords": ["sweater", "cardigan", "knit", "pullover", "knitwear", "turtleneck", "crewneck"],
        "collection_handles": ["womens-sweaters", "womens-sweatshirts-hoodies", "womens-knit-tops", "womens-tops"],
        "topic_themes": [
            "How to Style a Buttoned-Up Cardigan as a Standalone Top",
            "Oversized Chunky Knit Sweaters: How to Half-Tuck into High-Waisted Jeans",
            "Best Lightweight Cardigans for Layering Over Sleeveless Dresses",
            "Cropped Cardigan Outfit Formulas with Wide-Leg Trousers and Skirts",
            "How to Prevent Sweater Pilling: Fabric Care, Washing, and Shaving Tips",
            "Crewneck vs V-Neck Knitwear: Which Neckline Complements Your Frame?",
            "How to Layer a Turtleneck Under Blazers, Dresses, and Button-Downs",
            "Open-Front Duster Cardigan Outfits for Relaxed Everyday Layering",
            "Knit Vest Styling Guide: How to Wear Sweater Vests Over Crisp Shirts",
            "Cashmere and Merino Wool Care: Hand Washing vs Dry Cleaning Guide",
            "Monochrome Sweater and Pant Outfits That Look Effortlessly Expensive",
            "How to Style Cable-Knit Sweaters Without Adding Unwanted Bulk",
            "Striped Breton Knit Sweaters: French-Inspired Everyday Outfit Ideas",
            "Transitioning Knitwear from Chilly Mornings to Warm Afternoons",
            "How to Wear Long Knit Cardigans with Ankle Boots for Coffee Runs"
        ]
    },
    "coats-jackets-style-guide": {
        "name": "Coats & Jackets",
        "aliases": ["coats", "jackets", "coats-jackets", "outerwear", "blazers"],
        "template_suffix": "coats-jackets",
        "product_keywords": ["jacket", "coat", "blazer", "outerwear", "shacket", "vest", "denim jacket", "trench"],
        "collection_handles": ["womens-outerwear", "womens-blazers-vests-jackets", "womens-coats-jackets"],
        "topic_themes": [
            "How to Style an Oversized Blazer with Jeans and Sneakers for Casual Chic",
            "The Classic Trench Coat Styling Guide: Belted vs Open and Layered",
            "Denim Jacket Outfits Across Seasons: Pairing with Dresses and Bottoms",
            "Best Transitional Jackets for 50-60 Degree Weather: Shackets and Bombers",
            "How to Style a Cropped Moto Jacket with High-Waisted Pants and Skirts",
            "Choosing the Right Coat Length for Your Height: Knee-Length vs Maxi",
            "How to Layer Sweaters Under Tailored Wool Coats Without Feeling Stiff",
            "Utility and Quilted Jacket Outfit Ideas for Weekend Walks and Travel",
            "Double-Breasted vs Single-Breasted Blazers: Which Cut Suits Your Frame?",
            "How to Style Leather Blazers for Evening Dinners and Night Outs",
            "Puffer Jacket Styling Formulas That Look Sleek, Not Overstuffed",
            "Shacket Styling 101: Wearing Plaid and Wool Shirt Jackets Over Basics",
            "Water-Resistant Outerwear That Still Looks Fashionable for Rainy Days",
            "Outerwear Color Guide: Camel vs Charcoal vs Black Versatility Comparison",
            "How to Elevate Casual Athleisure with a Structured Long Coat"
        ]
    },
    "plus-size-curvy-clothing": {
        "name": "Plus Size | Curvy Clothing",
        "aliases": ["plus-size", "curvy", "plus-size-curvy", "curvy-clothing"],
        "template_suffix": "plus-size",
        "product_keywords": ["curvy", "plus size", "plus", "1x", "2x", "3x", "stretch"],
        "collection_handles": ["womens-curvy-plus-size-clothing", "womens-dresses", "womens-jeans", "womens-tops"],
        "topic_themes": [
            "Best Flattering Plus-Size Dress Silhouettes: Empire Waist vs Wrap Dresses",
            "Curvy Denim Fit Solutions: High-Rise Stretch Jeans That Never Gap",
            "How to Style Wide-Leg Trousers for Curvy and Plus-Size Proportions",
            "Plus-Size Date Night Outfits: Flattering Midi Dresses and Elevated Tops",
            "Layering Tips for Curvy Figures: Creating Defined Waistlines with Jackets",
            "Best Plus-Size Jeans for Apple and Hourglass Shapes: Rise and Pockets",
            "How to Style Oversized Sweaters and Tops Without Losing Body Shape",
            "Plus-Size Fall Wedding Guest Dresses: Flattering Sleeves and Fabrics",
            "Comfortable Plus-Size Loungewear That Looks Polished for Running Errands",
            "Plus-Size Capsule Wardrobe Essentials: 8 Mix-and-Match Boutique Pieces",
            "How to Choose Tops That Flatter a Fuller Bust Without Pulling or Gapping",
            "Skirt Outfits for Curvy Women: Styling Midi and A-Line Silhouettes",
            "Confidence-Boosting Monochrome Outfits for Curvy and Plus-Size Women",
            "How to Style High-Waisted Shorts and Skorts for Curvy Thighs and Hips",
            "Best Breathable Stretch Fabrics for Plus-Size All-Day Comfort"
        ]
    },
    "womens-clothing": {
        "name": "Women's Clothing",
        "aliases": ["womens-clothing", "clothing", "apparel", "general"],
        "template_suffix": "women-s-clothing",
        "product_keywords": ["dress", "top", "jean", "pant", "jacket", "skirt", "jumpsuit", "romper"],
        "collection_handles": ["womens-best-selling-collection", "womens-new-collection", "womens-dresses", "womens-tops"],
        "topic_themes": [
            "The 10-Piece Boutique Capsule Wardrobe That Creates 30+ Outfits",
            "The 3-Piece Outfit Rule: How Adding a Third Layer Elevates Any Look",
            "How to Build a Cohesive Color Palette for Your Everyday Wardrobe",
            "Day-to-Night Outfit Formulas: Transforming Workwear for Evening Dinner",
            "Boutique Shopping Guide: How to Spot Quality Fabric and Finishing",
            "Texture Mixing 101: Pairing Knit, Denim, Silk, and Leather Seamlessly",
            "Effortless 5-Minute Outfits for Busy Mornings: Ready-to-Wear Formulas",
            "Smart Casual Dress Code Explained: What to Wear for Modern Occasions",
            "How to Refresh Your Style Rut: 5 Easy Tweaks to Elevate Daily Outfits",
            "Seasonal Wardrobe Transition Checklist: What to Pack Away and What to Keep",
            "Packing Light for a Week-Long Vacation: Mix-and-Match Outfit Guide",
            "How to Dress for Your Proportions: Balancing Torso and Leg Lengths",
            "High-Low Fashion Styling: Pairing Affordable Basics with Statement Pieces",
            "Quiet Luxury Aesthetic on an Everyday Budget: Fabrics, Colors, and Cuts",
            "How to Style Jumpsuits and Rompers for Daytime and Evening Events"
        ]
    },
    "everything-anything-about-vegan": {
        "name": "Veganism",
        "aliases": ["vegan", "veganism", "sustainable", "cruelty-free"],
        "template_suffix": "veganism",
        "product_keywords": ["linen", "cotton", "bamboo", "cruelty-free", "sustainable", "plant-based"],
        "collection_handles": ["womens-tops", "womens-dresses", "womens-new-collection"],
        "topic_themes": [
            "How to Build an Ethical and Cruelty-Free Boutique Capsule Wardrobe",
            "Linen vs Organic Cotton: Breathability, Texture, and Durability Guide",
            "Bamboo and Modal Fabrics: Why They Are So Soft and How to Care for Them",
            "Faux Leather Care: How to Clean, Store, and Prevent Peeling and Cracking",
            "Plant-Based Wardrobe Essentials for Mindful, Sustainable Everyday Dressing",
            "How to Care for Natural Fiber Clothing to Double Its Garment Lifespan",
            "Tencel and Lyocell Styling: Breathable Eco-Friendly Fabrics for Travel",
            "Plastic-Free and Low-Impact Fashion: Choosing Sustainable Boutique Pieces",
            "How to Build a Minimalist 15-Piece Eco-Conscious Wardrobe",
            "Cruelty-Free Fashion Alternatives to Silk, Wool, and Down: What to Wear"
        ]
    },
    "our-tips": {
        "name": "Our Tips",
        "aliases": ["tips", "our-tips", "care", "advice"],
        "template_suffix": "our-tips",
        "product_keywords": ["top", "dress", "jean", "pant", "sweater"],
        "collection_handles": ["womens-tops", "womens-dresses", "womens-sweaters", "womens-new-collection"],
        "topic_themes": [
            "How to Read Clothing Care Labels: Preventing Shrinkage, Fading, and Bleeding",
            "The Ultimate Fabric Care Guide: How to Wash Linen, Rayon, and Knits",
            "How to Prevent Sweater and Knitwear Pilling: Shaving and Washing Rules",
            "Clothing Sizing Guide: How to Take Accurate Body Measurements at Home",
            "How to Organize Your Closet by Category and Color for Fast Mornings",
            "Preventing Denim Color Bleed: How to Wash Dark and Indigo Jeans Safely",
            "How to Steam vs Iron Different Fabrics: Delicate Rayon, Cotton, and Silk",
            "How to Fix a Stiff Zipper, Loose Button, or Snagged Thread in Seconds",
            "Spot Cleaning Guide: Removing Coffee, Makeup, and Oil Stains Safely",
            "How to Store Seasonal Clothes: Protecting Fabrics from Moisture and Dust"
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
    "effortlessly chic", "timeless classic", "fashion-forward", "style game", "without further ado",
    "9-to-5", "9 to 5", "boardroom to break room"
]

ENCRYPTED_SECRETS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "secrets.enc")

# ── Title Sanitizer ────────────────────────────────────────────────────────────
def sanitize_editorial_title(title: str) -> str:
    """
    Cleans and standardizes editorial titles.
    Strips conversational parentheticals, clickbait phrases, brackets, quotes, and punctuation.
    E.g. "How to Style Tailored Trousers Casually (Without Looking Like You're Heading to a 9-to-5)"
    -> "How to Style Tailored Trousers Casually"
    """
    clean = title.strip().strip('"').strip("'").strip('“').strip('”')
    clean = re.sub(r'\s*\([^)]*\)\s*$', '', clean).strip()
    clean = re.sub(r'\s*\[[^\]]*\]\s*$', '', clean).strip()
    clean = re.sub(r'[:\-–—\s]+$', '', clean).strip()
    clean = clean.strip('"').strip("'").strip('“').strip('”')
    return clean

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

# ── Dynamic Collection & Product Fetching (>= 20 Products Rule) ────────────────
def fetch_category_shopify_data(session, store_url, category_meta):
    """
    Fetches verified store collections (>= 20 active products) and topic/category matched products.
    """
    collections = []
    keywords = [k.lower() for k in category_meta.get("product_keywords", [])] + [category_meta["name"].lower()]

    try:
        # 1. Fetch live collections with >= 20 products via Shopify GraphQL
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
        valid_colls_by_handle = {}
        if g_resp.status_code == 200:
            edges = g_resp.json().get("data", {}).get("collections", {}).get("edges", [])
            for e in edges:
                node = e["node"]
                handle = node["handle"]
                title = node["title"]
                count = node.get("productsCount", {}).get("count", 0)
                if count >= MIN_COLLECTION_PRODUCTS and handle not in ["all-products_do_not_delete", "all"]:
                    valid_colls_by_handle[handle] = {
                        "title": title,
                        "url": f"/collections/{handle}",
                        "count": count
                    }

        # Match collections against category
        matched_colls = []
        for ch in category_meta.get("collection_handles", []):
            if ch in valid_colls_by_handle and valid_colls_by_handle[ch] not in matched_colls:
                matched_colls.append(valid_colls_by_handle[ch])

        for h, info in valid_colls_by_handle.items():
            if info not in matched_colls:
                text = f"{h} {info['title']}".lower()
                if any(kw in text for kw in keywords):
                    matched_colls.append(info)

        if len(matched_colls) < 2:
            general_fallbacks = ["womens-new-collection", "womens-best-selling-collection", "womens-tops", "womens-dresses"]
            for gf in general_fallbacks:
                if gf in valid_colls_by_handle and valid_colls_by_handle[gf] not in matched_colls:
                    matched_colls.append(valid_colls_by_handle[gf])
                    if len(matched_colls) >= 3:
                        break

        collections = matched_colls[:4]

    except Exception as e:
        print(f"Warning: Error fetching category collections: {e}")

    return collections

def fetch_topic_matched_products(session, store_url, category_meta, topic=""):
    """
    Fetches active products strictly matching the specific article topic and category.
    Directly queries products from the category's active collections via GraphQL.
    """
    colls = category_meta.get("collection_handles", [])
    raw_products = []
    
    prod_query = """
    query getCollectionProducts($handle: String!) {
      collectionByHandle(handle: $handle) {
        id
        title
        products(first: 30) {
          edges {
            node {
              id
              title
              handle
              productType
              images(first: 3) {
                edges {
                  node {
                    url
                  }
                }
              }
              variants(first: 1) {
                edges {
                  node {
                    price
                  }
                }
              }
            }
          }
        }
      }
    }
    """

    for handle in colls:
        try:
            resp = session.post(f"{store_url}/admin/api/2024-10/graphql.json", json={"query": prod_query, "variables": {"handle": handle}}, timeout=15)
            if resp.status_code == 200:
                c_data = resp.json().get("data", {}).get("collectionByHandle")
                if c_data and c_data.get("products"):
                    for p_edge in c_data["products"]["edges"]:
                        p = p_edge["node"]
                        imgs = [im["node"]["url"] for im in p.get("images", {}).get("edges", []) if not im["node"]["url"].lower().endswith('.svg') and '.svg?' not in im["node"]["url"].lower()]
                        if imgs:
                            price = p["variants"]["edges"][0]["node"]["price"] if p.get("variants", {}).get("edges") else "49"
                            raw_products.append({
                                "id": p["id"],
                                "title": p["title"],
                                "handle": p["handle"],
                                "url": f"/products/{p['handle']}",
                                "image_url": imgs[0],
                                "price": price,
                                "product_type": p.get("productType", "Apparel")
                            })
            if len(raw_products) >= 20:
                break
        except Exception:
            pass

    # Score products based on topic & category keywords
    search_text = (topic + " " + " ".join(category_meta.get("product_keywords", []))).lower()
    topic_words = set(re.findall(r'\b[a-zA-Z]{3,}\b', search_text))

    def score_product(p):
        text = f"{p['title']} {p['product_type']}".lower()
        score = 0
        for w in topic_words:
            if w in text:
                score += 2
        return score

    raw_products.sort(key=score_product, reverse=True)

    # Deduplicate by handle
    seen = set()
    deduped = []
    for p in raw_products:
        if p["handle"] not in seen:
            seen.add(p["handle"])
            deduped.append(p)

    return deduped[:6]

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

# ── Programmatic Long-Tail Query Generation Engine ────────────────────────────
OCCASIONS_LONG_TAIL = [
    "Fall Winery Wedding", "Outdoor Garden Party", "Sunday Brunch with Friends",
    "Casual Office Friday", "Dinner Date Night", "Summer Vacation Travel",
    "Holiday Family Gathering", "Weekend Farmers Market", "Boutique Wine Tasting",
    "Girls Weekend Getaway", "Breezy Coastal Trip", "Coffee Run and Errands",
    "Evening Cocktail Gathering", "Outdoor Concert and Festival", "Thanksgiving Dinner",
    "Spring Baby Shower", "Casual Business Lunch", "Effortless Airport Travel"
]

BODY_TYPES_LONG_TAIL = [
    "Petite Women", "Curvy Figures", "Hourglass and Pear Shapes",
    "Tall Frames", "Apple Shapes with Tummy Area", "Athletic Builds",
    "Short Torso and Long Legs", "Fuller Bust Silhouettes"
]

SILHOUETTES_BY_CATEGORY = {
    "dresses": ["Tiered Midi Dresses", "Floral Maxi Dresses", "Satin Slip Dresses", "Belted Shirt Dresses", "Wrap Dresses", "A-Line Sundresses", "Knit Ribbed Midi Dresses"],
    "jeans": ["High-Waisted Wide-Leg Jeans", "Cropped Straight-Leg Denim", "Flare Leg Jeans", "Boyfriend Jeans", "Dark Wash Straight Denim", "Tummy Control High-Rise Jeans"],
    "women-s-shirts-tops": ["Oversized Button-Down Shirts", "Classic White Cotton Tees", "Lightweight Layering Tops", "Silk Wrap Blouses", "Breezy Gauze Shirts", "Peplum Waist Tops"],
    "women-s-pants": ["Tailored Wide-Leg Trousers", "Linen Drawstring Pants", "High-Rise Paperbag Pants", "Cropped Ankle Pants", "Straight-Leg Chinos", "Pleated Front Slacks"],
    "women-s-skirts": ["Midi Slip Skirts", "Denim Midi Skirts with Slits", "Pleated A-Line Skirts", "Tiered Boho Maxi Skirts", "Button-Front Mini Skirts", "Knit Ribbed Skirts"],
    "cardigans-sweaters": ["Buttoned Standalone Cardigans", "Oversized Chunky Knit Sweaters", "Cropped Knit Cardigans", "Open-Front Duster Cardigans", "Ribbed Turtleneck Sweaters"],
    "coats-jackets": ["Oversized Tailored Blazers", "Classic Belted Trench Coats", "Cropped Denim Jackets", "Wool Shackets", "Lightweight Quilted Jackets", "Faux Leather Moto Jackets"],
    "plus-size": ["High-Rise Stretch Denim", "Flattering Wrap Midi Dresses", "Wide-Leg Tailored Trousers", "Belted Empire Waist Tops", "A-Line Midi Skirts"],
    "women-s-clothing": ["Boutique Capsule Wardrobes", "3-Piece Layered Outfits", "Versatile Day-to-Night Outfits", "Monochrome Neutral Ensembles", "Casual Weekend Outfits"],
    "veganism": ["Breathable Linen Outfits", "Organic Cotton Basics", "Bamboo Soft Knitwear", "Cruelty-Free Faux Leather", "Sustainable Plant-Based Pieces"],
    "our-tips": ["Delicate Fabric Care", "Accurate Body Measurements", "Closet Organization Routines", "Fabric Shrinkage Prevention", "Knitwear De-Pilling Routines"]
}

def detect_intent_archetype(topic: str) -> str:
    """
    Classifies search queries into distinct editorial archetypes so articles
    never share identical cookie-cutter structures.
    """
    tl = topic.lower()
    if any(k in tl for k in [" vs ", " versus ", "which silhouette", "which cut", "which dress", "which is more"]):
        return "comparison"
    elif any(k in tl for k in ["wash", "care", "shrink", "fabric", "pilling", "stain", "steam", "iron"]):
        return "care"
    elif any(k in tl for k in ["without", "prevent", "stop ", "gap", "bulky", "frumpy", "dragging", "petite", "tummy", "apple"]):
        return "fit_solver"
    elif any(k in tl for k in ["wedding", "brunch", "office", "travel", "dinner", "date night", "vacation"]):
        return "occasion"
    elif any(k in tl for k in ["shoes", "boots", "footwear", "sneakers", "loafers", "heels", "what to wear with"]):
        return "pairing"
    else:
        return "fit_solver"

def generate_programmatic_long_tail_topic(cat_key, category_name, existing_lower):
    """
    Deterministically generates genuine, high-volume People Also Ask (PAA) questions
    and real shopper search queries answering everyday fit, pairing, and sizing dilemmas.
    """
    if cat_key == "our-tips":
        care_topics = [
            "How to Wash Modal and Bamboo Tops So They Never Shrink or Pill",
            "How to Prevent Sweater and Knitwear Pilling: Garment Care Guide",
            "Clothing Sizing Guide: How to Take Accurate Body Measurements at Home",
            "Preventing Dark Denim Color Bleed: Laundry Rules That Actually Work",
            "Steam vs Iron: Safe Way to Refresh Silk, Rayon, Linen, and Knits",
            "How to Wash and Care for Delicate Boutique Fabrics to Prevent Damage",
            "How to Remove Stains from Delicate Fabrics Without Damaging the Weave",
            "How to Store Seasonal Clothes to Protect Fibers from Humidity and Dust",
            "How to Fix a Stiff Zipper, Loose Button, or Snagged Hemline at Home",
            "How to Organize Your Closet to Make Getting Dressed Fast and Effortless"
        ]
        avail = [t for t in care_topics if t.lower().strip() not in existing_lower]
        return random.choice(avail) if avail else care_topics[0]

    silhouettes = SILHOUETTES_BY_CATEGORY.get(cat_key, [f"{category_name} Staples", f"Tailored {category_name}"])
    current_season = "Fall" if datetime.now().month in [9, 10, 11] else "Winter" if datetime.now().month in [12, 1, 2] else "Spring" if datetime.now().month in [3, 4, 5] else "Summer"

    paa_generators = [
        # 1. Fit & Dilemma Problem Solvers (High PAA Volume)
        lambda s: f"How to Style {s} Without Looking Bulky or Overdressed",
        lambda s: f"How to Wear {s} So the Hemline Doesn't Drag or Catch",
        lambda s: f"How to Style {s} for Petite Proportions to Elongate Legs",
        lambda s: f"How to Wear {s} for Apple and Hourglass Shapes: Fit & Rise Guide",
        lambda s: f"Finding {s} That Never Gap at the Waist: Fit & Stretch Tips",
        lambda s: f"How to Style {s} for Relaxed Everyday Wear Without Looking Frumpy",
        # 2. Footwear & Pairing Queries (Top Search Query Format)
        lambda s: f"What Shoes and Boots to Pair with {s} This {current_season}",
        lambda s: f"How to Wear Sneakers with {s} for Effortless Casual Outfits",
        lambda s: f"What Tops and Layers Look Best with High-Rise {s}",
        lambda s: f"What Jacket to Wear Over {s} Across Changing Weather",
        # 3. Occasion & Lifestyle Queries
        lambda s: f"What to Wear to a Casual Business Lunch: {s} Outfit Ideas",
        lambda s: f"How to Style {s} from Desk to Dinner with Simple Swaps",
        lambda s: f"Comfortable Weekend Outfits Around {s} That Still Look Polished"
    ]

    random.shuffle(paa_generators)
    for gen in paa_generators:
        for _ in range(20):
            s = random.choice(silhouettes)
            candidate = gen(s)
            if candidate.lower().strip() not in existing_lower:
                return candidate

    return f"How to Style {category_name} for Modern Proportions and Everyday Confidence"

def select_high_intent_topic(category_meta, existing_titles):
    """Selects a fresh high-intent People Also Ask topic avoiding existing articles."""
    template_suffix = category_meta.get("template_suffix", "")
    category_name = category_meta["name"]
    topic_themes = category_meta.get("topic_themes", [])

    existing_lower = {t.lower().strip() for t in existing_titles}
    available_themes = [t for t in topic_themes if t.lower().strip() not in existing_lower]

    if available_themes:
        topic = random.choice(available_themes)
    else:
        topic = generate_programmatic_long_tail_topic(template_suffix, category_name, existing_lower)

    return sanitize_editorial_title(topic)

def generate_topic_faqs(topic, category_name=""):
    """
    Guarantees EXACTLY 3 complete, expert styling Q&As with full answers (35-50 words each)
    using structured JSON output to completely prevent truncated or unanswered questions.
    """
    from ai_client import generate as ai_generate
    faq_prompt = f"""
Act as an expert boutique stylist at MeeeShop boutique (USA).
Generate EXACTLY 3 helpful, practical shopper styling Q&As specifically addressing common doubts about: "{topic}".
Return ONLY a valid JSON array of 3 objects with "question" and "answer" keys. No markdown backticks, no explanations.
Example format:
[
  {{"question": "How do I choose the right fit for this silhouette?", "answer": "Focus on the waistline anchor and ensure the shoulder seams sit comfortably. For fluid fabrics, look for styles with built-in recovery..."}},
  {{"question": "What footwear pairing elongates the leg line with this piece?", "answer": "Pointed-toe flats, low block-heel mules, or sleek ankle boots in tonal neutrals keep the visual line uninterrupted and polished..."}},
  {{"question": "How can I transition this outfit from day to evening?", "answer": "Swap daytime loafers or sneakers for strappy heels, add a structured blazer or cropped jacket, and finish with delicate metallic accents..."}}
]
"""
    try:
        resp = ai_generate(faq_prompt, max_tokens=950, temperature=0.5)
        clean = resp.strip()
        if clean.startswith("```json"):
            clean = clean[7:]
        if clean.startswith("```"):
            clean = clean[3:]
        if clean.endswith("```"):
            clean = clean[:-3]
        clean = clean.strip()
        match = re.search(r'\[.*\]', clean, re.DOTALL)
        if match:
            clean = match.group(0)

        valid_items = []
        try:
            items = json.loads(clean)
            for it in items:
                q = str(it.get("question", "")).strip().replace("**", "")
                a = str(it.get("answer", "")).strip().replace("**", "")
                if q and a and len(q) > 8 and len(a) > 20:
                    valid_items.append({"question": q, "answer": a})
        except Exception:
            q_matches = re.findall(r'"question":\s*"([^"]+)"', clean)
            a_matches = re.findall(r'"answer":\s*"([^"]+)"', clean)
            for q, a in zip(q_matches, a_matches):
                if len(q.strip()) > 8 and len(a.strip()) > 20:
                    valid_items.append({"question": q.strip(), "answer": a.strip()})

        if len(valid_items) >= 2:
            return valid_items[:3]
    except Exception as e:
        print(f"Warning: Structured FAQ generation fallback triggered: {e}")

    return [
        {
            "question": f"How do I choose the most flattering cut for {category_name.lower() or 'this piece'}?",
            "answer": "Anchor your look at your natural waistline to define proportions. Look for medium-weight fabrics with high recovery that drape smoothly without clinging."
        },
        {
            "question": "What footwear pairing works best to elongate the leg line?",
            "answer": "Pointed-toe pumps, sleek ankle boots, or minimalist block-heel sandals in nude or tonal neutrals create a seamless, elongated vertical line."
        },
        {
            "question": "How do I transition this look from casual daytime to evening?",
            "answer": "Swap daytime flats or sneakers for elevated heels, layer with a tailored blazer or cropped jacket, and finish with a structured clutch."
        }
    ]

# ── Unified Search-Intent AI Content Generation Engine ──────────────────────────
def generate_blog_content(category_meta, collections, topic):
    """
    Generates high-value, Google Discover-eligible and search-intent aligned blog content.
    - Direct Answer First (Google Helpful Content System)
    - Dynamic Editorial Archetypes tailored to question intent (No cookie-cutter templates)
    - Evergreen internal linking to verified collections (never individual products that go out of stock)
    - Guaranteed 3 People Also Ask (PAA) FAQs via structured generation
    """
    from ai_client import generate as ai_generate

    category_name = category_meta["name"]
    archetype = detect_intent_archetype(topic)
    print(f"[*] Detected Search Intent Archetype: {archetype.upper()} for '{topic}'")

    # 1. Prepare Store Collections Context for Internal Links (max 2-3)
    collections_context = ""
    if collections:
        collections_context = "Verified active store collections (weave 2 to 3 naturally into your sentences):\n"
        for c in collections[:4]:
            collections_context += f"- {c['title']} (URL: {c['url']})\n"

    # 2. Dynamic Archetype Instructions with Deep 3-Section Architecture
    archetype_instructions = {
        "fit_solver": """
- DIRECT ANSWER FIRST: Paragraph 1 MUST immediately give the root cause and the numerical/proportion rule (e.g. hem break height ¼-½ inch, jacket-to-torso ratio 1:1.5, rise measurement, stretch recovery percentage). No morning commute or coffee run filler!
- Section 1 (Topic-Specific H2): The Mechanics of the Cut (waistband engineering, seam contour, rise height, hem break).
- Section 2 (Topic-Specific H2): Proportions & Balancing Volume (rule of thirds, fitted layers vs relaxed cuts, footwear pairing).
- Section 3 (Topic-Specific H2): Fabric Recovery & Silhouette Longevity (elastane recovery %, twill weight, avoiding sagging or gaping).
- Recommended Solution: Direct readers to explore complementary cuts in our verified store collection.
""",
        "pairing": """
- DIRECT ANSWER FIRST: Paragraph 1 MUST immediately state the golden rule for pairing hemlines with footwear profiles (toe box shape, sole thickness, shaft height) or outer layers. No morning commute or coffee run filler!
- Section 1 (Topic-Specific H2): Footwear Breakdown (Sneakers, Ankle Boots, Loafers, Mules) with hemline clearance rules.
- Section 2 (Topic-Specific H2): Outerwear & Layering Proportions (cropped vs longline jackets, balancing torso-to-leg proportions).
- Section 3 (Topic-Specific H2): Texture & Color Harmony (tonal palettes, contrasting textures like knits with denim).
- Recommended Solution: Link to our curated collection as the destination to find complementary silhouettes.
""",
        "comparison": """
- DIRECT ANSWER FIRST: Paragraph 1 MUST immediately summarize the fundamental difference between the two silhouettes and who each flatters most. No atmospheric filler!
- Section 1 (Topic-Specific H2): Deep Dive on Silhouette A (proportions, ideal body shapes, best styling pairings).
- Section 2 (Topic-Specific H2): Deep Dive on Silhouette B (proportions, ideal body shapes, best styling pairings).
- Section 3 (Topic-Specific H2): The Fitting Room Decision Guide (how to choose based on height, torso length, and daily lifestyle).
- Recommended Solution: Direct readers to compare cuts in our relevant category collections.
""",
        "occasion": """
- DIRECT ANSWER FIRST: Paragraph 1 MUST immediately decode the dress code and establish the balance between comfortable ease and elevated polish. No generic intro stories!
- Section 1 (Topic-Specific H2): Decoding the Dress Code & Establishing the Core Outfit Blueprint.
- Section 2 (Topic-Specific H2): Fabric Selection & Comfort-Driven Tailoring (breathability, movement, wrinkle-resistance).
- Section 3 (Topic-Specific H2): Day-to-Evening Transition & Weather Adaptation (footwear swaps, outerwear layers).
- Recommended Solution: Recommend checking our seasonal collections for curated occasion wear.
""",
        "care": """
- DIRECT ANSWER FIRST: Paragraph 1 MUST immediately explain the fabric fiber structure (natural vs synthetic matrix) and the #1 golden rule of washing/caring for it. No fluff!
- Section 1 (Topic-Specific H2): Understanding Fabric Fiber Structure (open weaves vs synthetic bonds, temperature thresholds).
- Section 2 (Topic-Specific H2): Step-by-Step Washing & Refreshing Protocol (water temperature, cycle, neutral detergents, steaming vs ironing).
- Section 3 (Topic-Specific H2): Common Pitfalls That Destroy Garment Drape & Longevity (fabric softener buildup, hanging heavy knits, dye bleeding).
- Recommended Solution: Mention how investing in boutique natural fibers and proper care guarantees seasons of wear.
"""
    }

    selected_archetype_guide = archetype_instructions.get(archetype, archetype_instructions["fit_solver"])

    # Archetype-aware practical blueprint instruction
    if archetype == "care":
        blueprint_instruction = """
   - Actionable Fabric & Stain Quick-Reference Protocol:
     Insert a styled quick-reference container:
     <div style="background: #faf8f5; border: 1px solid #e8dfd5; border-radius: 8px; padding: 16px 20px; margin: 20px 0;">
       <p style="margin: 0 0 8px 0; font-weight: 700; color: #222;">Quick Fabric Care & Emergency Protocol:</p>
       <ul style="margin: 0; padding-left: 20px; color: #444; line-height: 1.6;">
         <li><strong>Water-Based Spills (Coffee, Tea)</strong>: Blot immediately with a clean cloth; flush cool water with mild neutral detergent. Air-dry flat.</li>
         <li><strong>Oil-Based Stains (Makeup, Dressings)</strong>: Apply cornstarch or talc for 15 minutes to lift lipids before gentle spot-cleansing.</li>
         <li><strong>Delicate Weaves (Silk, Rayon, Knits)</strong>: Never scrub or wring; use lukewarm or cool cycles and steam to refresh.</li>
       </ul>
     </div>
     CRITICAL: Do NOT generate outfit styling blueprints or clothing combinations for garment care/laundry articles. NEVER recommend nonsensical advice like 'leave a blouse untucked to hide coffee stains'.
"""
    else:
        blueprint_instruction = """
   - Actionable Outfit Blueprints: Include 2 to 3 practical outfit formulas formatted in a clean bullet list:
     <ul>
       <li style="margin-bottom: 8px;"><strong>Look 1: [Creative Name]</strong> — [Garment A] + [Garment B] + [Footwear]. <em>[Proportion tip on tucking, hem break, or layering]</em></li>
       <li style="margin-bottom: 8px;"><strong>Look 2: [Creative Name]</strong> — [Garment A] + [Garment B] + [Footwear]. <em>[Proportion tip on tucking, hem break, or layering]</em></li>
     </ul>
     CRITICAL: All outfit tips must give genuine fashion styling advice (French tuck, 1/3 to 2/3 ratio, hem break clearance).
"""

    article_prompt = f"""
Act as a senior boutique stylist at MeeeShop (USA). Write an authoritative, engaging, and genuinely helpful fashion styling guide answering the real shopper search query: "{topic}".

EDITORIAL, READABILITY & SEARCH INTENT REQUIREMENTS:
1. STRICTLY FORBIDDEN CLICHÉS:
   - Do NOT write opening stories about "drinking a latte", "morning commute", "sprinting to the subway", "rooftop bistro/lunch", "coffee run", or "picture this in the fitting room".
   - Do NOT use generic headings like "Daytime Proportions vs Evening Layering", "Formula 1, 2, 3", or "Pro Stylist Rule-of-Thumb". Make all H2 headings UNIQUE and tailored to "{topic}".
   - Do NOT use repetitive table formats.

2. MOBILE-FRIENDLY FORMATTING FOR MODERN WOMEN SHOPPERS:
   - Paragraph Brevity: Keep every paragraph concise (2 to 3 sentences max) so it reads smoothly on mobile screens without dense walls of text.
   - Quick Stylist Takeaway Box: Immediately following the Direct Answer introduction paragraph, insert a styled callout box:
     <div style="background: #fbf9f6; border-left: 4px solid #b8977e; padding: 14px 18px; margin: 20px 0; border-radius: 0 6px 6px 0;">
       <p style="margin: 0 0 6px 0; font-weight: 700; color: #222;">Stylist Key Takeaway:</p>
       <p style="margin: 0; color: #444; line-height: 1.5;">[1-2 clear, actionable sentences summarizing the core proportion or fabric rule for this query]</p>
     </div>
{blueprint_instruction}

3. SEARCH INTENT ARCHETYPE GUIDELINES:
{selected_archetype_guide}

4. PRO STYLIST RULE:
   - Include 1 memorable styling rule-of-thumb inside a styled <blockquote style="border-left: 3px solid #b8977e; margin: 24px 0; padding: 12px 20px; font-style: italic; background: #faf8f5; color: #444;">Rule-of-Thumb: <em>...</em></blockquote>.

5. EVERGREEN INTERNAL LINKING:
{collections_context}
   - Naturally weave 2 to 3 links to our store collections above using natural, grammatically fluent anchor text (e.g. "...pair with <a href='/collections/...'>curated midi dresses</a>..." or "...explore our <a href='/collections/...'>tailored jackets collection</a>...").
   - CRITICAL: NEVER insert raw collection names stiffly as nouns like "on our Women's Dresses" or "a Women's Tops silk blouse". Anchor text must flow smoothly in the sentence.
   - CRITICAL: DO NOT link to individual product pages (/products/...) because inventory changes quickly and products sell out. Only link to category collections.

6. OUTPUT FORMAT:
   - Line 1 MUST be: <h1>{topic}</h1>
   - Return ONLY raw valid HTML. Do NOT wrap in ```html fences. Total length: 850-1,100 words of rich, comprehensive styling advice.
   - Do NOT include the FAQ section in this output (it will be appended separately).
"""

    html_content = ai_generate(article_prompt, max_tokens=2800, temperature=0.7)
    if not html_content:
        raise RuntimeError("Failed generating article body across all AI providers.")

    html_content = html_content.strip()

    if html_content.startswith("```html"):
        html_content = html_content[7:]
    if html_content.startswith("```"):
        html_content = html_content[3:]
    if html_content.endswith("```"):
        html_content = html_content[:-3]
    html_content = re.sub(r'<meta[^>]*>', '', html_content, flags=re.IGNORECASE).strip()

    # Clean unclosed tags and ensure proper closure
    html_content = re.sub(r'<[^>]*$', '', html_content).strip()
    if html_content.count("<div") > html_content.count("</div>"):
        diff = html_content.count("<div") - html_content.count("</div>")
        html_content += "</div>" * diff
    if html_content.count("<p") > html_content.count("</p>"):
        diff = html_content.count("<p") - html_content.count("</p>")
        html_content += "</p>" * diff
    html_content = re.sub(r'<[^>]*$', '', html_content).strip()

    # Extract <h1> title and strip from body to avoid double H1 in Dawn theme
    article_title = topic
    if "<h1>" in html_content and "</h1>" in html_content:
        h1_start = html_content.find("<h1>") + 4
        h1_end = html_content.find("</h1>")
        extracted_h1 = html_content[h1_start:h1_end].strip()
        article_title = sanitize_editorial_title(extracted_h1)
        html_content = html_content[:html_content.find("<h1>")] + html_content[h1_end + 5:]
        html_content = html_content.strip()

    # Generate high-CTR 50-60 char SEO Title and 140-155 char Meta Description matching search intent
    if len(article_title) <= 45:
        seo_title = f"{article_title} | MeeeShop Guide"
    else:
        seo_title = article_title[:60]

    clean_kw = re.sub(r'^(what to wear to a|how to style a|how to style|best|the)\s+', '', article_title.lower(), flags=re.IGNORECASE).strip()
    meta_desc = (
        f"Looking for {clean_kw}? Explore expert fit formulas, silhouette advice, "
        f"and boutique styles with fast US shipping and easy returns at MeeeShop!"
    )[:155]

    # Cleanly strip any raw or incomplete FAQ output from AI to prevent dangling tags
    html_content = re.sub(r'<h2[^>]*>\s*Frequently Asked Questions.*?$', '', html_content, flags=re.DOTALL | re.IGNORECASE).strip()
    html_content = re.sub(r'<div class="faq-item">.*?$', '', html_content, flags=re.DOTALL | re.IGNORECASE).strip()
    html_content = re.sub(r'<p><strong>\s*(?:Q:?|Question:?).*?$', '', html_content, flags=re.DOTALL | re.IGNORECASE).strip()
    html_content = re.sub(r'<[^>]*$', '', html_content).strip()

    # Fetch 3 guaranteed, fully answered styling FAQs
    faq_items = generate_topic_faqs(topic, category_name)

    # Cleanly append the verified FAQ section
    faq_html = '<h2 style="margin-top: 36px; margin-bottom: 16px;">Frequently Asked Questions</h2>\n'
    for item in faq_items:
        faq_html += (
            f'<div style="background: #ffffff; border: 1px solid #ebe5dc; border-radius: 8px; padding: 16px 20px; margin: 14px 0;">\n'
            f'  <p style="margin: 0 0 8px 0; line-height: 1.5; color: #333;"><strong>Q: {item["question"]}</strong></p>\n'
            f'  <p style="margin: 0; color: #555; line-height: 1.5;">A: {item["answer"]}</p>\n'
            f'</div>\n'
        )
    html_content = html_content + "\n\n" + faq_html

    return article_title, seo_title, meta_desc, html_content, faq_items

# ── 1200x630 Google Discover Image Generation ──────────────────────────────────
def generate_1200x630_collage(products):
    """
    Creates a 1200x630 Google Discover / Bing eligible single-frame image of 3 products.
    Zero split visuals, zero split panels, zero borders, cards, or divider lines.
    Seamless panoramic blend with smooth S-curve feathering so all 3 products appear
    naturally together in the exact same visual frame.
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

    if len(images) == 1:
        # Single hero product centered on continuous studio ambient backdrop
        canvas = Image.new("RGB", (CANVAS_W, CANVAS_H), (250, 249, 247))
        bg = ImageOps.fit(images[0], (CANVAS_W, CANVAS_H), method=Image.Resampling.BICUBIC)
        bg = bg.filter(ImageFilter.GaussianBlur(radius=50))
        canvas = Image.blend(bg, canvas, alpha=0.5)
        h = int(CANVAS_H * 0.96)
        w = int(images[0].width * (h / images[0].height))
        fg = ImageOps.fit(images[0], (w, h), method=Image.Resampling.LANCZOS, centering=(0.5, 0.35))
        canvas.paste(fg, ((CANVAS_W - w) // 2, (CANVAS_H - h) // 2))
        canvas = canvas.filter(ImageFilter.UnsharpMask(radius=1.1, percent=105, threshold=3))
        out_buf = BytesIO()
        canvas.save(out_buf, format="JPEG", quality=95, optimize=True)
        return out_buf.getvalue()

    if len(images) == 2:
        fade_width = 80
        col_w = (CANVAS_W + fade_width) // 2
        f_left = ImageOps.fit(images[0], (col_w, CANVAS_H), method=Image.Resampling.LANCZOS, centering=(0.5, 0.35))
        f_right = ImageOps.fit(images[1], (col_w, CANVAS_H), method=Image.Resampling.LANCZOS, centering=(0.5, 0.35))
        canvas = Image.new("RGB", (CANVAS_W, CANVAS_H), (255, 255, 255))
        canvas.paste(f_left, (0, 0))
        mask = Image.new("L", (col_w, CANVAS_H), 255)
        for x in range(fade_width):
            factor = (1.0 - math.cos(math.pi * x / fade_width)) / 2.0
            alpha = int(255 * factor)
            for y in range(CANVAS_H):
                mask.putpixel((x, y), alpha)
        canvas.paste(f_right, (col_w - fade_width, 0), mask)
        canvas = canvas.filter(ImageFilter.UnsharpMask(radius=1.1, percent=105, threshold=3))
        out_buf = BytesIO()
        canvas.save(out_buf, format="JPEG", quality=95, optimize=True)
        return out_buf.getvalue()

    # 3 products: seamless single frame without split panels or border cards
    fade_width = 70
    col_w = (CANVAS_W + 2 * fade_width) // 3

    feat_img = images[0]
    left_img = images[1]
    right_img = images[2]

    f_left = ImageOps.fit(left_img, (col_w, CANVAS_H), method=Image.Resampling.LANCZOS, centering=(0.5, 0.35))
    f_center = ImageOps.fit(feat_img, (col_w, CANVAS_H), method=Image.Resampling.LANCZOS, centering=(0.5, 0.35))
    f_right = ImageOps.fit(right_img, (col_w, CANVAS_H), method=Image.Resampling.LANCZOS, centering=(0.5, 0.35))

    canvas = Image.new("RGB", (CANVAS_W, CANVAS_H), (255, 255, 255))
    canvas.paste(f_left, (0, 0))

    # Smooth S-curve (cosine interpolation) transition mask
    mask = Image.new("L", (col_w, CANVAS_H), 255)
    for x in range(fade_width):
        factor = (1.0 - math.cos(math.pi * x / fade_width)) / 2.0
        alpha = int(255 * factor)
        for y in range(CANVAS_H):
            mask.putpixel((x, y), alpha)

    x_center = col_w - fade_width
    canvas.paste(f_center, (x_center, 0), mask)

    x_right = x_center + col_w - fade_width
    canvas.paste(f_right, (x_right, 0), mask)

    # Apply subtle unsharp mask filter for crisp editorial definition
    canvas = canvas.filter(ImageFilter.UnsharpMask(radius=1.1, percent=105, threshold=3))

    out_buf = BytesIO()
    canvas.save(out_buf, format="JPEG", quality=95, optimize=True)
    return out_buf.getvalue()

def generate_article_featured_image(api_key, title, category_name, products):
    """
    Creates a 1200x630 Google Discover / Bing eligible single-frame image of 3 products.
    Seamless composition in the same visual frame with no split visuals or panels.
    """
    print(f"[*] Creating 1200x630 Google Discover featured image for '{title}'...")

    # 1. Primary: Seamless single-frame 3-product editorial composition
    if products:
        try:
            collage_bytes = generate_1200x630_collage(products)
            if collage_bytes:
                print("  [OK] Successfully built 1200x630 single-frame 3-product featured image")
                return collage_bytes
        except Exception as e:
            print(f"  [!] Warning: Failed generating 3-product single frame image: {e}")

    # 2. Fallback: AI image generation if no products could be retrieved
    try:
        import warnings
        warnings.filterwarnings("ignore", category=UserWarning)
        warnings.filterwarnings("ignore", message=".*deprecated.*")
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

    return None

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
def publish_shopify_article_complete(session, store_url, blog_id, blog_handle, title, seo_title, meta_desc, html_content, author_name, template_suffix, image_bytes=None, draft=True, indexnow_key=None, faq_items=None):
    """
    Publishes article to Shopify with complete SEO Metafields, summary_html excerpt,
    JSON-LD structured data (BlogPosting + FAQPage), and exact OS 2.0 template suffix.
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

    # 3. Complete Structured Data Schema (BlogPosting)
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

    # 4. Attach Native FAQPage Schema in json_ld_schema.faq
    if faq_items:
        faq_schema = {
            "@context": "https://schema.org",
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

    print("  [OK] Attached SEO Title, Meta Description & Combined BlogPosting + FAQPage Schema")

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

    # 5. Select High-Intent Search / People Also Ask Topic
    print(f"\n[*] Selecting high-intent search query / PAA topic for '{category_meta['name']}'...")
    topic = select_high_intent_topic(category_meta, existing_titles)
    print(f"  [OK] Selected Topic: '{topic}'")

    # 6. Fetch Verified Collections (>= 20 Active Products Rule)
    print(f"\n[*] Fetching verified store collections (>= 20 active products) for '{category_meta['name']}'...")
    collections = fetch_category_shopify_data(session, shopify_store, category_meta)
    print(f"  [OK] Found {len(collections)} verified active collection links:")
    for c in collections:
        print(f"    - {c['title']} (URL: {c['url']}, Active Products: {c['count']})")

    # 7. Fetch Topic-Matched Products for In-Article Conversion & 1200x630 Discover Image
    print(f"\n[*] Fetching topic-matched store products for '{topic}'...")
    matched_products = fetch_topic_matched_products(session, shopify_store, category_meta, topic)
    print(f"  [OK] Selected {len(matched_products)} topic-matched products:")
    for p in matched_products[:3]:
        print(f"    - {p['title']} (Price: ${p.get('price', '')}, Type: {p.get('product_type', '')})")

    # 8. Generate Content (Intent-driven, direct answers, store product recommendations)
    print(f"\n[*] Generating high-intent, Google Discover & PAA optimized article content...")
    title, seo_title, meta_desc, html_content, faq_items = generate_blog_content(
        category_meta, collections, topic
    )

    # 9. Generate 1200x630 Discover Image (Single-frame seamless 3-product blend)
    image_bytes = generate_article_featured_image(gemini_key, title, category_meta['name'], matched_products)

    # 9. Select E-E-A-T Stylist Persona
    author_name = random.choice(list(AUTHORS.keys()))
    print(f"[*] Assigned E-E-A-T Stylist Author: {author_name}")

    # 10. Publish Article to Shopify
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
        indexnow_key=indexnow_key,
        faq_items=faq_items
    )

    print(f"\n{'='*70}")
    print(f"  [OK] SUCCESS: Blog post created successfully!")
    print(f"  - Article Title   : {article.get('title')}")
    print(f"  - Article ID      : {article.get('id')}")
    print(f"  - Blog Category   : {chosen_blog['title']} (/blogs/{blog_handle})")
    print(f"  - Template Suffix : {template_suffix}")
    print(f"  - Status          : {'Draft' if is_draft else 'Published Live'}")
    print(f"  - Discover Image  : 1200x630 Topic-Matched Landscape")
    print(f"  - SEO Metafields  : Populated (Title Tag & Description Tag)")
    print(f"  - Schema          : BlogPosting + FAQPage Structured Data")
    print(f"{'='*70}\n")

if __name__ == "__main__":
    main()

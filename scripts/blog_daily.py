#!/usr/bin/env python3
"""
blog_daily.py — Google Discover-ready blog automation for MeeeShop
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Google Discover + SEO requirements:
  - Featured image: 1200px wide, descriptive keyword-rich ALT text
  - SEO title: 50-60 chars, keyword-first, set via Shopify metafield
  - Meta description: 140-155 chars, action-oriented, set via summary_html
  - Slug (handle): auto-generated from SEO title by Shopify
  - EEAT: first-person experience, expertise signals, trust indicators
  - 5 high-intent formats: buying guide, comparison, problem-solver,
    trend report, outfit formula
  - Popular keywords embedded naturally in H1, H2, body, ALT, meta

AI: Gemini 2.0 Flash -> Groq Llama-3.3-70B -> OpenRouter (multi-model free tier)
Image: Shopify product image resized to 1200x630 via CDN; Pollinations.ai fallback

Usage:
  python blog_daily.py              # create 1 post
  python blog_daily.py --dry-run    # print only, no Shopify publish
  python blog_daily.py --count 3    # create 3 posts
"""

import os, sys, re, time, random, argparse
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import requests
import ai_client
from PIL import Image, ImageOps

from utils import (
    generate_collage,
    extract_handle_count,
    is_product_compatible,
    select_styling_matches,
    get_category_style_phrase,
    sanitize_title_to_category_phrase
)

def generate_outfit_collage(main_product: dict, matching_products: list) -> Path | None:
    """
    Downloads featured images for main product and matching products,
    creates a 1200x630 Discover landscape collage with taller center featured image + white border,
    and saves locally using utils.generate_collage.
    """
    image_bytes_list = []
    main_imgs = main_product.get("images", [])
    if main_imgs:
        try:
            r = requests.get(main_imgs[0]["src"], timeout=10)
            if r.status_code == 200:
                image_bytes_list.append(r.content)
        except Exception as e:
            print(f"    [!] Error fetching main product image: {e}")

    for p in matching_products:
        imgs = p.get("images", [])
        if imgs:
            try:
                r = requests.get(imgs[0]["src"], timeout=10)
                if r.status_code == 200:
                    image_bytes_list.append(r.content)
            except Exception as e:
                print(f"    [!] Error fetching product image: {e}")

    if not image_bytes_list:
        return None

    try:
        collage_bytes = generate_collage(image_bytes_list)
        temp_path = Path("collage_temp.jpg")
        with open(temp_path, "wb") as f:
            f.write(collage_bytes)
        print(f"  ✓ Discover featured collage generated locally: {temp_path.absolute()}")
        return temp_path
    except Exception as e:
        print(f"  [!] Failed to generate image collage: {e}")
        return None
from io import BytesIO
import weekly_trend_blog as wtb
from internal_linker import LinkMap
from article_deduplicator import ArticleDeduplicator

# ── credentials ───────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from secrets_manager import inject_to_env, get_secret
inject_to_env()

SHOP    = get_secret("SHOPIFY_STORE")
TOKEN   = get_secret("SHOPIFY_ACCESS_TOKEN")
API_VER = "2024-10"
BASE    = f"https://{SHOP}/admin/api/{API_VER}"
HEADERS = {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}

if not TOKEN:
    sys.exit("ERROR: SHOPIFY_ACCESS_TOKEN not set.")

STORE_URL = get_secret("STORE_BASE_URL")

YEAR  = datetime.now().year
MONTH = datetime.now().strftime("%B %Y")

from eeat_constants import PEN_NAMES  # single source of truth for pen names

# ── Shopify helpers ────────────────────────────────────────────────────────────
def _req(method, url, **kw):
    for attempt in range(5):
        try:
            r = getattr(requests, method)(url, headers=HEADERS, timeout=30, **kw)
            if r.status_code == 429:
                wait = int(float(r.headers.get("Retry-After", 4)))
                time.sleep(wait)
                continue
            return r
        except requests.exceptions.ConnectionError:
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"{method.upper()} {url} failed after 5 attempts")


# ── Blog category routing ──────────────────────────────────────────────────────
CATEGORY_BLOG_MAP = {
    "dress":      ["dress", "style", "fashion", "journal"],
    "jean":       ["denim", "jean", "style", "fashion", "journal"],
    "top":        ["style", "fashion", "tops", "journal"],
    "blouse":     ["style", "fashion", "tops", "journal"],
    "skirt":      ["style", "fashion", "journal"],
    "pant":       ["style", "fashion", "journal"],
    "jacket":     ["outerwear", "style", "fashion", "journal"],
    "coat":       ["outerwear", "style", "fashion", "journal"],
    "sweater":    ["style", "fashion", "journal"],
    "cardigan":   ["style", "fashion", "journal"],
    "swimwear":   ["swim", "summer", "style", "fashion", "journal"],
    "activewear": ["active", "fitness", "style", "fashion", "journal"],
    "accessory":  ["accessories", "style", "fashion", "journal"],
}


def get_all_blogs() -> list:
    r = _req("get", f"{BASE}/blogs.json")
    r.raise_for_status()
    return r.json().get("blogs", [])


def get_or_create_blog(product_type: str, all_blogs: list, dry_run: bool = False) -> dict:
    ptype_lower = (product_type or "").lower()
    
    # 1. Direct target blog names mapping
    target_blog_title = None
    if "dress" in ptype_lower:
        target_blog_title = "dresses"
    elif any(x in ptype_lower for x in ["jean", "denim", "jort"]):
        target_blog_title = "jeans"
    elif any(x in ptype_lower for x in ["skirt", "skort"]):
        target_blog_title = "skirts"
    elif any(x in ptype_lower for x in ["pant", "legging", "short"]):
        target_blog_title = "pants"
    elif any(x in ptype_lower for x in ["top", "blouse", "shirt", "tee", "t-shirt", "tank"]):
        target_blog_title = "shirts & tops"
    elif any(x in ptype_lower for x in ["jacket", "coat", "outerwear", "blazer"]):
        target_blog_title = "coats & jackets"
    elif any(x in ptype_lower for x in ["sweater", "cardigan", "knit", "pullover"]):
        target_blog_title = "cardigans & sweaters"
        
    # 2. Try matching the targeted title
    if target_blog_title:
        for blog in all_blogs:
            title_lower = blog.get("title", "").lower()
            # Avoid matching Announcements or system blogs
            if "announcements" in title_lower or "tips" in title_lower:
                continue
            if target_blog_title in title_lower:
                return blog
                
    # 3. Fallback to "Women's Clothing" if available
    for blog in all_blogs:
        title_lower = blog.get("title", "").lower()
        if "women's clothing" in title_lower:
            return blog
            
    # 4. Fallback to any blog that is not a system blog
    non_system_blogs = [
        b for b in all_blogs 
        if "announcements" not in b.get("title", "").lower() and "tips" not in b.get("title", "").lower()
    ]
    if non_system_blogs:
        return non_system_blogs[0]
        
    if all_blogs:
        return all_blogs[0]
        
    if dry_run:
        return {"id": 0, "title": "MOCK Fallback Blog (Dry Run)"}
        
    # Create blog if none exist
    r = _req("post", f"{BASE}/blogs.json",
             json={"blog": {"title": "Women's Clothing"}})
    r.raise_for_status()
    new_blog = r.json()["blog"]
    all_blogs.append(new_blog)
    return new_blog


def fetch_products(limit=100) -> list:
    r = _req("get", f"{BASE}/products.json",
             params={"limit": limit, "fields": "id,title,handle,product_type,vendor,tags,variants,images,body_html"})
    r.raise_for_status()
    return r.json().get("products", [])


# ── SEO metadata generation ────────────────────────────────────────────────────
def parse_and_clean_seo_meta(raw_seo_text: str, keyword: str, product_title: str, ptype: str) -> dict:
    """
    Parse SEO title, meta description, and image ALT text from the extracted text block.
    Falls back to deterministic values if parsing fails or fields are missing.
    """
    seo_title = meta_desc = img_alt = ""

    if raw_seo_text:
        for line in raw_seo_text.splitlines():
            line = line.strip()
            if line.upper().startswith("SEO_TITLE:"):
                seo_title = line.split(":", 1)[1].strip().strip('"')
            elif line.upper().startswith("META_DESC:"):
                meta_desc = line.split(":", 1)[1].strip().strip('"')
            elif line.upper().startswith("IMG_ALT:"):
                img_alt = line.split(":", 1)[1].strip().strip('"')

    # Deterministic fallbacks — always valid even if AI fails
    if not seo_title or len(seo_title) > 70:
        seo_title = f"{keyword.title()} — MeeeShop {YEAR}"[:60]
    if not meta_desc or len(meta_desc) > 165:
        meta_desc = (
            f"Discover the best {ptype} for women in {YEAR}. "
            f"Shop {product_title} at MeeeShop — free US shipping on orders $50+, "
            f"easy 7-day returns, sizes XS–3X."
        )[:155]
    if not img_alt:
        img_alt = f"{product_title} — {ptype} for women, {YEAR} fashion guide at MeeeShop"

    return {
        "seo_title":  seo_title,
        "meta_desc":  meta_desc,
        "img_alt":    img_alt,
    }


def generate_fallback_blog_post(fmt: str, product: dict, keyword: str, title_hint: str, similar_products: list, matching_products: list) -> tuple[str, dict]:
    """
    Generates a high-quality, Discover-ready blog article and SEO metadata locally
    as a fallback when all AI API providers are rate-limited or down.
    """
    display_name = get_product_display_name(product)
    clean_ptype = get_clean_product_type(product)
    price = product["variants"][0]["price"] if product.get("variants") else "49"
    
    match1_name = get_product_display_name(matching_products[0]) if len(matching_products) > 0 else "a classic handbag"
    match2_name = get_product_display_name(matching_products[1]) if len(matching_products) > 1 else "complementary accessories"
    
    # Alt/Similar products for comparison format
    real_alts = [
        p for p in similar_products
        if p.get('handle') != product.get('handle') and p.get('images')
    ][:2]
    if len(real_alts) < 2:
        real_alts = [
            p for p in similar_products
            if p.get('handle') != product.get('handle')
        ][:2]
    alt1_display = get_product_display_name(real_alts[0]) if real_alts else "a similar style"
    alt1_price = real_alts[0]['variants'][0]['price'] if (real_alts and real_alts[0].get('variants')) else "49"
    alt2_display = get_product_display_name(real_alts[1]) if len(real_alts) > 1 else "another option"
    alt2_price = real_alts[1]['variants'][0]['price'] if (len(real_alts) > 1 and real_alts[1].get('variants')) else "49"

    # Templates
    templates = {
        "sizing_guide": f"""
<p>Finding the perfect fit online can be a daunting experience, especially when dealing with premium boutique styles. Today, we're doing a deep-dive sizing and fit analysis of the {display_name} to help you select your ideal size with absolute confidence.</p>
<h2>Understanding Sizing for this {clean_ptype}</h2>
<p>The {display_name} is designed to flatter a wide range of silhouettes. Fabricated with a curated blend of fibers, it provides comfortable wear while maintaining its structural integrity. In general, this piece runs true to standard US boutique sizing, offering size options from XS through 3X to accommodate diverse body proportions.</p>
<h2>Fit Review by Silhouette & Body Shape</h2>
<h3>Petite Styling and Fit Recommendations</h3>
<p>For individuals with shorter torsos or petite frames, the {display_name} sits beautifully. We recommend staying with your standard size. The hemline and shoulder proportions are tailored so they do not overwhelm smaller frames, creating an elongated and elegant silhouette.</p>
<h3>Hourglass Styling and Fit Recommendations</h3>
<p>If you possess an hourglass figure, this style highlights your natural waistline beautifully. The drape of the fabric follows your curves without feeling constrictive. If you are between sizes, we recommend choosing your smaller size for a more defined, tailored look.</p>
<h3>Plus Size & Curvy Styling Recommendations</h3>
<p>Available up to 3X, this style offers generous stretch and cut allowances around the bust and hips. Curvy styling tips suggest wearing it with simple, streamlined basics to let the silhouette of this {clean_ptype} stand out. The fabric does not cling, providing an exceptionally comfortable and confidence-boosting wear.</p>
<h2>Fabric Stretch and Draping Factor</h2>
<p>Understanding how the fabric responds to movement is key. This style features moderate stretch with excellent recovery, meaning it won't bag out after a long day of wear. The draping factor is high, allowing the garment to cascade naturally and respond smoothly to your natural stride.</p>
<h2>Stylist Sizing Recommendation</h2>
<p>Our final verdict: choose your typical US size for the intended boutique fit. If you prefer a loose, oversized fashion statement, you can safely size up. If you prefer a highly defined fit, size down.</p>
""",

        "outfit_formula": f"""
<p>The best pieces in your wardrobe are not the most expensive ones. They are the ones you can actually wear five different ways. The {display_name} is one of those pieces — and here is exactly how to make each look work.</p>
<h2>Look 1: The Sunday Farmers Market</h2>
<p>This is your zero-effort look that somehow still turns heads. Layer the {clean_ptype} with a relaxed linen overshirt in off-white left open, grab a woven market tote, and knot a thin braided belt at the waist if the fit calls for it. Pair with the {match1_name} for a cohesive colour story. It is the kind of outfit that photographs beautifully at the breakfast table.</p>
<h2>Look 2: The Power Lunch</h2>
<p>Structure is the answer here. Pull a camel or ivory blazer over this {clean_ptype} and tuck in the front half of your top for a polished proportion. Add small gold hoops and a structured shoulder bag in cognac. Layer the {match2_name} on top if the temperature calls for it — the layering here reads expensive without trying.</p>
<h2>Look 3: Date Night That Doesn't Look Like You Tried Too Hard</h2>
<p>The key to this look is texture contrast. Wear the {display_name} with a fluid silk-touch camisole tucked in, add a delicate chain necklace, and carry a small leather crossbody. The balance between relaxed and intentional is where the magic happens. Dark wash jeans or a monochrome colour story in deep navy or olive both work here.</p>
<h2>Look 4: Airport Chic</h2>
<p>Comfort and looking pulled-together are not mutually exclusive. Wear the {clean_ptype} with an oversized zip-up hoodie or knit cardigan in a neutral — oatmeal, charcoal, or dusty rose. Add a spacious canvas tote for carry-on essentials. This outfit works from security line to arrival hall without looking like you gave up.</p>
<h2>Look 5: The Gallery Hop</h2>
<p>Go monochromatic. Pair this {clean_ptype} with similar tones in your blazer and top — think all-black for summer {datetime.now().year}, or a sandy neutral layered look. Statement earrings and a half-tuck are the only two details this look needs. It is the quiet luxury formula that is all over Flipboard right now.</p>
""",

        "buying_guide": f"""
<p>Here is the honest truth about the {clean_ptype} question I get asked every single week: not every style that looks good in photos actually holds up in real life. Here is a breakdown of the {display_name} so you know exactly what you are buying before you click Add to Cart.</p>
<h2>What Actually Makes a Good {clean_ptype.title()}?</h2>
<ul>
  <li><strong>Fabric Weight:</strong> The fabric must feel substantial enough to drape cleanly, not cling or go sheer. Lightweight does not mean thin.</li>
  <li><strong>Seam Construction:</strong> Check that side seams lie flat. Twisted seams are a manufacturing shortcut that distorts the silhouette after washing.</li>
  <li><strong>Size Consistency:</strong> Quality brands size consistently across colourways. Inconsistency is a red flag for fabric quality control issues.</li>
  <li><strong>Recovery After Washing:</strong> A good {clean_ptype} bounces back to its original shape — it should not bag out at the hips or stretch at the neckline after one wash cycle.</li>
</ul>
<h2>Why the {display_name} Made Our Edit: The Honest Breakdown</h2>
<p>The cut on this one is worth paying attention to. It hits at the right point to balance the silhouette without adding visual weight in the wrong places. The fabric has enough body to hang cleanly, which is harder to find at this price point than most people realise. For a fuller figure, the seaming through the middle creates a defined line without being constricting. Petite frames will find the proportions cooperative — it does not overwhelm.</p>
<h2>3 Real-Life Outfit Recipes</h2>
<h3>The Power Lunch</h3>
<p>Pull a structured blazer in ivory or soft camel over this {clean_ptype}. Front-tuck the hem slightly to define the waist, add the {match1_name} for a layer of interest, and finish with a small leather shoulder bag in cognac. Simple gold earrings, nothing statement. This works for a client meeting or a first date at a nice restaurant.</p>
<h3>Saturday Gallery Hop</h3>
<p>Go tone-on-tone. Match this {clean_ptype} with the {match2_name} in a similar neutral palette — oatmeal, olive, or all black. Half-tuck the top, add a canvas crossbody, and one interesting accessory (a chunky ring, a silk scarf). This is the quiet luxury formula that is dominating Flipboard Style feeds in summer {datetime.now().year}.</p>
<h3>The Long Weekend</h3>
<p>Pack light but look intentional. Pair with an oversized linen button-down in white or sage left open as a layer, a market tote, and a braided belt at the waist. Works from the airport to the poolside dinner with zero effort.</p>
<h2>Who This Actually Works For (and Who Should Skip It)</h2>
<p>This {clean_ptype} works best for women who prefer a clean, unfussy silhouette. If you love heavy embellishment or very structured boning, this is not the piece. If your wardrobe skews minimal and you want something that layers well and photographs without fuss, add this to your cart.</p>
""",

        "comparison": f"""
<p>We receive frequent questions from our customers asking how the {display_name} compares to other popular styles in our boutique. In this editor's comparison, we evaluate the drape, fit, and styling value of three outstanding options to help you choose the winner for your wardrobe.</p>
<h2>Option 1: {display_name} — What We Love</h2>
<p>The {display_name} is celebrated for its tailored fit and soft-touch fabric blend. It offers excellent structured support while remaining lightweight. It is the perfect choice if you want a reliable, elegant staple that works for both casual and dressy events.</p>
<h2>Option 2: {alt1_display} — The Alternative Style</h2>
<p>The {alt1_display} is a fantastic choice for those seeking a more relaxed, bohemian aesthetic. Priced at ${alt1_price}, it features a slightly looser cut, making it ideal for warm weather wear or casual layering.</p>
<h2>Option 3: {alt2_display} — The Trend-Forward Option</h2>
<p>For a modern silhouette, the {alt2_display} (priced at ${alt2_price}) offers a structured cut. It provides a distinct style that stands out, making it a bold and fashionable statement piece.</p>
<h2>Style and Fit Comparison Table</h2>
<table style="width:100%; border-collapse:collapse; margin:20px 0; font-family:sans-serif; font-size:14px; text-align:left;">
  <thead>
    <tr style="background-color:#f2f2f2; border-bottom:2px solid #ddd;">
      <th style="padding:12px; border:1px solid #ddd;">Style</th>
      <th style="padding:12px; border:1px solid #ddd;">Best For</th>
      <th style="padding:12px; border:1px solid #ddd;">Price Range</th>
      <th style="padding:12px; border:1px solid #ddd;">Fabric Stretch</th>
    </tr>
  </thead>
  <tbody>
    <tr style="border-bottom:1px solid #ddd;">
      <td style="padding:12px; border:1px solid #ddd; font-weight:bold;">{display_name}</td>
      <td style="padding:12px; border:1px solid #ddd;">Everyday Elegance</td>
      <td style="padding:12px; border:1px solid #ddd;">${price}</td>
      <td style="padding:12px; border:1px solid #ddd;">Moderate</td>
    </tr>
    <tr style="border-bottom:1px solid #ddd;">
      <td style="padding:12px; border:1px solid #ddd; font-weight:bold;">{alt1_display}</td>
      <td style="padding:12px; border:1px solid #ddd;">Relaxed / Boho Chic</td>
      <td style="padding:12px; border:1px solid #ddd;">${alt1_price}</td>
      <td style="padding:12px; border:1px solid #ddd;">High</td>
    </tr>
    <tr style="border-bottom:1px solid #ddd;">
      <td style="padding:12px; border:1px solid #ddd; font-weight:bold;">{alt2_display}</td>
      <td style="padding:12px; border:1px solid #ddd;">Modern Statements</td>
      <td style="padding:12px; border:1px solid #ddd;">${alt2_price}</td>
      <td style="padding:12px; border:1px solid #ddd;">Structured / Low</td>
    </tr>
  </tbody>
</table>
<h2>Our Honest Verdict — The Winner for Most Women</h2>
<p>While all three options are beautiful, the {display_name} wins for its sheer versatility and premium quality. It bridges the gap between casual comfort and sophisticated styling, making it the most cost-effective and wearable investment for your capsule wardrobe.</p>
""",

        "problem_solver": f"""
<p>You have probably experienced this: you buy a {clean_ptype}, it looks brilliant in the first hour, and by 2pm it has lost its shape, clung in the wrong places, or just feels wrong. The problem is not you. It is a very solvable construction problem, and the {display_name} is designed around exactly that fix.</p>
<h2>Why It Keeps Happening (and It's Not Your Fault)</h2>
<p>Most affordable {clean_ptype}s cut corners on two things: seam placement and fabric recovery. Seams that are not properly graded to the body create pulling and bunching. Fabric without adequate recovery stretches out and never bounces back to its original shape. These are not style problems. They are engineering problems.</p>
<h2>The Fix: Why the {display_name} Solves This</h2>
<p>The construction here is noticeably different. The side seam placement follows the natural curve of the body rather than a straight manufacturing line, which eliminates the pulling effect. The fabric blend includes enough structure to hold the silhouette through a full day without bagging. This is a {clean_ptype} you can wear to a 9am meeting and still feel sharp at dinner.</p>
<h2>3 Outfit Recipes That Prove It</h2>
<h3>The Efficient Morning</h3>
<p>Pair this {clean_ptype} with a crisp white linen tee tucked in, a crossbody bag in tan, and the {match1_name} as your layering piece. This combination goes from school drop-off to a mid-morning coffee meeting without a single adjustment.</p>
<h3>The Polished Work Environment</h3>
<p>A structured blazer in charcoal or camel over this {clean_ptype} reads immediately professional. Add the {match2_name} and a simple belt to define the waistline. No ironing drama, no fit adjustments, no second-guessing.</p>
<h3>Weekend Brunch, Done Right</h3>
<p>A market tote, a lightweight knit cardigan in a warm neutral, and a simple straw hat. This is the Saturday morning formula that looks put-together without announcing that you planned it. The {clean_ptype} handles the work; you just add the layers.</p>
<h2>4 Styling Rules That Actually Change Things</h2>
<ul>
  <li>Always half-tuck rather than full-tuck if you are unsure about proportions — it reads more intentional.</li>
  <li>If a {clean_ptype} fits perfectly everywhere except the waist, a thin belt solves it in ten seconds.</li>
  <li>Dark over light for a slimmer optical effect. Light over dark for a more relaxed, casual silhouette.</li>
  <li>One layering piece is always better than two. Choose your statement — blazer OR cardigan, not both.</li>
</ul>
""",

        "trend_report": f"""
<p>If you have been paying attention to Flipboard, Who What Wear, and real women\'s street style this {MONTH}, you already know that the rules shifted. Wide-leg is not the only answer anymore. Distressed denim is out. And the all-black summer outfit is not just acceptable — it is the move. Here is what is actually trending right now.</p>
<h2>Trend #1: {display_name} — Why It Fits the {datetime.now().year} Moment</h2>
<p>The {display_name} is landing at exactly the right time. The {datetime.now().year} consumer is tired of trend-chasing and wants pieces that read intentional, not disposable. This {clean_ptype} fits that shift. Its construction is clean, its colour palette is edit-friendly, and it layers like a dream over the linen-and-denim combinations dominating summer style right now.</p>
<h2>Trend #2: Cigarette Jeans Are Taking Over</h2>
<p>The wide-leg denim moment had its run. The silhouette that is replacing it? The cigarette jean — slim, straight, hitting at the ankle. It works with tucked-in tops, cropped layers, and oversized blazers in a way that wide-leg simply cannot match. If you are buying one new denim item this season, this is the silhouette.</p>
<h2>Trend #3: The Quiet Luxury Denim Edit</h2>
<p>Dark indigo. No distressing. Clean hems. No branding. This is the {datetime.now().year} quiet luxury formula applied to denim, and it is trending hard on Flipboard #Style (8.4 million followers). The effect is simple: dark wash jeans read more expensive than light wash at any price point, because the colour is doing the visual work.</p>
<h2>Trend #4: The Linen + Dark Wash Formula</h2>
<p>This is the heat-proof summer answer. A relaxed linen top in white, ecru, or sage layered over or tucked into dark wash jeans — it is the combination that keeps appearing on every mood board right now. The contrast of textures does all the work. You do not need to add much else.</p>
<h2>Trend #5: The Blazer-as-a-Top Moment</h2>
<p>An oversized blazer — unstructured, in linen or a lightweight crepe — worn over a simple tank top is the office-to-evening formula of the season. The {match1_name} and {match2_name} both layer into this formula naturally. Monochrome or one-tone contrast works best.</p>
<h2>How to Mix Two Trends Without Looking Overdone</h2>
<p>Choose one focal piece and keep everything else quiet. If the {display_name} is your statement, keep your layering pieces in neutral tones. If you are going for the cigarette jean silhouette, the top should be simple — a clean linen shirt or a fitted ribbed knit. One trend at a time is always the sharper choice.</p>
""",

        "care_guide": f"""
<p>Keeping your clothing in pristine condition extends its life, preserves its rich colors, and maintains its original fit. Today, we outline the complete care and washing instructions for the {display_name}.</p>
<h2>Fabric Care Label Analysis</h2>
<p>The {display_name} features a high-grade blend of materials designed for style and comfort. Always consult the care label inside the garment before washing. Modern blends react best to cool temperatures to avoid fabric shrinking or fiber deterioration.</p>
<h2>Step-by-Step Washing Instructions</h2>
<h3>Machine Wash Instructions</h3>
<p>When machine washing, turn the {clean_ptype} inside out to protect the surface fibers. Wash on a gentle, delicate cycle using cold water and a mild, color-safe liquid detergent. Avoid washing with rough materials like zippers or heavy denims.</p>
<h3>Hand Washing Instructions</h3>
<p>For hand washing, submerge the garment in cold water mixed with a small amount of delicate detergent. Agitate gently by hand for a few minutes. Do not wring or twist the fabric; instead, press the water out gently against the basin.</p>
<h2>How to Dry and Iron Without Damage</h2>
<p>We highly recommend line drying or laying the {clean_ptype} flat on a clean towel to dry. If using a dryer, select the lowest heat/tumble setting to avoid heat damage. To remove wrinkles, steam styling is preferred over direct ironing.</p>
<h2>Stylist Care & Storage Tips</h2>
<p>Store your {display_name} folded neatly in drawers or hung on padded hangers depending on weight. Knitted styles should always be folded to prevent shoulder stretching, while woven fabrics hang beautifully.</p>
"""
    }

    # Select template body or default to care_guide
    template_body = templates.get(fmt, templates["care_guide"])

    # Q&A Block
    qa_section = f"""
<h2>Shoppers' Q&A: Common Questions Answered</h2>
<h3>Why should the {display_name} be in my closet?</h3>
<p>The {display_name} offers the perfect balance of comfort, premium quality, and timeless styling versatility. It is designed to fit seamlessly into any capsule wardrobe, making it easy to create multiple outfit formulas with pieces you already own.</p>
<h3>What is the fabric composition and how do I wash this style?</h3>
<p>This style is made from a durable, high-quality fabric blend selected for its soft drape and fit retention. To keep it looking pristine, we recommend washing inside out in cold water on a gentle cycle, then line drying or laying flat to dry.</p>
<h3>How do I choose the correct size for the {display_name}?</h3>
<p>This style runs true to standard US boutique sizing and is available in sizes XS to 3X. If you prefer a relaxed or slightly oversized layering fit, we recommend sizing up one size. For a more tailored look, stay true to your usual size.</p>
"""

    # Verdict & CTA Block
    cta_text = f"""
<h2>The Styling Verdict</h2>
<p>Overall, the {display_name} is a stellar fashion investment for {YEAR}. Priced at ${price}, it offers premium boutique construction at an accessible value. Shop yours at MeeeShop today—enjoy free US shipping on orders $50+, easy 7-day returns, and a full size range from XS to 3X.</p>
"""

    html_body = f"<h1>{title_hint}</h1>\n{template_body}\n{qa_section}\n{cta_text}"
    
    seo = {
        "seo_title": f"{title_hint[:60]} — MeeeShop",
        "meta_desc": f"Shop the {display_name} at MeeeShop. Free US shipping on orders $50+, easy 7-day returns, sizes XS–3X. Discover fit and styling tips.",
        "img_alt": f"{display_name} — {clean_ptype} for women, {YEAR} fashion guide at MeeeShop",
    }
    
    return html_body, seo


def set_article_seo_metafields(blog_id: int, article_id: int, seo_title: str, meta_desc: str):
    """
    Set SEO title and meta description via Shopify metafields.
    These map to the <title> tag and <meta name="description"> in Shopify themes.
    Namespace: global — keys: title_tag, description_tag (standard Shopify SEO metafields).
    """
    metafields = [
        {"namespace": "global", "key": "title_tag",       "value": seo_title, "type": "single_line_text_field"},
        {"namespace": "global", "key": "description_tag", "value": meta_desc, "type": "single_line_text_field"},
    ]
    for mf in metafields:
        r = _req("post",
                 f"{BASE}/blogs/{blog_id}/articles/{article_id}/metafields.json",
                 json={"metafield": mf})
        if r.status_code in (200, 201):
            print(f"  SEO metafield set: {mf['key']} = {mf['value'][:60]}")
        else:
            print(f"  SEO metafield FAILED ({mf['key']}): {r.status_code} {r.text[:100]}")


# ── Image helpers ──────────────────────────────────────────────────────────────
def make_featured_image_url(product: dict, fmt: str) -> str:
    """
    Shopify product image resized to 1200x630 via CDN.
    Google Discover requires minimum 1200px wide.
    """
    images = product.get("images", [])
    if not images:
        raise ValueError(f"Product '{product.get('title')}' has no images. Direct CDN images are required for Discover.")
    src = images[0]["src"]
    # Shopify CDN image transform: insert _1200x630_crop_center before extension
    src = re.sub(r'\.(jpg|jpeg|png|webp)(\?.*)?$',
                 r'_1200x630_crop_center.\1', src, flags=re.IGNORECASE)
    return src


def product_img_url(product: dict) -> str | None:
    images = product.get("images", [])
    return images[0]["src"] if images else None


# ── Product cards ──────────────────────────────────────────────────────────────
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


def make_related_products_section(products: list, exclude_handle: str, keyword: str = "", matching_products: list = None) -> str:
    import html
    
    if matching_products:
        picks = matching_products
        section_title = "Shop Styled Pairings from This Article"
        cta_text = "Shop the Look"
    else:
        outfit_count = extract_handle_count(keyword or exclude_handle or "")
        main_prod_candidates = [p for p in products if p.get("handle") == exclude_handle]
        main_product = main_prod_candidates[0] if main_prod_candidates else {"handle": exclude_handle, "product_type": keyword}
        picks = select_styling_matches(main_product, products, num_matches=outfit_count, topic_context=keyword or exclude_handle)
        section_title = "Shop Styled Pairings from This Article"
        cta_text = "Shop the Look"

    cards_html = ""
    for p in picks:
        raw_title  = p["title"]
        clean_title = clean_product_title(raw_title)
        escaped_title = html.escape(clean_title)
        price  = p["variants"][0]["price"] if p.get("variants") else "0"
        handle = p.get("handle", "")
        ptype  = (p.get("product_type") or "women's fashion").lower()
        url    = f"{STORE_URL}/products/{handle}?utm_source=blog&utm_medium=related_card&utm_campaign=meeeshop"
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


# ── Dynamic Collage & Pairing Helpers ──────────────────────────────────────────


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





def upload_image_to_shopify(filepath: Path, filename: str) -> str | None:
    """Uploads the generated collage to Shopify Files and fetches its CDN URL."""
    print(f"  Uploading {filename} to Shopify Files...")
    graphql_url = f"{BASE}/graphql.json"
    
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
        r = _req("post", graphql_url, json={"query": staged_mut})
        r.raise_for_status()
        data = r.json()
        target = data["data"]["stagedUploadsCreate"]["stagedTargets"][0]
        
        # Upload the file to staging
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
        r = _req("post", graphql_url, json={"query": create_mut, "variables": variables})
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
            r = _req("post", graphql_url, json={"query": query_file})
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


# ── Publish ────────────────────────────────────────────────────────────────────
def publish_article(blog: dict, title: str, body_html: str, tags: list,
                    image_url: str, img_alt: str, meta_desc: str,
                    dry_run: bool = False, publish: bool = False,
                    author: str = "Elena Vance, MeeeShop Lead Stylist") -> dict | None:
    if dry_run:
        print(f"  [DRY-RUN] '{title}'")
        print(f"  Blog   : {blog.get('title')}")
        print(f"  Image  : {image_url[:90]}")
        print(f"  ALT    : {img_alt}")
        print(f"  Meta   : {meta_desc[:100]}")
        print(f"  Preview: {re.sub(r'<[^>]+>',' ',body_html)[:160].strip()}…\n")
        return {"id": 0, "title": title}

    payload: dict = {
        "article": {
            "title":        title,
            "body_html":    body_html,
            "summary_html": f"<p>{meta_desc}</p>",
            "tags":         ", ".join(tags),
            "published":    publish,
            "author":       author,
        }
    }
    if image_url:
        payload["article"]["image"] = {
            "src": image_url,
            "alt": img_alt,
        }

    r = _req("post", f"{BASE}/blogs/{blog['id']}/articles.json", json=payload)
    if r.status_code in (200, 201):
        art = r.json().get("article", {})
        print(f"  Published: '{art.get('title')}' (ID {art.get('id')}) → blog '{blog['title']}'")
        return art
    print(f"  FAILED {r.status_code}: {r.text[:200]}")
    return None


# ── High-intent blog formats ───────────────────────────────────────────────────
FORMATS = ["buying_guide", "comparison", "problem_solver", "trend_report", "outfit_formula", "care_guide", "sizing_guide"]

SEED_KEYWORDS = [
    # Dynamic Trending — sourced from Flipboard #Style (8.4M followers) & Who What Wear
    f"women's fashion {datetime.now().year}", f"summer outfit ideas for women {datetime.now().year}",
    "affordable women's clothing USA", "summer dress outfits for women",
    "women's jeans styles guide", "casual chic outfits women",
    f"women's fashion trends {datetime.now().year}", "cute outfits under $50",
    "stylish women's tops", "best dresses for women",
    "women's summer wardrobe essentials", "affordable boutique fashion USA",
    "women's outfit ideas", "how to style women's clothing",
    "plus size fashion tips", "work outfits for women",
    "women's weekend casual looks", f"women's spring outfit ideas {datetime.now().year}",
    "best tops to wear with jeans", "how to build a capsule wardrobe women",
    "women's date night outfit ideas",
    "Zenana women's clothing basics guide", "how to style POL clothing bohemian pieces",
    "Emory Park boutique clothing outfits", "best Judy Blue jeans styles for women",
    "Risen stretch denim jeans review", "Umgee USA clothing styling ideas",
    "Hyfve clothing fashion trends", "Bibi clothing cute outfits",
    "Artemis Vintage denim styles",
    # Jeans-specific trending (Flipboard #Jeans 66K followers)
    f"how to style jeans {datetime.now().year}", "dark wash jeans outfits",
    "quiet luxury jeans women", "cigarette jeans styling tips",
    "barrel leg jeans vs wide leg jeans", "blazer with jeans outfit ideas",
    f"tops to wear with jeans {datetime.now().year}", "how to look taller in jeans",
    # Care & How-To (high search intent, Flipboard trending)
    "how to wash jeans without fading", "how to remove stains from jeans",
    "how to remove smell from clothes", "how to fix pilling on clothes",
    f"jeans care guide {datetime.now().year}",
    # Summer (Flipboard #SummerFashion 73.9K followers)
    "linen top with jeans outfit", f"summer denim outfit ideas {datetime.now().year}",
    "all black summer outfit women", f"women's capsule wardrobe {datetime.now().year}",
    f"linen dress summer {datetime.now().year}",
]


EEAT_RULES = (
    "EDITORIAL VOICE & E-E-A-T REQUIREMENTS (non-negotiable — Google trust signals + reader value):\n\n"

    "═══ OPENING HOOK (Critical for Google Discover CTR) ═══\n"
    "Open with a SPECIFIC, OPINIONATED hook that immediately validates the reader's real-world problem.\n"
    "✅ GOOD: 'The single-roll cuff is everywhere right now — and after testing every variation on dark wash, barrel leg, and cigarette jeans, here is exactly what actually works.'\n"
    "✅ GOOD: 'If your jeans still smell faintly musty after washing, you are not alone — and a second wash is rarely the answer.'\n"
    "❌ BAD: 'Jeans are a timeless wardrobe staple that women everywhere love.'\n"
    "❌ BAD: 'In today's world of fashion, finding the perfect pair of jeans can be challenging.'\n\n"

    "═══ VOICE & TONE ═══\n"
    "Write as a knowledgeable, trusted stylist friend — warm, direct, and specific. NOT a brand.\n"
    "• Use second person ('your jeans', 'your body') to keep the reader central.\n"
    "• Mix short punchy sentences with longer explanatory ones. Vary rhythm deliberately.\n"
    "• Be opinionated where it helps: 'Skip the wide-leg for petite frames — the volume will overwhelm.'\n"
    "• Acknowledge real trade-offs: 'Cigarette jeans are incredibly chic, but if you run curvy in the hip, size up and have them tailored at the waist.'\n\n"

    "═══ SPECIFIC RECOMMENDATIONS (Required — not vague) ═══\n"
    "All styling advice MUST name specific item categories with descriptors. MeeeShop sells clothing only — do NOT recommend specific shoes. Instead recommend clothing layers, tops, bags, belts, and jewelry with specific descriptors:\n"
    "✅ GOOD: 'A relaxed linen button-down in ecru — untucked, one button undone at the collar — hits differently over dark wash jeans.'\n"
    "✅ GOOD: 'A structured mini tote in chocolate brown or off-white anchors the quiet luxury aesthetic without trying too hard.'\n"
    "✅ GOOD: 'Layer a cropped blazer in camel or ivory over the top — it balances the proportions instantly.'\n"
    "❌ BAD: 'Pair with heels for a polished look.' (no shoe recs — MeeeShop doesn't sell shoes)\n"
    "❌ BAD: 'Accessorize to complete the outfit.' (too vague)\n"
    "❌ BAD: 'Add a bag to elevate the look.' (generic filler)\n\n"

    "═══ 2026 TREND CONTEXT (Weave in naturally — sourced from Flipboard #Style 8.4M followers) ═══\n"
    "Reference real trends where relevant but do NOT force every trend into every article:\n"
    "• Quiet luxury: 'No logos, no distressing — clean dark wash denim with a tucked-in linen shirt is the 2026 quiet luxury formula.'\n"
    "• Cigarette/stovepipe silhouette replacing wide-leg as dominant denim cut in 2026.\n"
    "• Dark indigo clean wash over distressed/light wash — reads more expensive instantly.\n"
    "• Linen top + dark wash jean = the heat-proof chic summer formula trending on Flipboard.\n"
    "• All-black outfits even in summer — trending on Flipboard #Style with 8.4M followers.\n"
    "• Oversized blazer over a simple tank + straight-leg jeans = the office-to-evening formula.\n\n"

    "═══ STRUCTURE & FORMAT ═══\n"
    "• Use H2 for major sections, H3 for sub-steps or occasions.\n"
    "• Include at least 1 blockquote styled as a 'Stylist Tip' with specific advice.\n"
    "• Use bullet lists for step-by-step instructions (care guides, how-tos).\n"
    "• For outfit formulas: name EACH look with a creative occasion title (e.g., 'Look 1: Sunday Farmers Market', not 'Casual Look').\n"
    "• Vary structure between articles — avoid formulaic repetition.\n\n"

    "═══ BANNED PHRASES (never use these) ═══\n"
    "elevate your look | effortlessly chic | perfect for any occasion | versatile wardrobe staple\n"
    "timeless classic | fashion-forward | look and feel your best | style game\n"
    "take your look to the next level | complete your outfit | fashion journey\n\n"

    "═══ TRUST SIGNALS ═══\n"
    "Include naturally (once, in CTA or intro): Free US shipping on orders $50+. Easy 7-day returns. Sizes XS–3X.\n\n"
)


def _lsi_keywords(ptype: str, keyword: str) -> list[str]:
    """Return LSI / secondary keywords relevant to this product type and primary keyword."""
    base_lsi = [
        "women's outfit ideas", "stylish women USA", "affordable fashion",
        "how to style", "women's clothing guide", "USA boutique fashion",
    ]
    ptype_lsi = {
        "dress":      ["summer dress outfits", "flattering dresses women", "dress styles guide",
                       "midi dress", "casual dress", "linen dresses 2026"],
        "jean":       ["jeans for women 2026", "best fitting jeans", "dark wash jeans outfits",
                       "high waist jeans", "women's denim guide", "cigarette jeans styling",
                       "quiet luxury denim", "barrel leg jeans", "linen top with jeans outfit",
                       "denim trends 2026"],
        "top":        ["tops for women", "blouse styles", "women's shirts", "work tops",
                       "casual tops women", "linen tops summer 2026"],
        "blouse":     ["blouse outfits", "women's blouse styles", "office blouse",
                       "flowy tops women", "summer blouse ideas"],
        "skirt":      ["skirt outfits women", "midi skirt", "mini skirt style",
                       "how to wear skirts", "asymmetric skirt 2026"],
        "pant":       ["women's pants guide", "trousers women", "wide leg pants",
                       "work pants women", "trouser trends 2026"],
        "jacket":     ["women's jacket outfits", "layering outfits", "blazer women",
                       "casual jacket", "blazer jeans combo 2026"],
        "coat":       ["women's coat styles", "winter coat", "trench coat women", "coat outfit ideas"],
        "sweater":    ["cozy sweater outfits", "women's knitwear", "sweater styles", "fall fashion women"],
        "cardigan":   ["cardigan outfits", "layering cardigan", "open front cardigan", "cozy fashion"],
        "swimwear":   ["swimsuit styles women", "bikini guide", "one piece swimsuit", "flattering swimwear"],
        "activewear": ["workout outfit women", "athleisure look", "gym clothes women", "active style"],
        "accessory":  ["women's accessories", "accessory guide", "how to accessorize", "fashion accessories"],
    }
    extras = []
    for k, v in ptype_lsi.items():
        if k in ptype:
            extras = v
            break
    combined = list(dict.fromkeys(extras + base_lsi))[:8]
    return combined


# ── Handle-aware content blueprint map (mirrors modify_blog.py) ────────────────
# Sourced from live Flipboard #Jeans, #Denim, #Style research + Who What Wear 2026 editorial.
HANDLE_CONTENT_RULES: dict[str, dict] = {
    "how-to-cuff":          {"topic": "how to cuff jeans",
                             "required_sections": ["Why Cuffing Works (proportion + ankle visibility + outfit balance)",
                                                   "The Single Roll Cuff", "The Double Roll Cuff",
                                                   "The Pin Roll Cuff",
                                                   "What Tops Work Best With Each Cuff Style (tuck in or crop?)",
                                                   "2026 Styling Tip: Cigarette Jeans + Cropped Linen Top — The Cuffed Look"],
                             "tone": "step-by-step how-to, practical"},
    "sizing-guide":         {"topic": "jeans sizing guide for women",
                             "required_sections": ["How to Measure Yourself for Jeans",
                                                   "US Jeans Size Chart",
                                                   "Fit Guide by Body Shape (petite, hourglass, curvy, tall)",
                                                   "High Waist vs Mid Rise vs Low Rise — Which Fits Best?",
                                                   "How to Choose Size XS–3X Online"],
                             "tone": "helpful, inclusive, size-positive"},
    "how-to-look-taller":   {"topic": "how to look taller with clothing",
                             "required_sections": ["The Leg-Lengthening Formula: Rise + Tuck-In Trick",
                                                   "High-Waisted Jeans and Why They Work",
                                                   "The Tuck-In Effect: How a Cropped or Tucked Top Creates Leg Length",
                                                   "Monochrome Dressing for Height Illusion",
                                                   "Vertical Stripes and Elongating Details on Tops",
                                                   "2026 Pro Tip: Cigarette Jeans + Fitted Ribbed Top = Longest-Looking Legs"],
                             "tone": "empowering, styling expert"},
    "how-to-pair":          {"topic": "how to pair jeans with outfits",
                             "required_sections": ["The Foundation: Choosing the Right Jeans Wash for the Vibe",
                                                   "Casual Formula: Linen Top + Dark Wash Jean + Crossbody Bag",
                                                   "Office Formula: Blazer + Fitted Top + Straight-Leg Jeans",
                                                   "Evening Formula: Silk Blouse + Cigarette Jeans + Statement Earrings",
                                                   "Weekend Formula: Oversized Tee + Barrel Leg + Tote Bag",
                                                   "The Quiet Luxury Jeans Look for 2026"],
                             "tone": "outfit formula, editorial"},
    "what-to-pair":         {"topic": "what to pair with jeans",
                             "required_sections": ["Tops That Always Work With Jeans (tuck-in vs untucked vs knotted)",
                                                   "Layering Pieces: Blazers, Cardigans, and Jackets That Elevate Denim",
                                                   "Accessories: Belts, Bags, and Jewelry That Complete the Look",
                                                   "The Top + Bottom Proportion Rule for Different Jeans Silhouettes",
                                                   "Complete Outfit Formulas for 5 Occasions"],
                             "tone": "practical, shoppable, style guide"},
    "how-to-clean-pilling": {"topic": "how to remove pilling from clothes",
                             "required_sections": ["What Causes Pilling (and Which Fabrics Are Most Vulnerable)",
                                                   "The Sweater Stone Method",
                                                   "The Fabric Shaver Method",
                                                   "The Razor Trick",
                                                   "How to Prevent Pilling: Washing Tips",
                                                   "Care Instructions by Fabric Type"],
                             "tone": "practical, care expert"},
    "stinky-smell":         {"topic": "how to remove smell from clothes without washing",
                             "required_sections": ["Why Clothes Smell (bacteria, sweat, detergent buildup)",
                                                   "The Freezer Method",
                                                   "White Vinegar Spray",
                                                   "Baking Soda Treatment",
                                                   "Vodka Spritz Hack",
                                                   "Steam vs Dry Air Out",
                                                   "Prevention: The Wash-Less Denim Movement 2026"],
                             "tone": "practical, problem-solver"},
    "remove-stain":         {"topic": "how to remove stains from jeans and clothes",
                             "required_sections": ["Act Fast: The First 60 Seconds Rule",
                                                   "Oil and Grease Stains",
                                                   "Wine and Berry Stains",
                                                   "Grass and Mud Stains",
                                                   "Dye Transfer Stains",
                                                   "What NOT To Do (common mistakes)",
                                                   "Care After Stain Removal"],
                             "tone": "practical, urgent, step-by-step"},
}


def _get_handle_rules(article_handle: str) -> dict | None:
    """Return handle-specific content rules if the handle matches a known pattern."""
    handle_lower = (article_handle or "").lower()
    for pattern, rules in HANDLE_CONTENT_RULES.items():
        if pattern in handle_lower:
            return rules
    return None


def _build_prompt(fmt: str, product: dict, keyword: str, title_hint: str, similar_products: list | None = None, matching_products: list | None = None) -> tuple[str, str]:
    display_name = get_product_display_name(product)
    clean_ptype = get_clean_product_type(product)
    price  = product["variants"][0]["price"] if product.get("variants") else "49"
    handle = product.get("handle", "")
    url    = f"{STORE_URL}/products/{handle}" if handle else STORE_URL

    lsi    = _lsi_keywords(clean_ptype, keyword)
    lsi_str = ", ".join(f'"{k}"' for k in lsi)

    if similar_products is None:
        similar_products = []
    if matching_products is None:
        matching_products = []

    # Build styling instructions for the collage items to tie image & text together
    match_instr = ""
    if matching_products:
        clean_matches = [get_product_display_name(m) for m in matching_products]
        matches_str = " and ".join([f"'{m_title}' (${m['variants'][0]['price'] if m.get('variants') else '49'})" for m_title, m in zip(clean_matches, matching_products)])
        match_instr = (
            f"- We are featuring a styling lookbook collage showing this product paired with: {matches_str}.\n"
            f"- In the styling or outfit sections of your article, you MUST explicitly mention these matching pieces by name, explaining how to style them together with the main featured product to create a complete, cohesive outfit (e.g., 'pair it with the {clean_matches[0]}' or 'complete this look using the {clean_matches[1]}').\n"
        )

    base = (
        f"You are a fashion editor at MeeeShop, a USA women's clothing boutique.\n"
        f"Write a {MONTH} blog post. Target keyword: '{keyword}'\n"
        f"Feature product: {display_name} — ${price}\n"
        f"Category: {clean_ptype}\n\n"
        f"{EEAT_RULES}"
        f"2026 TREND FRESHNESS — weave 1-2 of these angles in naturally where relevant:\n"
        f"  • Quiet luxury: clean lines, no logos, elevated basics — trending on Flipboard #Style (8.4M followers)\n"
        f"  • Cigarette/stovepipe jeans — the 2026 dominant denim silhouette replacing baggy styles\n"
        f"  • Dark indigo/clean wash denim — the 'elevated' denim choice over distressed styles\n"
        f"  • Linen tops + jeans = heat-proof, chic summer formula (layer untucked or half-tuck)\n"
        f"  • All-black outfits even in summer — 7-look styling trend (Flipboard #Style)\n"
        f"  • Oversized blazer over a simple tank + straight-leg jeans = the office-to-evening 2026 formula\n\n"
        f"SEO rules (follow precisely):\n"
        f"- Primary keyword '{keyword}': use 3-4 times naturally — once in H1, once in first paragraph, 1-2 times in body/conclusion\n"
        f"- LSI / secondary keywords to weave in naturally (don't force all, pick what fits): {lsi_str}\n"
        f"- At least 2 of these LSI keywords must appear in H2 subheadings\n"
        f"- Do NOT write or include any HTML links (<a> tags) to the product page or MeeeShop anywhere in the body text. The product card and shop-the-look widgets will be programmatically injected by the system, so manual linking inside the article is redundant and violates SEO guidelines by looking spammy.\n"
        f"- Limit mentions of the product title '{display_name}' to a maximum of 2 times in the entire body. When referring to the product subsequent times, use pronouns or the specific generic term '{clean_ptype}' (e.g., 'this {clean_ptype}', 'the {clean_ptype}', 'it', 'this piece') instead of repeating the full product name.\n"
        f"- H1 title must include year {YEAR} or 'for Women'\n"
        f"- Keyword density: natural reading, never stuffed — if it sounds forced, rephrase\n"
        f"- Answer a real problem women face when shopping for this item\n"
        f"{match_instr}"
        f"- To avoid programmatic footprints, vary your structure. Occasionally include a <blockquote style='border-left: 3px solid #ccc; padding-left: 10px; margin: 15px 0; font-style: italic;'> for a 'Stylist Tip', or a styled callout box. Make the flow feel like a hand-written editorial, not a template.\n"
        f"- You MUST include a Shoppers' Q&A section immediately before the final CTA/verdict section. This must consist of:\n"
        f"  <h2>Shoppers' Q&A: Common Questions Answered</h2>\n"
        f"  <h3>Why should the {display_name} be in my closet?</h3>\n"
        f"  <p>[Detailed first-person answer from a stylist explaining why it's a wardrobe staple, 40-50 words]</p>\n"
        f"  <h3>What is the fabric composition and how do I wash this style?</h3>\n"
        f"  <p>[Detailed answer detailing how to wash and maintain the fabric quality, 40-50 words]</p>\n"
        f"  <h3>How do I choose the correct size for the {display_name}?</h3>\n"
        f"  <p>[Actionable advice on sizing fit, body shape guidelines, sizes XS-3X, 40-50 words]</p>\n\n"
        f"Store info: Free US shipping on orders $50+. Easy 7-day returns. Sizes XS-3X.\n\n"
    )

    if fmt == "buying_guide":
        prompt = base + (
            f"Format: Definitive Buying Guide (Refinery29 / Who What Wear editorial depth)\n"
            f"Write in HTML (<h1>,<h2>,<h3>,<p>,<ul>,<li>):\n"
            f"1. <h1> '{title_hint}'\n"
            f"2. <p> Hook — open with a SPECIFIC observation or problem (NOT 'In today's fashion world...'). Example: 'Here is the honest truth about the {clean_ptype} question I get asked every single week.' (80 words, stylist voice)\n"
            f"3. <h2> What Actually Makes a Good {clean_ptype.title()}? (4 real criteria — e.g., fabric weight, drape quality, seam construction, size consistency — as <ul><li> with 1-sentence explanations. Be specific, not generic.)\n"
            f"4. <h2> Why {display_name} Made Our Edit: The Honest Breakdown (120 words — discuss actual cut, fabric drape, fit reality for different body shapes, price-to-quality ratio. Do NOT include HTML links.)\n"
            f"5. <h2> 3 Real-Life Outfit Recipes (H3 each with creative occasion name like 'The Power Lunch' or 'Saturday Gallery Hop'. Each: list specific tops with fabric+color, a layering piece like a blazer or cardigan, a bag style, and one accessory with the reason it works. Do NOT recommend shoes — MeeeShop sells clothing only. 70 words each.)\n"
            f"6. <h2> Who This Actually Works For (and Who Should Skip It) (60 words — honest body shape and lifestyle fit advice. Acknowledge trade-offs.)\n"
            f"7. <h2> Sizing: Buy Your Size or Size Up? (40 words — specific verdict on fit, note if runs small/large, bust and length reality for XS-3X)\n"
            f"8. <p> Direct, warm CTA: price, free US shipping on orders $50+, 7-day returns. Do NOT include HTML links.\n"
            f"Target: 800-950 words. Output ONLY clean HTML, no markdown code fences."
        )

    elif fmt == "comparison":
        real_alts = [
            p for p in similar_products
            if p.get('handle') != product.get('handle') and p.get('images')
        ][:2]
        if len(real_alts) < 2:
            # Fallback: any 2 other products
            real_alts = [
                p for p in similar_products
                if p.get('handle') != product.get('handle')
            ][:2]
        alt1_display = get_product_display_name(real_alts[0]) if real_alts else "a similar style"
        alt1_price = real_alts[0]['variants'][0]['price'] if (real_alts and real_alts[0].get('variants')) else "49"
        alt2_display = get_product_display_name(real_alts[1]) if len(real_alts) > 1 else "another option"
        alt2_price = real_alts[1]['variants'][0]['price'] if (len(real_alts) > 1 and real_alts[1].get('variants')) else "49"
        
        prompt = base + (
            f"Format: Comparison Article — helps women choose the right style\n"
            f"Write in HTML:\n"
            f"1. <h1> '{title_hint}'\n"
            f"2. <p> Intro — 'I get asked this question every week from our customers: how does {display_name} compare to other styles?' (70 words, empathetic stylist perspective)\n"
            f"3. <h2> Option 1: {display_name} — What I Love + Who It's For (100 words, detailed stylist analysis of the drape and cut, do NOT include HTML links)\n"
            f"4. <h2> Option 2: {alt1_display} — Pros, Cons, and Styling Fit (80 words). Price: ${alt1_price}\n"
            f"5. <h2> Option 3: {alt2_display} — Pros, Cons, and Styling Fit (80 words). Price: ${alt2_price}\n"
            f"6. <h2> Quick Styling Comparison (HTML table: Style | Best For | Price Range | Fabric Draping Winner)\n"
            f"7. <h2> My Honest Verdict — The Winner for Most Women (80 words, stylist recommendation)\n"
            f"8. <p> CTA to shop {display_name} at MeeeShop + price, free shipping on orders $50+, easy returns, do NOT include HTML links\n"
            f"Target: 750-900 words. Output ONLY clean HTML."
        )

    elif fmt == "problem_solver":
        problems = {
            "dress":      "finding a flattering dress that works for multiple occasions without breaking the budget",
            "jean":       "finding jeans that actually fit your body type perfectly",
            "top":        "building a versatile work-to-weekend wardrobe on a budget",
            "blouse":     "finding a blouse that's polished enough for work but fun enough for weekends",
            "pant":       "finding pants that look amazing and feel comfortable all day long",
            "skirt":      "styling a skirt confidently for every occasion without overthinking it",
            "sweater":    "staying stylish and warm without looking frumpy in the cold months",
            "cardigan":   "layering outfits that look intentional, not sloppy",
            "jacket":     "layering outfits without looking bulky or adding too much volume",
            "coat":       "finding a coat that's practical in the cold but still looks chic",
            "swimwear":   "finding a swimsuit that flatters your figure and makes you feel confident",
            "activewear": "finding workout clothes that look great enough to wear all day",
        }
        problem = next(
            (v for k, v in problems.items() if k in clean_ptype or k in display_name.lower()),
            "dressing well on a budget without sacrificing style or looking like everyone else",
        )
        prompt = base + (
            f"Format: Problem-Solver — directly addressing '{problem}'\n"
            f"Write in HTML:\n"
            f"1. <h1> '{title_hint}'\n"
            f"2. <p> Opening — validate the reader's exact pain point with empathy and insider knowledge. Start with their frustration, not a generic intro. (80 words, second-person, warm and direct — like a stylist friend who finally gets it)\n"
            f"3. <h2> Why It Keeps Happening (and It's Not Your Fault) (60 words — explain the real structural or industry reason behind the problem, e.g., sizing inconsistency across brands, fabric quality shortcuts, etc.)\n"
            f"4. <h2> The Fix: Why {display_name} Solves This (120 words — describe specific cut details, fabric stretch or structure, and exactly HOW these features solve '{problem}'. Do NOT include HTML links.)\n"
            f"5. <h2> 3 Outfit Recipes That Prove It (H3 each with creative occasion name. Each outfit: name specific shoes with material+color, top with silhouette+fabric, bag style, one accessory. 70 words each.)\n"
            f"6. <h2> 4 Stylist Rules That Change Everything (bullet list — SPECIFIC tips like 'Always size up one in {clean_ptype} if you are between sizes — the waistband gap is easier to tailor than a tight seat.')\n"
            f"7. <p> Honest, warm CTA: price of {display_name}, free US shipping on $50+, 7-day returns, sizes XS-3X. Do NOT include HTML links.\n"
            f"Target: 750-900 words. Output ONLY clean HTML."
        )

    elif fmt == "trend_report":
        prompt = base + (
            f"Format: {MONTH} Trend Report — grounded in real 2026 fashion data\n"
            f"Write in HTML:\n"
            f"1. <h1> '{title_hint}'\n"
            f"2. <p> Intro — Anchor the reader in what is actually happening in fashion RIGHT NOW in summer 2026. Reference real Flipboard/street-style trends (quiet luxury, cigarette jeans replacing wide-leg, wedge sandals + denim combo). Be specific about what changed. (70 words, confident stylist voice)\n"
            f"3. Five trends, each as <h2> with opinionated trend name + 90-word description:\n"
            f"   - Trend #1 MUST be {display_name} (do NOT include HTML links) — explain why it fits the 2026 moment\n"
            f"   - Trend #2: Cigarette/Stovepipe Jeans Taking Over — why the wide-leg silhouette is being replaced\n"
            f"   - Trend #3: The Quiet Luxury Denim Edit — dark indigo, no distressing, clean lines\n"
            f"   - Trend #4: Linen + Denim Summer Formula — the heat-proof styling answer\n"
            f"   - Trend #5: One more relevant {MONTH} 2026 micro-trend for US women shoppers\n"
            f"   - Each trend: what it is, why it is trending NOW, specific how-to-wear formula, who it suits and who should skip it\n"
            f"4. <h2> How to Mix Two Trends Without Looking Overdone (60 words — a practical 'choose one focal piece' rule)\n"
            f"5. <p> Direct CTA: shop {display_name} at MeeeShop, price, free shipping on $50+. Do NOT include HTML links.\n"
            f"Target: 800-950 words. Output ONLY clean HTML."
        )

    elif fmt == "care_guide":
        is_denim_care = any(x in clean_ptype for x in ["jean", "denim"])
        denim_care_specifics = (
            f"   DENIM-SPECIFIC RULES to cover (sourced from real denim care standards):\n"
            f"   • Wash only every 5-10 wears — overwashing breaks down denim fibers and fades color\n"
            f"   • ALWAYS wash inside out — protects the indigo surface dye\n"
            f"   • Cold water ONLY — hot water causes shrinking and fading\n"
            f"   • NO fabric softener — it breaks down stretch fibers in stretch denim\n"
            f"   • Skip the dryer — hang dry flat to preserve the fit and elasticity\n"
            f"   • Spot clean small stains with a damp cloth instead of a full wash\n"
            f"   • The freezer method for odor: seal in a zip bag, freeze overnight — kills odor-causing bacteria\n"
        ) if is_denim_care else ""
        prompt = base + (
            f"Format: Practical Fabric Care & Washing Guide (reader-first, actionable like a Refinery29 care article)\n"
            f"Write in HTML:\n"
            f"1. <h1> '{title_hint}'\n"
            f"2. <p> Hook — open with a SPECIFIC care mistake women make that ruins their {clean_ptype}. E.g., for denim: 'Washing your jeans after every wear is the fastest way to ruin them — and most women don\'t know it.' (70 words, direct, problem-first)\n"
            f"3. <h2> Reading Your Care Label: What Those Symbols Actually Mean (explain the 4 main care symbols: wash tub, triangle, square, iron — with plain English translations)\n"
            f"4. <h2> The Right Way to Wash {display_name}\n"
            f"   <h3> Machine Washing (temperature, cycle, detergent — be precise, e.g., 'cold/delicate cycle, liquid detergent, turn inside out')\n"
            f"   <h3> Hand Washing (when and how — water temp, gentle swirl, no wringing)\n"
            f"{denim_care_specifics}"
            f"5. <h2> Drying Without Damage (air dry vs dryer reality — explain WHY heat damages the fabric, give specific hang-dry instructions)\n"
            f"6. <h2> Storage Tips That Preserve the Fit (folding vs hanging for this garment type, how to avoid stretch marks and misshaping)\n"
            f"7. <blockquote style='border-left:3px solid #ccc;padding-left:10px;margin:15px 0;font-style:italic;'> A Stylist Tip with one specific care hack that most people don't know\n"
            f"8. <p> Warm CTA: shop the {display_name} at MeeeShop, price, free US shipping on $50+, 7-day returns. Do NOT include HTML links.\n"
            f"Target: 750-900 words. Output ONLY clean HTML."
        )

    elif fmt == "sizing_guide":
        prompt = base + (
            f"Format: Inclusive Sizing & Fit Guide (body-shape-positive, honest, actionable)\n"
            f"Write in HTML:\n"
            f"1. <h1> '{title_hint}'\n"
            f"2. <p> Hook — open with the real frustration: 'Ordering {clean_ptype} online is a gamble — until you know the three measurements that matter most.' (70 words, warm, second-person, direct)\n"
            f"3. <h2> How to Measure Yourself in 3 Steps (waist, hips, inseam/length — give specific instructions for each measurement point)\n"
            f"4. <h2> MeeeShop Size Chart: XS to 3X Decoded (present a <table> with size / waist / hip / inseam ranges in inches — realistic US measurements)\n"
            f"5. <h2> Fit by Body Shape\n"
            f"   <h3> Petite Frame (under 5'4\"): what works, what to avoid, specific length/rise advice\n"
            f"   <h3> Hourglass: how this cut balances hip-to-waist ratio\n"
            f"   <h3> Straight / Athletic Build: how to create the illusion of curves with this {clean_ptype}\n"
            f"   <h3> Curvy / Full-Figured (1X–3X): real notes on hip room, waistband gap, and stretch factor\n"
            f"6. <h2> High Rise vs Mid Rise vs Low Rise — Which Fits Your Body Best? (40 words per rise — who each works for)\n"
            f"7. <h2> The Final Verdict: Buy Your Size or Size Up? (honest recommendation for {display_name} specifically — does it run small, large, or true to size)\n"
            f"8. <p> CTA: shop with confidence, free US shipping on $50+, easy 7-day returns, sizes XS-3X. Do NOT include HTML links.\n"
            f"Target: 800-950 words. Output ONLY clean HTML."
        )

    else:  # outfit_formula
        prompt = base + (
            f"Format: 5-Outfit Formula — Who What Wear / Refinery29 editorial style\n"
            f"Write in HTML:\n"
            f"1. <h1> '{title_hint}'\n"
            f"2. <p> Hook — open with a SPECIFIC insight about this garment's versatility that surprises the reader. NOT 'This piece is so versatile!' — instead: 'The reason the {display_name} works for five completely different occasions is one structural detail most people overlook.' (70 words, first-person stylist voice)\n"
            f"3. Five looks as <h2> sections — each MUST have a creative, evocative occasion title (not generic):\n"
            f"   Required: 'Look 1: [Creative Name]', 'Look 2: [Creative Name]', etc.\n"
            f"   Examples: 'Sunday Farmers Market', 'The Power Lunch', 'Date Night That Doesn\'t Look Like You Tried Too Hard', 'Airport Chic', 'Weekend Gallery Hop'\n"
            f"   Each look (80-90 words) MUST include:\n"
            f"   • Specific top or layer: silhouette + fabric + color (e.g., 'a relaxed linen shirt in ecru, left untucked')\n"
            f"   • A layering piece where relevant: blazer, cardigan, or jacket with specific color/weight\n"
            f"   • Specific bag: style + color (e.g., 'a mini structured tote in chocolate brown')\n"
            f"   • One accessory (belt, earrings, scarf, or hat) with a reason it works\n"
            f"   • Do NOT recommend shoes — MeeeShop sells clothing only\n"
            f"   • One sentence on WHERE exactly to wear this and WHY it works for that context\n"
            f"4. <h2> The Honest Fit Notes (50 words — specific body-type advice: who this works for, who should size up, any length or rise caveat)\n"
            f"5. <p> Direct CTA with price of {display_name}, free US shipping on $50+, 7-day returns. Do NOT include HTML links.\n"
            f"Target: 800-950 words. Output ONLY clean HTML."
        )

    # Append SEO metadata instructions to the prompt so we generate all details in one AI call
    prompt += (
        f"\n\nAt the very end of your response, after the HTML content, you MUST append a `<seometa>` section containing the SEO metadata. The format MUST be exactly like this (use these exact keys):\n"
        f"<seometa>\n"
        f"SEO_TITLE: [50-60 chars, keyword near start, year or 'for Women', compelling — referencing 2026 trend angle if possible]\n"
        f"META_DESC: [140-155 chars, action-oriented, includes keyword, mentions 2026 trend angle or free shipping, ends with CTA]\n"
        f"IMG_ALT: [descriptive ALT text for featured image collage, 10-15 words, describes the outfit/styling scene shown, includes keyword + 'women' + product type, no quotes]\n"
        f"</seometa>\n"
        f"Make sure there are no other text or markdown code fences enclosing the <seometa> block."
    )

    return prompt, title_hint


def _extract_h1(html: str, fallback: str) -> str:
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.IGNORECASE | re.DOTALL)
    return re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else fallback


def _clean_html(raw: str) -> str:
    raw = raw.strip()
    raw = re.sub(r"^```html?\s*", "", raw, flags=re.IGNORECASE)
    return re.sub(r"\s*```$", "", raw).strip()


def _make_tags(product: dict, fmt: str, keyword: str) -> list[str]:
    base_tags = ["fashion", "women fashion", "MeeeShop", "USA fashion",
                 "women's clothing", "affordable fashion", "style tips"]
    ptype = (product.get("product_type") or "").lower()
    fmt_tags = {
        "buying_guide":   ["buying guide", "fashion guide", f"best picks {YEAR}"],
        "comparison":     ["fashion comparison", "style guide", "what to buy"],
        "problem_solver": ["styling advice", "outfit help", "fashion tips"],
        "trend_report":   [f"fashion trends {YEAR}", "trending styles", "new in fashion"],
        "outfit_formula": ["outfit ideas", "how to style", "outfit inspiration"],
    }
    trending_2026_tags = [
        f"fashion {YEAR}", "denim trends 2026", "quiet luxury",
        "jeans outfit 2026", "summer fashion 2026"
    ]
    tags = base_tags + fmt_tags.get(fmt, []) + trending_2026_tags
    if ptype:
        tags.append(ptype)
    # Denim-specific trending tags
    if any(x in ptype for x in ["jean", "denim"]):
        tags += ["cigarette jeans", "dark wash jeans", "linen top with jeans"]
    # Primary keyword words as tags
    tags += [w for w in keyword.split() if len(w) > 3][:3]
    # Top LSI keywords as tags (short ones work best as Shopify tags)
    lsi = _lsi_keywords(ptype, keyword)
    tags += [k for k in lsi if len(k) < 30][:4]
    return list(dict.fromkeys(tags))[:25]


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


def generate_keyword_title_and_format(product: dict, format_override: str = None) -> tuple[str, str, str]:
    category_phrase = get_category_style_phrase(product)

    is_denim = any(x in (product.get("product_type") or "").lower() or (product.get("title") or "").lower()
                   for x in ["jean", "denim"])

    options = [
        (f"{category_phrase} sizing guide",
         f"{category_phrase}: Sizing & Fit Guide for Women {YEAR}",
         "sizing_guide"),
        (f"how to style {category_phrase}",
         f"5 Stunning Outfits to Build Around {category_phrase} in {YEAR}",
         "outfit_formula"),
        (f"best {category_phrase} for women",
         f"The Best {category_phrase} for Women in {YEAR}: Our Editor's Guide",
         "buying_guide"),
        (f"{category_phrase} fashion trends",
         f"{MONTH} Women's Fashion Trends: How to Style {category_phrase}",
         "trend_report"),
        (f"how to wash {category_phrase}",
         f"How to Wash & Care for {category_phrase} ({YEAR} Style Guide)",
         "care_guide"),
        (f"styling {category_phrase}",
         f"How to Style {category_phrase} for Casual Chic Outfits ({YEAR} Guide)",
         "problem_solver")
    ]

    if is_denim:
        options += [
            (f"quiet luxury {category_phrase}",
             f"The Quiet Luxury Denim Look: How to Style {category_phrase} in {YEAR}",
             "trend_report"),
            (f"how to pair {category_phrase} summer",
             f"Summer {YEAR} Denim Outfit Formula: Style {category_phrase} 5 Ways",
             "outfit_formula"),
        ]

    if format_override:
        matched = [opt for opt in options if opt[2] == format_override]
        if matched:
            return matched[0]

    base_options = options[:6]
    weights = [0.10, 0.25, 0.20, 0.20, 0.05, 0.20]
    return random.choices(base_options, weights=weights, k=1)[0]


# ── main ──────────────────────────────────────────────────────────────────────
def run(count: int = 1, dry_run: bool = False, publish: bool = False, format_override: str = None, topic: str = None):
    print(f"\n{'='*62}")
    print(f"  MeeeShop Blog Automation — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  Posts: {count} | Dry-run: {dry_run} | Publish: {publish} | Format: {format_override or 'weighted random'}")
    if topic:
        print(f"  Target Search Topic: '{topic}'")
    print(f"{'='*62}\n")

    print("Fetching products…")
    products = fetch_products(limit=100)
    if not products:
        sys.exit("ERROR: No products returned from Shopify.")
    products_with_imgs = [p for p in products if p.get("images")]
    # Strictly restrict pool to products with images to ensure high quality for Discover
    pool = products_with_imgs
    if not pool:
        sys.exit("ERROR: No products with images found in Shopify. Cannot generate Discover-ready blog posts without product images.")
    if len(pool) < count:
        print(f"  [Warning] Only found {len(pool)} products with images, but requested {count} posts. Adjusting count to {len(pool)}.")
        count = len(pool)
    print(f"  {len(products)} products ({len(products_with_imgs)} with images used as pool)\n")

    all_blogs = get_all_blogs()
    print(f"  Available blogs: {[b['title'] for b in all_blogs]}\n")

    # ── Deduplication: load all live article titles + handles once ─────────────
    dedup = ArticleDeduplicator(BASE, HEADERS)
    dedup.load_live_index()

    # Build internal linker map
    print("[*] Building internal linker map...")
    link_map = wtb.build_linker_map()

    # Build type map
    type_map = {}
    for p in pool:
        ptype = (p.get("product_type") or "Uncategorized").strip()
        if ptype not in type_map:
            type_map[ptype] = []
        type_map[ptype].append(p)

    chosen   = random.sample(pool, min(count, len(pool)))

    created = 0
    for i, product in enumerate(chosen):
        keyword, title_hint, fmt = generate_keyword_title_and_format(product, format_override)
        if topic:
            keyword = topic

        # Map our daily format to weekly_trend_blog's mode IDs
        mode_mapping = {
            "sizing_guide": "body_type_guide",
            "outfit_formula": "one_item_multiple_ways",
            "buying_guide": "shopping_guide_edit",
            "trend_report": "trend_report",
            "care_guide": "fabric_care_guide",
            "problem_solver": "stain_odour_rescue"
        }
        wtb_format = mode_mapping.get(fmt, "one_item_multiple_ways")
        if topic:
            wtb_format = "trend_report" if random.random() < 0.6 else "shopping_guide_edit"

        print(f"[{i+1}/{count}] Format: {fmt} (Mapping to wtb: {wtb_format}) | Keyword: '{keyword}'")
        print(f"  Product: {product['title'][:70]}")
        print(f"  Type   : {product.get('product_type', 'unknown')}")

        blog = get_or_create_blog(product.get("product_type", ""), all_blogs, dry_run)
        print(f"  Blog   : {blog['title']}")

        # We call the unified generator engine from weekly_trend_blog.py
        # It handles: Flipboard research, collage creation, E-E-A-T prompting, internal links injection, etc.
        content_assets = wtb.generate_single_article_content(
            main_product=product,
            all_products_with_images=pool,
            link_map=link_map,
            type_map=type_map,
            research_cache={},
            force_format=wtb_format,
            dry_run=dry_run,
            original_handle_hint=None
        )

        if not content_assets:
            print(f"  [!] Failed to generate content for product: {product['title']}")
            continue

        # Destructure generated assets
        raw_title        = content_assets.get("seo_title") or content_assets.get("title") or title_hint
        post_title       = sanitize_title_to_category_phrase(raw_title, product)
        html_body        = content_assets.get("html_body", "")
        tags             = content_assets.get("tags", [])
        img_url          = content_assets.get("img_url", "")
        img_alt          = content_assets.get("img_alt", get_category_style_phrase(product))
        meta_desc        = content_assets.get("meta_desc", "")
        author_name      = content_assets.get("author", "MeeeShop Editorial Team")
        suggested_handle = content_assets.get("suggested_handle") or content_assets.get("handle") or wtb._slugify(post_title)

        print(f"  SEO title : {post_title}")
        print(f"  Meta desc : {meta_desc[:60]}…")
        print(f"  IMG ALT   : {img_alt}")
        print(f"  Featured Image : {img_url}")
        print(f"  Author    : {author_name}")

        # ── Deduplication check before publishing ──────────────────────────────
        fmt_key = content_assets.get("chosen_mode", fmt)
        result = dedup.resolve(
            title=post_title,
            handle=suggested_handle or "",
            product_handle=product.get("handle", ""),
            article_format=fmt_key,
            dry_run=dry_run,
        )
        if result is None:
            print(f"  [Dedup] Skipping article — same product+format published recently.")
            continue
        post_title, suggested_handle = result

        # Update content_assets with resolved title/handle
        content_assets["title"] = post_title
        content_assets["handle"] = suggested_handle

        # Publish (or save as draft)
        status_label = "live" if publish else "DRAFT (review in Shopify Admin before publishing)"
        print(f"  Status    : {status_label}")
        article = publish_article(
            blog, post_title, html_body, tags,
            img_url, img_alt, meta_desc,
            dry_run, publish=publish, author=author_name
        )

        # Set SEO metafields (title_tag + description_tag) after creation
        if article and not dry_run and article.get("id"):
            # Update the article handle to match suggested_handle
            if suggested_handle and suggested_handle != article.get("handle"):
                try:
                    update_payload = {"id": article["id"], "handle": suggested_handle}
                    _req("put", f"{BASE}/blogs/{blog['id']}/articles/{article['id']}.json", json={"article": update_payload})
                    print(f"  [Handle] Updated article handle to '{suggested_handle}'")
                except Exception as e:
                    print(f"  [Warning] Failed to update handle: {e}")

            set_article_seo_metafields(blog["id"], article["id"],
                                       post_title, meta_desc)

        if article:
            created += 1
            # Register published title+handle so same run doesn't duplicate
            dedup.register(post_title, suggested_handle)
            # Record product×format cooldown
            dedup.record_product_format(
                product.get("handle", ""),
                fmt_key,
                dry_run=dry_run
            )
        print()
        time.sleep(4.0)

    result_label = "published live" if publish else "saved as DRAFT"
    print(f"Done — {created}/{count} blog posts {result_label}.")
    if not dry_run:
        if publish:
            print(f"View at: https://{SHOP}/blogs\n")
        else:
            print(f"Review drafts at: https://{SHOP}/admin/articles\n")
            print("Tip: add --publish flag to go live immediately (use after reviewing content)\n")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="MeeeShop Google Discover blog generator")
    ap.add_argument("--dry-run",  action="store_true", help="Print only, no publishing")
    ap.add_argument("--count",    type=int, default=1,  help="Number of posts to create (default 1)")
    ap.add_argument("--publish",  action="store_true",
                    help="Publish immediately (default: save as DRAFT for human review)")
    ap.add_argument("--format",   type=str, default=None,
                    choices=["sizing_guide", "outfit_formula", "buying_guide", "trend_report", "care_guide", "problem_solver"],
                    help="Force a specific blog format (default: weighted choice)")
    ap.add_argument("--topic",    type=str, default=None, help="Target search topic/query for long-tail blog creation")
    args = ap.parse_args()
    run(count=args.count, dry_run=args.dry_run, publish=args.publish, format_override=args.format, topic=args.topic)

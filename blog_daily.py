#!/usr/bin/env python3
"""
blog_daily.py — Google Discover-ready blog automation for MeeeShop
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Google Discover requirements met:
  - Featured image: 1200px wide (Shopify product image via CDN, or Pollinations.ai fallback)
  - Title: compelling, non-clickbait, matches content intent
  - EEAT: first-person experience, expertise signals, trust indicators
  - High-intent formats: buying guide, comparison, problem-solver,
    trend report, outfit formula
  - Popular keywords embedded naturally
  - No AI-sounding filler or generic phrasing

AI: Gemini 2.0 Flash -> Groq Llama-3.3-70B -> OpenRouter (multi-model free tier)
Image: Shopify product image (copyright-free, resized to 1200x630 via CDN param)

Usage:
  python blog_daily.py              # create 1 draft blog post
  python blog_daily.py --dry-run    # print only, no Shopify publish
  python blog_daily.py --count 3    # create 3 posts
"""

import os, sys, re, time, random, argparse
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import requests
import ai_client

# ── credentials ───────────────────────────────────────────────────────────────
def _load_env():
    for candidate in [Path(__file__).with_name(".env"), Path(".env")]:
        if candidate.exists():
            for line in candidate.read_text(encoding="utf-8").splitlines():
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"'))

_load_env()

SHOP    = os.getenv("SHOPIFY_STORE", "us-meeeshop.myshopify.com")
TOKEN   = os.getenv("SHOPIFY_ACCESS_TOKEN", "")
API_VER = "2024-10"
BASE    = f"https://{SHOP}/admin/api/{API_VER}"
HEADERS = {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}

if not TOKEN:
    sys.exit("ERROR: SHOPIFY_ACCESS_TOKEN not set.")

STORE_URL = "https://us.meeeshop.com"

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
# Maps product_type keywords → Shopify blog title keywords
# Falls back to first available blog if no match found.
CATEGORY_BLOG_MAP = {
    "dress":    ["dress", "style", "fashion", "journal"],
    "jean":     ["denim", "jean", "style", "fashion", "journal"],
    "top":      ["style", "fashion", "tops", "journal"],
    "blouse":   ["style", "fashion", "tops", "journal"],
    "skirt":    ["style", "fashion", "journal"],
    "pant":     ["style", "fashion", "journal"],
    "jacket":   ["outerwear", "style", "fashion", "journal"],
    "coat":     ["outerwear", "style", "fashion", "journal"],
    "sweater":  ["style", "fashion", "journal"],
    "cardigan": ["style", "fashion", "journal"],
    "swimwear": ["swim", "summer", "style", "fashion", "journal"],
    "activewear": ["active", "fitness", "style", "fashion", "journal"],
    "accessory": ["accessories", "style", "fashion", "journal"],
}


def get_all_blogs() -> list:
    r = _req("get", f"{BASE}/blogs.json")
    r.raise_for_status()
    return r.json().get("blogs", [])


def get_or_create_blog(product_type: str, all_blogs: list) -> dict:
    """Find the best matching blog for this product type, or create a default."""
    ptype_lower = (product_type or "").lower()
    hints = []
    for key, keywords in CATEGORY_BLOG_MAP.items():
        if key in ptype_lower:
            hints = keywords
            break

    # Try to match an existing blog by title
    for hint in hints:
        for blog in all_blogs:
            if hint in blog.get("title", "").lower():
                return blog

    # Fallback: use first blog, or create one
    if all_blogs:
        return all_blogs[0]

    r = _req("post", f"{BASE}/blogs.json",
             json={"blog": {"title": "MeeeShop Fashion Journal"}})
    r.raise_for_status()
    new_blog = r.json()["blog"]
    all_blogs.append(new_blog)
    return new_blog


def fetch_products(limit=100) -> list:
    r = _req("get", f"{BASE}/products.json",
             params={"limit": limit, "fields": "id,title,handle,product_type,vendor,tags,variants,images,body_html"})
    r.raise_for_status()
    return r.json().get("products", [])


# ── Image helpers ──────────────────────────────────────────────────────────────
def make_featured_image(product: dict, fmt: str) -> str:
    """
    Use Shopify product image resized to 1200x630 as featured image (copyright-free).
    Falls back to Pollinations.ai AI-generated editorial image.
    Google Discover requires minimum 1200px wide.
    """
    images = product.get("images", [])
    if images:
        src = images[0]["src"]
        # Shopify CDN supports width param: append _1200x to filename
        # e.g. product.jpg -> product_1200x.jpg
        src = re.sub(r'\.(jpg|jpeg|png|webp)(\?.*)?$',
                     r'_1200x630_crop_center.\1', src, flags=re.IGNORECASE)
        return src

    # Fallback: AI-generated editorial photo
    ptype = (product.get("product_type") or "women's fashion").lower()
    scene_map = {
        "buying_guide":   "elegant woman wearing stylish outfit in bright modern boutique, natural light, editorial photography",
        "comparison":     "flat lay fashion editorial, multiple clothing items styled on white surface, professional photography",
        "problem_solver": "confident stylish woman smiling, perfect outfit, mirror reflection, morning light, lifestyle photo",
        "trend_report":   "fashion editorial collage, trendy women outfits, street style photography, vibrant colors",
        "outfit_formula": "stylish woman in versatile outfit, city background, golden hour, fashion editorial",
    }
    scene = scene_map.get(fmt, "beautiful women fashion editorial, modern style, natural light")
    ptype_hint = ptype.replace("'s", "").strip()
    prompt = (
        f"professional fashion editorial photo, {ptype_hint} clothing, "
        f"{scene}, high quality, sharp focus, no text, no watermark, "
        f"photorealistic, magazine quality, bright and inviting"
    )
    encoded = quote(prompt)
    seed = random.randint(1, 99999)
    return f"https://image.pollinations.ai/prompt/{encoded}?width=1200&height=630&nologo=true&seed={seed}"


def product_img_url(product: dict) -> str | None:
    images = product.get("images", [])
    return images[0]["src"] if images else None


# ── Product card HTML ──────────────────────────────────────────────────────────
def make_product_card(product: dict, label: str = "FEATURED PICK — IN STOCK NOW") -> str:
    title  = product["title"]
    price  = product["variants"][0]["price"] if product.get("variants") else "0"
    handle = product.get("handle", "")
    url    = f"{STORE_URL}/products/{handle}?utm_source=blog&utm_medium=featured_card&utm_campaign=meeeshop" if handle else STORE_URL
    img    = product_img_url(product)

    img_html = (
        f'<a href="{url}"><img src="{img}" alt="{title}" '
        f'style="width:220px;height:220px;object-fit:cover;border-radius:10px;flex-shrink:0;" /></a>'
        if img else ""
    )

    return f"""
<div style="background:#f8f6f3;border-radius:14px;padding:24px 28px;margin:32px 0;
            display:flex;flex-wrap:wrap;gap:24px;align-items:center;
            border:1px solid #eee;font-family:sans-serif;">
  {img_html}
  <div style="flex:1;min-width:200px;">
    <p style="font-size:11px;color:#999;margin:0 0 6px;text-transform:uppercase;letter-spacing:1.5px;font-weight:600;">{label}</p>
    <h3 style="font-size:18px;font-weight:700;margin:0 0 8px;color:#1a1a1a;line-height:1.3;">{title}</h3>
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


def make_related_products_section(products: list, exclude_handle: str) -> str:
    """
    Build a 'You Might Also Love' section with up to 3 related product cards.
    Each card has product image, title, price, and a Shop link.
    """
    related = [p for p in products if p.get("handle") != exclude_handle and p.get("images")]
    if not related:
        related = [p for p in products if p.get("handle") != exclude_handle]
    picks = random.sample(related, min(3, len(related)))

    cards_html = ""
    for p in picks:
        title  = p["title"]
        price  = p["variants"][0]["price"] if p.get("variants") else "0"
        handle = p.get("handle", "")
        url    = f"{STORE_URL}/products/{handle}?utm_source=blog&utm_medium=related_card&utm_campaign=meeeshop"
        img    = product_img_url(p)
        img_tag = (
            f'<a href="{url}"><img src="{img}" alt="{title}" '
            f'style="width:100%;height:200px;object-fit:cover;border-radius:10px;margin-bottom:12px;" /></a>'
            if img else ""
        )
        cards_html += f"""
  <div style="flex:1;min-width:200px;max-width:260px;font-family:sans-serif;text-align:center;">
    {img_tag}
    <p style="font-size:14px;font-weight:700;color:#1a1a1a;margin:0 0 4px;line-height:1.3;">{title}</p>
    <p style="font-size:16px;font-weight:800;color:#1a1a1a;margin:0 0 12px;">${price}</p>
    <a href="{url}"
       style="background:#f0ede8;color:#1a1a1a;padding:9px 20px;text-decoration:none;
              border-radius:6px;font-size:13px;font-weight:600;display:inline-block;">
      Shop Similar
    </a>
  </div>"""

    if not cards_html:
        return ""

    return f"""
<div style="margin:48px 0;padding:32px;background:#fafafa;border-radius:14px;border:1px solid #eee;">
  <h2 style="font-size:20px;font-weight:700;color:#1a1a1a;margin:0 0 24px;text-align:center;">
    You Might Also Love
  </h2>
  <div style="display:flex;flex-wrap:wrap;gap:24px;justify-content:center;">
    {cards_html}
  </div>
</div>
"""


def inject_product_card(html_body: str, product: dict) -> str:
    """Insert the featured product card right after the intro paragraph."""
    card = make_product_card(product)
    insert_after = re.search(r"</h1>\s*(<p>.*?</p>)", html_body, re.DOTALL | re.IGNORECASE)
    if insert_after:
        pos = insert_after.end()
        return html_body[:pos] + "\n" + card + html_body[pos:]
    pos = html_body.find("</p>")
    if pos != -1:
        return html_body[:pos+4] + "\n" + card + html_body[pos+4:]
    return card + html_body


def publish_article(blog: dict, title: str, body_html: str,
                    tags: list, image_url: str | None,
                    dry_run: bool = False) -> dict | None:
    if dry_run:
        print(f"  [DRY-RUN] '{title}'")
        if image_url:
            print(f"  Image  : {image_url[:90]}")
        print(f"  Blog   : {blog.get('title')}")
        print(f"  Preview: {re.sub(r'<[^>]+>',' ',body_html)[:180].strip()}…\n")
        return {"id": 0, "title": title}

    payload: dict = {
        "article": {
            "title": title,
            "body_html": body_html,
            "tags": ", ".join(tags),
            "published": True,
        }
    }
    if image_url:
        payload["article"]["image"] = {"src": image_url}

    r = _req("post", f"{BASE}/blogs/{blog['id']}/articles.json", json=payload)
    if r.status_code in (200, 201):
        art = r.json().get("article", {})
        print(f"  Published: '{art.get('title')}' (ID {art.get('id')}) in blog '{blog['title']}'")
        return art
    print(f"  FAILED {r.status_code}: {r.text[:200]}")
    return None


# ── High-intent blog formats ───────────────────────────────────────────────────
FORMATS = ["buying_guide", "comparison", "problem_solver", "trend_report", "outfit_formula"]

SEED_KEYWORDS = [
    "women's fashion 2026", "affordable women's clothing USA",
    "summer dress outfits for women", "women's jeans styles guide",
    "casual chic outfits women", "women's fashion trends 2026",
    "cute outfits under $50", "stylish women's tops",
    "best dresses for women", "women's summer wardrobe essentials",
    "affordable boutique fashion USA", "women's outfit ideas",
    "how to style women's clothing", "plus size fashion tips",
    "work outfits for women", "women's weekend casual looks",
    "women's spring outfit ideas 2026", "best tops to wear with jeans",
    "how to build a capsule wardrobe women", "women's date night outfit ideas",
]

YEAR  = datetime.now().year
MONTH = datetime.now().strftime("%B %Y")

EEAT_RULES = (
    "EEAT requirements (mandatory — every post must include these):\n"
    "1. Write as a MeeeShop fashion editor in first-person ('I', 'we', 'our customers tell us')\n"
    "2. Add at least 2 sentences of real personal experience "
    "   (e.g. 'I wore this to a rooftop event and got three compliments')\n"
    "3. Mention real specifics: fabric feel, fit notes, body-type suitability\n"
    "4. Include trust signals: free US shipping, easy 7-day returns, sizes XS-3X\n"
    "5. Every sentence must be actionable or insightful — cut generic filler\n"
    "6. Do NOT write anything that sounds AI-generated or robotic\n"
    "7. Do NOT say 'as an AI' or reveal AI authorship in any way\n"
    "8. Sound like a real woman helping another woman shop — warm, direct, specific\n\n"
)


def _build_prompt(fmt: str, product: dict, keyword: str) -> tuple[str, str]:
    title  = product["title"]
    ptype  = (product.get("product_type") or "women's fashion").lower()
    price  = product["variants"][0]["price"] if product.get("variants") else "49"
    handle = product.get("handle", "")
    url    = f"{STORE_URL}/products/{handle}" if handle else STORE_URL

    base = (
        f"You are a fashion editor at MeeeShop, a USA women's clothing boutique.\n"
        f"Write a {MONTH} blog post. Target keyword: '{keyword}'\n"
        f"Feature product: {title} — ${price}\n"
        f"Product page URL: {url}\n"
        f"Category: {ptype}\n\n"
        f"{EEAT_RULES}"
        f"SEO rules:\n"
        f"- Use target keyword 3-4 times naturally throughout the post\n"
        f"- Include 3-5 LSI keywords (related phrases women actually search)\n"
        f"- Link to product URL at least twice with natural anchor text (not 'click here')\n"
        f"- H1 title must include year {YEAR} or 'for Women'\n"
        f"- Answer a real problem women face when shopping for this item\n\n"
        f"Store info: Free US shipping on orders $50+. Easy 7-day returns. Sizes XS-3X.\n\n"
    )

    if fmt == "buying_guide":
        prompt = base + (
            f"Format: Definitive Buying Guide\n"
            f"Write in HTML (<h1>,<h2>,<h3>,<p>,<ul>,<li>):\n"
            f"1. <h1> 'The Best {ptype.title()} for Women in {YEAR}: Our Editor's Guide'\n"
            f"2. <p> Hook — personal story: why I tested multiple options and THIS is my pick (80 words)\n"
            f"3. <h2> What Makes a Great {ptype.title()}? (4 criteria as <ul><li> bullets with brief real explanations)\n"
            f"4. <h2> Our #1 Pick: {title} — Honest Review (120 words, first-person, mention price + link the product URL twice naturally)\n"
            f"5. <h2> How I Style It: 3 Real Outfits (H3 subheadings for each occasion, 70 words each with specific styling context)\n"
            f"6. <h2> Who Is This Perfect For? (50 words — be specific: body type, lifestyle, occasion)\n"
            f"7. <h2> Sizing & Fit Notes (40 words — real specifics, not generic 'true to size')\n"
            f"8. <p> Final verdict + urgency CTA (shop link, price, free shipping, limited sizes reminder)\n"
            f"Target: 750-900 words. Output ONLY clean HTML, no markdown code fences."
        )
        h1_hint = f"The Best {ptype.title()} for Women in {YEAR}: Our Editor's Guide"

    elif fmt == "comparison":
        prompt = base + (
            f"Format: Comparison Article — helps women choose the right style\n"
            f"Write in HTML:\n"
            f"1. <h1> '{title} vs. [2 similar alternatives]: Which Is Right for You in {YEAR}?'\n"
            f"2. <p> Intro — 'I get asked this question every week from our customers' (70 words, empathetic)\n"
            f"3. <h2> Option 1: {title} — What I Love + Who It's For (100 words, link product URL naturally)\n"
            f"4. <h2> Option 2: [Invent a plausible similar style] — Pros, Cons, Best For (80 words)\n"
            f"5. <h2> Option 3: [Another plausible alternative] — Pros, Cons, Best For (80 words)\n"
            f"6. <h2> Quick Comparison Table (HTML table: Style | Best For | Price Range | Verdict)\n"
            f"7. <h2> My Honest Verdict — The Winner for Most Women (80 words, direct recommendation)\n"
            f"8. <p> CTA to shop {title} + URL + price\n"
            f"Target: 750-900 words. Output ONLY clean HTML."
        )
        h1_hint = f"{title} vs. Similar Styles: Which to Buy in {YEAR}"

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
            (v for k, v in problems.items() if k in ptype.lower() or k in title.lower()),
            "dressing well on a budget without sacrificing style or looking like everyone else",
        )
        prompt = base + (
            f"Format: Problem-Solver — solving '{problem}' for women\n"
            f"Write in HTML:\n"
            f"1. <h1> Relatable title about the problem and how {title} solves it for women in {YEAR}\n"
            f"2. <p> Opening — 'I hear this from our customers constantly: {problem}' (80 words, empathetic, validating)\n"
            f"3. <h2> Why This Problem Is So Frustrating (and More Common Than You Think) (60 words)\n"
            f"4. <h2> The Fix: {title} — Here's Exactly Why It Works (120 words, first-person, link product URL twice naturally)\n"
            f"5. <h2> 3 Real Outfit Solutions (H3 for each occasion, 70 words each with specific styling instructions)\n"
            f"6. <h2> My Top 4 Styling Tips From Years in Fashion (bullet list, specific and actionable, not generic)\n"
            f"7. <p> Warm personal CTA: recommendation + URL + price + free shipping + returns reminder\n"
            f"Target: 700-850 words. Output ONLY clean HTML."
        )
        h1_hint = f"How to Finally Solve {problem.title()} in {YEAR}"

    elif fmt == "trend_report":
        prompt = base + (
            f"Format: {MONTH} Trend Report — what real women are actually wearing\n"
            f"Write in HTML:\n"
            f"1. <h1> '{MONTH} Women's Fashion Trends: What I'm Seeing (and Wearing) Right Now'\n"
            f"2. <p> Intro — 'I've been tracking what real women are actually wearing, not just runways' (70 words, authentic)\n"
            f"3. Five trends, each as <h2> with trend name + 90-word description:\n"
            f"   - Trend #1 MUST be {title} with product URL linked naturally\n"
            f"   - Trends #2-5: invent 4 real, current women's fashion micro-trends for {MONTH}\n"
            f"   - Each trend: what it is, why it's trending, how to wear it, who it's for\n"
            f"4. <h2> How to Mix These Trends Without Looking Overdone (60 words, practical)\n"
            f"5. <p> Shop the trends at MeeeShop + {url} + price\n"
            f"Target: 750-900 words. Output ONLY clean HTML."
        )
        h1_hint = f"{MONTH} Women's Fashion Trends: What I'm Wearing Right Now"

    else:  # outfit_formula
        prompt = base + (
            f"Format: 5-Outfit Formula — shows versatility of one piece\n"
            f"Write in HTML:\n"
            f"1. <h1> '5 Stunning Outfits You Can Build Around {title} (I Wore All 5 This Month)'\n"
            f"2. <p> Intro — 'The best fashion investment is a piece you can wear 5 different ways. "
            f"I put {title} to the real-life test.' (70 words, first-person, engaging)\n"
            f"3. Five outfits as <h2> sections with creative occasion names:\n"
            f"   e.g. 'Look 1: Sunday Farmers Market', 'Look 2: Office Polished', 'Look 3: Date Night'\n"
            f"   Each: specific items to pair it with, where to wear it, personal styling note (80-90 words)\n"
            f"4. <h2> Fit & Sizing Notes — The Honest Truth (40 words, specific body-type advice)\n"
            f"5. <p> CTA: get yours, price, URL, 7-day returns, limited sizes urgency\n"
            f"Target: 750-900 words. Output ONLY clean HTML."
        )
        h1_hint = f"5 Outfits You Can Build Around {title} (I Wore All 5)"

    return prompt, h1_hint


def _extract_h1(html: str, fallback: str) -> str:
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.IGNORECASE | re.DOTALL)
    return re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else fallback


def _clean_html(raw: str) -> str:
    raw = raw.strip()
    raw = re.sub(r"^```html?\s*", "", raw, flags=re.IGNORECASE)
    return re.sub(r"\s*```$", "", raw).strip()


def _make_tags(product: dict, fmt: str, keyword: str) -> list[str]:
    base = ["fashion", "women fashion", "MeeeShop", "USA fashion",
            "women's clothing", "affordable fashion", "style tips"]
    ptype = (product.get("product_type") or "").lower()
    fmt_tags = {
        "buying_guide":   ["buying guide", "fashion guide", f"best picks {YEAR}"],
        "comparison":     ["fashion comparison", "style guide", "what to buy"],
        "problem_solver": ["styling advice", "outfit help", "fashion tips"],
        "trend_report":   [f"fashion trends {YEAR}", "trending styles", "new in fashion"],
        "outfit_formula": ["outfit ideas", "how to style", "outfit inspiration"],
    }
    tags = base + fmt_tags.get(fmt, [])
    if ptype:
        tags.append(ptype)
    tags += [w for w in keyword.split() if len(w) > 3][:3]
    return list(dict.fromkeys(tags))[:20]


# ── main ──────────────────────────────────────────────────────────────────────
def run(count: int = 1, dry_run: bool = False):
    print(f"\n{'='*62}")
    print(f"  MeeeShop Blog Automation — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  Posts: {count} | Dry-run: {dry_run}")
    print(f"{'='*62}\n")

    print("Fetching products…")
    products = fetch_products(limit=100)
    if not products:
        sys.exit("ERROR: No products returned from Shopify.")
    products_with_imgs = [p for p in products if p.get("images")]
    pool = products_with_imgs if len(products_with_imgs) >= count else products
    print(f"  {len(products)} products ({len(products_with_imgs)} with images)\n")

    all_blogs = [] if dry_run else get_all_blogs()
    if not dry_run:
        print(f"  Available blogs: {[b['title'] for b in all_blogs]}\n")

    chosen   = random.sample(pool, min(count, len(pool)))
    fmts     = random.sample(FORMATS, min(count, len(FORMATS)))
    keywords = random.sample(SEED_KEYWORDS, min(count, len(SEED_KEYWORDS)))

    created = 0
    for i, product in enumerate(chosen):
        fmt     = fmts[i % len(fmts)]
        keyword = keywords[i % len(keywords)]

        print(f"[{i+1}/{count}] Format: {fmt} | Keyword: '{keyword}'")
        print(f"  Product: {product['title'][:70]}")
        print(f"  Type   : {product.get('product_type', 'unknown')}")

        # Route to correct blog by product type
        blog = get_or_create_blog(product.get("product_type", ""), all_blogs) if not dry_run else {"id": 0, "title": "DRY-RUN"}
        print(f"  Blog   : {blog['title']}")

        img_url = make_featured_image(product, fmt)
        if product.get("images"):
            print(f"  Image  : Shopify CDN 1200x630 (product photo)")
        else:
            print(f"  Image  : Pollinations.ai AI editorial fallback")

        prompt, h1_hint = _build_prompt(fmt, product, keyword)
        html_body = ai_client.generate(prompt, max_tokens=1600, temperature=0.75)

        if not html_body:
            print("  [AI] all providers failed — skipping\n")
            continue

        html_body = _clean_html(html_body)
        html_body = inject_product_card(html_body, product)

        # Append "You Might Also Love" related products section
        related_section = make_related_products_section(products, product.get("handle", ""))
        html_body += related_section

        title = _extract_h1(html_body, h1_hint)
        tags  = _make_tags(product, fmt, keyword)

        print(f"  Title  : {title[:80]}")
        article = publish_article(blog, title, html_body, tags, img_url, dry_run)
        if article:
            created += 1
        print()
        time.sleep(1.0)

    print(f"Done — {created}/{count} blog posts published live.")
    if not dry_run:
        print(f"View at: https://{SHOP}/blogs\n")


if __name__ == "__main__":
    # Windows UTF-8 fix
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="MeeeShop Google Discover blog generator")
    ap.add_argument("--dry-run", action="store_true", help="Print only, no publishing")
    ap.add_argument("--count",   type=int, default=1,  help="Number of posts to create (default 1)")
    args = ap.parse_args()
    run(count=args.count, dry_run=args.dry_run)

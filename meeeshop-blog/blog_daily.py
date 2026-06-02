#!/usr/bin/env python3
"""
blog_daily.py — Google Discover-ready blog automation for MeeeShop
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Google Discover requirements met:
  - Featured image: 1200px wide (Shopify product image, copyright-free)
  - Title: compelling, non-clickbait, matches content intent
  - EEAT: first-person experience, expertise signals, trust indicators
  - High-intent formats: buying guide, comparison, problem-solver,
    trend report, outfit formula
  - Popular keywords embedded naturally
  - No AI-sounding filler or generic phrasing

AI: Gemini 2.0 Flash -> Groq Llama-3.3-70B -> OpenRouter Llama-3.3-70B (all free)
Image: Shopify product image (copyright-free, resized to 1200x675 via CDN)

Usage:
  python blog_daily.py              # create 3 draft blog posts
  python blog_daily.py --dry-run    # print only, no Shopify publish
  python blog_daily.py --count 1    # create 1 post
"""

import os, sys, re, time, random, argparse
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import requests
import ai_client

# ── credentials ───────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from secrets_manager import inject_to_env, get_secret
inject_to_env()

SHOP    = get_secret("SHOPIFY_STORE")
TOKEN   = get_secret("SHOPIFY_ACCESS_TOKEN")
API_VER = "2024-10"
BASE    = f"https://{SHOP}/admin/api/{API_VER}"
HEADERS = {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}

if not TOKEN:
    sys.exit("ERROR: SHOPIFY_ACCESS_TOKEN not set.")

STORE_URL = get_secret("SHOPIFY_SITE_URL", "https://us.meeeshop.com")

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
    raise RuntimeError(f"{method.upper()} {url} failed")


def get_blog_id() -> int:
    r = _req("get", f"{BASE}/blogs.json")
    r.raise_for_status()
    blogs = r.json().get("blogs", [])
    if blogs:
        return blogs[0]["id"]
    r2 = _req("post", f"{BASE}/blogs.json",
              json={"blog": {"title": "MeeeShop Fashion Journal"}})
    r2.raise_for_status()
    return r2.json()["blog"]["id"]


def fetch_products(limit=100) -> list:
    r = _req("get", f"{BASE}/products.json",
             params={"limit": limit, "fields": "id,title,handle,product_type,vendor,tags,variants,images,body_html"})
    r.raise_for_status()
    return r.json().get("products", [])


def make_featured_image(product_title: str, ptype: str, fmt: str) -> str:
    """
    Generate a professional 1200x630 editorial fashion image via Pollinations.ai.
    - AI-generated = copyright-free
    - Editorial/lifestyle style = clear, attractive, Google Discover eligible
    - Minimum 1200px wide (Google Discover requirement)
    """
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
    """Return the first product image URL (used inside the post card, not as featured image)."""
    images = product.get("images", [])
    return images[0]["src"] if images else None


def make_product_card(product: dict) -> str:
    """
    Build an inline HTML product card: image + title + price + Shop Now button.
    Google Discover safe — no scripts, pure HTML/inline CSS.
    Shows up naturally in the post so readers can buy without leaving.
    """
    title  = product["title"]
    price  = product["variants"][0]["price"] if product.get("variants") else "0"
    handle = product.get("handle", "")
    url    = f"{STORE_URL}/products/{handle}?utm_source=blog&utm_medium=post_card&utm_campaign=meeeshop" if handle else STORE_URL
    img    = product_img_url(product)

    img_html = (
        f'<img src="{img}" alt="{title}" '
        f'style="width:200px;height:200px;object-fit:cover;border-radius:10px;flex-shrink:0;" />'
        if img else ""
    )

    return f"""
<div style="background:#f8f6f3;border-radius:14px;padding:24px 28px;margin:32px 0;
            display:flex;flex-wrap:wrap;gap:24px;align-items:center;
            border:1px solid #eee;font-family:sans-serif;">
  {img_html}
  <div style="flex:1;min-width:200px;">
    <p style="font-size:11px;color:#999;margin:0 0 6px;text-transform:uppercase;letter-spacing:1.5px;font-weight:600;">Featured Pick</p>
    <h3 style="font-size:18px;font-weight:700;margin:0 0 8px;color:#1a1a1a;line-height:1.3;">{title}</h3>
    <p style="font-size:26px;font-weight:800;color:#1a1a1a;margin:0 0 6px;">${price}</p>
    <p style="font-size:12px;color:#777;margin:0 0 18px;">
      Free US shipping on orders $50+ &nbsp;&bull;&nbsp; 7-day easy returns &nbsp;&bull;&nbsp; Sizes XS–3X
    </p>
    <a href="{url}"
       style="background:#1a1a1a;color:#ffffff;padding:13px 30px;text-decoration:none;
              border-radius:8px;font-size:14px;font-weight:700;letter-spacing:0.5px;
              display:inline-block;transition:background 0.2s;">
      Shop Now &rarr;
    </a>
  </div>
</div>
"""


def inject_product_card(html_body: str, product: dict) -> str:
    """Insert the product card right after the intro paragraph (after first </p>)."""
    card = make_product_card(product)
    # Insert after the first closing </p> that follows the <h1>
    insert_after = re.search(r"</h1>\s*(<p>.*?</p>)", html_body, re.DOTALL | re.IGNORECASE)
    if insert_after:
        pos = insert_after.end()
        return html_body[:pos] + "\n" + card + html_body[pos:]
    # Fallback: insert after first </p> anywhere
    pos = html_body.find("</p>")
    if pos != -1:
        return html_body[:pos+4] + "\n" + card + html_body[pos+4:]
    return card + html_body


def publish_article(blog_id: int, title: str, body_html: str,
                    tags: list, image_url: str | None,
                    dry_run: bool = False) -> dict | None:
    if dry_run:
        print(f"  [DRY-RUN] '{title}'")
        if image_url:
            print(f"  Image  : {image_url[:90]}")
        print(f"  Preview: {re.sub(r'<[^>]+>',' ',body_html)[:180].strip()}…\n")
        return {"id": 0, "title": title}

    payload: dict = {
        "article": {
            "title": title,
            "body_html": body_html,
            "tags": ", ".join(tags),
            "published": False,  # draft — review before publishing
        }
    }
    if image_url:
        payload["article"]["image"] = {"src": image_url}

    r = _req("post", f"{BASE}/blogs/{blog_id}/articles.json", json=payload)
    if r.status_code in (200, 201):
        art = r.json().get("article", {})
        print(f"  Draft created: '{art.get('title')}' (ID {art.get('id')})")
        return art
    print(f"  FAILED {r.status_code}: {r.text[:150]}")
    return None


# ── high-intent blog formats ───────────────────────────────────────────────────

FORMATS = ["buying_guide", "comparison", "problem_solver", "trend_report", "outfit_formula"]

# High-search-volume keywords for women's fashion
SEED_KEYWORDS = [
    "women's fashion 2026", "affordable women's clothing USA",
    "summer dress outfits for women", "women's jeans styles guide",
    "casual chic outfits women", "women's fashion trends 2026",
    "cute outfits under $50", "stylish women's tops",
    "best dresses for women", "women's summer wardrobe essentials",
    "affordable boutique fashion USA", "women's outfit ideas",
    "how to style women's clothing", "plus size fashion tips",
    "work outfits for women", "women's weekend casual looks",
]

YEAR = datetime.now().year
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
    "7. Do NOT say 'as an AI' or reveal AI authorship in any way\n\n"
)


def _build_prompt(fmt: str, product: dict, keyword: str) -> tuple[str, str]:
    title = product["title"]
    ptype = (product.get("product_type") or "women's fashion").lower()
    price = product["variants"][0]["price"] if product.get("variants") else "49"
    handle = product.get("handle", "")
    url = f"{STORE_URL}/products/{handle}" if handle else STORE_URL

    base = (
        f"You are a fashion editor at MeeeShop, a USA women's clothing boutique.\n"
        f"Write a {MONTH} blog post. Target keyword: '{keyword}'\n"
        f"Feature product: {title} — ${price} ({url})\n"
        f"Category: {ptype}\n\n"
        f"{EEAT_RULES}"
        f"SEO rules:\n"
        f"- Use target keyword 3-4 times naturally\n"
        f"- Include 3-5 LSI keywords (related phrases)\n"
        f"- Link to product URL at least twice with natural anchor text\n"
        f"- H1 title must include year {YEAR} or 'for Women'\n\n"
        f"Store info: Free US shipping on orders $50+. Easy 7-day returns. Sizes XS-3X.\n\n"
    )

    if fmt == "buying_guide":
        prompt = base + (
            f"Format: Definitive Buying Guide\n"
            f"Write in HTML (<h1>,<h2>,<h3>,<p>,<ul>,<li>):\n"
            f"1. <h1> 'The Best {ptype.title()} for Women in {YEAR}: Our Editor's Guide'\n"
            f"2. <p> Hook — personal story: why I tested 12 options and THIS is my pick (80 words)\n"
            f"3. <h2> What Makes a Great {ptype.title()}? (4 criteria as bullets with brief explanations)\n"
            f"4. <h2> Our #1 Pick: {title} — Honest Review (120 words, first-person, mention price + URL twice)\n"
            f"5. <h2> How I Style It: 3 Real Outfits (H3 subheadings, 70 words each with occasion context)\n"
            f"6. <h2> Who Is This Perfect For? (50 words — be specific: body type, lifestyle, occasion)\n"
            f"7. <h2> Sizing & Fit Notes (40 words — real, not generic)\n"
            f"8. <p> Final verdict + CTA (shop link, price, free shipping reminder)\n"
            f"Target: 750-900 words. Output ONLY clean HTML, no markdown fences."
        )
        h1_hint = f"The Best {ptype.title()} for Women in {YEAR}: Our Editor's Guide"

    elif fmt == "comparison":
        prompt = base + (
            f"Format: Comparison Article — helps women choose the right style\n"
            f"Write in HTML:\n"
            f"1. <h1> '{title} vs. [2 similar alternatives]: Which Is Right for You in {YEAR}?'\n"
            f"2. <p> Intro — 'I get asked this question every week from our customers' (70 words)\n"
            f"3. <h2> Option 1: {title} — What I Love + Who It's For (100 words, link to URL)\n"
            f"4. <h2> Option 2: [Invent a plausible similar style] — Pros, Cons, Best For (80 words)\n"
            f"5. <h2> Option 3: [Another plausible alternative] — Pros, Cons, Best For (80 words)\n"
            f"6. <h2> Quick Comparison (HTML table: Style | Best For | Price Range | Verdict)\n"
            f"7. <h2> My Honest Verdict — The Winner for Most Women (80 words, direct recommendation)\n"
            f"8. <p> CTA to shop + URL\n"
            f"Target: 750-900 words. Output ONLY clean HTML."
        )
        h1_hint = f"{title} vs. Similar Styles: Which to Buy in {YEAR}"

    elif fmt == "problem_solver":
        # Pick a real shopping problem this product solves
        problems = {
            "dress":    "finding a flattering dress that works for multiple occasions",
            "jean":     "finding jeans that actually fit your body type",
            "top":      "building a versatile work-to-weekend wardrobe on a budget",
            "pant":     "finding the perfect pair of pants that look good all day",
            "skirt":    "styling a skirt for every occasion without overthinking it",
            "sweater":  "staying stylish and cozy at the same time",
            "jacket":   "layering outfits without looking bulky",
        }
        problem = next(
            (v for k, v in problems.items() if k in ptype.lower() or k in title.lower()),
            "dressing well on a budget without sacrificing style",
        )
        prompt = base + (
            f"Format: Problem-Solver — solving '{problem}' for women\n"
            f"Write in HTML:\n"
            f"1. <h1> Relatable title about the problem + the solution keyword\n"
            f"2. <p> Opening — 'I hear this from our customers constantly: {problem}' (80 words, empathetic)\n"
            f"3. <h2> Why This Problem Is So Frustrating (and Common) (60 words)\n"
            f"4. <h2> The Fix: {title} — Here's Exactly Why It Works (120 words, first-person, link URL twice)\n"
            f"5. <h2> 3 Real Outfit Solutions (H3 for each, 70 words each with specific styling instructions)\n"
            f"6. <h2> My Top 4 Styling Tips From 5 Years in Fashion (bullet list, specific and actionable)\n"
            f"7. <p> CTA: warm personal recommendation + URL + price + free shipping\n"
            f"Target: 700-850 words. Output ONLY clean HTML."
        )
        h1_hint = f"How to Finally Solve {problem.title()}"

    elif fmt == "trend_report":
        prompt = base + (
            f"Format: {MONTH} Trend Report\n"
            f"Write in HTML:\n"
            f"1. <h1> '{MONTH} Women's Fashion Trends: What I'm Seeing (and Wearing) Right Now'\n"
            f"2. <p> Intro — 'I've been tracking what real women are actually wearing, not just runways' (70 words)\n"
            f"3. Five trends, each as <h2> with trend name + 90-word description:\n"
            f"   - Trend #1 MUST be {title} with product URL linked\n"
            f"   - Trends #2-5: invent 4 real, current women's fashion micro-trends\n"
            f"   - Each trend: what it is, why it's trending, how to wear it\n"
            f"4. <h2> How to Mix These Trends Without Looking Overdone (60 words, practical)\n"
            f"5. <p> Shop the trends at MeeeShop + URL\n"
            f"Target: 750-900 words. Output ONLY clean HTML."
        )
        h1_hint = f"{MONTH} Women's Fashion Trends"

    else:  # outfit_formula
        prompt = base + (
            f"Format: 5-Outfit Formula — shows versatility of one piece\n"
            f"Write in HTML:\n"
            f"1. <h1> '5 Stunning Outfits You Can Build Around {title} (I Wore All 5)'\n"
            f"2. <p> Intro — 'The best fashion investment is a piece you can wear 5+ ways. "
            f"I put {title} to the test.' (70 words, first-person)\n"
            f"3. Five outfits as <h2> sections with creative names:\n"
            f"   e.g. 'Look 1: Sunday Brunch', 'Look 2: Office Polished', 'Look 3: Date Night'\n"
            f"   Each: what to pair it with, where to wear it, personal styling note (80-90 words)\n"
            f"4. <h2> Fit & Sizing Notes — The Honest Truth (40 words, specific, not generic)\n"
            f"5. <p> CTA: get yours, price, URL, 7-day returns mention\n"
            f"Target: 750-900 words. Output ONLY clean HTML."
        )
        h1_hint = f"5 Outfits You Can Build Around {title}"

    return prompt, h1_hint


def _extract_h1(html: str, fallback: str) -> str:
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.IGNORECASE | re.DOTALL)
    return re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else fallback


def _clean_html(raw: str) -> str:
    raw = raw.strip()
    raw = re.sub(r"^```html?\s*", "", raw, flags=re.IGNORECASE)
    return re.sub(r"\s*```$", "", raw).strip()


def _make_tags(product: dict, fmt: str, keyword: str) -> list[str]:
    base = ["fashion", "women fashion", get_secret("BRAND", "MeeeShop"), "USA fashion",
            "women's clothing", "affordable fashion", "style tips"]
    ptype = (product.get("product_type") or "").lower()
    fmt_tags = {
        "buying_guide":   ["buying guide", "fashion guide", "best picks 2026"],
        "comparison":     ["fashion comparison", "style guide", "what to buy"],
        "problem_solver": ["styling advice", "outfit help", "fashion tips"],
        "trend_report":   ["fashion trends 2026", "trending styles", "new in fashion"],
        "outfit_formula": ["outfit ideas", "how to style", "outfit inspiration"],
    }
    tags = base + fmt_tags.get(fmt, [])
    if ptype:
        tags.append(ptype)
    tags += [w for w in keyword.split() if len(w) > 3][:3]
    return list(dict.fromkeys(tags))[:20]


# ── main ──────────────────────────────────────────────────────────────────────
def run(count: int = 3, dry_run: bool = False):
    print(f"\n{'='*62}")
    print(f"  MeeeShop Blog Automation — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  Posts: {count} | Dry-run: {dry_run}")
    print(f"{'='*62}\n")

    print("Fetching products…")
    products = fetch_products(limit=100)
    if not products:
        sys.exit("ERROR: No products returned.")
    # Prefer products that have images for the featured 1200px image
    products_with_imgs = [p for p in products if p.get("images")]
    pool = products_with_imgs if len(products_with_imgs) >= count else products
    print(f"  {len(products)} products ({len(products_with_imgs)} with images)\n")

    blog_id = None if dry_run else get_blog_id()
    if not dry_run:
        print(f"  Blog ID: {blog_id}\n")

    chosen   = random.sample(pool, min(count, len(pool)))
    fmts     = random.sample(FORMATS, min(count, len(FORMATS)))
    keywords = random.sample(SEED_KEYWORDS, min(count, len(SEED_KEYWORDS)))

    created = 0
    for i, product in enumerate(chosen):
        fmt     = fmts[i % len(fmts)]
        keyword = keywords[i % len(keywords)]

        print(f"[{i+1}/{count}] {fmt} | keyword: '{keyword}'")
        print(f"  Product: {product['title'][:70]}")

        ptype   = (product.get("product_type") or "women's fashion").lower()
        img_url = make_featured_image(product["title"], ptype, fmt)
        print(f"  Image  : AI editorial (Pollinations.ai 1200x630)")

        prompt, h1_hint = _build_prompt(fmt, product, keyword)
        html_body = ai_client.generate(prompt, max_tokens=1400, temperature=0.75)

        if not html_body:
            print("  [AI] all providers failed — skipping\n")
            continue

        html_body = _clean_html(html_body)
        html_body = inject_product_card(html_body, product)   # embed Shop Now card
        title     = _extract_h1(html_body, h1_hint)
        tags      = _make_tags(product, fmt, keyword)

        print(f"  Title  : {title[:80]}")
        article = publish_article(blog_id, title, html_body, tags, img_url, dry_run)
        if article:
            created += 1
        time.sleep(0.8)

    print(f"\nDone — {created}/{count} blog drafts created.")
    if not dry_run:
        print(f"Review + publish at: https://{SHOP.replace('us-','')}/admin/articles\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="Print only, no publishing")
    ap.add_argument("--count",   type=int, default=3, help="Posts to create (default 3)")
    args = ap.parse_args()
    run(count=args.count, dry_run=args.dry_run)

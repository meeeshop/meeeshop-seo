#!/usr/bin/env python3
"""
revert_injected_links.py — Restore corrupted articles by recreating them via the
full blog_daily pipeline (EEAT content, featured image, product cards, SEO metafields).

For each article containing injected meeeshop links the script:
  1. Picks a relevant product + format + keyword from the blog_daily pool
  2. Generates full Google Discover-ready content (EEAT, product card, related products)
  3. Generates SEO metadata (title_tag, description_tag, featured image 1200x630)
  4. Deletes the corrupted article
  5. Re-publishes with the SAME handle so the URL stays identical
  6. Sets SEO metafields on the new article

Usage:
  python revert_injected_links.py --dry-run        # Preview only, no changes
  python revert_injected_links.py --apply          # Fix known corrupted articles
  python revert_injected_links.py --apply --all    # Fix ALL articles with meeeshop links


Batch mode (for large stores — mirrors internal_linker.yml pattern):
  python revert_injected_links.py --apply --all --batch-size 15 --batch-index 0
  python revert_injected_links.py --apply --all --batch-size 15 --batch-index 1
  ...
"""

import os, sys, re, time, random, argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from secrets_manager import inject_to_env, get_secret
inject_to_env()

import requests

# ── Reuse the full blog_daily pipeline ────────────────────────────────────────
import blog_daily as bd

STORE = get_secret("SHOPIFY_STORE")
TOKEN = get_secret("SHOPIFY_ACCESS_TOKEN")
HEADS = {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}
BASE  = f"https://{STORE}/admin/api/2024-01"

REQUEST_DELAY = 0.7
MAX_RETRIES   = 5

# Known corrupted articles — targeted fix without scanning everything
AFFECTED_TITLES = [
    "How to Style 2026's Boldest Dress Colors for Any Occasion",
    "How to Build a Capsule Wardrobe Women Will Love in 2026: Finding the Perfect Dress for Every Occasion",
    "5 Stunning Outfits You Can Build Around Asymmetrical Ruffle Mini Dress for Women in 2026 (I Wore All 5 This Month)",
    "The Best Dresses for Women in 2026: Our Editor's Guide",
    "The Ultimate 2026 Dress Guide for Fall Office Parties",
    "Affordable Jeans That Look Expensive: Must-Haves This Fall",
    "Women's Spring Outfit Ideas 2026: Building a Versatile Wardrobe on a Budget with MeeeShop",
    "Everything About Sizing & Measurements",
    "The Most Flattering Skirts for Curvy Women: Style Tips You Need",
    "Finding the Perfect Fit: Tips for Choosing the Right Size in Curvy Plus-Size Clothing",
    "Curvy Women's Jeans: Finding the Perfect Fit for Every Body",
    "Essential Tips For Plus Size Women Clothing.",
    "Trendy Plus Size Clothing",
    "Women Plus Size Outerwear",
    "Women's Fashion | New Styles that Make it your Wardrobe",
]


def _req(method: str, url: str, **kwargs) -> requests.Response:
    kwargs.setdefault("timeout", 30)
    for attempt in range(MAX_RETRIES):
        r = requests.request(method, url, headers=HEADS, **kwargs)
        if r.status_code == 429:
            wait = max(int(float(r.headers.get("Retry-After", 4))), 2 ** attempt)
            print(f"  [RATE LIMIT] waiting {wait}s...")
            time.sleep(wait)
            continue
        if r.status_code >= 500:
            wait = 2 ** attempt
            print(f"  [SERVER ERROR] {r.status_code} — waiting {wait}s...")
            time.sleep(wait)
            continue
        return r
    r.raise_for_status()
    return r


def _has_injected_links(html: str) -> bool:
    return bool(re.search(r'<a\s[^>]*href=["\'][^"\']*meeeshop', html, re.IGNORECASE))


def fetch_all_blogs() -> list:
    r = _req("GET", f"{BASE}/blogs.json?limit=250")
    r.raise_for_status()
    time.sleep(REQUEST_DELAY)
    return r.json().get("blogs", [])


def fetch_articles(blog_id: int) -> list:
    articles = []
    url = f"{BASE}/blogs/{blog_id}/articles.json?limit=250"
    while url:
        r = _req("GET", url)
        r.raise_for_status()
        articles.extend(r.json().get("articles", []))
        link = r.headers.get("Link", "")
        url = None
        for part in link.split(","):
            if 'rel="next"' in part:
                url = part.split("<")[1].split(">")[0]
        time.sleep(REQUEST_DELAY)
    return articles


def delete_article(blog_id: int, article_id: int) -> bool:
    r = _req("DELETE", f"{BASE}/blogs/{blog_id}/articles/{article_id}.json")
    time.sleep(REQUEST_DELAY)
    return r.status_code == 200


def publish_article_with_handle(blog_id: int, title: str, body_html: str,
                                 handle: str, tags: list,
                                 img_url: str, img_alt: str, meta_desc: str) -> dict | None:
    """Same as blog_daily.publish_article but forces a specific handle."""
    payload = {
        "article": {
            "title":        title,
            "body_html":    body_html,
            "summary_html": f"<p>{meta_desc}</p>",
            "tags":         ", ".join(tags),
            "published":    True,
            "handle":       handle,  # preserve original URL
        }
    }
    if img_url:
        payload["article"]["image"] = {"src": img_url, "alt": img_alt}

    r = _req("POST", f"{BASE}/blogs/{blog_id}/articles.json", json=payload)
    time.sleep(REQUEST_DELAY)
    if r.status_code in (200, 201):
        return r.json().get("article", {})
    print(f"  [PUBLISH FAILED] {r.status_code}: {r.text[:300]}")
    return None


def _pick_product_for_title(title: str, products: list) -> dict:
    """Pick a product whose type or title keywords match the article title."""
    title_lower = title.lower()
    type_hints = {
        "dress":    ["dress"],
        "jean":     ["jean", "denim"],
        "skirt":    ["skirt"],
        "top":      ["top", "blouse", "shirt"],
        "jacket":   ["jacket", "coat"],
        "sweater":  ["sweater", "cardigan"],
        "plus":     ["plus", "curvy"],
        "size":     ["plus", "curvy"],
        "handbag":  ["handbag", "bag", "purse"],
    }
    for hint, ptypes in type_hints.items():
        if hint in title_lower:
            matches = [p for p in products
                       if any(pt in (p.get("product_type") or "").lower() for pt in ptypes)
                       or any(pt in p.get("title", "").lower() for pt in ptypes)]
            if matches:
                return random.choice(matches)
    # Fallback: any product with an image
    with_imgs = [p for p in products if p.get("images")]
    return random.choice(with_imgs) if with_imgs else random.choice(products)


def _pick_keyword_for_title(title: str) -> str:
    """Pick the best seed keyword from blog_daily that fits the article title."""
    title_lower = title.lower()
    for kw in bd.SEED_KEYWORDS:
        kw_words = kw.lower().split()
        if any(w in title_lower for w in kw_words if len(w) > 4):
            return kw
    return random.choice(bd.SEED_KEYWORDS)


def recreate_article(blog_id: int, original_title: str, handle: str,
                     original_tags: str, products: list, all_blogs: list,
                     blog_obj: dict) -> tuple[bool, str]:
    """
    Generate full EEAT content via blog_daily pipeline and republish.
    Returns (success, new_article_id).
    """
    import ai_client

    product = _pick_product_for_title(original_title, products)
    fmt     = random.choice(bd.FORMATS)
    keyword = _pick_keyword_for_title(original_title)
    ptype   = (product.get("product_type") or "women's fashion").lower()

    print(f"  Product : {product['title'][:60]}")
    print(f"  Format  : {fmt} | Keyword: '{keyword}'")

    # 1. Generate body content (EEAT prompt from blog_daily)
    prompt, h1_hint = bd._build_prompt(fmt, product, keyword)
    print("  Generating EEAT content...")
    raw = ai_client.generate(prompt, max_tokens=1600, temperature=0.75)
    if not raw:
        return False, "AI content generation failed"

    body_html  = bd._clean_html(raw)

    # 2. SEO metadata
    print("  Generating SEO metadata...")
    seo = bd.generate_seo_meta(original_title, keyword, product["title"], ptype, h1_hint)
    print(f"  SEO title : {seo['seo_title']}")
    print(f"  Meta desc : {seo['meta_desc'][:80]}...")

    # 3. Featured image (1200x630 via Shopify CDN or Pollinations fallback)
    img_url = bd.make_featured_image_url(product, fmt)
    img_src = "Shopify CDN" if product.get("images") else "Pollinations.ai"
    print(f"  Image     : {img_src} 1200x630")

    # 4. Product card + related products section
    body_html = bd.inject_product_card(body_html, product, keyword)
    body_html += bd.make_related_products_section(products, product.get("handle", ""), keyword)

    # 5. Tags (reuse original tags + blog_daily enrichment)
    new_tags = bd._make_tags(product, fmt, keyword)
    if original_tags:
        for t in original_tags.split(","):
            t = t.strip()
            if t and t not in new_tags:
                new_tags.append(t)
    new_tags = list(dict.fromkeys(new_tags))[:20]

    return body_html, seo, img_url, new_tags


def collect_targets(all_flag: bool) -> list[dict]:
    """
    Scan all blogs and return a flat list of articles that need recreation.
    Each entry: {blog_id, blog_title, article_id, title, handle, tags}
    """
    blogs   = fetch_all_blogs()
    targets = []
    for blog in blogs:
        blog_id    = blog["id"]
        blog_title = blog.get("title", "")
        articles   = fetch_articles(blog_id)
        for article in articles:
            title     = article.get("title", "")
            body_html = article.get("body_html", "") or ""
            if all_flag:
                if not _has_injected_links(body_html):
                    continue
            else:
                if title not in AFFECTED_TITLES:
                    continue
                if not _has_injected_links(body_html):
                    continue
            targets.append({
                "blog_id":    blog_id,
                "blog_title": blog_title,
                "article_id": article["id"],
                "title":      title,
                "handle":     article.get("handle", ""),
                "tags":       article.get("tags", "") or "",
            })
    return targets


def main():
    parser = argparse.ArgumentParser(
        description="Restore corrupted articles using the full blog_daily EEAT pipeline"
    )
    parser.add_argument("--dry-run",     action="store_true", help="Preview without changes")
    parser.add_argument("--apply",       action="store_true", help="Delete + recreate articles")
    parser.add_argument("--all",         action="store_true", help="Scan ALL articles (not just known list)")
    parser.add_argument("--batch-size",  type=int, default=15, help="Articles per batch (default 15)")
    parser.add_argument("--batch-index", type=int, default=None,
                        help="Which batch to process (0-based). Omit to process all in one run.")
    parser.add_argument("--count-only",  action="store_true",
                        help="Print total article count and exit (used by workflow setup job)")
    args = parser.parse_args()

    if not args.dry_run and not args.apply and not args.count_only:
        print("Specify --dry-run, --apply, or --count-only")
        sys.exit(1)

    # ── count-only mode: used by the workflow setup job to build the batch matrix ──
    if args.count_only:
        targets = collect_targets(args.all)
        print(len(targets))
        return

    scope = "ALL articles with meeeshop links" if args.all else f"{len(AFFECTED_TITLES)} known affected articles"
    batch_label = f"batch {args.batch_index}/{(args.batch_size)}" if args.batch_index is not None else "all batches"
    print(f"Mode:        {'DRY RUN' if args.dry_run else 'APPLY'}")
    print(f"Scope:       {scope}")
    print(f"Batch size:  {args.batch_size}  |  Processing: {batch_label}")
    print("=" * 70)

    # Collect the full target list then slice to this batch
    targets = collect_targets(args.all)
    total_targets = len(targets)
    print(f"Total articles to fix: {total_targets}")

    if args.batch_index is not None:
        start = args.batch_index * args.batch_size
        end   = start + args.batch_size
        targets = targets[start:end]
        print(f"This batch: [{start}:{end}] → {len(targets)} articles")

    if not targets:
        print("Nothing to do.")
        return

    print()

    # Pre-load products once — reused for all articles in this batch
    print("Fetching products...")
    products = bd.fetch_products(limit=100)
    if not products:
        sys.exit("ERROR: No products returned from Shopify.")
    print(f"  {len(products)} products loaded\n")

    all_blogs  = bd.get_all_blogs()
    total_ok   = 0
    total_fail = 0

    for item in targets:
        blog_id    = item["blog_id"]
        blog_title = item["blog_title"]
        title      = item["title"]
        handle     = item["handle"]
        article_id = item["article_id"]
        orig_tags  = item["tags"]

        print(f"\n[{blog_title}] '{title}'")
        print(f"  Handle: {handle}")

        if args.dry_run:
            kw  = _pick_keyword_for_title(title)
            fmt = random.choice(bd.FORMATS)
            print(f"  [DRY RUN] Would recreate — format: {fmt}, keyword: '{kw}'")
            continue

        # Generate full EEAT content
        result = recreate_article(
            blog_id, title, handle, orig_tags,
            products, all_blogs, {}
        )
        if isinstance(result, tuple) and len(result) == 2 and isinstance(result[0], bool):
            print(f"  [FAIL] {result[1]}")
            total_fail += 1
            continue

        new_body, seo, img_url, new_tags = result

        # Delete corrupted article
        if not delete_article(blog_id, article_id):
            print(f"  [FAIL] Could not delete article — skipping")
            total_fail += 1
            continue
        print(f"  Deleted (ID {article_id})")

        # Re-publish with same handle
        new_art = publish_article_with_handle(
            blog_id, title, new_body, handle,
            new_tags, img_url, seo["img_alt"], seo["meta_desc"]
        )

        if new_art:
            new_id = new_art.get("id")
            print(f"  ✓ Recreated (new ID {new_id}) — URL preserved")
            bd.set_article_seo_metafields(blog_id, new_id, seo["seo_title"], seo["meta_desc"])
            print(f"  ✓ SEO metafields set")
            total_ok += 1
        else:
            print(f"  ✗ Re-publish failed — '{title}' deleted but NOT restored!")
            total_fail += 1

        time.sleep(1.0)

    print("\n" + "=" * 70)
    print(f"SUMMARY: recreated={total_ok}  failed={total_fail}  batch={args.batch_index}")
    print("=" * 70)

    if total_fail > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()

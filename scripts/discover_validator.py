#!/usr/bin/env python3
"""
discover_validator.py — Google Discover Eligibility Validator for MeeeShop
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Audits published Shopify blog articles against Google Discover requirements:
  - Featured image size (minimum 1200px wide)
  - E-E-A-T authorship (no generic names like "Editorial Team" or "Admin")
  - Image ALT text (descriptive, keyword-rich)
  - Meta description & SEO title (populated in metafields and proper length)
  - HTML structure (presence of H2/H3 headings, blockquotes, no double-H1s)
  - Robots meta tag availability (max-image-preview:large check on homepage)
"""

import os
import sys
import re
import json
import time
import argparse
from pathlib import Path
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup

# ── path setup ────────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from secrets_manager import inject_to_env, get_secret

inject_to_env()

# ── credentials ───────────────────────────────────────────────────────────────
SHOP      = get_secret("SHOPIFY_STORE")
TOKEN     = get_secret("SHOPIFY_ACCESS_TOKEN")
STORE_URL = get_secret("STORE_BASE_URL").rstrip("/")
API_VER   = "2024-10"
BASE      = f"https://{SHOP}/admin/api/{API_VER}"
SHP_HDR   = {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}

# Try importing Pillow to check image sizes dynamically
try:
    from PIL import Image
    from io import BytesIO
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False

GENERIC_AUTHORS = [
    "editorial team", "meeeshop editorial team", "admin", "administrator",
    "meeeshop", "author", "staff", "staff writer", "writer"
]

def _req(method, url, **kw):
    for attempt in range(4):
        try:
            r = getattr(requests, method)(url, headers=SHP_HDR, timeout=20, **kw)
            if r.status_code == 429:
                wait = int(float(r.headers.get("Retry-After", 4)))
                time.sleep(wait)
                continue
            return r
        except requests.exceptions.ConnectionError:
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"{method.upper()} {url} failed after 4 attempts")

def get_all_blogs() -> list:
    r = _req("get", f"{BASE}/blogs.json")
    r.raise_for_status()
    return r.json().get("blogs", [])

def get_articles(blog_id: int, limit: int = 10) -> list:
    r = _req("get", f"{BASE}/blogs/{blog_id}/articles.json", params={"limit": limit})
    r.raise_for_status()
    return r.json().get("articles", [])

def get_metafields(blog_id: int, article_id: int) -> list:
    r = _req("get", f"{BASE}/blogs/{blog_id}/articles/{article_id}/metafields.json")
    r.raise_for_status()
    return r.json().get("metafields", [])

def verify_live_robots_tag() -> tuple[bool, str]:
    """Inspects the live theme layout header for the max-image-preview:large tag."""
    try:
        r = requests.get(STORE_URL, timeout=15)
        if r.status_code != 200:
            return False, f"Failed to fetch homepage: HTTP {r.status_code}"
        
        soup = BeautifulSoup(r.text, "html.parser")
        meta_robots = soup.find("meta", attrs={"name": "robots"})
        if meta_robots:
            content = meta_robots.get("content", "").lower()
            if "max-image-preview:large" in content:
                return True, "Found 'max-image-preview:large' in meta robots tag"
            return False, f"Meta robots tag found but content is '{content}' (missing max-image-preview:large)"
        return False, "No <meta name=\"robots\"> tag found on homepage"
    except Exception as e:
        return False, f"Error checking live robots tag: {e}"

def check_image_dimensions(url: str) -> tuple[int, int, str]:
    """Downloads image headers/bytes to verify actual width & height."""
    if not HAS_PILLOW:
        return 0, 0, "Pillow library not installed; skipping exact dimension check"
    try:
        # Fetch only first 128KB of image to get size quickly
        h = {"Range": "bytes=0-131072"}
        r = requests.get(url, headers=h, timeout=10)
        if r.status_code in (200, 206):
            img = Image.open(BytesIO(r.content))
            return img.width, img.height, "Success"
        return 0, 0, f"HTTP {r.status_code} on image download"
    except Exception as e:
        # Fallback to full download if range request fails
        try:
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                img = Image.open(BytesIO(r.content))
                return img.width, img.height, "Success"
            return 0, 0, f"HTTP {r.status_code}"
        except Exception as err:
            return 0, 0, str(err)

def validate_article(blog_title: str, blog_id: int, article: dict) -> dict:
    title = article.get("title", "")
    author = article.get("author", "").strip()
    body_html = article.get("body_html", "")
    article_id = article["id"]
    
    report = {
        "title": title,
        "id": article_id,
        "author": author,
        "blog": blog_title,
        "score": 100,
        "checks": [],
        "warnings": [],
        "errors": []
    }
    
    # 1. E-E-A-T Authorship Check
    author_lower = author.lower()
    if not author:
        report["errors"].append("EEAT: Author field is empty.")
        report["score"] -= 25
    elif any(g in author_lower for g in GENERIC_AUTHORS):
        report["warnings"].append(f"EEAT: Author '{author}' appears generic. Use a fictional style persona (e.g. 'Elena Vance, MeeeShop Lead Stylist') instead.")
        report["score"] -= 15
    else:
        report["checks"].append(f"EEAT: Named author '{author}' is present.")

    # 2. Featured Image Check
    image = article.get("image")
    if not image:
        report["errors"].append("IMAGE: No featured image is set on the article.")
        report["score"] -= 30
    else:
        src = image.get("src", "")
        alt = image.get("alt", "").strip()
        
        # Check ALT Text
        if not alt:
            report["errors"].append("IMAGE: Featured image is missing ALT text.")
            report["score"] -= 10
        elif len(alt) < 15:
            report["warnings"].append(f"IMAGE: ALT text is very short ('{alt}'). Make it more descriptive (10-15 words).")
            report["score"] -= 5
        else:
            report["checks"].append(f"IMAGE: Featured image has ALT text ('{alt}').")

        # Check Dimensions
        if src:
            width = height = 0
            if "_1200x630" in src or "_1200x" in src:
                # Shopify crop suffix check
                width, height = 1200, 630
                report["checks"].append("IMAGE: Image URL contains Shopify 1200px crop transform.")
            elif HAS_PILLOW:
                width, height, status = check_image_dimensions(src)
                if width > 0:
                    report["checks"].append(f"IMAGE: Image resolution resolved as {width}x{height}px.")
                else:
                    report["warnings"].append(f"IMAGE: Could not check image resolution ({status}).")
            else:
                report["warnings"].append("IMAGE: Could not verify image dimensions (Pillow missing). Ensure the image is at least 1200px wide.")
            
            if width > 0 and width < 1200:
                report["errors"].append(f"IMAGE: Featured image width is {width}px. Discover requires at least 1200px wide.")
                report["score"] -= 20
        else:
            report["errors"].append("IMAGE: Image object exists but has no source URL.")
            report["score"] -= 20

    # 3. SEO Metafields Check (global.title_tag, global.description_tag)
    metafields = get_metafields(blog_id, article_id)
    title_tag = next((m["value"] for m in metafields if m["namespace"] == "global" and m["key"] == "title_tag"), None)
    desc_tag = next((m["value"] for m in metafields if m["namespace"] == "global" and m["key"] == "description_tag"), None)
    
    if not title_tag:
        report["warnings"].append("SEO: Custom SEO Title Tag metafield (global.title_tag) is missing.")
        report["score"] -= 10
    else:
        length = len(title_tag)
        if length < 40 or length > 65:
            report["warnings"].append(f"SEO: Title Tag is {length} chars (suggested: 50-60 chars). Value: '{title_tag}'")
            report["score"] -= 5
        else:
            report["checks"].append("SEO: Title Tag metafield is set and has optimal length.")

    if not desc_tag:
        report["warnings"].append("SEO: Custom Meta Description metafield (global.description_tag) is missing.")
        report["score"] -= 10
    else:
        length = len(desc_tag)
        if length < 120 or length > 160:
            report["warnings"].append(f"SEO: Meta Description is {length} chars (suggested: 140-155 chars). Value: '{desc_tag}'")
            report["score"] -= 5
        else:
            report["checks"].append("SEO: Meta Description metafield is set and has optimal length.")

    # 4. HTML Content Analysis
    if not body_html:
        report["errors"].append("CONTENT: Article body is completely empty.")
        report["score"] -= 20
    else:
        soup = BeautifulSoup(body_html, "html.parser")
        
        # Check H1 duplication
        h1s = soup.find_all("h1")
        if h1s:
            report["warnings"].append(f"CONTENT: Found {len(h1s)} <h1> tag(s) inside the body. The Shopify template already renders the title in H1, so body H1s create duplicates. Use H2 instead.")
            report["score"] -= 10
            
        # Check subheadings (H2/H3 structure)
        h2s = soup.find_all("h2")
        h3s = soup.find_all("h3")
        if not h2s:
            report["warnings"].append("CONTENT: No H2 headings found in article body. Add sections to break up content.")
            report["score"] -= 5
        else:
            report["checks"].append(f"CONTENT: Found {len(h2s)} H2 heading(s).")
            
        # Check for variety blockquotes
        blockquotes = soup.find_all("blockquote")
        if not blockquotes:
            report["warnings"].append("CONTENT: No blockquotes or visual callouts found. Use them to break text blocks and prevent automated pattern matching.")
        else:
            report["checks"].append("CONTENT: Visual callout/blockquote is present.")
            
        # Check for spammy inline product links (Redundant if utilizing product cards)
        links = soup.find_all("a")
        product_links = [l for l in links if "/products/" in l.get("href", "")]
        if len(product_links) > 3:
            report["warnings"].append(f"CONTENT: Found {len(product_links)} product links inside text. Rely on styling widgets and product cards; too many inline links looks spammy to Discover.")
            report["score"] -= 5
            
        # Check Q&A sections
        text_lower = soup.get_text().lower()
        has_qa = any(q in text_lower for q in ["faq", "frequently asked", "q&a", "question", "why does", "what is", "how to style"])
        if not has_qa:
            report["warnings"].append("CONTENT: No structured FAQ/Q&A or 'why/what/how' headings found to answer shopper queries.")
        else:
            report["checks"].append("CONTENT: Helpful Q&A or query-answering phrasing is present.")

    # Normalize score
    report["score"] = max(0, report["score"])
    return report

def main():
    parser = argparse.ArgumentParser(description="Audit Shopify blog posts for Google Discover readiness")
    parser.add_argument("--limit", type=int, default=5, help="Number of articles to scan per blog (default: 5)")
    parser.add_argument("--save-report", action="store_true", help="Save the output to discover_audit_report.json")
    args = parser.parse_args()

    print("=" * 75)
    print("GOOGLE DISCOVER ELIGIBILITY AUDIT")
    print("=" * 75)
    
    if not SHOP or not TOKEN:
        sys.exit("ERROR: Shopify configuration missing. Check secrets.enc.")
        
    print(f"Store: {SHOP}")
    
    # Check live site meta tags
    print("\n[*] Auditing live theme header for robots tag...")
    robots_ok, robots_msg = verify_live_robots_tag()
    if robots_ok:
        print(f"  [OK] {robots_msg}")
    else:
        print(f"  [!] WARNING: {robots_msg}")
        print("      Action required: Add <meta name=\"robots\" content=\"max-image-preview:large\"> before </head> in layout/theme.liquid")

    print("\n[*] Fetching blogs...")
    try:
        blogs = get_all_blogs()
    except Exception as e:
        sys.exit(f"ERROR: Could not fetch blogs: {e}")
        
    print(f"Found {len(blogs)} blog(s)")
    
    all_reports = []
    
    for blog in blogs:
        blog_title = blog["title"]
        blog_id = blog["id"]
        print(f"\nScanning blog: '{blog_title}' (ID {blog_id})...")
        
        try:
            articles = get_articles(blog_id, limit=args.limit)
        except Exception as e:
            print(f"  [!] Failed to get articles: {e}")
            continue
            
        print(f"  Found {len(articles)} article(s)")
        
        for art in articles:
            print(f"    - Auditing: '{art.get('title')[:50]}...'")
            rep = validate_article(blog_title, blog_id, art)
            all_reports.append(rep)
            
            # Print summary for this article
            color = "\033[92m" if rep["score"] >= 80 else ("\033[93m" if rep["score"] >= 50 else "\033[91m")
            reset = "\033[0m"
            print(f"      Discover Score: {color}{rep['score']}/100{reset}")
            
            for err in rep["errors"]:
                print(f"      [X] ERROR  : {err}")
            for wrn in rep["warnings"]:
                print(f"      [!] WARNING: {wrn}")
            time.sleep(0.3)

    # Calculate overall stats
    if all_reports:
        avg_score = sum(r["score"] for r in all_reports) / len(all_reports)
        total_errors = sum(len(r["errors"]) for r in all_reports)
        total_warnings = sum(len(r["warnings"]) for r in all_reports)
        
        print("\n" + "=" * 75)
        print("SUMMARY REPORT")
        print("=" * 75)
        print(f"Total articles audited  : {len(all_reports)}")
        print(f"Average Discover Score  : {avg_score:.1f}/100")
        print(f"Total critical errors   : {total_errors}")
        print(f"Total quality warnings  : {total_warnings}")
        print("=" * 75)
        
        if args.save_report:
            out_file = Path("discover_audit_report.json")
            out_file.write_text(json.dumps(all_reports, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"Report saved to {out_file.absolute()}")
    else:
        print("\nNo articles found to audit.")

if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()

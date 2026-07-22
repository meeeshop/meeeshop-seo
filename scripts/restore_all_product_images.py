#!/usr/bin/env python3
"""
restore_all_product_images.py — Scans articles updated today and restores missing product images & product card widgets.
"""

import os, sys, re, time, requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse

SEO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SEO_DIR)
os.chdir(SEO_DIR)

from secrets_manager import inject_to_env, get_secret
inject_to_env()

SHOP      = get_secret("SHOPIFY_STORE")
TOKEN     = get_secret("SHOPIFY_ACCESS_TOKEN")
API_VER   = "2024-10"
BASE      = f"https://{SHOP}/admin/api/{API_VER}"
HEADERS   = {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}
STORE_URL = get_secret("STORE_BASE_URL") or f"https://{SHOP}"

def get_product_by_handle(handle: str) -> dict | None:
    try:
        r = requests.get(f"{BASE}/products.json?handle={handle}", headers=HEADERS, timeout=15)
        if r.status_code == 200:
            prods = r.json().get("products", [])
            if prods:
                return prods[0]
    except Exception as e:
        print(f"    [Warning] Could not fetch product '{handle}': {e}")
    return None

def build_product_card_html(prod: dict) -> str:
    title = prod.get("title", "")
    handle = prod.get("handle", "")
    images = prod.get("images", [])
    img_src = images[0]["src"] if images else ""
    variants = prod.get("variants", [])
    price = variants[0]["price"] if variants else "0.00"
    prod_url = f"{STORE_URL}/products/{handle}"

    return f"""
<div class="meee-product-card" style="background:#f8f6f3; border:1px solid #e0deda; border-radius:10px; padding:20px; margin:28px 0; font-family:sans-serif;">
  <div style="display:flex; flex-wrap:wrap; gap:20px; align-items:center;">
    <div style="flex:0 0 180px; max-width:180px;">
      <a href="{prod_url}">
        <img src="{img_src}" alt="{title}" style="width:100%; height:auto; border-radius:8px; object-fit:cover; display:block;" />
      </a>
    </div>
    <div style="flex:1; min-width:220px;">
      <span style="font-size:12px; font-weight:bold; letter-spacing:1px; color:#8b263e; text-transform:uppercase;">Featured Look</span>
      <h4 style="margin:6px 0; font-size:20px; color:#222; font-weight:600;">{title}</h4>
      <p style="margin:0 0 14px 0; font-size:18px; font-weight:bold; color:#8b263e;">${price} USD</p>
      <a href="{prod_url}" style="display:inline-block; background:#222; color:#fff; padding:12px 24px; border-radius:6px; text-decoration:none; font-weight:bold; font-size:14px; transition:background 0.2s;">View Product Details</a>
    </div>
  </div>
</div>
"""

def restore_article(blog_id: int, article: dict) -> bool:
    art_id = article["id"]
    title  = article.get("title", "")
    body   = article.get("body_html", "")
    soup   = BeautifulSoup(body, "html.parser")

    # Check if article contains any product images
    imgs = soup.find_all("img")
    has_prod_img = any("/products/" in img.get("src", "").lower() or "cdn.shopify.com" in img.get("src", "").lower() for img in imgs)

    # Extract product handles
    handles = []
    for l in soup.find_all("a"):
        href = l.get("href", "")
        if "/products/" in href:
            path = urlparse(href).path
            m = re.search(r"/products/([^/?]+)", path)
            if m:
                h = m.group(1)
                if h not in handles:
                    handles.append(h)

    if not handles:
        return False

    # Check if Q&A is at the top — move to bottom if needed
    body_changed = False
    text_lower = body.lower()

    # Move top Q&A to bottom if present near beginning
    qa_div = soup.find(id="shoppers-qa") or soup.find(class_="shoppers-qa")
    if qa_div and qa_div != soup.contents[-1]:
        qa_div.extract()
        soup.append(qa_div)
        body_changed = True

    # If product image is missing from body, inject featured product card widget
    if not has_prod_img and handles:
        main_h = handles[0]
        prod = get_product_by_handle(main_h)
        if prod and prod.get("images"):
            card_html = build_product_card_html(prod)
            card_soup = BeautifulSoup(card_html, "html.parser")
            first_p = soup.find("p") or soup.find("h2")
            if first_p:
                first_p.insert_after(card_soup)
            else:
                soup.insert(0, card_soup)
            body_changed = True
            print(f"  [RESTORE] Injected featured product card with image for '{prod['title']}'")

    if body_changed:
        new_body = str(soup)
        r = requests.put(f"{BASE}/blogs/{blog_id}/articles/{art_id}.json",
                         headers=HEADERS, json={"article": {"id": art_id, "body_html": new_body}}, timeout=15)
        if r.status_code == 200:
            print(f"  ✓ Restored article {art_id}: '{title}'")
            return True
        else:
            print(f"  [!] Failed to update article {art_id}: HTTP {r.status_code}")
    else:
        print(f"  [OK] Article {art_id}: '{title}' images intact.")

    return False

def main():
    print("=" * 70)
    print("MEEESHOP PRODUCT IMAGE & PRODUCT CARD RESTORER")
    print("=" * 70)

    r = requests.get(f"{BASE}/blogs.json", headers=HEADERS, timeout=15)
    blogs = r.json().get("blogs", [])
    total_restored = 0

    for b in blogs:
        b_id = b["id"]
        b_title = b["title"]
        print(f"\nProcessing blog: '{b_title}' (ID {b_id})...")

        arts_res = requests.get(f"{BASE}/blogs/{b_id}/articles.json?limit=250", headers=HEADERS, timeout=20)
        articles = arts_res.json().get("articles", [])

        for art in articles:
            # Check articles updated today
            up_at = art.get("updated_at", "")
            if "2026-07-22" in up_at:
                res = restore_article(b_id, art)
                if res:
                    total_restored += 1
                time.sleep(0.5)

    print(f"\n✓ Completed. Restored product images & cards for {total_restored} articles.")

if __name__ == "__main__":
    main()

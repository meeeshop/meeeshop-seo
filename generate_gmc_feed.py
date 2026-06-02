#!/usr/bin/env python3
"""
generate_gmc_feed.py — Google Merchant Center Feed Generator
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Fetches all active products from Shopify and generates a formatted
CSV feed for Google Merchant Center. Maps inventory, images, attributes,
age, color, gender, and country.
"""

import os
import csv
import re
import time
import requests
import secrets_manager

# ── Configuration & Credentials ───────────────────────────────────────────────
try:
    SHOPIFY_STORE = secrets_manager.get_secret("SHOPIFY_STORE_URL")
    SHOPIFY_TOKEN = secrets_manager.get_secret("SHOPIFY_ACCESS_TOKEN")
except KeyError as e:
    raise ValueError(f"Missing Shopify credentials in secrets.enc: {e}")

STORE_BASE_URL = "https://us.meeeshop.com"

STORE_DOMAIN = SHOPIFY_STORE.replace("https://", "").replace("http://", "").strip("/")
API_VER = "2024-01"
HEADERS = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}

# Default MeeeShop GMC Settings
DEFAULT_GENDER = "female"
DEFAULT_AGE_GROUP = "adult"
DEFAULT_CONDITION = "new"
DEFAULT_COUNTRY = "US"
DEFAULT_BRAND = "MeeeShop"
DEFAULT_GOOGLE_CATEGORY = "166" # Apparel & Accessories

OUTPUT_FILE = "google_merchant_feed.csv"

def clean_html(raw_html):
    """Removes HTML tags from product descriptions for the GMC feed."""
    if not raw_html:
        return ""
    cleanr = re.compile('<.*?>')
    text = re.sub(cleanr, '', raw_html)
    return text.replace('\n', ' ').replace('\r', ' ').replace(';', ',').strip()

def fetch_all_active_products():
    """Fetches all active products from Shopify handling pagination via Link headers."""
    products = []
    url = f"https://{STORE_DOMAIN}/admin/api/{API_VER}/products.json?limit=250&status=active"
    
    print(f"Fetching active products from {STORE_DOMAIN}...")
    while url:
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        data = response.json()
        products.extend(data.get("products", []))
        
        # Handle cursor-based pagination
        link_header = response.headers.get("Link")
        url = None
        if link_header:
            links = link_header.split(",")
            for link in links:
                if 'rel="next"' in link:
                    url = link[link.find("<")+1:link.find(">")]
                    
        # Respect rate limits
        time.sleep(0.5)
        
    print(f"Total products fetched: {len(products)}")
    return products

def generate_feed():
    products = fetch_all_active_products()
    
    feed_headers = [
        "id", "title", "description", "link", "image_link", "additional_image_link",
        "availability", "price", "condition", "brand", "gtin", "mpn",
        "google_product_category", "item_group_id", "gender", "age_group",
        "color", "size", "shipping_country", "custom_label_0", "custom_label_1"
    ]
    
    rows = []
    
    for product in products:
        # Extract Images
        images = product.get("images", [])
        main_image = images[0].get("src") if images else ""
        additional_images = ",".join([img.get("src") for img in images[1:11]]) # Max 10 additional images
        
        # Extract Base Product details
        prod_desc = clean_html(product.get("body_html", ""))
        brand = product.get("vendor") or DEFAULT_BRAND
        item_group_id = str(product.get("id"))
        product_type = product.get("product_type", "")
        tags = product.get("tags", "")
        
        # Process each variant as a unique item in GMC
        for variant in product.get("variants", []):
            var_id = str(variant.get("id"))
            sku = variant.get("sku") or var_id
            feed_id = f"{item_group_id}_{var_id}"
            
            # Title mapping
            title = product.get("title")
            if variant.get("title") and variant.get("title") != "Default Title":
                title = f"{title} - {variant.get('title')}"
                
            link = f"{STORE_BASE_URL.rstrip('/')}/products/{product.get('handle')}?variant={var_id}"
            
            # Availability mapping
            qty = variant.get("inventory_quantity", 0)
            policy = variant.get("inventory_policy", "deny")
            availability = "in_stock" if (qty > 0 or policy == "continue") else "out_of_stock"
            
            # Price mapping
            price = f"{variant.get('price')} USD"
            
            # Find Color and Size dynamically from variant options
            color = ""
            size = ""
            for opt in product.get("options", []):
                opt_name = opt.get("name", "").lower()
                opt_pos = opt.get("position")
                val = variant.get(f"option{opt_pos}", "")
                
                if "color" in opt_name or "colour" in opt_name:
                    color = val
                elif "size" in opt_name:
                    size = val
                    
            rows.append({
                "id": feed_id,
                "title": title,
                "description": prod_desc,
                "link": link,
                "image_link": main_image,
                "additional_image_link": additional_images,
                "availability": availability,
                "price": price,
                "condition": DEFAULT_CONDITION,
                "brand": brand,
                "gtin": variant.get("barcode", ""),
                "mpn": sku,
                "google_product_category": DEFAULT_GOOGLE_CATEGORY,
                "item_group_id": item_group_id,
                "gender": DEFAULT_GENDER,
                "age_group": DEFAULT_AGE_GROUP,
                "color": color,
                "size": size,
                "shipping_country": DEFAULT_COUNTRY,
                "custom_label_0": product_type,
                "custom_label_1": tags
            })
            
    # Write to CSV file
    print(f"Writing {len(rows)} variants to {OUTPUT_FILE}...")
    with open(OUTPUT_FILE, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=feed_headers)
        writer.writeheader()
        writer.writerows(rows)
        
    print("✅ Google Merchant Feed generated successfully.")

if __name__ == "__main__":
    generate_feed()
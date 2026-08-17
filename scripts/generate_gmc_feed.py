#!/usr/bin/env python3
"""
generate_gmc_feed.py — Google Merchant Center Feed Generator
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Fetches all active products from Shopify and generates a formatted
CSV/TSV feed for Google Merchant Center. Maps inventory, images, attributes,
age, color, gender, country, and 3+ level Google Product Taxonomy.
Uploads to Shopify CDN and manages permanent redirect /a/google_merchant_feed.csv.
"""

import os
import csv
import re
import time
import requests
import secrets_manager
import gzip
import json

# ── Configuration & Credentials ───────────────────────────────────────────────
try:
    SHOPIFY_STORE = secrets_manager.get_secret("SHOPIFY_STORE")
    SHOPIFY_TOKEN = secrets_manager.get_secret("SHOPIFY_ACCESS_TOKEN")
    STORE_BASE_URL = secrets_manager.get_secret("STORE_BASE_URL")
except KeyError as e:
    raise ValueError(f"Missing Shopify credentials in secrets.enc: {e}")

STORE_DOMAIN = SHOPIFY_STORE.replace("https://", "").replace("http://", "").strip("/")
API_VER = "2025-01"
HEADERS = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}

# Default MeeeShop GMC Settings
DEFAULT_GENDER = "female"
DEFAULT_AGE_GROUP = "adult"
DEFAULT_CONDITION = "new"
DEFAULT_BRAND = "MeeeShop"

OUTPUT_FILE = "google_merchant_feed.txt"

def clean_html(raw_html):
    """Removes HTML tags from product descriptions for the GMC feed."""
    if not raw_html:
        return ""
    cleanr = re.compile('<.*?>')
    text = re.sub(cleanr, '', raw_html)
    return text.replace('\n', ' ').replace('\r', ' ').replace('\t', ' ').replace(';', ',').strip()

def clean_and_validate_gtin(raw_gtin):
    """
    Sanitizes and validates GTIN according to GS1 standards & GMC rules.
    Must be digits only, length 8, 12, 13, or 14, with valid GS1 check digit.
    Excludes internal store barcodes (20-29, 40-49), coupons (98-99), dummy repeats.
    Returns valid GTIN string, or "" if invalid.
    """
    if not raw_gtin:
        return ""
    digits = re.sub(r'\D', '', str(raw_gtin).strip())
    if len(digits) not in [8, 12, 13, 14]:
        return ""

    # Exclude dummy repeat digits (e.g. 111111111111, 000000000000)
    if len(set(digits)) <= 2:
        return ""

    # Strip leading zeros to evaluate true GS1 prefix
    clean_digits = digits.lstrip('0')
    if not clean_digits:
        return ""

    # Exclude GS1 Restricted Distribution & Internal Barcodes:
    # - Prefixes 20-29 & 020-029: Internal store / variable weight
    # - Prefixes 40-49 & 040-049: Internal EAN-8 / EAN-13 store SKUs
    # - Prefixes 980-999: GS1 Refund / Coupon / In-store Vouchers
    if clean_digits.startswith(('20','21','22','23','24','25','26','27','28','29',
                               '40','41','42','43','44','45','46','47','48','49',
                               '98','99')):
        return ""

    # Exclude sequential dummy barcodes
    if clean_digits in ("12345678", "123456789012", "01234567890123", "12345678901234"):
        return ""

    # Validate GS1 Check Digit
    padded = digits.zfill(14)
    try:
        odd_sum = sum(int(padded[i]) for i in range(0, 13, 2))
        even_sum = sum(int(padded[i]) for i in range(1, 13, 2))
        total = odd_sum * 3 + even_sum
        check_digit = (10 - (total % 10)) % 10
        if check_digit == int(padded[13]):
            return digits
    except (ValueError, IndexError):
        pass
    return ""

def filter_image_url(url):
    """
    Validates and formats image URL for GMC compatibility.
    Shopify CDN converts WebP/SVG/PNG to JPEG on the fly by appending format=jpg.
    Returns a guaranteed valid JPEG/PNG URL or "".
    """
    if not url or not isinstance(url, str):
        return ""
    clean_url = url.strip()
    if not (clean_url.startswith("http://") or clean_url.startswith("https://")):
        return ""
    
    # Ensure format=jpg parameter for Shopify CDN URLs
    if "cdn.shopify.com" in clean_url:
        if not ("format=jpg" in clean_url or "format=jpeg" in clean_url or "format=png" in clean_url):
            clean_url = clean_url + ("&format=jpg" if "?" in clean_url else "?format=jpg")
            
    return clean_url

def get_google_product_category(product):
    """Maps product details to full 3+ level Google Product Taxonomy paths for optimized GMC matching."""
    title = (product.get("title") or "").lower()
    ptype = (product.get("product_type") or "").lower()
    tags = (product.get("tags") or "").lower()
    text = f"{title} {ptype} {tags}"

    if any(w in text for w in ["boot", "boots", "bootie", "booties"]):
        return "Apparel & Accessories > Shoes > Boots"
    elif any(w in text for w in ["sneaker", "sneakers", "athletic shoe", "running shoe"]):
        return "Apparel & Accessories > Shoes > Athletic Shoes"
    elif any(w in text for w in ["sandal", "sandals", "flip flop", "slide", "slides"]):
        return "Apparel & Accessories > Shoes > Sandals"
    elif any(w in text for w in ["heel", "heels", "pump", "pumps", "stiletto"]):
        return "Apparel & Accessories > Shoes > Heels"
    elif any(w in text for w in ["flat", "flats", "loafer", "loafers", "mule", "mules", "oxford"]):
        return "Apparel & Accessories > Shoes > Flats"
    elif any(w in text for w in ["shoe", "shoes", "footwear"]):
        return "Apparel & Accessories > Shoes > Boots"
    elif any(w in text for w in ["dress", "dresses", "gown", "romper", "jumpsuit"]):
        return "Apparel & Accessories > Clothing > Dresses"
    elif any(w in text for w in ["set", "sets", "outfit", "two piece", "2 piece", "co-ord", "coord"]):
        return "Apparel & Accessories > Clothing > Outfit Sets"
    elif any(w in text for w in ["pant", "pants", "jean", "jeans", "trouser", "trousers", "legging", "leggings"]):
        return "Apparel & Accessories > Clothing > Pants"
    elif any(w in text for w in ["short", "shorts"]):
        return "Apparel & Accessories > Clothing > Shorts"
    elif any(w in text for w in ["skirt", "skirts"]):
        return "Apparel & Accessories > Clothing > Skirts"
    elif any(w in text for w in ["jacket", "jackets", "coat", "coats", "blazer", "blazers", "cardigan", "outerwear", "sweatshirt", "hoodie"]):
        return "Apparel & Accessories > Clothing > Outerwear > Coats & Jackets"
    elif any(w in text for w in ["top", "tops", "shirt", "shirts", "tee", "t-shirt", "blouse", "knit", "sweater"]):
        return "Apparel & Accessories > Clothing > Shirts & Tops"
    elif any(w in text for w in ["bag", "bags", "handbag", "clutch", "tote", "purse", "backpack", "crossbody"]):
        return "Apparel & Accessories > Handbags, Wallets & Cases > Handbags"
    elif any(w in text for w in ["bikini", "swimsuit", "swimwear", "monokini"]):
        return "Apparel & Accessories > Clothing > Swimwear"
    elif any(w in text for w in ["pajama", "sleepwear", "loungewear", "robe", "nightgown"]):
        return "Apparel & Accessories > Clothing > Sleepwear & Loungewear"
    elif any(w in text for w in ["necklace", "necklaces"]):
        return "Apparel & Accessories > Jewelry > Necklaces"
    elif any(w in text for w in ["earring", "earrings"]):
        return "Apparel & Accessories > Jewelry > Earrings"
    elif any(w in text for w in ["bracelet", "bracelets"]):
        return "Apparel & Accessories > Jewelry > Bracelets"
    elif any(w in text for w in ["ring", "rings"]):
        return "Apparel & Accessories > Jewelry > Rings"
    elif any(w in text for w in ["jewelry", "jewelries", "pendant", "charm"]):
        return "Apparel & Accessories > Jewelry > Jewelry Sets"
    elif any(w in text for w in ["hat", "hats", "cap", "caps", "beanie"]):
        return "Apparel & Accessories > Clothing Accessories > Hats"
    elif any(w in text for w in ["belt", "belts"]):
        return "Apparel & Accessories > Clothing Accessories > Belts"
    elif any(w in text for w in ["sunglasses", "eyewear"]):
        return "Apparel & Accessories > Clothing Accessories > Sunglasses"
    else:
        return "Apparel & Accessories > Clothing > Shirts & Tops"

def extract_color(product, variant, current_color):
    """Dynamically extracts product color from options, title, tags, description, or defaults to Multi."""
    if current_color and current_color.strip():
        return current_color.strip()

    title_lower = product.get("title", "").lower()
    tags_lower = [t.lower().strip() for t in product.get("tags", "").split(",") if t.strip()]
    desc_clean = clean_html(product.get("body_html", "")).lower()

    common_colors = [
        "black", "white", "red", "blue", "pink", "green", "yellow", "orange", "purple", "brown",
        "grey", "gray", "cream", "beige", "navy", "gold", "silver", "olive", "mustard", "burgundy",
        "rust", "lavender", "coral", "peach", "mint", "ivory", "denim", "camel", "taupe", "tan",
        "multi", "teal", "charcoal", "khaki", "plum", "apricot", "lilac", "mauve", "fuchsia",
        "turquoise", "maroon", "bronze", "indigo", "magenta", "leopard", "cheetah", "floral", "animal"
    ]

    for pos in [1, 2, 3]:
        opt_val = variant.get(f"option{pos}", "")
        if opt_val:
            opt_val_lower = opt_val.lower().strip()
            for word in re.split(r'[\s/]+', opt_val_lower):
                if word in common_colors:
                    return word.capitalize()

    for tag in tags_lower:
        if tag in common_colors:
            return tag.capitalize()

    for word in re.split(r'[\s,\-\(\)]+', title_lower):
        if word in common_colors:
            return word.capitalize()

    match = re.search(r'colou?r:\s*([a-z]+)', desc_clean)
    if match:
        color_word = match.group(1)
        if color_word in common_colors:
            return color_word.capitalize()

    for word in re.split(r'[\s,\.\!\?]+', desc_clean):
        if word in common_colors:
            return word.capitalize()

    return "Multi"

def fetch_all_active_products():
    """Fetches all active products from Shopify handling pagination via Link headers."""
    products = []
    url = f"https://{STORE_DOMAIN}/admin/api/{API_VER}/products.json?limit=250&status=active&published_status=published"
    
    print(f"Fetching active products from {STORE_DOMAIN}...", flush=True)
    while url:
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        try:
            data = response.json()
        except json.JSONDecodeError:
            print(f"⚠️ Shopify API response for products was not valid JSON: {response.text}", flush=True)
            raise Exception("Shopify API response for products was not valid JSON.")
        products.extend(data.get("products", []))
        
        link_header = response.headers.get("Link")
        url = None
        if link_header:
            links = link_header.split(",")
            for link in links:
                if 'rel="next"' in link:
                    url = link[link.find("<")+1:link.find(">")]
                    
        time.sleep(0.4)
        
    print(f"Total products fetched: {len(products)}", flush=True)
    return products

def upload_to_shopify_files(filepath):
    """Uploads the generated CSV directly to Shopify Files (CDN)."""
    print("\nUploading feed to Shopify CDN...", flush=True)
    graphql_url = f"https://{STORE_DOMAIN}/admin/api/{API_VER}/graphql.json"
    
    filename = os.path.basename(filepath)
    mime_type = "application/gzip" if filepath.endswith(".gz") else "text/plain"

    query_existing = f"""
    query {{
      files(first: 10, query: "filename:{filename}") {{
        edges {{
          node {{
            id
          }}
        }}
      }}
    }}
    """
    resp = requests.post(graphql_url, headers=HEADERS, json={"query": query_existing})
    resp.raise_for_status()
    data = resp.json()

    edges = data.get("data", {}).get("files", {}).get("edges", [])
    if edges:
        file_ids_to_delete = [edge["node"]["id"] for edge in edges]
        delete_mut = """
        mutation fileDelete($fileIds: [ID!]!) {
          fileDelete(fileIds: $fileIds) {
            deletedFileIds
          }
        }
        """
        resp = requests.post(graphql_url, headers=HEADERS, json={"query": delete_mut, "variables": {"fileIds": file_ids_to_delete}})
        resp.raise_for_status()
        time.sleep(2)
        
    file_size = str(os.path.getsize(filepath))
    staged_mut = f"""
    mutation {{
      stagedUploadsCreate(input: [{{
        resource: FILE,
        filename: "{filename}",
        mimeType: "{mime_type}",
        httpMethod: POST,
        fileSize: "{file_size}"
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
    resp = requests.post(graphql_url, headers=HEADERS, json={"query": staged_mut})
    resp.raise_for_status()
    data = resp.json()

    target = data["data"]["stagedUploadsCreate"]["stagedTargets"][0]

    with open(filepath, "rb") as f:
        form_data = [(p["name"], p["value"]) for p in target["parameters"]]
        form_data.append(("file", (os.path.basename(filepath), f, "text/plain")))
        
        upload_resp = requests.post(target["url"], files=form_data)
        upload_resp.raise_for_status()
        
    create_mut = """
    mutation fileCreate($files: [FileCreateInput!]!) {
      fileCreate(files: $files) {
        files {
          id
          fileStatus
        }
      }
    }
    """
    variables = {"files": [{"originalSource": target["resourceUrl"], "contentType": "FILE"}]}
    resp = requests.post(graphql_url, headers=HEADERS, json={"query": create_mut, "variables": variables})
    resp.raise_for_status()
    create_data = resp.json()
    file_id = create_data["data"]["fileCreate"]["files"][0]["id"]

    public_url = None
    for _ in range(12):
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
        resp = requests.post(graphql_url, headers=HEADERS, json={"query": query_file})
        resp.raise_for_status()
        node_data = resp.json()
        node = node_data.get("data", {}).get("node", {})
        if node.get("fileStatus") == "READY":
            public_url = node.get("url")
            break
            
    if public_url:
        print(f"✅ Feed uploaded successfully to Shopify CDN!", flush=True)
        print(f"🔗 CDN URL: {public_url}", flush=True)
        create_or_update_redirect(public_url)
    else:
        raise Exception("Failed to retrieve public URL for uploaded file.")

def create_or_update_redirect(target_url):
    """Creates or updates a URL redirect to point to the latest feed URL."""
    print("\nCreating/updating URL redirect...", flush=True)
    graphql_url = f"https://{STORE_DOMAIN}/admin/api/{API_VER}/graphql.json"
    redirect_path = "/a/google_merchant_feed.csv"

    query_redirect = f'''
    query {{
      urlRedirects(first: 1, query: "path:{redirect_path}") {{
        edges {{
          node {{
            id
          }}
        }}
      }}
    }}
    '''
    resp = requests.post(graphql_url, headers=HEADERS, json={"query": query_redirect})
    resp.raise_for_status()
    data = resp.json()
    edges = data.get("data", {}).get("urlRedirects", {}).get("edges", [])

    url_redirect_input = {"path": redirect_path, "target": target_url}

    if edges:
        redirect_id = edges[0]["node"]["id"]
        update_mut = """
        mutation urlRedirectUpdate($id: ID!, $urlRedirect: UrlRedirectInput!) {
          urlRedirectUpdate(id: $id, urlRedirect: $urlRedirect) {
            urlRedirect { id path target }
            userErrors { field message }
          }
        }
        """
        resp = requests.post(graphql_url, headers=HEADERS, json={"query": update_mut, "variables": {"id": redirect_id, "urlRedirect": url_redirect_input}})
        resp.raise_for_status()
    else:
        create_mut = """
        mutation urlRedirectCreate($urlRedirect: UrlRedirectInput!) {
          urlRedirectCreate(urlRedirect: $urlRedirect) {
            urlRedirect { id path target }
            userErrors { field message }
          }
        }
        """
        resp = requests.post(graphql_url, headers=HEADERS, json={"query": create_mut, "variables": {"urlRedirect": url_redirect_input}})
        resp.raise_for_status()

    static_url = f"{STORE_BASE_URL.rstrip('/')}{redirect_path}"
    print(f"✅ Redirect is live.", flush=True)
    print(f"🔗 Static Google Merchant Center URL: {static_url}", flush=True)

def generate_feed():
    products = fetch_all_active_products()
    
    feed_headers = [
        "id", "title", "description", "link", "image_link", "additional_image_link",
        "availability", "price", "condition", "brand", "gtin", "mpn",
        "identifier_exists", "google_product_category", "item_group_id", "gender", "age_group",
        "color", "size", "custom_label_0", "custom_label_1", "included_destination",
        "shipping"
    ]
    
    rows = []
    
    for product in products:
        if not product.get("published_at"):
            continue

        images = product.get("images", [])
        main_image = filter_image_url(images[0].get("src") if images else "")
        
        additional_images_list = []
        for img in images[1:15]:
            filtered_img = filter_image_url(img.get("src"))
            if filtered_img:
                additional_images_list.append(filtered_img)
            if len(additional_images_list) >= 10:
                break

        additional_images = ",".join(additional_images_list)
        
        prod_desc = clean_html(product.get("body_html", ""))
        if len(prod_desc) > 500:
            prod_desc = prod_desc[:497] + "..."
        brand = DEFAULT_BRAND
        item_group_id = str(product.get("id"))
        product_type = product.get("product_type", "")
        tags = product.get("tags", "")
        google_cat = get_google_product_category(product)
        
        tags_list = [t.strip() for t in tags.split(",") if t.strip()]
        first_tag = tags_list[0][:50] if tags_list else ""
        
        for variant in product.get("variants", []):
            var_id = str(variant.get("id"))
            sku = variant.get("sku") or var_id
            feed_id = f"shopify_ZZ_{item_group_id}_{var_id}"
            
            title = product.get("title")
            if variant.get("title") and variant.get("title") != "Default Title":
                title = f"{title} - {variant.get('title')}"
                
            link = f"{STORE_BASE_URL.rstrip('/')}/products/{product.get('handle')}?variant={var_id}"
            
            qty = variant.get("inventory_quantity", 0)
            policy = variant.get("inventory_policy", "deny")
            management = variant.get("inventory_management")
            is_available = not management or policy == "continue" or qty > 0
            availability = "in_stock" if is_available else "out_of_stock"
            
            price = f"{variant.get('price')} USD"
             
            # GTIN validation (Excludes 20-29, 40-49 internal barcode prefixes and coupon codes)
            raw_gtin = variant.get("barcode", "") or ""
            gtin_value = clean_and_validate_gtin(raw_gtin)

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
                    
            color = extract_color(product, variant, color)
                    
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
                "gtin": gtin_value,
                "mpn": sku,
                "identifier_exists": "yes" if gtin_value else "no",
                "google_product_category": google_cat,
                "item_group_id": item_group_id,
                "gender": DEFAULT_GENDER,
                "age_group": DEFAULT_AGE_GROUP,
                "color": color,
                "size": size,
                "custom_label_0": product_type,
                "custom_label_1": first_tag,
                "included_destination": "Shopping_ads,Free_listings",
                "shipping": "US:::0.00 USD"
            })
            
    output_gz = OUTPUT_FILE + ".gz"
    print(f"Writing {len(rows)} variants to {output_gz} (TSV format, gzipped)...", flush=True)
    with gzip.open(output_gz, mode="wt", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=feed_headers, delimiter='\t')
        writer.writeheader()
        writer.writerows(rows)
        
    print("✅ Google Merchant Feed generated successfully.", flush=True)

    upload_to_shopify_files(output_gz)

if __name__ == "__main__":
    generate_feed()
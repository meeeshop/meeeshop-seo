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
import json # Import json for pretty printing

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
        try:
            data = response.json()
        except json.JSONDecodeError:
            print(f"⚠️ Shopify API response for products was not valid JSON: {response.text}")
            raise Exception("Shopify API response for products was not valid JSON.")
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

def upload_to_shopify_files(filepath):
    """Uploads the generated CSV directly to Shopify Files (CDN)."""
    print("\nUploading feed to Shopify CDN...")
    graphql_url = f"https://{STORE_DOMAIN}/admin/api/{API_VER}/graphql.json"
    
    # 1. Check for existing file and delete it so the new URL stays clean
    # We are deleting files with the exact name, but Shopify might append GUIDs.
    # This step is primarily to clean up any previous exact matches.
    query_existing = """
    query {
      files(first: 10, query: "filename:google_merchant_feed.csv") {
        edges {
          node {
            id
          }
        }
      }
    }
    """
    resp = requests.post(graphql_url, headers=HEADERS, json={"query": query_existing})
    resp.raise_for_status() # Ensure HTTP errors are caught
    try:
        data = resp.json()
    except json.JSONDecodeError:
        print(f"⚠️ Shopify GraphQL response for querying existing files was not valid JSON: {resp.text}")
        raise Exception("Shopify GraphQL response for querying existing files was not valid JSON.")

    if data.get("errors"):
        print(f"⚠️ Shopify GraphQL errors when querying existing files: {json.dumps(data['errors'], indent=2)}")
        # Continue, as this might not be critical if no files are found

    edges = data.get("data", {}).get("files", {}).get("edges", [])
    
    if edges:
        print(f"Found {len(edges)} existing feed file(s) on Shopify. Deleting...")
        file_ids_to_delete = [edge["node"]["id"] for edge in edges]
        delete_mut = """
        mutation fileDelete($fileIds: [ID!]!) {
          fileDelete(fileIds: $fileIds) {
            deletedFileIds
          }
        }
        """
        resp = requests.post(graphql_url, headers=HEADERS, json={"query": delete_mut, "variables": {"fileIds": file_ids_to_delete}})
        resp.raise_for_status() # Ensure HTTP errors are caught
        try:
            delete_data = resp.json()
        except json.JSONDecodeError:
            print(f"⚠️ Shopify GraphQL response for deleting files was not valid JSON: {resp.text}")
            # Continue, as deletion might not be critical if file was already gone
            delete_data = {} # Assign empty dict to avoid further errors
        if delete_data.get("errors"):
            print(f"⚠️ Shopify GraphQL errors when deleting files: {json.dumps(delete_data['errors'], indent=2)}")
            # Continue, as deletion might not be critical if file was already gone
        print("Deleted existing feed file(s) on Shopify.")
        time.sleep(3) # Wait for deletion to propagate
        
    # 2. Request Staged Upload
    staged_mut = """
    mutation {
      stagedUploadsCreate(input: [{
        resource: FILE,
        filename: "google_merchant_feed.csv",
        mimeType: "text/csv",
        httpMethod: POST
      }]) {
        stagedTargets {
          url
          resourceUrl
          parameters {
            name
            value
          }
        }
      }
    }
    """
    resp = requests.post(graphql_url, headers=HEADERS, json={"query": staged_mut})
    resp.raise_for_status() # Ensure HTTP errors are caught
    try:
        data = resp.json()
    except json.JSONDecodeError:
        print(f"⚠️ Shopify GraphQL response for creating staged upload was not valid JSON: {resp.text}")
        raise Exception("Shopify GraphQL response for creating staged upload was not valid JSON.")

    if data.get("errors"):
        print(f"⚠️ Shopify GraphQL errors when creating staged upload: {json.dumps(data['errors'], indent=2)}")
        raise Exception("Shopify GraphQL staged upload failed.")

    try:
        target = data["data"]["stagedUploadsCreate"]["stagedTargets"][0]
    except (KeyError, IndexError):
        print(f"Failed to create staged upload: {json.dumps(data, indent=2)}")
        raise Exception("Shopify staged upload target not found in response.")

    # 3. Upload file to staging target
    with open(filepath, "rb") as f:
        files = {"file": ("google_merchant_feed.csv", f, "text/csv")}
        params = {p["name"]: p["value"] for p in target["parameters"]}
        upload_resp = requests.post(target["url"], data=params, files=files)
        upload_resp.raise_for_status()
        
    # 4. Create file in Shopify
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
    resp = requests.post(graphql_url, headers=HEADERS, json={"query": create_mut, "variables": variables})
    resp.raise_for_status() # Ensure HTTP errors are caught
    try:
        create_data = resp.json()
    except json.JSONDecodeError:
        print(f"⚠️ Shopify GraphQL response for creating file was not valid JSON: {resp.text}")
        raise Exception("Shopify GraphQL response for creating file was not valid JSON.")

    if create_data.get("errors"):
        print(f"⚠️ Shopify GraphQL errors when creating file: {json.dumps(create_data['errors'], indent=2)}")
        raise Exception("Shopify GraphQL file creation failed.")
    
    try:
        file_id = create_data["data"]["fileCreate"]["files"][0]["id"]
    except (KeyError, IndexError):
        print(f"Failed to create file: {json.dumps(create_data, indent=2)}")
        raise Exception("Shopify file ID not found in response.")
        
    print("File processing in Shopify...")
    
    # 5. Wait for file to be ready and get URL
    public_url = None
    for _ in range(10):
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
        resp.raise_for_status() # Ensure HTTP errors are caught
        try:
            node_data = resp.json()
        except json.JSONDecodeError:
            print(f"⚠️ Shopify GraphQL response for querying file status was not valid JSON: {resp.text}")
            # Continue, as it might just be processing
            node_data = {} # Assign empty dict to avoid further errors

        if node_data.get("errors"):
            print(f"⚠️ Shopify GraphQL errors when querying file status: {json.dumps(node_data['errors'], indent=2)}")
            # Continue, as it might just be processing

        node = node_data.get("data", {}).get("node", {})
        if node.get("fileStatus") == "READY":
            public_url = node.get("url")
            break
            
    if public_url:
        print(f"✅ Feed uploaded successfully to Shopify CDN!")
        cdn_url = public_url.split("?")[0] # Remove any version parameters
        print(f"🔗 Temporary CDN URL: {cdn_url}")
        create_or_update_redirect(cdn_url)
    else:
        print("⚠️ File uploaded, but URL could not be retrieved in time. Check Shopify Admin > Settings > Files.")
        raise Exception("Failed to retrieve public URL for uploaded file.")

def create_or_update_redirect(target_url):
    """Creates or updates a URL redirect to point to the latest feed URL."""
    print("\nCreating/updating URL redirect...")
    graphql_url = f"https://{STORE_DOMAIN}/admin/api/{API_VER}/graphql.json"
    redirect_path = "/a/google_merchant_feed.csv"  # A static, non-conflicting path

    # 1. Check for an existing redirect for this path
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
    resp.raise_for_status() # Ensure HTTP errors are caught
    try:
        data = resp.json()
    except json.JSONDecodeError:
        print(f"⚠️ Shopify GraphQL response for query_redirect was not valid JSON: {resp.text}")
        raise Exception("Shopify GraphQL response for redirects was not valid JSON.")

    print(f"Shopify GraphQL response for query_redirect: {json.dumps(data, indent=2)}") # <-- Added for debugging

    # Check for GraphQL errors first
    if data.get("errors"):
        print(f"⚠️ Shopify GraphQL errors when querying redirects: {json.dumps(data['errors'], indent=2)}")
        raise Exception("Shopify GraphQL query for redirects failed.")

    # Safely get the 'data' part of the response
    graphql_data = data.get("data")
    if graphql_data is None:
        print(f"⚠️ Shopify GraphQL response missing 'data' key or it's null for query_redirect: {json.dumps(data, indent=2)}")
        raise Exception("Shopify GraphQL response for redirects was empty or invalid.")

    edges = graphql_data.get("urlRedirects", {}).get("edges", [])

    url_redirect_input = {
        "path": redirect_path,
        "target": target_url
    }

    if edges:
        redirect_id = edges[0]["node"]["id"]
        print(f"Found existing redirect. Updating it to point to new URL...")
        update_mut = """
        mutation urlRedirectUpdate($id: ID!, $urlRedirect: UrlRedirectInput!) {
          urlRedirectUpdate(id: $id, urlRedirect: $urlRedirect) {
            urlRedirect { id path target }
            userErrors { field message }
          }
        }
        """
        variables = {"id": redirect_id, "urlRedirect": url_redirect_input}
        resp = requests.post(graphql_url, headers=HEADERS, json={"query": update_mut, "variables": variables})
        resp.raise_for_status()
        try:
            result = resp.json()
        except json.JSONDecodeError:
            print(f"⚠️ Shopify GraphQL response for updating redirect was not valid JSON: {resp.text}")
            raise Exception("Shopify GraphQL response for updating redirect was not valid JSON.")

        if result.get("errors"):
            print(f"⚠️ Shopify GraphQL errors when updating redirect: {json.dumps(result['errors'], indent=2)}")
            raise Exception("Shopify GraphQL update redirect failed.")
        result = result.get("data", {}).get("urlRedirectUpdate", {})

    else:
        print("No existing redirect found. Creating a new one...")
        create_mut = """
        mutation urlRedirectCreate($urlRedirect: UrlRedirectInput!) {
          urlRedirectCreate(urlRedirect: $urlRedirect) {
            urlRedirect { id path target }
            userErrors { field message }
          }
        }
        """
        variables = {"urlRedirect": url_redirect_input}
        resp = requests.post(graphql_url, headers=HEADERS, json={"query": create_mut, "variables": variables})
        resp.raise_for_status()
        try:
            result = resp.json()
        except json.JSONDecodeError:
            print(f"⚠️ Shopify GraphQL response for creating redirect was not valid JSON: {resp.text}")
            raise Exception("Shopify GraphQL response for creating redirect was not valid JSON.")

        if result.get("errors"):
            print(f"⚠️ Shopify GraphQL errors when creating redirect: {json.dumps(result['errors'], indent=2)}")
            raise Exception("Shopify GraphQL create redirect failed.")
        result = result.get("data", {}).get("urlRedirectCreate", {})

    user_errors = result.get("userErrors", [])
    if user_errors:
        print(f"⚠️ Error managing redirect: {user_errors}")
        raise Exception(f"Shopify redirect operation failed with user errors: {user_errors}")
    else:
        static_url = f"{STORE_BASE_URL.rstrip('/')}{redirect_path}"
        print(f"✅ Redirect is live.")
        print(f"🔗 Static Google Merchant Center URL: {static_url}")

def generate_feed():
    products = fetch_all_active_products()
    
    feed_headers = [
        "id", "title", "description", "link", "image_link", "additional_image_link",
        "availability", "price", "condition", "brand", "gtin", "mpn",
        "google_product_category", "item_group_id", "gender", "age_group",
        "color", "size", "custom_label_0", "custom_label_1", "excluded_destination",
        "store_code", # Added for local inventory data
        "quantity",    # Added for local inventory data
        "shipping"     # Added for default shipping
    ]
    
    rows = []
    
    for product in products:
        # Extract Images
        images = product.get("images", [])
        main_image = images[0].get("src") if images else ""
        additional_images = ",".join([img.get("src") for img in images[1:11]]) # Max 10 additional images
        
        # Extract Base Product details
        prod_desc = clean_html(product.get("body_html", ""))
        # Force the store brand for all products to build brand equity and prevent price shopping
        brand = DEFAULT_BRAND
        item_group_id = str(product.get("id"))
        product_type = product.get("product_type", "")
        tags = product.get("tags", "")
        
        # Extract the first tag and limit to 100 characters to avoid "Text too long" and 1000 unique value limits
        tags_list = [t.strip() for t in tags.split(",") if t.strip()]
        first_tag = tags_list[0][:100] if tags_list else ""
        
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
            
            # GTIN validation
            gtin_value = variant.get("barcode", "")
            # Common GTIN lengths are 8, 12, 13, 14. If it's not one of these, send empty.
            if gtin_value and not (len(gtin_value) in [8, 12, 13, 14] and gtin_value.isdigit()):
                gtin_value = ""

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
                "gtin": gtin_value, # Using validated GTIN
                "mpn": sku,
                "google_product_category": DEFAULT_GOOGLE_CATEGORY,
                "item_group_id": item_group_id,
                "gender": DEFAULT_GENDER,
                "age_group": DEFAULT_AGE_GROUP,
                "color": color,
                "size": size,
                "custom_label_0": product_type,
                "custom_label_1": first_tag,
                "excluded_destination": "local_inventory_ads,free_local_listings",
                "store_code": "", # Added with empty value
                "quantity": "",   # Added with empty value
                "shipping": "US:::0.00 USD" # Default shipping for US, 0.00 price
            })
            
    # Write to CSV file
    print(f"Writing {len(rows)} variants to {OUTPUT_FILE}...")
    with open(OUTPUT_FILE, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=feed_headers)
        writer.writeheader()
        writer.writerows(rows)
        
    print("✅ Google Merchant Feed generated successfully.")

    # Upload to Shopify
    upload_to_shopify_files(OUTPUT_FILE)

if __name__ == "__main__":
    generate_feed()
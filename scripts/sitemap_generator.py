#!/usr/bin/env python3
"""
sitemap_generator.py — Custom Sitemap & Image Sitemap generator for Shopify
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Generates a custom Google-compliant Image Sitemap (sitemap_images.xml) with
optimized image:title and image:caption tags, uploads it to Shopify Files,
creates a redirect from /sitemap_images.xml to the Shopify CDN URL, and
submits it programmatically to Google Search Console and Bing.
"""

import os
import sys
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape
import json
import time
import urllib.parse
import requests
from datetime import datetime, timezone
from pathlib import Path

# Configure stdout and stderr to handle UTF-8 output properly on Windows
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')

# ── path setup ────────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from secrets_manager import inject_to_env, get_secret
from shopify_graphql import run_graphql, parse_gid

inject_to_env()

# ── credentials ───────────────────────────────────────────────────────────────
SHOP      = get_secret("SHOPIFY_STORE")
TOKEN     = get_secret("SHOPIFY_ACCESS_TOKEN")
STORE_URL = get_secret("STORE_BASE_URL").rstrip("/")
API_VER   = "2024-10"
BASE      = f"https://{SHOP}/admin/api/{API_VER}"
SHP_HDR   = {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}

# ── Google OAuth / API constants ──────────────────────────────────────────────
OAUTH_ENDPOINT = "https://oauth2.googleapis.com/token"
GSC_SCOPE      = "https://www.googleapis.com/auth/webmasters"

# ── Shopify helpers ────────────────────────────────────────────────────────────
def _shopify_post(url: str, json_data: dict) -> dict:
    r = requests.post(url, headers=SHP_HDR, json=json_data, timeout=20)
    r.raise_for_status()
    return r.json()

# ── Fetch active content for the sitemap ─────────────────────────────────────
def fetch_products_for_sitemap() -> list[dict]:
    print("Fetching active products via GraphQL...")
    graphql_url = f"{BASE}/graphql.json"
    query = """
    query ($first: Int!, $after: String) {
      products(first: $first, after: $after, query: "status:active") {
        pageInfo { hasNextPage endCursor }
        edges {
          node {
            handle
            title
            descriptionHtml
            media(first: 100) {
              edges {
                node {
                  mediaContentType
                  ... on MediaImage {
                    alt
                    image {
                      url
                    }
                  }
                }
              }
            }
          }
        }
      }
    }
    """
    products = []
    has_next = True
    cursor = None
    while has_next:
        variables = {"first": 100, "after": cursor}
        try:
            res = _shopify_post(graphql_url, {"query": query, "variables": variables})
            data = res.get("data", {}).get("products", {})
            for edge in data.get("edges", []):
                node = edge.get("node", {})
                images = []
                for media_edge in node.get("media", {}).get("edges", []):
                    media_node = media_edge.get("node", {})
                    if media_node.get("mediaContentType") == "IMAGE":
                        img_url = media_node.get("image", {}).get("url")
                        if img_url:
                            images.append({
                                "url": img_url.split("?")[0],
                                "alt": media_node.get("alt") or ""
                            })
                
                # Strip HTML from description to use as caption
                desc_raw = node.get("descriptionHtml") or ""
                import re
                desc_clean = re.sub(r'<[^>]+>', ' ', desc_raw).strip()
                desc_clean = " ".join(desc_clean.split())[:200]
                
                products.append({
                    "url": f"{STORE_URL}/products/{node.get('handle')}",
                    "title": node.get("title") or "",
                    "caption": desc_clean,
                    "images": images
                })
            page_info = data.get("pageInfo", {})
            has_next = page_info.get("hasNextPage", False)
            cursor = page_info.get("endCursor")
        except Exception as e:
            print(f"Error fetching products: {e}")
            break
    print(f"Loaded {len(products)} products for sitemap.")
    return products

def fetch_collections_for_sitemap() -> list[dict]:
    print("Fetching active collections via GraphQL...")
    graphql_url = f"{BASE}/graphql.json"
    query = """
    query ($first: Int!, $after: String) {
      collections(first: $first, after: $after) {
        pageInfo { hasNextPage endCursor }
        edges {
          node {
            handle
            title
            descriptionHtml
            image {
              url
              altText
            }
          }
        }
      }
    }
    """
    collections = []
    has_next = True
    cursor = None
    while has_next:
        variables = {"first": 250, "after": cursor}
        try:
            res = _shopify_post(graphql_url, {"query": query, "variables": variables})
            data = res.get("data", {}).get("collections", {})
            for edge in data.get("edges", []):
                node = edge.get("node", {})
                images = []
                img_node = node.get("image")
                if img_node and img_node.get("url"):
                    images.append({
                        "url": img_node.get("url").split("?")[0],
                        "alt": img_node.get("altText") or ""
                    })
                
                import re
                desc_raw = node.get("descriptionHtml") or ""
                desc_clean = re.sub(r'<[^>]+>', ' ', desc_raw).strip()
                desc_clean = " ".join(desc_clean.split())[:200]

                collections.append({
                    "url": f"{STORE_URL}/collections/{node.get('handle')}",
                    "title": node.get("title") or "",
                    "caption": desc_clean,
                    "images": images
                })
            page_info = data.get("pageInfo", {})
            has_next = page_info.get("hasNextPage", False)
            cursor = page_info.get("endCursor")
        except Exception as e:
            print(f"Error fetching collections: {e}")
            break
    print(f"Loaded {len(collections)} collections for sitemap.")
    return collections

def fetch_articles_for_sitemap() -> list[dict]:
    print("Fetching blog articles via GraphQL...")
    graphql_url = f"{BASE}/graphql.json"
    blogs_query = """
    query {
      blogs(first: 50) {
        edges {
          node {
            id
            handle
          }
        }
      }
    }
    """
    try:
        res = _shopify_post(graphql_url, {"query": blogs_query})
        blogs = res.get("data", {}).get("blogs", {}).get("edges", [])
    except Exception as e:
        print(f"Error fetching blogs: {e}")
        return []

    articles = []
    articles_query = """
    query ($blogId: ID!, $first: Int!, $after: String) {
      node(id: $blogId) {
        ... on Blog {
          articles(first: $first, after: $after) {
            pageInfo { hasNextPage endCursor }
            edges {
              node {
                handle
                title
                summary
                image {
                  url
                  altText
                }
              }
            }
          }
        }
      }
    }
    """
    for blog_edge in blogs:
        blog_node = blog_edge.get("node", {})
        blog_id = blog_node.get("id")
        blog_handle = blog_node.get("handle")
        if not blog_id or not blog_handle:
            continue
            
        has_next = True
        cursor = None
        while has_next:
            variables = {"blogId": blog_id, "first": 100, "after": cursor}
            try:
                res = _shopify_post(graphql_url, {"query": articles_query, "variables": variables})
                data = res.get("data", {}).get("node", {}).get("articles", {})
                for edge in data.get("edges", []):
                    node = edge.get("node", {})
                    images = []
                    img_node = node.get("image")
                    if img_node and img_node.get("url"):
                        images.append({
                            "url": img_node.get("url").split("?")[0],
                            "alt": img_node.get("altText") or ""
                        })
                    
                    import re
                    desc_raw = node.get("summary") or ""
                    desc_clean = re.sub(r'<[^>]+>', ' ', desc_raw).strip()
                    desc_clean = " ".join(desc_clean.split())[:200]

                    articles.append({
                        "url": f"{STORE_URL}/blogs/{blog_handle}/{node.get('handle')}",
                        "title": node.get("title") or "",
                        "caption": desc_clean,
                        "images": images
                    })
                page_info = data.get("pageInfo", {})
                has_next = page_info.get("hasNextPage", False)
                cursor = page_info.get("endCursor")
            except Exception as e:
                print(f"Error fetching articles for blog {blog_handle}: {e}")
                break
    print(f"Loaded {len(articles)} blog articles for sitemap.")
    return articles

# ── Generate XML Sitemap ─────────────────────────────────────────────────────
def generate_image_sitemap(products: list[dict], collections: list[dict], articles: list[dict]) -> str:
    print("Generating Image Sitemap XML content...")
    
    # We output XML directly to ensure clean tags and namespaces
    xml_parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"',
        '        xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">'
    ]
    
    all_items = products + collections + articles
    for item in all_items:
        if not item["images"]:
            continue
        
        xml_parts.append('  <url>')
        xml_parts.append(f'    <loc>{escape(item["url"])}</loc>')
        
        for img in item["images"]:
            xml_parts.append('    <image:image>')
            xml_parts.append(f'      <image:loc>{escape(img["url"])}</image:loc>')
            
            # Use alt text or item title as the image title
            title = img["alt"].strip() or item["title"].strip()
            if title:
                xml_parts.append(f'      <image:title>{escape(title)}</image:title>')
            
            # Use item description snippet as caption
            caption = item["caption"].strip()
            if caption:
                xml_parts.append(f'      <image:caption>{escape(caption)}</image:caption>')
                
            xml_parts.append('    </image:image>')
            
        xml_parts.append('  </url>')
        
    xml_parts.append('</urlset>')
    
    return "\n".join(xml_parts)

# ── Upload to Shopify Files and Create Redirect ──────────────────────────────
def upload_sitemap_to_shopify(sitemap_content: str, filename: str = "sitemap_images.xml") -> str:
    print(f"Uploading {filename} to Shopify Files...")
    graphql_url = f"{BASE}/graphql.json"

    # Create local temporary sitemap file
    local_path = Path(filename)
    local_path.write_text(sitemap_content, encoding="utf-8")

    try:
        # 1. Staged upload request
        staged_mut = f"""
        mutation {{
          stagedUploadsCreate(input: [{{
            resource: FILE,
            filename: "{filename}",
            mimeType: "text/xml",
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
        staged_data = _shopify_post(graphql_url, {"query": staged_mut})
        target = staged_data["data"]["stagedUploadsCreate"]["stagedTargets"][0]

        # 2. Upload file
        with open(local_path, "rb") as f:
            form_data = []
            for p in target["parameters"]:
                form_data.append((p["name"], p["value"]))
            form_data.append(("file", (filename, f, "text/xml")))
            
            upload_resp = requests.post(target["url"], files=form_data)
            upload_resp.raise_for_status()

        # 3. Create generic file
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
        create_data = _shopify_post(graphql_url, {"query": create_mut, "variables": variables})
        file_id = create_data["data"]["fileCreate"]["files"][0]["id"]

        # 4. Wait for file to compile to get CDN URL
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
            node_data = _shopify_post(graphql_url, {"query": query_file})
            node = node_data.get("data", {}).get("node", {})
            if node.get("fileStatus") == "READY":
                public_url = node.get("url")
                break

        if not public_url:
            raise Exception("Timeout waiting for sitemap file compilation on Shopify CDN.")

        cdn_url = public_url.split("?")[0]
        print(f"Sitemap CDN URL: {cdn_url}")

        # 5. Create or update URL redirect from /sitemap_images.xml to CDN URL
        redirect_path = f"/{filename}"
        
        # Check if redirect already exists
        query_redirect = f'''
        query {{
          urlRedirects(first: 1, query: "path:{redirect_path}") {{
            edges {{
              node {{
                id
                target
              }}
            }}
          }}
        }}
        '''
        redirect_id = None
        try:
            r_data = _shopify_post(graphql_url, {"query": query_redirect})
            edges = r_data.get("data", {}).get("urlRedirects", {}).get("edges", [])
            if edges:
                redirect_id = edges[0]["node"]["id"]
                current_target = edges[0]["node"]["target"]
                if current_target == cdn_url:
                    print(f"[OK] Redirect already points to correct target: {redirect_path} -> {cdn_url}")
                    return cdn_url
        except Exception as e:
            print(f"Warning: redirect check failed: {e}")

        if redirect_id:
            # Update existing redirect
            update_redirect_mut = """
            mutation urlRedirectUpdate($id: ID!, $urlRedirect: UrlRedirectInput!) {
              urlRedirectUpdate(id: $id, urlRedirect: $urlRedirect) {
                urlRedirect {
                  id
                }
                userErrors {
                  message
                }
              }
            }
            """
            variables_update = {
                "id": redirect_id,
                "urlRedirect": {
                    "path": redirect_path,
                    "target": cdn_url
                }
            }
            _shopify_post(graphql_url, {"query": update_redirect_mut, "variables": variables_update})
            print(f"[OK] Updated existing redirect: {redirect_path} -> {cdn_url}")
        else:
            # Create new redirect
            create_redirect_mut = """
            mutation urlRedirectCreate($urlRedirect: UrlRedirectInput!) {
              urlRedirectCreate(urlRedirect: $urlRedirect) {
                urlRedirect {
                  id
                }
                userErrors {
                  message
                }
              }
            }
            """
            redirect_input = {
                "path": redirect_path,
                "target": cdn_url
            }
            _shopify_post(graphql_url, {"query": create_redirect_mut, "variables": {"urlRedirect": redirect_input}})
            print(f"[OK] Created redirect: {redirect_path} -> {cdn_url}")

        return cdn_url
    finally:
        if local_path.exists():
            local_path.unlink()

# ── Submit to Google Search Console API ──────────────────────────────────────
def get_gsc_access_token(sa_key: dict) -> str:
    print("[AUTH] Requesting OAuth2 access token for Google Search Console...")
    try:
        import base64
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.backends import default_backend
    except ImportError:
        sys.exit("ERROR: 'cryptography' package missing — run: pip install cryptography")

    now     = int(time.time())
    header  = {"alg": "RS256", "typ": "JWT"}
    payload = {"iss": sa_key["client_email"], "scope": GSC_SCOPE,
                "aud": OAUTH_ENDPOINT, "exp": now + 3600, "iat": now}

    def _b64url(data):
        return base64.urlsafe_b64encode(
            json.dumps(data, separators=(",", ":")).encode()
        ).rstrip(b"=").decode()

    signing_input = f"{_b64url(header)}.{_b64url(payload)}".encode()
    pk  = serialization.load_pem_private_key(
        sa_key["private_key"].encode(), password=None, backend=default_backend()
    )
    sig = pk.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    jwt = f"{signing_input.decode()}.{base64.urlsafe_b64encode(sig).rstrip(b'=').decode()}"

    resp = requests.post(OAUTH_ENDPOINT,
                         data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                               "assertion": jwt},
                         timeout=15)
    resp.raise_for_status()
    return resp.json()["access_token"]

def submit_sitemap_to_gsc(sitemap_url: str):
    print("Loading Google Service Account key...")
    # Load Google Service Account credentials (from secrets vault)
    try:
        raw = get_secret("GOOGLE_SA_KEY_JSON")
        sa_key = json.loads(raw)
    except Exception as e:
        print(f"Error loading GOOGLE_SA_KEY_JSON: {e}. Checking local key file...")
        local = Path(__file__).parent.parent / "google_sa_key.json"
        if local.exists():
            sa_key = json.loads(local.read_text(encoding="utf-8"))
        else:
            print("ERROR: Google Service Account key not found. Skipping Google Search Console submission.")
            return

    try:
        token = get_gsc_access_token(sa_key)
        
        # Query GSC verified sites list to find the matching property (e.g. sc-domain:us.meeeshop.com)
        list_url = "https://www.googleapis.com/webmasters/v3/sites"
        list_resp = requests.get(list_url, headers={"Authorization": f"Bearer {token}"}, timeout=15)
        list_resp.raise_for_status()
        sites = list_resp.json().get("siteEntry", [])
        
        store_domain = urllib.parse.urlparse(STORE_URL).netloc.lower()
        site_url = None
        for site in sites:
            candidate = site.get("siteUrl", "")
            if store_domain in candidate.lower():
                site_url = candidate
                break
                
        if not site_url:
            # Fallback
            site_url = STORE_URL + "/"
            
        encoded_site = urllib.parse.quote_plus(site_url)
        encoded_feed = urllib.parse.quote_plus(sitemap_url)
        
        gsc_url = f"https://www.googleapis.com/webmasters/v3/sites/{encoded_site}/sitemaps/{encoded_feed}"
        print(f"Submitting sitemap to Google Search Console API for property: {site_url}")
        
        resp = requests.put(
            gsc_url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=15
        )
        if resp.status_code in (200, 204):
            print("[OK] Google Search Console: Sitemap submitted successfully!")
        else:
            print(f"[WARNING] Google Search Console Submission failed (HTTP {resp.status_code}): {resp.text}")
            
    except Exception as e:
        print(f"[ERROR] Error submitting sitemap to Google Search Console: {e}")

# ── Submit to Bing Webmaster API ─────────────────────────────────────────────
def submit_sitemap_to_bing(sitemap_url: str):
    print(f"Submitting sitemap to Bing: {sitemap_url}")
    
    api_key = None
    try:
        api_key = get_secret("BING_WEBMASTER_API_KEY")
    except Exception:
        api_key = os.environ.get("BING_WEBMASTER_API_KEY", "").strip()

    if not api_key:
        print("[WARNING] BING_WEBMASTER_API_KEY not found. Skipping Bing sitemap submission.")
        return

    try:
        bing_api_url = f"https://ssl.bing.com/webmaster/api.svc/json/SubmitFeed?apikey={api_key}"
        payload = {
            "siteUrl": STORE_URL,
            "feedUrl": sitemap_url
        }
        resp = requests.post(bing_api_url, json=payload, timeout=15)
        if resp.status_code == 200:
            print(f"[OK] Bing Webmaster API: Sitemap submitted successfully: {sitemap_url}")
        else:
            print(f"[WARNING] Bing Webmaster API returned status {resp.status_code}: {resp.text}")
    except Exception as e:
        print(f"[ERROR] Bing Webmaster API submission failed for {sitemap_url}: {e}")

def fetch_and_submit_all_sitemaps(custom_image_sitemap_url: str):
    print("Fetching Shopify's main sitemap index to extract sub-sitemaps...")
    sitemap_index_url = f"{STORE_URL}/sitemap.xml"
    sitemaps_to_submit = [sitemap_index_url, custom_image_sitemap_url]
    
    try:
        resp = requests.get(sitemap_index_url, timeout=15)
        if resp.status_code == 200:
            root = ET.fromstring(resp.content)
            namespace = {"ns": "http://www.sitemaps.org/schemas/sitemap/0.9"}
            for sitemap_node in root.findall("ns:sitemap", namespace):
                loc_node = sitemap_node.find("ns:loc", namespace)
                if loc_node is not None and loc_node.text:
                    sitemaps_to_submit.append(loc_node.text.strip())
        else:
            print(f"[WARNING] Could not fetch sitemap index from {sitemap_index_url} (HTTP {resp.status_code})")
    except Exception as e:
        print(f"[WARNING] Failed to parse sitemap index: {e}")
        
    sitemaps_to_submit = list(dict.fromkeys(sitemaps_to_submit))
    print(f"Found {len(sitemaps_to_submit)} sitemaps to submit to Search Engines (Google & Bing):")
    for sm in sitemaps_to_submit:
        print(f"  - {sm}")
        
    # Submit each to Google Search Console and Bing
    for sm in sitemaps_to_submit:
        submit_sitemap_to_gsc(sm)
        submit_sitemap_to_bing(sm)

# ── Main Execution ───────────────────────────────────────────────────────────
def main():
    print("=" * 65)
    print("  Custom Sitemap & Image Sitemap Generator & Submitter")
    print("=" * 65)
    
    # 1. Discover all content
    products = fetch_products_for_sitemap()
    collections = fetch_collections_for_sitemap()
    articles = fetch_articles_for_sitemap()
    
    # 2. Build XML content
    xml_content = generate_image_sitemap(products, collections, articles)
    
    # 3. Upload sitemap to Shopify Files & set redirect
    upload_sitemap_to_shopify(xml_content, filename="sitemap_images.xml")
    
    # The storefront URL for our redirected sitemap
    sitemap_store_url = f"{STORE_URL}/sitemap_images.xml"
    print(f"Sitemap is available at storefront URL: {sitemap_store_url}")
    
    # 4. Submit sitemaps to Search Engines (GSC and Bing)
    fetch_and_submit_all_sitemaps(sitemap_store_url)
    
    print("\n[OK] Sitemap generation & submission workflow completed successfully!")
    print("=" * 65)

if __name__ == "__main__":
    main()

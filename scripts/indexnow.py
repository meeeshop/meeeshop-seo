#!/usr/bin/env python3
"""
indexnow.py — IndexNow (Bing/Yandex) automation for MeeeShop
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Automatically registers your IndexNow verification key in Shopify files,
creates a redirect from /key.txt to the CDN file, and submits new
product and blog URLs to Bing/Yandex for instant crawling.

DEDUPLICATION:
  - Tracks submissions in indexnow_history.json
  - Skips URLs submitted within last 48 hours
"""

import os
import sys
import json
import re
import time
import argparse
from pathlib import Path
from urllib.parse import urlparse
import requests

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

if not TOKEN:
    sys.exit("ERROR: SHOPIFY_ACCESS_TOKEN not set in secrets vault.")

INDEXNOW_KEY = "c5def3bf8d13211be2bacf8d13211be2"
KEY_FILE_NAME = f"{INDEXNOW_KEY}.txt"
HISTORY_FILE = Path("indexnow_history.json")

# ── Shopify helpers ────────────────────────────────────────────────────────────
def _shopify_get(url: str, params: dict = None) -> dict:
    for attempt in range(4):
        try:
            r = requests.get(url, headers=SHP_HDR, params=params, timeout=20)
            if r.status_code == 429:
                time.sleep(int(float(r.headers.get("Retry-After", 4))))
                continue
            r.raise_for_status()
            return r.json()
        except requests.exceptions.ConnectionError:
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"GET {url} failed after 4 attempts")

def _shopify_post(url: str, json_data: dict) -> dict:
    r = requests.post(url, headers=SHP_HDR, json=json_data, timeout=20)
    r.raise_for_status()
    return r.json()

# ── Key Registration (Shopify Files + Redirect) ───────────────────────────────
def verify_and_register_key():
    """Idempotently uploads indexnow key file to Shopify and creates a redirect."""
    print("Checking IndexNow key status in Shopify...")
    graphql_url = f"{BASE}/graphql.json"

    # Check if redirect already exists
    redirect_path = f"/{KEY_FILE_NAME}"
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
    try:
        data = _shopify_post(graphql_url, {"query": query_redirect})
        edges = data.get("data", {}).get("urlRedirects", {}).get("edges", [])
        if edges:
            print(f"✓ IndexNow key redirect already exists: {redirect_path} -> {edges[0]['node']['target'][:60]}...")
            return
    except Exception as e:
        print(f"⚠️ Could not query redirects: {e}. Attempting key upload anyway.")

    # Create local temporary key file
    local_key_path = Path(KEY_FILE_NAME)
    local_key_path.write_text(INDEXNOW_KEY, encoding="utf-8")

    try:
        print("Uploading IndexNow key to Shopify Files...")
        # 1. Staged upload request
        staged_mut = f"""
        mutation {{
          stagedUploadsCreate(input: [{{
            resource: FILE,
            filename: "{KEY_FILE_NAME}",
            mimeType: "text/plain",
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
        with open(local_key_path, "rb") as f:
            files = {"file": (KEY_FILE_NAME, f, "text/plain")}
            params = {p["name"]: p["value"] for p in target["parameters"]}
            upload_resp = requests.post(target["url"], data=params, files=files)
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
            node_data = _shopify_post(graphql_url, {"query": query_file})
            node = node_data.get("data", {}).get("node", {})
            if node.get("fileStatus") == "READY":
                public_url = node.get("url")
                break

        if not public_url:
            raise Exception("Timeout waiting for key file compilation on Shopify CDN.")

        cdn_url = public_url.split("?")[0]
        print(f"IndexNow Key CDN URL: {cdn_url}")

        # 5. Create URL redirect from /key.txt to CDN URL
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
        print(f"✅ Created redirect: {redirect_path} -> {cdn_url}")

    finally:
        if local_key_path.exists():
            local_key_path.unlink()

# ── URL Discovery ──────────────────────────────────────────────────────────────
def fetch_recent_articles(days: int) -> list[str]:
    print(f"Fetching blog posts published in the last {days} days...")
    blogs = _shopify_get(f"{BASE}/blogs.json").get("blogs", [])
    urls = []
    
    # Calculate cutoff time
    from datetime import datetime, timezone, timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_str = cutoff.strftime("%Y-%m-%dT%H:%M:%S%z")

    for blog in blogs:
        blog_id = blog["id"]
        blog_handle = blog.get("handle", "news")
        data = _shopify_get(f"{BASE}/blogs/{blog_id}/articles.json",
                             params={"limit": 100, "published_at_min": cutoff_str,
                                     "published_status": "published",
                                     "fields": "id,handle"})
        for art in data.get("articles", []):
            urls.append(f"{STORE_URL}/blogs/{blog_handle}/{art.get('handle', art['id'])}")
    return urls

def fetch_products(limit: int = 100) -> list[str]:
    print(f"Fetching recently updated products (limit={limit})...")
    data = _shopify_get(f"{BASE}/products.json",
                         params={"limit": limit, "published_status": "published",
                                 "fields": "id,handle"})
    return [f"{STORE_URL}/products/{p['handle']}" for p in data.get("products", []) if p.get("handle")]

# ── Submission History ─────────────────────────────────────────────────────────
def load_history() -> dict:
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def save_history(history: dict):
    HISTORY_FILE.write_text(json.dumps(history, indent=2), encoding="utf-8")

# ── Submit to IndexNow ─────────────────────────────────────────────────────────
def submit_to_indexnow(urls: list[str], dry_run: bool = False):
    if not urls:
        print("No new URLs to submit to IndexNow.")
        return

    domain = urlparse(STORE_URL).netloc
    key_location = f"{STORE_URL}/{KEY_FILE_NAME}"

    payload = {
        "host": domain,
        "key": INDEXNOW_KEY,
        "keyLocation": key_location,
        "urlList": urls
    }

    print(f"\nSubmitting {len(urls)} URLs to IndexNow (Host: {domain})...")
    for u in urls:
        print(f"  + {u}")

    if dry_run:
        print("[DRY-RUN] IndexNow payload prepared, skipping API call.")
        return

    # IndexNow primary engine endpoint (submits to all participating search engines like Bing/Yandex)
    endpoint = "https://api.indexnow.org/indexnow"
    
    try:
        resp = requests.post(endpoint, json=payload, headers={"Content-Type": "application/json; charset=utf-8"}, timeout=15)
        if resp.status_code == 200:
            print("✅ IndexNow submission successful! URLs submitted to search engine queue.")
        else:
            print(f"⚠️ IndexNow submission failed with HTTP status {resp.status_code}: {resp.text}")
    except Exception as e:
        print(f"❌ Connection error during IndexNow submission: {e}")

# ── Main ───────────────────────────────────────────────────────────────────────
def run(days: int = 1, products: bool = False, force: bool = False, dry_run: bool = False):
    print("=" * 65)
    print("  MeeeShop IndexNow submission script")
    print("=" * 65)

    # 1. Setup verify redirect key file
    if not dry_run:
        verify_and_register_key()

    # 2. Gather URLs
    urls = fetch_recent_articles(days)
    if products:
        urls.extend(fetch_products(100))

    urls = list(dict.fromkeys(urls)) # Deduplicate

    # 3. Deduplicate against history
    history = load_history()
    to_submit = []
    now = time.time()
    
    for u in urls:
        last_submitted = history.get(u, 0)
        # Skip if submitted in the last 48 hours (172800 seconds)
        if force or (now - last_submitted > 172800):
            to_submit.append(u)
            if not dry_run:
                history[u] = now
        else:
            print(f"Skipping recently submitted URL: {u}")

    # 4. Submit
    submit_to_indexnow(to_submit, dry_run)

    # 5. Save history
    if not dry_run and to_submit:
        save_history(history)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="IndexNow Submission Automation")
    parser.add_argument("--days", type=int, default=1, help="Lookback days for blogs (default: 1)")
    parser.add_argument("--products", action="store_true", help="Include recently updated products")
    parser.add_argument("--force", action="store_true", help="Force submit all discovered URLs")
    parser.add_argument("--dry-run", action="store_true", help="Dry run mode, do not call API or modify files")
    args = parser.parse_args()

    run(days=args.days, products=args.products, force=args.force, dry_run=args.dry_run)

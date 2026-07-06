#!/usr/bin/env python3
"""
redirect_manager.py — Optimizes 404 scanning by using Shopify GraphQL cached path matching,
allowing us to skip checking active pages and concurrently check the rest.
"""

import os, sys, requests, xml.etree.ElementTree as ET, time, logging
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from secrets_manager import inject_to_env, get_secret
from shopify_graphql import run_graphql

inject_to_env()

STORE = get_secret("SHOPIFY_STORE")
TOKEN = get_secret("SHOPIFY_ACCESS_TOKEN")
BASE_URL = f"https://{STORE}/admin/api/2024-01"
HEADERS = {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}
SITE = get_secret("STORE_BASE_URL") or f"https://{STORE}"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

def get_active_paths() -> set:
    """Fetch all active resource paths from Shopify GraphQL for super-fast lookups."""
    logger.info("Fetching active resources from Shopify GraphQL...")
    active_paths = {"/", "/cart", "/search", "/checkout"}
    
    # 1. Products
    has_next = True
    cursor = None
    query_products = """
    query ($first: Int!, $after: String) {
      products(first: $first, after: $after, query: "status:active") {
        pageInfo { hasNextPage endCursor }
        edges { node { handle } }
      }
    }
    """
    while has_next:
        res = run_graphql(query_products, {"first": 250, "after": cursor})
        data = res.get("data", {}).get("products", {})
        for edge in data.get("edges", []):
            handle = edge.get("node", {}).get("handle")
            if handle:
                active_paths.add(f"/products/{handle}")
        page_info = data.get("pageInfo", {})
        has_next = page_info.get("hasNextPage", False)
        cursor = page_info.get("endCursor")

    # 2. Collections
    has_next = True
    cursor = None
    query_collections = """
    query ($first: Int!, $after: String) {
      collections(first: $first, after: $after) {
        pageInfo { hasNextPage endCursor }
        edges { node { handle } }
      }
    }
    """
    while has_next:
        res = run_graphql(query_collections, {"first": 250, "after": cursor})
        data = res.get("data", {}).get("collections", {})
        for edge in data.get("edges", []):
            handle = edge.get("node", {}).get("handle")
            if handle:
                active_paths.add(f"/collections/{handle}")
        page_info = data.get("pageInfo", {})
        has_next = page_info.get("hasNextPage", False)
        cursor = page_info.get("endCursor")

    # 3. Pages
    has_next = True
    cursor = None
    query_pages = """
    query ($first: Int!, $after: String) {
      pages(first: $first, after: $after) {
        pageInfo { hasNextPage endCursor }
        edges { node { handle } }
      }
    }
    """
    while has_next:
        res = run_graphql(query_pages, {"first": 250, "after": cursor})
        data = res.get("data", {}).get("pages", {})
        for edge in data.get("edges", []):
            handle = edge.get("node", {}).get("handle")
            if handle:
                active_paths.add(f"/pages/{handle}")
        page_info = data.get("pageInfo", {})
        has_next = page_info.get("hasNextPage", False)
        cursor = page_info.get("endCursor")

    # 4. Articles
    has_next = True
    cursor = None
    query_articles = """
    query ($first: Int!, $after: String) {
      articles(first: $first, after: $after) {
        pageInfo { hasNextPage endCursor }
        edges { node { handle blog { handle } } }
      }
    }
    """
    while has_next:
        res = run_graphql(query_articles, {"first": 250, "after": cursor})
        data = res.get("data", {}).get("articles", {})
        for edge in data.get("edges", []):
            node = edge.get("node", {})
            handle = node.get("handle")
            blog_node = node.get("blog")
            blog_handle = blog_node.get("handle") if blog_node else None
            if handle and blog_handle:
                active_paths.add(f"/blogs/{blog_handle}/{handle}")
        page_info = data.get("pageInfo", {})
        has_next = page_info.get("hasNextPage", False)
        cursor = page_info.get("endCursor")

    logger.info(f"Loaded {len(active_paths)} active Shopify resource paths.")
    return active_paths

def fetch_sitemap_urls() -> list:
    """Fetch URL list from the Shopify sitemap.xml."""
    urls = []
    sitemap_url = f"{SITE}/sitemap.xml"
    logger.info(f"Fetching parent sitemap from {sitemap_url}")
    try:
        r = requests.get(sitemap_url, timeout=30)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        ns = {"ns": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        
        sub_sitemaps = [loc.text for loc in root.findall(".//ns:loc", ns)]
        
        if sub_sitemaps:
            for sub in sub_sitemaps:
                logger.info(f"Parsing sub-sitemap: {sub}")
                sub_r = requests.get(sub, timeout=30)
                sub_r.raise_for_status()
                sub_root = ET.fromstring(sub_r.content)
                urls.extend([loc.text for loc in sub_root.findall(".//ns:loc", ns)])
        else:
            urls.extend([loc.text for loc in root.findall(".//ns:loc", ns)])
            
    except Exception as e:
        logger.error(f"Failed to fetch/parse sitemap: {e}")
    return list(set(urls))

def create_redirect(path: str, target: str) -> bool:
    """Register a 301 redirect in Shopify Admin."""
    url = f"{BASE_URL}/redirects.json"
    payload = {
        "redirect": {
            "path": path,
            "target": target
        }
    }
    try:
        r = requests.post(url, headers=HEADERS, json=payload, timeout=20)
        if r.status_code == 429:
            retry_after = int(float(r.headers.get("Retry-After", 4)))
            time.sleep(retry_after)
            r = requests.post(url, headers=HEADERS, json=payload, timeout=20)
            
        if r.status_code in (200, 201):
            logger.info(f"Successfully created redirect: {path} -> {target}")
            return True
        elif r.status_code == 422 and "already has a redirect" in r.text:
            logger.warning(f"Redirect already exists for path: {path}")
            return True
        else:
            logger.error(f"Failed to create redirect for {path}: {r.status_code} - {r.text}")
    except Exception as e:
        logger.error(f"Error calling Shopify Redirects API: {e}")
    return False

def check_url_status(url: str, store_base_path: str) -> tuple:
    """Helper to verify HTTP status of a URL."""
    try:
        r = requests.head(url, allow_redirects=True, timeout=10)
        return url, r.status_code
    except Exception as e:
        return url, -1

def scan_and_fix_broken_urls(urls: list):
    """Verify HTTP status of URLs and register redirects for 404s."""
    active_paths = get_active_paths()
    store_base_path = SITE.rstrip('/')
    
    # 1. Filter out known active paths first to prevent unnecessary network calls
    urls_to_check = []
    skipped_count = 0
    for url in urls:
        if not url.startswith(SITE):
            continue
        
        relative_path = url.replace(store_base_path, "").split("?")[0]
        # Direct active resource check
        if relative_path in active_paths:
            skipped_count += 1
            continue
            
        # Canonical counterpart check for collection-aware product URLs
        if "/collections/" in relative_path and "/products/" in relative_path:
            parts = relative_path.split("/products/")
            canonical_path = f"/products/{parts[-1]}"
            if canonical_path in active_paths:
                # Target path matches an active product canonical URL. Since the original page 
                # might still redirect or load, we check status dynamically or skip it.
                skipped_count += 1
                continue
                
        urls_to_check.append(url)
        
    logger.info(f"Filtered out {skipped_count} active paths. {len(urls_to_check)} URLs remaining for HTTP validation.")
    
    # 2. Concurrently check HTTP statuses of remaining candidates
    redirects_created = 0
    checked_count = 0
    total_to_check = len(urls_to_check)
    
    if not urls_to_check:
        logger.info("All sitemap URLs correspond to active paths. No checks needed.")
        return
        
    logger.info(f"Starting concurrent status verification for {total_to_check} URLs (using 10 threads)...")
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(check_url_status, url, store_base_path): url for url in urls_to_check}
        
        for future in as_completed(futures):
            url, status = future.result()
            checked_count += 1
            
            if checked_count % 50 == 0 or checked_count == total_to_check:
                logger.info(f"Progress: checked {checked_count}/{total_to_check} URLs...")
                
            if status == 404:
                relative_path = url.replace(store_base_path, "")
                
                # Resolve redirect target
                if "/collections/" in relative_path and "/products/" in relative_path:
                    parts = relative_path.split("/products/")
                    canonical_target = f"/products/{parts[-1]}"
                    logger.info(f"Found collection-aware product 404: {relative_path}. Redirecting to canonical: {canonical_target}")
                    if create_redirect(relative_path, canonical_target):
                        redirects_created += 1
                else:
                    logger.info(f"Found general 404: {relative_path}. Redirecting to home path (/).")
                    if create_redirect(relative_path, "/"):
                        redirects_created += 1
                        
    logger.info(f"Status check completed. Created {redirects_created} redirects.")

def main():
    urls = fetch_sitemap_urls()
    if not urls:
        logger.warning("No URLs discovered to check.")
        return
        
    scan_and_fix_broken_urls(urls)

if __name__ == "__main__":
    main()

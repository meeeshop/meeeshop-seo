#!/usr/bin/env python3
"""
redirect_manager.py — Crawls sitemaps and links, detects 404s, and automatically registers 301 redirects in Shopify.
"""

import os, sys, requests, xml.etree.ElementTree as ET, time, logging
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from secrets_manager import inject_to_env, get_secret

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

def fetch_sitemap_urls() -> list:
    """Fetch URL list from the Shopify sitemap.xml."""
    urls = []
    sitemap_url = f"{SITE}/sitemap.xml"
    logger.info(f"Fetching parent sitemap from {sitemap_url}")
    try:
        r = requests.get(sitemap_url, timeout=30)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        # Sitemaps use namespaces
        ns = {"ns": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        
        # Shopify site index references sub-sitemaps
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

def scan_and_fix_broken_urls(urls: list):
    """Verify HTTP status of URLs and register redirects for 404s."""
    logger.info(f"Starting status scan of {len(urls)} URLs...")
    redirects_created = 0
    
    # Process relative to store URL base path
    store_base_path = SITE.rstrip('/')
    
    for url in urls:
        if not url.startswith(SITE):
            continue
            
        # Don't overload the server
        time.sleep(0.5)
        
        try:
            r = requests.head(url, allow_redirects=True, timeout=15)
            status = r.status_code
            if status == 404:
                # Target path resolution logic
                relative_path = url.replace(store_base_path, "")
                
                # Check if it was collection aware product URL
                if "/collections/" in relative_path and "/products/" in relative_path:
                    # e.g., /collections/mens/products/shoe -> redirect to canonical /products/shoe
                    parts = relative_path.split("/products/")
                    canonical_target = f"/products/{parts[-1]}"
                    logger.info(f"Found collection-aware product 404: {relative_path}. Redirecting to canonical: {canonical_target}")
                    if create_redirect(relative_path, canonical_target):
                        redirects_created += 1
                else:
                    # fallback redirect to home page
                    logger.info(f"Found general 404: {relative_path}. Redirecting to home path (/).")
                    if create_redirect(relative_path, "/"):
                        redirects_created += 1
                        
        except Exception as e:
            logger.error(f"Failed checking {url}: {e}")
            
    logger.info(f"Status check completed. Created {redirects_created} redirects.")

def main():
    urls = fetch_sitemap_urls()
    if not urls:
        logger.warning("No URLs discovered to check.")
        return
        
    scan_and_fix_broken_urls(urls)

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
seo_backup_restore.py — Back up and restore SEO metadata for Shopify products,
collections, pages, and blog articles.

This script ensures a safety net before applying SEO modifications.
"""

import os
import sys
import json
import argparse
from datetime import datetime, timezone
from pathlib import Path

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')

# Add parent dir to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.shopify_graphql import (
    run_graphql,
    fetch_products_graphql,
    fetch_collections_graphql,
    fetch_pages_graphql,
    fetch_articles_graphql,
    make_gid,
    parse_gid
)
from secrets_manager import inject_to_env, get_secret

inject_to_env()

STORE = get_secret("SHOPIFY_STORE")
TOKEN = get_secret("SHOPIFY_ACCESS_TOKEN")
HEADS = {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}
BASE_REST = f"https://{STORE}/admin/api/2024-01"

# ── helper function for REST PUT ──────────────────────────────────────────────
def rest_put(endpoint: str, payload: dict) -> dict:
    import requests
    url = f"{BASE_REST}{endpoint}"
    for attempt in range(5):
        try:
            r = requests.put(url, headers=HEADS, json=payload, timeout=30)
            if r.status_code == 429:
                import time
                retry_after = float(r.headers.get("Retry-After", 2.0))
                time.sleep(retry_after)
                continue
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            if attempt < 4:
                import time
                time.sleep(2.0 ** attempt)
            else:
                raise e
    raise RuntimeError(f"REST PUT {endpoint} failed")

# ── helper function to set SEO metafields using GraphQL ───────────────────────
def set_seo_metafields_graphql(resource_type: str, resource_id: int, meta_title: str, meta_desc: str) -> bool:
    # Normalize resource type for GraphQL make_gid
    if "collection" in resource_type.lower():
        gql_type = "collection"
    elif "blog" in resource_type.lower() or "article" in resource_type.lower():
        gql_type = "article"
    elif "page" in resource_type.lower():
        gql_type = "page"
    elif "product" in resource_type.lower():
        gql_type = "product"
    else:
        gql_type = resource_type

    owner_id = make_gid(gql_type, resource_id)
    
    query = """
    mutation metafieldsSet($metafields: [MetafieldsSetInput!]!) {
      metafieldsSet(metafields: $metafields) {
        metafields { id }
        userErrors { field message }
      }
    }
    """
    
    metafields = []
    if meta_title is not None:
        metafields.append({
            "ownerId": owner_id,
            "namespace": "global",
            "key": "title_tag",
            "type": "single_line_text_field",
            "value": meta_title
        })
    if meta_desc is not None:
        metafields.append({
            "ownerId": owner_id,
            "namespace": "global",
            "key": "description_tag",
            "type": "multi_line_text_field",
            "value": meta_desc
        })
        
    if not metafields:
        return True
        
    variables = {"metafields": metafields}
    try:
        res = run_graphql(query, variables)
        errors = res.get("data", {}).get("metafieldsSet", {}).get("userErrors", [])
        if errors:
            print(f"  [GraphQL Error] setting SEO metafields for {owner_id}: {errors}", file=sys.stderr)
            return False
        return True
    except Exception as e:
        print(f"  [GraphQL Exception] setting SEO metafields for {owner_id}: {e}", file=sys.stderr)
        return False

# ── helper function to update alt text ────────────────────────────────────────
def update_image_alt(pid: int, iid: int, alt: str) -> bool:
    product_gid = make_gid("product", pid)
    media_gid = f"gid://shopify/MediaImage/{iid}"
    
    query = """
    mutation productUpdateMedia($productId: ID!, $media: [UpdateMediaInput!]!) {
      productUpdateMedia(productId: $productId, media: $media) {
        media { id alt }
        userErrors { field message }
      }
    }
    """
    variables = {
        "productId": product_gid,
        "media": [{"id": media_gid, "alt": alt}]
    }
    try:
        res = run_graphql(query, variables)
        errors = res.get("data", {}).get("productUpdateMedia", {}).get("userErrors", [])
        if errors:
            print(f"  [GraphQL Error] updating image alt for {media_gid}: {errors}", file=sys.stderr)
            return False
        return True
    except Exception as e:
        print(f"  [GraphQL Exception] updating image alt for {media_gid}: {e}", file=sys.stderr)
        return False

# ── BACKUP FLOW ───────────────────────────────────────────────────────────────
def run_backup(dry_run=False):
    print("Starting SEO Backup of Shopify Store...")
    backup_data = {
        "backup_at": datetime.now(timezone.utc).isoformat(),
        "store": STORE,
        "products": [],
        "collections": [],
        "pages": [],
        "articles": []
    }
    
    # 1. Fetch Products
    print("Fetching active products...")
    prods = fetch_products_graphql(hours=0)
    print(f"Found {len(prods)} products. Extracting metadata...")
    for p in prods:
        mfs = {f"{m['namespace']}.{m['key']}": m for m in p.get('metafields', [])}
        p_backup = {
            "id": p["id"],
            "title": p["title"],
            "handle": p["handle"],
            "body_html": p["body_html"],
            "meta_title": mfs.get("global.title_tag", {}).get("value"),
            "meta_desc": mfs.get("global.description_tag", {}).get("value"),
            "images": [{"id": img["id"], "alt": img["alt"]} for img in p.get("images", [])]
        }
        backup_data["products"].append(p_backup)
        
    # 2. Fetch Collections
    print("Fetching collections...")
    colls = fetch_collections_graphql(hours=0)
    print(f"Found {len(colls)} collections. Extracting metadata...")
    for c in colls:
        mfs = {f"{m['namespace']}.{m['key']}": m for m in c.get('metafields', [])}
        c_backup = {
            "id": c["id"],
            "title": c["title"],
            "handle": c["handle"],
            "body_html": c["body_html"],
            "meta_title": mfs.get("global.title_tag", {}).get("value"),
            "meta_desc": mfs.get("global.description_tag", {}).get("value")
        }
        backup_data["collections"].append(c_backup)
        
    # 3. Fetch Pages
    print("Fetching pages...")
    pages = fetch_pages_graphql(hours=0)
    print(f"Found {len(pages)} pages. Extracting metadata...")
    for pg in pages:
        mfs = {f"{m['namespace']}.{m['key']}": m for m in pg.get('metafields', [])}
        pg_backup = {
            "id": pg["id"],
            "title": pg["title"],
            "handle": pg["handle"],
            "body_html": pg["body_html"],
            "meta_title": mfs.get("global.title_tag", {}).get("value"),
            "meta_desc": mfs.get("global.description_tag", {}).get("value")
        }
        backup_data["pages"].append(pg_backup)
        
    # 4. Fetch Articles
    print("Fetching blog articles...")
    arts = fetch_articles_graphql(hours=0)
    print(f"Found {len(arts)} blog articles. Extracting metadata...")
    for a in arts:
        mfs = {f"{m['namespace']}.{m['key']}": m for m in a.get('metafields', [])}
        a_backup = {
            "id": a["id"],
            "blog_id": a["blog_id"],
            "blog_handle": a["blog_handle"],
            "title": a["title"],
            "handle": a["handle"],
            "body_html": a["body_html"],
            "meta_title": mfs.get("global.title_tag", {}).get("value"),
            "meta_desc": mfs.get("global.description_tag", {}).get("value")
        }
        backup_data["articles"].append(a_backup)
        
    # Write to file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    scratch_dir = Path(__file__).parent.parent / "scratch"
    scratch_dir.mkdir(exist_ok=True)
    backup_file = scratch_dir / f"seo_backup_{timestamp}.json"
    
    if not dry_run:
        backup_file.write_text(json.dumps(backup_data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\n✅ SEO Backup saved to '{backup_file}' successfully!")
    else:
        print(f"\n[DRY RUN] Would write backup data containing:")
        print(f"  Products: {len(backup_data['products'])}")
        print(f"  Collections: {len(backup_data['collections'])}")
        print(f"  Pages: {len(backup_data['pages'])}")
        print(f"  Articles: {len(backup_data['articles'])}")

# ── RESTORE FLOW ──────────────────────────────────────────────────────────────
def run_restore(backup_path: str, dry_run=False):
    print(f"Starting SEO Restore from '{backup_path}'...")
    if not os.path.exists(backup_path):
        sys.exit(f"ERROR: Backup file '{backup_path}' does not exist.")
        
    with open(backup_path, "r", encoding="utf-8") as f:
        backup_data = json.load(f)
        
    # 1. Restore Products
    print(f"\nRestoring {len(backup_data.get('products', []))} products...")
    for p in backup_data.get("products", []):
        pid = p["id"]
        title = p["title"]
        handle = p["handle"]
        body_html = p["body_html"]
        meta_title = p.get("meta_title")
        meta_desc = p.get("meta_desc")
        images = p.get("images", [])
        
        print(f"  Restoring Product ID {pid}: '{title}'")
        if dry_run:
            print(f"    [DRY RUN] Would restore title='{title}', handle='{handle}', body_html_len={len(body_html or '')}")
            print(f"    [DRY RUN] Would restore meta_title='{meta_title}', meta_desc='{meta_desc}'")
            for img in images:
                print(f"    [DRY RUN] Would restore image {img['id']} alt='{img['alt']}'")
        else:
            # Update product basic info
            try:
                rest_put(f"/products/{pid}.json", {
                    "product": {
                        "title": title,
                        "handle": handle,
                        "body_html": body_html
                    }
                })
                print("    ✓ REST fields updated")
            except Exception as e:
                print(f"    ✗ REST fields failed: {e}")
                
            # Update metafields
            success_meta = set_seo_metafields_graphql("product", pid, meta_title or "", meta_desc or "")
            if success_meta:
                print("    ✓ Metafields restored")
            else:
                print("    ✗ Metafields restoration failed")
                
            # Update image alts
            for img in images:
                success_alt = update_image_alt(pid, img["id"], img["alt"] or "")
                if success_alt:
                    print(f"    ✓ Image {img['id']} alt restored")
                else:
                    print(f"    ✗ Image {img['id']} alt restoration failed")

    # 2. Restore Collections
    print(f"\nRestoring {len(backup_data.get('collections', []))} collections...")
    for c in backup_data.get("collections", []):
        cid = c["id"]
        title = c["title"]
        meta_title = c.get("meta_title")
        meta_desc = c.get("meta_desc")
        
        print(f"  Restoring Collection ID {cid}: '{title}'")
        if dry_run:
            print(f"    [DRY RUN] Would restore meta_title='{meta_title}', meta_desc='{meta_desc}'")
        else:
            success_meta = set_seo_metafields_graphql("collection", cid, meta_title or "", meta_desc or "")
            if success_meta:
                print("    ✓ Metafields restored")
            else:
                print("    ✗ Metafields restoration failed")

    # 3. Restore Pages
    print(f"\nRestoring {len(backup_data.get('pages', []))} pages...")
    for pg in backup_data.get("pages", []):
        pgid = pg["id"]
        title = pg["title"]
        meta_title = pg.get("meta_title")
        meta_desc = pg.get("meta_desc")
        
        print(f"  Restoring Page ID {pgid}: '{title}'")
        if dry_run:
            print(f"    [DRY RUN] Would restore meta_title='{meta_title}', meta_desc='{meta_desc}'")
        else:
            success_meta = set_seo_metafields_graphql("page", pgid, meta_title or "", meta_desc or "")
            if success_meta:
                print("    ✓ Metafields restored")
            else:
                print("    ✗ Metafields restoration failed")

    # 4. Restore Articles
    print(f"\nRestoring {len(backup_data.get('articles', []))} articles...")
    for a in backup_data.get("articles", []):
        aid = a["id"]
        title = a["title"]
        meta_title = a.get("meta_title")
        meta_desc = a.get("meta_desc")
        
        print(f"  Restoring Article ID {aid}: '{title}'")
        if dry_run:
            print(f"    [DRY RUN] Would restore meta_title='{meta_title}', meta_desc='{meta_desc}'")
        else:
            success_meta = set_seo_metafields_graphql("article", aid, meta_title or "", meta_desc or "")
            if success_meta:
                print("    ✓ Metafields restored")
            else:
                print("    ✗ Metafields restoration failed")

    print(f"\n✅ Restore completed{' (Dry Run)' if dry_run else ''}!")

# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Shopify SEO Backup & Restore tool")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--backup", action="store_true", help="Create a backup of all current SEO fields")
    group.add_argument("--restore", type=str, help="Restore SEO fields from a backup JSON file path")
    parser.add_argument("--dry-run", action="store_true", help="Perform dry run without making Shopify writes")
    
    args = parser.parse_args()
    
    if args.backup:
        run_backup(dry_run=args.dry_run)
    elif args.restore:
        run_restore(args.restore, dry_run=args.dry_run)

if __name__ == "__main__":
    main()

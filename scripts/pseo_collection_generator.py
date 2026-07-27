#!/usr/bin/env python3
"""
pseo_collection_generator.py — Programmatic SEO (pSEO) Occasion Hubs
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Scans Shopify inventory for 4-part attribute combinations:
[Target] + [Color/Pattern] + [Material/Occasion] + [Product Type]
Enforces 5+ in-stock product threshold before generating landing pages.
"""

import os
import sys
import json
import re
import argparse
from pathlib import Path
import requests

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')

# Path setup
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(REPO_ROOT))

from secrets_manager import inject_to_env, get_secret
inject_to_env()

SHOP = get_secret("SHOPIFY_STORE")
TOKEN = get_secret("SHOPIFY_ACCESS_TOKEN")
STORE_URL = (get_secret("STORE_BASE_URL") or "https://us.meeeshop.com").rstrip("/")
API_VER = "2024-10"
GRAPHQL_URL = f"https://{SHOP}/admin/api/{API_VER}/graphql.json"
HEADERS = {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}

COLORS = ['black', 'white', 'blue', 'green', 'emerald', 'red', 'pink', 'floral', 'print', 'yellow', 'beige', 'navy']
MATERIALS_OCCASIONS = ['silk', 'linen', 'boho', 'vintage', 'summer', 'evening', 'casual', 'cocktail', 'party', 'workwear', 'knit', 'denim']
TYPES = ['dresses', 'tops', 'blouses', 'skirts', 'pants', 'jeans', 'jackets', 'sweaters', 'maxi-dresses']

def run_query(query: str, variables: dict = None) -> dict:
    resp = requests.post(GRAPHQL_URL, headers=HEADERS, json={"query": query, "variables": variables or {}}, timeout=20)
    resp.raise_for_status()
    return resp.json()

def extract_strict_colors(title, variant_nodes):
    colors = set()
    t_lower = title.lower()
    for col in COLORS:
        if f" {col} " in f" {t_lower} " or f"({col})" in t_lower or f"- {col}" in t_lower or f"_{col}" in t_lower:
            if "black friday" not in t_lower:
                colors.add(col)
                
    for v in variant_nodes:
        for opt in v.get("selectedOptions", []):
            val = (opt.get("value") or "").lower()
            for col in COLORS:
                if col in val:
                    colors.add(col)
        v_title = (v.get("title") or "").lower()
        for col in COLORS:
            if col in v_title:
                colors.add(col)
                
    return colors

def fetch_catalog_products():
    q = """
    query {
      products(first: 250, query: "status:active") {
        edges {
          node {
            id
            title
            handle
            productType
            tags
            totalInventory
            variants(first: 50) {
              edges {
                node {
                  title
                  selectedOptions {
                    name
                    value
                  }
                }
              }
            }
          }
        }
      }
    }
    """
    res = run_query(q)
    edges = res.get("data", {}).get("products", {}).get("edges", [])
    products = []
    for e in edges:
        p = e["node"]
        if (p.get("totalInventory") or 0) > 0:
            var_nodes = [v["node"] for v in p.get("variants", {}).get("edges", [])]
            strict_colors = extract_strict_colors(p["title"], var_nodes)
            
            products.append({
                "id": p["id"],
                "title": p["title"],
                "handle": p["handle"],
                "type": (p.get("productType") or "").lower(),
                "tags": [t.lower() for t in p.get("tags", [])],
                "colors": strict_colors
            })
    return products

def generate_pseo_combinations(products):
    combinations = {}
    
    for color in COLORS:
        for mat in MATERIALS_OCCASIONS:
            for ptype in TYPES:
                comb_title = f"Women's {color.title()} {mat.title()} {ptype.title()}"
                comb_handle = f"womens-{color}-{mat}-{ptype}"
                
                ptype_stem = ptype[:-1] if ptype.endswith("s") else ptype
                
                matching = []
                for p in products:
                    # 1. Strict Color Match (must exist in title or variant options)
                    if color not in p["colors"]:
                        continue
                        
                    # 2. Material / Occasion Match
                    txt = f"{p['title']} {' '.join(p['tags'])}".lower()
                    if mat not in txt:
                        continue
                        
                    # 3. Product Type Match
                    p_type_txt = f"{p['title']} {p['type']} {' '.join(p['tags'])}".lower()
                    if ptype_stem not in p_type_txt:
                        continue
                        
                    matching.append(p)
                    
                # STRICT RULE OF 5 GUARDRAIL
                if len(matching) >= 5:
                    combinations[comb_handle] = {
                        "title": comb_title,
                        "handle": comb_handle,
                        "color": color,
                        "material": mat,
                        "type": ptype,
                        "count": len(matching),
                        "products": matching
                    }
                    
    return combinations


def build_pseo_description(title, color, material, ptype, count):
    intro = f"""
    <div class="pseo-seo-intro" style="margin-bottom: 20px; line-height: 1.6;">
        <p>Explore our curated collection of <strong>{title}</strong> at MeeeShop. Featuring {count} premium styles in {color} {material}, designed for effortless elegance and comfort. All orders qualify for free US shipping and our 7-day return guarantee.</p>
    </div>
    """
    
    faq_schema = f"""
    <script type="application/ld+json">
    {{
      "@context": "https://schema.org",
      "@type": "FAQPage",
      "mainEntity": [
        {{
          "@type": "Question",
          "name": "What sizes are available in {title}?",
          "acceptedAnswer": {{
            "@type": "Answer",
            "text": "Our {title} selection includes US sizes from S to XL (and select 3XL options). Check each product size chart for exact measurements."
          }}
        }},
        {{
          "@type": "Question",
          "name": "How fast is US shipping for {title}?",
          "acceptedAnswer": {{
            "@type": "Answer",
            "text": "We offer fast standard US shipping with orders processing in 1-2 business days."
          }}
        }},
        {{
          "@type": "Question",
          "name": "What is the return policy?",
          "acceptedAnswer": {{
            "@type": "Answer",
            "text": "We provide a 7-day return policy for all unworn items in original packaging."
          }}
        }}
      ]
    }}
    </script>
    """
    return intro + faq_schema

from datetime import datetime, timezone

BASE = f"https://{SHOP}/admin/api/2024-10"

def create_or_update_collection(handle, title, body_html, color, material, ptype, matching_products):
    payload = {
        "custom_collection": {
            "title": title,
            "handle": handle,
            "body_html": body_html,
            "published": True,
            "published_scope": "global",
            "published_at": datetime.now(timezone.utc).isoformat()
        }
    }

    try:
        # 1. Clean up legacy smart collections with same handle if any exist
        r_sm = requests.get(f"{BASE}/smart_collections.json?handle={handle}", headers=HEADERS)
        sm_cols = r_sm.json().get("smart_collections", []) if r_sm.status_code == 200 else []
        for sm in sm_cols:
            requests.delete(f"{BASE}/smart_collections/{sm['id']}.json", headers=HEADERS)
            print(f"  [pSEO] Cleaned up legacy smart collection: {handle} (ID: {sm['id']})")

        # 2. Create or update custom collection
        r_check = requests.get(f"{BASE}/custom_collections.json?handle={handle}", headers=HEADERS)
        existing = r_check.json().get("custom_collections", []) if r_check.status_code == 200 else []

        if existing:
            cid = existing[0]["id"]
            r_up = requests.put(f"{BASE}/custom_collections/{cid}.json", headers=HEADERS, json=payload)
            if r_up.status_code in (200, 201):
                print(f"  [pSEO] Updated custom collection: {title} (ID: {cid}) with global sales channels.")
        else:
            r_cr = requests.post(f"{BASE}/custom_collections.json", headers=HEADERS, json=payload)
            if r_cr.status_code in (200, 201):
                cid = r_cr.json().get("custom_collection", {}).get("id")
                print(f"  [pSEO] Created custom collection: {title} (ID: {cid}) with global sales channels.")
            else:
                print(f"  [pSEO] Warning creating {title}: {r_cr.text}")
                return

        # 3. Explicitly link all matching products via collects API
        r_coll = requests.get(f"{BASE}/collects.json?collection_id={cid}", headers=HEADERS)
        existing_collects = r_coll.json().get("collects", []) if r_coll.status_code == 200 else []
        existing_pids = {c["product_id"] for c in existing_collects}

        added_count = 0
        for p in matching_products:
            raw_id = p["id"]
            numeric_pid = int(str(raw_id).split("/")[-1])
            if numeric_pid not in existing_pids:
                r_add = requests.post(f"{BASE}/collects.json", headers=HEADERS, json={"collect": {"collection_id": cid, "product_id": numeric_pid}})
                if r_add.status_code in (200, 201):
                    added_count += 1
                    existing_pids.add(numeric_pid)

        total_prods = len(existing_pids)
        print(f"  [pSEO] ✅ Collection {title} ({handle}) now contains {total_prods} verified products & global sales channels.")

    except Exception as e:
        print(f"  [pSEO] Error processing collection {handle}: {e}")

def cleanup_non_compliant_collections(valid_handles: set):
    """Delete any pSEO custom collection whose valid product count has dropped below 5 or was created in error."""
    try:
        r = requests.get(f"{BASE}/custom_collections.json?limit=250", headers=HEADERS)
        cols = r.json().get("custom_collections", []) if r.status_code == 200 else []
        
        for c in cols:
            handle = c.get("handle", "")
            # Only target auto-generated pSEO collection handles matching our formula
            if handle.startswith("womens-") and ("-dresses" in handle or "-tops" in handle or "-blouses" in handle or "-skirts" in handle or "-pants" in handle or "-jeans" in handle or "-jackets" in handle or "-sweaters" in handle) and handle not in valid_handles:
                cid = c["id"]
                title = c.get("title")
                requests.delete(f"{BASE}/custom_collections/{cid}.json", headers=HEADERS)
                print(f"  [pSEO Cleanup] 🗑️ Deleted non-compliant collection: '{title}' ({handle}) — insufficient verified variant color matches.")
    except Exception as e:
        print(f"Warning during pSEO collection cleanup: {e}")

def run_pseo_pipeline(dry_run=False):
    print("🔍 Fetching active in-stock products for pSEO analysis...")
    products = fetch_catalog_products()
    print(f"  Found {len(products)} active in-stock products.")
    
    combs = generate_pseo_combinations(products)
    print(f"✅ Identified {len(combs)} pSEO combinations meeting the strict 5+ item threshold.")
    
    valid_handles = set(combs.keys())
    
    for handle, data in combs.items():
        print(f"  • {data['title']} -> {data['count']} matching items")
        if not dry_run:
            html = build_pseo_description(data['title'], data['color'], data['material'], data['type'], data['count'])
            create_or_update_collection(handle, data['title'], html, data['color'], data['material'], data['type'], data['products'])
            
    if not dry_run:
        cleanup_non_compliant_collections(valid_handles)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="pSEO Occasion Hub Generator")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without creating collections")
    args = parser.parse_args()
    
    run_pseo_pipeline(dry_run=args.dry_run)




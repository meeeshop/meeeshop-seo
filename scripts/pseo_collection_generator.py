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

# Key attribute matrices
COLORS = ['black', 'white', 'blue', 'green', 'emerald', 'red', 'pink', 'floral', 'print', 'yellow', 'beige', 'navy']
MATERIALS_OCCASIONS = ['silk', 'linen', 'boho', 'vintage', 'summer', 'evening', 'casual', 'cocktail', 'party', 'workwear', 'knit', 'denim']
TYPES = ['dresses', 'tops', 'blouses', 'skirts', 'pants', 'jeans', 'jackets', 'sweaters', 'maxi-dresses']

def run_query(query: str, variables: dict = None) -> dict:
    resp = requests.post(GRAPHQL_URL, headers=HEADERS, json={"query": query, "variables": variables or {}}, timeout=20)
    resp.raise_for_status()
    return resp.json()

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
            products.append({
                "id": p["id"],
                "title": p["title"],
                "handle": p["handle"],
                "type": (p.get("productType") or "").lower(),
                "tags": [t.lower() for t in p.get("tags", [])],
                "search_text": f"{p['title']} {p.get('productType','')} {' '.join(p.get('tags',[]))}".lower()
            })
    return products

def generate_pseo_combinations(products):
    combinations = {}
    
    for color in COLORS:
        for mat in MATERIALS_OCCASIONS:
            for ptype in TYPES:
                comb_title = f"Women's {color.title()} {mat.title()} {ptype.title()}"
                comb_handle = f"womens-{color}-{mat}-{ptype}"
                
                # Filter products matching all attributes
                matching = []
                for p in products:
                    txt = p["search_text"]
                    if color in txt and mat in txt and ptype[:-1] in txt:
                        matching.append(p)
                        
                # RULE OF 5 GUARDRAIL
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

def create_or_update_collection(handle, title, body_html, color, material, ptype):
    type_singular = ptype[:-1] if ptype.endswith("s") else ptype
    rules = [
        {"column": "title", "relation": "contains", "condition": type_singular.title()},
        {"column": "title", "relation": "contains", "condition": color.title()}
    ]
    if material.lower() not in ('casual', 'summer', 'evening'):
        rules.append({"column": "title", "relation": "contains", "condition": material.title()})

    payload = {
        "smart_collection": {
            "title": title,
            "handle": handle,
            "body_html": body_html,
            "published_scope": "global",
            "published": True,
            "published_at": datetime.now(timezone.utc).isoformat(),
            "disjunctive": False,
            "rules": rules
        }
    }

    try:
        r_check = requests.get(f"{BASE}/smart_collections.json?handle={handle}", headers=HEADERS)
        existing = r_check.json().get("smart_collections", []) if r_check.status_code == 200 else []

        if existing:
            cid = existing[0]["id"]
            r_up = requests.put(f"{BASE}/smart_collections/{cid}.json", headers=HEADERS, json=payload)
            if r_up.status_code in (200, 201):
                data = r_up.json().get("smart_collection", {})
                print(f"  [pSEO] Updated collection: {title} (ID: {cid}) with global sales channels.")
            else:
                print(f"  [pSEO] Warning updating {title}: {r_up.text}")
        else:
            r_cr = requests.post(f"{BASE}/smart_collections.json", headers=HEADERS, json=payload)
            if r_cr.status_code in (200, 201):
                data = r_cr.json().get("smart_collection", {})
                print(f"  [pSEO] Created collection: {title} (ID: {data.get('id')}) with global sales channels.")
            else:
                print(f"  [pSEO] Warning creating {title}: {r_cr.text}")
    except Exception as e:
        print(f"  [pSEO] Error processing collection {handle}: {e}")

def run_pseo_pipeline(dry_run=False):
    print("🔍 Fetching active in-stock products for pSEO analysis...")
    products = fetch_catalog_products()
    print(f"  Found {len(products)} active in-stock products.")
    
    combs = generate_pseo_combinations(products)
    print(f"✅ Identified {len(combs)} pSEO combinations meeting the 5+ item threshold.")
    
    for handle, data in combs.items():
        print(f"  • {data['title']} -> {data['count']} matching items")
        if not dry_run:
            html = build_pseo_description(data['title'], data['color'], data['material'], data['type'], data['count'])
            create_or_update_collection(handle, data['title'], html, data['color'], data['material'], data['type'])

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="pSEO Occasion Hub Generator")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without creating collections")
    args = parser.parse_args()
    
    run_pseo_pipeline(dry_run=args.dry_run)


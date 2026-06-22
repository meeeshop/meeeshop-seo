import os
import sys
import json
import requests
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
from secrets_manager import inject_to_env, get_secret
inject_to_env()

STORE = get_secret("SHOPIFY_STORE")
TOKEN = get_secret("SHOPIFY_ACCESS_TOKEN")
API_VER = "2024-01"
BASE_URL = f"https://{STORE}/admin/api/{API_VER}"
HEADERS = {
    "X-Shopify-Access-Token": TOKEN,
    "Content-Type": "application/json"
}

# Import target mapping from optimize_zsv_metafields
from optimize_zsv_metafields import OPTIMIZED_SEO, set_seo_metafields

# New ZSV collections to create
NEW_ZSV_COLLECTIONS = {
    "womens-loungewear": (
        "Women's Loungewear & Basics | Cozy Casual Styling",
        "Shop comfortable loungewear, cozy sets, and casual basics for women at MeeeShop. Free US shipping & 7-day returns on all lounge styles.",
        "Women's Loungewear & Basics",
        "<p>Shop comfortable loungewear, cozy sets, and casual basics for women at MeeeShop. Made with ultra-soft fabrics for everyday style. Enjoy free US shipping and 7-day returns.</p>"
    ),
    "womens-graphic-tees": (
        "Women's Graphic T-Shirts & Tees | Retro Boutique Styles",
        "Shop retro, cute women's graphic t-shirts and tees at MeeeShop. Discover trendy graphic prints and comfy fits. Free US shipping & returns.",
        "Women's Graphic T-Shirts & Tees",
        "<p>Browse cute, trendy graphic t-shirts and retro tees for women at MeeeShop. Perfect for effortless casual style and daily layering. Free US shipping & 7-day returns.</p>"
    ),
    "womens-tunics": (
        "Women's Tunics & Flowy Tops | Casual Chic Boutique Styles",
        "Discover comfortable women's tunics and flowy tops at MeeeShop. Flattering long blouses and casual cuts. Free US shipping & 7-day returns.",
        "Women's Tunics & Flowy Tops",
        "<p>Shop gorgeous women's tunics, flowy tops, and long blouses at MeeeShop. Flattering fits and easy everyday comfort. Includes free US shipping and 7-day returns.</p>"
    ),
    "womens-coats-jackets": (
        "Women's Coats & Jackets | Chic Outerwear & Layering Pieces",
        "Shop trendy women's coats, jackets, and winter layers at MeeeShop. Find cozy outerwear and classic blazers. Free US shipping and returns.",
        "Women's Coats & Jackets",
        "<p>Stay warm in style with chic coats and jackets for women at MeeeShop. Discover classic layers, blazers, and outerwear designed for comfort. Free US shipping & 7-day returns.</p>"
    ),
    "womens-new-denim": (
        "New Arrivals Denim & Jeans | Premium Stretchy Fits at MeeeShop",
        "Discover the latest new arrivals in premium denim and stretch jeans for women. Flattering washes and trendy styles. Free US shipping & returns.",
        "New Arrivals Denim & Jeans",
        "<p>Explore the latest new arrivals in premium women's denim and jeans at MeeeShop. Stretchy straight leg, flare, and skinny fits. Free US shipping & 7-day returns.</p>"
    )
}

# Rules defining how products should be dynamically populated
COLLECTION_RULES = {
    "womens-loungewear": {
        "rules": [
            {"column": "type", "relation": "equals", "condition": "LOUNGEWEAR"},
            {"column": "title", "relation": "contains", "condition": "lounge"}
        ]
    },
    "womens-graphic-tees": {
        "rules": [
            {"column": "type", "relation": "equals", "condition": "Graphic T's"},
            {"column": "title", "relation": "contains", "condition": "graphic"}
        ]
    },
    "womens-tunics": {
        "rules": [
            {"column": "type", "relation": "equals", "condition": "Tunic"},
            {"column": "title", "relation": "contains", "condition": "tunic"}
        ]
    },
    "womens-coats-jackets": {
        "rules": [
            {"column": "type", "relation": "equals", "condition": "Coats & Jackets"},
            {"column": "type", "relation": "equals", "condition": "Jacket"},
            {"column": "title", "relation": "contains", "condition": "jacket"},
            {"column": "title", "relation": "contains", "condition": "coat"}
        ]
    },
    "womens-new-denim": {
        "rules": [
            {"column": "type", "relation": "equals", "condition": "DENIM (NEW)"},
            {"column": "type", "relation": "equals", "condition": "DENIM JEANS"},
            {"column": "title", "relation": "contains", "condition": "denim"}
        ]
    },
    "emory-park-womens-clothing": {
        "rules": [{"column": "vendor", "relation": "equals", "condition": "EMORY PARK"}]
    },
    "pol-womens-clothing-collection": {
        "rules": [{"column": "vendor", "relation": "equals", "condition": "POL"}]
    },
    "zenana-womens-clothing": {
        "rules": [{"column": "vendor", "relation": "equals", "condition": "ZENANA"}]
    },
    "judy-blue-womens-jeans": {
        "rules": [{"column": "vendor", "relation": "equals", "condition": "JUDY BLUE"}]
    },
    "risen-womens-jeans-collection": {
        "rules": [{"column": "vendor", "relation": "equals", "condition": "RISEN JEANS"}]
    },
    "hyfve-womens-clothing": {
        "rules": [{"column": "vendor", "relation": "equals", "condition": "HYFVE"}]
    },
    "umgee-usa-womens-clothing": {
        "rules": [{"column": "vendor", "relation": "equals", "condition": "Umgee USA"}]
    },
    "bibi-womens-clothing": {
        "rules": [{"column": "vendor", "relation": "equals", "condition": "BIBI"}]
    },
    "artemis-vintage-womens-jeans": {
        "rules": [{"column": "vendor", "relation": "equals", "condition": "ARTEMIS VINTAGE"}]
    },
    "womens-cardigans": {
        "rules": [{"column": "type", "relation": "equals", "condition": "Cardigans"}]
    },
    "womens-sweaters": {
        "rules": [{"column": "type", "relation": "equals", "condition": "Sweaters"}]
    },
    "womens-maxi-dresses": {
        "rules": [
            {"column": "type", "relation": "equals", "condition": "Dresses"},
            {"column": "title", "relation": "contains", "condition": "maxi"}
        ]
    },
    "womens-casual-dresses": {
        "rules": [
            {"column": "type", "relation": "equals", "condition": "Dresses"},
            {"column": "title", "relation": "contains", "condition": "casual"}
        ]
    },
    "womens-cocktail-dresses": {
        "rules": [
            {"column": "type", "relation": "equals", "condition": "Dresses"},
            {"column": "title", "relation": "contains", "condition": "cocktail"}
        ]
    },
    "womens-dresses": {
        "rules": [{"column": "type", "relation": "equals", "condition": "Dresses"}]
    },
    "womens-shirts": {
        "rules": [{"column": "type", "relation": "equals", "condition": "Shirts"}]
    },
    "womens-camis-tanks-tops": {
        "rules": [
            {"column": "type", "relation": "equals", "condition": "Tops"},
            {"column": "title", "relation": "contains", "condition": "tank"}
        ]
    },
    "womens-knit-tops": {
        "rules": [
            {"column": "type", "relation": "equals", "condition": "Tops"},
            {"column": "title", "relation": "contains", "condition": "knit"}
        ]
    },
    "womens-t-shirts": {
        "rules": [{"column": "type", "relation": "equals", "condition": "T-Shirts"}]
    },
    "womens-tops": {
        "rules": [{"column": "type", "relation": "equals", "condition": "Tops"}]
    },
    "womens-outerwear": {
        "rules": [{"column": "type", "relation": "equals", "condition": "Outerwear"}]
    },
    "womens-bottoms": {
        "rules": [{"column": "type", "relation": "equals", "condition": "Bottoms"}]
    },
    "womens-pants-leggings": {
        "rules": [{"column": "type", "relation": "equals", "condition": "Pants"}]
    },
    "womens-shorts": {
        "rules": [{"column": "type", "relation": "equals", "condition": "Shorts"}]
    },
    "womens-skirts": {
        "rules": [{"column": "type", "relation": "equals", "condition": "Skirts"}]
    },
    "womens-jeans": {
        "rules": [{"column": "type", "relation": "equals", "condition": "Jeans"}]
    },
    "womens-denim-tops-jackets": {
        "rules": [
            {"column": "type", "relation": "equals", "condition": "Jeans"},
            {"column": "title", "relation": "contains", "condition": "jacket"}
        ]
    },
    "womens-sweatshirts": {
        "rules": [{"column": "type", "relation": "equals", "condition": "Sweatshirts"}]
    },
    "womens-sweatshirts-hoodies": {
        "rules": [{"column": "type", "relation": "equals", "condition": "Hoodies"}]
    },
    "womens-hoodies": {
        "rules": [{"column": "type", "relation": "equals", "condition": "Hoodies"}]
    },
    "womens-handbags-accessories": {
        "rules": [{"column": "type", "relation": "equals", "condition": "Bags"}]
    },
    "womens-rompers-jumpsuit-sets": {
        "rules": [{"column": "type", "relation": "equals", "condition": "Jumpsuits"}]
    }
}

def fetch_existing_collections():
    url = f"{BASE_URL}/smart_collections.json?limit=250"
    r = requests.get(url, headers=HEADERS)
    r.raise_for_status()
    smart = r.json().get("smart_collections", [])

    url2 = f"{BASE_URL}/custom_collections.json?limit=250"
    r2 = requests.get(url2, headers=HEADERS)
    r2.raise_for_status()
    custom = r2.json().get("custom_collections", [])

    return {c["handle"]: c for c in smart + custom}

def create_smart_collection(handle, title, body_html, rules):
    url = f"{BASE_URL}/smart_collections.json"
    payload = {
        "smart_collection": {
            "title": title,
            "handle": handle,
            "body_html": body_html,
            "rules": rules,
            "disjunctive": True  # match any rule condition if multiple rules exist
        }
    }
    r = requests.post(url, headers=HEADERS, json=payload)
    if r.status_code == 429:
        wait = float(r.headers.get("Retry-After", 2.0))
        time.sleep(wait)
        r = requests.post(url, headers=HEADERS, json=payload)
    r.raise_for_status()
    return r.json()["smart_collection"]

def main():
    print("Fetching existing collections from Shopify...")
    existing = fetch_existing_collections()
    print(f"Found {len(existing)} existing collections.")

    created_count = 0
    for handle, target in NEW_ZSV_COLLECTIONS.items():
        seo_title, seo_desc, normal_title, normal_desc = target
        
        if handle in existing:
            # Already exists, skip creation
            print(f"Collection {normal_title} ({handle}) already exists. Skipping.")
            continue

        rules_info = COLLECTION_RULES.get(handle)
        if not rules_info:
            print(f"No automation rules defined for collection: {handle}. Skipping creation.")
            continue

        print(f"Creating automated ZSV collection: {normal_title} ({handle})...")
        try:
            col = create_smart_collection(handle, normal_title, normal_desc, rules_info["rules"])
            print(f"  [OK] Created Smart Collection ID: {col['id']}")
            
            # Set SEO metafields
            seo_success = set_seo_metafields(col["id"], seo_title, seo_desc)
            if seo_success:
                print(f"  [OK] Set SEO Metafields for {normal_title}")
            
            created_count += 1
            time.sleep(0.5)  # Rate limiting safety
        except Exception as e:
            print(f"  [ERROR] Failed to create {normal_title}: {e}")

    print(f"\nAutomation complete! Created {created_count} new automated collections.")

if __name__ == "__main__":
    main()

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

# Define the optimized matching rules (disjunctive matching where appropriate)
OPTIMIZED_RULES = {
    "womens-jeans": {
        "disjunctive": True,
        "rules": [
            {"column": "type", "relation": "equals", "condition": "Jeans"},
            {"column": "type", "relation": "equals", "condition": "DENIM JEANS"},
            {"column": "type", "relation": "equals", "condition": "DENIM (NEW)"},
            {"column": "title", "relation": "contains", "condition": "Jean"},
            {"column": "tag", "relation": "equals", "condition": "Jeans"}
        ]
    },
    "pol-womens-clothing-collection": {
        "disjunctive": True,
        "rules": [
            {"column": "tag", "relation": "equals", "condition": "POL"},
            {"column": "vendor", "relation": "equals", "condition": "POL"},
            {"column": "title", "relation": "starts_with", "condition": "POL "},
            {"column": "title", "relation": "starts_with", "condition": "Pol "}
        ]
    },
    "bibi-womens-clothing": {
        "disjunctive": True,
        "rules": [
            {"column": "tag", "relation": "equals", "condition": "BiBi"},
            {"column": "tag", "relation": "equals", "condition": "BIBI"},
            {"column": "vendor", "relation": "equals", "condition": "BiBi"},
            {"column": "vendor", "relation": "equals", "condition": "BIBI"},
            {"column": "title", "relation": "contains", "condition": "Bibi"}
        ]
    },
    "risen-womens-jeans-collection": {
        "disjunctive": True,
        "rules": [
            {"column": "tag", "relation": "equals", "condition": "RISEN"},
            {"column": "tag", "relation": "equals", "condition": "Risen"},
            {"column": "vendor", "relation": "equals", "condition": "RISEN JEANS"},
            {"column": "vendor", "relation": "equals", "condition": "Risen"},
            {"column": "title", "relation": "contains", "condition": "Risen"}
        ]
    },
    "umgee-usa-womens-clothing": {
        "disjunctive": True,
        "rules": [
            {"column": "tag", "relation": "equals", "condition": "Umgee USA"},
            {"column": "tag", "relation": "equals", "condition": "Umgee"},
            {"column": "vendor", "relation": "equals", "condition": "Umgee USA"},
            {"column": "vendor", "relation": "equals", "condition": "Umgee"},
            {"column": "title", "relation": "contains", "condition": "Umgee"}
        ]
    },
    "zenana-womens-clothing": {
        "disjunctive": True,
        "rules": [
            {"column": "tag", "relation": "equals", "condition": "Zenana"},
            {"column": "tag", "relation": "equals", "condition": "ZENANA"},
            {"column": "vendor", "relation": "equals", "condition": "Zenana"},
            {"column": "vendor", "relation": "equals", "condition": "ZENANA"},
            {"column": "title", "relation": "contains", "condition": "Zenana"}
        ]
    },
    "womens-blazers-vests-jackets": {
        "disjunctive": True,
        "rules": [
            {"column": "tag", "relation": "equals", "condition": "Jackets & Blazers"},
            {"column": "tag", "relation": "equals", "condition": "Vests"},
            {"column": "title", "relation": "contains", "condition": "Blazer"},
            {"column": "title", "relation": "contains", "condition": "Vest"},
            {"column": "title", "relation": "contains", "condition": "Jacket"},
            {"column": "title", "relation": "contains", "condition": "Coat"},
            {"column": "type", "relation": "equals", "condition": "Coats & Jackets"},
            {"column": "type", "relation": "equals", "condition": "Jacket"}
        ]
    },
    "womens-shoes": {
        "disjunctive": True,
        "rules": [
            {"column": "tag", "relation": "equals", "condition": "Shoes"},
            {"column": "title", "relation": "contains", "condition": "Shoe"},
            {"column": "title", "relation": "contains", "condition": "Shoes"},
            {"column": "title", "relation": "contains", "condition": "Sandal"},
            {"column": "title", "relation": "contains", "condition": "Sandals"},
            {"column": "title", "relation": "contains", "condition": "Combat Boots"},
            {"column": "title", "relation": "contains", "condition": "Platform Booties"},
            {"column": "title", "relation": "contains", "condition": "Heels"},
            {"column": "title", "relation": "contains", "condition": "Heel"},
            {"column": "title", "relation": "contains", "condition": "Mules"},
            {"column": "title", "relation": "contains", "condition": "Mule"},
            {"column": "title", "relation": "contains", "condition": "Sneaker"},
            {"column": "title", "relation": "contains", "condition": "Sneakers"}
        ]
    },
    "womens-tops": {
        "disjunctive": True,
        "rules": [
            {"column": "type", "relation": "equals", "condition": "Shirts & Tops"},
            {"column": "type", "relation": "equals", "condition": "Tops"},
            {"column": "type", "relation": "equals", "condition": "TOPS"},
            {"column": "type", "relation": "equals", "condition": "Shirt"},
            {"column": "title", "relation": "contains", "condition": "Top"},
            {"column": "title", "relation": "contains", "condition": "Blouse"},
            {"column": "title", "relation": "contains", "condition": "Tee"},
            {"column": "title", "relation": "contains", "condition": "Shirt"}
        ]
    },
    "mini-dresses": {
        "disjunctive": True,
        "rules": [
            {"column": "title", "relation": "contains", "condition": "Mini Dress"},
            {"column": "title", "relation": "contains", "condition": "Mini Dresses"},
            {"column": "tag", "relation": "equals", "condition": "Mini Dress"},
            {"column": "tag", "relation": "equals", "condition": "Mini Dresses"}
        ]
    },
    "midi-dresses": {
        "disjunctive": True,
        "rules": [
            {"column": "title", "relation": "contains", "condition": "Midi Dress"},
            {"column": "title", "relation": "contains", "condition": "Midi Dresses"},
            {"column": "tag", "relation": "equals", "condition": "Midi Dress"},
            {"column": "tag", "relation": "equals", "condition": "Midi Dresses"}
        ]
    },
    "womens-maxi-dresses": {
        "disjunctive": True,
        "rules": [
            {"column": "title", "relation": "contains", "condition": "Maxi Dress"},
            {"column": "title", "relation": "contains", "condition": "Maxi Dresses"},
            {"column": "tag", "relation": "equals", "condition": "Maxi Dress"},
            {"column": "tag", "relation": "equals", "condition": "Maxi Dresses"}
        ]
    },
    "womens-skirts": {
        "disjunctive": True,
        "rules": [
            {"column": "type", "relation": "equals", "condition": "Skirts"},
            {"column": "type", "relation": "equals", "condition": "SKIRTS"},
            {"column": "type", "relation": "equals", "condition": "SKIRT"},
            {"column": "title", "relation": "contains", "condition": "Skirt"},
            {"column": "title", "relation": "contains", "condition": "Skort"},
            {"column": "tag", "relation": "equals", "condition": "Skirts"},
            {"column": "tag", "relation": "equals", "condition": "Skort"}
        ]
    },
    "womens-cardigans": {
        "disjunctive": True,
        "rules": [
            {"column": "title", "relation": "contains", "condition": "Cardigan"},
            {"column": "type", "relation": "equals", "condition": "Cardigans"},
            {"column": "tag", "relation": "equals", "condition": "Cardigans"}
        ]
    },
    "womens-sweaters": {
        "disjunctive": True,
        "rules": [
            {"column": "title", "relation": "contains", "condition": "Sweater"},
            {"column": "type", "relation": "equals", "condition": "Sweaters"},
            {"column": "tag", "relation": "equals", "condition": "Sweaters"}
        ]
    },
    "womens-cocktail-dresses": {
        "disjunctive": True,
        "rules": [
            {"column": "title", "relation": "contains", "condition": "Cocktail"},
            {"column": "title", "relation": "contains", "condition": "Party Dress"},
            {"column": "tag", "relation": "equals", "condition": "Cocktail Dresses"},
            {"column": "tag", "relation": "equals", "condition": "Club & Night Out"}
        ]
    },
    "womens-pants-leggings": {
        "disjunctive": True,
        "rules": [
            {"column": "type", "relation": "equals", "condition": "Pants"},
            {"column": "type", "relation": "equals", "condition": "PANTS"},
            {"column": "type", "relation": "equals", "condition": "Leggings"},
            {"column": "title", "relation": "contains", "condition": "Pant"},
            {"column": "title", "relation": "contains", "condition": "Legging"},
            {"column": "title", "relation": "contains", "condition": "Jogger"},
            {"column": "tag", "relation": "equals", "condition": "Pants & Leggings"}
        ]
    }
}

def update_smart_collection_rules(collection_id, disjunctive, rules):
    url = f"{BASE_URL}/smart_collections/{collection_id}.json"
    payload = {
        "smart_collection": {
            "id": collection_id,
            "rules": rules,
            "disjunctive": disjunctive
        }
    }
    r = requests.put(url, headers=HEADERS, json=payload)
    if r.status_code == 429:
        wait = float(r.headers.get("Retry-After", 2.0))
        time.sleep(wait)
        r = requests.put(url, headers=HEADERS, json=payload)
    r.raise_for_status()
    return r.json()["smart_collection"]

def main():
    print("Fetching existing smart collections from Shopify...")
    url = f"{BASE_URL}/smart_collections.json?limit=250"
    r = requests.get(url, headers=HEADERS)
    r.raise_for_status()
    smart_collections = r.json().get("smart_collections", [])
    
    smart_map = {c["handle"]: c for c in smart_collections}

    updated_count = 0
    for handle, config in OPTIMIZED_RULES.items():
        if handle in smart_map:
            c = smart_map[handle]
            print(f"Updating rules for: {c['title']} ({handle})...")
            try:
                update_smart_collection_rules(c["id"], config["disjunctive"], config["rules"])
                print(f"  [OK] Updated rules successfully.")
                updated_count += 1
            except Exception as e:
                print(f"  [ERROR] Failed to update: {e}")
        else:
            print(f"[Warning] Collection {handle} not found in store.")

    print(f"\nRule optimization complete! Updated {updated_count} collections.")

if __name__ == "__main__":
    main()

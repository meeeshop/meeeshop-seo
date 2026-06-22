import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
from shopify_graphql import fetch_products_graphql

def main():
    products = fetch_products_graphql(hours=0)
    
    # We will simulate the clean brand rules
    brand_rules = {
        "pol": {
            "title_contains": ["pol "], # Match "Pol " or "POL" (but avoid matching words like "polka" or "polo"!)
            "vendor_equals": ["POL", "POL Clothing"]
        },
        "bibi": {
            "title_contains": ["bibi"],
            "vendor_equals": ["BiBi", "BIBI"]
        },
        "risen": {
            "title_contains": ["risen"],
            "vendor_equals": ["Risen", "RISEN JEANS"]
        },
        "umgee": {
            "title_contains": ["umgee"],
            "vendor_equals": ["Umgee USA", "Umgee"]
        },
        "zenana": {
            "title_contains": ["zenana"],
            "vendor_equals": ["Zenana", "ZENANA"]
        }
    }
    
    for brand, rules in brand_rules.items():
        matched = []
        for p in products:
            title_lower = p["title"].lower()
            vendor_lower = p["vendor"].lower()
            
            # Check title contains
            matches_title = False
            for tc in rules["title_contains"]:
                # To match "pol" cleanly and avoid "polka" or "polo", we can check word boundaries
                if tc == "pol ":
                    # Check if 'pol' is a word
                    words = title_lower.replace("-", " ").replace("_", " ").split()
                    if "pol" in words:
                        matches_title = True
                        break
                elif tc in title_lower:
                    matches_title = True
                    break
            
            # Check vendor equals
            matches_vendor = False
            for ve in rules["vendor_equals"]:
                if ve.lower() == vendor_lower:
                    matches_vendor = True
                    break
                    
            if matches_title or matches_vendor:
                matched.append(p)
                
        print(f"Brand '{brand.upper()}': Matches: {len(matched)}")
        for p in matched[:3]:
            print(f"  - Title: '{p['title']}' | Vendor: '{p['vendor']}'")

if __name__ == "__main__":
    main()

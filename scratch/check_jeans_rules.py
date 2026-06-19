import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
from shopify_graphql import fetch_products_graphql

def main():
    products = fetch_products_graphql(hours=0)
    
    # Let's test a few rule filters
    # Rule Set A: type in ['Jeans', 'DENIM JEANS', 'DENIM (NEW)'] OR tag == 'Jeans' OR title contains 'Jean' (but wait, what about title contains 'Jean' matching 'Jean Jacket'?)
    
    matched_a = []
    excluded_by_non_pants = []
    
    non_pants_indicators = ["dress", "skirt", "jacket", "vest", "shirt", "skort", "shorts", "romper", "jumpsuit"]
    
    for p in products:
        title_lower = p["title"].lower()
        type_lower = p["product_type"].lower()
        
        # Simulating disjunctive rules:
        matches_rules = (
            type_lower == "jeans" or
            type_lower == "denim jeans" or
            type_lower == "denim (new)" or
            "jeans" in title_lower or
            "jean" in title_lower or  # Note: "jean" is in "jeans"
            "denim" in title_lower
        )
        
        if matches_rules:
            # Check if it's a non-pant denim product
            is_non_pant = any(ind in title_lower for ind in non_pants_indicators) or any(ind in type_lower for ind in ["dress", "skirt", "jacket", "vest", "shirt", "skort", "shorts", "romper", "jumpsuit"])
            if is_non_pant:
                excluded_by_non_pants.append(p)
            else:
                matched_a.append(p)
                
    print(f"Total products matching current rules: {len(matched_a) + len(excluded_by_non_pants)}")
    print(f"Non-pants/jeans products matching current rules (should be excluded): {len(excluded_by_non_pants)}")
    for p in excluded_by_non_pants[:20]:
        print(f"  EXCLUDE: {p['title']} | Type: {p['product_type']}")
        
    # Let's check if we restrict to only:
    # 1. type == Jeans
    # 2. type == DENIM JEANS
    # 3. type == DENIM (NEW)
    # 4. tag == Jeans (if we can find tag)
    # 5. title contains "Jeans" (instead of "Jean" or "Denim")
    # Let's see if this matches all genuine jeans.
    matched_b = []
    missed_jeans = []
    for p in products:
        title_lower = p["title"].lower()
        type_lower = p["product_type"].lower()
        
        matches_strict = (
            type_lower == "jeans" or
            type_lower == "denim jeans" or
            type_lower == "denim (new)" or
            "jeans" in title_lower
        )
        
        if matches_strict:
            matched_b.append(p)
        elif "jean" in title_lower or "denim" in title_lower:
            # Let's see if it's a real jean that we missed
            is_non_pant = any(ind in title_lower for ind in non_pants_indicators) or any(ind in type_lower for ind in ["dress", "skirt", "jacket", "vest", "shirt", "skort", "shorts", "romper", "jumpsuit"])
            if not is_non_pant:
                missed_jeans.append(p)
                
    print(f"\nStrict rules (type: Jeans/DENIM JEANS/DENIM (NEW) or title contains 'Jeans'): {len(matched_b)} products.")
    print(f"Missed genuine jeans: {len(missed_jeans)}")
    for p in missed_jeans[:20]:
        print(f"  MISSED: {p['title']} | Type: {p['product_type']}")

if __name__ == "__main__":
    main()

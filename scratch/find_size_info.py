import sys
import os
import re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.shopify_graphql import run_graphql

def main():
    query = """
    query GetBags($cursor: String) {
      products(first: 50, query: "product_type:Handbags", after: $cursor) {
        edges {
          node {
            id
            title
            handle
            descriptionHtml
          }
        }
        pageInfo {
          hasNextPage
          endCursor
        }
      }
    }
    """
    
    has_next = True
    cursor = None
    total_bags = 0
    with_table = 0
    with_dimensions = 0
    
    print("Scanning Handbag products...")
    
    while has_next:
        res = run_graphql(query, {"cursor": cursor})
        data = res.get("data", {}).get("products", {})
        edges = data.get("edges", [])
        
        for edge in edges:
            node = edge["node"]
            total_bags += 1
            desc = node.get("descriptionHtml") or ""
            
            # Check for clothing table
            has_apparel_table = "bust" in desc.lower() or "waist" in desc.lower() or "hip" in desc.lower()
            if has_apparel_table:
                with_table += 1
                
            # Check for actual bag dimensions or measurements in description
            # e.g., "9.5 in", "9.5\"", "9.5 W", "height", "width", "measurements"
            dim_patterns = [
                r'\b\d+(?:\.\d+)?\s*(?:in|inch|inches|cm|mm)\b',
                r'\b\d+(?:\.\d+)?\s*["”]\b',
                r'\b(?:measurements|dimensions|height|width|length|depth|size)\b'
            ]
            
            # Exclude the words inside the clothing table when checking for dimensions
            # Strip out the table block first
            desc_no_table = re.sub(r'<table[\s\S]*?</table>', '', desc)
            desc_no_table = re.sub(r'<h[1-6][^>]*>[^<]*size[^<]*</h[1-6]>', '', desc_no_table, flags=re.IGNORECASE)
            
            has_dims = False
            matched_text = []
            for pat in dim_patterns:
                matches = re.findall(pat, desc_no_table, re.IGNORECASE)
                if matches:
                    has_dims = True
                    matched_text.extend(matches[:3]) # Show a few matches
                    
            if has_dims:
                with_dimensions += 1
                if with_dimensions <= 5:
                    print(f"\nProduct: {node['title']} (Handle: {node['handle']})")
                    print(f" - Matches: {matched_text}")
                    # Print lines from description that contain dimensions
                    text_lines = re.split(r'<[^>]+>', desc_no_table)
                    for line in text_lines:
                        if any(term in line.lower() for term in ["in", "\"", "height", "width", "length", "measure"]):
                            line_strip = line.strip()
                            if line_strip:
                                print(f"   * {line_strip}")
            
        page_info = data.get("pageInfo", {})
        has_next = page_info.get("hasNextPage", False)
        cursor = page_info.get("endCursor")
        
    print(f"\nScan Summary:")
    print(f"Total Handbag products found: {total_bags}")
    print(f"Products with apparel size table: {with_table}")
    print(f"Products containing actual dimension text: {with_dimensions}")

if __name__ == "__main__":
    main()

import sys
import os
import re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.shopify_graphql import run_graphql

def remove_clothing_size_table(html):
    """Remove any clothing size table (containing bust, waist, hip, etc.) and its heading."""
    if not html:
        return ""
    
    # 1. Match clothing-specific terms inside tables
    clothing_terms = re.compile(r'\b(bust|waist|hip|sleeve|inseam|rise|underwire|chest)\b', re.IGNORECASE)
    
    def replacement(match):
        table_html = match.group(0)
        if clothing_terms.search(table_html):
            return ""
        return table_html
        
    cleaned = re.sub(r'<table[\s\S]*?</table>', replacement, html)
    
    # 2. Clean up orphaned headings like <h3>Size Chart</h3> immediately followed by another heading/tag or end of string
    cleaned = re.sub(
        r'(<h[1-6][^>]*>[^<]*size[^<]*</h[1-6]>\s*|<p[^>]*>\s*<strong>\s*size[^<]*chart[^<]*</strong>\s*</p>\s*)'
        r'(?=<h|<p|<ul>|<li>|<div>|<!--|$)',
        '', cleaned, flags=re.IGNORECASE
    )
    return cleaned.strip()

def update_product_description(p_id, description_html):
    mutation = """
    mutation productUpdate($input: ProductInput!) {
      productUpdate(input: $input) {
        product {
          id
          title
        }
        userErrors {
          field
          message
        }
      }
    }
    """
    res = run_graphql(mutation, {
        "input": {
            "id": p_id,
            "descriptionHtml": description_html
        }
    })
    errors = res.get("data", {}).get("productUpdate", {}).get("userErrors", [])
    if errors:
        print(f"  ❌ Errors updating {p_id}: {errors}")
        return False
    return True

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
    total_processed = 0
    total_updated = 0
    
    print("Fetching Handbag products and auditing size charts...")
    
    while has_next:
        res = run_graphql(query, {"cursor": cursor})
        data = res.get("data", {}).get("products", {})
        edges = data.get("edges", [])
        
        for edge in edges:
            node = edge["node"]
            p_id = node["id"]
            title = node["title"]
            desc = node.get("descriptionHtml") or ""
            total_processed += 1
            
            # Check if description contains clothing size table keywords
            if "bust" in desc.lower() or "waist" in desc.lower() or "hip" in desc.lower():
                cleaned_desc = remove_clothing_size_table(desc)
                if cleaned_desc != desc:
                    print(f"Purging apparel size chart from: {title} (Handle: {node['handle']})")
                    success = update_product_description(p_id, cleaned_desc)
                    if success:
                        total_updated += 1
            
        page_info = data.get("pageInfo", {})
        has_next = page_info.get("hasNextPage", False)
        cursor = page_info.get("endCursor")
        
    print(f"\nAudit completed:")
    print(f" - Handbags processed: {total_processed}")
    print(f" - Size charts purged: {total_updated}")

if __name__ == "__main__":
    main()

import sys, os, re, json, argparse
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)
sys.path.insert(0, ROOT_DIR)

from secrets_manager import inject_to_env
inject_to_env()
from shopify_graphql import run_graphql, parse_gid
from seo_daily import detect_cat, remove_clothing_size_table, api_put, APPAREL_CATEGORIES

def clean_all_non_clothing_size_charts(dry_run=True):
    print("=== MeeeShop One-Time Non-Clothing Size Chart Cleanup ===")
    print(f"Mode: {'DRY-RUN (preview only)' if dry_run else 'LIVE UPDATE ON SHOPIFY'}\n")
    
    # Query all candidate non-clothing products efficiently via GraphQL
    query_str = (
        "product_type:Bag OR product_type:Handbag OR product_type:Backpack OR product_type:Tote OR "
        "product_type:Accessories OR product_type:Jewelry OR product_type:Shoes OR product_type:Hat OR "
        "tag:bag OR tag:backpack OR tag:accessory OR tag:jewelry OR tag:shoes OR "
        "title:bag OR title:backpack OR title:tote OR title:handbag OR title:purse OR title:clutch OR "
        "title:wallet OR title:hat OR title:beanie OR title:earring OR title:necklace OR title:bracelet OR "
        "title:belt OR title:sunglasses OR title:scarf OR title:shoe OR title:boot OR title:sandal"
    )
    
    gql = """
    query ($first: Int!, $after: String, $queryStr: String) {
      products(first: $first, after: $after, query: $queryStr) {
        pageInfo { hasNextPage endCursor }
        edges {
          node {
            id
            title
            handle
            productType
            bodyHtml
          }
        }
      }
    }
    """
    
    candidates = []
    has_next = True
    cursor = None
    
    print("Querying candidate non-clothing products...")
    while has_next:
        res = run_graphql(gql, {"first": 250, "after": cursor, "queryStr": query_str})
        data = res.get("data", {}).get("products", {})
        for edge in data.get("edges", []):
            node = edge["node"]
            candidates.append({
                "id": parse_gid(node["id"]),
                "gid": node["id"],
                "title": node["title"],
                "handle": node["handle"],
                "product_type": node["productType"],
                "body_html": node["bodyHtml"] or ""
            })
        page_info = data.get("pageInfo", {})
        has_next = page_info.get("hasNextPage", False)
        cursor = page_info.get("endCursor")
        
    print(f"Candidate non-clothing products found: {len(candidates)}\n")
    
    clothing_table_re = re.compile(r'<table[\s\S]*?\b(bust|waist|hip|inseam|underwire|chest)\b[\s\S]*?</table>', re.IGNORECASE)
    cleaned_count = 0
    
    for item in candidates:
        pid = item["id"]
        title = item["title"]
        body_html = item["body_html"]
        cat, word = detect_cat(title, item["product_type"])
        
        # Verify it is non-apparel
        if cat not in APPAREL_CATEGORIES:
            if clothing_table_re.search(body_html):
                print(f"[{cleaned_count+1}] FOUND INVALID SIZE TABLE in [{cat}] '{title}' (ID: {pid})")
                cleaned_body = remove_clothing_size_table(body_html)
                
                # Cleanup leftover empty headings
                cleaned_body = re.sub(
                    r'(<h[1-6][^>]*>[^<]*size[^<]*</h[1-6]>\s*|<p[^>]*>\s*<strong>\s*size[^<]*chart[^<]*</strong>\s*</p>\s*)'
                    r'(?=<h|<p|<ul>|<li>|<div>|<!--|$)',
                    '', cleaned_body, flags=re.IGNORECASE
                ).strip()
                
                print(f"  - Original HTML Length : {len(body_html)}")
                print(f"  - Cleaned HTML Length  : {len(cleaned_body)}")
                
                if dry_run:
                    print(f"  [DRY-RUN] Would update product {pid} body_html")
                else:
                    try:
                        api_put(f"/products/{pid}.json", {"product": {"id": pid, "body_html": cleaned_body}})
                        print(f"  [LIVE OK] Updated product {pid} body_html on Shopify")
                    except Exception as e:
                        print(f"  [ERROR] Failed updating product {pid}: {e}")
                        
                cleaned_count += 1
                print("-" * 60)

    print(f"\n============================================================")
    print(f"Cleanup Completed: {cleaned_count} non-clothing product(s) cleaned.")
    print(f"============================================================")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="One-time cleanup of clothing size tables from non-clothing products.")
    parser.add_argument("--live", action="store_true", help="Perform live updates on Shopify store.")
    args = parser.parse_args()
    
    clean_all_non_clothing_size_charts(dry_run=not args.live)

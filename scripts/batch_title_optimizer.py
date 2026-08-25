import sys, os, requests, json, re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from secrets_manager import get_secret

store = get_secret('SHOPIFY_STORE')
token = get_secret('SHOPIFY_ACCESS_TOKEN')
headers = {'X-Shopify-Access-Token': token, 'Content-Type': 'application/json'}

def clean_title(title, vendor, ptype):
    original = title.strip()
    v_clean = (vendor or '').strip()
    if v_clean.upper() == 'YMI JEANS':
        v_clean = 'YMI'
    elif v_clean.upper() == 'ORANGE FARM CLOTHING':
        v_clean = 'Orange Farm'
    elif v_clean.upper() in ('CCWHOLESALECLOTHING', 'CC WHOLESALE CLOTHING', 'WHOLESALE', 'ATHINA RETAIL', 'ATHINA'):
        if 'HYFVE' in original.upper():
            v_clean = 'Hyfve'
        else:
            v_clean = ''
    elif v_clean.upper() == 'MKF DROPSHIP':
        v_clean = 'MKF Collection'
    elif v_clean.upper() in ('UNKNOWN', 'OTHER', 'D&J', 'TRENDSI'):
        v_clean = ''
    
    cleaned = re.sub(r'^\*+|\*+$', '', original).strip()
    cleaned = re.sub(r'\[.*?\]', '', cleaned).strip()
    cleaned = re.sub(r'\b(Hj\d{3}|HJ\d{3})\b', '', cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r'\bCCWHOLESALECLOTHING\b[\s\-\:\—]*', '', cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r'\bATHINA\s+RETAIL\b[\s\-\:\—]*', '', cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r'\bATHINA\b[\s\-\:\—]*', '', cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    
    if v_clean and v_clean.lower() not in ('unknown', 'other', ''):
        has_brand = False
        for v_part in [v_clean, v_clean.split()[0]]:
            if cleaned.lower().startswith(v_part.lower()):
                has_brand = True
                break
        if 'judy blue' in cleaned.lower() or 'risen' in cleaned.lower() or 'artemis' in cleaned.lower():
            has_brand = True
            
        if not has_brand:
            cleaned = f"{v_clean} {cleaned}"
            
    ptype_lower = (ptype or '').lower()
    c_lower = cleaned.lower()
    if ('jean' in ptype_lower or 'denim' in ptype_lower) and 'jean' not in c_lower and 'short' not in c_lower and 'pant' not in c_lower and 'jacket' not in c_lower and 'vest' not in c_lower:
        cleaned += " Jeans"
    elif 'dress' in ptype_lower and 'dress' not in c_lower and 'set' not in c_lower:
        cleaned += " Dress"
    elif ('top' in ptype_lower or 'shirt' in ptype_lower) and 'top' not in c_lower and 'shirt' not in c_lower and 'blouse' not in c_lower and 'sweater' not in c_lower and 'tee' not in c_lower and 'tank' not in c_lower:
        cleaned += " Top"
    elif ('tote' in ptype_lower or 'bag' in ptype_lower or 'handbag' in ptype_lower) and 'bag' not in c_lower and 'tote' not in c_lower and 'handbag' not in c_lower:
        cleaned += " Handbag"

    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned

def run_batch_optimization():
    target_vendors = ['YMI JEANS', 'Trendsi', 'Artemis Vintage', 'MKF Dropship', 'Orange Farm Clothing', 'Hey Joanie', 'CCWHOLESALECLOTHING', 'Madeline Love', 'Indie & Co.']

    query_products = """
    query($cursor: String) {
      products(first: 250, after: $cursor, query: "status:active") {
        pageInfo {
          hasNextPage
          endCursor
        }
        edges {
          node {
            id
            title
            vendor
            productType
          }
        }
      }
    }
    """

    has_next = True
    cursor = None
    products_to_optimize = []

    print("Fetching active catalog products for optimization...")
    while has_next:
        vars_dict = {"cursor": cursor} if cursor else {}
        r_prods = requests.post(f"https://{store}/admin/api/2024-10/graphql.json", headers=headers, json={"query": query_products, "variables": vars_dict})
        if r_prods.status_code != 200:
            break
        pdata = r_prods.json().get('data', {}).get('products', {})
        for e in pdata.get('edges', []):
            node = e['node']
            v = node.get('vendor', '')
            if v in target_vendors or any(tv.lower() in v.lower() for tv in target_vendors):
                products_to_optimize.append(node)
                
        page_info = pdata.get('pageInfo', {})
        has_next = page_info.get('hasNextPage', False)
        cursor = page_info.get('endCursor')

    print(f"Total matching products to check: {len(products_to_optimize)}")

    mutation_update = """
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

    updated_count = 0
    for idx, p in enumerate(products_to_optimize, 1):
        pid = p['id']
        old_title = p['title']
        vendor = p.get('vendor', '')
        ptype = p.get('productType', '')
        
        new_title = clean_title(old_title, vendor, ptype)
        if new_title != old_title:
            payload = {"query": mutation_update, "variables": {"input": {"id": pid, "title": new_title}}}
            r_up = requests.post(f"https://{store}/admin/api/2024-10/graphql.json", headers=headers, json=payload)
            if r_up.status_code == 200 and not r_up.json().get('data', {}).get('productUpdate', {}).get('userErrors'):
                updated_count += 1
                if updated_count <= 10 or updated_count % 50 == 0:
                    print(f"[{updated_count}] '{old_title}' -> '{new_title}'")

    print(f"\n=== FINISHED: Optimized {updated_count} product titles! ===")

if __name__ == '__main__':
    run_batch_optimization()

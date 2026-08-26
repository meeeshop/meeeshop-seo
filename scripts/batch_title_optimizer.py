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
    blocked_suppliers = (
        'CCWHOLESALECLOTHING', 'CC WHOLESALE CLOTHING', 'CC WHOLESALE', 'WHOLESALE',
        'ATHINA RETAIL', 'ATHINA', 'BOHO CLOTHING AND ACCESSORIES', 'BOHO CLOTHING',
        'AILI\'S CORNER', 'AILIS CORNER', 'SUPREME FASHION', 'COTTONWAYS',
        'SHOPBASICBAE', 'BASIC BAE', 'HELLODAY.US', 'HELLO DAY', 'ELLISONYOUNG.COM', 'ELLISONYOUNG',
        'LUCKY FEET SHOES', 'SPUN BAMBOO', 'TRENDSI', 'D&J', 'UNKNOWN', 'OTHER', 'DEFAULT', '',
        'MKF DROPSHIP', 'GLEE + CO', 'GLEE AND CO', 'ORANGE FARM CLOTHING', 'ORANGE FARM',
        'GRACE+EMMA', 'GRACE AND EMMA', 'GRACE & EMMA', 'ARTEMIS VINTAGE', 'ARTEMIS',
        'INDIE & CO.', 'INDIE AND CO.', 'INDIE & CO', 'INDIE AND CO', 'HEY JOANIE',
        'PRETTY SIMPLE', 'MADELINE LOVE', 'MISSFINCHNYC', 'MISS FINCH NYC', 'SNOSKINS',
        'ALYTH ACTIVE', 'DIZZY-LIZZIE', 'DIZZY LIZZIE', 'TROPHY YOGA', 'VAILA SHOES', 'VAILA',
        'BOTORI EQUESTRIAN', 'BOTORI', 'VALENTINE', 'TYCHE', 'DIOSA', 'CEFIAN', 'SOVELLA'
    )
    if v_clean.upper() in blocked_suppliers:
        v_clean = ''
    elif v_clean.upper() == 'MKF DROPSHIP':
        v_clean = 'MKF Collection'
    
    cleaned = re.sub(r'^\*+|\*+$', '', original).strip()
    cleaned = re.sub(r'\[.*?\]', '', cleaned).strip()
    cleaned = re.sub(r'\b(Hj\d{3}|HJ\d{3})\b', '', cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r'\b(?:Clearance|New|Sale)\s+', '', cleaned, flags=re.IGNORECASE).strip()
    
    wholesale_patterns = [
        r'\bBoho Clothing and Accessories\b[\s\-\:\—]*',
        r'\bBoho Clothing\b[\s\-\:\—]*',
        r'\bAili\'s Corner\b[\s\-\:\—]*',
        r'\bAilis Corner\b[\s\-\:\—]*',
        r'\bSUPREME FASHION\b[\s\-\:\—]*',
        r'\bSupreme Fashion\b[\s\-\:\—]*',
        r'\bCottonways\b[\s\-\:\—]*',
        r'\bShopbasicbae\b[\s\-\:\—]*',
        r'\bBasic Bae\b[\s\-\:\—]*',
        r'\bHelloday\.us\b[\s\-\:\—]*',
        r'\bHello Day\b[\s\-\:\—]*',
        r'\bEllisonyoung\.com\b[\s\-\:\—]*',
        r'\bEllisonyoung\b[\s\-\:\—]*',
        r'\bLucky Feet Shoes\b[\s\-\:\—]*',
        r'\bSpun Bamboo\b[\s\-\:\—]*',
        r'\bCCWHOLESALECLOTHING\b[\s\-\:\—]*',
        r'\bCC\s+WHOLESALE\s+CLOTHING\b[\s\-\:\—]*',
        r'\bCC\s+WHOLESALE\b[\s\-\:\—]*',
        r'\bATHINA\s+RETAIL\b[\s\-\:\—]*',
        r'\bATHINA\b[\s\-\:\—]*',
        r'\bTrendsi\b[\s\-\:\—]*',
        r'\bMKF\s+Dropship\b[\s\-\:\—]*',
        r'\bglee\s*\+\s*co\b[\s\-\:\—]*',
        r'\bGlee\s+and\s+Co\b[\s\-\:\—]*',
        r'\bOrange\s+Farm\s+Clothing\b[\s\-\:\—]*',
        r'\bOrange\s+Farm\b[\s\-\:\—]*',
        r'\bGrace\s*\+\s*Emma\b[\s\-\:\—]*',
        r'\bGrace\s+and\s+Emma\b[\s\-\:\—]*',
        r'\bArtemis\s+Vintage\b[\s\-\:\—]*',
        r'\bArtemis\b[\s\-\:\—]*',
        r'\bIndie\s*&\s*Co\.?\b[\s\-\:\—]*',
        r'\bIndie\s+and\s+Co\.?\b[\s\-\:\—]*',
        r'\bHey\s+Joanie\b[\s\-\:\—]*',
        r'\bPretty\s+Simple\b[\s\-\:\—]*',
        r'\bMadeline\s+Love\b[\s\-\:\—]*',
        r'\bMissFinchNYC\b[\s\-\:\—]*',
        r'\bMiss\s+Finch\s+NYC\b[\s\-\:\—]*',
        r'\bSnoSkins\b[\s\-\:\—]*',
        r'\bAlyth\s+Active\b[\s\-\:\—]*',
        r'\bDizzy\-Lizzie\b[\s\-\:\—]*',
        r'\bDizzy\s+Lizzie\b[\s\-\:\—]*',
        r'\bTrophy\s+Yoga\b[\s\-\:\—]*',
        r'\bVaila\s+Shoes\b[\s\-\:\—]*',
        r'\bVaila\b[\s\-\:\—]*',
        r'\bBOTORI\s+Equestrian\b[\s\-\:\—]*',
        r'\bBOTORI\b[\s\-\:\—]*',
        r'\bVALENTINE\b[\s\-\:\—]*',
        r'\bTYCHE\b[\s\-\:\—]*',
        r'\bDIOSA\b[\s\-\:\—]*',
        r'\bCEFIAN\b[\s\-\:\—]*',
        r'\bSovella\b[\s\-\:\—]*'
    ]
    for pat in wholesale_patterns:
        cleaned = re.sub(pat, '', cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r'[\s\-–—:]+$', '', cleaned).strip()
    cleaned = re.sub(r'^[\s\-–—:]+', '', cleaned).strip()
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    
    recognized_brands_to_prefix = {
        'JUDY BLUE', 'YMI', 'RISEN', 'EMORY PARK', 'FLYING TOMATO',
        'RETROLICIOUS', 'DOWNEAST', 'HYFVE', 'BUKI', 'GOAL FIVE',
        'ELASTIQUE ATHLETICS', 'MKF COLLECTION'
    }
    if v_clean and v_clean.upper() in recognized_brands_to_prefix:
        has_brand = False
        for v_part in [v_clean, v_clean.split()[0]]:
            if cleaned.lower().startswith(v_part.lower()):
                has_brand = True
                break
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

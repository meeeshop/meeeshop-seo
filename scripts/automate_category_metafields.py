import requests
import json
import re
import os
import sys
import time

# Ensure output encoding is UTF-8 for Windows console
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

# Add current directory to path to load secrets and ai_client
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from secrets_manager import inject_to_env, get_secret
from ai_client import generate

# Load environment variables
inject_to_env()
STORE_URL = get_secret("SHOPIFY_STORE_URL")
ACCESS_TOKEN = get_secret("SHOPIFY_ACCESS_TOKEN")

headers = {
    "X-Shopify-Access-Token": ACCESS_TOKEN,
    "Content-Type": "application/json"
}

_session = requests.Session()
_session.headers.update(headers)

# Cache for standard taxonomy metaobjects: key is (type, display_name.lower()) -> GID
taxonomy_cache = {}

# Active metafield definitions in the `shopify` namespace on the store: key is key_name -> definition type
shopify_definitions = {}

# Cache for standard taxonomy values from Shopify: key is (type, display_name.lower()) -> TaxonomyValue GID
standard_values_cache = {}

# Categories for which standard values have been loaded
loaded_categories = set()

TAXONOMY_MAP = {
    "color": {
        "key": "color-pattern",
        "type": "shopify--color-pattern"
    },
    "fabric": {
        "key": "fabric",
        "type": "shopify--fabric"
    },
    "bag_case_material": {
        "key": "bag-case-material",
        "type": "shopify--bag-case-material"
    },
    "carry_options": {
        "key": "carry-options",
        "type": "shopify--carry-options"
    },
    "accessory_size": {
        "key": "accessory-size",
        "type": "shopify--accessory-size"
    },
    "bag_case_closure": {
        "key": "bag-case-closure",
        "type": "shopify--bag-case-closure"
    },
    "bag_case_features": {
        "key": "bag-case-features",
        "type": "shopify--bag-case-features"
    },
    "bag_case_storage_features": {
        "key": "bag-case-storage-features",
        "type": "shopify--bag-case-storage-features"
    },
    "target_gender": {
        "key": "target-gender",
        "type": "shopify--target-gender"
    },
    "age_group": {
        "key": "age-group",
        "type": "shopify--age-group"
    },
    "sleeve_length_type": {
        "key": "sleeve-length-type",
        "type": "shopify--sleeve-length-type"
    },
    "dress_style": {
        "key": "dress-style",
        "type": "shopify--dress-style"
    },
    "neckline": {
        "key": "neckline",
        "type": "shopify--neckline"
    },
    "skirt_length_type": {
        "key": "skirt-dress-length-type",
        "type": "shopify--skirt-dress-length-type"
    },
    "care_instructions": {
        "key": "care-instructions",
        "type": "shopify--care-instructions"
    },
    "clothing_features": {
        "key": "clothing-features",
        "type": "shopify--clothing-features"
    },
    "dress_occasion": {
        "key": "dress-occasion",
        "type": "shopify--dress-occasion"
    }
}

def init_taxonomy_cache():
    """Load and cache standard shopify definitions and their metaobjects from the store."""
    print("Initializing Shopify Standard Taxonomy definitions and cache...")
    
    # 1. Fetch active shopify namespace definitions
    def_query = """
    query {
      metafieldDefinitions(first: 250, ownerType: PRODUCT) {
        edges {
          node {
            key
            namespace
            type {
              name
            }
          }
        }
      }
    }
    """
    try:
        res = run_graphql(def_query)
        edges = res.get("data", {}).get("metafieldDefinitions", {}).get("edges", [])
        for edge in edges:
            node = edge["node"]
            if node["namespace"] == "shopify":
                shopify_definitions[node["key"]] = node["type"]["name"]
        print(f"  Loaded {len(shopify_definitions)} active 'shopify' namespace metafield definitions.")
    except Exception as e:
        print(f"  Warning: Failed to load metafield definitions: {e}")

    # 2. Fetch all metaobjects for target taxonomy types
    TAXONOMY_TYPES = [
        "shopify--color-pattern",
        "shopify--fabric",
        "shopify--bag-case-material",
        "shopify--carry-options",
        "shopify--accessory-size",
        "shopify--bag-case-closure",
        "shopify--bag-case-features",
        "shopify--bag-case-storage-features",
        "shopify--target-gender",
        "shopify--age-group",
        "shopify--sleeve-length-type",
        "shopify--one-piece-style",
        "shopify--dress-style",
        "shopify--neckline",
        "shopify--skirt-dress-length-type",
        "shopify--care-instructions",
        "shopify--clothing-features",
        "shopify--dress-occasion"
    ]
    mo_query = """
    query GetMetaobjects($type: String!, $cursor: String) {
      metaobjects(type: $type, first: 250, after: $cursor) {
        edges {
          node {
            id
            displayName
          }
        }
        pageInfo {
          hasNextPage
          endCursor
        }
      }
    }
    """
    for t in TAXONOMY_TYPES:
        has_next = True
        cursor = None
        count = 0
        while has_next:
            try:
                res = run_graphql(mo_query, {"type": t, "cursor": cursor})
                data = res.get("data", {}).get("metaobjects", {})
                for edge in data.get("edges", []):
                    node = edge["node"]
                    name = node["displayName"].lower().strip()
                    taxonomy_cache[(t, name)] = node["id"]
                    count += 1
                page_info = data.get("pageInfo", {})
                has_next = page_info.get("hasNextPage", False)
                cursor = page_info.get("endCursor")
            except Exception as e:
                print(f"  Warning: Failed to fetch metaobjects for type '{t}': {e}")
                has_next = False
        if count > 0:
            print(f"  Cached {count} standard values for '{t}'.")

def load_standard_category_values(category_id):
    """Fetch all standard attributes and their allowed taxonomy value GIDs for a category."""
    query = """
    query GetCategory($id: ID!) {
      node(id: $id) {
        ... on TaxonomyCategory {
          attributes(first: 50) {
            edges {
              node {
                __typename
                ... on TaxonomyChoiceListAttribute {
                  name
                  values(first: 250) {
                    edges {
                      node {
                        id
                        name
                      }
                    }
                  }
                }
              }
            }
          }
        }
      }
    }
    """
    try:
        res = run_graphql(query, {"id": category_id})
        edges = res.get("data", {}).get("node", {}).get("attributes", {}).get("edges", [])
        cat_values = {}
        for edge in edges:
            node = edge["node"]
            attr_name = node["name"]
            attr_name_norm = attr_name.lower().replace("/", " ").replace("-", " ").strip()
            
            # Find which key in TAXONOMY_MAP matches this attribute name (case-insensitive)
            map_key = None
            for k, m in TAXONOMY_MAP.items():
                map_key_norm = m["key"].lower().replace("-", " ").strip()
                k_norm = k.lower().replace("_", " ").strip()
                if map_key_norm == attr_name_norm or k_norm == attr_name_norm:
                    map_key = k
                    break
            
            if not map_key:
                # Direct match fallback
                for k, m in TAXONOMY_MAP.items():
                    type_clean = m["type"].lower().replace("shopify--", "").replace("-", " ").strip()
                    if attr_name_norm in type_clean or type_clean in attr_name_norm:
                        map_key = k
                        break
                        
            if map_key:
                mo_type = TAXONOMY_MAP[map_key]["type"]
                for val_edge in node.get("values", {}).get("edges", []):
                    val_node = val_edge["node"]
                    name_clean = val_node["name"].lower().strip()
                    cat_values[(mo_type, name_clean)] = val_node["id"]
        return cat_values
    except Exception as e:
        print(f"  Warning: Failed to load standard category values for {category_id}: {e}")
        return {}

def create_store_metaobject(mo_type, label, taxonomy_value_gid):
    """Create a standard taxonomy metaobject in the store."""
    mutation = """
    mutation metaobjectCreate($metaobject: MetaobjectCreateInput!) {
      metaobjectCreate(metaobject: $metaobject) {
        metaobject {
          id
        }
        userErrors {
          field
          message
        }
      }
    }
    """
    try:
        res = run_graphql(mutation, {
            "metaobject": {
                "type": mo_type,
                "fields": [
                    {"key": "label", "value": label},
                    {"key": "taxonomy_reference", "value": taxonomy_value_gid}
                ]
            }
        })
        errors = res.get("data", {}).get("metaobjectCreate", {}).get("userErrors", [])
        if errors:
            print(f"  ❌ Failed to create metaobject for '{label}': {errors}")
            return None
        mo_id = res.get("data", {}).get("metaobjectCreate", {}).get("metaobject", {}).get("id")
        return mo_id
    except Exception as e:
        print(f"  ❌ Error creating metaobject for '{label}': {e}")
        return None

def resolve_metaobject_value(mo_type, val_cleaned):
    """Resolve clean value to store metaobject GID, creating it if necessary."""
    # 1. Check if it already exists in the store cache
    mo_gid = taxonomy_cache.get((mo_type, val_cleaned))
    if mo_gid:
        return mo_gid
        
    # Normalizations
    normalizations = {
        "grey": "gray",
        "gray": "grey",
        "adult": "adults",
        "round neck": "round",
        "mock neck": "mock"
    }
    norm_val = normalizations.get(val_cleaned)
    if norm_val:
        mo_gid = taxonomy_cache.get((mo_type, norm_val))
        if mo_gid:
            return mo_gid
            
    # 2. Check if we have the standard TaxonomyValue GID for it
    search_val = norm_val if norm_val else val_cleaned
    std_gid = standard_values_cache.get((mo_type, search_val))
    if not std_gid:
        # Try finding standard value with substring or case match
        for (t, n), gid in standard_values_cache.items():
            if t == mo_type and (search_val in n or n in search_val):
                std_gid = gid
                search_val = n
                break
                
    if std_gid:
        # Create the metaobject in the store
        # Find proper title-case label
        label = search_val.capitalize()
        # Exception labels
        if search_val == "v-neck": label = "V-neck"
        elif search_val == "round-neck": label = "Round-neck"
        
        print(f"  - Creating store metaobject for '{label}' of type '{mo_type}' (TaxonomyValue: {std_gid})...")
        new_mo_gid = create_store_metaobject(mo_type, label, std_gid)
        if new_mo_gid:
            # Cache it
            taxonomy_cache[(mo_type, search_val)] = new_mo_gid
            taxonomy_cache[(mo_type, val_cleaned)] = new_mo_gid
            print(f"  ✓ Created metaobject: {new_mo_gid}")
            return new_mo_gid
            
    return None

def make_request(method, url, json_data=None):
    """Dynamically rate-limited HTTP requests wrapper."""
    while True:
        try:
            resp = _session.request(method, url, json=json_data, timeout=30)
            if resp.status_code == 429:
                retry_after = float(resp.headers.get("Retry-After", 2.0))
                print(f"Rate limited (429). Sleeping for {retry_after}s...")
                time.sleep(retry_after)
                continue
            resp.raise_for_status()
            
            call_limit = resp.headers.get("X-Shopify-Shop-Api-Call-Limit")
            if call_limit:
                used, total = map(int, call_limit.split("/"))
                if used > 35:
                    time.sleep(1.0)
            return resp
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                time.sleep(2.0)
                continue
            raise

def run_graphql(query, variables=None):
    """Run GraphQL Admin API query."""
    url = f"{STORE_URL}/admin/api/2024-01/graphql.json"
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
    
    resp = make_request("POST", url, payload)
    result = resp.json()
    if "errors" in result:
        print("GraphQL Errors:", result["errors"])
    return result

def get_product_by_handle(handle):
    """Retrieve product, variants, and media by product handle."""
    query = """
    query GetProduct($handle: String!) {
      productByHandle(handle: $handle) {
        id
        title
        handle
        descriptionHtml
        productType
        category {
          id
          name
        }
        metafields(first: 20, keys: [
          "shopify.color-pattern", "shopify.fabric", "shopify.target-gender", "shopify.age-group",
          "shopify.sleeve-length-type", "shopify.one-piece-style", "shopify.dress-style", "shopify.neckline",
          "shopify.skirt-dress-length-type", "shopify.care-instructions", "shopify.clothing-features",
          "shopify.dress-occasion", "shopify.carry-options", "shopify.bag-case-material",
          "shopify.accessory-size", "shopify.bag-case-closure", "shopify.bag-case-features", "shopify.bag-case-storage-features"
        ]) {
          edges {
            node {
              id
              namespace
              key
              value
            }
          }
        }
        media(first: 50) {
          edges {
            node {
              id
              alt
              mediaContentType
              ... on MediaImage {
                image {
                  url
                }
              }
            }
          }
        }
        variants(first: 100) {
          edges {
            node {
              id
              title
              media(first: 1) {
                nodes {
                  id
                }
              }
              selectedOptions {
                name
                value
              }
            }
          }
        }
      }
    }
    """
    res = run_graphql(query, {"handle": handle})
    return res.get("data", {}).get("productByHandle")

def get_collection_products_by_handle(handle):
    """Retrieve all products inside a collection by collection handle."""
    query = """
    query GetCollectionProducts($handle: String!) {
      collectionByHandle(handle: $handle) {
        id
        title
        handle
        products(first: 50) {
          edges {
            node {
              id
              title
              handle
              descriptionHtml
              productType
              category {
                id
                name
              }
              metafields(first: 20, keys: [
                "shopify.color-pattern", "shopify.fabric", "shopify.target-gender", "shopify.age-group",
                "shopify.sleeve-length-type", "shopify.one-piece-style", "shopify.dress-style", "shopify.neckline",
                "shopify.skirt-dress-length-type", "shopify.care-instructions", "shopify.clothing-features",
                "shopify.dress-occasion", "shopify.carry-options", "shopify.bag-case-material",
                "shopify.accessory-size", "shopify.bag-case-closure", "shopify.bag-case-features", "shopify.bag-case-storage-features"
              ]) {
                edges {
                  node {
                    id
                    namespace
                    key
                    value
                  }
                }
              }
              media(first: 50) {
                edges {
                  node {
                    id
                    alt
                    mediaContentType
                    ... on MediaImage {
                      image {
                        url
                      }
                    }
                  }
                }
              }
              variants(first: 100) {
                edges {
                  node {
                    id
                    title
                    media(first: 1) {
                      nodes {
                        id
                      }
                    }
                    selectedOptions {
                      name
                      value
                    }
                  }
                }
              }
            }
          }
        }
      }
    }
    """
    res = run_graphql(query, {"handle": handle})
    col = res.get("data", {}).get("collectionByHandle")
    if not col:
        return None, []
    
    edges = col.get("products", {}).get("edges", [])
    prods = [e["node"] for e in edges]
    return col, prods


def get_recent_products(since_iso, query_field="created_at"):
    """Retrieve products since a specific timestamp using a specific date field."""
    query = """
    query GetRecentProducts($queryStr: String, $cursor: String) {
      products(first: 50, query: $queryStr, after: $cursor) {
        edges {
          node {
            id
            title
            handle
            descriptionHtml
            productType
            category {
              id
              name
            }
            metafields(first: 20, keys: [
              "shopify.color-pattern", "shopify.fabric", "shopify.target-gender", "shopify.age-group",
              "shopify.sleeve-length-type", "shopify.one-piece-style", "shopify.dress-style", "shopify.neckline",
              "shopify.skirt-dress-length-type", "shopify.care-instructions", "shopify.clothing-features",
              "shopify.dress-occasion", "shopify.carry-options", "shopify.bag-case-material",
              "shopify.accessory-size", "shopify.bag-case-closure", "shopify.bag-case-features", "shopify.bag-case-storage-features"
            ]) {
              edges {
                node {
                  id
                  namespace
                  key
                  value
                }
              }
            }
            media(first: 50) {
              edges {
                node {
                  id
                  alt
                  mediaContentType
                  ... on MediaImage {
                    image {
                      url
                    }
                  }
                }
              }
            }
            variants(first: 100) {
              edges {
                node {
                  id
                  title
                  media(first: 1) {
                    nodes {
                      id
                    }
                  }
                  selectedOptions {
                    name
                    value
                  }
                }
              }
            }
          }
        }
        pageInfo {
          hasNextPage
          endCursor
        }
      }
    }
    """
    products = []
    has_next = True
    cursor = None
    query_str = f"{query_field}:>='{since_iso}'"
    
    while has_next:
        res = run_graphql(query, {"queryStr": query_str, "cursor": cursor})
        data = res.get("data", {}).get("products", {})
        edges = data.get("edges", [])
        
        for edge in edges:
            products.append(edge["node"])
            
        page_info = data.get("pageInfo", {})
        has_next = page_info.get("hasNextPage", False)
        cursor = page_info.get("endCursor")
        
    return products

def get_all_products():
    """Retrieve all products in the store."""
    query = """
    query GetAllProducts($cursor: String) {
      products(first: 50, after: $cursor) {
        edges {
          node {
            id
            title
            handle
            descriptionHtml
            productType
            category {
              id
              name
            }
            metafields(first: 20, keys: [
              "shopify.color-pattern", "shopify.fabric", "shopify.target-gender", "shopify.age-group",
              "shopify.sleeve-length-type", "shopify.one-piece-style", "shopify.dress-style", "shopify.neckline",
              "shopify.skirt-dress-length-type", "shopify.care-instructions", "shopify.clothing-features",
              "shopify.dress-occasion", "shopify.carry-options", "shopify.bag-case-material",
              "shopify.accessory-size", "shopify.bag-case-closure", "shopify.bag-case-features", "shopify.bag-case-storage-features"
            ]) {
              edges {
                node {
                  id
                  namespace
                  key
                  value
                }
              }
            }
            media(first: 50) {
              edges {
                node {
                  id
                  alt
                  mediaContentType
                  ... on MediaImage {
                    image {
                      url
                    }
                  }
                }
              }
            }
            variants(first: 100) {
              edges {
                node {
                  id
                  title
                  media(first: 1) {
                    nodes {
                      id
                    }
                  }
                  selectedOptions {
                    name
                    value
                  }
                }
              }
            }
          }
        }
        pageInfo {
          hasNextPage
          endCursor
        }
      }
    }
    """
    products = []
    has_next = True
    cursor = None
    
    while has_next:
        res = run_graphql(query, {"cursor": cursor})
        data = res.get("data", {}).get("products", {})
        edges = data.get("edges", [])
        
        for edge in edges:
            products.append(edge["node"])
            
        page_info = data.get("pageInfo", {})
        has_next = page_info.get("hasNextPage", False)
        cursor = page_info.get("endCursor")
        
    return products

def get_products_by_query(query_str):
    """Retrieve products matching a specific query string."""
    query = """
    query GetProductsByQuery($queryStr: String, $cursor: String) {
      products(first: 50, query: $queryStr, after: $cursor) {
        edges {
          node {
            id
            title
            handle
            descriptionHtml
            productType
            category {
              id
              name
            }
            metafields(first: 20, keys: [
              "shopify.color-pattern", "shopify.fabric", "shopify.target-gender", "shopify.age-group",
              "shopify.sleeve-length-type", "shopify.one-piece-style", "shopify.dress-style", "shopify.neckline",
              "shopify.skirt-dress-length-type", "shopify.care-instructions", "shopify.clothing-features",
              "shopify.dress-occasion", "shopify.carry-options", "shopify.bag-case-material",
              "shopify.accessory-size", "shopify.bag-case-closure", "shopify.bag-case-features", "shopify.bag-case-storage-features"
            ]) {
              edges {
                node {
                  id
                  namespace
                  key
                  value
                }
              }
            }
            media(first: 50) {
              edges {
                node {
                  id
                  alt
                  mediaContentType
                  ... on MediaImage {
                    image {
                      url
                    }
                  }
                }
              }
            }
            variants(first: 100) {
              edges {
                node {
                  id
                  title
                  media(first: 1) {
                    nodes {
                      id
                    }
                  }
                  selectedOptions {
                    name
                    value
                  }
                }
              }
            }
          }
        }
        pageInfo {
          hasNextPage
          endCursor
        }
      }
    }
    """
    products = []
    has_next = True
    cursor = None
    
    while has_next:
        res = run_graphql(query, {"queryStr": query_str, "cursor": cursor})
        data = res.get("data", {}).get("products", {})
        edges = data.get("edges", [])
        
        for edge in edges:
            products.append(edge["node"])
            
        page_info = data.get("pageInfo", {})
        has_next = page_info.get("hasNextPage", False)
        cursor = page_info.get("endCursor")
        
    return products

# --- Local Heuristics / Rules Fallback ---

def parse_with_heuristics(title, desc, category_name):
    """Locally extract attributes using simple keyword rules if AI is limited."""
    text = f"{title} {desc}".lower()
    
    # 1. Color matching
    color = None
    colors = ["black", "white", "red", "blue", "green", "navy", "grey", "gray", "charcoal", 
              "cream", "ivory", "sage", "pink", "olive", "floral", "leopard", "paisley", "denim", "tomate"]
    for c in colors:
        if c in text:
            color = c.capitalize()
            if color == "Grey": color = "Gray"
            break
            
    # 2. Fabric matching (multiple allowed)
    matched_fabrics = []
    fabrics = ["linen", "cotton", "denim", "satin", "knit", "viscose", "velvet", "polyester", "acrylic", "wool", "rayon"]
    for f in fabrics:
        if f in text:
            matched_fabrics.append(f.capitalize())
    fabric = matched_fabrics if matched_fabrics else None
            
    # 3. Sleeve type matching
    sleeve = None
    if "sleeveless" in text:
        sleeve = "Sleeveless"
    elif "puff" in text:
        sleeve = "Puff"
    elif "short sleeve" in text or "short-sleeve" in text:
        sleeve = "Short"
    elif "long sleeve" in text or "long-sleeve" in text:
        sleeve = "Long"
    elif "cap sleeve" in text or "cap-sleeve" in text:
        sleeve = "Cap"
        
    # 4. Neckline matching
    neckline = None
    if "v-neck" in text or "v neck" in text:
        neckline = "V-neck"
    elif "round neck" in text or "round-neck" in text:
        neckline = "Round"
    elif "halter" in text:
        neckline = "Halter"
    elif "mock neck" in text or "mock-neck" in text:
        neckline = "Mock"
    elif "crew neck" in text or "crew-neck" in text:
        neckline = "Crew"
        
    # 5. Skirt/Dress Length matching
    length = None
    if "mini" in text:
        length = "Mini"
    elif "midi" in text:
        length = "Midi"
    elif "maxi" in text:
        length = "Maxi"
    elif "knee length" in text or "knee-length" in text:
        length = "Knee"
        
    # 6. Dress style matching
    style = None
    if "a-line" in text or "a line" in text:
        style = "A-line"
    elif "shift" in text:
        style = "Shift"
    elif "babydoll" in text:
        style = "Babydoll"
    elif "slip dress" in text or "slip-dress" in text:
        style = "Slip"
        
    # 7. Care instructions (multiple allowed)
    matched_care = []
    if "machine wash" in text:
        matched_care.append("Machine washable")
    if "tumble dry" in text:
        matched_care.append("Tumble dry")
    if "hand wash" in text:
        matched_care.append("Hand wash")
    if "dry clean" in text:
        matched_care.append("Dry clean only")
    care_instructions = matched_care if matched_care else None

    # 8. Clothing features (multiple allowed)
    matched_features = []
    if "stretch" in text or "spandex" in text or "elastane" in text:
        matched_features.append("Stretchable")
    if "breathable" in text:
        matched_features.append("Breathable design")
    if "lightweight" in text:
        matched_features.append("Lightweight")
    clothing_features = matched_features if matched_features else None

    # 9. Dress occasion (multiple allowed)
    matched_occasion = []
    if "casual" in text:
        matched_occasion.append("Casual")
    if "formal" in text:
        matched_occasion.append("Formal")
    if "party" in text or "cocktail" in text or "celebrate" in text:
        matched_occasion.append("Party")
    if "everyday" in text or "daily" in text:
        matched_occasion.append("Everyday")
    dress_occasion = matched_occasion if matched_occasion else None

    # 10. Handbag-specific heuristics (material & carry options)
    bag_case_material = None
    if "leather" in text:
        bag_case_material = ["Leather"]
        if "faux leather" in text or "vegan leather" in text or "pu leather" in text:
            bag_case_material = ["Faux leather"]
    elif "nylon" in text:
        bag_case_material = ["Nylon"]
    elif "canvas" in text:
        bag_case_material = ["Canvas"]
    elif "polyester" in text:
        bag_case_material = ["Polyester"]
    elif "straw" in text:
        bag_case_material = ["Straw"]
    elif "velvet" in text:
        bag_case_material = ["Velvet"]
        
    carry_options = []
    if "shoulder strap" in text or "shoulder bag" in text or "shoulder" in text:
        carry_options.append("Shoulder strap")
    if "top handle" in text or "tote" in text or "handle" in text:
        carry_options.append("Top handle")
    if "crossbody" in text or "cross-body" in text:
        carry_options.append("Crossbody strap")
    if "wristlet" in text:
        carry_options.append("Wristlet")
    if "backpack" in text:
        carry_options.append("Backpack strap")
    if "clutch" in text:
        carry_options.append("Clutch")
    carry_options = carry_options if carry_options else None

    # 11. Handbag closure heuristic
    bag_case_closure = None
    closures = ["zipper", "zip", "magnetic", "flap", "drawstring", "snap", "buckle", "open top", "kiss lock"]
    for cl in closures:
        if cl in text:
            bag_case_closure = "Zipper" if cl in ["zipper", "zip"] else cl.capitalize()
            break

    # 12. Handbag features heuristic
    bag_features = []
    if "water resistant" in text or "water-resistant" in text or "waterproof" in text:
        bag_features.append("Water resistant")
    if "lightweight" in text:
        bag_features.append("Lightweight")
    if "adjustable strap" in text or "adjustable-strap" in text:
        bag_features.append("Adjustable strap")
    if "detachable strap" in text or "detachable-strap" in text or "removable strap" in text:
        bag_features.append("Detachable strap")
    if "convertible" in text:
        bag_features.append("Convertible")
    bag_features = bag_features if bag_features else None

    # 13. Handbag storage features heuristic
    bag_storage = []
    if "laptop compartment" in text or "laptop pocket" in text:
        bag_storage.append("Laptop compartment")
    if "inner pocket" in text or "interior pocket" in text:
        bag_storage.append("Inner pockets")
    if "card slot" in text:
        bag_storage.append("Card slots")
    bag_storage = bag_storage if bag_storage else None

    # 14. Handbag size heuristic
    accessory_size = None
    if "mini" in text:
        accessory_size = "Mini"
    elif "small" in text:
        accessory_size = "Small"
    elif "medium" in text:
        accessory_size = "Medium"
    elif "large" in text:
        accessory_size = "Large"
        
    return {
        "color": color,
        "fabric": fabric,
        "bag_case_material": bag_case_material,
        "carry_options": carry_options,
        "accessory_size": accessory_size,
        "bag_case_closure": bag_case_closure,
        "bag_case_features": bag_features,
        "bag_case_storage_features": bag_storage,
        "target_gender": "Female",  # Meeeshop defaults
        "age_group": "Adults",
        "dress_style": style,
        "neckline": neckline,
        "skirt_length_type": length,
        "sleeve_length_type": sleeve,
        "care_instructions": care_instructions,
        "clothing_features": clothing_features,
        "dress_occasion": dress_occasion
    }

def get_extracted_attributes(title, desc, category_name):
    """Run AI first; if it returns None, instantly run local heuristics."""
    category_label = category_name if category_name else "Clothing"
    prompt = f"""Analyze this product's title and description:
Title: {title}
Description: {desc}
Category: {category_label}

Suggest values for the following standard attributes if you can identify them from the text. Note that you can return a list of strings for attributes that support multiple values (like fabric, care_instructions, clothing_features, sleeve_length_type, carry_options, bag_case_material, bag_case_features, bag_case_storage_features) or a single string:
1. target_gender (values: Female, Male, Unisex)
2. age_group (values: Adults, Kids, Teens, Babies, Toddlers, Universal)
3. color (e.g. Navy, Sage, Floral, Denim)
4. fabric (e.g. Denim, Linen, Cotton, Viscose, Polyester) - list or string (for clothing only)
5. bag_case_material (values: Leather, Faux leather, Canvas, Nylon, Polyester, Polyurethane, Straw, Velvet) - list or string (for bags/handbags only)
6. carry_options (values: Shoulder strap, Top handle, Crossbody strap, Wristlet, Backpack strap, Clutch) - list or string (for bags/handbags only)
7. accessory_size (values: One Size, Mini, Small, Medium, Large, Extra Large) - for bags/handbags only
8. bag_case_closure (values: Zipper, Magnetic, Flap, Drawstring, Snap, Buckle, Open top, Kiss lock) - for bags/handbags only
9. bag_case_features (values: Water resistant, Lightweight, Adjustable strap, Detachable strap, Convertible, Anti-theft) - list or string (for bags/handbags only)
10. bag_case_storage_features (values: Laptop compartment, Tablet pocket, Inner pockets, Card slots, Key leash) - list or string (for bags/handbags only)
11. dress_style (values: A-line, Babydoll, Blouson, Caftan, Drop waist, Empire waist, Flared, Gown, Jacket, Mermaid, Pencil, Peplum, Sheath, Shift, Shirt, Skater, Slip, Sweater, Tank, Trumpet, Wrap)
12. neckline (values: V-neck, Split, Asymmetric, Bardot, Boat, Cowl, Halter, Hooded, Mandarin, Crew, Mock, Plunging, Sweetheart, Turtle, Wrap, Round, Square)
13. skirt_length_type (values: Mini, Midi, Maxi, Knee, Short)
14. sleeve_length_type (values: Short, Sleeveless, Spaghetti strap, Strapless, 3/4, Cap, Long) - list or string
15. care_instructions (e.g. Machine washable, Tumble dry, Hand wash, Dry clean only, Dryer safe) - list or string
16. clothing_features (e.g. Stretchable, Insulated, Moisture wicking, Quick drying, Reversible, UV protection) - list or string
17. dress_occasion (values: Birthday, Casual, Dance, Everyday, Formal, Holiday, Pageant, Party, Portrait, Religious ceremony, School, Wedding) - list or string

Return ONLY a valid JSON object with keys: color, fabric, bag_case_material, carry_options, accessory_size, bag_case_closure, bag_case_features, bag_case_storage_features, target_gender, age_group, dress_style, neckline, skirt_length_type, sleeve_length_type, care_instructions, clothing_features, dress_occasion. If you can't identify any value for a key, use null.
"""
    try:
        # Single try for AI
        print("  Calling AI for attribute extraction...")
        ai_resp = generate(prompt, max_tokens=250, temperature=0.2)
        if ai_resp:
            # Parse JSON
            match = re.search(r'\{[\s\S]*\}', ai_resp)
            if match:
                parsed = json.loads(match.group(0))
                print("  ✓ AI Extraction successful.")
                return parsed
    except Exception as e:
        print(f"  [Warning] AI extraction failed or rate-limited: {e}")
        
    # Instant fallback to local template
    print("  ⚠ Falling back to Local Heuristics parser...")
    return parse_with_heuristics(title, desc, category_label)

# --- Variant Image Matcher ---

def find_matching_image(variant_title, options, product_media, unique_colors=None):
    """Find a product media image matching variant color option."""
    # Find color option
    color_val = None
    for opt in options:
        name_lower = opt["name"].lower()
        if "color" in name_lower or "colour" in name_lower:
            color_val = opt["value"].lower().strip()
            break
            
    if not color_val:
        return None
        
    # Scan media
    for media_edge in product_media.get("edges", []):
        m = media_edge["node"]
        if m.get("mediaContentType") != "IMAGE":
            continue
        m_id = m["id"]
        alt = (m.get("alt") or "").lower()
        url = (m.get("image", {}).get("url") or "").lower()
        
        # Match by alt text or filename portion
        filename = url.split("/")[-1].split("?")[0]
        if color_val in alt or color_val.replace(" ", "-") in filename or color_val.replace(" ", "_") in filename:
            return m_id
            
    # If no match and only one unique color across the product, return first image
    if unique_colors and len(unique_colors) == 1:
        for media_edge in product_media.get("edges", []):
            m = media_edge["node"]
            if m.get("mediaContentType") == "IMAGE":
                return m["id"]
            
    return None

def get_batch_extracted_attributes(products_info):
    """
    Query AI with a batch of products to extract their category metafields.
    products_info is a list of dicts:
      {
        "id": product GID (string),
        "title": title (string),
        "description": cleaned description (string, first 300 chars),
        "category": category label (string)
      }
    Returns a dict mapping product GID -> attributes dict.
    If the batch call fails or returns invalid JSON, returns an empty dict (allowing fallback).
    """
    if not products_info:
        return {}

    # Format the product info for the prompt
    formatted_products = []
    for p in products_info:
        desc_snippet = p["description"][:300] if p["description"] else ""
        formatted_products.append(
            f"Product ID: {p['id']}\n"
            f"Title: {p['title']}\n"
            f"Category: {p['category']}\n"
            f"Description: {desc_snippet}\n"
            f"---"
        )
    products_text = "\n".join(formatted_products)

    prompt = f"""You are an expert product data taxonomist. Analyze the following list of products:

{products_text}

For each product, identify values for these standard attributes if they are present in the title or description. Attributes and their allowed/example values:
1. target_gender (values: Female, Male, Unisex)
2. age_group (values: Adults, Kids, Teens, Babies, Toddlers, Universal)
3. color (e.g. Navy, Sage, Floral, Denim)
4. fabric (e.g. Denim, Linen, Cotton, Viscose, Polyester) - list or string
5. bag_case_material (values: Leather, Faux leather, Canvas, Nylon, Polyester, Polyurethane, Straw, Velvet) - list or string (for bags/handbags only)
6. carry_options (values: Shoulder strap, Top handle, Crossbody strap, Wristlet, Backpack strap, Clutch) - list or string (for bags/handbags only)
7. accessory_size (values: One Size, Mini, Small, Medium, Large, Extra Large) - for bags/handbags only
8. bag_case_closure (values: Zipper, Magnetic, Flap, Drawstring, Snap, Buckle, Open top, Kiss lock) - for bags/handbags only
9. bag_case_features (values: Water resistant, Lightweight, Adjustable strap, Detachable strap, Convertible, Anti-theft) - list or string (for bags/handbags only)
10. bag_case_storage_features (values: Laptop compartment, Tablet pocket, Inner pockets, Card slots, Key leash) - list or string (for bags/handbags only)
11. dress_style (values: A-line, Babydoll, Blouson, Caftan, Drop waist, Empire waist, Flared, Gown, Jacket, Mermaid, Pencil, Peplum, Sheath, Shift, Shirt, Skater, Slip, Sweater, Tank, Trumpet, Wrap)
12. neckline (values: V-neck, Split, Asymmetric, Bardot, Boat, Cowl, Halter, Hooded, Mandarin, Crew, Mock, Plunging, Sweetheart, Turtle, Wrap, Round, Square)
13. skirt_length_type (values: Mini, Midi, Maxi, Knee, Short)
14. sleeve_length_type (values: Short, Sleeveless, Spaghetti strap, Strapless, 3/4, Cap, Long) - list or string
15. care_instructions (e.g. Machine washable, Tumble dry, Hand wash, Dry clean only, Dryer safe) - list or string
16. clothing_features (e.g. Stretchable, Insulated, Moisture wicking, Quick drying, Reversible, UV protection) - list or string
17. dress_occasion (values: Birthday, Casual, Dance, Everyday, Formal, Holiday, Pageant, Party, Portrait, Religious ceremony, School, Wedding) - list or string

Return ONLY a valid JSON object mapping each Product ID to its identified attributes. If you cannot identify a value for an attribute, use null.
The output format must be a single JSON object where keys are the exact Product IDs and values are objects with keys: color, fabric, bag_case_material, carry_options, accessory_size, bag_case_closure, bag_case_features, bag_case_storage_features, target_gender, age_group, dress_style, neckline, skirt_length_type, sleeve_length_type, care_instructions, clothing_features, dress_occasion.

Example Output Format:
{{
  "gid://shopify/Product/12345": {{
    "color": "Navy",
    "fabric": null,
    "bag_case_material": ["Faux leather"],
    "carry_options": ["Shoulder strap", "Top handle"],
    "accessory_size": "Medium",
    "bag_case_closure": "Zipper",
    "bag_case_features": ["Detachable strap"],
    "bag_case_storage_features": ["Inner pockets"],
    "target_gender": "Female",
    "age_group": "Adults",
    "dress_style": null,
    "neckline": null,
    "skirt_length_type": null,
    "sleeve_length_type": null,
    "care_instructions": null,
    "clothing_features": null,
    "dress_occasion": null
  }}
}}
Do not include any explanation or markdown formatting outside of the raw JSON code block.
"""
    try:
        print(f"Calling AI for batch attribute extraction of {len(products_info)} product(s)...")
        # Increase max_tokens for batch response: 300 per product
        max_tokens = max(400, len(products_info) * 300)
        ai_resp = generate(prompt, max_tokens=max_tokens, temperature=0.2)
        if ai_resp:
            # Parse JSON
            match = re.search(r'\{[\s\S]*\}', ai_resp)
            if match:
                parsed = json.loads(match.group(0))
                print("✓ Batch AI Extraction successful.")
                return parsed
    except Exception as e:
        print(f"[Warning] Batch AI extraction failed or rate-limited: {e}")

    return {}

# --- Main Automation Logic ---

def process_product(product, dry_run=True, skip_ai=False, pre_extracted_attrs=None):
    """Process a single product: extract GPC metafields and variant images."""
    p_id = product["id"]
    p_title = product["title"]
    p_handle = product["handle"]
    desc = product["descriptionHtml"] or ""
    product_type = product["productType"] or ""
    category_name = product.get("category", {}).get("name") if product.get("category") else None
    
    print(f"\nProcessing product: {p_title} (Handle: {p_handle})")
    
    category_id = product.get("category", {}).get("id") if product.get("category") else None
    if category_id and category_id not in loaded_categories:
        loaded_categories.add(category_id)
        cat_std_vals = load_standard_category_values(category_id)
        standard_values_cache.update(cat_std_vals)
        print(f"  Loaded {len(cat_std_vals)} standard values for category '{product['category']['name']}'.")

    suggestions = {
        "product_id": p_id,
        "title": p_title,
        "handle": p_handle,
        "metafields": [],
        "variants": []
    }
    
    # 1. Fetch AI/Local Category Metafields
    if skip_ai:
        print(f"  - Category metafields already set for '{p_title}'. Skipping AI/heuristics attribute extraction.")
        attrs = {}
    elif pre_extracted_attrs is not None:
        print(f"  - Using pre-extracted attributes from batch AI call.")
        attrs = pre_extracted_attrs
    else:
        attrs = get_extracted_attributes(p_title, desc, category_name)
    print(f"  Extracted Attributes: {attrs}")
    
    # Map to metafield list
    for key, val in attrs.items():
        if not val:
            continue
        
        # Resolve to standard taxonomy key
        mapping = TAXONOMY_MAP.get(key)
        if not mapping:
            continue
            
        std_key = mapping["key"]
        mo_type = mapping["type"]
        
        # Check if this standard key definition exists on the store
        if std_key not in shopify_definitions:
            continue
            
        # Resolve value(s) to metaobject reference GID(s)
        gids = []
        vals_to_process = val if isinstance(val, list) else [val]
        for v in vals_to_process:
            if not v:
                continue
            v_cleaned = v.lower().strip()
            mo_gid = resolve_metaobject_value(mo_type, v_cleaned)
            if mo_gid:
                gids.append(mo_gid)
            else:
                print(f"  - Standard value '{v}' not found in active metaobjects for '{mo_type}' (skipped)")
                
        if gids:
            suggestions["metafields"].append({
                "namespace": "shopify",
                "key": std_key,
                "value": json.dumps(gids),
                "type": "list.metaobject_reference"
            })
            print(f"  ✓ Standard metafield resolved: shopify.{std_key} = {val} ({gids})")
            
    # 2. Check Variant Images
    # First, collect all unique colors in variants
    unique_colors = set()
    for v_edge in product.get("variants", {}).get("edges", []):
        v = v_edge["node"]
        for opt in v.get("selectedOptions", []):
            if "color" in opt["name"].lower() or "colour" in opt["name"].lower():
                val = opt["value"].strip()
                if val:
                    unique_colors.add(val)

    for v_edge in product.get("variants", {}).get("edges", []):
        v = v_edge["node"]
        v_id = v["id"]
        v_title = v["title"]
        media_nodes = v.get("media", {}).get("nodes", []) if v.get("media") else []
        current_media_id = media_nodes[0]["id"] if media_nodes else None
        
        if not current_media_id:
            # Try to match image
            matching_img_id = find_matching_image(v_title, v["selectedOptions"], product["media"], unique_colors)
            if matching_img_id:
                print(f"  ✓ Found matching image for variant '{v_title}': {matching_img_id.split('/')[-1]}")
                suggestions["variants"].append({
                    "id": v_id,
                    "title": v_title,
                    "image_id": matching_img_id
                })
            else:
                print(f"  - No matching image found for variant '{v_title}'")
                
    return suggestions

def apply_product_updates(suggestions):
    """Apply metafield and variant updates to Shopify."""
    p_id = suggestions["product_id"]
    title = suggestions["title"]
    
    print(f"\nApplying updates to product: {title}")
    
    # 1. Update Metafields
    if suggestions["metafields"]:
        metafields_payload = []
        for m in suggestions["metafields"]:
            metafields_payload.append({
                "ownerId": p_id,
                "namespace": m["namespace"],
                "key": m["key"],
                "value": m["value"],
                "type": m["type"]
            })
            
        mutation = """
        mutation metafieldsSet($metafields: [MetafieldsSetInput!]!) {
          metafieldsSet(metafields: $metafields) {
            metafields {
              key
              value
            }
            userErrors {
              field
              message
            }
          }
        }
        """
        try:
            res = run_graphql(mutation, {"metafields": metafields_payload})
            errors = res.get("data", {}).get("metafieldsSet", {}).get("userErrors", [])
            if errors:
                print(f"  ❌ Metafield Errors: {errors}")
            else:
                print(f"  ✓ Successfully updated {len(metafields_payload)} category metafields.")
        except Exception as e:
            print(f"  ❌ Metafield Update Failed: {e}")
            
    # 2. Update Variant Images
    if suggestions["variants"]:
        bulk_mutation = """
        mutation productVariantsBulkUpdate($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
          productVariantsBulkUpdate(productId: $productId, variants: $variants) {
            productVariants {
              id
            }
            userErrors {
              field
              message
            }
          }
        }
        """
        variants_payload = []
        for v in suggestions["variants"]:
            variants_payload.append({
                "id": v["id"],
                "mediaId": v["image_id"]
            })
            
        try:
            res = run_graphql(bulk_mutation, {
                "productId": p_id,
                "variants": variants_payload
            })
            errors = res.get("data", {}).get("productVariantsBulkUpdate", {}).get("userErrors", [])
            if errors:
                print(f"  ❌ Variant Image Update Errors: {errors}")
            else:
                print(f"  ✓ Successfully updated {len(variants_payload)} variant images.")
        except Exception as e:
            print(f"  ❌ Variant Image Update Failed: {e}")

# --- Revert Logic ---

def fetch_current_metafields_and_variants(product_ids):
    """Fetch current state of products for backing up before updates."""
    # We query GraphQL for exact current values of the metafields and variant images
    query = """
    query GetBackupInfo($ids: [ID!]!) {
      nodes(ids: $ids) {
        ... on Product {
          id
          title
          handle
          metafields(first: 20, keys: [
            "shopify.color-pattern", "shopify.fabric", "shopify.target-gender", "shopify.age-group",
            "shopify.sleeve-length-type", "shopify.one-piece-style", "shopify.dress-style", "shopify.neckline",
            "shopify.skirt-dress-length-type", "shopify.care-instructions", "shopify.clothing-features",
            "shopify.dress-occasion", "shopify.carry-options", "shopify.bag-case-material",
            "shopify.accessory-size", "shopify.bag-case-closure", "shopify.bag-case-features", "shopify.bag-case-storage-features"
          ]) {
            edges {
              node {
                id
                namespace
                key
                value
              }
            }
          }
          variants(first: 100) {
            edges {
              node {
                id
                media(first: 1) {
                  nodes {
                    id
                  }
                }
              }
            }
          }
        }
      }
    }
    """
    res = run_graphql(query, {"ids": product_ids})
    nodes = res.get("data", {}).get("nodes", [])
    
    backup_data = []
    for node in nodes:
        if not node: continue
        
        metafields = []
        for m_edge in node.get("metafields", {}).get("edges", []):
            m = m_edge["node"]
            metafields.append({
                "id": m["id"],
                "namespace": m["namespace"],
                "key": m["key"],
                "value": m["value"]
            })
            
        variants = []
        for v_edge in node.get("variants", {}).get("edges", []):
            v = v_edge["node"]
            media_nodes = v.get("media", {}).get("nodes", []) if v.get("media") else []
            variants.append({
                "id": v["id"],
                "media_id": media_nodes[0]["id"] if media_nodes else None
            })
            
        backup_data.append({
            "product_id": node["id"],
            "title": node["title"],
            "handle": node["handle"],
            "metafields": metafields,
            "variants": variants
        })
    return backup_data

def revert_metafields_and_variants(backup_file):
    """Restore state from backup log file."""
    if not os.path.exists(backup_file):
        print(f"Error: Backup file {backup_file} not found.")
        return
        
    with open(backup_file, "r", encoding="utf-8") as f:
        backup_data = json.load(f)
        
    print(f"Reverting changes for {len(backup_data)} products...")
    
    for p in backup_data:
        p_id = p["product_id"]
        print(f"Reverting Product: {p['title']}")
        
        # Revert metafields
        # If the metafield existed, set it back. If it didn't, we delete the current value.
        current = fetch_current_metafields_and_variants([p_id])[0]
        backup_keys = {m["key"] for m in p["metafields"]}
        
        # Delete metafields created during apply that were not originally there
        to_delete = []
        for m in current["metafields"]:
            if m["key"] not in backup_keys:
                print(f"  - Deleting new metafield shopify.{m['key']}")
                to_delete.append({
                    "ownerId": p_id,
                    "namespace": m["namespace"],
                    "key": m["key"]
                })
        if to_delete:
            delete_mutation = """
            mutation metafieldsDelete($metafields: [MetafieldIdentifierInput!]!) {
              metafieldsDelete(metafields: $metafields) {
                deletedMetafields {
                  ownerId
                  namespace
                  key
                }
                userErrors {
                  field
                  message
                }
              }
            }
            """
            run_graphql(delete_mutation, {"metafields": to_delete})
                
        # Restore originally backed up metafields
        if p["metafields"]:
            metafields_payload = []
            for m in p["metafields"]:
                metafields_payload.append({
                    "ownerId": p_id,
                    "namespace": m["namespace"],
                    "key": m["key"],
                    "value": m["value"],
                    "type": "list.metaobject_reference"
                })
            if metafields_payload:
                set_mutation = """
                mutation metafieldsSet($metafields: [MetafieldsSetInput!]!) {
                  metafieldsSet(metafields: $metafields) {
                    metafields {
                      key
                    }
                  }
                }
                """
                run_graphql(set_mutation, {"metafields": metafields_payload})
                print(f"  ✓ Restored original {len(metafields_payload)} metafields.")
                
        # Revert variants using bulk update
        variants_payload = []
        for v in p["variants"]:
            v_id = v["id"]
            orig_media = v.get("media_id") or v.get("image_id")
            
            # Check current variant media
            current_v = next((x for x in current["variants"] if x["id"] == v_id), None)
            current_media_id = current_v.get("media_id") if current_v else None
            
            if current_media_id != orig_media:
                variants_payload.append({
                    "id": v_id,
                    "mediaId": orig_media
                })
                
        if variants_payload:
            bulk_mutation = """
            mutation productVariantsBulkUpdate($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
              productVariantsBulkUpdate(productId: $productId, variants: $variants) {
                userErrors {
                  field
                  message
                }
              }
            }
            """
            run_graphql(bulk_mutation, {
                "productId": p_id,
                "variants": variants_payload
            })
            print(f"  ✓ Restored original images for {len(variants_payload)} variants.")

# ══════════════════════════════════════════════════════════════════════════════
# LOG HELPERS FOR SKIP HISTORY
# ══════════════════════════════════════════════════════════════════════════════

def load_recently_updated_ids(filepath: str = "category_metafields_log.json") -> set:
    """
    Return a set of product IDs (GID strings) that were successfully processed/updated.
    Searches recursively for all category_metafields_log.json files in the workspace.
    """
    from pathlib import Path
    log_files = []
    if os.path.exists(filepath):
        log_files.append(Path(filepath))

    for p in Path(".").glob("**/category_metafields_log.json"):
        if p.resolve() not in [lf.resolve() for lf in log_files]:
            log_files.append(p)

    processed_ids = set()
    for lf in log_files:
        try:
            logs = json.loads(lf.read_text(encoding="utf-8"))
            if not isinstance(logs, list):
                continue
            for entry in logs:
                if not isinstance(entry, dict):
                    continue
                ids = entry.get("processed_ids", [])
                for item_id in ids:
                    processed_ids.add(str(item_id))
        except Exception:
            pass
    return processed_ids


def save_update_log(processed_ids: set, stats: dict, filepath: str = "category_metafields_log.json"):
    from pathlib import Path
    log_path = Path(filepath)
    logs = []
    if log_path.exists():
        try:
            logs = json.loads(log_path.read_text(encoding="utf-8"))
        except Exception:
            logs = []

    existing_timestamps = {entry.get("timestamp") for entry in logs if isinstance(entry, dict)}

    # Merge logs from other files
    for p in Path(".").glob("**/category_metafields_log.json"):
        if p.resolve() == log_path.resolve():
            continue
        try:
            sub_logs = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(sub_logs, list):
                for entry in sub_logs:
                    if isinstance(entry, dict):
                        ts = entry.get("timestamp")
                        if ts not in existing_timestamps:
                            logs.append(entry)
                            existing_timestamps.add(ts)
        except Exception:
            pass

    logs.sort(key=lambda entry: entry.get("timestamp") or "")

    logs.append({
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "summary": stats,
        "processed_ids": sorted(list(processed_ids))
    })

    log_path.write_text(json.dumps(logs, indent=2), encoding="utf-8")
    print(f"[Log] Saved consolidated log to {filepath}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Shopify Category Metafields & Variant Image Automation Utility")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--diagnose", action="store_true", help="Diagnose and preview changes")
    group.add_argument("--apply", action="store_true", help="Diagnose and apply changes directly")
    group.add_argument("--revert", action="store_true", help="Revert changes from a backup file")
    
    parser.add_argument("--handle", help="Restrict run to a single product handle (for local validation)")
    parser.add_argument("--query", help="Scan products matching a custom Shopify query (e.g. 'product_type:Handbags')")
    parser.add_argument("--full", action="store_true", help="Trigger a full catalog scan (forced)")
    parser.add_argument("--weekly", action="store_true", help="Scan products created in the last 7 days")
    parser.add_argument("--daily", action="store_true", help="Scan products created in the last 24 hours")
    parser.add_argument("--batch-size", type=int, default=0, help="Batch size for slicing products (0 = no batching)")
    parser.add_argument("--batch-index", type=int, default=0, help="Batch index for slicing products (0-based)")
    parser.add_argument("--backup-file", default="shopify_metafields_backup.json", help="Path to backup log file")
    
    args = parser.parse_args()
    
    if args.revert:
        revert_metafields_and_variants(args.backup_file)
        print("\nRevert operation completed.")
        return
        
    init_taxonomy_cache()
    
    # Determine scan list
    products = []
    if args.handle:
        print(f"Loading single product or collection with handle: {args.handle}")
        prod = get_product_by_handle(args.handle)
        if prod:
            products.append(prod)
        else:
            col, col_prods = get_collection_products_by_handle(args.handle)
            if col and col_prods:
                print(f"✓ Smart Match: '{args.handle}' is a Collection ({col['title']}). Loaded {len(col_prods)} products for category metafield updates.")
                products.extend(col_prods)
                
                # Also run Collection SEO & PAA Accordion update for this collection
                try:
                    import bulk_update_collection_seo
                    print(f"✓ Running Collection SEO & PAA updates for '{col['title']}'...")
                    bulk_update_collection_seo.update_all_collections(target_handle=args.handle, dry_run=args.diagnose, force=args.full or args.weekly)
                except Exception as e:
                    print(f"  [Collection SEO Notice]: {e}")
            else:
                print(f"Error: Handle '{args.handle}' is neither a valid Product handle nor a Collection handle.")
                sys.exit(1)
    elif args.query:
        # Strip outer quotes if passed literally by shell escaping
        clean_query = args.query.strip().strip('"').strip("'")
        print(f"Loading products matching query: {clean_query}")
        products = get_products_by_query(clean_query)
        print(f"Fetched {len(products)} products.")
    elif args.full:
        print("Loading full store catalog...")
        products = get_all_products()
        print(f"Fetched {len(products)} products.")
    elif args.weekly:
        # Weekly Mode (last 7 days created)
        seven_days_ago = (time.time() - (7 * 24 * 3600))
        seven_days_ago_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(seven_days_ago))
        print(f"Loading products created since: {seven_days_ago_iso}")
        products = get_recent_products(seven_days_ago_iso, query_field="created_at")
        print(f"Fetched {len(products)} recently created products.")
    else:
        # Daily Mode (last 24 hours created, default/fallback)
        yesterday = (time.time() - (24 * 3600))
        yesterday_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(yesterday))
        print(f"Loading products created since: {yesterday_iso}")
        products = get_recent_products(yesterday_iso, query_field="created_at")
        print(f"Fetched {len(products)} recently created products.")
        
    # Auto-run Collection SEO & PAA FAQs update for store collections during batch/mode runs
    if not args.handle:
        try:
            import bulk_update_collection_seo
            print("\n==================================================")
            print("Running Collection SEO & PAA Accordions Update...")
            print("==================================================")
            bulk_update_collection_seo.update_all_collections(dry_run=args.diagnose, force=args.full)
        except Exception as e:
            print(f"  [Collection SEO Notice]: {e}")

    if not products:
        print("No products found to process.")
        return

    # Slice products if batching is enabled
    if args.batch_size > 0:
        start = args.batch_index * args.batch_size
        end = start + args.batch_size
        sliced_products = products[start:end]
        print(f"[Batch] Slicing products: index={args.batch_index}, size={args.batch_size} (processing {len(sliced_products)} of {len(products)})")
        products = sliced_products
        if not products:
            print("No products in this batch slice.")
            return

    # ── Load recently processed GIDs to skip ──────────────────────────────────
    skip_ids = set()
    if not args.full and not args.handle and not args.query:
        try:
            skip_ids = load_recently_updated_ids()
            if skip_ids:
                print(f"[Skip] {len(skip_ids)} product(s) already processed in previous runs — will skip\n")
        except Exception as e:
            print(f"Warning: Failed to load skip history: {e}")

    processed_ids = set()
        
    # Analyze and generate suggestions
    products_to_process = []
    products_needing_ai = []
    
    for p in products:
        p_id = p["id"]
        if not args.full and not args.handle and not args.query and p_id in skip_ids:
            print(f"Skipping product (recently processed): {p['title']}")
            continue

        # Check if product already has standard category metafields populated
        metafield_edges = p.get("metafields", {}).get("edges", []) if p.get("metafields") else []
        has_metafields = False
        for edge in metafield_edges:
            m = edge.get("node", {})
            if m.get("value"):
                has_metafields = True
                break

        skip_ai = has_metafields and not args.full and not args.handle and not args.query
        products_to_process.append((p, skip_ai))
        
        if not skip_ai:
            desc_html = p.get("descriptionHtml") or ""
            desc_clean = re.sub(r'<[^>]*>', '', desc_html).strip()
            desc_clean = re.sub(r'\s+', ' ', desc_clean)
            products_needing_ai.append({
                "id": p_id,
                "title": p["title"],
                "description": desc_clean[:300],
                "category": p.get("category", {}).get("name") if p.get("category") else "Clothing"
            })

    # Run batch AI call in chunks of 10 to avoid token limitations or output truncations
    batch_results = {}
    if products_needing_ai:
        chunk_size = 10
        total_chunks = (len(products_needing_ai) - 1) // chunk_size + 1
        for i in range(0, len(products_needing_ai), chunk_size):
            chunk = products_needing_ai[i:i + chunk_size]
            chunk_num = i // chunk_size + 1
            print(f"\n--- Batch Chunk {chunk_num} of {total_chunks} ({len(chunk)} products) ---")
            chunk_results = get_batch_extracted_attributes(chunk)
            if chunk_results:
                batch_results.update(chunk_results)

    all_suggestions = []
    for p, skip_ai in products_to_process:
        p_id = p["id"]
        p_pre_extracted = None
        if not skip_ai:
            if batch_results and p_id in batch_results:
                p_pre_extracted = batch_results.get(p_id)
                if not isinstance(p_pre_extracted, dict) or not p_pre_extracted:
                    p_pre_extracted = None
            
            # If batch results didn't have it, or batch failed, use non-AI heuristics fallback immediately
            if p_pre_extracted is None:
                print(f"  ⚠ AI failed or not available for '{p['title']}'. Falling back to local heuristics immediately.")
                title = p["title"]
                desc_html = p.get("descriptionHtml") or ""
                category_name = p.get("category", {}).get("name") if p.get("category") else "Clothing"
                p_pre_extracted = parse_with_heuristics(title, desc_html, category_name)
                
        s = process_product(p, skip_ai=skip_ai, pre_extracted_attrs=p_pre_extracted)
        processed_ids.add(p_id)
        if s["metafields"] or s["variants"]:
            all_suggestions.append(s)
            
    if not all_suggestions:
        print("\nNo metadata or variant image updates are needed.")
        # Save processed GIDs log if no updates are needed
        if not args.full and not args.handle:
            try:
                stats = {
                    "total_fetched": len(products),
                    "total_processed": len(processed_ids),
                    "total_updates_found": 0
                }
                save_update_log(processed_ids, stats)
            except Exception as e:
                print(f"Warning: Failed to save skip history: {e}")
        return
        
    print(f"\nFound updates for {len(all_suggestions)} products.")
    
    if args.diagnose:
        # Write suggestions to preview file
        preview_file = "category_metafields_preview.json"
        with open(preview_file, "w", encoding="utf-8") as f:
            json.dump(all_suggestions, f, indent=2)
        print(f"\nDiagnostics preview written to '{preview_file}'.")
        print("To apply these changes, run: python automate_category_metafields.py --apply " + 
              (f"--handle {args.handle}" if args.handle else ""))
        
    elif args.apply:
        # 1. Back up current state of target products before updating
        target_ids = [s["product_id"] for s in all_suggestions]
        print(f"\nBacking up current state of {len(target_ids)} products before applying changes...")
        backup_data = fetch_current_metafields_and_variants(target_ids)
        
        with open(args.backup_file, "w", encoding="utf-8") as f:
            json.dump(backup_data, f, indent=2)
        print(f"Backup written to '{args.backup_file}'.")
        
        # 2. Apply updates
        for s in all_suggestions:
            apply_product_updates(s)
        print("\nAll updates applied successfully.")

        # Save processed GIDs log after successfully applying updates
        if not args.full and not args.handle:
            try:
                stats = {
                    "total_fetched": len(products),
                    "total_processed": len(processed_ids),
                    "total_updates_found": len(all_suggestions)
                }
                save_update_log(processed_ids, stats)
            except Exception as e:
                print(f"Warning: Failed to save skip history: {e}")

if __name__ == "__main__":
    main()

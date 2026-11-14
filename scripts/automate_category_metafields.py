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
    # Color & Patterns
    "color": {
        "key": "color-pattern",
        "type": "shopify--color-pattern"
    },
    # Fabric
    "fabric": {
        "key": "fabric",
        "type": "shopify--fabric"
    },
    # Pants, Jeans & Denim Specific Metafields
    "waist_rise": {
        "key": "waist-rise",
        "type": "shopify--waist-rise"
    },
    "pants_length_type": {
        "key": "pants-length-type",
        "type": "shopify--pants-length-type"
    },
    "fit": {
        "key": "fit",
        "type": "shopify--fit"
    },
    # Handbags & Bags
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
    # Demographics
    "target_gender": {
        "key": "target-gender",
        "type": "shopify--target-gender"
    },
    "age_group": {
        "key": "age-group",
        "type": "shopify--age-group"
    },
    # Tops / Blouses / Sweaters / Outerwear
    "sleeve_length_type": {
        "key": "sleeve-length-type",
        "type": "shopify--sleeve-length-type"
    },
    "neckline": {
        "key": "neckline",
        "type": "shopify--neckline"
    },
    "outerwear_clothing_features": {
        "key": "outerwear-clothing-features",
        "type": "shopify--outerwear-clothing-features"
    },
    "one_piece_style": {
        "key": "one-piece-style",
        "type": "shopify--one-piece-style"
    },
    # Dresses
    "dress_style": {
        "key": "dress-style",
        "type": "shopify--dress-style"
    },
    "skirt_length_type": {
        "key": "skirt-dress-length-type",
        "type": "shopify--skirt-dress-length-type"
    },
    "dress_occasion": {
        "key": "dress-occasion",
        "type": "shopify--dress-occasion"
    },
    # Care & Features
    "care_instructions": {
        "key": "care-instructions",
        "type": "shopify--care-instructions"
    },
    "clothing_features": {
        "key": "clothing-features",
        "type": "shopify--clothing-features"
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
        "shopify--waist-rise",
        "shopify--pants-length-type",
        "shopify--fit",
        "shopify--bag-case-material",
        "shopify--carry-options",
        "shopify--accessory-size",
        "shopify--bag-case-closure",
        "shopify--bag-case-features",
        "shopify--bag-case-storage-features",
        "shopify--target-gender",
        "shopify--age-group",
        "shopify--sleeve-length-type",
        "shopify--outerwear-clothing-features",
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
        "mock neck": "mock",
        "v neck": "v-neck",
        "crew neck": "crew",
        "high-rise": "high",
        "high rise": "high",
        "high waist": "high",
        "high waisted": "high",
        "mid-rise": "mid",
        "mid rise": "mid",
        "medium rise": "mid",
        "low-rise": "low",
        "low rise": "low",
        "ultra high rise": "ultra high",
        "wide leg": "wide",
        "wide-leg": "wide",
        "boot cut": "bootcut",
        "boot-cut": "bootcut",
        "straight leg": "straight",
        "straight-leg": "straight",
        "relaxed fit": "relaxed",
        "skinny fit": "skinny",
        "regular fit": "regular",
        "slim fit": "slim",
        "full length": "long",
        "full-length": "long",
        "ankle length": "ankle",
        "ankle-length": "ankle",
        "crop": "cropped",
        "3/4 sleeve": "3/4",
        "three quarter": "3/4",
        "short-sleeve": "short",
        "long-sleeve": "long",
        "pocket": "pockets",
        "hood": "hooded",
        "button": "button front",
        "buttons": "button front",
        "zip": "zipper front",
        "zipper": "zipper front",
        "overalls": "overall",
        "rompers": "romper",
        "jumpsuits": "jumpsuit"
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

METAFIELDS_QUERY_FRAGMENT = """
        metafields(first: 50, keys: [
          "shopify.color-pattern", "shopify.fabric", "shopify.target-gender", "shopify.age-group",
          "shopify.sleeve-length-type", "shopify.one-piece-style", "shopify.dress-style", "shopify.neckline",
          "shopify.skirt-dress-length-type", "shopify.care-instructions", "shopify.clothing-features",
          "shopify.dress-occasion", "shopify.carry-options", "shopify.bag-case-material",
          "shopify.accessory-size", "shopify.bag-case-closure", "shopify.bag-case-features", "shopify.bag-case-storage-features",
          "shopify.waist-rise", "shopify.pants-length-type", "shopify.fit", "shopify.outerwear-clothing-features",
          "shopify--discovery--product_search_boost.queries",
          "custom.search_keyword_1", "custom.search-keyword_2", "custom.search-keyword_3", "custom.search-keyword_4", "custom.search-keyword_5"
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
"""

def get_product_by_handle(handle):
    """Retrieve product, variants, and media by product handle."""
    query = f"""
    query GetProduct($handle: String!) {{
      productByHandle(handle: $handle) {{
        id
        title
        handle
        descriptionHtml
        productType
        vendor
        category {{
          id
          name
        }}
        {METAFIELDS_QUERY_FRAGMENT}
        media(first: 50) {{
          edges {{
            node {{
              id
              alt
              mediaContentType
              ... on MediaImage {{
                image {{
                  url
                }}
              }}
            }}
          }}
        }}
        variants(first: 100) {{
          edges {{
            node {{
              id
              title
              media(first: 1) {{
                nodes {{
                  id
                }}
              }}
              selectedOptions {{
                name
                value
              }}
            }}
          }}
        }}
      }}
    }}
    """
    res = run_graphql(query, {"handle": handle})
    return res.get("data", {}).get("productByHandle")

def get_collection_products_by_handle(handle):
    """Retrieve all products inside a collection by collection handle."""
    query = f"""
    query GetCollectionProducts($handle: String!) {{
      collectionByHandle(handle: $handle) {{
        id
        title
        handle
        products(first: 50) {{
          edges {{
            node {{
              id
              title
              handle
              descriptionHtml
              productType
              vendor
              category {{
                id
                name
              }}
              {METAFIELDS_QUERY_FRAGMENT}
              media(first: 50) {{
                edges {{
                  node {{
                    id
                    alt
                    mediaContentType
                    ... on MediaImage {{
                      image {{
                        url
                      }}
                    }}
                  }}
                }}
              }}
              variants(first: 100) {{
                edges {{
                  node {{
                    id
                    title
                    media(first: 1) {{
                      nodes {{
                        id
                      }}
                    }}
                    selectedOptions {{
                      name
                      value
                    }}
                  }}
                }}
              }}
            }}
          }}
        }}
      }}
    }}
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
    query = f"""
    query GetRecentProducts($queryStr: String, $cursor: String) {{
      products(first: 50, query: $queryStr, after: $cursor) {{
        edges {{
          node {{
            id
            title
            handle
            descriptionHtml
            productType
            vendor
            category {{
              id
              name
            }}
            {METAFIELDS_QUERY_FRAGMENT}
            media(first: 50) {{
              edges {{
                node {{
                  id
                  alt
                  mediaContentType
                  ... on MediaImage {{
                    image {{
                      url
                    }}
                  }}
                }}
              }}
            }}
            variants(first: 100) {{
              edges {{
                node {{
                  id
                  title
                  media(first: 1) {{
                    nodes {{
                  id
                }}
              }}
              selectedOptions {{
                name
                value
              }}
            }}
          }}
        }}
      }}
        pageInfo {{
          hasNextPage
          endCursor
        }}
      }}
    }}
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
    query = f"""
    query GetAllProducts($cursor: String) {{
      products(first: 50, after: $cursor) {{
        edges {{
          node {{
            id
            title
            handle
            descriptionHtml
            productType
            vendor
            category {{
              id
              name
            }}
            {METAFIELDS_QUERY_FRAGMENT}
            media(first: 50) {{
              edges {{
                node {{
                  id
                  alt
                  mediaContentType
                  ... on MediaImage {{
                    image {{
                      url
                    }}
                  }}
                }}
              }}
            }}
            variants(first: 100) {{
              edges {{
                node {{
                  id
                  title
                  media(first: 1) {{
                    nodes {{
                      id
                    }}
                  }}
                  selectedOptions {{
                    name
                    value
                  }}
                }}
              }}
            }}
          }}
        }}
        pageInfo {{
          hasNextPage
          endCursor
        }}
      }}
    }}
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
    query = f"""
    query GetProductsByQuery($queryStr: String, $cursor: String) {{
      products(first: 50, query: $queryStr, after: $cursor) {{
        edges {{
          node {{
            id
            title
            handle
            descriptionHtml
            productType
            vendor
            category {{
              id
              name
            }}
            {METAFIELDS_QUERY_FRAGMENT}
            media(first: 50) {{
              edges {{
                node {{
                  id
                  alt
                  mediaContentType
                  ... on MediaImage {{
                    image {{
                      url
                    }}
                  }}
                }}
              }}
            }}
            variants(first: 100) {{
              edges {{
                node {{
                  id
                  title
                  media(first: 1) {{
                    nodes {{
                      id
                    }}
                  }}
                  selectedOptions {{
                    name
                    value
                  }}
                }}
              }}
            }}
          }}
        }}
        pageInfo {{
          hasNextPage
          endCursor
        }}
      }}
    }}
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

# --- Product Domain Classification & SEO Keywords ---

def classify_product_domain(product_type: str = "", category_name: str = "", title: str = "") -> str:
    """Classify product into core domain for category-accurate metafield extraction."""
    comb = f"{product_type or ''} {category_name or ''} {title or ''}".lower()
    
    if any(k in comb for k in ["handbag", "purse", "tote bag", "crossbody bag", "clutch", "backpack", "satchel", "wallet"]):
        return "handbags"
    if any(k in comb for k in ["romper", "jumpsuit", "overall"]):
        return "one_piece"
    if any(k in comb for k in ["jacket", "coat", "blazer", "vest", "shacket", "parka", "puffer", "outerwear"]):
        return "outerwear"
    if any(k in comb for k in ["dress", "gown", "sundress"]):
        return "dresses"
    if any(k in comb for k in ["jean", "denim pant", "pants", "pant", "trouser", "legging", "jeggings", "shorts", "skort"]):
        return "pants_denim"
    if any(k in comb for k in ["top", "shirt", "blouse", "sweater", "cardigan", "tee", "t-shirt", "tank", "cami", "pullover", "hoodie", "sweatshirt", "bodysuit"]):
        return "tops_sweaters"
    return "apparel_general"


def generate_product_seo_keywords(title: str, desc: str, domain: str, vendor: str, attributes: dict):
    """
    Generate high-converting US women shopper search boost queries (up to 10)
    and 5 custom search keywords for organic discovery.
    """
    queries = []
    clean_vendor = (vendor or "").strip()
    clean_title = (title or "").strip()
    
    # 1. Vendor + core item
    if clean_vendor and clean_vendor.lower() not in clean_title.lower():
        queries.append(f"{clean_vendor} {clean_title}"[:100])
    else:
        queries.append(clean_title[:100])
        
    # Domain specific queries for US women shoppers
    if domain == "pants_denim":
        rise = attributes.get("waist_rise") or "high rise"
        fit = attributes.get("fit") or "stretch"
        if isinstance(rise, list): rise = rise[0]
        if isinstance(fit, list): fit = fit[0]
        
        queries.append(f"women's {rise.lower()} {fit.lower()} jeans")
        queries.append(f"women's {fit.lower()} denim pants")
        queries.append("tummy control stretch jeans women")
        queries.append("comfortable stretch denim women")
        queries.append("trending women's boutique jeans")
        if clean_vendor:
            queries.append(f"{clean_vendor} {fit.lower()} jeans for women")
        queries.append("boutique high waisted jeans usa")
    elif domain == "dresses":
        style = attributes.get("dress_style") or "casual"
        length = attributes.get("skirt_length_type") or "maxi"
        occasion = attributes.get("dress_occasion") or "everyday"
        if isinstance(style, list): style = style[0]
        if isinstance(length, list): length = length[0]
        if isinstance(occasion, list): occasion = occasion[0]
        
        queries.append(f"women's {length.lower()} {style.lower()} dress")
        queries.append(f"women's {occasion.lower()} boutique dress")
        queries.append("flowy boho floral dresses for women")
        queries.append("casual summer sundresses women")
        queries.append("chic party evening midi dress")
        if clean_vendor:
            queries.append(f"{clean_vendor} women's dresses")
        queries.append("trendy boutique dresses usa")
    elif domain == "tops_sweaters":
        sleeve = attributes.get("sleeve_length_type") or "long sleeve"
        neck = attributes.get("neckline") or "v-neck"
        if isinstance(sleeve, list): sleeve = sleeve[0]
        if isinstance(neck, list): neck = neck[0]
        
        queries.append(f"women's {sleeve.lower()} {neck.lower()} top")
        queries.append("soft knit cozy sweater women")
        queries.append("trendy boutique tops for women")
        queries.append("casual everyday layering tops")
        queries.append("oversized knit pullovers women")
        if clean_vendor:
            queries.append(f"{clean_vendor} women's tops blouses")
        queries.append("boutique fall clothing for women")
    elif domain == "outerwear":
        feature = attributes.get("outerwear_clothing_features") or "pockets"
        if isinstance(feature, list): feature = feature[0]
        queries.append("women's boutique jackets coats")
        queries.append("stylish casual outerwear women")
        queries.append("cozy fall winter jackets for women")
        queries.append("trendy button front shackets women")
        if clean_vendor:
            queries.append(f"{clean_vendor} women's jackets")
    elif domain == "one_piece":
        op_style = attributes.get("one_piece_style") or "romper"
        if isinstance(op_style, list): op_style = op_style[0]
        queries.append(f"women's {op_style.lower()} outfits")
        queries.append("chic casual jumpsuits for women")
        queries.append("summer boutique rompers women")
        if clean_vendor:
            queries.append(f"{clean_vendor} {op_style.lower()}")
    elif domain == "handbags":
        queries.append("women's boutique crossbody handbags")
        queries.append("stylish shoulder bags for women")
        queries.append("everyday leather totes and purses")
        queries.append("chic designer quality bags women")
    else:
        queries.append("women's boutique apparel usa")
        queries.append("trendy women's casual fashion")
        queries.append("flattering stylish clothing for women")

    # Add general high-converting US boutique keywords
    queries.append("free us shipping boutique clothing")
    
    # Deduplicate and clean queries
    seen = set()
    cleaned_queries = []
    for q in queries:
        q_norm = re.sub(r'\s+', ' ', q).strip().lower()
        if q_norm and q_norm not in seen:
            seen.add(q_norm)
            cleaned_queries.append(q[:100])

    boost_queries = cleaned_queries[:10]
    custom_keywords = [q[:100] for q in cleaned_queries[:5]]
    while len(custom_keywords) < 5:
        custom_keywords.append(clean_title[:100])
        
    return boost_queries, custom_keywords

# --- Local Heuristics / Rules Fallback ---

def parse_with_heuristics(title, desc, category_name="", product_type=""):
    """Locally extract attributes using category/domain aware rules if AI is limited."""
    text = f"{title} {desc}".lower()
    domain = classify_product_domain(product_type, category_name, title)
    
    # 1. Color matching (all domains)
    color = None
    colors = ["black", "white", "red", "blue", "green", "navy", "grey", "gray", "charcoal", 
              "cream", "ivory", "sage", "pink", "olive", "floral", "leopard", "paisley", "denim", 
              "khaki", "burgundy", "camel", "taupe", "rust", "tan", "mustard", "coral", "lavender", 
              "mauve", "mocha", "brown", "beige", "tomate"]
    for c in colors:
        if c in text:
            color = c.capitalize()
            if color == "Grey": color = "Gray"
            break
            
    # 2. Fabric matching (clothing domains)
    fabric = None
    if domain != "handbags":
        matched_fabrics = []
        fabrics = ["linen", "cotton", "denim", "satin", "knit", "viscose", "velvet", "polyester", 
                   "acrylic", "wool", "rayon", "spandex", "elastane", "french terry", "chiffon", "silk", "modal", "fleece"]
        for f in fabrics:
            if f in text:
                matched_fabrics.append(f.capitalize())
        fabric = matched_fabrics if matched_fabrics else None

    # 3. Care instructions (clothing domains)
    care_instructions = None
    if domain != "handbags":
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

    # 4. Clothing features (clothing domains)
    clothing_features = None
    if domain != "handbags":
        matched_features = []
        if any(k in text for k in ["stretch", "stretchy", "spandex", "elastane"]):
            matched_features.append("Stretchable")
        if "tummy control" in text:
            matched_features.append("Tummy control")
        if "breathable" in text:
            matched_features.append("Breathable design")
        if "lightweight" in text:
            matched_features.append("Lightweight")
        if any(k in text for k in ["distressed", "destroyed"]):
            matched_features.append("Distressed")
        if "raw hem" in text:
            matched_features.append("Raw hem")
        if "acid wash" in text:
            matched_features.append("Acid wash")
        if "pocket" in text:
            matched_features.append("Pockets")
        clothing_features = matched_features if matched_features else None

    # Domain-specific extractions
    waist_rise = None
    pants_length_type = None
    fit = None
    dress_style = None
    skirt_length_type = None
    dress_occasion = None
    sleeve_length_type = None
    neckline = None
    outerwear_features = None
    one_piece_style = None
    bag_case_material = None
    carry_options = None
    accessory_size = None
    bag_case_closure = None
    bag_case_features = None
    bag_case_storage_features = None

    if domain == "pants_denim":
        # Rise
        if any(k in text for k in ["high rise", "high-rise", "high waist", "high-waisted"]):
            waist_rise = "High"
        elif any(k in text for k in ["mid rise", "mid-rise", "mid waist", "medium rise"]):
            waist_rise = "Mid"
        elif any(k in text for k in ["low rise", "low-rise", "low waist"]):
            waist_rise = "Low"
        elif "ultra high" in text:
            waist_rise = "Ultra high"
        else:
            waist_rise = "High"
            
        # Fit
        if any(k in text for k in ["wide leg", "wide-leg", "wide"]):
            fit = "Wide"
        elif any(k in text for k in ["flare", "flared", "bell bottom"]):
            fit = "Flare"
        elif any(k in text for k in ["bootcut", "boot cut", "boot-cut"]):
            fit = "Bootcut"
        elif any(k in text for k in ["straight leg", "straight-leg", "straight"]):
            fit = "Straight"
        elif any(k in text for k in ["skinny", "tight fit"]):
            fit = "Skinny"
        elif any(k in text for k in ["boyfriend", "relaxed fit", "slouchy"]):
            fit = "Relaxed"
        elif "cargo" in text:
            fit = "Cargo"
        elif "mom" in text:
            fit = "Mom"
        elif "oversized" in text:
            fit = "Oversized"
        elif "regular" in text:
            fit = "Regular"
            
        # Length
        if any(k in text for k in ["cropped", "crop"]):
            pants_length_type = "Cropped"
        elif any(k in text for k in ["ankle", "ankle length"]):
            pants_length_type = "Ankle"
        elif any(k in text for k in ["capri", "capris"]):
            pants_length_type = "Capris"
        else:
            pants_length_type = "Long"

    elif domain == "dresses":
        # Style
        if "a-line" in text or "a line" in text:
            dress_style = "A-line"
        elif "shift" in text:
            dress_style = "Shift"
        elif "babydoll" in text:
            dress_style = "Babydoll"
        elif "slip" in text:
            dress_style = "Slip"
        elif "wrap" in text:
            dress_style = "Wrap"
        elif "maxi" in text:
            dress_style = "Maxi"
        elif "midi" in text:
            dress_style = "Midi"
            
        # Skirt length
        if "mini" in text:
            skirt_length_type = "Mini"
        elif "midi" in text:
            skirt_length_type = "Midi"
        elif "maxi" in text:
            skirt_length_type = "Maxi"
        elif "knee length" in text or "knee-length" in text:
            skirt_length_type = "Knee"
            
        # Neckline
        if "v-neck" in text or "v neck" in text:
            neckline = "V-neck"
        elif "round neck" in text or "round-neck" in text:
            neckline = "Round"
        elif "halter" in text:
            neckline = "Halter"
        elif "mock neck" in text or "mock-neck" in text:
            neckline = "Mock"
        elif "square neck" in text or "square" in text:
            neckline = "Square"
        elif "sweetheart" in text:
            neckline = "Sweetheart"
            
        # Sleeve
        if "sleeveless" in text:
            sleeve_length_type = "Sleeveless"
        elif "short sleeve" in text or "short-sleeve" in text:
            sleeve_length_type = "Short"
        elif "long sleeve" in text or "long-sleeve" in text:
            sleeve_length_type = "Long"
        elif "spaghetti strap" in text:
            sleeve_length_type = "Spaghetti strap"
            
        # Occasion
        matched_occ = []
        if "casual" in text: matched_occ.append("Casual")
        if "party" in text or "cocktail" in text: matched_occ.append("Party")
        if "formal" in text: matched_occ.append("Formal")
        if "everyday" in text or "daily" in text: matched_occ.append("Everyday")
        dress_occasion = matched_occ if matched_occ else ["Everyday"]

    elif domain == "tops_sweaters":
        # Sleeve
        if "sleeveless" in text:
            sleeve_length_type = "Sleeveless"
        elif "short sleeve" in text or "short-sleeve" in text:
            sleeve_length_type = "Short"
        elif "long sleeve" in text or "long-sleeve" in text:
            sleeve_length_type = "Long"
        elif "3/4 sleeve" in text or "three quarter" in text:
            sleeve_length_type = "3/4"
        elif "puff" in text:
            sleeve_length_type = "Puff"
            
        # Neckline
        if "v-neck" in text or "v neck" in text:
            neckline = "V-neck"
        elif "round neck" in text or "round-neck" in text:
            neckline = "Round"
        elif "crew neck" in text or "crew-neck" in text:
            neckline = "Crew"
        elif "mock neck" in text or "mock-neck" in text:
            neckline = "Mock"
        elif "turtle" in text or "turtleneck" in text:
            neckline = "Turtle"
            
        # Fit
        if "oversized" in text or "oversize" in text:
            fit = "Oversized"
        elif "relaxed" in text:
            fit = "Relaxed"
        elif "slim" in text:
            fit = "Slim"

    elif domain == "outerwear":
        matched_of = []
        if "pocket" in text: matched_of.append("Pockets")
        if "button" in text: matched_of.append("Button front")
        if "zip" in text or "zipper" in text: matched_of.append("Zipper front")
        if "hood" in text or "hooded" in text: matched_of.append("Hooded")
        if "belt" in text: matched_of.append("Belted")
        if "water resistant" in text or "waterproof" in text: matched_of.append("Water resistant")
        outerwear_features = matched_of if matched_of else ["Pockets"]
        sleeve_length_type = "Long"

    elif domain == "one_piece":
        if "romper" in text:
            one_piece_style = "Romper"
        elif "jumpsuit" in text:
            one_piece_style = "Jumpsuit"
        elif "overall" in text:
            one_piece_style = "Overall"
        else:
            one_piece_style = "Jumpsuit"

    elif domain == "handbags":
        if "leather" in text:
            bag_case_material = ["Faux leather" if any(k in text for k in ["faux", "vegan", "pu"]) else "Leather"]
        elif "nylon" in text:
            bag_case_material = ["Nylon"]
        elif "canvas" in text:
            bag_case_material = ["Canvas"]
        elif "straw" in text:
            bag_case_material = ["Straw"]
            
        co = []
        if "crossbody" in text or "cross-body" in text: co.append("Crossbody strap")
        if "shoulder" in text: co.append("Shoulder strap")
        if "tote" in text or "top handle" in text: co.append("Top handle")
        if "wristlet" in text: co.append("Wristlet")
        if "clutch" in text: co.append("Clutch")
        carry_options = co if co else None
        
        closures = ["zipper", "zip", "magnetic", "flap", "snap", "buckle", "open top"]
        for cl in closures:
            if cl in text:
                bag_case_closure = "Zipper" if cl in ["zipper", "zip"] else cl.capitalize()
                break
                
        bf = []
        if "water resistant" in text or "waterproof" in text: bf.append("Water resistant")
        if "lightweight" in text: bf.append("Lightweight")
        if "adjustable strap" in text: bf.append("Adjustable strap")
        bag_case_features = bf if bf else None
        
        if "mini" in text: accessory_size = "Mini"
        elif "small" in text: accessory_size = "Small"
        elif "medium" in text: accessory_size = "Medium"
        elif "large" in text: accessory_size = "Large"
        else: accessory_size = "One Size"

    return {
        "color": color,
        "fabric": fabric,
        "waist_rise": waist_rise,
        "pants_length_type": pants_length_type,
        "fit": fit,
        "outerwear_clothing_features": outerwear_features,
        "one_piece_style": one_piece_style,
        "target_gender": "Female" if domain != "handbags" else None,
        "age_group": "Adults" if domain != "handbags" else None,
        "dress_style": dress_style,
        "neckline": neckline,
        "skirt_length_type": skirt_length_type,
        "sleeve_length_type": sleeve_length_type,
        "care_instructions": care_instructions,
        "clothing_features": clothing_features,
        "dress_occasion": dress_occasion,
        "bag_case_material": bag_case_material,
        "carry_options": carry_options,
        "accessory_size": accessory_size,
        "bag_case_closure": bag_case_closure,
        "bag_case_features": bag_case_features,
        "bag_case_storage_features": bag_case_storage_features
    }

def get_extracted_attributes(title, desc, category_name="", product_type=""):
    """Run AI first; if it returns None, instantly run local heuristics."""
    category_label = category_name if category_name else (product_type if product_type else "Clothing")
    domain = classify_product_domain(product_type, category_name, title)
    
    prompt = f"""Analyze this product's title and description for a US women's boutique store:
Title: {title}
Description: {desc}
Category: {category_label}
Domain: {domain}

Identify standard attributes present in the text. Return category-appropriate values only (e.g. waist_rise/fit/pants_length_type for pants/jeans; dress_style/neckline/skirt_length_type for dresses; handbag attributes only for bags).
Attributes and allowed values:
1. target_gender (values: Female, Male, Unisex) - Default Female for women's clothing
2. age_group (values: Adults, Kids, Teens, Universal) - Default Adults
3. color (e.g. Navy, Sage, Floral, Denim, Black, White, Cream)
4. fabric (e.g. Denim, Cotton, Linen, French terry, Viscose, Polyester, Spandex) - list or string
5. waist_rise (values: High, Mid, Low, Ultra high) - for pants/jeans
6. pants_length_type (values: Long, Cropped, Ankle, Capris) - for pants/jeans
7. fit (values: Wide, Flare, Bootcut, Straight, Skinny, Relaxed, Cargo, Oversized, Regular, Slim) - for pants/jeans or tops
8. sleeve_length_type (values: Short, Long, Sleeveless, Spaghetti strap, 3/4, Cap, Puff, Strapless) - list or string
9. neckline (values: V-neck, Round, Crew, Mock, Halter, Square, Sweetheart, Turtle, Boat)
10. dress_style (values: A-line, Babydoll, Shift, Slip, Wrap, Maxi, Midi, Tiered, Sweater, Tank)
11. skirt_length_type (values: Mini, Midi, Maxi, Knee)
12. dress_occasion (values: Everyday, Casual, Party, Formal, Wedding, Cocktail) - list or string
13. outerwear_clothing_features (values: Pockets, Button front, Zipper front, Hooded, Belted, Water resistant) - list or string
14. one_piece_style (values: Jumpsuit, Romper, Overall)
15. care_instructions (values: Machine washable, Tumble dry, Hand wash, Dry clean only) - list or string
16. clothing_features (values: Stretchable, Tummy control, Pockets, Breathable design, Lightweight, Distressed, Raw hem, Acid wash) - list or string
17. bag_case_material (values: Leather, Faux leather, Canvas, Nylon, Straw) - for bags only
18. carry_options (values: Crossbody strap, Shoulder strap, Top handle, Wristlet, Clutch) - for bags only
19. accessory_size (values: One Size, Mini, Small, Medium, Large) - for bags only
20. bag_case_closure (values: Zipper, Magnetic, Snap, Flap, Open top) - for bags only
21. bag_case_features (values: Water resistant, Lightweight, Adjustable strap, Detachable strap) - for bags only
22. bag_case_storage_features (values: Inner pockets, Card slots, Laptop compartment) - for bags only

Return ONLY a valid JSON object. If you cannot identify a value, use null.
"""
    try:
        print("  Calling AI for attribute extraction...")
        ai_resp = generate(prompt, max_tokens=300, temperature=0.2)
        if ai_resp:
            match = re.search(r'\{[\s\S]*\}', ai_resp)
            if match:
                parsed = json.loads(match.group(0))
                print("  ✓ AI Extraction successful.")
                return parsed
    except Exception as e:
        print(f"  [Warning] AI extraction failed or rate-limited: {e}")
        
    print("  ⚠ Falling back to Local Heuristics parser...")
    return parse_with_heuristics(title, desc, category_name, product_type)

# --- Variant Image Matcher ---

def find_matching_image(variant_title, options, product_media, unique_colors=None):
    """Find a product media image matching variant color option."""
    color_val = None
    for opt in options:
        name_lower = opt["name"].lower()
        if "color" in name_lower or "colour" in name_lower:
            color_val = opt["value"].lower().strip()
            break
            
    if not color_val:
        return None
        
    for media_edge in product_media.get("edges", []):
        m = media_edge["node"]
        if m.get("mediaContentType") != "IMAGE":
            continue
        m_id = m["id"]
        alt = (m.get("alt") or "").lower()
        url = (m.get("image", {}).get("url") or "").lower()
        
        filename = url.split("/")[-1].split("?")[0]
        if color_val in alt or color_val.replace(" ", "-") in filename or color_val.replace(" ", "_") in filename:
            return m_id
            
    if unique_colors and len(unique_colors) == 1:
        for media_edge in product_media.get("edges", []):
            m = media_edge["node"]
            if m.get("mediaContentType") == "IMAGE":
                return m["id"]
            
    return None

def get_batch_extracted_attributes(products_info):
    """Query AI with a batch of products to extract category-specific metafields."""
    if not products_info:
        return {}

    formatted_products = []
    for p in products_info:
        desc_snippet = p["description"][:300] if p["description"] else ""
        formatted_products.append(
            f"Product ID: {p['id']}\n"
            f"Title: {p['title']}\n"
            f"Category: {p['category']}\n"
            f"Product Type: {p.get('product_type', '')}\n"
            f"Domain: {p.get('domain', '')}\n"
            f"Description: {desc_snippet}\n"
            f"---"
        )
    products_text = "\n".join(formatted_products)

    prompt = f"""You are an expert product data taxonomist for a US women's boutique fashion store.
Analyze the following products and extract standard attributes based on each product's Domain:
- Pants/Jeans domain: extract waist_rise (High, Mid, Low), fit (Wide, Flare, Bootcut, Straight, Skinny, Relaxed, Cargo), pants_length_type (Long, Cropped, Ankle, Capris), fabric, clothing_features (Stretchable, Tummy control, Distressed, Raw hem). DO NOT return dress or handbag fields.
- Dresses domain: extract dress_style (Maxi, Midi, Mini, A-line, Wrap, Slip, Babydoll), neckline, skirt_length_type, dress_occasion, sleeve_length_type, fabric. DO NOT return pants or handbag fields.
- Tops/Sweaters domain: extract sleeve_length_type, neckline, fit (Oversized, Relaxed, Slim), fabric, clothing_features.
- Outerwear domain: extract outerwear_clothing_features (Pockets, Button front, Zipper front, Hooded, Belted), sleeve_length_type, fabric.
- One-Piece domain: extract one_piece_style (Jumpsuit, Romper, Overall), neckline, sleeve_length_type.
- Handbags domain: extract bag_case_material, carry_options, accessory_size, bag_case_closure, bag_case_features.

Products:
{products_text}

Return ONLY a valid JSON object mapping Product ID to its identified attributes dictionary. Use null for non-applicable or missing keys.
"""
    try:
        print(f"Calling AI for batch attribute extraction of {len(products_info)} product(s)...")
        max_tokens = max(500, len(products_info) * 350)
        ai_resp = generate(prompt, max_tokens=max_tokens, temperature=0.2)
        if ai_resp:
            match = re.search(r'\{[\s\S]*\}', ai_resp)
            if match:
                parsed = json.loads(match.group(0))
                print("✓ Batch AI Extraction successful.")
                return parsed
    except Exception as e:
        print(f"[Warning] Batch AI extraction failed or rate-limited: {e}")

    return {}

# --- Main Product Automation Logic ---

def process_product(product, dry_run=True, skip_ai=False, pre_extracted_attrs=None, force=False):
    """Process a single product: extract taxonomy metafields, SEO search boost queries, and variant images."""
    p_id = product["id"]
    p_title = product["title"]
    p_handle = product["handle"]
    desc = product["descriptionHtml"] or ""
    product_type = product.get("productType") or ""
    vendor = product.get("vendor") or ""
    category_name = product.get("category", {}).get("name") if product.get("category") else None
    domain = classify_product_domain(product_type, category_name, p_title)
    
    print(f"\nProcessing product: {p_title} (Handle: {p_handle}, Type: '{product_type}', Domain: '{domain}')")
    
    category_id = product.get("category", {}).get("id") if product.get("category") else None
    if category_id and category_id not in loaded_categories:
        loaded_categories.add(category_id)
        cat_std_vals = load_standard_category_values(category_id)
        standard_values_cache.update(cat_std_vals)
        print(f"  Loaded {len(cat_std_vals)} standard values for category '{product['category']['name']}'.")

    # Map existing metafields on product to avoid unnecessary overwrites
    existing_metafields = {}
    for m_edge in product.get("metafields", {}).get("edges", []):
        m = m_edge.get("node", {})
        if m.get("namespace") and m.get("key") and m.get("value"):
            existing_metafields[(m["namespace"], m["key"])] = m["value"]

    suggestions = {
        "product_id": p_id,
        "title": p_title,
        "handle": p_handle,
        "domain": domain,
        "metafields": [],
        "variants": []
    }
    
    # 1. Fetch AI/Local Category Metafields
    if skip_ai:
        print(f"  - Core category metafields already populated for '{p_title}'. Skipping AI/heuristics attribute extraction.")
        attrs = {}
    elif pre_extracted_attrs is not None:
        print(f"  - Using pre-extracted attributes from batch AI call.")
        attrs = pre_extracted_attrs
    else:
        attrs = get_extracted_attributes(p_title, desc, category_name, product_type)
    print(f"  Extracted Attributes: {attrs}")
    
    # Map to standard taxonomy metafield list
    for key, val in attrs.items():
        if not val:
            continue
        
        mapping = TAXONOMY_MAP.get(key)
        if not mapping:
            continue
            
        std_key = mapping["key"]
        mo_type = mapping["type"]
        
        # Check if already populated on product
        if ("shopify", std_key) in existing_metafields and not force:
            print(f"  - shopify.{std_key} already set on product. Skipping.")
            continue
        
        # Check if definition exists on store
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

    # 2. Add Search Boost Queries & Custom Search Keywords for US Women Shoppers
    boost_queries, custom_kw = generate_product_seo_keywords(p_title, desc, domain, vendor, attrs)
    
    if ("shopify--discovery--product_search_boost", "queries") not in existing_metafields or force:
        suggestions["metafields"].append({
            "namespace": "shopify--discovery--product_search_boost",
            "key": "queries",
            "value": json.dumps(boost_queries),
            "type": "list.single_line_text_field"
        })
        print(f"  ✓ Added {len(boost_queries)} Shopify Discovery Search Boost Queries")

    kw_keys = [
        ("custom", "search_keyword_1"),
        ("custom", "search-keyword_2"),
        ("custom", "search-keyword_3"),
        ("custom", "search-keyword_4"),
        ("custom", "search-keyword_5")
    ]
    for (ns, k), kw_val in zip(kw_keys, custom_kw):
        if (ns, k) not in existing_metafields or force:
            suggestions["metafields"].append({
                "namespace": ns,
                "key": k,
                "value": str(kw_val)[:100],
                "type": "single_line_text_field"
            })
            print(f"  ✓ Added SEO keyword {ns}.{k} = '{kw_val}'")
            
    # 3. Check Variant Images
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
    query = f"""
    query GetBackupInfo($ids: [ID!]!) {{
      nodes(ids: $ids) {{
        ... on Product {{
          id
          title
          handle
          {METAFIELDS_QUERY_FRAGMENT}
          variants(first: 100) {{
            edges {{
              node {{
                id
                media(first: 1) {{
                  nodes {{
                    id
                  }}
                }}
              }}
            }}
          }}
        }}
      }}
    }}
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
    parser.add_argument("--scope", choices=["both", "products", "collections"], default="both", help="Execution scope: 'both', 'products', or 'collections'")
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

    col_stats = {"total_collections": 0, "updated_collections": 0, "skipped_collections": 0}
    
    # Run Collections SEO & Metafields if scope is 'collections' or 'both'
    if args.scope in ["both", "collections"] and not args.handle:
        try:
            import bulk_update_collection_seo
            print("\n==================================================")
            print("Running Collection SEO & PAA Accordions Update...")
            print("==================================================")
            res_col = bulk_update_collection_seo.update_all_collections(dry_run=args.diagnose, force=args.full or args.weekly)
            if isinstance(res_col, dict):
                col_stats.update(res_col)
        except Exception as e:
            print(f"  [Collection SEO Notice]: {e}")

    # If scope is 'collections' and no handle specified, we're done
    if args.scope == "collections" and not args.handle:
        print("\nCollection scope run complete.")
        summary_data = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "action": "diagnose" if args.diagnose else "apply",
            "mode": "force" if args.full else ("weekly" if args.weekly else "daily"),
            "scope": args.scope,
            "batch_index": args.batch_index,
            "products_fetched": 0,
            "products_processed": 0,
            "products_updated": 0,
            "collection_stats": col_stats,
            "metafields_by_type": {}
        }
        with open("category_metafields_summary.json", "w", encoding="utf-8") as f:
            json.dump(summary_data, f, indent=2)
        return
    
    # Determine scan list
    products = []
    if args.handle:
        print(f"Loading single product or collection with handle: {args.handle}")
        prod = get_product_by_handle(args.handle)
        if prod:
            if args.scope in ["both", "products"]:
                products.append(prod)
            else:
                print(f"Handle '{args.handle}' is a Product, but scope is 'collections'. Skipping.")
                return
        else:
            col, col_prods = get_collection_products_by_handle(args.handle)
            if col and col_prods:
                print(f"✓ Smart Match: '{args.handle}' is a Collection ({col['title']}). Loaded {len(col_prods)} products for category metafield updates.")
                if args.scope in ["both", "products"]:
                    products.extend(col_prods)
                
                # Run Collection SEO & PAA Accordion update for this collection
                if args.scope in ["both", "collections"]:
                    try:
                        import bulk_update_collection_seo
                        print(f"✓ Running Collection SEO & PAA updates for '{col['title']}'...")
                        res_col = bulk_update_collection_seo.update_all_collections(target_handle=args.handle, dry_run=args.diagnose, force=args.full or args.weekly)
                        if isinstance(res_col, dict):
                            col_stats.update(res_col)
                    except Exception as e:
                        print(f"  [Collection SEO Notice]: {e}")
                
                if args.scope == "collections":
                    print(f"\nCollection '{col['title']}' update complete.")
                    return
            else:
                print(f"Error: Handle '{args.handle}' is neither a valid Product handle nor a Collection handle.")
                sys.exit(1)
    elif args.query:
        clean_query = args.query.strip().strip('"').strip("'")
        print(f"Loading products matching query: {clean_query}")
        products = get_products_by_query(clean_query)
        print(f"Fetched {len(products)} products.")
    elif args.full:
        print("Loading full store catalog...")
        products = get_all_products()
        print(f"Fetched {len(products)} products.")
    elif args.weekly:
        seven_days_ago = (time.time() - (7 * 24 * 3600))
        seven_days_ago_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(seven_days_ago))
        print(f"Loading products created since: {seven_days_ago_iso}")
        products = get_recent_products(seven_days_ago_iso, query_field="created_at")
        print(f"Fetched {len(products)} recently created products.")
    else:
        yesterday = (time.time() - (24 * 3600))
        yesterday_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(yesterday))
        print(f"Loading products created since: {yesterday_iso}")
        products = get_recent_products(yesterday_iso, query_field="created_at")
        print(f"Fetched {len(products)} recently created products.")

    if not products:
        print("No products found to process.")
        summary_data = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "action": "diagnose" if args.diagnose else "apply",
            "mode": "force" if args.full else ("weekly" if args.weekly else "daily"),
            "scope": args.scope,
            "batch_index": args.batch_index,
            "products_fetched": 0,
            "products_processed": 0,
            "products_updated": 0,
            "collection_stats": col_stats,
            "metafields_by_type": {}
        }
        with open("category_metafields_summary.json", "w", encoding="utf-8") as f:
            json.dump(summary_data, f, indent=2)
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

        metafield_edges = p.get("metafields", {}).get("edges", []) if p.get("metafields") else []
        existing_keys = {
            m.get("node", {}).get("key") 
            for m in metafield_edges 
            if m.get("node", {}).get("value")
        }
        
        # Determine essential keys for product domain
        p_type = p.get("productType") or ""
        cat_name = p.get("category", {}).get("name") if p.get("category") else ""
        domain = classify_product_domain(p_type, cat_name, p["title"])
        
        domain_essential_keys = {"color-pattern", "fabric"}
        if domain == "pants_denim":
            domain_essential_keys.update({"waist-rise", "fit", "pants-length-type"})
        elif domain == "dresses":
            domain_essential_keys.update({"dress-style", "skirt-dress-length-type", "neckline"})
        elif domain == "tops_sweaters":
            domain_essential_keys.update({"sleeve-length-type", "neckline"})
        elif domain == "outerwear":
            domain_essential_keys.update({"outerwear-clothing-features"})
        elif domain == "one_piece":
            domain_essential_keys.update({"one-piece-style"})
        elif domain == "handbags":
            domain_essential_keys = {"bag-case-material", "carry-options", "accessory-size"}
            
        has_search_boost = "queries" in existing_keys
        is_complete = domain_essential_keys.issubset(existing_keys) and has_search_boost
        skip_ai = is_complete and not args.full and not args.handle and not args.query
        products_to_process.append((p, skip_ai))
        
        if not skip_ai:
            desc_html = p.get("descriptionHtml") or ""
            desc_clean = re.sub(r'<[^>]*>', '', desc_html).strip()
            desc_clean = re.sub(r'\s+', ' ', desc_clean)
            products_needing_ai.append({
                "id": p_id,
                "title": p["title"],
                "description": desc_clean[:300],
                "category": cat_name if cat_name else (p_type if p_type else "Clothing"),
                "product_type": p_type,
                "domain": domain
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
    metafield_type_counts = {}
    
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
                p_type = p.get("productType") or ""
                p_pre_extracted = parse_with_heuristics(title, desc_html, category_name, p_type)
                
        s = process_product(p, dry_run=args.diagnose, skip_ai=skip_ai, pre_extracted_attrs=p_pre_extracted, force=args.full)
        processed_ids.add(p_id)
        if s["metafields"] or s["variants"]:
            all_suggestions.append(s)
            for mf in s["metafields"]:
                key_name = f"{mf['namespace']}.{mf['key']}"
                metafield_type_counts[key_name] = metafield_type_counts.get(key_name, 0) + 1
            
    summary_data = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "action": "diagnose" if args.diagnose else "apply",
        "mode": "force" if args.full else ("weekly" if args.weekly else "daily"),
        "scope": args.scope,
        "batch_index": args.batch_index,
        "products_fetched": len(products),
        "products_processed": len(processed_ids),
        "products_updated": len(all_suggestions),
        "collection_stats": col_stats,
        "metafields_by_type": metafield_type_counts
    }
    with open("category_metafields_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary_data, f, indent=2)

    if not all_suggestions:
        print("\nNo metadata or variant image updates are needed.")
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
        preview_file = "category_metafields_preview.json"
        with open(preview_file, "w", encoding="utf-8") as f:
            json.dump(all_suggestions, f, indent=2)
        print(f"\nDiagnostics preview written to '{preview_file}'.")
        print("To apply these changes, run: python automate_category_metafields.py --apply " + 
              (f"--handle {args.handle}" if args.handle else ""))
        
    elif args.apply:
        target_ids = [s["product_id"] for s in all_suggestions]
        print(f"\nBacking up current state of {len(target_ids)} products before applying changes...")
        backup_data = fetch_current_metafields_and_variants(target_ids)
        
        with open(args.backup_file, "w", encoding="utf-8") as f:
            json.dump(backup_data, f, indent=2)
        print(f"Backup written to '{args.backup_file}'.")
        
        for s in all_suggestions:
            apply_product_updates(s)
        print("\nAll updates applied successfully.")

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

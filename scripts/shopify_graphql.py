import os, sys, requests, time, re
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from secrets_manager import inject_to_env, get_secret
inject_to_env()

STORE = get_secret("SHOPIFY_STORE")
TOKEN = get_secret("SHOPIFY_ACCESS_TOKEN")
HEADS = {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}
BASE_URL = f"https://{STORE}/admin/api/2024-01/graphql.json"

def run_graphql(query: str, variables: Optional[Dict] = None) -> Dict:
    """Run GraphQL Admin API query with rate-limiting retry."""
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
    
    for attempt in range(5):
        try:
            resp = requests.post(BASE_URL, headers=HEADS, json=payload, timeout=30)
            if resp.status_code == 429:
                retry_after = float(resp.headers.get("Retry-After", 2.0))
                time.sleep(retry_after)
                continue
            resp.raise_for_status()
            result = resp.json()
            if "errors" in result:
                # Log errors but return result socaller can handle
                print(f"[GraphQL] Errors in response: {result['errors']}", file=sys.stderr)
            return result
        except requests.exceptions.RequestException as e:
            if attempt < 4:
                time.sleep(2.0 ** attempt)
            else:
                raise e
    raise RuntimeError("GraphQL request failed after 5 attempts")

def parse_gid(gid: str) -> int:
    """Extract integer ID from Shopify GID string."""
    if not gid:
        return 0
    match = re.search(r'/(\d+)$', gid)
    return int(match.group(1)) if match else 0

def fetch_products_graphql(hours: int = 0, query_by_updated: bool = True) -> List[Dict]:
    """Fetch all active products with their json_ld_schema metafield using GraphQL."""
    query = """
    query ($first: Int!, $after: String, $queryStr: String) {
      products(first: $first, after: $after, query: $queryStr) {
        pageInfo { hasNextPage endCursor }
        edges {
          node {
            id
            title
            handle
            vendor
            productType
            createdAt
            updatedAt
            bodyHtml
            status
            media(first: 100) {
              edges {
                node {
                  id
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
                  sku
                  price
                  barcode
                  inventoryQuantity
                  selectedOptions {
                    name
                    value
                  }
                  image {
                    id
                  }
                }
              }
            }
            metafield(namespace: "json_ld_schema", key: "product") {
              id
              namespace
              key
              value
            }
            title_tag: metafield(namespace: "global", key: "title_tag") {
              id
              namespace
              key
              value
            }
            description_tag: metafield(namespace: "global", key: "description_tag") {
              id
              namespace
              key
              value
            }
          }
        }
      }
    }
    """
    
    query_parts = ["status:active"]
    if hours > 0:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime('%Y-%m-%dT%H:%M:%SZ')
        if query_by_updated:
            # Check both created_at and updated_at to be safe (fixer uses updated_at, validator uses created_at)
            query_parts.append(f"(created_at:>='{cutoff}' OR updated_at:>='{cutoff}')")
        else:
            # Only query by created_at (daily/weekly SEO mode to catch new dropship imports)
            query_parts.append(f"created_at:>='{cutoff}'")
    
    query_str = " AND ".join(query_parts)
    
    products = []
    has_next = True
    cursor = None
    
    while has_next:
        variables = {"first": 100, "after": cursor, "queryStr": query_str}
        res = run_graphql(query, variables)
        data = res.get("data", {}).get("products", {})
        
        for edge in data.get("edges", []):
            node = edge["node"]
            
            # Map GraphQL node to REST product structure
            metafield = node.get("metafield")
            metafields_list = []
            if metafield:
                metafields_list.append({
                    "id": parse_gid(metafield["id"]),
                    "namespace": metafield["namespace"],
                    "key": metafield["key"],
                    "value": metafield["value"]
                })
            for k in ["title_tag", "description_tag"]:
                m = node.get(k)
                if m:
                    metafields_list.append({
                        "id": parse_gid(m["id"]),
                        "namespace": m["namespace"],
                        "key": m["key"],
                        "value": m["value"]
                    })
                
            # Determine overall availability from variants
            has_stock = any(v.get("node", {}).get("inventoryQuantity", 0) > 0 for v in node["variants"]["edges"])
            
            products.append({
                "id": parse_gid(node["id"]),
                "title": node["title"],
                "handle": node["handle"],
                "vendor": node["vendor"] or "Trendsi",
                "product_type": node.get("productType") or "",
                "created_at": node["createdAt"],
                "updated_at": node["updatedAt"],
                "body_html": node["bodyHtml"] or "",
                "available": has_stock,
                "images": [
                     {
                         "id": parse_gid(img["node"]["id"]),
                         "src": img["node"]["image"]["url"] if img["node"].get("image") else ""
                     }
                     for img in node["media"]["edges"]
                     if img["node"].get("mediaContentType") == "IMAGE"
                 ],
                "variants": [
                    {
                        "id": parse_gid(v["node"]["id"]),
                        "sku": v["node"]["sku"] or "",
                        "price": v["node"]["price"],
                        "barcode": v["node"]["barcode"] or "",
                        "inventory_quantity": v["node"].get("inventoryQuantity", 0),
                        "option1": v["node"]["selectedOptions"][0]["value"] if v["node"].get("selectedOptions") and len(v["node"]["selectedOptions"]) > 0 else None,
                        "option2": v["node"]["selectedOptions"][1]["value"] if v["node"].get("selectedOptions") and len(v["node"]["selectedOptions"]) > 1 else None,
                        "option3": v["node"]["selectedOptions"][2]["value"] if v["node"].get("selectedOptions") and len(v["node"]["selectedOptions"]) > 2 else None,
                        "image_id": parse_gid(v["node"]["image"]["id"]) if v["node"].get("image") else None
                    }
                    for v in node["variants"]["edges"]
                ],
                "metafields": metafields_list
            })
            
        page_info = data.get("pageInfo", {})
        has_next = page_info.get("hasNextPage", False)
        cursor = page_info.get("endCursor")
        
    return products

def fetch_collections_graphql(hours: int = 0) -> List[Dict]:
    """Fetch custom and smart collections with their json_ld_schema metafield."""
    query = """
    query ($first: Int!, $after: String, $queryStr: String) {
      collections(first: $first, after: $after, query: $queryStr) {
        pageInfo { hasNextPage endCursor }
        edges {
          node {
            id
            title
            handle
            updatedAt
            descriptionHtml
            metafield(namespace: "json_ld_schema", key: "collectionpage") {
              id
              namespace
              key
              value
            }
            title_tag: metafield(namespace: "global", key: "title_tag") {
              id
              namespace
              key
              value
            }
            description_tag: metafield(namespace: "global", key: "description_tag") {
              id
              namespace
              key
              value
            }
          }
        }
      }
    }
    """
    
    query_str = None
    if hours > 0:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime('%Y-%m-%dT%H:%M:%SZ')
        query_str = f"updated_at:>='{cutoff}'"
        
    collections = []
    has_next = True
    cursor = None
    
    while has_next:
        variables = {"first": 250, "after": cursor, "queryStr": query_str}
        res = run_graphql(query, variables)
        data = res.get("data", {}).get("collections", {})
        
        for edge in data.get("edges", []):
            node = edge["node"]
            
            metafield = node.get("metafield")
            metafields_list = []
            if metafield:
                metafields_list.append({
                    "id": parse_gid(metafield["id"]),
                    "namespace": metafield["namespace"],
                    "key": metafield["key"],
                    "value": metafield["value"]
                })
            for k in ["title_tag", "description_tag"]:
                m = node.get(k)
                if m:
                    metafields_list.append({
                        "id": parse_gid(m["id"]),
                        "namespace": m["namespace"],
                        "key": m["key"],
                        "value": m["value"]
                    })
                
            collections.append({
                "id": parse_gid(node["id"]),
                "title": node["title"],
                "handle": node["handle"],
                "body_html": node["descriptionHtml"] or "",
                "updated_at": node["updatedAt"],
                "metafields": metafields_list
            })
            
        page_info = data.get("pageInfo", {})
        has_next = page_info.get("hasNextPage", False)
        cursor = page_info.get("endCursor")
        
    return collections

def fetch_pages_graphql(hours: int = 0) -> List[Dict]:
    """Fetch pages with their json_ld_schema metafield."""
    query = """
    query ($first: Int!, $after: String, $queryStr: String) {
      pages(first: $first, after: $after, query: $queryStr) {
        pageInfo { hasNextPage endCursor }
        edges {
          node {
            id
            title
            handle
            updatedAt
            body
            metafield(namespace: "json_ld_schema", key: "webpage") {
              id
              namespace
              key
              value
            }
            title_tag: metafield(namespace: "global", key: "title_tag") {
              id
              namespace
              key
              value
            }
            description_tag: metafield(namespace: "global", key: "description_tag") {
              id
              namespace
              key
              value
            }
          }
        }
      }
    }
    """
    
    query_str = None
    if hours > 0:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime('%Y-%m-%dT%H:%M:%SZ')
        query_str = f"updated_at:>='{cutoff}'"
        
    pages = []
    has_next = True
    cursor = None
    
    while has_next:
        variables = {"first": 250, "after": cursor, "queryStr": query_str}
        res = run_graphql(query, variables)
        data = res.get("data", {}).get("pages", {})
        
        for edge in data.get("edges", []):
            node = edge["node"]
            
            metafield = node.get("metafield")
            metafields_list = []
            if metafield:
                metafields_list.append({
                    "id": parse_gid(metafield["id"]),
                    "namespace": metafield["namespace"],
                    "key": metafield["key"],
                    "value": metafield["value"]
                })
            for k in ["title_tag", "description_tag"]:
                m = node.get(k)
                if m:
                    metafields_list.append({
                        "id": parse_gid(m["id"]),
                        "namespace": m["namespace"],
                        "key": m["key"],
                        "value": m["value"]
                    })
                
            pages.append({
                "id": parse_gid(node["id"]),
                "title": node["title"],
                "handle": node["handle"],
                "body_html": node["body"] or "",
                "updated_at": node["updatedAt"],
                "metafields": metafields_list
            })
            
        page_info = data.get("pageInfo", {})
        has_next = page_info.get("hasNextPage", False)
        cursor = page_info.get("endCursor")
        
    return pages

def fetch_articles_graphql(hours: int = 0) -> List[Dict]:
    """Fetch blog articles with their json_ld_schema metafields from all blogs."""
    # 1. Fetch all blogs
    blogs_query = """
    query {
      blogs(first: 50) {
        edges {
          node {
            id
            handle
          }
        }
      }
    }
    """
    res = run_graphql(blogs_query)
    blog_edges = res.get("data", {}).get("blogs", {}).get("edges", [])
    
    articles_query = """
    query ($blogId: ID!, $first: Int!, $after: String) {
      node(id: $blogId) {
        ... on Blog {
          articles(first: $first, after: $after) {
            pageInfo { hasNextPage endCursor }
            edges {
              node {
                id
                title
                handle
                updatedAt
                publishedAt
                summary
                body
                author { name }
                image { url }
                metafield(namespace: "json_ld_schema", key: "blogposting") {
                  id
                  namespace
                  key
                  value
                }
                title_tag: metafield(namespace: "global", key: "title_tag") {
                  id
                  namespace
                  key
                  value
                }
                description_tag: metafield(namespace: "global", key: "description_tag") {
                  id
                  namespace
                  key
                  value
                }
              }
            }
          }
        }
      }
    }
    """
    
    all_articles = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours) if hours > 0 else None
    
    for blog_edge in blog_edges:
        blog_node = blog_edge["node"]
        blog_id = blog_node["id"]
        blog_handle = blog_node["handle"]
        
        has_next = True
        cursor = None
        
        while has_next:
            variables = {"blogId": blog_id, "first": 250, "after": cursor}
            a_res = run_graphql(articles_query, variables)
            data = a_res.get("data", {}).get("node", {}).get("articles", {})
            
            for edge in data.get("edges", []):
                node = edge["node"]
                
                # Filter by hours (updatedAt)
                if cutoff:
                    try:
                        updated_at = datetime.fromisoformat(node["updatedAt"].replace("Z", "+00:00"))
                        if updated_at < cutoff:
                            continue
                    except Exception:
                        pass
                
                metafield = node.get("metafield")
                metafields_list = []
                if metafield:
                    metafields_list.append({
                        "id": parse_gid(metafield["id"]),
                        "namespace": metafield["namespace"],
                        "key": metafield["key"],
                        "value": metafield["value"]
                    })
                for k in ["title_tag", "description_tag"]:
                    m = node.get(k)
                    if m:
                        metafields_list.append({
                            "id": parse_gid(m["id"]),
                            "namespace": m["namespace"],
                            "key": m["key"],
                            "value": m["value"]
                        })
                
                author_name = node.get("author", {}).get("name", "MeeeShop") if node.get("author") else "MeeeShop"
                image_src = node.get("image", {}).get("url", "") if node.get("image") else ""
                
                all_articles.append({
                    "id": parse_gid(node["id"]),
                    "title": node["title"],
                    "handle": node["handle"],
                    "body_html": node["body"] or "",
                    "excerpt_html": node["summary"] or "",
                    "published_at": node["publishedAt"] or "",
                    "updated_at": node["updatedAt"] or "",
                    "author": author_name,
                    "image": {"src": image_src} if image_src else None,
                    "blog_handle": blog_handle,
                    "blog_id": parse_gid(blog_id),
                    "metafields": metafields_list
                })
                
            page_info = data.get("pageInfo", {})
            has_next = page_info.get("hasNextPage", False)
            cursor = page_info.get("endCursor")
            
    return all_articles

def make_gid(resource_type: str, numeric_id: int) -> str:
    """Map REST resource type to GraphQL GID string."""
    type_map = {
        "product": "Product",
        "collection": "Collection",
        "page": "Page",
        "article": "Article"
    }
    gql_type = type_map.get(resource_type.lower(), resource_type.capitalize())
    return f"gid://shopify/{gql_type}/{numeric_id}"

def set_metafield_graphql(resource_type: str, resource_id: int, key: str, value_dict: dict) -> bool:
    """Set metafield for a resource using GraphQL Admin API."""
    import json
    owner_id = make_gid(resource_type, resource_id)
    value_str = json.dumps(value_dict, ensure_ascii=False)
    
    query = """
    mutation metafieldsSet($metafields: [MetafieldsSetInput!]!) {
      metafieldsSet(metafields: $metafields) {
        metafields {
          id
        }
        userErrors {
          field
          message
        }
      }
    }
    """
    
    variables = {
      "metafields": [
        {
          "ownerId": owner_id,
          "namespace": "json_ld_schema",
          "key": key,
          "type": "json",
          "value": value_str
        }
      ]
    }
    
    try:
        res = run_graphql(query, variables)
        errors = res.get("data", {}).get("metafieldsSet", {}).get("userErrors", [])
        if errors:
            print(f"[GraphQL] Errors setting metafield for {owner_id}: {errors}", file=sys.stderr)
            return False
        return True
    except Exception as e:
        print(f"[GraphQL] Exception setting metafield for {owner_id}: {e}", file=sys.stderr)
        return False

def delete_metafield_graphql(metafield_id: int) -> bool:
    """Delete a metafield using GraphQL Admin API."""
    gid = f"gid://shopify/Metafield/{metafield_id}"
    query = """
    mutation metafieldDelete($input: MetafieldDeleteInput!) {
      metafieldDelete(input: $input) {
        deletedId
        userErrors {
          field
          message
        }
      }
    }
    """
    
    variables = {
      "input": {
        "id": gid
      }
    }
    
    try:
        res = run_graphql(query, variables)
        errors = res.get("data", {}).get("metafieldDelete", {}).get("userErrors", [])
        if errors:
            print(f"[GraphQL] Errors deleting metafield {gid}: {errors}", file=sys.stderr)
            return False
        return True
    except Exception as e:
        print(f"[GraphQL] Exception deleting metafield {gid}: {e}", file=sys.stderr)
        return False


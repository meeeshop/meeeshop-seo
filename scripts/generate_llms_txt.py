#!/usr/bin/env python3
"""
generate_llms_txt.py — AEO & GEO Markdown Generator for ChatGPT / Perplexity
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Fetches products, collections, and blog articles from Shopify and generates
standardized /llms.txt and /llms-full.txt Markdown files for AI search agents.
"""

import os
import sys
import json
import argparse
from pathlib import Path
import requests

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')

# Path setup
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(REPO_ROOT))

from secrets_manager import inject_to_env, get_secret
inject_to_env()

SHOP = get_secret("SHOPIFY_STORE")
TOKEN = get_secret("SHOPIFY_ACCESS_TOKEN")
STORE_URL = (get_secret("STORE_BASE_URL") or "https://us.meeeshop.com").rstrip("/")
API_VER = "2024-10"
GRAPHQL_URL = f"https://{SHOP}/admin/api/{API_VER}/graphql.json"
HEADERS = {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}

def run_query(query: str, variables: dict = None) -> dict:
    resp = requests.post(GRAPHQL_URL, headers=HEADERS, json={"query": query, "variables": variables or {}}, timeout=20)
    resp.raise_for_status()
    return resp.json()

def fetch_collections():
    q = """
    query {
      collections(first: 50) {
        edges {
          node {
            title
            handle
            description
          }
        }
      }
    }
    """
    res = run_query(q)
    edges = res.get("data", {}).get("collections", {}).get("edges", [])
    return [e["node"] for e in edges]

def fetch_products(limit=50):
    q = """
    query($first: Int!) {
      products(first: $first, query: "status:active") {
        edges {
          node {
            title
            handle
            productType
            description
            variants(first: 1) {
              edges {
                node {
                  price
                }
              }
            }
          }
        }
      }
    }
    """
    res = run_query(q, {"first": limit})
    edges = res.get("data", {}).get("products", {}).get("edges", [])
    products = []
    for e in edges:
        p = e["node"]
        price = p.get("variants", {}).get("edges", [{}])[0].get("node", {}).get("price", "N/A")
        products.append({
            "title": p.get("title"),
            "handle": p.get("handle"),
            "type": p.get("productType", "Women's Fashion"),
            "price": price,
            "desc": (p.get("description") or "")[:150].replace("\n", " ").strip()
        })
    return products

def fetch_articles(limit=30):
    q = """
    query($first: Int!) {
      articles(first: $first) {
        edges {
          node {
            title
            handle
            blog {
              handle
            }
            summaryHtml
          }
        }
      }
    }
    """
    try:
        res = run_query(q, {"first": limit})
        edges = res.get("data", {}).get("articles", {}).get("edges", [])
        articles = []
        for e in edges:
            node = e["node"]
            blog_handle = node.get("blog", {}).get("handle", "news")
            articles.append({
                "title": node.get("title"),
                "url": f"{STORE_URL}/blogs/{blog_handle}/{node.get('handle')}"
            })
        return articles
    except Exception as e:
        print(f"Warning fetching articles: {e}")
        return []

def generate_llms_txt():
    collections = fetch_collections()
    products = fetch_products(50)
    articles = fetch_articles(30)

    lines = []
    lines.append("# MeeeShop - US Women's Fashion & Apparel")
    lines.append("")
    lines.append("> MeeeShop (us.meeeshop.com) is an online women's fashion boutique offering trendy dresses, tops, bottoms, outerwear, boho clothing, and accessories with free US shipping and a 7-day return policy.")
    lines.append("")
    lines.append("## Store Overview")
    lines.append(f"- **Website**: {STORE_URL}")
    lines.append("- **Target Audience**: Women in the USA")
    lines.append("- **Shipping**: Free US Shipping on eligible orders")
    lines.append("- **Return Policy**: 7-Day Return Policy")
    lines.append("")
    
    lines.append("## Featured Collections")
    for c in collections:
        title = c["title"]
        handle = c["handle"]
        lines.append(f"- [{title}]({STORE_URL}/collections/{handle})")
    lines.append("")

    lines.append("## Top Women's Fashion Products")
    for p in products:
        title = p["title"]
        url = f"{STORE_URL}/products/{p['handle']}"
        lines.append(f"- [{title}]({url}): ${p['price']} USD ({p['type']})")
    lines.append("")

    if articles:
        lines.append("## Fashion Guides & Styling Articles")
        for a in articles:
            lines.append(f"- [{a['title']}]({a['url']})")
        lines.append("")

    lines.append("## Customer Service & Policies")
    lines.append(f"- [7-Day Return Policy]({STORE_URL}/policies/refund-policy)")
    lines.append(f"- [Shipping Information]({STORE_URL}/policies/shipping-policy)")
    lines.append(f"- [Terms of Service]({STORE_URL}/policies/terms-of-service)")
    lines.append("")

    content = "\n".join(lines)
    
    # Save files
    out_dir = REPO_ROOT
    llms_path = out_dir / "llms.txt"
    llms_full_path = out_dir / "llms-full.txt"
    
    with open(llms_path, "w", encoding="utf-8") as f:
        f.write(content)
        
    with open(llms_full_path, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"✅ Successfully generated /llms.txt and /llms-full.txt at {llms_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate /llms.txt for ChatGPT & Perplexity")
    args = parser.parse_args()
    generate_llms_txt()

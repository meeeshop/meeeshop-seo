#!/usr/bin/env python3
"""
popular_pages_indexer.py — Improvised GSC & Bing Analytics Indexer, Deduplicated Description Query Enricher & Blog Automation
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Queries Google Search Console (GSC) and Bing Webmaster APIs for 7-day search analytics targeting US Women Shoppers.
Identifies high-impression, zero/low-click products, collections, and blog articles (EXCLUDING size chart pages/queries).
Enriches product & collection descriptions naturally with missing search queries (with strict deduplication safeguards,
leaving Title Tags & Meta Descriptions 100% untouched).
Submits updated URLs to Google Indexing API & IndexNow for immediate search engine recrawling.
"""

import os
import sys
import json
import time
import re
import urllib.parse
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── path setup ────────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from secrets_manager import inject_to_env, get_secret
from article_deduplicator import ArticleDeduplicator
from utils import get_category_style_phrase

inject_to_env()

# Configure stdout and stderr to handle UTF-8 output properly on Windows
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')

# ── credentials ───────────────────────────────────────────────────────────────
SHOP      = get_secret("SHOPIFY_STORE")
STORE_URL = get_secret("STORE_BASE_URL").rstrip("/")

# ── Google OAuth / API constants ──────────────────────────────────────────────
OAUTH_ENDPOINT = "https://oauth2.googleapis.com/token"
GSC_SCOPE      = "https://www.googleapis.com/auth/webmasters.readonly"
INDEXING_SCOPE = "https://www.googleapis.com/auth/indexing"
INDEXING_ENDPOINT = "https://indexing.googleapis.com/v3/urlNotifications:publish"

# ── IndexNow Constants ────────────────────────────────────────────────────────
INDEXNOW_KEY = "c5def3bf8d13211be2bacf8d13211be2"
KEY_FILE_NAME = f"{INDEXNOW_KEY}.txt"

# ── History log path for deduplication ────────────────────────────────────────
HISTORY_FILE = Path(__file__).parent / "zero_click_query_history.json"

# ── Size Chart Filter Helper ─────────────────────────────────────────────────
def is_size_chart(text: str) -> bool:
    """Returns True if URL or query string relates to size charts or sizing pages."""
    t = text.lower()
    return ("size" in t and "chart" in t) or "sizing" in t or "size-chart" in t or "sizing-chart" in t or "size_chart" in t

# ── Google OAuth2 Helper ──────────────────────────────────────────────────────
def get_oauth_token(sa_key: dict, scope: str) -> str:
    try:
        import base64
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.backends import default_backend
    except ImportError:
        sys.exit("ERROR: 'cryptography' package missing — run: pip install cryptography")

    now     = int(time.time())
    header  = {"alg": "RS256", "typ": "JWT"}
    payload = {"iss": sa_key["client_email"], "scope": scope,
                "aud": OAUTH_ENDPOINT, "exp": now + 3600, "iat": now}

    def _b64url(data):
        return base64.urlsafe_b64encode(
            json.dumps(data, separators=(",", ":")).encode()
        ).rstrip(b"=").decode()

    signing_input = f"{_b64url(header)}.{_b64url(payload)}".encode()
    pk  = serialization.load_pem_private_key(
        sa_key["private_key"].encode(), password=None, backend=default_backend()
    )
    sig = pk.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    jwt = f"{signing_input.decode()}.{base64.urlsafe_b64encode(sig).rstrip(b'=').decode()}"

    resp = requests.post(OAUTH_ENDPOINT,
                         data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                               "assertion": jwt},
                         timeout=15)
    resp.raise_for_status()
    return resp.json()["access_token"]

# ── Fetch GSC Analytics (Pages & Queries with Country Filter) ─────────────────
def fetch_gsc_analytics(sa_key: dict, days: int = 7, page_limit: int = 100, query_limit: int = 100, country: str = "usa") -> tuple[list[dict], list[dict]]:
    print(f"Fetching GSC search analytics over the last {days} days (Country filter: {country.upper()})...")
    pages = []
    queries = []
    try:
        token = get_oauth_token(sa_key, GSC_SCOPE)
        
        # Query GSC verified sites list to find the matching property
        list_url = "https://www.googleapis.com/webmasters/v3/sites"
        list_resp = requests.get(list_url, headers={"Authorization": f"Bearer {token}"}, timeout=15)
        list_resp.raise_for_status()
        sites = list_resp.json().get("siteEntry", [])
        
        store_domain = urllib.parse.urlparse(STORE_URL).netloc.lower()
        site_url = None
        for site in sites:
            candidate = site.get("siteUrl", "")
            if store_domain in candidate.lower():
                site_url = candidate
                break
                
        if not site_url:
            site_url = STORE_URL + "/"
            
        encoded_site = urllib.parse.quote_plus(site_url)
        query_url = f"https://www.googleapis.com/webmasters/v3/sites/{encoded_site}/searchAnalytics/query"
        
        end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        start_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
        
        dim_filter_group = None
        if country:
            dim_filter_group = [{
                "filters": [{
                    "dimension": "country",
                    "operator": "equals",
                    "expression": country.lower()
                }]
            }]

        # 1. Query Pages
        page_payload = {
            "startDate": start_date,
            "endDate": end_date,
            "dimensions": ["page"],
            "rowLimit": page_limit
        }
        if dim_filter_group:
            page_payload["dimensionFilterGroups"] = dim_filter_group

        resp_pages = requests.post(
            query_url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=page_payload,
            timeout=20
        )
        if resp_pages.status_code == 200:
            for row in resp_pages.json().get("rows", []):
                p_url = row.get("keys", [""])[0]
                if not is_size_chart(p_url):
                    pages.append({
                        "url": p_url,
                        "clicks": int(row.get("clicks", 0)),
                        "impressions": int(row.get("impressions", 0)),
                        "ctr": float(row.get("ctr", 0)),
                        "position": float(row.get("position", 0)),
                        "source": "GSC"
                    })

        # 2. Query Search Terms
        query_payload = {
            "startDate": start_date,
            "endDate": end_date,
            "dimensions": ["query"],
            "rowLimit": query_limit
        }
        if dim_filter_group:
            query_payload["dimensionFilterGroups"] = dim_filter_group

        resp_queries = requests.post(
            query_url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=query_payload,
            timeout=20
        )
        if resp_queries.status_code == 200:
            for row in resp_queries.json().get("rows", []):
                q_text = row.get("keys", [""])[0]
                if not is_size_chart(q_text):
                    queries.append({
                        "query": q_text,
                        "clicks": int(row.get("clicks", 0)),
                        "impressions": int(row.get("impressions", 0)),
                        "ctr": float(row.get("ctr", 0)),
                        "position": float(row.get("position", 0)),
                        "source": "GSC"
                    })

    except Exception as e:
        print(f"[ERROR] Failed to fetch search analytics data from GSC: {e}")

    return pages, queries

# ── Fetch Bing Webmaster Analytics ────────────────────────────────────────────
def fetch_bing_analytics(api_key: str = None, days: int = 7, limit: int = 100) -> tuple[list[dict], list[dict]]:
    if not api_key:
        try:
            api_key = get_secret("BING_WEBMASTER_API_KEY")
        except Exception:
            api_key = os.environ.get("BING_WEBMASTER_API_KEY", "").strip()

    if not api_key:
        print("[INFO] BING_WEBMASTER_API_KEY not specified/found. Skipping Bing Webmaster API fetch.")
        return [], []

    print(f"Fetching Bing Webmaster search analytics over the last {days} days...")
    pages = []
    queries = []
    
    try:
        domain = urllib.parse.urlparse(STORE_URL).netloc
        site_param = urllib.parse.quote(STORE_URL)
        
        # 1. Fetch Query Stats
        query_endpoint = f"https://ssl.bing.com/webmaster/api.svc/json/GetQueryStats?siteUrl={site_param}&apikey={api_key}"
        rq = requests.get(query_endpoint, timeout=15)
        if rq.status_code == 200:
            q_rows = rq.json().get("d", [])
            for row in q_rows[:limit]:
                q_text = row.get("Query", "")
                if is_size_chart(q_text):
                    continue
                clicks = int(row.get("Clicks", 0))
                impressions = int(row.get("Impressions", 0))
                ctr = float(clicks / impressions) if impressions > 0 else 0.0
                queries.append({
                    "query": q_text,
                    "clicks": clicks,
                    "impressions": impressions,
                    "ctr": ctr,
                    "position": float(row.get("AvgImpressionPosition", 0)),
                    "source": "Bing"
                })

        # 2. Fetch Page Stats
        page_endpoint = f"https://ssl.bing.com/webmaster/api.svc/json/GetPageStats?siteUrl={site_param}&apikey={api_key}"
        rp = requests.get(page_endpoint, timeout=15)
        if rp.status_code == 200:
            p_rows = rp.json().get("d", [])
            for row in p_rows[:limit]:
                url = row.get("Query", "")
                if not url.startswith("http"):
                    url = f"{STORE_URL}{url}"
                if is_size_chart(url):
                    continue
                clicks = int(row.get("Clicks", 0))
                impressions = int(row.get("Impressions", 0))
                ctr = float(clicks / impressions) if impressions > 0 else 0.0
                pages.append({
                    "url": url,
                    "clicks": clicks,
                    "impressions": impressions,
                    "ctr": ctr,
                    "position": float(row.get("AvgImpressionPosition", 0)),
                    "source": "Bing"
                })
        print(f"Retrieved {len(queries)} Bing queries and {len(pages)} Bing pages stats.")
    except Exception as e:
        print(f"[WARNING] Bing Webmaster API request failed: {e}")

    return pages, queries

# ── Merge GSC and Bing Analytics ──────────────────────────────────────────────
def merge_analytics(gsc_pages: list[dict], gsc_queries: list[dict], bing_pages: list[dict], bing_queries: list[dict]) -> tuple[list[dict], list[dict]]:
    merged_pages_map = {}
    for p in gsc_pages + bing_pages:
        url = p["url"]
        if is_size_chart(url):
            continue
        if url not in merged_pages_map:
            merged_pages_map[url] = dict(p)
        else:
            merged_pages_map[url]["clicks"] += p["clicks"]
            merged_pages_map[url]["impressions"] += p["impressions"]
            tot_imp = merged_pages_map[url]["impressions"]
            merged_pages_map[url]["ctr"] = merged_pages_map[url]["clicks"] / tot_imp if tot_imp > 0 else 0.0
            merged_pages_map[url]["source"] = "GSC+Bing"

    merged_queries_map = {}
    for q in gsc_queries + bing_queries:
        q_text = q["query"].lower().strip()
        if is_size_chart(q_text):
            continue
        if q_text not in merged_queries_map:
            merged_queries_map[q_text] = dict(q)
        else:
            merged_queries_map[q_text]["clicks"] += q["clicks"]
            merged_queries_map[q_text]["impressions"] += q["impressions"]
            tot_imp = merged_queries_map[q_text]["impressions"]
            merged_queries_map[q_text]["ctr"] = merged_queries_map[q_text]["clicks"] / tot_imp if tot_imp > 0 else 0.0
            merged_queries_map[q_text]["source"] = "GSC+Bing"

    pages = list(merged_pages_map.values())
    queries = list(merged_queries_map.values())
    return pages, queries

# ── Filter Zero/Low-Click Opportunities (Excluding Size Charts) ──────────────
def filter_zero_click_opportunities(pages: list[dict], queries: list[dict], min_impressions: int = 5) -> dict:
    zero_click_pages = [p for p in pages if p["impressions"] >= min_impressions and p["clicks"] == 0 and not is_size_chart(p["url"])]
    zero_click_queries = [q for q in queries if q["impressions"] >= min_impressions and q["clicks"] == 0 and not is_size_chart(q["query"])]

    zero_click_pages.sort(key=lambda x: x["impressions"], reverse=True)
    zero_click_queries.sort(key=lambda x: x["impressions"], reverse=True)

    products = [p for p in zero_click_pages if "/products/" in p["url"]]
    collections = [p for p in zero_click_pages if "/collections/" in p["url"]]
    blogs = [p for p in zero_click_pages if "/blogs/" in p["url"]]
    other = [p for p in zero_click_pages if p not in products and p not in collections and p not in blogs]

    return {
        "all_zero_click_pages": zero_click_pages,
        "zero_click_queries": zero_click_queries,
        "products": products,
        "collections": collections,
        "blogs": blogs,
        "other": other
    }

# ── Search Storefront Resources for Queries ──────────────────────────────────
def search_store_resources(queries: list[dict]) -> set[str]:
    print("Searching store for products, pages, and articles matching search queries...")
    matched_urls = set()
    TOKEN = get_secret("SHOPIFY_ACCESS_TOKEN")
    if not TOKEN:
        print("[WARNING] SHOPIFY_ACCESS_TOKEN missing, skipping resource lookup.")
        return matched_urls

    headers = {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}
    admin_base = f"https://{SHOP}/admin/api/2024-10"

    for item in queries:
        q = item["query"].strip()
        if len(q) < 3 or is_size_chart(q):
            continue
        try:
            search_endpoint = f"{admin_base}/products.json?title={urllib.parse.quote(q)}&limit=5"
            r = requests.get(search_endpoint, headers=headers, timeout=10)
            if r.status_code == 200:
                products = r.json().get("products", [])
                for p in products:
                    handle = p.get("handle")
                    if handle and not is_size_chart(handle):
                        matched_urls.add(f"{STORE_URL}/products/{handle}")

            article_endpoint = f"{admin_base}/articles.json?limit=10"
            ra = requests.get(article_endpoint, headers=headers, timeout=10)
            if ra.status_code == 200:
                articles = ra.json().get("articles", [])
                q_words = set(q.lower().split())
                for art in articles:
                    title = art.get("title", "").lower()
                    if any(w in title for w in q_words if len(w) > 3):
                        handle = art.get("handle")
                        if handle and not is_size_chart(handle):
                            matched_urls.add(f"{STORE_URL}/blogs/news/{handle}")
        except Exception as e:
            print(f"  [!] Error searching store resources for '{q}': {e}")

    # Exclude any size chart pages from matched URLs
    matched_urls = {u for u in matched_urls if not is_size_chart(u)}
    print(f"Discovered {len(matched_urls)} matching product/article URLs from query lookup.")
    return matched_urls

# ── Deduplicated Natural Description Query Enricher ──────────────────────────
def enrich_descriptions_with_queries(opportunities: dict, queries: list[dict], dry_run: bool = False) -> int:
    print("\n" + "=" * 70)
    print("  DEDUPLICATED NATURAL DESCRIPTION QUERY ENRICHER")
    print("  (Preserving Titles & Meta Descriptions Untouched; Excluding Size Charts)")
    print("=" * 70)

    TOKEN = get_secret("SHOPIFY_ACCESS_TOKEN")
    if not TOKEN:
        print("[ERROR] SHOPIFY_ACCESS_TOKEN missing. Skipping description enrichment.")
        return 0

    headers = {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}
    admin_base = f"https://{SHOP}/admin/api/2024-10"

    history = {}
    if HISTORY_FILE.exists():
        try:
            history = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            history = {}

    modified_count = 0

    # 1. Process Product Opportunities
    for item in opportunities.get("products", []):
        url = item["url"]
        if is_size_chart(url):
            continue

        handle = url.rstrip("/").split("/")[-1]
        if not handle:
            continue

        try:
            r = requests.get(f"{admin_base}/products.json?handle={handle}", headers=headers, timeout=10)
            if r.status_code != 200:
                continue
            prods = r.json().get("products", [])
            if not prods:
                continue
            prod = prods[0]
            prod_id = str(prod["id"])
            body_html = prod.get("body_html", "") or ""
            prod_title = prod.get("title", "")

            matching_queries = [
                q for q in queries
                if not is_size_chart(q["query"]) and any(w in prod_title.lower() or w in handle.lower() for w in q["query"].lower().split() if len(w) > 3)
            ]
            if not matching_queries:
                non_size_queries = [q for q in queries if not is_size_chart(q["query"])]
                matching_queries = non_size_queries[:1]

            for q_obj in matching_queries[:2]:
                q_text = q_obj["query"].strip()
                if is_size_chart(q_text):
                    continue
                q_clean = q_text.lower()
                hist_key = f"product:{prod_id}:{q_clean}"

                if q_clean in body_html.lower() or f"gsc-query: \"{q_clean}\"" in body_html.lower():
                    print(f"  [SKIP DUP] Product '{handle}': Query '{q_text}' already present in description.")
                    continue

                if hist_key in history:
                    print(f"  [SKIP HIST] Product '{handle}': Query '{q_text}' previously injected on {history[hist_key].get('date')}.")
                    continue

                injection_html = (
                    f'\n<p class="gsc-seo-note"><!-- gsc-query: "{q_clean}" -->'
                    f'<strong>Styling Tip:</strong> Ideal for creating an effortless <em>{q_text}</em> look. '
                    f'Pair with classic accessories for a versatile US women\'s outfit.</p>'
                )

                new_body = body_html + injection_html
                print(f"  [ENRICH] Product '{handle}': Adding natural query '{q_text}' (Impressions: {q_obj['impressions']})")

                if not dry_run:
                    up_res = requests.put(
                        f"{admin_base}/products/{prod_id}.json",
                        headers=headers,
                        json={"product": {"id": prod["id"], "body_html": new_body}},
                        timeout=15
                    )
                    if up_res.status_code == 200:
                        modified_count += 1
                        history[hist_key] = {"date": datetime.now(timezone.utc).isoformat(), "url": url, "query": q_text}
                    else:
                        print(f"  [ERROR] Failed to update product '{handle}': HTTP {up_res.status_code}")
                else:
                    modified_count += 1

        except Exception as e:
            print(f"  [!] Error processing product '{handle}': {e}")

    # 2. Process Collection Opportunities
    for item in opportunities.get("collections", []):
        url = item["url"]
        if is_size_chart(url):
            continue

        handle = url.rstrip("/").split("/")[-1]
        if not handle:
            continue

        try:
            col_obj = None
            col_type = "custom_collections"
            r_cust = requests.get(f"{admin_base}/custom_collections.json?handle={handle}", headers=headers, timeout=10)
            if r_cust.status_code == 200 and r_cust.json().get("custom_collections"):
                col_obj = r_cust.json()["custom_collections"][0]
            else:
                r_smart = requests.get(f"{admin_base}/smart_collections.json?handle={handle}", headers=headers, timeout=10)
                if r_smart.status_code == 200 and r_smart.json().get("smart_collections"):
                    col_obj = r_smart.json()["smart_collections"][0]
                    col_type = "smart_collections"

            if not col_obj:
                continue

            col_id = str(col_obj["id"])
            col_desc = col_obj.get("body_html") or col_obj.get("description") or ""

            matching_queries = [
                q for q in queries
                if not is_size_chart(q["query"]) and any(w in handle.lower() for w in q["query"].lower().split() if len(w) > 3)
            ]
            if not matching_queries:
                non_size_queries = [q for q in queries if not is_size_chart(q["query"])]
                matching_queries = non_size_queries[:1]

            for q_obj in matching_queries[:1]:
                q_text = q_obj["query"].strip()
                if is_size_chart(q_text):
                    continue
                q_clean = q_text.lower()
                hist_key = f"collection:{col_id}:{q_clean}"

                if q_clean in col_desc.lower() or f"gsc-query: \"{q_clean}\"" in col_desc.lower():
                    print(f"  [SKIP DUP] Collection '{handle}': Query '{q_text}' already present in description.")
                    continue

                if hist_key in history:
                    print(f"  [SKIP HIST] Collection '{handle}': Query '{q_text}' previously injected.")
                    continue

                injection_html = (
                    f'\n<p class="gsc-seo-note"><!-- gsc-query: "{q_clean}" -->'
                    f'<strong>Collection Highlight:</strong> Explore top-trending styles for <em>{q_text}</em>. '
                    f'Curated for modern US women with fast shipping and easy 7-day returns.</p>'
                )

                new_desc = col_desc + injection_html
                print(f"  [ENRICH] Collection '{handle}': Adding natural query '{q_text}' (Impressions: {q_obj['impressions']})")

                if not dry_run:
                    up_res = requests.put(
                        f"{admin_base}/{col_type}/{col_id}.json",
                        headers=headers,
                        json={col_type[:-1]: {"id": col_obj["id"], "body_html": new_desc}},
                        timeout=15
                    )
                    if up_res.status_code == 200:
                        modified_count += 1
                        history[hist_key] = {"date": datetime.now(timezone.utc).isoformat(), "url": url, "query": q_text}
                else:
                    modified_count += 1

        except Exception as e:
            print(f"  [!] Error processing collection '{handle}': {e}")

    if not dry_run:
        HISTORY_FILE.write_text(json.dumps(history, indent=2), encoding="utf-8")

    print(f"Enriched {modified_count} product/collection descriptions with zero-click search queries.")
    print("=" * 70 + "\n")
    return modified_count

# ── Export Opportunities Report ───────────────────────────────────────────────
def export_opportunity_report(opportunities: dict, report_file: str = "reports/zero_click_7d_opportunities.json"):
    out_path = Path(report_file)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    summary = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_zero_click_pages": len(opportunities["all_zero_click_pages"]),
        "total_zero_click_queries": len(opportunities["zero_click_queries"]),
        "products_count": len(opportunities["products"]),
        "collections_count": len(opportunities["collections"]),
        "blogs_count": len(opportunities["blogs"]),
        "top_product_opportunities": opportunities["products"][:10],
        "top_collection_opportunities": opportunities["collections"][:10],
        "top_blog_opportunities": opportunities["blogs"][:10],
        "top_query_opportunities": opportunities["zero_click_queries"][:15]
    }

    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"[REPORT] Exported 7-day SEO opportunity report to: {out_path.resolve()}")

# ── Identify Long-Tail Question Queries for Blog Creation ──────────────────────
def identify_longtail_question_queries(queries: list[dict]) -> list[dict]:
    question_triggers = [
        "what", "how", "why", "outfit", "style", "wear", "best",
        "versus", "vs", "flattering", "types", "guide", "look", "combination"
    ]
    candidates = []
    for q in queries:
        q_text = q["query"].lower().strip()
        if is_size_chart(q_text):
            continue

        if any(w in q_text for w in question_triggers) or (q["impressions"] >= 15 and q["clicks"] == 0):
            candidates.append(q)

    candidates.sort(key=lambda x: (x["clicks"], x["impressions"]), reverse=True)
    return candidates

# ── Generate Blog Articles from Long-Tail Queries ─────────────────────────────
def generate_blogs_from_longtail(queries: list[dict], max_blogs: int = 1, dry_run: bool = False) -> list[str]:
    new_blog_urls = []
    if not queries or max_blogs <= 0:
        return new_blog_urls

    print(f"\nFound {len(queries)} potential long-tail question/trend queries for blog creation.")
    selected = queries[:max_blogs]

    TOKEN = get_secret("SHOPIFY_ACCESS_TOKEN")
    admin_base = f"https://{SHOP}/admin/api/2024-10"
    headers = {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}
    dedup = ArticleDeduplicator(admin_base, headers)
    dedup.load_live_index()

    for i, item in enumerate(selected, 1):
        q = item["query"]
        if is_size_chart(q):
            continue
        category_topic = get_category_style_phrase({"title": q, "product_type": q})
        print(f"\n[{i}/{len(selected)}] Preparing blog post for long-tail query: '{q}' → category topic: '{category_topic}' (Impressions: {item['impressions']}, Clicks: {item['clicks']})")

        if dedup.is_duplicate_title(q) or dedup.is_duplicate_title(category_topic) or dedup.is_duplicate_category_or_topic(q, category_topic):
            print(f"  [Dedup] SKIP — Article for search query / category topic '{q}' ('{category_topic}') already exists or was covered recently on Shopify.")
            continue

        try:
            import subprocess
            cmd = [
                sys.executable,
                str(Path(__file__).parent / "blog_daily.py"),
                "--count", "1",
                "--topic", category_topic,
            ]
            if dry_run:
                cmd.append("--dry-run")
            else:
                cmd.append("--publish")

            print(f"  Executing blog_daily workflow command: {' '.join(cmd)}")
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            print(res.stdout)
            if res.stderr:
                print(f"[LOG] {res.stderr}")

            if res.returncode == 0:
                mode_str = "dry-run preview" if dry_run else "published live"
                print(f"  ✓ Blog article creation ({mode_str}) completed for topic '{category_topic}'!")
        except Exception as e:
            print(f"  [ERROR] Failed to run blog generation for query '{q}': {e}")

    return new_blog_urls

# ── Submit to Google Indexing API ────────────────────────────────────────────
def submit_to_google_indexing(urls: list[str], sa_key: dict, dry_run: bool = False):
    urls = [u for u in urls if not is_size_chart(u)]
    if not urls:
        return
    
    print("\nSubmitting trending & matched URLs to Google Indexing API (Excluding Size Charts)...")
    if dry_run:
        print("[DRY-RUN] Skipping API calls for Google Indexing.")
        return
        
    try:
        token = get_oauth_token(sa_key, INDEXING_SCOPE)
        for i, url in enumerate(urls, 1):
            try:
                resp = requests.post(
                    INDEXING_ENDPOINT,
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    json={"url": url, "type": "URL_UPDATED"},
                    timeout=15
                )
                if resp.status_code == 200:
                    print(f"  [{i:>3}/{len(urls)}] [OK] Google Indexing: {url}")
                elif resp.status_code == 429:
                    print(f"  [{i:>3}/{len(urls)}] [QUOTA EXCEEDED] Google Indexing: stopping submissions.")
                    break
                else:
                    print(f"  [{i:>3}/{len(urls)}] [ERROR {resp.status_code}] Google Indexing: {resp.text}")
            except Exception as e:
                print(f"  [{i:>3}/{len(urls)}] [ERROR] Google Indexing: {e}")
            time.sleep(0.2)
    except Exception as e:
        print(f"[ERROR] Failed to authenticate for Google Indexing: {e}")

# ── Submit to IndexNow ────────────────────────────────────────────────────────
def submit_to_indexnow(urls: list[str], dry_run: bool = False):
    urls = [u for u in urls if not is_size_chart(u)]
    if not urls:
        return
        
    print("\nSubmitting trending & matched URLs to IndexNow (Excluding Size Charts)...")
    domain = urllib.parse.urlparse(STORE_URL).netloc
    key_location = f"{STORE_URL}/{KEY_FILE_NAME}"
    
    payload = {
        "host": domain,
        "key": INDEXNOW_KEY,
        "keyLocation": key_location,
        "urlList": urls
    }
    
    if dry_run:
        print("[DRY-RUN] IndexNow payload prepared, skipping API call.")
        return
        
    endpoint = "https://api.indexnow.org/indexnow"
    try:
        resp = requests.post(endpoint, json=payload, headers={"Content-Type": "application/json; charset=utf-8"}, timeout=15)
        if resp.status_code in (200, 202):
            print(f"[OK] IndexNow submission successful (HTTP {resp.status_code})!")
        else:
            print(f"[WARNING] IndexNow submission failed with HTTP status {resp.status_code}: {resp.text}")
    except Exception as e:
        print(f"[ERROR] Connection error during IndexNow submission: {e}")

# ── Main Execution ───────────────────────────────────────────────────────────
def main():
    import argparse
    parser = argparse.ArgumentParser(description="Multi-Search Analytics Indexer, Deduplicated Description Enricher & Blog Automation")
    parser.add_argument("--dry-run", action="store_true", help="Dry run mode, do not call indexing APIs or mutate Shopify descriptions")
    parser.add_argument("--limit", type=int, default=100, help="Number of popular pages to process (default: 100)")
    parser.add_argument("--query-limit", type=int, default=100, help="Number of top search queries to retrieve (default: 100)")
    parser.add_argument("--days", type=int, default=7, help="Search analytics lookback days (default: 7)")
    parser.add_argument("--country", type=str, default="usa", help="GSC Country filter (default: usa)")
    parser.add_argument("--min-impressions", type=int, default=5, help="Minimum impression threshold for 0-click opportunity (default: 5)")
    parser.add_argument("--enrich-descriptions", action="store_true", help="Enrich 0-click product & collection descriptions with missing search queries")
    parser.add_argument("--bing-api-key", type=str, default=None, help="Bing Webmaster API Key (optional)")
    parser.add_argument("--export-report", action="store_true", help="Export structured 7-day opportunity report JSON")
    parser.add_argument("--generate-blogs", action="store_true", help="Generate blog articles for long-tail question queries")
    parser.add_argument("--max-blogs", type=int, default=1, help="Maximum number of blog articles to generate per run (default: 1)")
    args = parser.parse_args()

    print("=" * 70)
    print("  Popular Pages Indexer & Deduplicated Search Query Enricher (7-Day GSC + Bing)")
    print("  [Size Chart & Sizing Exclusions Active]")
    print("=" * 70)
    
    try:
        raw = get_secret("GOOGLE_SA_KEY_JSON")
        sa_key = json.loads(raw)
    except Exception as e:
        print(f"Error loading GOOGLE_SA_KEY_JSON: {e}. Checking local key file...")
        local = Path(__file__).parent.parent / "google_sa_key.json"
        if local.exists():
            sa_key = json.loads(local.read_text(encoding="utf-8"))
        else:
            print("ERROR: Google Service Account key not found. Exiting.")
            sys.exit(1)
            
    # 1. Fetch top pages & search queries from GSC
    gsc_pages, gsc_queries = fetch_gsc_analytics(
        sa_key, days=args.days, page_limit=args.limit, query_limit=args.query_limit, country=args.country
    )

    # 2. Fetch Bing Webmaster Analytics if API Key available
    bing_pages, bing_queries = fetch_bing_analytics(
        api_key=args.bing_api_key, days=args.days, limit=args.limit
    )

    # 3. Merge GSC and Bing analytics
    pages, queries = merge_analytics(gsc_pages, gsc_queries, bing_pages, bing_queries)

    # Filter out size chart queries and pages from analytics list
    pages = [p for p in pages if not is_size_chart(p["url"])]
    queries = [q for q in queries if not is_size_chart(q["query"])]

    # Display Top Queries Log
    print("\n" + "=" * 70)
    print(f"  TOP {len(queries)} COMBINED SEARCH QUERIES (Excluding Size Charts)")
    print("=" * 70)
    for q in queries[:20]:
        print(f"  {q['query']:<45} \t{q['clicks']}\t{q['impressions']}\t[{q['source']}]")
    print("=" * 70 + "\n")

    # 4. Filter Zero-Click High-Impression Opportunities
    opportunities = filter_zero_click_opportunities(pages, queries, min_impressions=args.min_impressions)
    print(f"Found {len(opportunities['all_zero_click_pages'])} zero-click pages (excluding size charts) with >= {args.min_impressions} impressions over last {args.days} days:")
    print(f"  • Products:    {len(opportunities['products'])}")
    print(f"  • Collections: {len(opportunities['collections'])}")
    print(f"  • Blogs:       {len(opportunities['blogs'])}")

    # 5. Enrich Product & Collection descriptions if requested
    if args.enrich_descriptions:
        enrich_descriptions_with_queries(opportunities, queries, dry_run=args.dry_run)

    # 6. Export Opportunity Report if requested
    if args.export_report:
        export_opportunity_report(opportunities)

    # Collect direct GSC & matched store URLs (strictly excluding size charts)
    gsc_urls = [p["url"] for p in pages if p["url"].startswith(STORE_URL) and not is_size_chart(p["url"])]
    matched_urls = search_store_resources(queries)
    urls_to_index = sorted(list(set(gsc_urls).union(matched_urls)))
    urls_to_index = [u for u in urls_to_index if not is_size_chart(u)]
    print(f"\nTotal unique product/collection/article URLs targeted for re-indexing: {len(urls_to_index)}")

    # 7. Generate long-tail blog posts if requested
    if args.generate_blogs:
        longtail_candidates = identify_longtail_question_queries(queries)
        generate_blogs_from_longtail(longtail_candidates, max_blogs=args.max_blogs, dry_run=args.dry_run)

    # 8. Submit to Google Indexing API
    submit_to_google_indexing(urls_to_index, sa_key, dry_run=args.dry_run)
    
    # 9. Submit to IndexNow (Bing/DuckDuckGo)
    submit_to_indexnow(urls_to_index, dry_run=args.dry_run)
    
    print("\n[OK] Popular Pages Indexer & Deduplicated Query Enricher completed successfully!")
    print("=" * 70)

if __name__ == "__main__":
    main()

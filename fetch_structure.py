"""Fetch all collections, products sample, and blog posts from MeeeShop for structure mapping."""
import urllib.request, urllib.parse, json, time, sys

TOKEN = "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"
SHOP  = "us-meeeshop.myshopify.com"
API   = "2025-01"
HDR   = {"X-Shopify-Access-Token": TOKEN}

def get(path, params=None):
    url = f"https://{SHOP}/admin/api/{API}/{path}"
    if params: url += "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(urllib.request.Request(url, headers=HDR)) as r:
        return json.loads(r.read())

def paginate(path, key, params=None):
    params = {**(params or {}), "limit": 250}
    items = []
    while True:
        data = get(path, params)
        items.extend(data.get(key, []))
        if len(data.get(key, [])) < 250: break
        params["page_info"] = data.get("next_page_info")
        time.sleep(0.2)
    return items

# ── Collections ──────────────────────────────────────────────────────────────
print("Fetching collections...")
custom = get("custom_collections.json", {"limit": 250}).get("custom_collections", [])
smart  = get("smart_collections.json",  {"limit": 250}).get("smart_collections", [])
all_cols = custom + smart
time.sleep(0.3)

print(f"\n=== ALL COLLECTIONS ({len(all_cols)}) ===")
col_map = {}
for c in sorted(all_cols, key=lambda x: x["title"]):
    print(f"  {c['title']:55s} handle: {c['handle']}")
    col_map[c["handle"]] = c["title"]

# ── Product types ─────────────────────────────────────────────────────────────
time.sleep(0.3)
print("\nFetching product types...")
products = get("products.json", {"limit": 250, "fields": "id,title,product_type,tags,handle"}).get("products", [])
types = {}
for p in products:
    pt = p.get("product_type", "").strip()
    if pt:
        types[pt] = types.get(pt, 0) + 1

print(f"\n=== PRODUCT TYPES ({len(types)}) ===")
for t, count in sorted(types.items(), key=lambda x: -x[1])[:30]:
    print(f"  {t:45s} {count} products")

# ── Blog posts ────────────────────────────────────────────────────────────────
time.sleep(0.3)
print("\nFetching blogs...")
blogs = get("blogs.json").get("blogs", [])
print(f"\n=== BLOGS ({len(blogs)}) ===")
for b in blogs:
    print(f"  Blog: {b['title']} (handle: {b['handle']}, ID: {b['id']})")
    articles = get(f"blogs/{b['id']}/articles.json", {"limit": 10}).get("articles", [])
    for a in articles[:5]:
        print(f"    - {a['title'][:60]}")
    time.sleep(0.2)

# Save for use in theme builder
with open("store_structure.json", "w") as f:
    json.dump({"collections": [{"title": c["title"], "handle": c["handle"]} for c in all_cols],
               "product_types": types, "blogs": blogs}, f, indent=2)
print("\nSaved to store_structure.json")

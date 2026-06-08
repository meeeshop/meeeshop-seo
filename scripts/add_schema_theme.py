"""
MeeeShop Schema Theme Cleanup
- Removes the OLD metafield-loop injection from layout/theme.liquid
  (was added by a previous version of this script, now duplicates the
   snippets/meeeshop-jsonld.liquid snippet)
- Verifies {% render 'meeeshop-jsonld' %} is present (the correct approach)
- Optionally purges stale json_ld_schema metafields from all products so
  schema_fixer.py can regenerate clean ones (run with --purge-metafields)

The old injection iterated product.metafields.json_ld_schema and output
{{ metafield.value | json }} which caused <script>null</script> and
duplicate schema blocks alongside the snippet.
"""
import os, sys, json, time, argparse
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from secrets_manager import inject_to_env, get_secret
inject_to_env()

STORE    = get_secret("SHOPIFY_STORE")
TOKEN    = get_secret("SHOPIFY_ACCESS_TOKEN")
THEME_ID = get_secret("LIVE_THEME_ID")

BASE_URL = f"https://{STORE}/admin/api/2024-01"
HEADERS  = {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}

# Markers that identify the old injected block in theme.liquid
OLD_MARKERS = [
    "JSON-LD Schema Rendering (MeeeShop)",   # updated version
    "JSON-LD Schema Rendering",               # original version
    "Global Organization Schema",             # original trailing block
]

# The correct render tag (added by seo_daily.py inject_jsonld)
RENDER_TAG = "{% render 'meeeshop-jsonld' %}"
ROBOTS_TAG = '<meta name="robots" content="max-image-preview:large">'


# ── theme.liquid helpers ──────────────────────────────────────────────────────

def get_theme_liquid():
    url  = f"{BASE_URL}/themes/{THEME_ID}/assets.json"
    resp = requests.get(url, headers=HEADERS, params={"asset[key]": "layout/theme.liquid"})
    if resp.status_code != 200:
        print(f"[!] Error fetching theme.liquid: {resp.status_code}")
        return None
    return resp.json()["asset"]["value"]


def put_theme_liquid(content):
    url  = f"{BASE_URL}/themes/{THEME_ID}/assets.json"
    resp = requests.put(url, headers=HEADERS,
                        json={"asset": {"key": "layout/theme.liquid", "value": content}})
    if resp.status_code not in (200, 201):
        print(f"[!] Error updating theme.liquid: {resp.status_code} {resp.text[:200]}")
        return False
    return True


def remove_old_injection(content: str) -> tuple[str, bool]:
    """
    Strip the old <!-- JSON-LD Schema Rendering --> block injected into theme.liquid.
    The block starts at the HTML comment and ends after the last {%- endif -%} or
    </script> belonging to it, before the closing </head>.
    Returns (cleaned_content, changed).
    """
    changed = False

    # Strategy: find the comment open tag, then the matching </head> boundary
    # and strip everything between them that belongs to the old block.
    # We use the known comment markers as anchors.
    for marker in OLD_MARKERS:
        comment_open = f"<!-- {marker}"
        if comment_open not in content:
            continue

        start = content.find(comment_open)

        # Old block ends at the last %} or </script> before </head>
        # Simplest reliable approach: find </head> after start and cut backwards
        head_close = content.find("</head>", start)
        if head_close == -1:
            continue

        # The block to remove is from 'start' up to (but not including) </head>
        # BUT we only want to remove the injected block, not anything else before </head>.
        # The injected block ends with either:
        #   - the closing of the last {%- endunless -%}{%- endfor -%}{%- endif -%}
        #   - or a closing </script> tag (for the old Organization hardcoded block)
        block_candidate = content[start:head_close]

        # Find the last occurrence of a Liquid end tag or </script> in the block
        end_markers = ["{%- endif -%}", "{% endif %}", "</script>", "{%- endfor -%}"]
        block_end_rel = -1
        for em in end_markers:
            pos = block_candidate.rfind(em)
            if pos != -1:
                candidate = pos + len(em)
                if candidate > block_end_rel:
                    block_end_rel = candidate

        if block_end_rel == -1:
            # Can't find end — skip to avoid corrupting file
            print(f"  [?] Could not find end of old block for marker '{marker}' — skipping")
            continue

        block_end_abs = start + block_end_rel

        # Remove the block (including any trailing whitespace/newlines up to </head>)
        removed = content[start:block_end_abs]
        content = content[:start] + content[block_end_abs:]
        changed = True
        print(f"  [OK] Removed old injection block ({len(removed)} chars) — marker: '{marker}'")
        break  # one pass is enough; re-run if there are somehow two blocks

    return content, changed


def ensure_render_tag(content: str) -> tuple[str, bool]:
    """Ensure {% render 'meeeshop-jsonld' %} is present before </head>."""
    if RENDER_TAG in content:
        return content, False
    if "</head>" not in content:
        print("  [!] </head> not found — cannot add render tag")
        return content, False
    content = content.replace("</head>", f"  {RENDER_TAG}\n</head>", 1)
    print("  [OK] Added {% render 'meeeshop-jsonld' %} before </head>")
    return content, True


def ensure_robots_tag(content: str) -> tuple[str, bool]:
    """Ensure <meta name="robots" content="max-image-preview:large"> is present in head."""
    if "max-image-preview:large" in content:
        return content, False
    if "</head>" not in content:
        print("  [!] </head> not found — cannot add robots meta tag")
        return content, False
    content = content.replace("</head>", f"  {ROBOTS_TAG}\n</head>", 1)
    print("  [OK] Added <meta name=\"robots\" content=\"max-image-preview:large\"> before </head>")
    return content, True


# ── metafield purge ───────────────────────────────────────────────────────────

def get_all_products():
    products, url = [], f"{BASE_URL}/products.json"
    params = {"limit": 250, "status": "active"}
    while url:
        resp = requests.get(url, headers=HEADERS, params=params)
        if resp.status_code != 200:
            break
        products.extend(resp.json().get("products", []))
        link = resp.headers.get("Link", "")
        url, params = None, {}
        for part in link.split(","):
            if 'rel="next"' in part:
                url = part.split(";")[0].strip().strip("<>")
    return products


def purge_json_ld_metafields():
    """Delete all json_ld_schema metafields from products so fixer regenerates them."""
    print("\n[*] Purging stale json_ld_schema metafields from products...")
    products = get_all_products()
    print(f"    Found {len(products)} products")
    deleted = 0
    for p in products:
        pid   = p["id"]
        title = p.get("title", str(pid))
        resp  = requests.get(f"{BASE_URL}/products/{pid}/metafields.json",
                             headers=HEADERS,
                             params={"namespace": "json_ld_schema", "limit": 250})
        if resp.status_code != 200:
            continue
        mfs = resp.json().get("metafields", [])
        for mf in mfs:
            time.sleep(0.3)
            dr = requests.delete(f"{BASE_URL}/metafields/{mf['id']}.json", headers=HEADERS)
            if dr.status_code == 200:
                deleted += 1
                print(f"  Deleted metafield {mf['id']} from '{title}'")
            else:
                print(f"  [!] Failed to delete {mf['id']} from '{title}': {dr.status_code}")
        time.sleep(0.5)
    print(f"\n[OK] Purged {deleted} metafields. Run schema_fixer.py --force to regenerate.")


# ── main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--purge-metafields", action="store_true",
                        help="Also delete all json_ld_schema product metafields (fixer will regenerate)")
    args = parser.parse_args()

    print("=" * 70)
    print("MEEESHOP SCHEMA THEME CLEANUP")
    print("=" * 70)
    print(f"Store:    {STORE}")
    print(f"Theme ID: {THEME_ID}\n")

    content = get_theme_liquid()
    if not content:
        print("[!] Failed to fetch theme.liquid. Exiting.")
        sys.exit(1)
    print(f"[OK] Fetched theme.liquid ({len(content):,} bytes)")

    content, removed = remove_old_injection(content)
    content, added_render = ensure_render_tag(content)
    content, added_robots = ensure_robots_tag(content)

    if removed or added_render or added_robots:
        if put_theme_liquid(content):
            print("[OK] theme.liquid updated successfully")
        else:
            print("[!] Failed to update theme.liquid")
            sys.exit(1)
    else:
        print("[OK] theme.liquid already clean — no changes needed")

    # Verify final state
    final = get_theme_liquid()
    has_old = any(m in (final or "") for m in OLD_MARKERS)
    has_new = RENDER_TAG in (final or "")
    has_robots = "max-image-preview:large" in (final or "")
    print(f"\nVerification:")
    print(f"  Old injection removed: {'YES' if not has_old else 'NO — still present!'}")
    print(f"  Render tag present:    {'YES' if has_new else 'NO — missing!'}")
    print(f"  Robots tag present:    {'YES' if has_robots else 'NO — missing!'}")

    if has_old:
        print("\n[!] Old injection still detected — re-run this script")
        sys.exit(1)
    if not has_new:
        print("\n[!] Render tag missing — check theme.liquid manually")
        sys.exit(1)
    if not has_robots:
        print("\n[!] Robots tag missing — check theme.liquid manually")
        sys.exit(1)

    print("\n[OK] Theme is clean. Single schema source: snippets/meeeshop-jsonld.liquid")

    if args.purge_metafields:
        purge_json_ld_metafields()

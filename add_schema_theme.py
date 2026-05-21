"""
Add Schema Rendering Code to Shopify Theme
Injects JSON-LD schema rendering code into theme.liquid
"""
import os
import sys
import json
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from secrets_manager import inject_to_env, get_secret
inject_to_env()

STORE = get_secret("SHOPIFY_STORE")
TOKEN = get_secret("SHOPIFY_ACCESS_TOKEN")
THEME_ID = get_secret("LIVE_THEME_ID")
ASSET_KEY = "layout/theme.liquid"

BASE_URL = f"https://{STORE}/admin/api/2024-01"
HEADERS = {
    "X-Shopify-Access-Token": TOKEN,
    "Content-Type": "application/json"
}

# Schema rendering code to inject
SCHEMA_CODE = '''<!-- JSON-LD Schema Rendering -->
{% if product %}
  {% for metafield in product.metafields.json_ld_schema %}
    <script type="application/ld+json">{{ metafield.value | json }}</script>
  {% endfor %}
{% endif %}

{% if collection %}
  {% for metafield in collection.metafields.json_ld_schema %}
    <script type="application/ld+json">{{ metafield.value | json }}</script>
  {% endfor %}
{% endif %}

{% if page %}
  {% for metafield in page.metafields.json_ld_schema %}
    <script type="application/ld+json">{{ metafield.value | json }}</script>
  {% endfor %}
{% endif %}

{% if article %}
  {% for metafield in article.metafields.json_ld_schema %}
    <script type="application/ld+json">{{ metafield.value | json }}</script>
  {% endfor %}
{% endif %}

<!-- Global Organization Schema -->
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "Organization",
  "name": "MeeeShop",
  "url": "https://us.meeeshop.com",
  "contactPoint": {
    "@type": "ContactPoint",
    "email": "meeeshop17@gmail.com"
  }
}
</script>
'''

def get_theme_liquid():
    """Fetch current theme.liquid"""
    print(f"[*] Fetching theme.liquid from theme {THEME_ID}...")
    url = f"{BASE_URL}/themes/{THEME_ID}/assets.json?asset[key]={ASSET_KEY}"

    resp = requests.get(url, headers=HEADERS)
    if resp.status_code != 200:
        print(f"[!] Error fetching theme.liquid: {resp.status_code}")
        print(resp.text)
        return None

    return resp.json()["asset"]["value"]

def check_code_exists(content):
    """Check if schema code already exists"""
    return "JSON-LD Schema Rendering" in content

def inject_schema_code(content):
    """Inject schema code before </head>"""
    if check_code_exists(content):
        print("[!] Schema code already exists in theme.liquid")
        return None

    # Find </head> tag
    if "</head>" not in content:
        print("[!] Error: </head> tag not found in theme.liquid")
        return None

    # Insert before </head>
    new_content = content.replace("</head>", SCHEMA_CODE + "\n  </head>")
    return new_content

def update_theme_liquid(new_content):
    """Update theme.liquid with new content"""
    print(f"[*] Updating theme.liquid...")
    url = f"{BASE_URL}/themes/{THEME_ID}/assets.json"

    payload = {
        "asset": {
            "key": ASSET_KEY,
            "value": new_content
        }
    }

    resp = requests.put(url, headers=HEADERS, json=payload)
    if resp.status_code not in [200, 201]:
        print(f"[!] Error updating theme.liquid: {resp.status_code}")
        print(resp.text)
        return False

    print("[+] [OK] theme.liquid updated successfully")
    return True

def verify_code_added():
    """Verify code was added"""
    print("[*] Verifying code was added...")
    content = get_theme_liquid()
    if not content:
        return False

    if check_code_exists(content):
        print("[+] [OK] Schema rendering code confirmed in theme.liquid")
        return True
    else:
        print("[!] Schema code not found - verification failed")
        return False

if __name__ == "__main__":
    print("=" * 70)
    print("ADDING SCHEMA RENDERING CODE TO SHOPIFY THEME")
    print("=" * 70)
    print(f"Store: {STORE}")
    print(f"Theme ID: {THEME_ID}")
    print(f"Asset: {ASSET_KEY}\n")

    # Step 1: Fetch current theme.liquid
    current_content = get_theme_liquid()
    if not current_content:
        print("[!] Failed to fetch theme.liquid. Exiting.")
        exit(1)

    print(f"[+] [OK] Retrieved theme.liquid ({len(current_content)} bytes)")

    # Step 2: Check if code already exists
    if check_code_exists(current_content):
        print("[!] Schema code already exists - skipping")
        print("\n" + "=" * 70)
        print("VERIFICATION RESULT: [OK] SCHEMA CODE ALREADY IN PLACE")
        print("=" * 70)
        exit(0)

    # Step 3: Inject schema code
    new_content = inject_schema_code(current_content)
    if not new_content:
        print("[!] Failed to inject code. Exiting.")
        exit(1)

    print(f"[+] [OK] Schema code ready to inject ({len(SCHEMA_CODE)} bytes)")

    # Step 4: Update theme
    if not update_theme_liquid(new_content):
        print("[!] Failed to update theme. Exiting.")
        exit(1)

    # Step 5: Verify
    if verify_code_added():
        print("\n" + "=" * 70)
        print("SUCCESS: SCHEMA RENDERING CODE ADDED & VERIFIED")
        print("=" * 70)
        print("\nTheme code status:")
        print("  [OK] JSON-LD schema rendering for products")
        print("  [OK] JSON-LD schema rendering for collections")
        print("  [OK] JSON-LD schema rendering for pages")
        print("  [OK] JSON-LD schema rendering for blog articles")
        print("  [OK] Global Organization schema")
        print("\nNext step: Trigger first schema validation run in GitHub Actions")
    else:
        print("\n[!] Verification failed")
        exit(1)

import os
import requests
from dotenv import load_dotenv

load_dotenv()
STORE = os.getenv("SHOPIFY_STORE")
TOKEN = os.getenv("SHOPIFY_ACCESS_TOKEN")
THEME_ID = "155143110827"
ASSET_KEY = "layout/theme.liquid"

BASE_URL = f"https://{STORE}/admin/api/2024-01"
HEADERS = {
    "X-Shopify-Access-Token": TOKEN,
    "Content-Type": "application/json"
}

url = f"{BASE_URL}/themes/{THEME_ID}/assets.json?asset[key]={ASSET_KEY}"
resp = requests.get(url, headers=HEADERS)

if resp.status_code == 200:
    content = resp.json()["asset"]["value"]

    # Check for schema code
    if "JSON-LD Schema Rendering" in content:
        print("[OK] Schema code FOUND in theme.liquid")

        # Find position
        pos = content.find("JSON-LD Schema Rendering")
        snippet = content[pos:pos+200]
        print(f"\nSnippet from position {pos}:")
        print(snippet)
    else:
        print("[!] Schema code NOT FOUND in theme.liquid")

        # Check for </head>
        if "</head>" in content:
            pos = content.find("</head>")
            snippet = content[pos-200:pos+100]
            print(f"\nContext around </head> (position {pos}):")
            print(snippet)
        else:
            print("[!] </head> tag not found either!")

    print(f"\nTotal file size: {len(content)} bytes")
else:
    print(f"Error: {resp.status_code}")
    print(resp.text)

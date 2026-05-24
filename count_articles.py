"""Used by CI to count total published articles across all blogs — prints the number only."""
import sys
sys.path.insert(0, ".")
from secrets_manager import inject_to_env, get_secret
inject_to_env()
import requests

store = get_secret("SHOPIFY_STORE")
token = get_secret("SHOPIFY_ACCESS_TOKEN")
headers = {"X-Shopify-Access-Token": token}
base = f"https://{store}/admin/api/2024-10"

blogs_r = requests.get(f"{base}/blogs.json", headers=headers, timeout=30)
blogs_r.raise_for_status()
blogs = blogs_r.json().get("blogs", [])

total = 0
for blog in blogs:
    r = requests.get(
        f"{base}/blogs/{blog['id']}/articles/count.json",
        headers=headers,
        params={"published_status": "published"},
        timeout=30,
    )
    r.raise_for_status()
    total += r.json().get("count", 0)

print(total)

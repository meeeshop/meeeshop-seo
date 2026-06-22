import sys
sys.path.insert(0, "scripts")
from secrets_manager import inject_to_env, get_secret
inject_to_env()
import requests

shop = get_secret("SHOPIFY_STORE")
token = get_secret("SHOPIFY_ACCESS_TOKEN")
r = requests.get(
    f"https://{shop}/admin/api/2024-10/blogs.json",
    headers={"X-Shopify-Access-Token": token}
)
for b in r.json().get("blogs", []):
    print(f"  ID: {b['id']}  Handle: {b['handle']:<30}  Title: {b['title']}")

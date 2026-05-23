"""Used by CI to count active products and print the number — nothing else."""
import sys
sys.path.insert(0, ".")
from secrets_manager import inject_to_env, get_secret
inject_to_env()
import requests

store = get_secret("SHOPIFY_STORE")
token = get_secret("SHOPIFY_ACCESS_TOKEN")
url = f"https://{store}/admin/api/2025-01/products/count.json"
r = requests.get(url, headers={"X-Shopify-Access-Token": token},
                 params={"status": "active"}, timeout=30)
r.raise_for_status()
print(r.json()["count"])

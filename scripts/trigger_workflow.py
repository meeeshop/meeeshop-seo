import os
import sys
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from secrets_manager import inject_to_env, get_secret
inject_to_env()

# GitHub info
GITHUB_TOKEN = get_secret("GITHUB_TOKEN")
if not GITHUB_TOKEN:
    print("[!] Error: GITHUB_TOKEN not set in .env")
    print("Set it with: echo 'GITHUB_TOKEN=your_token' >> .env")
    exit(1)

# GitHub repo info
REPO_OWNER = "meeeshop"
REPO_NAME = "meeeshop-seo"


print("=" * 70)
print("TRIGGERING GITHUB ACTIONS WORKFLOW")
print("=" * 70)
print(f"Repository: {REPO_OWNER}/{REPO_NAME}")
print(f"Workflow: schema_validation_daily.yml")
print(f"Mode: force (full audit)\n")

url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/actions/workflows/schema_validation_daily.yml/dispatches"
headers = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}
payload = {
    "ref": "main",  # or your default branch
    "inputs": {
        "run_mode": "force"
    }
}

resp = requests.post(url, headers=headers, json=payload)

print(f"Response status: {resp.status_code}")
if resp.status_code in [204]:  # 204 No Content = success
    print("[OK] Workflow triggered successfully!")
    print("\nNext steps:")
    print("1. Go to: https://github.com/{}/{}/actions".format(REPO_OWNER, REPO_NAME))
    print("2. Click on 'Daily Schema Validation & Page Speed Optimization'")
    print("3. Look for the latest run (should appear in ~30 seconds)")
    print("4. Wait 5-10 minutes for completion")
    print("5. Download artifacts to review results")
elif resp.status_code in [401, 403]:
    print("[!] Authentication failed - check GITHUB_TOKEN")
    print(resp.text)
else:
    print(f"[!] Error: {resp.status_code}")
    print(resp.text)

import os
import sys
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.secrets_manager import inject_to_env, get_secret

def main():
    inject_to_env()
    
    token = get_secret("GITHUB_TOKEN")
    if not token:
        print("[!] Error: GITHUB_TOKEN not found in secrets.")
        sys.exit(1)
        
    owner = "meeeshop"
    repo = "meeeshop-seo"
    workflow = "category_metafields_daily.yml"
    
    print(f"Triggering GitHub Action workflow: {workflow} on branch 'develop'...")
    url = f"https://api.github.com/repos/{owner}/{repo}/actions/workflows/{workflow}/dispatches"
    
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    }
    payload = {
        "ref": "develop",
        "inputs": {
            "action": "apply",
            "mode": "daily"
        }
    }
    
    resp = requests.post(url, headers=headers, json=payload)
    print(f"Status Code: {resp.status_code}")
    if resp.status_code == 204:
        print("[OK] Workflow triggered successfully!")
        print(f"You can view the workflow runs at: https://github.com/{owner}/{repo}/actions/workflows/{workflow}")
    else:
        print(f"[!] Error triggering workflow: {resp.text}")

if __name__ == "__main__":
    main()

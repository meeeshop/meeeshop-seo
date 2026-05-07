#!/usr/bin/env python3
"""
enable_pr_policy.py — Enable branch protection (PR required) on both repos.
All commits must go through a pull request — direct pushes to main are blocked.
"""

import sys, requests

TOKEN = "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"
REPOS = ["meeeshop/meeeshop-seo", "meeeshop/meeeshop-youtube"]

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

RULESET = {
    "name": "require-pr-main",
    "target": "branch",
    "enforcement": "active",
    "conditions": {
        "ref_name": {
            "include": ["refs/heads/main"],
            "exclude": [],
        }
    },
    "rules": [
        {"type": "pull_request",
         "parameters": {
             "required_approving_review_count": 0,
             "dismiss_stale_reviews_on_push": False,
             "require_code_owner_review": False,
             "require_last_push_approval": False,
             "required_review_thread_resolution": False,
         }},
        {"type": "deletion"},
        {"type": "non_fast_forward"},
    ],
}

for repo in REPOS:
    url = f"https://api.github.com/repos/{repo}/rulesets"
    r = requests.post(url, headers=HEADERS, json=RULESET)
    if r.status_code in (200, 201):
        print(f"OK  {repo} — PR ruleset created on main")
    else:
        print(f"ERR {repo} — {r.status_code}: {r.text[:250]}")

#!/usr/bin/env python3
"""
set_secrets.py — Set GitHub Actions secrets on both repos using the API.
Uses PyNaCl for encryption (as required by GitHub's API).
"""

import base64, sys, requests
from nacl import encoding, public

# ── config ─────────────────────────────────────────────────────────────────
GITHUB_TOKEN    = "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"
GITHUB_TOKEN_YT = "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"

SECRETS = {
    "GEMINI_API_KEY":     "AIzaSyA_XygT6JKLzRynOM1N-8ecSGEMAJrATJQ",
    "GROQ_API_KEY":       "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",
    "OPENROUTER_API_KEY": "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",
}

REPOS = [
    ("meeeshop/meeeshop-seo",     GITHUB_TOKEN),
    ("meeeshop/meeeshop-youtube", GITHUB_TOKEN_YT),
]


def encrypt(public_key_str: str, secret_value: str) -> str:
    pk = public.PublicKey(public_key_str.encode(), encoding.Base64Encoder())
    box = public.SealedBox(pk)
    encrypted = box.encrypt(secret_value.encode())
    return base64.b64encode(encrypted).decode()


def get_public_key(repo: str, token: str) -> tuple[str, str]:
    url = f"https://api.github.com/repos/{repo}/actions/secrets/public-key"
    r = requests.get(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    })
    r.raise_for_status()
    data = r.json()
    return data["key_id"], data["key"]


def set_secret(repo: str, token: str, name: str, value: str, key_id: str, pub_key: str):
    encrypted = encrypt(pub_key, value)
    url = f"https://api.github.com/repos/{repo}/actions/secrets/{name}"
    r = requests.put(url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        },
        json={"encrypted_value": encrypted, "key_id": key_id},
    )
    if r.status_code in (201, 204):
        print(f"  OK {name}")
    else:
        print(f"  ✗ {name}: {r.status_code} {r.text[:100]}")


if __name__ == "__main__":
    for repo, token in REPOS:
        print(f"\n{repo}")
        try:
            key_id, pub_key = get_public_key(repo, token)
            for name, value in SECRETS.items():
                set_secret(repo, token, name, value, key_id, pub_key)
        except Exception as e:
            print(f"  ERROR: {e}")
    print("\nDone.")

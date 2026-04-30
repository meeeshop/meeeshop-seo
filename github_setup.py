"""
One-time script: creates all GitHub repo secrets and pushes code.
Run once, then delete this file.
"""
import requests
import base64
import os
import subprocess
from nacl import encoding, public

GITHUB_TOKEN = "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"
OWNER        = "meeeshop"
REPO         = "meeeshop-youtube"

SECRETS = {
    "SHOPIFY_STORE":          "us-meeeshop.myshopify.com",
    "SHOPIFY_ACCESS_TOKEN":   "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",
    "YOUTUBE_CLIENT_ID":      "571964116396-ogn8b0dkis7ejaiepm2t9j20v2k7r2um.apps.googleusercontent.com",
    "YOUTUBE_CLIENT_SECRET":  "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",
    "YOUTUBE_REFRESH_TOKEN":  "1//0gL_O-eonic_iCgYIARAAGBASNwF-L9Iriu-C_JMFSHQEjcom4tlrbGzjFWgsNVCdZKrWJKg5_EbpVaJJe8GWm2bYAAO8s9YbwsM",
}

HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
    "User-Agent": "MeeeShop-Setup",
}


def encrypt_secret(public_key_b64: str, secret_value: str) -> str:
    pk = public.PublicKey(public_key_b64.encode(), encoding.Base64Encoder())
    box = public.SealedBox(pk)
    encrypted = box.encrypt(secret_value.encode())
    return base64.b64encode(encrypted).decode()


def get_repo_public_key():
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/actions/secrets/public-key"
    r = requests.get(url, headers=HEADERS)
    r.raise_for_status()
    return r.json()


def create_secret(key_data, name, value):
    encrypted = encrypt_secret(key_data["key"], value)
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/actions/secrets/{name}"
    r = requests.put(url, headers=HEADERS,
                     json={"encrypted_value": encrypted, "key_id": key_data["key_id"]})
    if r.status_code in (201, 204):
        print(f"  [OK] {name}")
    else:
        print(f"  [FAIL] {name}: {r.status_code} {r.text}")


def push_code():
    repo_dir = os.path.dirname(os.path.abspath(__file__))
    remote   = f"https://{GITHUB_TOKEN}@github.com/{OWNER}/{REPO}.git"

    cmds = [
        ["git", "init"],
        ["git", "add", "."],
        ["git", "commit", "-m", "Initial MeeeShop YouTube automation"],
        ["git", "branch", "-M", "main"],
        ["git", "remote", "remove", "origin"],   # ignore error if not set
        ["git", "remote", "add", "origin", remote],
        ["git", "push", "-u", "origin", "main", "--force"],
    ]

    for cmd in cmds:
        result = subprocess.run(cmd, cwd=repo_dir, capture_output=True, text=True)
        label = " ".join(cmd[:3])
        if result.returncode == 0:
            print(f"  [OK] {label}")
        else:
            # remote remove failing is expected if remote didn't exist yet
            if "remote remove" in label and "No such remote" in result.stderr:
                print(f"  [skip] remote remove (not set yet)")
            else:
                print(f"  [WARN] {label}: {result.stderr.strip()[:120]}")


def configure_git_user():
    subprocess.run(["git", "config", "user.email", "meeeshop17@gmail.com"], capture_output=True)
    subprocess.run(["git", "config", "user.name",  "MeeeShop"],             capture_output=True)


if __name__ == "__main__":
    print("=== MeeeShop GitHub Setup ===\n")

    print("Step 1: Creating GitHub Secrets...")
    key_data = get_repo_public_key()
    for name, value in SECRETS.items():
        create_secret(key_data, name, value)

    print("\nStep 2: Configuring git...")
    configure_git_user()

    print("\nStep 3: Pushing code to GitHub...")
    push_code()

    print("\n=== Done! ===")
    print(f"Repo: https://github.com/{OWNER}/{REPO}")
    print("GitHub Actions will run every day at 8 AM EST automatically.")
    print("\nDELETE this file now (it contains your secrets).")

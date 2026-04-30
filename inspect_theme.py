"""
Shopify Theme Inspector & Backup Tool
Fetches active theme, lists all assets, and downloads a full backup.
"""

import urllib.request
import urllib.error
import json
import os
import zipfile
import time
from datetime import datetime

TOKEN = "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"
SHOP  = "us-meeeshop.myshopify.com"
API   = "2025-01"
HEADERS = {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}


def get(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def get_asset(theme_id, key):
    url = f"https://{SHOP}/admin/api/{API}/themes/{theme_id}/assets.json?asset[key]={urllib.request.quote(key)}"
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read()).get("asset", {})
    except urllib.error.HTTPError:
        return {}


def main():
    print("=" * 60)
    print("SHOPIFY THEME INSPECTOR")
    print("=" * 60)

    # ── 1. List all themes ────────────────────────────────────────
    print("\n[1/4] Fetching themes...")
    themes = get(f"https://{SHOP}/admin/api/{API}/themes.json")["themes"]

    print("\nAll themes on your store:")
    for t in themes:
        marker = "  <<< LIVE (Active)" if t["role"] == "main" else ""
        print(f"  • {t['name']:40s}  ID: {t['id']}  Role: {t['role']}{marker}")

    active = next(t for t in themes if t["role"] == "main")
    theme_id   = active["id"]
    theme_name = active["name"]
    print(f"\nActive theme: {theme_name} (ID: {theme_id})")

    # ── 2. Fetch all asset keys ───────────────────────────────────
    print("\n[2/4] Fetching asset list...")
    assets_data = get(f"https://{SHOP}/admin/api/{API}/themes/{theme_id}/assets.json")
    assets = assets_data["assets"]
    print(f"  Total assets: {len(assets)}")

    # Categorise
    categories = {}
    for a in assets:
        folder = a["key"].split("/")[0]
        categories.setdefault(folder, []).append(a["key"])

    print("\n  Asset breakdown:")
    for folder, keys in sorted(categories.items()):
        print(f"    {folder:20s} -> {len(keys)} files")

    # ── 3. Download & backup theme ────────────────────────────────
    backup_dir = os.path.join(os.path.dirname(__file__), "theme_backup")
    os.makedirs(backup_dir, exist_ok=True)

    print(f"\n[3/4] Downloading theme files to ./theme_backup/ ...")
    downloaded = 0
    skipped    = 0

    # Only download text-based assets (Liquid, CSS, JS, JSON, SVG)
    text_exts = {".liquid", ".css", ".scss", ".js", ".json", ".txt", ".svg", ".html", ".md"}

    for a in assets:
        key = a["key"]
        ext = os.path.splitext(key)[1].lower()
        if ext not in text_exts:
            skipped += 1
            continue

        dest = os.path.join(backup_dir, key.replace("/", os.sep))
        os.makedirs(os.path.dirname(dest), exist_ok=True)

        asset = get_asset(theme_id, key)
        content = asset.get("value") or asset.get("attachment", "")
        if content:
            mode = "wb" if asset.get("attachment") else "w"
            enc  = {} if asset.get("attachment") else {"encoding": "utf-8"}
            with open(dest, mode, **enc) as f:
                f.write(content)
            downloaded += 1

        time.sleep(0.15)  # stay under API rate limit

    print(f"  Downloaded: {downloaded} files  |  Skipped (images/fonts): {skipped}")

    # ── 4. Zip the backup ─────────────────────────────────────────
    print("\n[4/4] Creating zip archive...")
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_name = os.path.join(os.path.dirname(__file__), f"theme_backup_{ts}.zip")
    with zipfile.ZipFile(zip_name, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(backup_dir):
            for f in files:
                fp = os.path.join(root, f)
                zf.write(fp, os.path.relpath(fp, backup_dir))

    size_kb = os.path.getsize(zip_name) // 1024
    print(f"  Backup saved: theme_backup_{ts}.zip  ({size_kb} KB)")

    # ── 5. Summary report ─────────────────────────────────────────
    print("\n" + "=" * 60)
    print("BACKUP COMPLETE")
    print("=" * 60)
    print(f"  Theme name : {theme_name}")
    print(f"  Theme ID   : {theme_id}")
    print(f"  Files saved: {downloaded}")
    print(f"  Zip file   : theme_backup_{ts}.zip")
    print(f"  Raw files  : ./theme_backup/")
    print()

    # Return key info for analysis
    return theme_id, theme_name, categories, assets


if __name__ == "__main__":
    main()

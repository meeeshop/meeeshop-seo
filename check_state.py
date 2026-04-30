import json, os

# Check SEO backup
seo_file = "seo_backup_20260430_152031.json"
with open(seo_file) as f:
    d = json.load(f)

products = d.get("products", [])
print(f"=== SEO BACKUP: {len(products)} products ===")
for p in products[:15]:
    title = p.get("title", "")[:45]
    seo   = p.get("seo_title") or p.get("title", "")
    print(f"  {title:45s} | {seo[:40]}")

# Check theme backup
backup_dir = "theme_backup"
if os.path.exists(backup_dir):
    folders = {}
    for root, dirs, files in os.walk(backup_dir):
        rel = os.path.relpath(root, backup_dir)
        if rel != ".":
            folder = rel.split(os.sep)[0]
            folders[folder] = folders.get(folder, 0) + len(files)
    print(f"\n=== THEME BACKUP: {sum(folders.values())} files ===")
    for k, v in sorted(folders.items()):
        print(f"  {k:20s} -> {v} files")

# Check YouTube short
mp4 = [f for f in os.listdir(".") if f.endswith(".mp4")]
print(f"\n=== YOUTUBE SHORTS: {mp4} ===")

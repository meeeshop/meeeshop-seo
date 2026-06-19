import json

with open("scratch/backup_prices_under_40_20260615_035556.json", "r", encoding="utf-8") as f:
    data = json.load(f)

bags = []
for p in data["products"]:
    title = p["title"].lower()
    if any(x in title for x in ["tote", "bag", "crossbody", "clutch"]):
        bags.append(p)

print(f"Total handbag/bag products found in update list: {len(bags)}")
print("\nHere are details of 3 of them:")
for p in bags[:3]:
    print(f"\nProduct: {p['title']} ({p['id']})")
    for v in p["variants"]:
        print(f"  Variant SKU: {v['sku']} | Original Price: ${v['price']}")

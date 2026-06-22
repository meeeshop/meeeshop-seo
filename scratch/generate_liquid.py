import json

with open("scratch/matched_collections.json", "r", encoding="utf-8") as f:
    matched = json.load(f)

# Sort them alphabetically or keep sitemap order. Let's keep sitemap order.
keywords = [item[0] for item in matched]
handles = [item[1] for item in matched]

keywords_str = "|".join(keywords)
handles_str = "|".join(handles)

print("KEYWORDS:")
print(keywords_str)
print("\nHANDLES:")
print(handles_str)
print(f"\nTotal items: {len(matched)}")

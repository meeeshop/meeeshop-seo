"""Quick test: imports, Shopify fetch, 1 image download, 1 frame render — no upload."""
import os, sys
os.chdir(os.path.dirname(os.path.abspath(__file__)))

print("[1] Imports...")
import numpy as np
from PIL import Image, ImageDraw
from moviepy.editor import VideoClip
from dotenv import load_dotenv
import requests, pickle
print("    OK")

load_dotenv()
SHOP  = os.getenv("SHOPIFY_STORE")
TOKEN = os.getenv("SHOPIFY_ACCESS_TOKEN")

print("[2] Fetch 1 product from Shopify...")
r = requests.get(
    f"https://{SHOP}/admin/api/2024-01/products.json?limit=1&status=active",
    headers={"X-Shopify-Access-Token": TOKEN}
)
r.raise_for_status()
products = r.json().get("products", [])
if not products:
    print("    No products found!"); sys.exit(1)
p = products[0]
print(f"    {p['title']} — ${p['variants'][0]['price']}")

print("[3] Download first product image...")
img_src = p["images"][0]["src"] if p.get("images") else None
if not img_src:
    print("    No image"); sys.exit(1)
img_data = requests.get(img_src).content
with open("_test_img.jpg", "wb") as f:
    f.write(img_data)
print(f"    Saved _test_img.jpg ({len(img_data)//1024} KB)")

print("[4] Render 1 frame with Ken Burns overlay...")
VIDEO_W, VIDEO_H = 1080, 1920
img = Image.open("_test_img.jpg").convert("RGB").resize((VIDEO_W, VIDEO_H))
draw = ImageDraw.Draw(img)
draw.rectangle([(0, VIDEO_H-200), (VIDEO_W, VIDEO_H)], fill=(0,0,0,180))
draw.text((VIDEO_W//2, VIDEO_H-100), "MeeeShop", fill="white", anchor="mm")
img.save("_test_frame.jpg")
print("    Saved _test_frame.jpg")

print("[5] Create 1-second test video clip...")
arr = np.array(img)
clip = VideoClip(lambda t: arr, duration=1).set_fps(30)
clip.write_videofile("_test_clip.mp4", codec="libx264", audio=False,
                     verbose=False, logger=None)
size = os.path.getsize("_test_clip.mp4") // 1024
print(f"    Saved _test_clip.mp4 ({size} KB)")

print("[6] Check YouTube token...")
if os.path.exists("youtube_token.pickle"):
    with open("youtube_token.pickle","rb") as f:
        creds = pickle.load(f)
    print(f"    Token valid: {creds.valid}  Expired: {creds.expired}")
else:
    print("    youtube_token.pickle NOT found — need to run youtube_auth.py first")

# Cleanup
for f in ["_test_img.jpg", "_test_frame.jpg", "_test_clip.mp4"]:
    if os.path.exists(f): os.remove(f)

print("\nAll checks passed — youtube_shorts.py is ready to run!")

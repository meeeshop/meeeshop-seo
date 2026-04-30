import os
import platform
import requests
import pickle
import numpy as np
import random
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import (VideoClip, concatenate_videoclips,
                             AudioFileClip, CompositeAudioClip)
from gtts import gTTS
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from dotenv import load_dotenv
from scipy.io import wavfile
import shutil
import textwrap

load_dotenv()

SHOPIFY_STORE  = os.getenv("SHOPIFY_STORE")
SHOPIFY_TOKEN  = os.getenv("SHOPIFY_ACCESS_TOKEN")

VIDEO_W        = 1080
VIDEO_H        = 1920
FPS            = 30
IMG_DURATION   = 3
YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]

# Cross-platform fonts
if platform.system() == "Windows":
    FONT_BOLD = r"C:\Windows\Fonts\arialbd.ttf"
    FONT_REG  = r"C:\Windows\Fonts\arial.ttf"
else:
    FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    FONT_REG  = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

POSTING_SLOTS_EST = {
    0: [12, 19, 21], 1: [12, 19, 21], 2: [12, 19, 21],
    3: [12, 19, 21], 4: [12, 19, 21], 5: [11, 14, 20], 6: [11, 14, 20],
}


# ─── Background music generator ──────────────────────────────────────────────

def generate_bg_music(duration=90, bpm=115, sr=22050, out_path="bg_music.wav"):
    """Generate a lo-fi fashion beat: kick, snare, hi-hat, bass, synth pad."""
    samples = int(sr * duration)
    beat    = int(sr * 60 / bpm)
    out     = np.zeros(samples)

    # Kick drum — beats 1 & 3 (pitch sweep 180→40 Hz)
    for i in range(0, samples, beat * 2):
        n = min(int(sr * 0.12), samples - i)
        if n <= 0: continue
        freqs  = np.linspace(180, 40, n)
        kick   = np.sin(2 * np.pi * np.cumsum(freqs) / sr)
        env    = np.exp(-np.linspace(0, 12, n))
        out[i:i+n] += 0.85 * kick * env

    # Snare/clap — beats 2 & 4
    for i in range(beat, samples, beat * 2):
        n = min(int(sr * 0.07), samples - i)
        if n <= 0: continue
        env   = np.exp(-np.linspace(0, 22, n))
        tone  = np.sin(2 * np.pi * 220 * np.arange(n) / sr)
        noise = np.random.randn(n)
        out[i:i+n] += 0.45 * (noise * 0.65 + tone * 0.35) * env

    # Hi-hat — every 8th note
    for i in range(0, samples, beat // 2):
        n = min(int(sr * 0.018), samples - i)
        if n <= 0: continue
        env  = np.exp(-np.linspace(0, 35, n))
        # high-pass noise
        noise = np.random.randn(n)
        out[i:i+n] += 0.18 * noise * env

    # Sub bass — follows kick, simple sine
    bass_freqs = [65, 73, 55, 65]
    for idx, start in enumerate(range(0, samples, beat * 2)):
        n = min(beat * 2, samples - start)
        if n <= 0: continue
        freq   = bass_freqs[idx % len(bass_freqs)]
        t_loc  = np.arange(n) / sr
        fade     = np.ones(n)
        fade_len = max(1, n // 5)
        fade[n - fade_len:] = np.linspace(1, 0, fade_len)
        out[start:start+n] += 0.35 * np.sin(2 * np.pi * freq * t_loc) * fade

    # Synth pad — warm chord (F major: F C A)
    pad_freqs = [174.61, 220.00, 261.63, 349.23]
    t_full = np.arange(samples) / sr
    for freq in pad_freqs:
        # Slight vibrato + soft attack
        vibrato = 1 + 0.003 * np.sin(2 * np.pi * 4.5 * t_full)
        pad = 0.06 * np.sin(2 * np.pi * freq * t_full * vibrato)
        out += pad

    # Open hi-hat accent every bar
    for i in range(0, samples, beat * 4):
        n = min(int(sr * 0.06), samples - i)
        if n <= 0: continue
        env  = np.exp(-np.linspace(0, 10, n))
        noise = np.random.randn(n)
        out[i:i+n] += 0.22 * noise * env

    # Normalize & fade in/out
    out = np.clip(out / (np.max(np.abs(out)) + 1e-6) * 0.80, -1.0, 1.0)
    fade_len = int(sr * 1.5)
    out[:fade_len]  *= np.linspace(0, 1, fade_len)
    out[-fade_len:] *= np.linspace(1, 0, fade_len)

    wavfile.write(out_path, sr, out.astype(np.float32))
    return out_path


def get_or_create_bg_music():
    wav = "bg_music.wav"
    mp3 = "bg_music.mp3"
    # Prefer mp3 if it exists (user-supplied), else use/create wav
    if os.path.exists(mp3):
        return mp3
    if not os.path.exists(wav):
        print("Generating background music...")
        generate_bg_music(out_path=wav)
    return wav


# ─── Shopify ─────────────────────────────────────────────────────────────────

def fetch_all_products(limit=50):
    headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN}
    url = f"https://{SHOPIFY_STORE}/admin/api/2024-01/products.json?limit={limit}&status=active"
    r = requests.get(url, headers=headers)
    r.raise_for_status()
    return r.json().get("products", [])


def fetch_random_product():
    products = fetch_all_products()
    if not products:
        raise RuntimeError("No active products found.")
    p = random.choice(products)
    print(f"Selected: {p['title']}")
    return p


def download_images(product, tmp_dir):
    os.makedirs(tmp_dir, exist_ok=True)
    paths = []
    for i, img in enumerate(product.get("images", [])[:6]):
        dest = os.path.join(tmp_dir, f"img_{i}.jpg")
        r = requests.get(img["src"], stream=True)
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
        paths.append(dest)
        print(f"  Image {i+1}")
    return paths


# ─── Shared draw helpers ──────────────────────────────────────────────────────

def _font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def _prep_image(img_path):
    img = Image.open(img_path).convert("RGB")
    target_ratio = VIDEO_W / VIDEO_H
    w, h = img.size
    if w / h > target_ratio:
        new_w = int(h * target_ratio)
        img = img.crop(((w - new_w) // 2, 0, (w - new_w) // 2 + new_w, h))
    else:
        new_h = int(w / target_ratio)
        img = img.crop((0, (h - new_h) // 2, w, (h - new_h) // 2 + new_h))
    return img.resize((VIDEO_W, VIDEO_H), Image.LANCZOS)


def _gradient(img, top_rgba, bottom_rgba, y_start=0, y_end=None):
    if y_end is None: y_end = VIDEO_H
    height = y_end - y_start
    overlay = Image.new("RGBA", (VIDEO_W, VIDEO_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for y in range(height):
        t = y / height
        r = int(top_rgba[0] + t * (bottom_rgba[0] - top_rgba[0]))
        g = int(top_rgba[1] + t * (bottom_rgba[1] - top_rgba[1]))
        b = int(top_rgba[2] + t * (bottom_rgba[2] - top_rgba[2]))
        a = int(top_rgba[3] + t * (bottom_rgba[3] - top_rgba[3]))
        draw.line([(0, y_start + y), (VIDEO_W, y_start + y)], fill=(r, g, b, a))
    img = img.convert("RGBA")
    img.alpha_composite(overlay)
    return img.convert("RGB")


def _draw_logo(draw):
    font = _font(FONT_BOLD, 36)
    bx0, by0, bx1, by1 = 28, 38, 272, 92
    draw.rounded_rectangle([(bx0, by0), (bx1, by1)], radius=22, fill="white")
    draw.text(((bx0+bx1)//2, (by0+by1)//2), "MeeeShop",
              font=font, fill="black", anchor="mm")


def _draw_title(draw, title, y, color=(255, 255, 255)):
    font = _font(FONT_BOLD, 60)
    for line in textwrap.wrap(title, width=22)[:3]:
        draw.text((VIDEO_W//2, y), line, font=font, fill=color,
                  anchor="mm", stroke_width=3, stroke_fill=(0, 0, 0, 160))
        y += 74


def _draw_price(draw, price, color=(255, 215, 0)):
    font = _font(FONT_BOLD, 76)
    draw.text((VIDEO_W//2, VIDEO_H-215), f"${price}",
              font=font, fill=color, anchor="mm",
              stroke_width=3, stroke_fill=(0, 0, 0))


def _draw_cta(draw, bg, fg, text="Shop Now ->"):
    y0, y1 = VIDEO_H-140, VIDEO_H-68
    draw.rounded_rectangle([(VIDEO_W//2-210, y0), (VIDEO_W//2+210, y1)],
                            radius=35, fill=bg)
    draw.text((VIDEO_W//2, (y0+y1)//2), text,
              font=_font(FONT_BOLD, 44), fill=fg, anchor="mm")


def _draw_url_overlay(draw, url):
    """Show tappable URL in last-frame overlay."""
    font = _font(FONT_BOLD, 34)
    label_font = _font(FONT_REG, 28)
    # Semi-transparent pill
    py0, py1 = VIDEO_H - 240, VIDEO_H - 185
    draw.rounded_rectangle([(50, py0), (VIDEO_W-50, py1)],
                            radius=20, fill=(255, 255, 255, 220))
    draw.text((VIDEO_W//2, py0+15), "TAP LINK IN DESCRIPTION TO SHOP",
              font=label_font, fill=(120, 120, 120), anchor="mt")
    draw.text((VIDEO_W//2, py0+42), url,
              font=font, fill=(0, 100, 220), anchor="mt")


# ─── 5 Video Templates ────────────────────────────────────────────────────────

def template_dark_luxury(img_path, title, price, url, show_url=False):
    img = _prep_image(img_path)
    img = _gradient(img, (10,10,20,60), (5,5,15,220), VIDEO_H-700, VIDEO_H)
    draw = ImageDraw.Draw(img)
    _draw_logo(draw)
    draw.rectangle([(60,VIDEO_H-560),(VIDEO_W-60,VIDEO_H-554)], fill=(212,175,55))
    _draw_title(draw, title, VIDEO_H-510, (255,255,255))
    _draw_price(draw, price, (212,175,55))
    _draw_cta(draw, (212,175,55), "black")
    if show_url: _draw_url_overlay(draw, url)
    return img

def template_clean_minimal(img_path, title, price, url, show_url=False):
    img = _prep_image(img_path)
    img = _gradient(img, (255,255,255,0), (255,255,255,230), VIDEO_H-700, VIDEO_H)
    draw = ImageDraw.Draw(img)
    _draw_logo(draw)
    _draw_title(draw, title, VIDEO_H-500, (20,20,20))
    _draw_price(draw, price, (220,50,80))
    _draw_cta(draw, (20,20,20), "white")
    if show_url: _draw_url_overlay(draw, url)
    return img

def template_vibrant_pop(img_path, title, price, url, show_url=False):
    img = _prep_image(img_path)
    img = _gradient(img, (120,0,180,20), (220,20,100,210), VIDEO_H-700, VIDEO_H)
    draw = ImageDraw.Draw(img)
    _draw_logo(draw)
    _draw_title(draw, title, VIDEO_H-490, (255,255,255))
    _draw_price(draw, price, (255,245,100))
    _draw_cta(draw, "white", (180,0,100))
    if show_url: _draw_url_overlay(draw, url)
    return img

def template_earthy_warm(img_path, title, price, url, show_url=False):
    img = _prep_image(img_path)
    img = _gradient(img, (90,60,30,30), (40,25,10,215), VIDEO_H-700, VIDEO_H)
    draw = ImageDraw.Draw(img)
    _draw_logo(draw)
    _draw_title(draw, title, VIDEO_H-500, (255,240,210))
    _draw_price(draw, price, (255,200,100))
    _draw_cta(draw, (255,200,100), (40,25,10))
    if show_url: _draw_url_overlay(draw, url)
    return img

def template_neon_night(img_path, title, price, url, show_url=False):
    img = _prep_image(img_path)
    img = _gradient(img, (0,5,20,80), (0,10,30,220), VIDEO_H-700, VIDEO_H)
    draw = ImageDraw.Draw(img)
    _draw_logo(draw)
    draw.rectangle([(60,VIDEO_H-555),(VIDEO_W-60,VIDEO_H-549)], fill=(0,255,200))
    _draw_title(draw, title, VIDEO_H-510, (200,255,245))
    _draw_price(draw, price, (0,255,200))
    _draw_cta(draw, (0,255,200), "black")
    if show_url: _draw_url_overlay(draw, url)
    return img

TEMPLATES = [
    template_dark_luxury,
    template_clean_minimal,
    template_vibrant_pop,
    template_earthy_warm,
    template_neon_night,
]


# ─── Ken Burns ────────────────────────────────────────────────────────────────

DIRECTIONS = ["zoom_in", "pan_right", "pan_left", "zoom_out", "pan_up", "pan_down"]


def ken_burns_clip(img_path, title, price, url, duration, direction,
                   template_fn, show_url=False):
    src_w = int(VIDEO_W * 1.20)   # 20% extra for more aggressive movement
    src_h = int(VIDEO_H * 1.20)

    raw    = _prep_image(img_path).resize((src_w, src_h), Image.LANCZOS)
    styled = template_fn(img_path, title, price, url, show_url)

    raw_arr    = np.array(raw)
    styled_arr = np.array(styled)

    def make_frame(t):
        p = t / duration

        if direction == "zoom_in":
            scale = 1.0 - 0.18 * p
        elif direction == "zoom_out":
            scale = 0.82 + 0.18 * p
        else:
            scale = 0.88

        cw = int(src_w * scale)
        ch = int(src_h * scale)

        if direction == "pan_right":
            x0 = int((src_w - cw) * p);       y0 = (src_h - ch) // 2
        elif direction == "pan_left":
            x0 = int((src_w - cw) * (1-p));   y0 = (src_h - ch) // 2
        elif direction == "pan_up":
            x0 = (src_w - cw) // 2;           y0 = int((src_h - ch) * p)
        elif direction == "pan_down":
            x0 = (src_w - cw) // 2;           y0 = int((src_h - ch) * (1-p))
        else:
            x0 = (src_w - cw) // 2;           y0 = (src_h - ch) // 2

        x0 = max(0, min(x0, src_w - cw))
        y0 = max(0, min(y0, src_h - ch))

        cropped = raw_arr[y0:y0+ch, x0:x0+cw]
        bg = np.array(Image.fromarray(cropped).resize((VIDEO_W, VIDEO_H), Image.LANCZOS))

        # Strong blend: styled overlay dominates
        blended = (bg * 0.12 + styled_arr * 0.88).astype(np.uint8)
        return blended

    return VideoClip(make_frame, duration=duration).set_fps(FPS)


# ─── Audio: background music + sparse voiceover ──────────────────────────────

def _make_vo(text, path):
    gTTS(text=text, lang="en", tld="us").save(path)
    return AudioFileClip(path)


def build_audio(title, price, total_duration, tmp_dir, music_path):
    clips = []

    # Sparse voiceover: intro, price reveal, CTA
    p1 = os.path.join(tmp_dir, "vo_intro.mp3")
    clips.append(_make_vo(f"Obsessed with this {title}.", p1).set_start(0))

    mid = total_duration / 2
    p2  = os.path.join(tmp_dir, "vo_price.mp3")
    pc  = _make_vo(f"Only {price} dollars. Grab it before it's gone!", p2)
    clips.append(pc.set_start(mid))

    cta_start = max(total_duration - 5, mid + pc.duration + 0.5)
    p3 = os.path.join(tmp_dir, "vo_cta.mp3")
    clips.append(_make_vo(
        "Link in description! Shop now at MeeeShop.", p3
    ).set_start(cta_start))

    # Background music — always present
    if os.path.exists(music_path):
        bg = AudioFileClip(music_path).volumex(0.22)
        bg = bg.audio_loop(duration=total_duration) \
            if bg.duration < total_duration else bg.subclip(0, total_duration)
        # Duck music under voiceover (simple version: reduce vol slightly)
        clips.insert(0, bg)

    return CompositeAudioClip(clips)


# ─── Video assembly ───────────────────────────────────────────────────────────

def create_short(product, out_path="short_output.mp4"):
    title  = product["title"]
    price  = product["variants"][0]["price"] if product.get("variants") else "0"
    handle = product.get("handle", "")
    url    = f"u.meeeshop.com/products/{handle}" if handle else "u.meeeshop.com"

    print(f"Product  : {title}")
    print(f"Price    : ${price}")

    tmp_imgs = "tmp_product_images"
    tmp_vo   = "tmp_voiceover"

    template_fn = random.choice(TEMPLATES)
    print(f"Template : {template_fn.__name__}")

    try:
        print("Downloading images...")
        img_paths = download_images(product, tmp_imgs)
        if not img_paths:
            raise RuntimeError("No images found.")

        os.makedirs(tmp_vo, exist_ok=True)
        music_path = get_or_create_bg_music()

        print("Building clips (Ken Burns)...")
        clips = []
        dirs  = random.sample(DIRECTIONS, len(DIRECTIONS))  # shuffle directions
        for i, p in enumerate(img_paths):
            direction = dirs[i % len(dirs)]
            show_url  = (i == len(img_paths) - 1)  # show URL on last image
            clip = ken_burns_clip(p, title, price, url, IMG_DURATION,
                                  direction, template_fn, show_url)
            clip = clip.fadein(0.3).fadeout(0.3)
            clips.append(clip)

        video = concatenate_videoclips(clips, method="compose")

        print("Building audio...")
        audio = build_audio(title, price, video.duration, tmp_vo, music_path)
        final = video.set_audio(audio)

        print("Rendering...")
        final.write_videofile(
            out_path, fps=FPS, codec="libx264", audio_codec="aac",
            temp_audiofile="tmp_audio.m4a", remove_temp=True,
            verbose=False, logger=None
        )
        final.close()
        print(f"Saved -> {out_path}")
        return out_path, url

    finally:
        shutil.rmtree(tmp_imgs, ignore_errors=True)
        shutil.rmtree(tmp_vo,   ignore_errors=True)
        import time; time.sleep(1)
        try:
            if os.path.exists("tmp_audio.m4a"):
                os.remove("tmp_audio.m4a")
        except PermissionError:
            pass


# ─── YouTube ──────────────────────────────────────────────────────────────────

def get_youtube():
    # Cloud mode: build credentials from environment variables (GitHub Actions)
    refresh_token = os.getenv("YOUTUBE_REFRESH_TOKEN")
    if refresh_token:
        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=os.getenv("YOUTUBE_CLIENT_ID"),
            client_secret=os.getenv("YOUTUBE_CLIENT_SECRET"),
            scopes=YOUTUBE_SCOPES,
        )
        creds.refresh(Request())
        return build("youtube", "v3", credentials=creds)

    # Local mode: use saved pickle file
    creds, token_file = None, "youtube_token.pickle"
    if os.path.exists(token_file):
        with open(token_file, "rb") as f:
            creds = pickle.load(f)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                "client_secret.json", YOUTUBE_SCOPES)
            creds = flow.run_local_server(port=8080, open_browser=False)
        with open(token_file, "wb") as f:
            pickle.dump(creds, f)
    return build("youtube", "v3", credentials=creds)


def _next_slots(n=3):
    est = ZoneInfo("America/New_York")
    now = datetime.now(est)
    results = []
    for day_offset in range(14):
        day = now + timedelta(days=day_offset)
        for hour in POSTING_SLOTS_EST[day.weekday()]:
            slot = day.replace(hour=hour, minute=0, second=0, microsecond=0)
            if slot > now + timedelta(minutes=15):
                utc = slot.astimezone(timezone.utc)
                results.append((utc.strftime("%Y-%m-%dT%H:%M:%S.000Z"), slot))
                if len(results) == n:
                    return results
    return results


TITLE_TEMPLATES = [
    "This {title} is EVERYTHING! Only ${price} | MeeeShop #Shorts",
    "You NEED this {title} | ${price} | MeeeShop #Shorts",
    "Obsessed with this {title} | ${price} at MeeeShop #Shorts",
    "New Drop! {title} | Only ${price} | MeeeShop #Shorts",
    "SOLD OUT everywhere EXCEPT here | {title} ${price} #Shorts",
    "The {title} you've been looking for | ${price} | MeeeShop #Shorts",
    "This {title} went VIRAL for a reason | ${price} #Shorts",
]


def _build_metadata(product, product_url):
    title = product["title"]
    price = product["variants"][0]["price"] if product.get("variants") else "0"
    tags  = product.get("tags", "").split(", ") if product.get("tags") else []

    yt_title = random.choice(TITLE_TEMPLATES).format(title=title, price=price)[:100]

    full_url = f"https://{product_url}"
    description = (
        f"SHOP NOW (clickable link): {full_url}\n"
        f"_________________________________\n\n"
        f"{title}\n"
        f"Only ${price} - limited stock!\n\n"
        f"FREE shipping on orders $50+\n"
        f"New styles dropped daily at MeeeShop!\n\n"
        f"Follow us for daily fashion drops!\n"
        f"_________________________________\n\n"
        f"#fashion #womenfashion #ootd #style #shopping "
        f"#dresses #outfit #trending #Shorts #MeeeShop "
        f"#USA #womenclothing #fashionista #styleinspo "
        f"#outfitoftheday #affordablefashion #newdrop "
        f"#musthave #shoppinghaul #viral #fyp #foryou"
    )

    base_tags = [
        "fashion", "women fashion", "ootd", "style", "shopping",
        "dresses", "outfit", "trending", "MeeeShop", "USA fashion",
        "women clothing", "fashionista", "style inspo", "outfit of the day",
        "affordable fashion", "new drop", "must have", "shopping haul",
        "viral fashion", "fyp", "for you", title
    ]
    all_tags = list(dict.fromkeys(base_tags + tags))

    return yt_title, description, all_tags


def upload_short(video_path, product, product_url, slot_utc, slot_local):
    yt = get_youtube()
    yt_title, description, tags = _build_metadata(product, product_url)

    body = {
        "snippet": {
            "title": yt_title,
            "description": description,
            "tags": tags,
            "categoryId": "26",
            "defaultLanguage": "en",
            "defaultAudioLanguage": "en",
        },
        "status": {
            "privacyStatus": "private",
            "selfDeclaredMadeForKids": False,
            "publishAt": slot_utc,
        },
    }

    media = MediaFileUpload(video_path, mimetype="video/mp4", resumable=True)
    req   = yt.videos().insert(part=",".join(body.keys()), body=body, media_body=media)

    slot_str = slot_local.strftime("%a %b %d %I:%M %p EST")
    pst_str  = (slot_local - timedelta(hours=3)).strftime("%I:%M %p PST")
    print(f"\nUploading -> {slot_str} | {pst_str}")
    response = None
    while response is None:
        status, response = req.next_chunk()
        if status:
            print(f"  {int(status.progress()*100)}%", end="\r")

    vid_id = response["id"]
    print(f"  Done -> https://www.youtube.com/shorts/{vid_id}")
    return vid_id


def update_video_description(video_id, new_description, new_title=None):
    """Update description (and optionally title) of an existing video."""
    yt = get_youtube()
    # First fetch current snippet
    r = yt.videos().list(part="snippet", id=video_id).execute()
    if not r.get("items"):
        print(f"  Video {video_id} not found.")
        return
    snippet = r["items"][0]["snippet"]
    snippet["description"] = new_description
    if new_title:
        snippet["title"] = new_title[:100]
    yt.videos().update(
        part="snippet",
        body={"id": video_id, "snippet": snippet}
    ).execute()
    print(f"  Updated {video_id}")


# ─── Main ─────────────────────────────────────────────────────────────────────

# Video IDs from previous run — will update their descriptions
PREVIOUS_VIDEOS = {
    "PqoFYSN1eH8": {
        "title": "Bolt Long Sleeve Crew Neck Sweater",
        "price": "65.99",
        "url": "https://u.meeeshop.com/products/bolt-long-sleeve-crew-neck-sweater"
    },
    "-ma1CWzMxsg": {
        "title": "AT1082STM Altitude Heights Corset Double Waistband",
        "price": "110.99",
        "url": "https://u.meeeshop.com/products/at1082stm-altitude-heights-corset-double-waistband"
    },
    "ultNgH0YrKc": {
        "title": "Backless Front Tie Halter Top With Lace Trim",
        "price": "57.99",
        "url": "https://u.meeeshop.com/products/backless-front-tie-halter-top-with-lace-trim"
    },
}


def update_previous_videos():
    print("\nUpdating descriptions of previous videos...")
    for vid_id, info in PREVIOUS_VIDEOS.items():
        desc = (
            f"SHOP NOW (clickable link): {info['url']}\n"
            f"_________________________________\n\n"
            f"{info['title']}\n"
            f"Only ${info['price']} - limited stock!\n\n"
            f"FREE shipping on orders $50+\n"
            f"New styles dropped daily at MeeeShop!\n\n"
            f"#fashion #womenfashion #ootd #style #shopping "
            f"#dresses #outfit #trending #Shorts #MeeeShop "
            f"#USA #womenclothing #fashionista #styleinspo "
            f"#outfitoftheday #affordablefashion #musthave #viral #fyp"
        )
        update_video_description(vid_id, desc)
    print("Previous videos updated!")


def main():
    print("=== MeeeShop - YouTube Shorts Automation ===\n")

    # Create 3 new videos
    slots = _next_slots(n=3)
    print(f"\nCreating {len(slots)} new videos:")
    for _, s in slots:
        pst = (s - timedelta(hours=3)).strftime("%I:%M %p PST")
        cst = (s - timedelta(hours=1)).strftime("%I:%M %p CST")
        print(f"  {s.strftime('%a %b %d %I:%M %p EST')} | {cst} | {pst}")

    for i, (slot_utc, slot_local) in enumerate(slots):
        print(f"\n--- Video {i+1} of {len(slots)} ---")
        product    = fetch_random_product()
        video_path = f"short_{product['id']}_{i}.mp4"
        _, prod_url = create_short(product, video_path)
        upload_short(video_path, product, prod_url, slot_utc, slot_local)
        if os.path.exists(video_path):
            os.remove(video_path)

    print("\n=== All done! ===")


if __name__ == "__main__":
    main()

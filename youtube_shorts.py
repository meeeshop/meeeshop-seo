import os
import platform
import requests
import pickle
import numpy as np
import random
from datetime import datetime, timedelta, timezone, date
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
import shutil, textwrap, time

load_dotenv()

SHOPIFY_STORE  = os.getenv("SHOPIFY_STORE")
SHOPIFY_TOKEN  = os.getenv("SHOPIFY_ACCESS_TOKEN")

VIDEO_W, VIDEO_H = 1080, 1920          # Shorts / vertical
LONG_W,  LONG_H  = 1080, 1920          # Keep vertical for long-form too
FPS              = 30
IMG_DURATION     = 3                   # seconds per image
LONG_IMG_DUR     = 12                  # seconds per product in long video

YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]

if platform.system() == "Windows":
    FONT_BOLD = r"C:\Windows\Fonts\arialbd.ttf"
    FONT_REG  = r"C:\Windows\Fonts\arial.ttf"
else:
    FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    FONT_REG  = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

POSTING_SLOTS_EST = {
    0:[12,19,21], 1:[12,19,21], 2:[12,19,21],
    3:[12,19,21], 4:[12,19,21], 5:[11,14,20], 6:[11,14,20],
}


# ══════════════════════════════════════════════════════════════════════════════
#  PIANO-ONLY MUSIC — 6 distinct tracks, one per content format
#  Pure sine-wave piano synthesis, no drums, no noise
# ══════════════════════════════════════════════════════════════════════════════

# Each format gets its own musical personality
MUSIC_PROFILES = {
    "ootd":          dict(root=261.63, bpm=118, pattern=[0,2,4,7,5,4,2,0,4,7,5,4,2,4,0,2]),  # C, bright
    "how_to_style":  dict(root=293.66, bpm=108, pattern=[0,4,7,5,4,2,0,4,2,0,4,7,5,4,7,0]),  # D, elegant
    "new_drop":      dict(root=329.63, bpm=126, pattern=[0,2,4,7,7,5,4,2,4,0,2,4,7,5,4,0]),  # E, energetic
    "trend_alert":   dict(root=349.23, bpm=124, pattern=[0,4,7,9,7,5,4,2,0,4,5,7,4,2,0,4]),  # F, upbeat
    "fashion_steal": dict(root=392.00, bpm=112, pattern=[0,2,4,5,4,2,0,4,2,4,7,5,4,2,4,0]),  # G, fun
    "styling_inspo": dict(root=220.00, bpm=100, pattern=[0,4,7,4,0,2,4,7,5,4,2,0,4,7,5,4]),  # A, dreamy
}

def _major_scale(root):
    """Return one-octave major scale from root (Hz)."""
    ratios = [1, 9/8, 5/4, 4/3, 3/2, 5/3, 15/8, 2]
    return [root * r for r in ratios]

def generate_piano_track(fmt_name, duration=90, sr=22050, out_path=None):
    """Pure piano music — no drums, no noise. Distinct per format."""
    prof    = MUSIC_PROFILES.get(fmt_name, MUSIC_PROFILES["ootd"])
    bpm     = prof["bpm"]
    pattern = prof["pattern"]
    scale   = _major_scale(prof["root"])
    # Chord: I-V-vi-IV in the format's key
    r = prof["root"]
    chords = [
        [r, r*5/4, r*3/2],          # I  major
        [r*3/2, r*15/8, r*2*9/8],   # V  major
        [r*5/3, r*2, r*2*5/4],      # vi minor-ish
        [r*4/3, r*5/3, r*2],        # IV major
    ]
    samples = int(sr * duration)
    beat    = int(sr * 60 / bpm)
    mix     = np.zeros(samples)

    def piano_note(freq, start, length, amp=0.10):
        n = min(length, samples - start)
        if n <= 0: return
        tl = np.arange(n) / sr
        wave = (1.00*np.sin(2*np.pi*freq*1*tl) +
                0.50*np.sin(2*np.pi*freq*2*tl) +
                0.25*np.sin(2*np.pi*freq*3*tl) +
                0.12*np.sin(2*np.pi*freq*4*tl) +
                0.06*np.sin(2*np.pi*freq*5*tl))
        atk = max(1, int(sr*0.008))
        dec = max(1, int(sr*0.10))
        rel = max(1, int(sr*0.20))
        env = np.full(n, 0.70)
        env[:atk] = np.linspace(0, 1, atk)
        if atk+dec < n: env[atk:atk+dec] = np.linspace(1, 0.70, dec)
        if n > rel:      env[-rel:] *= np.linspace(1, 0, rel)
        mix[start:start+n] += amp * wave * env

    # Chord accompaniment (left hand)
    bar = beat * 4
    for bar_i in range(0, samples, bar*4):
        for ci, chord in enumerate(chords):
            cs = bar_i + ci*bar
            if cs >= samples: break
            for freq in chord:
                piano_note(freq, cs, bar, amp=0.08)

    # Melody (right hand) — format's unique pattern
    mel_scale = _major_scale(prof["root"] * 2)  # one octave up
    for rep in range(0, samples, beat*len(pattern)):
        for j, idx in enumerate(pattern):
            s = rep + j*beat
            if s >= samples: break
            piano_note(mel_scale[idx % len(mel_scale)], s, beat, amp=0.07)

    # Soft bass (root only, two octaves down)
    bass_root = prof["root"] / 2
    roots_seq = [bass_root, bass_root*3/2, bass_root*5/3, bass_root*4/3]
    for bar_i in range(0, samples, bar*4):
        for ri, bass in enumerate(roots_seq):
            s = bar_i + ri*bar
            n = min(bar, samples-s)
            if n <= 0: break
            tl = np.arange(n)/sr
            fl = max(1, n//6)
            fade = np.ones(n); fade[-fl:] = np.linspace(1, 0, fl)
            mix[s:s+n] += 0.18*np.sin(2*np.pi*bass*tl)*fade

    # Normalize & fade edges
    mix = np.clip(mix/(np.max(np.abs(mix))+1e-6)*0.80, -1, 1)
    fl  = int(sr*1.5)
    mix[:fl]  *= np.linspace(0, 1, fl)
    mix[-fl:] *= np.linspace(1, 0, fl)

    if out_path is None:
        out_path = f"music_{fmt_name}.wav"
    wavfile.write(out_path, sr, mix.astype(np.float32))
    return out_path


def get_music_for_format(fmt_name):
    """Return path to cached piano track for this format, generating if needed."""
    path = f"music_{fmt_name}.wav"
    if not os.path.exists(path):
        print(f"  Generating piano music for {fmt_name}...")
        generate_piano_track(fmt_name, out_path=path)
    return path


def get_bg_music():   # kept for long-video fallback
    path = "music_ootd.wav"
    if not os.path.exists(path):
        generate_piano_track("ootd", out_path=path)
    return path




# ══════════════════════════════════════════════════════════════════════════════
#  SHOPIFY
# ══════════════════════════════════════════════════════════════════════════════

def fetch_products(limit=100):
    r = requests.get(
        f"https://{SHOPIFY_STORE}/admin/api/2024-01/products.json?limit={limit}&status=active",
        headers={"X-Shopify-Access-Token": SHOPIFY_TOKEN})
    r.raise_for_status()
    return r.json().get("products", [])


def pick_unique_products(n, exclude_ids=None):
    exclude_ids = exclude_ids or set()
    pool = [p for p in fetch_products() if p["id"] not in exclude_ids]
    return random.sample(pool, min(n, len(pool)))


def download_images(product, tmp_dir, max_imgs=6):
    os.makedirs(tmp_dir, exist_ok=True)
    paths = []
    for i, img in enumerate(product.get("images", [])[:max_imgs]):
        dest = os.path.join(tmp_dir, f"img_{i}.jpg")
        r = requests.get(img["src"], stream=True); r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(8192): f.write(chunk)
        paths.append(dest)
    return paths


# ══════════════════════════════════════════════════════════════════════════════
#  DRAW UTILITIES
# ══════════════════════════════════════════════════════════════════════════════

def _font(path, size):
    try:    return ImageFont.truetype(path, size)
    except: return ImageFont.load_default()

def _prep(img_path, w=VIDEO_W, h=VIDEO_H):
    img = Image.open(img_path).convert("RGB")
    iw, ih = img.size
    if iw/ih > w/h:
        nw = int(ih*(w/h)); img = img.crop(((iw-nw)//2,0,(iw-nw)//2+nw,ih))
    else:
        nh = int(iw/(w/h)); img = img.crop((0,(ih-nh)//2,iw,(ih-nh)//2+nh))
    return img.resize((w, h), Image.LANCZOS)

def _gradient(img, top_rgba, bot_rgba, y0=0, y1=None):
    y1 = y1 or img.height
    ov = Image.new("RGBA", img.size, (0,0,0,0))
    dr = ImageDraw.Draw(ov)
    for y in range(y1-y0):
        t = y/(y1-y0)
        r = int(top_rgba[0]+t*(bot_rgba[0]-top_rgba[0]))
        g = int(top_rgba[1]+t*(bot_rgba[1]-top_rgba[1]))
        b = int(top_rgba[2]+t*(bot_rgba[2]-top_rgba[2]))
        a = int(top_rgba[3]+t*(bot_rgba[3]-top_rgba[3]))
        dr.line([(0,y0+y),(img.width,y0+y)], fill=(r,g,b,a))
    img = img.convert("RGBA"); img.alpha_composite(ov)
    return img.convert("RGB")

def _pill(draw, text, cx, cy, font, bg, fg, pad_x=30, pad_y=14, radius=22):
    bb = draw.textbbox((0,0), text, font=font)
    tw, th = bb[2]-bb[0], bb[3]-bb[1]
    x0,y0 = cx-tw//2-pad_x, cy-th//2-pad_y
    x1,y1 = cx+tw//2+pad_x, cy+th//2+pad_y
    draw.rounded_rectangle([(x0,y0),(x1,y1)], radius=radius, fill=bg)
    draw.text((cx,cy), text, font=font, fill=fg, anchor="mm")

def _logo(draw, w=VIDEO_W):
    _pill(draw, "MeeeShop", 150, 65, _font(FONT_BOLD,34), "white", "black", 22, 12, 20)

def _title_lines(draw, title, y, color="white", size=58, w=VIDEO_W):
    font = _font(FONT_BOLD, size)
    for line in textwrap.wrap(title, 22)[:3]:
        draw.text((w//2, y), line, font=font, fill=color,
                  anchor="mm", stroke_width=3, stroke_fill=(0,0,0,150))
        y += 70

def _price_text(draw, price, y=VIDEO_H-215, color=(255,215,0), w=VIDEO_W):
    draw.text((w//2, y), f"${price}", font=_font(FONT_BOLD,76),
              fill=color, anchor="mm", stroke_width=3, stroke_fill=(0,0,0))

def _cta(draw, text="Shop Now ->", bg="white", fg="black", w=VIDEO_W, h=VIDEO_H):
    y0,y1 = h-140, h-68
    draw.rounded_rectangle([(w//2-210,y0),(w//2+210,y1)], radius=35, fill=bg)
    draw.text((w//2,(y0+y1)//2), text, font=_font(FONT_BOLD,44), fill=fg, anchor="mm")

def _url_bar(draw, url, w=VIDEO_W, h=VIDEO_H):
    y0,y1 = h-245, h-195
    draw.rounded_rectangle([(50,y0),(w-50,y1)], radius=18, fill=(255,255,255,200))
    draw.text((w//2,(y0+y1)//2), url, font=_font(FONT_BOLD,30),
              fill=(0,90,200), anchor="mm")

def _format_badge(draw, label, w=VIDEO_W):
    """Top-right badge showing video format."""
    font = _font(FONT_BOLD, 30)
    _pill(draw, label, w-160, 65, font, (255,50,100), "white", 18, 10, 18)


# ══════════════════════════════════════════════════════════════════════════════
#  6 VISUAL TEMPLATES  (colour/mood)
# ══════════════════════════════════════════════════════════════════════════════

def _build_base(img_path, title, price, url, fmt_label,
                grad_top, grad_bot, title_color, price_color,
                cta_bg, cta_fg, show_url=False, w=VIDEO_W, h=VIDEO_H):
    img = _prep(img_path, w, h)
    img = _gradient(img, grad_top, grad_bot, h-680, h)
    draw = ImageDraw.Draw(img)
    _logo(draw); _format_badge(draw, fmt_label)
    _title_lines(draw, title, h-490, title_color)
    _price_text(draw, price, h-215, price_color)
    _cta(draw, cta_bg=cta_bg, cta_fg=cta_fg)
    if show_url: _url_bar(draw, url)
    return img

VISUAL_STYLES = {
    "dark_luxury":   dict(grad_top=(10,10,20,50),    grad_bot=(5,5,15,215),
                          title_color="white",         price_color=(212,175,55),
                          cta_bg=(212,175,55),         cta_fg="black"),
    "clean_minimal": dict(grad_top=(255,255,255,0),   grad_bot=(255,255,255,225),
                          title_color=(20,20,20),      price_color=(220,50,80),
                          cta_bg=(20,20,20),           cta_fg="white"),
    "vibrant_pop":   dict(grad_top=(120,0,180,20),    grad_bot=(220,20,100,210),
                          title_color="white",          price_color=(255,245,100),
                          cta_bg="white",               cta_fg=(180,0,100)),
    "earthy_warm":   dict(grad_top=(90,60,30,30),     grad_bot=(40,25,10,215),
                          title_color=(255,240,210),    price_color=(255,200,100),
                          cta_bg=(255,200,100),         cta_fg=(40,25,10)),
    "neon_night":    dict(grad_top=(0,5,20,80),        grad_bot=(0,10,30,220),
                          title_color=(200,255,245),    price_color=(0,255,200),
                          cta_bg=(0,255,200),           cta_fg="black"),
    "blush_rose":    dict(grad_top=(255,192,203,30),   grad_bot=(180,60,100,220),
                          title_color="white",           price_color=(255,255,200),
                          cta_bg="white",                cta_fg=(180,60,100)),
}
STYLE_NAMES = list(VISUAL_STYLES.keys())

# ── Scene overlays: subtle tinted vignette suggesting a location ──────────────
# These paint a semi-transparent colour wash over the top 40% of the image
# so it feels like different lighting environments (studio, outdoor, home, etc.)
SCENE_OVERLAYS = {
    "studio":  (220, 220, 255, 28),   # cool white studio light
    "outdoor": (135, 190, 100, 32),   # fresh green/daylight
    "home":    (255, 210, 160, 30),   # warm golden home light
    "park":    (100, 180, 130, 28),   # green park light
    "sunset":  (255, 160, 80,  35),   # warm sunset orange
    "city":    (160, 180, 220, 30),   # cool city blue
}
SCENE_NAMES = list(SCENE_OVERLAYS.keys())

def _compose_scene(img_path, scene_name, w=VIDEO_W, h=VIDEO_H):
    """
    Foreground/background compositor:
    - Background: product image heavily blurred + scene colour tint (feels like park/home/studio)
    - Foreground: sharp product image centred, slightly smaller — model in front, scene behind
    """
    from PIL import ImageFilter
    scene_color = SCENE_OVERLAYS.get(scene_name, (220, 220, 255, 40))
    raw = Image.open(img_path).convert("RGB")

    # ── BACKGROUND: fill frame, blur strongly, tint with scene colour ──
    bg = _prep(img_path, w, h)
    bg = bg.filter(ImageFilter.GaussianBlur(radius=22))
    tint = Image.new("RGB", (w, h), scene_color[:3])
    bg   = Image.blend(bg, tint, alpha=0.38)   # blend scene colour

    # ── FOREGROUND: sharp product image, 88% of frame height, centered ──
    fg_h = int(h * 0.88)
    fg_w = int(fg_h * (raw.width / raw.height))
    if fg_w > w:
        fg_w = w; fg_h = int(fg_w * (raw.height / raw.width))
    fg   = raw.resize((fg_w, fg_h), Image.LANCZOS)

    # centre horizontally, push slightly up to leave room for text at bottom
    x_off = (w - fg_w) // 2
    y_off = max(0, int(h * 0.04))

    canvas = bg.copy()
    canvas.paste(fg, (x_off, y_off))
    return canvas


# ══════════════════════════════════════════════════════════════════════════════
#  6 CONTENT FORMATS  (what the video "is about")
# ══════════════════════════════════════════════════════════════════════════════

CONTENT_FORMATS = {
    "ootd": {
        "badge":     "OOTD",
        "hook":      "Today's Look",
        "voiceover": lambda t, p: (
            f"Outfit of the day! Rocking this stunning {t}. "
            f"Only {p} dollars. Perfect for any occasion. Shop it now at MeeeShop!"
        ),
        "yt_titles": [
            "OOTD: {title} | Outfit Inspo | MeeeShop #Shorts",
            "Today's Outfit: {title} for ${price} | MeeeShop #Shorts",
            "Outfit of the Day! {title} | Only ${price} #Shorts",
        ],
        "extra_tags": ["ootd","outfit of the day","daily outfit","outfit inspo"],
    },
    "how_to_style": {
        "badge":     "STYLE TIPS",
        "hook":      "3 Ways to Style This",
        "voiceover": lambda t, p: (
            f"Here are three ways to style this {t}. "
            f"Dress it up, dress it down, or go casual. "
            f"Just {p} dollars at MeeeShop. Link in description!"
        ),
        "yt_titles": [
            "How to Style {title} | 3 Outfit Ideas | MeeeShop #Shorts",
            "3 Ways to Wear {title} | MeeeShop Styling Tips #Shorts",
            "Style This {title} 3 Different Ways | ${price} | MeeeShop #Shorts",
        ],
        "extra_tags": ["how to style","styling tips","outfit ideas","fashion tips"],
    },
    "new_drop": {
        "badge":     "NEW DROP",
        "hook":      "Just Dropped!",
        "voiceover": lambda t, p: (
            f"New drop alert! This {t} just landed at MeeeShop. "
            f"Only {p} dollars and it's already selling fast. Don't sleep on this!"
        ),
        "yt_titles": [
            "New Drop! {title} Just Arrived | ${price} | MeeeShop #Shorts",
            "JUST DROPPED: {title} | Only ${price} | MeeeShop #Shorts",
            "New Arrival Alert! {title} | MeeeShop #Shorts",
        ],
        "extra_tags": ["new drop","new arrival","just dropped","new in"],
    },
    "trend_alert": {
        "badge":     "TRENDING",
        "hook":      "Trending Right Now",
        "voiceover": lambda t, p: (
            f"This is trending everywhere right now! The {t} from MeeeShop. "
            f"Grab yours for just {p} dollars before it sells out!"
        ),
        "yt_titles": [
            "TRENDING: {title} | Everyone's Wearing This | MeeeShop #Shorts",
            "This {title} is Going Viral! ${price} | MeeeShop #Shorts",
            "Trend Alert! {title} | ${price} | MeeeShop #Shorts",
        ],
        "extra_tags": ["trending","viral fashion","trend alert","what's trending"],
    },
    "fashion_steal": {
        "badge":     "STEAL",
        "hook":      "Fashion Steal Alert!",
        "voiceover": lambda t, p: (
            f"Fashion on a budget! This amazing {t} is only {p} dollars. "
            f"Look like you spent a fortune without breaking the bank. Shop MeeeShop!"
        ),
        "yt_titles": [
            "Fashion Steal! {title} for Only ${price} | MeeeShop #Shorts",
            "Slay on a Budget: {title} | Just ${price} | MeeeShop #Shorts",
            "Look Expensive for ${price}: {title} | MeeeShop #Shorts",
        ],
        "extra_tags": ["fashion steal","budget fashion","affordable style","cheap fashion"],
    },
    "styling_inspo": {
        "badge":     "INSPO",
        "hook":      "Style Inspiration",
        "voiceover": lambda t, p: (
            f"Style inspiration coming your way! This gorgeous {t} "
            f"is available now for {p} dollars. MeeeShop has everything you need!"
        ),
        "yt_titles": [
            "Style Inspo: {title} | Fashion Goals | MeeeShop #Shorts",
            "Obsessed with This {title} | ${price} | MeeeShop #Shorts",
            "Your Next Favourite Outfit: {title} | MeeeShop #Shorts",
        ],
        "extra_tags": ["style inspo","fashion goals","outfit inspiration","style goals"],
    },
}
FORMAT_NAMES = list(CONTENT_FORMATS.keys())


# ══════════════════════════════════════════════════════════════════════════════
#  FRAME BUILDER — combines visual style + content format
# ══════════════════════════════════════════════════════════════════════════════

def build_frame(img_path, product, style_name, fmt_name,
                show_url=False, frame_idx=0, scene_name="studio",
                w=VIDEO_W, h=VIDEO_H):
    title  = product["title"]
    price  = product["variants"][0]["price"] if product.get("variants") else "0"
    handle = product.get("handle","")
    url    = f"u.meeeshop.com/products/{handle}" if handle else "u.meeeshop.com"
    fmt    = CONTENT_FORMATS[fmt_name]
    style  = VISUAL_STYLES[style_name]

    img = _compose_scene(img_path, scene_name, w, h)   # bg blurred scene + fg sharp product
    img = _gradient(img, style["grad_top"], style["grad_bot"], h-680, h)
    draw = ImageDraw.Draw(img)

    _logo(draw)
    _format_badge(draw, fmt["badge"])

    # Hook text on first frame
    if frame_idx == 0:
        hook_font = _font(FONT_BOLD, 52)
        _pill(draw, fmt["hook"], w//2, h-570, hook_font,
              (255,255,255,210), (20,20,20), 28, 14, 24)

    _title_lines(draw, title, h-480, style["title_color"])
    _price_text(draw, price, h-215, style["price_color"])
    _cta(draw, bg=style["cta_bg"], fg=style["cta_fg"])
    if show_url:
        _url_bar(draw, url)
    return img


# ══════════════════════════════════════════════════════════════════════════════
#  KEN BURNS  (zoom/pan every clip — direction shuffled)
# ══════════════════════════════════════════════════════════════════════════════

DIRECTIONS = ["zoom_in","zoom_out","pan_right","pan_left","pan_up","pan_down"]


def ken_burns_clip(img_path, product, style_name, fmt_name,
                   duration, direction, frame_idx=0,
                   show_url=False, scene_name="studio", w=VIDEO_W, h=VIDEO_H):
    sw, sh = int(w*1.20), int(h*1.20)
    # Use composed scene (blurred bg + sharp fg) scaled up for Ken Burns room
    composed = _compose_scene(img_path, scene_name, sw, sh)
    styled   = build_frame(img_path, product, style_name, fmt_name,
                           show_url, frame_idx, scene_name, w, h)
    raw_a    = np.array(composed)
    styled_a = np.array(styled)

    def make_frame(t):
        p  = t / duration
        sc = {"zoom_in":1-0.18*p, "zoom_out":0.82+0.18*p}.get(direction, 0.88)
        cw, ch = int(sw*sc), int(sh*sc)
        if   direction == "pan_right": x0,y0 = int((sw-cw)*p), (sh-ch)//2
        elif direction == "pan_left":  x0,y0 = int((sw-cw)*(1-p)), (sh-ch)//2
        elif direction == "pan_up":    x0,y0 = (sw-cw)//2, int((sh-ch)*p)
        elif direction == "pan_down":  x0,y0 = (sw-cw)//2, int((sh-ch)*(1-p))
        else:                          x0,y0 = (sw-cw)//2, (sh-ch)//2
        x0,y0 = max(0,min(x0,sw-cw)), max(0,min(y0,sh-ch))
        crop  = raw_a[y0:y0+ch, x0:x0+cw]
        bg    = np.array(Image.fromarray(crop).resize((w,h), Image.LANCZOS))
        return (bg*0.12 + styled_a*0.88).astype(np.uint8)

    return VideoClip(make_frame, duration=duration).set_fps(FPS)


# ══════════════════════════════════════════════════════════════════════════════
#  AUDIO — sparse voiceover + happy background music
# ══════════════════════════════════════════════════════════════════════════════

def _vo(text, path):
    gTTS(text=text, lang="en", tld="us").save(path)
    return AudioFileClip(path)


def build_audio(product, fmt_name, total_dur, tmp_dir, music_path):
    """Piano music throughout. Voiceover CTA only at the END (last ~5s)."""
    title  = product["title"]
    price  = product["variants"][0]["price"] if product.get("variants") else "0"
    handle = product.get("handle", "")

    # Single CTA voiceover — plays at the very end only
    cta = f"Shop this look at MeeeShop dot com. Only {price} dollars. Link in description!"
    p1  = os.path.join(tmp_dir, "vo_cta.mp3")
    vo  = _vo(cta, p1)
    vo_start = max(0, total_dur - vo.duration - 0.5)

    clips = [vo.set_start(vo_start)]

    # Format-specific piano music — distinct per video
    if os.path.exists(music_path):
        bg = AudioFileClip(music_path).volumex(0.28)
        bg = bg.audio_loop(duration=total_dur) if bg.duration<total_dur else bg.subclip(0,total_dur)
        clips.insert(0, bg)

    return CompositeAudioClip(clips)


# ══════════════════════════════════════════════════════════════════════════════
#  VIDEO ASSEMBLY — SHORT (≤60s)
# ══════════════════════════════════════════════════════════════════════════════

def create_short(product, style_name, fmt_name, out_path):
    title  = product["title"]
    price  = product["variants"][0]["price"] if product.get("variants") else "0"
    handle = product.get("handle","")
    url    = f"u.meeeshop.com/products/{handle}" if handle else "u.meeeshop.com"

    print(f"  Product : {title[:50]}")
    print(f"  Style   : {style_name} | Format: {fmt_name}")

    tmp_i = "tmp_imgs"; tmp_v = "tmp_vo"
    try:
        imgs = download_images(product, tmp_i)
        if not imgs: raise RuntimeError("No images")
        os.makedirs(tmp_v, exist_ok=True)
        music = get_music_for_format(fmt_name)

        dirs   = random.sample(DIRECTIONS, len(DIRECTIONS))
        scenes = random.sample(SCENE_NAMES, len(SCENE_NAMES))  # shuffle scenes
        clips  = []
        for idx, img_path in enumerate(imgs):
            show_url   = (idx == len(imgs)-1)
            scene_name = scenes[idx % len(scenes)]
            clip = ken_burns_clip(img_path, product, style_name, fmt_name,
                                  IMG_DURATION, dirs[idx%len(dirs)], idx,
                                  show_url, scene_name)
            clip = clip.fadein(0.3).fadeout(0.3)
            clips.append(clip)

        video = concatenate_videoclips(clips, method="compose")
        audio = build_audio(product, fmt_name, video.duration, tmp_v, music)
        final = video.set_audio(audio)
        final.write_videofile(out_path, fps=FPS, codec="libx264", audio_codec="aac",
                              temp_audiofile="tmp_audio.m4a", remove_temp=True,
                              verbose=False, logger=None)
        final.close()
        return out_path, url
    finally:
        shutil.rmtree(tmp_i, ignore_errors=True)
        shutil.rmtree(tmp_v, ignore_errors=True)
        time.sleep(1)
        try:
            if os.path.exists("tmp_audio.m4a"): os.remove("tmp_audio.m4a")
        except PermissionError: pass


# ══════════════════════════════════════════════════════════════════════════════
#  VIDEO ASSEMBLY — LONG (3+ min, every 3 days)
# ══════════════════════════════════════════════════════════════════════════════

def build_long_frame(img_path, product, idx, total, w=VIDEO_W, h=VIDEO_H):
    """Magazine-style frame for the weekly roundup."""
    title  = product["title"]
    price  = product["variants"][0]["price"] if product.get("variants") else "0"
    img    = _prep(img_path, w, h)
    img    = _gradient(img, (0,0,0,0), (0,0,0,200), h-800, h)
    draw   = ImageDraw.Draw(img)
    _logo(draw)
    # Item counter
    _pill(draw, f"{idx+1} of {total}", w-120, 65, _font(FONT_BOLD,28), "black", "white", 14, 8, 14)
    _title_lines(draw, title, h-470, "white", size=54)
    _price_text(draw, price, h-210, (255,215,0))
    _cta(draw, "Shop at MeeeShop ->", (255,255,255), "black")
    return img


def create_long_video(products, out_path):
    print(f"\n  Creating LONG VIDEO with {len(products)} products...")
    tmp_i = "tmp_long_imgs"; tmp_v = "tmp_long_vo"
    try:
        os.makedirs(tmp_v, exist_ok=True)
        music  = get_bg_music()
        clips  = []
        dirs   = DIRECTIONS * 10

        for p_idx, product in enumerate(products):
            print(f"  Product {p_idx+1}/{len(products)}: {product['title'][:40]}")
            imgs = download_images(product, tmp_i, max_imgs=3)
            if not imgs: continue

            for i_idx, img_path in enumerate(imgs):
                styled = build_long_frame(img_path, product, p_idx, len(products))
                styled_a = np.array(styled)
                sw, sh   = int(VIDEO_W*1.18), int(VIDEO_H*1.18)
                raw_a    = np.array(_prep(img_path, sw, sh))
                direction = dirs[(p_idx*3+i_idx) % len(dirs)]

                def make_frame(t, ra=raw_a, sa=styled_a, d=direction):
                    prog = t / LONG_IMG_DUR
                    sc   = {"zoom_in":1-0.15*prog,"zoom_out":0.85+0.15*prog}.get(d, 0.90)
                    cw,ch = int(sw*sc), int(sh*sc)
                    if   d=="pan_right": x0,y0=int((sw-cw)*prog),(sh-ch)//2
                    elif d=="pan_left":  x0,y0=int((sw-cw)*(1-prog)),(sh-ch)//2
                    else:                x0,y0=(sw-cw)//2,(sh-ch)//2
                    x0,y0=max(0,min(x0,sw-cw)),max(0,min(y0,sh-ch))
                    bg = np.array(Image.fromarray(ra[y0:y0+ch,x0:x0+cw]).resize((VIDEO_W,VIDEO_H),Image.LANCZOS))
                    return (bg*0.10+sa*0.90).astype(np.uint8)

                c = VideoClip(make_frame, duration=LONG_IMG_DUR).set_fps(FPS)
                c = c.fadein(0.4).fadeout(0.4)
                clips.append(c)
            shutil.rmtree(tmp_i, ignore_errors=True)

        video = concatenate_videoclips(clips, method="compose")

        # Build long-form audio: intro + product narrations
        vo_clips = []
        p0 = os.path.join(tmp_v,"intro.mp3")
        vo_clips.append(_vo("Welcome to MeeeShop's weekly fashion picks! Here are this week's hottest styles.", p0).set_start(0))

        offset = 4.0
        for p_idx, product in enumerate(products):
            title  = product["title"]
            price  = product["variants"][0]["price"] if product.get("variants") else "0"
            script = f"{title}. Only {price} dollars. Shop it now at MeeeShop dot com."
            pf = os.path.join(tmp_v, f"p{p_idx}.mp3")
            vo_clips.append(_vo(script, pf).set_start(offset))
            offset += LONG_IMG_DUR * 3

        if os.path.exists(music):
            bg = AudioFileClip(music).volumex(0.22)
            bg = bg.audio_loop(duration=video.duration) if bg.duration<video.duration else bg.subclip(0,video.duration)
            vo_clips.insert(0, bg)

        final = video.set_audio(CompositeAudioClip(vo_clips))
        final.write_videofile(out_path, fps=FPS, codec="libx264", audio_codec="aac",
                              temp_audiofile="tmp_audio.m4a", remove_temp=True,
                              verbose=False, logger=None)
        final.close()
        return out_path
    finally:
        shutil.rmtree(tmp_i, ignore_errors=True)
        shutil.rmtree(tmp_v, ignore_errors=True)
        time.sleep(1)
        try:
            if os.path.exists("tmp_audio.m4a"): os.remove("tmp_audio.m4a")
        except PermissionError: pass


# ══════════════════════════════════════════════════════════════════════════════
#  YOUTUBE AUTH
# ══════════════════════════════════════════════════════════════════════════════

def get_youtube():
    rt = os.getenv("YOUTUBE_REFRESH_TOKEN")
    if rt:
        creds = Credentials(token=None, refresh_token=rt,
                            token_uri="https://oauth2.googleapis.com/token",
                            client_id=os.getenv("YOUTUBE_CLIENT_ID"),
                            client_secret=os.getenv("YOUTUBE_CLIENT_SECRET"),
                            scopes=YOUTUBE_SCOPES)
        creds.refresh(Request())
        return build("youtube","v3",credentials=creds)
    creds, tf = None, "youtube_token.pickle"
    if os.path.exists(tf):
        with open(tf,"rb") as f: creds=pickle.load(f)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("client_secret.json", YOUTUBE_SCOPES)
            creds = flow.run_local_server(port=8080, open_browser=False)
        with open(tf,"wb") as f: pickle.dump(creds,f)
    return build("youtube","v3",credentials=creds)


# ══════════════════════════════════════════════════════════════════════════════
#  SCHEDULING
# ══════════════════════════════════════════════════════════════════════════════

def next_slots(n=3):
    est = ZoneInfo("America/New_York")
    now = datetime.now(est)
    results = []
    for d in range(14):
        day = now + timedelta(days=d)
        for h in POSTING_SLOTS_EST[day.weekday()]:
            slot = day.replace(hour=h,minute=0,second=0,microsecond=0)
            if slot > now + timedelta(minutes=15):
                utc = slot.astimezone(timezone.utc)
                results.append((utc.strftime("%Y-%m-%dT%H:%M:%S.000Z"), slot))
                if len(results) == n: return results
    return results


# ══════════════════════════════════════════════════════════════════════════════
#  UPLOAD
# ══════════════════════════════════════════════════════════════════════════════

def _build_short_meta(product, fmt_name, prod_url):
    title  = product["title"]
    price  = product["variants"][0]["price"] if product.get("variants") else "0"
    fmt    = CONTENT_FORMATS[fmt_name]
    yt_title = random.choice(fmt["yt_titles"]).format(title=title, price=price)[:100]
    full_url = f"https://{prod_url}"
    description = (
        f"SHOP NOW: {full_url}\n"
        f"________________________________\n\n"
        f"{title} — only ${price}\n"
        f"Free shipping on orders $50+!\n\n"
        f"Follow MeeeShop for daily fashion drops!\n\n"
        + " ".join(f"#{t.replace(' ','')}" for t in
                   ["fashion","womenfashion","ootd","style","shopping","dresses",
                    "outfit","trending","Shorts","MeeeShop","USA","womenclothing",
                    "fashionista","styleinspo","outfitoftheday","affordablefashion",
                    "newdrop","musthave","viral","fyp"] + fmt["extra_tags"])
    )
    tags = (["fashion","women fashion","ootd","style","shopping","dresses","outfit",
              "trending","MeeeShop","USA fashion","women clothing","fashionista",
              "viral","fyp","for you", title] + fmt["extra_tags"])
    return yt_title, description, list(dict.fromkeys(tags))


def upload_short(video_path, product, fmt_name, prod_url, slot_utc, slot_local):
    yt = get_youtube()
    yt_title, desc, tags = _build_short_meta(product, fmt_name, prod_url)
    body = {
        "snippet": {"title":yt_title,"description":desc,"tags":tags,
                    "categoryId":"26","defaultLanguage":"en"},
        "status":  {"privacyStatus":"private","selfDeclaredMadeForKids":False,
                    "publishAt":slot_utc},
    }
    media = MediaFileUpload(video_path, mimetype="video/mp4", resumable=True)
    req   = yt.videos().insert(part=",".join(body.keys()), body=body, media_body=media)
    resp  = None
    while resp is None:
        st, resp = req.next_chunk()
        if st: print(f"    {int(st.progress()*100)}%", end="\r")
    vid = resp["id"]
    pst = (slot_local-timedelta(hours=3)).strftime("%I:%M %p PST")
    print(f"    Done -> https://www.youtube.com/shorts/{vid} | {slot_local.strftime('%I:%M %p EST')} | {pst}")
    return vid


def upload_long(video_path, products):
    yt    = get_youtube()
    month = datetime.now().strftime("%B %Y")
    title_opts = [
        f"MeeeShop Fashion Picks | {month} | Top Styles",
        f"Weekly Fashion Haul | {month} | MeeeShop",
        f"Top Women's Fashion Finds | {month} | MeeeShop",
    ]
    yt_title = random.choice(title_opts)[:100]
    product_lines = "\n".join(
        f"• {p['title']} — ${p['variants'][0]['price']}" for p in products
    )
    desc = (
        f"Shop everything at: https://u.meeeshop.com\n\n"
        f"This week's top picks:\n{product_lines}\n\n"
        f"Free shipping on orders $50+!\n\n"
        f"#MeeeShop #fashion #womenfashion #weeklyhaul #fashionhaul "
        f"#ootd #style #outfit #USA #womenclothing #lookbook"
    )
    body = {
        "snippet": {"title":yt_title,"description":desc,
                    "tags":["MeeeShop","fashion","women fashion","lookbook",
                            "fashion haul","weekly haul","ootd","style","USA"],
                    "categoryId":"26","defaultLanguage":"en"},
        "status":  {"privacyStatus":"public","selfDeclaredMadeForKids":False},
    }
    media = MediaFileUpload(video_path, mimetype="video/mp4", resumable=True)
    req   = yt.videos().insert(part=",".join(body.keys()), body=body, media_body=media)
    resp  = None
    while resp is None:
        st, resp = req.next_chunk()
        if st: print(f"    {int(st.progress()*100)}%", end="\r")
    vid = resp["id"]
    print(f"    Long video live -> https://www.youtube.com/watch?v={vid}")
    return vid


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def is_long_video_day():
    return date.today().day % 3 == 0   # every 3rd calendar day


def main():
    print("=== MeeeShop YouTube Automation ===")
    today_long = is_long_video_day()

    # Pick 3 unique formats + styles — no duplicates in same day
    formats = random.sample(FORMAT_NAMES, 3)
    styles  = random.sample(STYLE_NAMES,  3)

    slots = next_slots(3)
    print(f"\nPosting 3 Shorts today:")
    for _, s in slots:
        pst = (s-timedelta(hours=3)).strftime("%I:%M %p PST")
        print(f"  {s.strftime('%a %b %d %I:%M %p EST')} | {pst}")
    if today_long:
        print("  + 1 Long video (3-day cycle)")

    used_ids = set()
    short_video_ids = []

    for i, (slot_utc, slot_local) in enumerate(slots):
        print(f"\n--- Short {i+1}/3 | {formats[i].upper()} | {styles[i]} ---")
        product = pick_unique_products(1, exclude_ids=used_ids)[0]
        used_ids.add(product["id"])
        out = f"short_{product['id']}_{i}.mp4"
        _, prod_url = create_short(product, styles[i], formats[i], out)
        vid = upload_short(out, product, formats[i], prod_url, slot_utc, slot_local)
        short_video_ids.append(vid)
        if os.path.exists(out): os.remove(out)

    if today_long:
        print("\n--- Long Video (Weekly Picks) ---")
        products = pick_unique_products(8, exclude_ids=used_ids)
        out = "long_video.mp4"
        create_long_video(products, out)
        upload_long(out, products)
        if os.path.exists(out): os.remove(out)

    print("\n=== All done! ===")
    for vid in short_video_ids:
        print(f"  https://www.youtube.com/shorts/{vid}")


if __name__ == "__main__":
    main()

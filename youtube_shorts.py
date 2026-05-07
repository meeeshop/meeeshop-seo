import os
import platform
import requests
import pickle
import numpy as np
import random
import ai_client          # Gemini → Groq → OpenRouter fallback chain
from urllib.parse import quote as _url_quote
from datetime import datetime, timedelta, timezone, date
from zoneinfo import ZoneInfo
from PIL import Image, ImageDraw, ImageFont, ImageFilter
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
import shutil, textwrap, time, json

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

# Set TESTING_MODE=true (env var or below) to upload as private drafts for review.
# Set to False only after you have verified the videos look good.
TESTING_MODE = os.getenv("TESTING_MODE", "false").lower() == "true"

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
        atk = min(max(1, int(sr*0.008)), n)
        dec = min(max(1, int(sr*0.10)),  max(0, n - atk))
        rel = min(max(1, int(sr*0.20)),  n)
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

    # Warm bass line
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

    # ── DRUM BEATS — pure sine, zero noise ──────────────────────────────────
    # Kick: beats 1 & 3 (pitch sweep 110 → 30 Hz, punchy but clean)
    for i in range(0, samples, beat * 2):
        n = min(int(sr * 0.10), samples - i)
        if n <= 0: continue
        sweepf = np.linspace(110, 30, n)
        kick   = np.sin(2*np.pi*np.cumsum(sweepf)/sr)
        env    = np.exp(-np.linspace(0, 9, n))
        mix[i:i+n] += 0.50 * kick * env

    # Snare: beats 2 & 4 — two-tone sine (180 Hz + 290 Hz), rimshot style
    for i in range(beat, samples, beat * 2):
        n = min(int(sr * 0.055), samples - i)
        if n <= 0: continue
        tl  = np.arange(n) / sr
        env = np.exp(-np.linspace(0, 20, n))
        snare = 0.6*np.sin(2*np.pi*180*tl) + 0.4*np.sin(2*np.pi*290*tl)
        mix[i:i+n] += 0.28 * snare * env

    # Hi-hat: every 8th note — 2800 Hz sine, very short, very soft
    for i in range(0, samples, beat // 2):
        n = min(int(sr * 0.012), samples - i)
        if n <= 0: continue
        tl  = np.arange(n) / sr
        env = np.exp(-np.linspace(0, 55, n))
        mix[i:i+n] += 0.07 * np.sin(2*np.pi*2800*tl) * env

    # Normalize & fade edges
    mix = np.clip(mix/(np.max(np.abs(mix))+1e-6)*0.80, -1, 1)
    fl  = int(sr*1.5)
    mix[:fl]  *= np.linspace(0, 1, fl)
    mix[-fl:] *= np.linspace(1, 0, fl)

    if out_path is None:
        out_path = f"music_{fmt_name}.wav"
    wavfile.write(out_path, sr, mix.astype(np.float32))
    return out_path


# ── YouTube Audio Library mood → search terms ────────────────────────────────
# Mood per format — 5 distinct moods, no two formats share the same
FORMAT_MOODS = {
    "ootd":          "happy",
    "how_to_style":  "inspirational",
    "new_drop":      "rock",
    "trend_alert":   "funky",
    "fashion_steal": "bright",
    "styling_inspo": "inspirational",
}

# ── Music usage history (10-day cooldown, same as products) ──────────────────
MUSIC_HISTORY_FILE    = "music_history.json"
MUSIC_COOLDOWN_DAYS   = 10

def _load_music_history():
    if os.path.exists(MUSIC_HISTORY_FILE):
        try:
            with open(MUSIC_HISTORY_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def _save_music_history(h):
    with open(MUSIC_HISTORY_FILE, "w") as f:
        json.dump(h, f, indent=2)

def _mark_music_used(path):
    h = _load_music_history()
    h[os.path.basename(path)] = datetime.now(timezone.utc).isoformat()
    _save_music_history(h)

def _music_on_cooldown():
    """Return set of filenames used within the last MUSIC_COOLDOWN_DAYS."""
    h      = _load_music_history()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=MUSIC_COOLDOWN_DAYS)).isoformat()
    return {fname for fname, used_at in h.items() if used_at > cutoff}

MOOD_QUERIES = {
    "happy":         "happy upbeat background music no copyright royalty free",
    "funky":         "funky groove upbeat background music no copyright",
    "inspirational": "inspirational uplifting background music no copyright",
}

# YouTube Audio Library internal mood IDs (for the unofficial API)
YT_MOOD_IDS = {"happy": "5", "funky": "4", "inspirational": "6"}


def _yt_audio_library_tracks(mood):
    """Try unofficial YouTube Audio Library API to get free track video IDs."""
    mood_id = YT_MOOD_IDS.get(mood, "5")
    url = (f"https://www.youtube.com/audiolibrary_ajax"
           f"?action_load_tracks=1&filter=2&mood={mood_id}&per_page=20&page=1")
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if r.status_code == 200:
            data = r.json()
            tracks = data.get("tracks", [])
            ids = [t.get("external_id") or t.get("id") for t in tracks if t.get("external_id") or t.get("id")]
            return ids
    except Exception:
        pass
    return []


def _yt_dlp_download(url_or_search, out_base):
    """
    Download best audio via yt-dlp (no ffmpeg needed).
    Returns path to downloaded file, or None.
    AudioFileClip handles webm/opus/m4a/mp3 natively.
    """
    import glob as _glob
    try:
        import yt_dlp
        ydl_opts = {
            "format":      "bestaudio[ext=webm]/bestaudio[ext=m4a]/bestaudio",
            "outtmpl":     out_base + ".%(ext)s",
            "quiet":       True,
            "no_warnings": True,
            "noplaylist":  True,
            "match_filter": lambda i, *, incomplete: None if (i.get("duration") or 0) < 600 else "too long",
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url_or_search])
        except yt_dlp.utils.MaxDownloadsReached:
            pass  # expected when playlist_items limits kick in

        # Find whatever file yt-dlp created matching out_base.*
        matches = _glob.glob(out_base + ".*")
        for f in matches:
            if not f.endswith(".wav") and os.path.getsize(f) > 10000:
                return f
    except Exception:
        pass
    return None


def _find_cached_music(fmt_name, used_tracks=None):
    """
    Return a unique cached track:
    - Not used in this run (used_tracks set)
    - Not used in the last MUSIC_COOLDOWN_DAYS (music_history.json)
    Falls back to least-recently-used if everything is on cooldown.
    """
    import glob as _glob
    mood        = FORMAT_MOODS.get(fmt_name, "happy")
    used_tracks = used_tracks or set()
    on_cooldown = _music_on_cooldown()   # filenames, not full paths

    MAX_MUSIC_BYTES = 30 * 1024 * 1024   # 30 MB cap — above = full video, not audio
    def _eligible(f):
        sz = os.path.getsize(f)
        return (not f.endswith(".wav")
                and 50_000 < sz < MAX_MUSIC_BYTES
                and f not in used_tracks
                and os.path.basename(f) not in on_cooldown)

    def _pick(pattern):
        candidates = [f for f in _glob.glob(pattern) if _eligible(f)]
        if not candidates:  # relax cooldown
            candidates = [f for f in _glob.glob(pattern)
                          if not f.endswith(".wav")
                          and 50_000 < os.path.getsize(f) < MAX_MUSIC_BYTES
                          and f not in used_tracks]
        if candidates:
            chosen = random.choice(candidates)
            _mark_music_used(chosen)
            print(f"  Music: {os.path.basename(chosen)}")
            return chosen
        return None

    # 1. Exact mood match
    result = _pick(f"music_{mood}_*.*")
    if result:
        return result

    # 2. Fallback moods (energetically similar)
    fallback_map = {
        "funky":   ["happy", "bright"],
        "bright":  ["happy", "funky"],
        "rock":    ["funky", "happy"],
        "inspirational": ["happy"],
    }
    for fallback in fallback_map.get(mood, ["happy"]):
        result = _pick(f"music_{fallback}_*.*")
        if result:
            print(f"  Using {fallback} track as fallback for {mood}")
            return result

    # 3. Any track not used in this run
    result = _pick("music_*_*.*")
    if result:
        return result

    # Generated wav fallback
    for f in _glob.glob(f"music_{fmt_name}.wav") + _glob.glob(f"music_{mood}.wav"):
        if os.path.exists(f) and os.path.getsize(f) > 100:
            return f
    return None


def get_music_for_format(fmt_name, used_tracks=None):
    """
    Returns a unique cached track. Downloads new one if cache is empty.
    used_tracks: set of file paths already used in this run.
    """
    cached = _find_cached_music(fmt_name, used_tracks)
    if cached:
        return cached

    mood  = FORMAT_MOODS.get(fmt_name, "happy")
    base  = f"music_{fmt_name}"
    print(f"  Getting {mood} music for {fmt_name}...")

    # ── Try 1: YouTube Audio Library ──
    track_ids = _yt_audio_library_tracks(mood)
    if track_ids:
        vid_id = random.choice(track_ids[:8])
        path = _yt_dlp_download(f"https://www.youtube.com/watch?v={vid_id}", base)
        if path:
            print(f"    YouTube Audio Library track downloaded")
            return path

    # ── Try 2: YouTube search (no-copyright) ──
    query = MOOD_QUERIES.get(mood, MOOD_QUERIES["happy"])
    path  = _yt_dlp_download(f"ytsearch1:{query}", base)
    if path:
        print(f"    YouTube no-copyright track downloaded")
        return path

    # ── Fallback: generated piano + drums ──
    print(f"    Using generated piano music")
    wav = f"{base}.wav"
    generate_piano_track(fmt_name, out_path=wav)
    return wav


def get_bg_music():
    """Long-video music."""
    cached = _find_cached_music("long")
    if cached:
        return cached
    path = _yt_dlp_download(f"ytsearch1:{MOOD_QUERIES['happy']}", "music_long")
    if path:
        return path
    wav = "music_long.wav"
    generate_piano_track("ootd", out_path=wav)
    return wav




# ══════════════════════════════════════════════════════════════════════════════
#  SHOPIFY
# ══════════════════════════════════════════════════════════════════════════════

def fetch_products(limit=100):
    r = requests.get(
        f"https://{SHOPIFY_STORE}/admin/api/2024-01/products.json?limit={limit}&status=active",
        headers={"X-Shopify-Access-Token": SHOPIFY_TOKEN})
    r.raise_for_status()
    return r.json().get("products", [])


PRODUCT_HISTORY_FILE = "product_history.json"
PRODUCT_COOLDOWN_DAYS = 10


def load_product_history():
    """Load {product_id: last_used_date} from file."""
    if os.path.exists(PRODUCT_HISTORY_FILE):
        try:
            with open(PRODUCT_HISTORY_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_product_history(history):
    with open(PRODUCT_HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)


def pick_unique_products(n, exclude_ids=None):
    """
    Pick n products not used in last PRODUCT_COOLDOWN_DAYS days.
    Falls back to oldest-used products if pool is too small.
    """
    exclude_ids = set(exclude_ids or [])
    history     = load_product_history()
    cutoff      = (datetime.now(timezone.utc) - timedelta(days=PRODUCT_COOLDOWN_DAYS)).isoformat()

    # Products used within cooldown window — exclude them
    recent = {pid for pid, used_at in history.items() if used_at > cutoff}
    exclude_ids |= recent

    all_products = fetch_products(limit=250)
    pool = [p for p in all_products if str(p["id"]) not in exclude_ids]

    # If pool too small, fall back to least-recently-used products
    if len(pool) < n:
        extras = sorted(
            [p for p in all_products if str(p["id"]) not in {str(i) for i in (exclude_ids - recent)}],
            key=lambda p: history.get(str(p["id"]), "1970-01-01")
        )
        pool = pool + [p for p in extras if p not in pool]

    chosen = random.sample(pool, min(n, len(pool)))

    # Record usage
    now = datetime.now(timezone.utc).isoformat()
    for p in chosen:
        history[str(p["id"])] = now
    save_product_history(history)

    return chosen


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
    from PIL import ImageEnhance
    img = Image.open(img_path).convert("RGB")
    iw, ih = img.size
    if iw/ih > w/h:
        nw = int(ih*(w/h)); img = img.crop(((iw-nw)//2,0,(iw-nw)//2+nw,ih))
    else:
        nh = int(iw/(w/h)); img = img.crop((0,(ih-nh)//2,iw,(ih-nh)//2+nh))
    img = img.resize((w, h), Image.LANCZOS)
    # Enhance vibrancy — makes products pop like professional product photography
    img = ImageEnhance.Color(img).enhance(1.25)
    img = ImageEnhance.Contrast(img).enhance(1.08)
    img = ImageEnhance.Sharpness(img).enhance(1.15)
    img = ImageEnhance.Brightness(img).enhance(1.04)
    return img

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
    return img  # keep RGBA so build_frame retains transparency

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

# ══════════════════════════════════════════════════════════════════════════════
#  AI BACKGROUND GENERATION — Pollinations.ai (primary) + picsum (fallback)
#  Each image in the video gets a DIFFERENT AI-generated background scene.
# ══════════════════════════════════════════════════════════════════════════════

POLLINATIONS_BASE_PROMPTS = {
    "beach":       "sun-drenched beach in Malibu California, fine white sand, turquoise water, empty beach, golden hour light, fashion photography, shallow depth of field, 8k, no people, no text",
    "park":        "lush Central Park New York spring, cherry blossoms, green grass, empty pathway, dappled sunlight, fashion lifestyle photography, bokeh, 8k, no people, no text",
    "rooftop":     "luxury rooftop terrace Miami golden hour, city skyline, warm string lights, elegant outdoor lounge, fashion editorial photography, bokeh, no people, no text",
    "city":        "upscale shopping street Beverly Hills, boutique storefronts, palm trees, golden afternoon light, empty sidewalk, fashion lifestyle photography, bokeh, no people, no text",
    "cafe":        "chic outdoor cafe terrace SoHo New York, morning sunlight, white bistro chairs, lush greenery, lifestyle fashion photography, soft focus, no people, no text",
    "garden":      "beautiful private garden Hamptons estate, blooming roses and lavender, stone pathway, soft afternoon light, fashion photography, bokeh, no people, no text",
    "yacht":       "luxury yacht deck Mediterranean, turquoise sea, white railing, sunny day, elegant outdoor space, fashion lifestyle photography, bokeh, no people, no text",
    "living_room": "bright modern luxury living room USA, large windows, natural light, neutral designer tones, elegant furniture, fashion lifestyle photography, no people, no text",
}

SCENE_PICSUM = {   # fallback seeds
    "beach":"870","park":"1448","city":"1067","rooftop":"1560",
    "cafe":"1090","garden":"157","yacht":"870","living_room":"1090",
}
SCENE_NAMES = list(POLLINATIONS_BASE_PROMPTS.keys())

SCENE_GRADIENTS = {
    "beach":[(255,225,140),(80,175,225)],  "park":[(100,195,80),(30,120,40)],
    "city":[(110,140,225),(45,75,170)],    "rooftop":[(175,195,220),(95,115,155)],
    "cafe":[(255,200,130),(195,130,55)],   "garden":[(240,240,255),(175,180,210)],
    "yacht":[(200,230,255),(60,140,200)],  "living_room":[(255,245,220),(200,180,140)],
}

# Colour-gradient fallbacks if Unsplash download fails
SCENE_GRADIENTS = {
    "beach":       [(255, 225, 140), (80, 175, 225)],
    "park":        [(100, 195, 80),  (30, 120, 40)],
    "city":        [(110, 140, 225), (45, 75, 170)],
    "building":    [(175, 195, 220), (95, 115, 155)],
    "living_room": [(255, 200, 130), (195, 130, 55)],
    "studio":      [(240, 240, 255), (175, 180, 210)],
}


def generate_pollinations_bg(scene_name, seed, cache_key, product_title=""):
    """Pollinations.ai background (primary) → picsum.photos (fallback)."""
    cache = f"bg_{cache_key}.jpg"
    if os.path.exists(cache) and os.path.getsize(cache) > 10000:
        return cache

    def _save(content):
        with open(cache, "wb") as f: f.write(content)
        return cache

    prompt = POLLINATIONS_BASE_PROMPTS.get(scene_name, POLLINATIONS_BASE_PROMPTS["beach"])
    try:
        r = requests.get(
            f"https://image.pollinations.ai/prompt/{_url_quote(prompt)}"
            f"?width=1080&height=1920&model=flux&nologo=true&enhance=true&seed={seed}",
            timeout=90)
        if r.status_code == 200 and len(r.content) > 20000:
            return _save(r.content)
    except Exception:
        pass

    seed_str = SCENE_PICSUM.get(scene_name, "100")
    try:
        r = requests.get(f"https://picsum.photos/seed/{seed_str}/1080/1920",
                         allow_redirects=True, timeout=20)
        if r.status_code == 200 and len(r.content) > 10000:
            return _save(r.content)
    except Exception:
        pass
    return None


def scenes_for_product(title, tags=""):
    """AI or rule-based scene selection matching the product category."""
    # Try AI first for creative, contextual scene selection
    prompt = (f"Choose 4 best background scene names from this list for a fashion video of: '{title}'. "
              f"List: beach, park, rooftop, city, cafe, garden, yacht, living_room. "
              f"Reply with exactly 4 names comma-separated, most fitting first. No explanation.")
    result = ai_client.generate(prompt, max_tokens=30, temperature=0.5)
    if result:
        chosen = [s.strip().lower() for s in result.split(",")
                  if s.strip().lower() in POLLINATIONS_BASE_PROMPTS]
        if len(chosen) >= 2:
            return chosen

    # Rule-based fallback
    t = (title + " " + tags).lower()
    if any(w in t for w in ["dress","gown","midi","maxi","sundress","skirt","romper"]):
        return ["beach", "garden", "rooftop", "yacht"]
    if any(w in t for w in ["jean","pant","trouser","short","legging"]):
        return ["city", "park", "cafe", "rooftop"]
    if any(w in t for w in ["top","blouse","shirt","tank","tee","tunic"]):
        return ["cafe", "rooftop", "garden", "yacht"]
    if any(w in t for w in ["jacket","coat","blazer","sweater","cardigan"]):
        return ["city", "park", "cafe", "rooftop"]
    if any(w in t for w in ["bag","purse","tote","crossbody","sling","clutch","backpack"]):
        return ["city", "cafe", "rooftop", "yacht"]
    return ["beach", "park", "city", "cafe", "garden"]


def _scene_background(scene_name, w, h, seed=None, cache_key=None, product_title=""):
    """Return AI-generated background as numpy array. Pollinations.ai → picsum → gradient."""
    seed = seed or random.randint(1000, 99999)
    ck   = cache_key or f"{scene_name}_{seed}"
    bg_path = generate_pollinations_bg(scene_name, seed, ck, product_title)
    if bg_path:
        bg = _prep(bg_path, w, h).filter(ImageFilter.GaussianBlur(radius=5))
    else:
        colors = SCENE_GRADIENTS.get(scene_name, SCENE_GRADIENTS["city"])
        bg = Image.new("RGB", (w, h))
        dr = ImageDraw.Draw(bg)
        for y in range(h):
            t = y/h; c = [int(colors[0][i]+t*(colors[1][i]-colors[0][i])) for i in range(3)]
            dr.line([(0, y), (w, y)], fill=tuple(c))
    return np.array(bg)


# ══════════════════════════════════════════════════════════════════════════════
#  6 CONTENT FORMATS  (what the video "is about")
# ══════════════════════════════════════════════════════════════════════════════

CONTENT_FORMATS = {
    "ootd": {
        "badge":     "OOTD",
        "hook":      "Today's Look",
        "voiceover": lambda t, p: random.choice([
            f"Ladies, wait until you see today's look! This {t} from MeeeShop is only {p} dollars and I am OBSESSED. Free shipping too. Grab it now — link in description!",
            f"Today's outfit check! I'm wearing the {t} from MeeeShop. It's just {p} dollars and it goes with everything. Shop the link in description before it sells out!",
            f"This {t} has been getting me so many compliments. Only {p} dollars at MeeeShop. Link in description — thank me later!",
        ]),
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
        "voiceover": lambda t, p: random.choice([
            f"Okay so I styled this {t} three different ways and every single one is a winner. Only {p} dollars at MeeeShop. Link in description to shop it now!",
            f"This {t} is so versatile it's not even funny. Work look, brunch look, night out look — all for {p} dollars. MeeeShop dot com, link in description!",
            f"You need this {t} in your closet immediately. Three outfits, one piece, only {p} dollars. Shop MeeeShop — link in description!",
        ]),
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
        "voiceover": lambda t, p: random.choice([
            f"STOP scrolling! This {t} just dropped at MeeeShop and it is everything. Only {p} dollars. These will sell out FAST. Link in description — shop it right now!",
            f"New arrival alert! The {t} just hit MeeeShop and I need everyone to see this. {p} dollars. Free shipping. Link in description. Go go go!",
            f"Drop everything because this {t} just landed at MeeeShop. {p} dollars and it's already flying off the shelves. Link in description before it's gone!",
        ]),
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
        "voiceover": lambda t, p: random.choice([
            f"This {t} is literally everywhere right now — and MeeeShop has it for only {p} dollars. Everyone's been asking where to get this. Link in description, shop it today!",
            f"The trend you need right now? This {t}. Only {p} dollars at MeeeShop. Free US shipping. Be the first in your group to wear it — link in description!",
            f"This {t} is going viral for a reason. Get it from MeeeShop for just {p} dollars before everyone else does. Link in description!",
        ]),
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
        "voiceover": lambda t, p: random.choice([
            f"You will NOT believe this price. This {t} is only {p} dollars at MeeeShop. I said {p} DOLLARS. Free shipping included. Link in description — this is a steal!",
            f"Okay this {t} looks like it costs five times more than {p} dollars. MeeeShop is giving it away basically. Link in description before they realize what they're doing!",
            f"Fashion steal of the year! This stunning {t} is just {p} dollars at MeeeShop. Look expensive for less. Free US shipping. Link in description!",
        ]),
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
        "voiceover": lambda t, p: random.choice([
            f"If you've been looking for your next favorite outfit, I just found it for you. This {t} from MeeeShop is stunning and it's only {p} dollars. Link in description!",
            f"Your next obsession just arrived. This {t} from MeeeShop — {p} dollars, free shipping, and it's GORGEOUS. Click the link in description and thank yourself later!",
            f"I am giving you the best style inspo right now. This {t} from MeeeShop for just {p} dollars. This is the vibe we need. Shop it — link in description!",
        ]),
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

STYLE_TIP_LABELS = ["Dress It Up", "Keep It Casual", "Night Out Look"]


_REMBG_SESSION = None   # cached session — avoid reloading model for each image

def _get_rembg_session():
    global _REMBG_SESSION
    if _REMBG_SESSION is None:
        from rembg import new_session
        _REMBG_SESSION = new_session("u2net_human_seg")  # keeps full body: face+hands+legs
    return _REMBG_SESSION


def _remove_bg(img_path):
    """
    Remove product photo background so the full model appears over the real scene.
    Strategy 1: rembg u2net_human_seg — keeps face, hands, legs (best).
    Strategy 2: PIL colour-based — works for white studio backgrounds.
    Strategy 3: original RGBA fallback.
    """
    # ── Strategy 1: rembg human-segmentation AI ────────────────────────────
    try:
        from rembg import remove
        import io
        with open(img_path, "rb") as f:
            data = f.read()
        session = _get_rembg_session()
        result  = remove(data, session=session)
        img = Image.open(io.BytesIO(result)).convert("RGBA")
        print("  BG: AI human-seg (full body kept)")
        return _defringe_rgba(img)
    except Exception:
        pass

    # ── Strategy 2: PIL colour-based removal for light/white studio backgrounds ─
    try:
        img  = Image.open(img_path).convert("RGBA")
        data = np.array(img)
        rgb  = data[:, :, :3].astype(np.float32)
        h, w = rgb.shape[:2]

        # Sample background colour from image borders
        border = np.concatenate([
            rgb[0, :, :], rgb[-1, :, :],
            rgb[:, 0, :], rgb[:, -1, :]
        ])
        bg = np.median(border, axis=0)

        # Only apply if background is clearly light (studio/white)
        if np.mean(bg) >= 185:
            diff  = np.sqrt(np.sum((rgb - bg) ** 2, axis=-1))
            alpha = data[:, :, 3].copy()
            alpha[diff < 40] = 0          # background → transparent
            # Soften jagged edges slightly
            from PIL import ImageFilter
            mask_img = Image.fromarray(alpha)
            mask_img = mask_img.filter(ImageFilter.SMOOTH_MORE)
            alpha    = np.array(mask_img)
            result   = data.copy(); result[:, :, 3] = alpha
            print(f"  BG: colour removal (bg≈{int(np.mean(bg))})")
            return Image.fromarray(result)
    except Exception as e:
        print(f"  BG: colour removal failed ({e})")

    # ── Strategy 3: original image ────────────────────────────────────────
    print("  BG: using original (no removal)")
    return Image.open(img_path).convert("RGBA")


def _defringe_rgba(img_rgba, bg=(255, 255, 255)):
    """Remove background colour contamination from semi-transparent edge pixels."""
    try:
        data  = np.array(img_rgba).astype(np.float32)
        alpha = data[:, :, 3] / 255.0
        mask  = alpha > 0.05
        for c in range(3):
            data[:, :, c] = np.where(
                mask,
                np.clip((data[:, :, c] - bg[c] * (1 - alpha)) / np.maximum(alpha, 0.05), 0, 255),
                data[:, :, c])
        return Image.fromarray(data.clip(0, 255).astype(np.uint8))
    except Exception:
        return img_rgba


def _product_rgba(img_path, w, h):
    """
    Returns RGBA: product/model with background REMOVED, centred (82% height).
    The studio/white background is cut out by AI — only model remains.
    Composited over the real animated scene background in ken_burns_clip.
    """
    from PIL import ImageEnhance

    raw = _remove_bg(img_path)              # RGBA, background transparent
    alpha_mask = raw.split()[3]             # keep original alpha mask

    # Enhance product colours (work on RGB then restore alpha)
    raw_rgb = raw.convert("RGB")
    raw_rgb = ImageEnhance.Color(raw_rgb).enhance(1.30)
    raw_rgb = ImageEnhance.Contrast(raw_rgb).enhance(1.10)
    raw_rgb = ImageEnhance.Sharpness(raw_rgb).enhance(1.20)
    raw_rgb = ImageEnhance.Brightness(raw_rgb).enhance(1.05)
    raw = raw_rgb.convert("RGBA")
    raw.putalpha(alpha_mask)                # restore alpha

    ph = int(h * 0.82)
    pw = int(ph * raw.width / raw.height)
    if pw > int(w * 0.98):
        pw = int(w * 0.98); ph = int(pw * raw.height / raw.width)
    fg = raw.resize((pw, ph), Image.LANCZOS)

    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    canvas.paste(fg, ((w - pw) // 2, int(h * 0.01)), mask=fg.split()[3])

    # Semi-transparent dark gradient at bottom for text readability
    grad = Image.new("RGBA", (w, 760), (0, 0, 0, 0))
    gd   = ImageDraw.Draw(grad)
    for y in range(760):
        a = int((y / 760) ** 1.4 * 218)
        gd.line([(0, y), (w, y)], fill=(0, 0, 0, a))
    canvas.alpha_composite(grad, dest=(0, h - 760))
    return canvas


def build_frame(img_path, product, style_name, fmt_name,
                show_url=False, frame_idx=0, scene_name="studio",
                w=VIDEO_W, h=VIDEO_H):
    title  = product["title"]
    price  = product["variants"][0]["price"] if product.get("variants") else "0"
    handle = product.get("handle","")
    url    = (f"us.meeeshop.com/products/{handle}?utm_source=youtube&utm_medium=shorts&utm_campaign=meeeshop"
              if handle else
              "us.meeeshop.com?utm_source=youtube&utm_medium=shorts&utm_campaign=meeeshop")

    # RGBA canvas: product centred on transparent background
    img  = _product_rgba(img_path, w, h)
    draw = ImageDraw.Draw(img)
    _logo(draw)

    if fmt_name == "ootd":
        # ── OOTD: big "TODAY'S LOOK" header, warm gold accents ──────────────
        img  = _gradient(img, (0,0,0,0), (20,10,5,220), h-700, h)
        draw = ImageDraw.Draw(img)
        _logo(draw)
        _pill(draw, "✨  TODAY'S LOOK  ✨", w//2, 90, _font(FONT_BOLD,42),
              (255,210,60), (20,20,20), 32, 14, 24)
        _title_lines(draw, title, h-490, "white", 60)
        draw.text((w//2, h-250), f"Complete this look for just ${price}",
                  font=_font(FONT_REG,34), fill=(255,220,130), anchor="mm")
        _cta(draw, "Shop The Look ->", (255,210,60), "black")

    elif fmt_name == "how_to_style":
        # ── HOW TO STYLE: numbered tip per image, editorial feel ─────────────
        img  = _gradient(img, (0,0,0,0), (10,15,30,215), h-700, h)
        draw = ImageDraw.Draw(img)
        _logo(draw)
        _pill(draw, "HOW TO STYLE IT", w//2, 90, _font(FONT_BOLD,40),
              (255,255,255), (20,20,20), 28, 12, 22)
        tip_idx = frame_idx % len(STYLE_TIP_LABELS)
        _pill(draw, f"  {tip_idx+1}  {STYLE_TIP_LABELS[tip_idx]}  ",
              w//2, h-560, _font(FONT_BOLD,38), (80,160,255), "white", 22, 12, 20)
        _title_lines(draw, title, h-470, "white", 56)
        _price_text(draw, price, h-215, (130,210,255))
        _cta(draw, "See All Styles ->", (80,160,255), "white")

    elif fmt_name == "new_drop":
        # ── NEW DROP: urgency, bold announcement, red accent ─────────────────
        img  = _gradient(img, (0,0,0,0), (30,5,5,225), h-700, h)
        draw = ImageDraw.Draw(img)
        _logo(draw)
        _pill(draw, "🆕  JUST DROPPED", w//2, 90, _font(FONT_BOLD,44),
              (220,40,40), "white", 28, 14, 24)
        _title_lines(draw, title, h-490, "white", 60)
        if frame_idx == 0:
            _pill(draw, "⚡ LIMITED STOCK — ACT FAST",
                  w//2, h-280, _font(FONT_BOLD,32), (255,200,0), (30,0,0), 20,10,16)
        _price_text(draw, price, h-215, (255,100,100))
        _cta(draw, "Shop Before It's Gone ->", (220,40,40), "white")

    elif fmt_name == "trend_alert":
        # ── TREND ALERT: fire orange, viral energy ───────────────────────────
        img  = _gradient(img, (0,0,0,0), (25,10,0,220), h-700, h)
        draw = ImageDraw.Draw(img)
        _logo(draw)
        _pill(draw, "🔥  TRENDING NOW", w//2, 90, _font(FONT_BOLD,44),
              (255,100,20), "white", 28, 14, 24)
        draw.text((w//2, 155), "Seen all over the USA",
                  font=_font(FONT_REG,34), fill=(255,180,100), anchor="mm")
        _title_lines(draw, title, h-480, "white", 58)
        _price_text(draw, price, h-215, (255,140,50))
        _cta(draw, "Get The Trend ->", (255,100,20), "white")

    elif fmt_name == "fashion_steal":
        # ── FASHION STEAL: BIG price front-and-center, deal focus ────────────
        img  = _gradient(img, (0,0,0,0), (5,20,5,220), h-700, h)
        draw = ImageDraw.Draw(img)
        _logo(draw)
        _pill(draw, "💰  FASHION STEAL", w//2, 90, _font(FONT_BOLD,42),
              (50,200,80), "white", 28, 14, 24)
        # Giant price as headline
        draw.text((w//2, h-540), f"ONLY", font=_font(FONT_BOLD,44),
                  fill=(200,255,200), anchor="mm")
        draw.text((w//2, h-470), f"${price}", font=_font(FONT_BOLD,100),
                  fill=(50,230,90), anchor="mm",
                  stroke_width=4, stroke_fill=(0,0,0))
        draw.text((w//2, h-375), "Look like you spent $500",
                  font=_font(FONT_REG,32), fill=(200,255,200), anchor="mm")
        _title_lines(draw, title, h-310, "white", 46)
        _cta(draw, "Grab This Deal ->", (50,200,80), "white")

    else:  # styling_inspo — editorial/magazine minimal
        # ── STYLING INSPO: magazine editorial, clean & aspirational ──────────
        img  = _gradient(img, (0,0,0,0), (15,5,25,215), h-700, h)
        draw = ImageDraw.Draw(img)
        _logo(draw)
        _pill(draw, "🌟  STYLE INSPO", w//2, 90, _font(FONT_BOLD,42),
              (200,160,255), (10,0,20), 28, 14, 24)
        draw.text((w//2, 155), "MeeeShop Curated Edit",
                  font=_font(FONT_REG,32), fill=(200,180,255), anchor="mm")
        _title_lines(draw, title, h-490, (240,225,255), 58)
        _price_text(draw, price, h-215, (200,160,255))
        _cta(draw, "Get The Look ->", (200,160,255), (10,0,20))

    if show_url:
        _url_bar(draw, url)
    return img


# ══════════════════════════════════════════════════════════════════════════════
#  KEN BURNS  (zoom/pan every clip — direction shuffled)
# ══════════════════════════════════════════════════════════════════════════════

DIRECTIONS = ["zoom_in","zoom_out","pan_right","pan_left","pan_up","pan_down"]


def ken_burns_clip(img_path, product, style_name, fmt_name,
                   duration, direction, frame_idx=0,
                   show_url=False, scene_name="beach",
                   seed=None, cache_key=None, w=VIDEO_W, h=VIDEO_H):
    """
    BACKGROUND: Pollinations.ai AI-generated scene, Ken-Burns animated.
    FOREGROUND: model with BG removed (u2net_human_seg), sharp + static.
    Result: model appears sharp in front, real background moves behind them.
    """
    sw, sh = int(w * 1.25), int(h * 1.25)

    # ── 1. Background: Pollinations.ai AI scene, enlarged for Ken Burns room ─
    bg_arr = _scene_background(scene_name, sw, sh, seed=seed, cache_key=cache_key)

    # ── 2. Product + text overlay: RGBA (transparent background areas) ──────
    styled      = build_frame(img_path, product, style_name, fmt_name,
                              show_url, frame_idx, scene_name, w, h)
    overlay_arr = np.array(styled.convert("RGBA"))  # ensure RGBA
    alpha       = overlay_arr[:, :, 3:4].astype(np.float32) / 255.0
    rgb         = overlay_arr[:, :, :3].astype(np.float32)

    def make_frame(t):
        p  = t / duration
        sc = {"zoom_in": 1.0 - 0.20*p, "zoom_out": 0.80 + 0.20*p}.get(direction, 0.90)
        cw, ch = int(sw*sc), int(sh*sc)
        if   direction == "pan_right": x0,y0 = int((sw-cw)*p), (sh-ch)//2
        elif direction == "pan_left":  x0,y0 = int((sw-cw)*(1-p)), (sh-ch)//2
        elif direction == "pan_up":    x0,y0 = (sw-cw)//2, int((sh-ch)*p)
        elif direction == "pan_down":  x0,y0 = (sw-cw)//2, int((sh-ch)*(1-p))
        else:                          x0,y0 = (sw-cw)//2, (sh-ch)//2
        x0, y0 = max(0, min(x0, sw-cw)), max(0, min(y0, sh-ch))

        # Animated background (full colour, crisp)
        crop = bg_arr[y0:y0+ch, x0:x0+cw]
        bg   = np.array(Image.fromarray(crop).resize((w, h), Image.LANCZOS),
                        dtype=np.float32)

        # Alpha-composite RGBA product overlay over animated background
        result = bg * (1.0 - alpha) + rgb * alpha
        return result.clip(0, 255).astype(np.uint8)

    return VideoClip(make_frame, duration=duration).set_fps(FPS)


# ══════════════════════════════════════════════════════════════════════════════
#  AUDIO — sparse voiceover + happy background music
# ══════════════════════════════════════════════════════════════════════════════

def _vo(text, path):
    gTTS(text=text, lang="en", tld="us").save(path)
    return AudioFileClip(path)


def ai_voiceover_text(product, fmt_name):
    """AI-generated engaging voiceover script. Falls back to format templates."""
    title  = product["title"]
    price  = product["variants"][0]["price"] if product.get("variants") else "0"
    fmt    = CONTENT_FORMATS.get(fmt_name, {})
    badge  = fmt.get("badge", "OOTD")
    prompt = (
        f"Write a 2-sentence exciting USA women's fashion TikTok/YouTube Shorts voiceover for:\n"
        f"Product: '{title}' — ${price} at MeeeShop\n"
        f"Style: {badge} — high energy, like a real USA fashion influencer\n"
        f"Rules: mention price, mention MeeeShop, end with 'link in description', under 35 words, no hashtags\n"
        f"Output ONLY the voiceover text, nothing else."
    )
    result = ai_client.generate(prompt, max_tokens=80, temperature=0.9)
    if result and len(result) > 20:
        return result.strip()
    # Fallback to format lambda
    vo_fn = fmt.get("voiceover")
    if callable(vo_fn):
        return vo_fn(title, price)
    return f"You need this {title} from MeeeShop! Only ${price} dollars. Link in description!"


def build_audio(product, fmt_name, total_dur, tmp_dir, music_path):
    """Piano+drums music throughout. AI-generated voiceover at the END only."""
    price = product["variants"][0]["price"] if product.get("variants") else "0"

    # AI-generated voiceover — plays at the very end only
    cta = ai_voiceover_text(product, fmt_name)
    p1  = os.path.join(tmp_dir, "vo_cta.mp3")
    vo  = _vo(cta, p1)
    vo_start = max(0, total_dur - vo.duration - 0.5)
    print(f"  Voiceover: {cta[:60]}...")

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

def create_short(product, style_name, fmt_name, out_path, used_tracks=None):
    title  = product["title"]
    price  = product["variants"][0]["price"] if product.get("variants") else "0"
    handle = product.get("handle","")
    url    = (f"us.meeeshop.com/products/{handle}?utm_source=youtube&utm_medium=shorts&utm_campaign=meeeshop"
              if handle else
              "us.meeeshop.com?utm_source=youtube&utm_medium=shorts&utm_campaign=meeeshop")

    print(f"  Product : {title[:50]}")
    print(f"  Style   : {style_name} | Format: {fmt_name}")

    tmp_i = "tmp_imgs"; tmp_v = "tmp_vo"
    try:
        imgs = download_images(product, tmp_i)
        if not imgs: raise RuntimeError("No images")
        os.makedirs(tmp_v, exist_ok=True)
        music = get_music_for_format(fmt_name, used_tracks)
        if used_tracks is not None and music:
            used_tracks.add(music)

        # AI picks contextually appropriate scenes for this product
        scenes_pool = scenes_for_product(title, product.get("tags",""))
        print(f"  Scenes  : {scenes_pool[:len(imgs)]}")
        dirs   = random.sample(DIRECTIONS, len(DIRECTIONS))
        clips  = []
        for idx, img_path in enumerate(imgs):
            show_url   = (idx == len(imgs)-1)
            scene_name = scenes_pool[idx % len(scenes_pool)]
            seed       = random.randint(1000, 99999)   # unique seed → different BG each image
            cache_key  = f"{scene_name}_{seed}"
            print(f"  Image {idx+1}: {scene_name} bg (Pollinations.ai seed={seed})")
            clip = ken_burns_clip(img_path, product, style_name, fmt_name,
                                  IMG_DURATION, dirs[idx%len(dirs)], idx,
                                  show_url, scene_name, seed=seed, cache_key=cache_key)
            clip = clip.fadein(0.3).fadeout(0.3)
            clips.append(clip)

        video = concatenate_videoclips(clips, method="compose")
        audio = build_audio(product, fmt_name, video.duration, tmp_v, music)
        final = video.set_audio(audio)
        final.write_videofile(out_path, fps=FPS, codec="libx264", audio_codec="aac",
                              temp_audiofile="tmp_audio.m4a", remove_temp=True,
                              verbose=False, logger=None,
                              ffmpeg_params=["-crf", "18", "-preset", "fast",
                                             "-b:a", "192k"])
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
                              verbose=False, logger=None,
                              ffmpeg_params=["-crf", "18", "-preset", "fast",
                                             "-b:a", "192k"])
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
    if TESTING_MODE:
        # Draft mode: private, no publish date — review in YouTube Studio first
        status = {"privacyStatus": "private", "selfDeclaredMadeForKids": False}
        print("    [TESTING] Uploading as private draft for review.")
    else:
        status = {"privacyStatus": "private", "selfDeclaredMadeForKids": False,
                  "publishAt": slot_utc}

    body = {
        "snippet": {
            "title":                yt_title,
            "description":          desc,
            "tags":                 tags,
            "categoryId":           "26",
            "defaultLanguage":      "en",
            "defaultAudioLanguage": "en-US",
        },
        "status": status,
        "recordingDetails": {
            "locationDescription": "United States",
            "location": {"latitude": 37.0902, "longitude": -95.7129, "altitude": 0},
        },
    }
    media = MediaFileUpload(video_path, mimetype="video/mp4", resumable=True)
    req   = yt.videos().insert(
        part=",".join(body.keys()), body=body, media_body=media)
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
        f"Shop everything at: https://us.meeeshop.com\n\n"
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

    # Pre-pick all products for today — 10-day cooldown enforced
    all_products = pick_unique_products(3 + (8 if today_long else 0))
    short_products = all_products[:3]
    long_products  = all_products[3:] if today_long else []

    used_tracks = set()   # tracks used in this run — ensures no repeats
    short_video_ids = []

    for i, (slot_utc, slot_local) in enumerate(slots):
        print(f"\n--- Short {i+1}/3 | {formats[i].upper()} | {styles[i]} ---")
        product = short_products[i]
        out     = f"short_{product['id']}_{i}.mp4"
        _, prod_url = create_short(product, styles[i], formats[i], out, used_tracks)
        vid = upload_short(out, product, formats[i], prod_url, slot_utc, slot_local)
        short_video_ids.append(vid)
        if os.path.exists(out): os.remove(out)

    if today_long and long_products:
        print("\n--- Long Video (Weekly Picks) ---")
        out = "long_video.mp4"
        create_long_video(long_products, out)
        upload_long(out, long_products)
        if os.path.exists(out): os.remove(out)

    print("\n=== All done! ===")
    for vid in short_video_ids:
        print(f"  https://www.youtube.com/shorts/{vid}")


if __name__ == "__main__":
    main()

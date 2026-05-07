"""
Downloads 6 unique tracks per mood (happy / inspirational / rock)
from YouTube — each track uses a DIFFERENT search query so all 18
files are genuinely different audio. Instrumental-only queries prevent
vocal/foreign-language tracks. Run once; tracks are cached locally.

Usage:
    python setup_music.py            # download missing tracks only
    python setup_music.py --refresh  # re-download all tracks fresh
"""
import os, glob, hashlib, time, argparse, pickle
import requests

# GitHub Actions sets CI=true — yt-dlp is blocked by YouTube bot detection in CI.
# When IN_CI, generate piano tracks locally instead of downloading.
IN_CI = os.getenv("CI", "").lower() == "true"

# ── 6 unique search queries per mood ──────────────────────────────────────────
# Each query is distinct so yt-dlp returns a different video each time.
# "instrumental", "no lyrics", "no vocals" filters prevent foreign-language tracks.

QUERIES = {
    "happy": [
        "ytsearch1:happy upbeat instrumental background music royalty free no lyrics",
        "ytsearch1:bright cheerful acoustic guitar instrumental music free to use",
        "ytsearch1:positive upbeat ukulele instrumental music no copyright",
        "ytsearch1:fun energetic piano background music no vocals royalty free",
        "ytsearch1:light pop instrumental background music no lyrics free download",
        "ytsearch1:sunny happy background music instrumental no singing royalty free",
    ],
    "inspirational": [
        "ytsearch1:inspirational orchestral background music instrumental no lyrics royalty free",
        "ytsearch1:uplifting cinematic instrumental music no copyright no vocals",
        "ytsearch1:motivational piano background music instrumental no lyrics free",
        "ytsearch1:epic uplifting background music instrumental no singing",
        "ytsearch1:emotional inspiring strings background music no copyright no vocals",
        "ytsearch1:hope uplifting acoustic instrumental background music royalty free",
    ],
    "rock": [
        "ytsearch1:rock guitar loop background music short royalty free no lyrics",
        "ytsearch1:short rock instrumental music free to use no lyrics 60 seconds",
        "ytsearch1:upbeat rock background music clip royalty free instrumental",
        "ytsearch1:indie rock background short clip instrumental no vocals no copyright",
        "ytsearch1:energetic guitar riff background music short royalty free",
        "ytsearch1:rock beat short instrumental music no copyright no singing",
    ],
    "funky": [
        "ytsearch1:funky groove instrumental background music royalty free no lyrics",
        "ytsearch1:funk bass guitar instrumental music no copyright no vocals",
        "ytsearch1:upbeat funky pop instrumental background music free to use",
        "ytsearch1:groovy funk background music instrumental no lyrics royalty free",
        "ytsearch1:funky rhythm instrumental background music no singing free",
        "ytsearch1:disco funk instrumental background music no copyright royalty free",
    ],
    "bright": [
        "ytsearch1:bright upbeat acoustic instrumental background music royalty free",
        "ytsearch1:cheerful bright pop instrumental music no lyrics no copyright",
        "ytsearch1:light airy background music instrumental no vocals royalty free",
        "ytsearch1:bright energetic background music short instrumental free to use",
        "ytsearch1:fresh bright guitar instrumental music no copyright no lyrics",
        "ytsearch1:uplifting bright background music instrumental no singing royalty free",
    ],
}

TRACKS_PER_MOOD = 6


# ── File utilities ────────────────────────────────────────────────────────────

def file_hash(path, chunk=1024 * 512):
    """MD5 of first 512 KB — fast uniqueness check."""
    h = hashlib.md5()
    with open(path, "rb") as f:
        h.update(f.read(chunk))
    return h.hexdigest()


MAX_TRACK_BYTES = 30 * 1024 * 1024   # 30 MB — above this is a full video, not audio-only

def existing_tracks(mood):
    """Return list of valid cached tracks for this mood (audio-only, < 30 MB)."""
    files = glob.glob(f"music_{mood}_*.webm") + glob.glob(f"music_{mood}_*.m4a")
    return [f for f in files
            if 50_000 < os.path.getsize(f) < MAX_TRACK_BYTES]


def all_hashes(mood):
    return {file_hash(f) for f in existing_tracks(mood)}


# ── yt-dlp download ───────────────────────────────────────────────────────────

def yt_download(search_query, out_base):
    """Download audio-only stream. Returns file path or None."""
    try:
        import yt_dlp
        opts = {
            "format":       "bestaudio[ext=webm]/bestaudio[ext=m4a]/bestaudio",
            "outtmpl":      out_base + ".%(ext)s",
            "quiet":        True,
            "no_warnings":  True,
            "noplaylist":   True,
            # Skip videos longer than 5 minutes (compilations, full albums)
            "match_filter": lambda i, **_: (
                None if (i.get("duration") or 999) <= 300 else "too long"
            ),
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([search_query])
        for ext in ["webm", "m4a", "opus", "mp3"]:
            p = out_base + "." + ext
            if os.path.exists(p):
                size = os.path.getsize(p)
                if size > MAX_TRACK_BYTES:
                    os.remove(p)   # video file — too large, skip it
                    return None
                if size > 50_000:
                    return p
    except Exception as e:
        print(f"    yt-dlp error: {e}")
    return None


# ── Auth for YouTube Studio API ───────────────────────────────────────────────

def get_access_token():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from dotenv import load_dotenv
    load_dotenv()
    rt = os.getenv("YOUTUBE_REFRESH_TOKEN")
    if rt:
        creds = Credentials(
            token=None, refresh_token=rt,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=os.getenv("YOUTUBE_CLIENT_ID"),
            client_secret=os.getenv("YOUTUBE_CLIENT_SECRET"),
        )
        creds.refresh(Request())
        return creds.token
    if os.path.exists("youtube_token.pickle"):
        with open("youtube_token.pickle", "rb") as f:
            creds = pickle.load(f)
        if not creds.valid and creds.refresh_token:
            from google.auth.transport.requests import Request as Req
            creds.refresh(Req())
        return creds.token
    return None


def fetch_audio_library_ids(access_token, mood_key, count=20):
    """Try to get track IDs from YouTube Audio Library (last 60 days)."""
    mood_map  = {"happy": "5", "inspirational": "6", "rock": "3", "funky": "4", "bright": "10"}
    mood_id   = mood_map.get(mood_key, "5")
    mood_name = mood_key.upper()
    headers   = {
        "Authorization": f"Bearer {access_token}",
        "User-Agent":    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer":       "https://www.youtube.com/",
    }

    # Attempt 1: old audiolibrary_ajax endpoint (no auth needed but try with auth)
    try:
        r = requests.get(
            "https://www.youtube.com/audiolibrary_ajax",
            params={"action_load_tracks": "1", "filter": "2",
                    "mood": mood_id, "per_page": str(count), "page": "1"},
            headers=headers, timeout=12,
        )
        if r.status_code == 200:
            data   = r.json()
            tracks = data.get("tracks", [])
            ids    = [t.get("external_id") or t.get("id") for t in tracks
                      if t.get("external_id") or t.get("id")]
            if ids:
                print(f"    Audio Library API: {len(ids)} track IDs")
                return ids
    except Exception:
        pass

    # Attempt 2: Studio creator_music API
    try:
        r = requests.post(
            "https://studio.youtube.com/youtubei/v1/creator_music/list_tracks",
            headers={**headers, "Content-Type": "application/json",
                     "Origin": "https://studio.youtube.com"},
            json={
                "context": {"client": {"clientName": "WEB_CREATOR",
                                       "clientVersion": "1.20250501.01.00",
                                       "hl": "en", "gl": "US"}},
                "filter":   {"mood": mood_name},
                "sortOrder": "NEWEST",
                "pageSize": count,
            },
            timeout=12,
        )
        if r.status_code == 200:
            data   = r.json()
            tracks = data.get("tracks") or data.get("tracklist", {}).get("tracks", [])
            ids    = [extract_id(t) for t in tracks if extract_id(t)]
            if ids:
                print(f"    Studio API: {len(ids)} track IDs")
                return ids
    except Exception:
        pass

    return []


def extract_id(track):
    for key in ("externalVideoId", "videoId", "id"):
        if track.get(key):
            return track[key]
    for sub in ("entity", "video"):
        if isinstance(track.get(sub), dict):
            for key in ("externalVideoId", "videoId", "id"):
                if track[sub].get(key):
                    return track[sub][key]
    return None


# ── Main ──────────────────────────────────────────────────────────────────────

def _generate_piano_fallback(mood):
    """Generate piano WAV tracks locally — used in CI where yt-dlp is blocked."""
    try:
        from youtube_shorts import generate_piano_track
        # Map mood → closest format name for the piano generator
        mood_to_fmt = {
            "happy":         "fashion_steal",
            "inspirational": "styling_inspo",
            "rock":          "new_drop",
            "funky":         "trend_alert",
            "bright":        "ootd",
        }
        fmt = mood_to_fmt.get(mood, "ootd")
        for i in range(1, TRACKS_PER_MOOD + 1):
            out = f"music_{mood}_{i}.wav"
            if not os.path.exists(out):
                generate_piano_track(fmt, out_path=out)
                print(f"  [{i}/{TRACKS_PER_MOOD}] Generated piano track: {out}")
            else:
                print(f"  [{i}/{TRACKS_PER_MOOD}] Already exists: {out}")
        print(f"  Done: {TRACKS_PER_MOOD} piano tracks for {mood}.")
    except Exception as e:
        print(f"  Piano generation failed: {e}")


def download_mood(mood, token, refresh):
    print(f"\n--- {mood.upper()} tracks ---")
    have   = existing_tracks(mood)
    hashes = all_hashes(mood) if have else set()

    if not refresh and len(have) >= TRACKS_PER_MOOD:
        print(f"  Already have {len(have)} tracks — skipping.")
        return

    if refresh:
        for f in have: os.remove(f)
        have, hashes = [], set()

    # ── CI: yt-dlp blocked by YouTube bot detection — use piano generation ────
    if IN_CI:
        print(f"  CI detected — generating piano tracks (yt-dlp blocked in CI).")
        _generate_piano_fallback(mood)
        return

    slot = len(have)
    used = 0

    # ── Try YouTube Audio Library IDs first ───────────────────────────────────
    if token:
        ids = fetch_audio_library_ids(token, mood, count=TRACKS_PER_MOOD * 3)
        for vid_id in ids:
            if slot >= TRACKS_PER_MOOD: break
            out  = f"music_{mood}_{slot + 1}"
            path = yt_download(f"https://www.youtube.com/watch?v={vid_id}", out)
            if path:
                h = file_hash(path)
                if h in hashes:
                    os.remove(path); continue
                hashes.add(h); slot += 1; used += 1
                print(f"  [{slot}/{TRACKS_PER_MOOD}] {os.path.basename(path)}")
            time.sleep(0.3)

    # ── Fill remaining with unique search queries ─────────────────────────────
    queries   = QUERIES.get(mood, QUERIES["happy"])
    query_idx = used

    while slot < TRACKS_PER_MOOD and query_idx < len(queries):
        q = queries[query_idx]; query_idx += 1
        out  = f"music_{mood}_{slot + 1}"
        print(f"  [{slot + 1}/{TRACKS_PER_MOOD}] {q[-55:]}")
        path = yt_download(q, out)
        if not path: continue
        h = file_hash(path)
        if h in hashes:
            os.remove(path); continue
        hashes.add(h); slot += 1
        print(f"    Saved: {os.path.basename(path)}")
        time.sleep(0.3)

    print(f"  Done: {slot} unique {mood} tracks.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true",
                    help="Re-download all tracks, replacing existing ones")
    args = ap.parse_args()

    print("=== YouTube Audio Library Music Setup ===\n")
    token = None
    try:
        token = get_access_token()
        print("OAuth token obtained — will try Audio Library first.\n")
    except Exception as e:
        print(f"No token ({e}) — using search only.\n")

    for mood in ["happy", "inspirational", "rock", "funky", "bright"]:
        download_mood(mood, token, args.refresh)

    print("\n=== Tracks available ===")
    for mood in ["happy", "inspirational", "rock", "funky", "bright"]:
        tracks = existing_tracks(mood)
        print(f"  {mood:<14}: {len(tracks)} tracks")
        for f in sorted(tracks):
            kb = os.path.getsize(f) // 1024
            print(f"    {f}  ({kb} KB)")


if __name__ == "__main__":
    main()

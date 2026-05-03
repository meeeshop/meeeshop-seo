"""
One-time setup: downloads 6 Happy + 6 Inspirational tracks from the
YouTube Audio Library (royalty-free, YouTube-approved, safe to monetize).
Run this once — tracks are cached locally and reused by youtube_shorts.py.

Usage:
    python setup_music.py
"""
import os, glob, pickle, random, time
import requests

# ── Auth ──────────────────────────────────────────────────────────────────────

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

    with open("youtube_token.pickle", "rb") as f:
        creds = pickle.load(f)
    if not creds.valid and creds.refresh_token:
        from google.auth.transport.requests import Request as Req
        creds.refresh(Req())
    return creds.token


# ── YouTube Studio Audio Library API ─────────────────────────────────────────

# Internal mood IDs used by YouTube Studio creator_music API
YT_MOODS = {
    "happy":         "HAPPY",
    "inspirational": "INSPIRATIONAL",
}

def fetch_library_tracks(access_token, mood_key, count=12):
    """Try multiple endpoints to get YouTube Audio Library track IDs."""
    mood_val = YT_MOODS[mood_key]
    headers_base = {
        "Authorization": f"Bearer {access_token}",
        "User-Agent":    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }

    # ── Attempt 1: old audiolibrary_ajax endpoint ──────────────────────────
    mood_id_map = {"HAPPY": "5", "INSPIRATIONAL": "6"}
    mood_id = mood_id_map.get(mood_val, "5")
    try:
        r = requests.get(
            "https://www.youtube.com/audiolibrary_ajax",
            params={"action_load_tracks": "1", "filter": "2",
                    "mood": mood_id, "per_page": str(count), "page": "1"},
            headers={**headers_base, "Referer": "https://www.youtube.com/"},
            timeout=12,
        )
        if r.status_code == 200:
            data = r.json()
            tracks = data.get("tracks", [])
            if tracks:
                print(f"  Audio Library ajax: {len(tracks)} tracks")
                return tracks
    except Exception as e:
        print(f"  ajax attempt: {e}")

    # ── Attempt 2: Studio creator_music API ──────────────────────────────────
    try:
        r = requests.post(
            "https://studio.youtube.com/youtubei/v1/creator_music/list_tracks",
            headers={**headers_base,
                     "Content-Type": "application/json",
                     "Origin":       "https://studio.youtube.com",
                     "Referer":      "https://studio.youtube.com/"},
            json={
                "context": {
                    "client": {"clientName": "WEB_CREATOR",
                               "clientVersion": "1.20250501.01.00",
                               "hl": "en", "gl": "US"}
                },
                "filter":   {"mood": mood_val},
                "pageSize": count,
            },
            timeout=12,
        )
        if r.status_code == 200:
            data = r.json()
            tracks = (data.get("tracks")
                      or data.get("tracklist", {}).get("tracks", []))
            if tracks:
                print(f"  Studio API: {len(tracks)} tracks")
                return tracks
        print(f"  Studio API {r.status_code}")
    except Exception as e:
        print(f"  Studio API: {e}")

    return []


def extract_video_id(track):
    """Try several known fields to get the YouTube video ID from a track object."""
    for key in ("externalVideoId", "videoId", "id", "external_id"):
        if track.get(key):
            return track[key]
    # Sometimes nested under entity or video
    for sub in ("entity", "video", "musicTrack"):
        if isinstance(track.get(sub), dict):
            for key in ("externalVideoId", "videoId", "id"):
                if track[sub].get(key):
                    return track[sub][key]
    return None


# ── yt-dlp download (audio-only, no ffmpeg needed) ───────────────────────────

def yt_download(video_id_or_url, out_base):
    """Download best audio stream. Returns file path or None."""
    import glob as _glob
    try:
        import yt_dlp
        # Handle: full URL, ytsearch prefix, or bare video ID
        if video_id_or_url.startswith(("http", "ytsearch")):
            url = video_id_or_url
        else:
            url = f"https://www.youtube.com/watch?v={video_id_or_url}"
        opts = {
            "format":      "bestaudio[ext=webm]/bestaudio[ext=m4a]/bestaudio",
            "outtmpl":     out_base + ".%(ext)s",
            "quiet":       True,
            "no_warnings": True,
            "noplaylist":  True,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        matches = [f for f in _glob.glob(out_base + ".*")
                   if not f.endswith(".wav") and os.path.getsize(f) > 10000]
        return matches[0] if matches else None
    except Exception as e:
        print(f"  Download error: {e}")
        return None


# ── Fallback: yt-dlp search with strict audio-library query ──────────────────

FALLBACK_QUERIES = {
    "happy": [
        "ytsearch1:happy background music youtube audio library royalty free",
        "ytsearch1:upbeat happy music no copyright youtube audio library 2024",
        "ytsearch1:happy pop background music free to use youtube",
    ],
    "inspirational": [
        "ytsearch1:inspirational background music youtube audio library royalty free",
        "ytsearch1:uplifting motivational music no copyright youtube audio library",
        "ytsearch1:inspirational cinematic music free to use youtube 2024",
    ],
}


def download_fallback(mood_key, out_base):
    queries = FALLBACK_QUERIES.get(mood_key, FALLBACK_QUERIES["happy"])
    for q in queries:
        path = yt_download(q, out_base)
        if path:
            return path
    return None


# ── Main ──────────────────────────────────────────────────────────────────────

TRACKS_PER_MOOD = 6   # downloads 6 happy + 6 inspirational = 12 total


def already_have(mood_key, needed):
    """Check how many tracks we already have for this mood."""
    return len([f for f in glob.glob(f"music_{mood_key}_*.webm")
                + glob.glob(f"music_{mood_key}_*.m4a")
                if os.path.getsize(f) > 10000])


def main():
    print("=== YouTube Audio Library Music Setup ===\n")
    print("Fetching your OAuth token...")
    try:
        token = get_access_token()
        print("  Token obtained.\n")
    except Exception as e:
        print(f"  Token error: {e}\n  Will use fallback search only.\n")
        token = None

    for mood in ["happy", "inspirational"]:
        print(f"--- {mood.upper()} tracks ---")
        have = already_have(mood, TRACKS_PER_MOOD)
        if have >= TRACKS_PER_MOOD:
            print(f"  Already have {have} {mood} tracks — skipping.\n")
            continue

        needed    = TRACKS_PER_MOOD - have
        track_ids = []

        # Step 1: Try YouTube Studio API
        if token:
            print(f"  Fetching from YouTube Audio Library ({mood})...")
            raw_tracks = fetch_library_tracks(token, mood, count=needed * 3)
            track_ids  = [extract_video_id(t) for t in raw_tracks]
            track_ids  = [tid for tid in track_ids if tid][:needed * 2]
            if track_ids:
                print(f"  Got {len(track_ids)} track IDs from Audio Library")
            else:
                print("  Studio API returned no tracks — using search fallback")

        random.shuffle(track_ids)
        downloaded = have

        # Step 2: Download from track IDs
        for i, vid_id in enumerate(track_ids):
            if downloaded >= TRACKS_PER_MOOD:
                break
            out = f"music_{mood}_{downloaded + 1}"
            print(f"  Downloading track {downloaded + 1}/{TRACKS_PER_MOOD} (id:{vid_id})...")
            path = yt_download(vid_id, out)
            if path:
                print(f"  Saved: {os.path.basename(path)}")
                downloaded += 1
            time.sleep(0.5)

        # Step 3: Fallback search for remaining
        if downloaded < TRACKS_PER_MOOD:
            print(f"  Using search fallback for remaining {TRACKS_PER_MOOD - downloaded} tracks...")
            while downloaded < TRACKS_PER_MOOD:
                out  = f"music_{mood}_{downloaded + 1}"
                path = download_fallback(mood, out)
                if path:
                    print(f"  Saved: {os.path.basename(path)}")
                    downloaded += 1
                else:
                    print("  Search fallback also failed — will use generated piano")
                    break
                time.sleep(0.5)

        total = already_have(mood, TRACKS_PER_MOOD)
        print(f"  Done: {total} {mood} tracks available.\n")

    print("=== Setup complete ===")
    print("Tracks saved:")
    for f in sorted(glob.glob("music_happy_*.webm") + glob.glob("music_happy_*.m4a")
                    + glob.glob("music_inspirational_*.webm") + glob.glob("music_inspirational_*.m4a")):
        size_kb = os.path.getsize(f) // 1024
        print(f"  {f}  ({size_kb} KB)")
    print("\nRun youtube_shorts.py — it will automatically use these tracks.")


if __name__ == "__main__":
    main()

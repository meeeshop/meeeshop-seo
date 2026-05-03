"""
Finds all private/unscheduled MeeeShop YouTube videos and schedules them
at optimal USA time slots (EST). Run once to clear the backlog of drafts.
"""
import pickle, random
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from dotenv import load_dotenv
import os

load_dotenv()

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]

POSTING_SLOTS_EST = {
    0:[12,19,21], 1:[12,19,21], 2:[12,19,21],
    3:[12,19,21], 4:[12,19,21], 5:[11,14,20], 6:[11,14,20],
}

VIRAL_TITLE_SUFFIXES = [
    "#Shorts", "| MeeeShop #Shorts", "| Shop Now #Shorts",
    "| Women Fashion #Shorts", "| USA Fashion #Shorts",
]


def get_youtube():
    rt = os.getenv("YOUTUBE_REFRESH_TOKEN")
    if rt:
        creds = Credentials(token=None, refresh_token=rt,
                            token_uri="https://oauth2.googleapis.com/token",
                            client_id=os.getenv("YOUTUBE_CLIENT_ID"),
                            client_secret=os.getenv("YOUTUBE_CLIENT_SECRET"),
                            scopes=SCOPES)
        creds.refresh(Request())
        return build("youtube", "v3", credentials=creds)
    with open("youtube_token.pickle", "rb") as f:
        creds = pickle.load(f)
    if not creds.valid and creds.refresh_token:
        creds.refresh(Request())
    return build("youtube", "v3", credentials=creds)


def get_all_private_videos(yt, channel_id):
    """Fetch all private/unscheduled drafts via the channel uploads playlist."""
    # Uploads playlist = channel_id with UC→UU
    playlist_id = "UU" + channel_id[2:]
    drafts, page_token = [], None

    while True:
        kwargs = dict(part="contentDetails", playlistId=playlist_id, maxResults=50)
        if page_token:
            kwargs["pageToken"] = page_token
        r = yt.playlistItems().list(**kwargs).execute()

        ids = [i["contentDetails"]["videoId"] for i in r.get("items", [])]
        if ids:
            vr = yt.videos().list(
                part="id,snippet,status,recordingDetails",
                id=",".join(ids)
            ).execute()
            for v in vr.get("items", []):
                s = v.get("status", {})
                if s.get("privacyStatus") == "private" and not s.get("publishAt"):
                    drafts.append(v)

        page_token = r.get("nextPageToken")
        if not page_token:
            break
    return drafts


def next_slots(n, used_slots=None):
    """Generate n optimal publishing slots in EST, avoiding already-used ones."""
    used_slots = used_slots or set()
    est  = ZoneInfo("America/New_York")
    now  = datetime.now(est)
    slots, d = [], 0
    while len(slots) < n and d < 60:
        day = now + timedelta(days=d)
        for h in POSTING_SLOTS_EST[day.weekday()]:
            slot = day.replace(hour=h, minute=0, second=0, microsecond=0)
            slot_key = slot.strftime("%Y-%m-%d-%H")
            if slot > now + timedelta(minutes=30) and slot_key not in used_slots:
                utc = slot.astimezone(timezone.utc)
                slots.append((utc.strftime("%Y-%m-%dT%H:%M:%S.000Z"), slot))
                used_slots.add(slot_key)
                if len(slots) == n:
                    return slots
        d += 1
    return slots


def improve_title(title):
    """Ensure title ends with a viral suffix if not already."""
    if "#Shorts" in title or "#shorts" in title:
        return title
    suffix = random.choice(VIRAL_TITLE_SUFFIXES)
    candidate = f"{title} {suffix}"
    return candidate[:100]


def schedule_video(yt, video_id, snippet, slot_utc, slot_local):
    """Update a private video to scheduled with improved metadata and USA location."""
    new_title = improve_title(snippet.get("title", ""))
    desc = snippet.get("description", "")

    # Add shop link if missing
    if "us.meeeshop.com" not in desc and "meeeshop.com" not in desc:
        desc = f"Shop now: https://us.meeeshop.com\n\n{desc}"

    # Add USA tags if missing
    tags = snippet.get("tags", [])
    for t in ["USA", "women fashion", "MeeeShop", "fashion", "ootd", "Shorts"]:
        if t not in tags:
            tags.append(t)

    body = {
        "id": video_id,
        "snippet": {
            "title":                new_title,
            "description":          desc,
            "tags":                 tags[:500],
            "categoryId":           snippet.get("categoryId", "26"),
            "defaultLanguage":      "en",
            "defaultAudioLanguage": "en-US",
        },
        "status": {
            "privacyStatus":          "private",
            "selfDeclaredMadeForKids": False,
            "publishAt":              slot_utc,
        },
        "recordingDetails": {
            "locationDescription": "United States",
            "location": {"latitude": 37.0902, "longitude": -95.7129, "altitude": 0},
        },
    }
    yt.videos().update(
        part="snippet,status,recordingDetails", body=body
    ).execute()

    pst = (slot_local - timedelta(hours=3)).strftime("%I:%M %p PST")
    print(f"  Scheduled: {slot_local.strftime('%a %b %d %I:%M %p EST')} | {pst}")
    print(f"  -> https://www.youtube.com/shorts/{video_id}")


def main():
    print("=== MeeeShop Draft Scheduler ===\n")
    yt = get_youtube()

    # Get channel ID
    ch = yt.channels().list(part="id,snippet", mine=True).execute()
    ch_id   = ch["items"][0]["id"]
    ch_name = ch["items"][0]["snippet"]["title"]
    print(f"Channel: {ch_name}\n")

    print("Fetching unscheduled private videos...")
    drafts = get_all_private_videos(yt, ch_id)
    print(f"Found {len(drafts)} unscheduled drafts\n")

    if not drafts:
        print("Nothing to schedule.")
        return

    # Generate enough slots for all drafts (spread over next 60 days)
    slots = next_slots(len(drafts))

    if len(slots) < len(drafts):
        print(f"Warning: only {len(slots)} slots available for {len(drafts)} drafts")
        drafts = drafts[:len(slots)]

    for i, (video, (slot_utc, slot_local)) in enumerate(zip(drafts, slots), 1):
        vid_id  = video["id"]
        snippet = video["snippet"]
        print(f"[{i}/{len(drafts)}] {snippet.get('title','')[:55]}")
        try:
            schedule_video(yt, vid_id, snippet, slot_utc, slot_local)
        except Exception as e:
            print(f"  ! Error: {e}")

    print(f"\n=== Done! Scheduled {len(drafts)} videos ===")
    print("They will auto-publish at the times shown above.")


if __name__ == "__main__":
    main()

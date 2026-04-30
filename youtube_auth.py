"""
YouTube OAuth - starts a local server on port 8080 to capture the redirect automatically.
Run this, open the printed URL in Chrome, login, and the script finishes on its own.
"""
import os
import pickle
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]
os.chdir(os.path.dirname(os.path.abspath(__file__)))

flow = InstalledAppFlow.from_client_secrets_file("client_secret.json", SCOPES)

print("\n" + "=" * 70)
print("Starting local server on http://localhost:8080 ...")
print("=" * 70)
print("A URL will appear below. Open it in Chrome and login.")
print("After you click Allow, Chrome will redirect back automatically.")
print("DO NOT close this window until you see 'Success!'")
print("=" * 70 + "\n")

creds = flow.run_local_server(port=8080, open_browser=False)

with open("youtube_token.pickle", "wb") as f:
    pickle.dump(creds, f)

youtube = build("youtube", "v3", credentials=creds)
me = youtube.channels().list(part="snippet", mine=True).execute()
channel = me["items"][0]["snippet"]["title"] if me.get("items") else "Unknown"

print(f"\nSuccess! Connected to YouTube channel: {channel}")
print("Token saved. You can now run: python youtube_shorts.py")

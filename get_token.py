"""
Shopify OAuth Token Generator
Run this script to get your Admin API access token.
"""

import http.server
import urllib.parse
import webbrowser
import requests
import os

# ─── FILL THESE IN ───────────────────────────────────────────────────────────
CLIENT_ID     = "2393044b0d5c77ffb2fe2f9ca9dd9781"       # from Dev Dashboard → MycustomIntegration → Settings
CLIENT_SECRET = "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"   # same place, click eye icon to reveal
SHOP          = "us-meeeshop.myshopify.com"
REDIRECT_URI  = "http://localhost:3000/callback"
# ─────────────────────────────────────────────────────────────────────────────

SCOPES = ",".join([
    "read_products", "write_products",
    "read_collections", "write_collections",
    "read_inventory", "write_inventory",
    "read_orders",
    "read_customers",
    "read_analytics",
    "read_themes", "write_themes",
    "read_content", "write_content",
    "read_script_tags", "write_script_tags",
    "read_metafields", "write_metafields",
    "read_metaobjects", "write_metaobjects",
    "read_marketing_events", "write_marketing_events",
    "read_price_rules", "write_price_rules",
    "read_discounts", "write_discounts",
    "read_product_listings",
])

STATE = "shopify_oauth_state_12345"
access_token_result = {}


class CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if "code" not in params:
            self._respond("Error: No code received.")
            return

        code  = params["code"][0]
        state = params.get("state", [""])[0]

        if state != STATE:
            self._respond("Error: State mismatch. Possible CSRF attack.")
            return

        # Exchange code for access token
        response = requests.post(
            f"https://{SHOP}/admin/oauth/access_token",
            json={
                "client_id":     CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "code":          code,
            },
        )

        if response.status_code == 200:
            token_data = response.json()
            access_token = token_data.get("access_token", "")
            access_token_result["token"] = access_token

            # Save to .env file
            env_path = os.path.join(os.path.dirname(__file__), ".env")
            with open(env_path, "w") as f:
                f.write(f'SHOPIFY_STORE="{SHOP}"\n')
                f.write(f'SHOPIFY_ACCESS_TOKEN="{access_token}"\n')
                f.write(f'SHOPIFY_CLIENT_ID="{CLIENT_ID}"\n')
                f.write(f'SHOPIFY_CLIENT_SECRET="{CLIENT_SECRET}"\n')

            self._respond(
                f"<h2>SUCCESS!</h2>"
                f"<p>Access token saved to <strong>.env</strong> file in your project folder.</p>"
                f"<p><strong>Token:</strong> {access_token}</p>"
                f"<p>Copy this token and keep it safe. You can close this window.</p>"
            )
            print("\n" + "="*60)
            print("SUCCESS! Access Token Retrieved:")
            print(f"  {access_token}")
            print("="*60)
            print("Token saved to .env file")
            print("You can close this terminal after copying your token.")
        else:
            self._respond(f"Error exchanging code: {response.text}")
            print(f"Error: {response.text}")

    def _respond(self, html):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(f"<html><body>{html}</body></html>".encode())

    def log_message(self, *args):
        pass


def main():
    if CLIENT_ID == "YOUR_CLIENT_ID":
        print("ERROR: Please open get_token.py and fill in your CLIENT_ID and CLIENT_SECRET first.")
        return

    auth_url = (
        f"https://{SHOP}/admin/oauth/authorize"
        f"?client_id={CLIENT_ID}"
        f"&scope={urllib.parse.quote(SCOPES)}"
        f"&redirect_uri={urllib.parse.quote(REDIRECT_URI)}"
        f"&state={STATE}"
    )

    print("="*60)
    print("Shopify OAuth Token Generator")
    print("="*60)
    print(f"\nOpening browser to authorize your app...")
    print(f"If browser doesn't open, visit this URL manually:\n\n{auth_url}\n")
    print("Waiting for authorization...")

    # Try Chrome first, fall back to default browser
    chrome_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    opened = False
    for chrome in chrome_paths:
        if os.path.exists(chrome):
            import subprocess
            subprocess.Popen([chrome, auth_url])
            opened = True
            break
    if not opened:
        webbrowser.open(auth_url)

    server = http.server.HTTPServer(("localhost", 3000), CallbackHandler)
    server.handle_request()


if __name__ == "__main__":
    main()

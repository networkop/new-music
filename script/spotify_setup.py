#!/usr/bin/env python3
"""One-time interactive setup: exchange a Spotify authorization for a refresh
token. Run this locally, once, on a machine with a browser - it needs your
own Spotify login, so it can't run in CI.

Prerequisite: a Spotify app at https://developer.spotify.com/dashboard with
redirect URI http://127.0.0.1:8080/callback added under app settings (exact
match required, including the port).

Usage:
    SPOTIFY_CLIENT_ID=... SPOTIFY_CLIENT_SECRET=... python3 script/spotify_setup.py

Writes the resulting refresh token to REFRESH_TOKEN_PATH (gitignored).
Put its contents into the SPOTIFY_REFRESH_TOKEN GitHub secret afterward.
"""

import base64
import http.server
import json
import os
import secrets
import sys
import urllib.parse
import urllib.request
import webbrowser

REDIRECT_URI = "http://127.0.0.1:8080/callback"
SCOPES = "playlist-modify-public playlist-modify-private playlist-read-private"
AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
REFRESH_TOKEN_PATH = "data/.spotify_refresh_token"


class CallbackHandler(http.server.BaseHTTPRequestHandler):
    result = {}

    def do_GET(self):
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        CallbackHandler.result = {k: v[0] for k, v in params.items()}
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(b"<html><body>Done - you can close this tab.</body></html>")

    def log_message(self, fmt, *args):
        pass  # quiet - the auth code would otherwise land in this log line


def get_client_credentials():
    client_id = os.environ.get("SPOTIFY_CLIENT_ID") or input("Spotify client ID: ")
    client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET") or input("Spotify client secret: ")
    return client_id, client_secret


def authorize(client_id, state):
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "state": state,
    }
    url = f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"
    print(f"Opening {url}\nIf it didn't open, paste that URL into a browser yourself.")
    webbrowser.open(url)

    server = http.server.HTTPServer(("127.0.0.1", 8080), CallbackHandler)
    server.handle_request()  # blocks until the one redirect comes in
    return CallbackHandler.result


def exchange_code(client_id, client_secret, code):
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    body = urllib.parse.urlencode(
        {"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT_URI}
    ).encode()
    req = urllib.request.Request(
        TOKEN_URL,
        data=body,
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


def main():
    client_id, client_secret = get_client_credentials()
    state = secrets.token_urlsafe(16)

    result = authorize(client_id, state)

    if "error" in result:
        print(f"Spotify returned an error: {result['error']}", file=sys.stderr)
        sys.exit(1)
    if result.get("state") != state:
        print("state mismatch - possible CSRF, aborting", file=sys.stderr)
        sys.exit(1)

    tokens = exchange_code(client_id, client_secret, result["code"])
    if "refresh_token" not in tokens:
        print(f"no refresh_token in response: {tokens}", file=sys.stderr)
        sys.exit(1)

    with open(REFRESH_TOKEN_PATH, "w") as fh:
        fh.write(tokens["refresh_token"])
    print(f"wrote {REFRESH_TOKEN_PATH}")
    print("put its contents into the SPOTIFY_REFRESH_TOKEN GitHub secret")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Sync kept tracks to a rolling Spotify playlist (stage 3).

Not built yet - this is the auth smoke test. See docs/playlist-sync.md and
script/spotify_setup.py (run that first, once, locally - it needs a browser
login and can't run in CI).

Credentials, three pieces:

- SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET: from the app at
  https://developer.spotify.com/dashboard.
- SPOTIFY_REFRESH_TOKEN: written by spotify_setup.py to
  data/.spotify_refresh_token (gitignored) - put its contents in this secret.

Unlike Google's OAuth, Spotify refresh tokens are long-lived and don't have
a "Testing" publishing status with a ~1-week expiry to worry about.
"""

import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

TOKEN_URL = "https://accounts.spotify.com/api/token"
API_BASE = "https://api.spotify.com/v1"


def get_access_token():
    client_id = os.environ["SPOTIFY_CLIENT_ID"]
    client_secret = os.environ["SPOTIFY_CLIENT_SECRET"]
    refresh_token = os.environ["SPOTIFY_REFRESH_TOKEN"]

    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    body = urllib.parse.urlencode(
        {"grant_type": "refresh_token", "refresh_token": refresh_token}
    ).encode()
    req = urllib.request.Request(
        TOKEN_URL,
        data=body,
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.load(resp)["access_token"]
    except urllib.error.HTTPError as exc:
        print(f"token refresh failed: {exc.code} {exc.read().decode()}", file=sys.stderr)
        raise


def api_get(path, token):
    req = urllib.request.Request(
        f"{API_BASE}{path}", headers={"Authorization": f"Bearer {token}"}
    )
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


def main():
    token = get_access_token()
    me = api_get("/me", token)
    print(f"authenticated as {me.get('display_name')} ({me.get('id')})")

    playlists = api_get("/me/playlists?limit=50", token)
    print(f"{playlists['total']} playlist(s) in this account:")
    for p in playlists["items"]:
        print(f"  {p['id']}  {p['name']}")


if __name__ == "__main__":
    main()

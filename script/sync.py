#!/usr/bin/env python3
"""Sync kept/review tracks to two rolling Spotify playlists (stage 3).

Two playlists, created on first run and remembered in PLAYLISTS_PATH:
- "keep": the real rolling playlist.
- "review": ambiguous genre calls the owner skims occasionally, per
  docs/filtering.md ("route ambiguity to a review list, don't guess").

Each run recomputes desired membership from scratch from
data/tracks_filtered.jsonl (decision + a WINDOW_DAYS cutoff) and reconciles
against the playlist's actual current contents fetched from Spotify - not
against a local "what we added last time" record. That means aging out,
an owner correcting an override, and a manual removal by the owner in the
Spotify app all get picked up automatically with no separate state file to
go stale. See docs/playlist-sync.md.

Credentials: SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET / SPOTIFY_REFRESH_TOKEN
(see script/spotify_setup.py for how to obtain the refresh token).
"""

import base64
import difflib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

TOKEN_URL = "https://accounts.spotify.com/api/token"
API_BASE = "https://api.spotify.com/v1"

FILTERED_PATH = "data/tracks_filtered.jsonl"
PLAYLISTS_PATH = "data/spotify_playlists.json"
MATCH_CACHE_PATH = "data/track_matches.json"

WINDOW_DAYS = int(os.environ.get("WINDOW_DAYS", "30"))
MATCH_THRESHOLD = 0.6

PLAYLIST_NAMES = {
    "keep": "New Music Show",
    "review": "New Music Show - Review",
}


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
            payload = json.load(resp)
    except urllib.error.HTTPError as exc:
        print(f"token refresh failed: {exc.code} {exc.read().decode()}", file=sys.stderr)
        raise
    print(f"token scope: {payload.get('scope')}", file=sys.stderr)
    return payload["access_token"]


def api_request(method, path_or_url, token, params=None, json_body=None, attempts=4):
    url = path_or_url if path_or_url.startswith("http") else f"{API_BASE}{path_or_url}"
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    data = json.dumps(json_body).encode() if json_body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    for i in range(attempts):
        try:
            with urllib.request.urlopen(req) as resp:
                body = resp.read()
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and i < attempts - 1:
                time.sleep(int(exc.headers.get("Retry-After", 2**i)))
                continue
            if exc.code in (500, 502, 503) and i < attempts - 1:
                time.sleep(2**i)
                continue
            print(f"{method} {url} -> {exc.code} {exc.read().decode()}", file=sys.stderr)
            raise
    raise RuntimeError(f"exhausted retries: {method} {url}")


def ensure_playlists(token):
    # POST /me/playlists, not /users/{user_id}/playlists - the latter was
    # removed for Development Mode apps in Spotify's Feb 2026 Web API
    # migration (https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide).
    config = load_json(PLAYLISTS_PATH, {})
    changed = False
    for bucket, name in PLAYLIST_NAMES.items():
        if bucket not in config:
            created = api_request(
                "POST",
                "/me/playlists",
                token,
                json_body={"name": name, "public": False, "description": "Managed by new-music, do not edit by hand except to remove tracks."},
            )
            config[bucket] = created["id"]
            changed = True
            print(f"created playlist {bucket!r}: {name} ({created['id']})")
    if changed:
        save_json(PLAYLISTS_PATH, config)
    return config


def get_playlist_uris(playlist_id, token):
    # /playlists/{id}/items, not /tracks - same Feb 2026 migration also
    # renamed items[].track -> items[].item and dropped the max page size
    # from 100 to 50.
    uris = set()
    url = f"/playlists/{playlist_id}/items"
    params = {"fields": "items(item(uri)),next", "limit": 50}
    while url:
        resp = api_request("GET", url, token, params=params)
        params = None  # 'next' already carries its own query string
        for entry in resp.get("items", []):
            item = entry.get("item")
            if item and item.get("uri"):
                uris.add(item["uri"])
        url = resp.get("next")
    return uris


def normalize(s):
    s = s.lower()
    s = re.sub(r"\(.*?\)|\[.*?\]", "", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return s.strip()


def best_match(artist, title, candidates):
    query = normalize(f"{artist} {title}")
    best, best_score = None, 0.0
    for c in candidates:
        c_artist = c["artists"][0]["name"] if c.get("artists") else ""
        cand = normalize(f"{c_artist} {c['name']}")
        score = difflib.SequenceMatcher(None, query, cand).ratio()
        if score > best_score:
            best, best_score = c, score
    return best, best_score


def resolve_track(artist, title, token, cache):
    key = f"{artist.strip().lower()}|||{title.strip().lower()}"
    if key in cache:
        return cache[key]["uri"]

    q = f'track:"{title}" artist:"{artist}"'
    resp = api_request("GET", "/search", token, params={"q": q, "type": "track", "limit": 5})
    candidates = resp.get("tracks", {}).get("items", [])
    match, score = best_match(artist, title, candidates)

    if match and score >= MATCH_THRESHOLD:
        cache[key] = {
            "uri": match["uri"],
            "score": round(score, 3),
            "matched": f"{match['artists'][0]['name']} - {match['name']}",
        }
    else:
        cache[key] = {"uri": None, "score": round(score, 3) if match else 0.0, "matched": None}

    time.sleep(0.1)  # be polite, same spirit as fetch.py
    return cache[key]["uri"]


def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path) as fh:
        return json.load(fh)


def save_json(path, data):
    with open(path, "w") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False, sort_keys=True)


def reconcile(playlist_id, desired_uris, token, label):
    actual = get_playlist_uris(playlist_id, token)
    to_add = list(desired_uris - actual)
    to_remove = list(actual - desired_uris)

    for i in range(0, len(to_add), 100):
        batch = to_add[i : i + 100]
        api_request("POST", f"/playlists/{playlist_id}/items", token, json_body={"uris": batch})
    for i in range(0, len(to_remove), 100):
        batch = to_remove[i : i + 100]
        api_request(
            "DELETE",
            f"/playlists/{playlist_id}/items",
            token,
            json_body={"items": [{"uri": u} for u in batch]},
        )

    print(f"{label}: {len(desired_uris)} desired, +{len(to_add)} -{len(to_remove)}")


def main():
    if not os.path.exists(FILTERED_PATH):
        print(f"{FILTERED_PATH} not found - run filter.py first", file=sys.stderr)
        sys.exit(1)

    token = get_access_token()
    me = api_request("GET", "/me", token)
    print(f"authenticated as {me.get('display_name')} ({me.get('id')})")

    playlists = ensure_playlists(token)
    cache = load_json(MATCH_CACHE_PATH, {})

    cutoff = (datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)).strftime("%Y-%m-%d")
    with open(FILTERED_PATH) as fh:
        tracks = [json.loads(line) for line in fh if line.strip()]

    unmatched = []
    for bucket in ("keep", "review"):
        desired = set()
        for t in tracks:
            if t["decision"] != bucket or t["broadcast"] < cutoff:
                continue
            uri = resolve_track(t["artist"], t["title"], token, cache)
            if uri:
                desired.add(uri)
            else:
                unmatched.append((bucket, t["artist"], t["title"]))
        reconcile(playlists[bucket], desired, token, bucket)

    save_json(MATCH_CACHE_PATH, cache)

    if unmatched:
        print(f"{len(unmatched)} track(s) with no confident Spotify match:", file=sys.stderr)
        for bucket, artist, title in unmatched:
            print(f"  [{bucket}] {artist} - {title}", file=sys.stderr)


if __name__ == "__main__":
    main()

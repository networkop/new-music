#!/usr/bin/env python3
"""Fetch Radio 1 New Music Show tracklists from the BBC /programmes JSON feeds.

Walks the brand's monthly broadcast index, resolves episode PIDs, and pulls
per-episode segment data. Episodes already on disk are skipped, so re-runs cost
almost nothing and the job is safe to run more often than the show airs.

Stdlib only - no pip install step in CI.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

BRAND_PID = os.environ.get("BRAND_PID", "m001chdz")
WINDOW_DAYS = int(os.environ.get("WINDOW_DAYS", "35"))
BASE = "https://www.bbc.co.uk/programmes"
EPISODE_DIR = "data/episodes"
TRACKS_PATH = "data/tracks.jsonl"

# The BBC asks for a descriptive agent; be identifiable rather than anonymous.
UA = "new-music-tracklist-bot/1.0 (personal playlist project)"


def get_json(url, attempts=3):
    """GET with a small retry budget. Returns None on 404 rather than raising."""
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept": "application/json"}
    )
    for i in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            if exc.code in (429, 500, 502, 503) and i < attempts - 1:
                time.sleep(2 ** i)
                continue
            raise
        except urllib.error.URLError:
            if i < attempts - 1:
                time.sleep(2 ** i)
                continue
            raise
    return None


def months_in_window(now, days):
    """Year/month pairs the window touches, newest first.

    A 35-day window can straddle three months at the turn of a long month, so
    step backwards by day rather than assuming two.
    """
    seen = []
    cursor = now
    earliest = now - timedelta(days=days)
    while cursor >= earliest:
        key = (cursor.year, cursor.month)
        if key not in seen:
            seen.append(key)
        cursor -= timedelta(days=1)
    return seen


def collect_broadcasts(now):
    """Past, non-blanked broadcasts inside the window, oldest first."""
    cutoff = now - timedelta(days=WINDOW_DAYS)
    found = {}
    for year, month in months_in_window(now, WINDOW_DAYS):
        url = f"{BASE}/{BRAND_PID}/episodes/{year}/{month}.json"
        payload = get_json(url)
        if not payload:
            print(f"  no data for {year}-{month:02d}", file=sys.stderr)
            continue
        for bc in payload.get("broadcasts", []):
            if bc.get("is_blanked"):
                continue
            start = datetime.fromisoformat(bc["start"])
            # The monthly file includes future scheduled transmissions.
            if start > now or start < cutoff:
                continue
            prog = bc.get("programme") or {}
            pid = prog.get("pid")
            if not pid:
                continue
            found[pid] = {
                "pid": pid,
                "broadcast_start": bc["start"],
                "schedule_date": bc.get("schedule_date"),
                "title": (prog.get("display_titles") or {}).get("subtitle"),
            }
    return sorted(found.values(), key=lambda e: e["broadcast_start"])


def fetch_segments(pid):
    """Track segments for one episode. Segments hang off the version, so follow
    redirects - urllib does this by default for 30x."""
    payload = get_json(f"{BASE}/{pid}/segments.json")
    if not payload:
        return None
    return payload.get("segment_events", [])


def extract(event):
    """Pull the fields we care about, keeping the raw segment for later use.

    Track-level identifiers (if the BBC exposes them) are what make an exact
    lookup possible downstream instead of fuzzy title matching, so keep
    anything that looks like one.
    """
    seg = event.get("segment") or {}
    return {
        "artist": seg.get("artist"),
        "title": seg.get("title"),
        "isrc": seg.get("isrc"),
        "musicbrainz_id": seg.get("musicbrainz_id") or seg.get("gid"),
        "raw": seg,
    }


def main():
    now = datetime.now(timezone.utc).astimezone()
    os.makedirs(EPISODE_DIR, exist_ok=True)

    episodes = collect_broadcasts(now)
    print(f"{len(episodes)} broadcast(s) in the last {WINDOW_DAYS} days")

    fetched = 0
    for ep in episodes:
        path = os.path.join(EPISODE_DIR, f"{ep['pid']}.json")
        if os.path.exists(path):
            continue
        events = fetch_segments(ep["pid"])
        if events is None:
            # Tracklists can lag the broadcast by a few hours. Leave it
            # unwritten and the next run will pick it up.
            print(f"  {ep['pid']}: no segments yet", file=sys.stderr)
            continue
        record = dict(ep)
        record["tracks"] = [extract(e) for e in events]
        with open(path, "w") as fh:
            json.dump(record, fh, indent=2, ensure_ascii=False)
        print(f"  {ep['pid']} {ep['schedule_date']}: {len(record['tracks'])} tracks")
        fetched += 1
        time.sleep(1)  # be polite; this is an unofficial feed

    rebuild_flat()
    print(f"done: {fetched} new episode(s)")


def rebuild_flat():
    """Flatten every stored episode into one JSONL, newest last."""
    rows = []
    for name in sorted(os.listdir(EPISODE_DIR)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(EPISODE_DIR, name)) as fh:
            ep = json.load(fh)
        for pos, track in enumerate(ep.get("tracks", [])):
            rows.append(
                {
                    "broadcast": ep["schedule_date"],
                    "episode_pid": ep["pid"],
                    "position": pos,
                    "artist": track["artist"],
                    "title": track["title"],
                    "isrc": track.get("isrc"),
                }
            )
    rows.sort(key=lambda r: (r["broadcast"] or "", r["position"]))
    with open(TRACKS_PATH, "w") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"{TRACKS_PATH}: {len(rows)} rows")


if __name__ == "__main__":
    main()

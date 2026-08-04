#!/usr/bin/env python3
"""Drop tracks by genre: exclude soul, country, indie folk; keep everything else,
including artists with no genre data at all (see docs/filtering.md).

Looks up Last.fm top tags per artist, keyed by MusicBrainz artist ID where
fetch.py found one (99%+ of tracks) and falling back to artist name otherwise.
Results are cached at the artist level in ARTIST_CACHE_PATH so repeat runs and
recurring artists cost no API calls. OVERRIDES_PATH is hand-maintained and
always wins over cache or API - see docs/filtering.md's note that a
hand-corrected list beats any tag source for this material.

Stdlib only, matching fetch.py.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

TRACKS_PATH = "data/tracks.jsonl"
FILTERED_PATH = "data/tracks_filtered.jsonl"
ARTIST_CACHE_PATH = "data/artist_genres.json"
OVERRIDES_PATH = "data/artist_overrides.json"

LASTFM_API_KEY = os.environ.get("LASTFM_API_KEY")
LASTFM_URL = "https://ws.audioscrobbler.com/2.0/"

# Only the three excluded categories plus their documented synonym bleed.
# Deliberately narrow: R&B and funk are noted in docs/filtering.md as
# adjacent to soul but are NOT excluded, so they're not in this vocabulary.
CATEGORIES = {
    "soul": {"soul", "neo-soul", "neo soul", "northern soul", "uk soul"},
    "country": {"country", "americana", "alt-country", "alt country"},
    "indie folk": {
        "indie folk",
        "folk",
        "singer-songwriter",
        "singer songwriter",
        "freak folk",
    },
}

# Exclude on weight alone, not rank - Last.fm's per-artist weight scale means
# a rank-3 tag can trail the top tag by a huge margin (e.g. 39 vs 100), so
# being 3rd doesn't imply "dominant genre". A below-threshold match still
# routes to review rather than being silently dropped either way.
WEIGHT_THRESHOLD = 50

UA = "new-music-tracklist-bot/1.0 (personal playlist project)"


def get_json(url, attempts=3):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for i in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503) and i < attempts - 1:
                time.sleep(2**i)
                continue
            raise
        except urllib.error.URLError:
            if i < attempts - 1:
                time.sleep(2**i)
                continue
            raise
    return None


def lastfm_top_tags(artist_mbid, artist_name):
    """[(tag, weight), ...] ordered by weight descending, or [] if Last.fm has
    nothing. Prefers mbid (exact) over name (fuzzy) when both are available."""
    params = {
        "method": "artist.gettoptags",
        "api_key": LASTFM_API_KEY,
        "autocorrect": "1",
        "format": "json",
    }
    if artist_mbid:
        params["mbid"] = artist_mbid
    else:
        params["artist"] = artist_name
    url = f"{LASTFM_URL}?{urllib.parse.urlencode(params)}"
    payload = get_json(url)
    if not payload:
        return []
    tags = (payload.get("toptags") or {}).get("tag") or []
    out = []
    for t in tags:
        try:
            out.append((t["name"].lower(), int(t["count"])))
        except (KeyError, ValueError, TypeError):
            continue
    return out


def classify(tags):
    """(decision, category, matched_tag) from a weighted tag list.

    decision is one of: exclude, review, keep.
    - exclude: a blocked-category tag at or above the weight threshold.
    - review: a blocked-category tag present, but only weakly (below
      threshold) - ambiguous, don't guess.
    - keep: no blocked-category tag, or no tag data at all (unknown genre
      defaults to keep - that's the whole point of an exclusion list).
    """
    weak_hit = None
    for tag, weight in tags:
        for category, synonyms in CATEGORIES.items():
            if tag in synonyms:
                if weight >= WEIGHT_THRESHOLD:
                    return "exclude", category, tag
                if weak_hit is None:
                    weak_hit = (category, tag)
    if weak_hit:
        return "review", weak_hit[0], weak_hit[1]
    return "keep", None, None


def artist_key(artist_mbid, artist_name):
    return artist_mbid or f"name:{artist_name.strip().lower()}"


def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path) as fh:
        return json.load(fh)


def save_json(path, data):
    with open(path, "w") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False, sort_keys=True)


def resolve_artist(key, artist_mbid, artist_name, cache, overrides, misses):
    """decision, category, matched_tag for one artist, consulting overrides,
    then cache, then Last.fm (fetching tags on a cache miss).

    The cache stores tags, not decisions - classify() runs fresh every time
    so a rule change (new synonym, new threshold) takes effect on the next
    run without spending an API call to re-derive data Last.fm already gave
    us. Overrides are decisions, not tags, since they exist specifically to
    override whatever classify() would say.
    """
    if key in overrides:
        return overrides[key]["decision"], overrides[key].get("category"), overrides[key].get("matched_tag")

    if key in cache:
        tags = cache[key]["tags"]
    elif LASTFM_API_KEY:
        tags = lastfm_top_tags(artist_mbid, artist_name)
        cache[key] = {"name": artist_name, "tags": tags[:10], "source": "lastfm"}
        time.sleep(0.25)  # be polite to Last.fm, same spirit as fetch.py
    else:
        misses.append((artist_name, artist_mbid))
        tags = []

    return classify(tags)


def main():
    if not os.path.exists(TRACKS_PATH):
        print(f"{TRACKS_PATH} not found - run fetch.py first", file=sys.stderr)
        sys.exit(1)

    cache = load_json(ARTIST_CACHE_PATH, {})
    for entry in cache.values():
        entry.pop("decision", None)
        entry.pop("category", None)
        entry.pop("matched_tag", None)
    overrides = load_json(OVERRIDES_PATH, {})

    with open(TRACKS_PATH) as fh:
        tracks = [json.loads(line) for line in fh if line.strip()]

    if not LASTFM_API_KEY:
        print(
            "LASTFM_API_KEY not set - artists not already cached or overridden "
            "will default to keep",
            file=sys.stderr,
        )

    misses = []
    counts = {"keep": 0, "exclude": 0, "review": 0}
    out_rows = []
    for track in tracks:
        key = artist_key(track.get("artist_mbid"), track["artist"])
        decision, category, matched_tag = resolve_artist(
            key, track.get("artist_mbid"), track["artist"], cache, overrides, misses
        )
        counts[decision] += 1
        out_rows.append(
            {
                **track,
                "decision": decision,
                "category": category,
                "matched_tag": matched_tag,
            }
        )

    save_json(ARTIST_CACHE_PATH, cache)
    with open(FILTERED_PATH, "w") as fh:
        for row in out_rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"{FILTERED_PATH}: {len(out_rows)} rows")
    print(f"  keep={counts['keep']} exclude={counts['exclude']} review={counts['review']}")
    if misses:
        print(f"  {len(misses)} artist(s) skipped, no API key and not cached", file=sys.stderr)


if __name__ == "__main__":
    main()

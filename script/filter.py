#!/usr/bin/env python3
"""Drop tracks by genre: exclude soul, country, indie folk, rnb; keep everything
else, including artists with no genre data at all (see docs/filtering.md).

Looks up Last.fm top tags per artist, keyed by MusicBrainz artist ID where
fetch.py found one (99%+ of tracks) and falling back to artist name otherwise.
Results are cached at the artist level in ARTIST_CACHE_PATH so repeat runs and
recurring artists cost no API calls. OVERRIDES_PATH is hand-maintained and
always wins over cache or API - see docs/filtering.md's note that a
hand-corrected list beats any tag source for this material.

TRACK_OVERRIDES_PATH is song-level and checked first, ahead of the
artist-level override - it's written automatically by sync.py when the
owner removes a track from the Spotify playlist (see its docstring), and a
specific song correction should outrank a blanket artist one.

Stdlib only, matching fetch.py.
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

TRACKS_PATH = "data/tracks.jsonl"
FILTERED_PATH = "data/tracks_filtered.jsonl"
ARTIST_CACHE_PATH = "data/artist_genres.json"
OVERRIDES_PATH = "data/artist_overrides.json"
TRACK_OVERRIDES_PATH = "data/track_overrides.json"
NEW_EPISODES_PATH = "data/.new_episodes.json"  # written by fetch.py, transient

LASTFM_API_KEY = os.environ.get("LASTFM_API_KEY")
LASTFM_URL = "https://ws.audioscrobbler.com/2.0/"

# Only the four excluded categories plus their documented synonym bleed.
# Deliberately narrow: funk is noted in docs/filtering.md as adjacent to
# soul but is NOT excluded, so it's not in this vocabulary.
#
# "singer-songwriter" was dropped 2026-08-17: it describes a performance
# mode, not a genre, and was the single biggest contributor to the review
# queue (23/87 on a real run) by flagging pop/R&B/indie-pop artists who
# simply write their own songs. "folk" and "indie folk" already cover the
# real cases.
#
# rnb added 2026-08-18, at the owner's request, after a before/after check
# against real playlist history (see docs/filtering.md).
#
# reggae added 2026-08-30, at the owner's request. Checked against the
# cached artist tags at the time: only one currently-kept track carried a
# real reggae/dancehall signal - Original Koffee, "RAPID FIYAH" (reggae
# weight 100) - so the blast radius is small. "dub" is included since
# Last.fm uses it for reggae dub specifically (not dubstep, which tags
# itself "dubstep"); low-weight stray "dub" hits (e.g. Ezra Collective,
# Yazmin Lacey at weight 1) don't clear WEIGHT_THRESHOLD or the review
# noise floor either way, so including it is safe.
CATEGORIES = {
    "soul": {"soul", "neo-soul", "neo soul", "northern soul", "uk soul"},
    "country": {"country", "americana", "alt-country", "alt country"},
    "indie folk": {
        "indie folk",
        "folk",
        "freak folk",
    },
    "rnb": {"rnb", "r&b", "contemporary rnb", "alternative rnb"},
    "reggae": {"reggae", "roots reggae", "dancehall", "dub"},
}

# Personal/meta tags Last.fm users apply that aren't genres at all - some of
# these outrank every real genre tag by raw count (more people add a song to
# "my top songs" than bother tagging its actual genre), so they're skipped
# when picking a single display genre. Narrow by design, same spirit as
# CATEGORIES - extend as new ones turn up rather than trying to be exhaustive.
NOISE_TAGS = {"my top songs", "seen live", "favourite", "favourites", "favorite", "favorites"}

# General backstop for one-off junk tags NOISE_TAGS hasn't named yet - found
# via real data (2026-08-05): "motherfuckin rabbits ejaculating sunshine" and
# "she loves big cock" both showed up as an artist's #1 tag. Every legitimate
# genre observed so far is <=3 words ("drum and bass", "singer-songwriter");
# troll tags tend to read like a sentence, so word count is a cheap, reliable
# discriminator without needing a profanity list.
MAX_GENRE_WORDS = 3

# "under 2000 listeners" etc. - a Last.fm popularity-tier convention, common
# for exactly the very new/small artists this show surfaces (found via
# O'Flynn, whose only cached tag was this). Short enough to dodge
# MAX_GENRE_WORDS, and the number varies, so a pattern beats another
# NOISE_TAGS entry.
LISTENER_COUNT_RE = re.compile(r"^(under|over)?\s*[\d,]+\s*listeners?$")


def looks_like_genre(tag):
    if tag in NOISE_TAGS or len(tag.split()) > MAX_GENRE_WORDS:
        return False
    return not LISTENER_COUNT_RE.match(tag)

# Exclude on weight alone, not rank - Last.fm's per-artist weight scale means
# a rank-3 tag can trail the top tag by a huge margin (e.g. 39 vs 100), so
# being 3rd doesn't imply "dominant genre". A below-threshold match still
# routes to review rather than being silently dropped either way.
WEIGHT_THRESHOLD = 50

# A blocked-category tag below WEIGHT_THRESHOLD isn't automatically
# "ambiguous" - below these bars it's noise, not a signal, and defaults to
# keep like no match at all. Found via real data 2026-08-17: most of the
# review queue was R&B/electronic/jazz artists carrying a trace-weight
# "soul" tag from stray crowd-tagging (Erin LeCount: rnb 100 / soul 7,
# WHATMORE: rap 100 / soul 4, Jungle: electronic 100 / soul 10) - nowhere
# near "kind of soul", just noise on an otherwise clear tag profile.
# REVIEW_DOMINANCE_RATIO compares the blocked tag's weight to the artist's
# own top tag (tags are Last.fm-ordered, so tags[0] is the max);
# REVIEW_WEIGHT_FLOOR is an absolute backstop for artists with a flat,
# noisy tag profile where nothing reaches a high top weight.
REVIEW_DOMINANCE_RATIO = 0.25
REVIEW_WEIGHT_FLOOR = 15

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
    nothing under either lookup.

    Tries mbid first when available (exact), but falls back to a name lookup
    if that comes back empty. Last.fm's own mbid linkage is incomplete for
    plenty of real artists - confirmed by hand 2026-08-05 for Sienna Spiro,
    whose mbid lookup returns nothing despite her having a real, populated
    top-tags page (soul, jazz, pop, indie, singer-songwriter) under her name.
    Without this fallback an artist can look "unknown" and default to keep
    when Last.fm actually has tag data, just not linked to that mbid.
    """
    tags = _lastfm_query(mbid=artist_mbid) if artist_mbid else []
    if not tags and artist_name:
        tags = _lastfm_query(artist=artist_name)
    return tags


def _lastfm_query(mbid=None, artist=None):
    params = {
        "method": "artist.gettoptags",
        "api_key": LASTFM_API_KEY,
        "autocorrect": "1",
        "format": "json",
    }
    if mbid:
        params["mbid"] = mbid
    else:
        params["artist"] = artist
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
    - review: a blocked-category tag present with enough weight to be a real
      signal (see REVIEW_DOMINANCE_RATIO / REVIEW_WEIGHT_FLOOR) but below the
      exclude threshold - ambiguous, don't guess.
    - keep: no blocked-category tag carrying real signal, or no tag data at
      all (unknown genre defaults to keep - that's the whole point of an
      exclusion list). A trace-weight blocked tag on an artist clearly
      dominated by something else counts as noise here, not ambiguity.

    tags is assumed weight-descending (Last.fm's own order - same assumption
    the caller already makes when picking a display genre), so tags[0]'s
    weight is the artist's top-tag weight and the dominance baseline below.
    """
    top_weight = tags[0][1] if tags else 0
    noise_floor = max(REVIEW_WEIGHT_FLOOR, REVIEW_DOMINANCE_RATIO * top_weight)

    weak_hit = None
    for tag, weight in tags:
        for category, synonyms in CATEGORIES.items():
            if tag in synonyms:
                if weight >= WEIGHT_THRESHOLD:
                    return "exclude", category, tag
                if weight >= noise_floor and weak_hit is None:
                    weak_hit = (category, tag)
    if weak_hit:
        return "review", weak_hit[0], weak_hit[1]
    return "keep", None, None


def artist_key(artist_mbid, artist_name):
    return artist_mbid or f"name:{artist_name.strip().lower()}"


def track_key(artist, title):
    # Must match sync.py's track_key() exactly - it's how a downvote
    # written there gets matched back up here.
    return f"{artist.strip().lower()}|||{title.strip().lower()}"


def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path) as fh:
        return json.load(fh)


def save_json(path, data):
    with open(path, "w") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False, sort_keys=True)


def resolve_artist(key, artist_mbid, artist_name, cache, overrides, misses):
    """decision, category, matched_tag, genre for one artist, consulting
    overrides, then cache, then Last.fm (fetching tags on a cache miss).

    genre is the artist's top Last.fm tag that passes looks_like_genre()
    (not a known meta-tag, not a troll tag going by word count), independent
    of whether it matched a blocked category - it's informational only, so
    kept tracks show *something* instead of always being blank.
    category/matched_tag stay reserved for the exclusion reasoning
    specifically.

    The cache stores tags, not decisions - classify() runs fresh every time
    so a rule change (new synonym, new threshold) takes effect on the next
    run without spending an API call to re-derive data Last.fm already gave
    us. Overrides are decisions, not tags, since they exist specifically to
    override whatever classify() would say.
    """
    if key in overrides:
        entry = overrides[key]
        return entry["decision"], entry.get("category"), entry.get("matched_tag"), entry.get("genre")

    if key in cache:
        tags = cache[key]["tags"]
    elif LASTFM_API_KEY:
        tags = lastfm_top_tags(artist_mbid, artist_name)
        cache[key] = {"name": artist_name, "tags": tags[:10], "source": "lastfm"}
        time.sleep(0.25)  # be polite to Last.fm, same spirit as fetch.py
    else:
        misses.append((artist_name, artist_mbid))
        tags = []

    genre = next((tag for tag, _ in tags if looks_like_genre(tag)), None)
    decision, category, matched_tag = classify(tags)
    return decision, category, matched_tag, genre


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
    track_overrides = load_json(TRACK_OVERRIDES_PATH, {})

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
        tkey = track_key(track["artist"], track["title"])
        if tkey in track_overrides:
            entry = track_overrides[tkey]
            decision, category, matched_tag, genre = (
                entry["decision"], entry.get("category"), entry.get("matched_tag"), entry.get("genre")
            )
        else:
            key = artist_key(track.get("artist_mbid"), track["artist"])
            decision, category, matched_tag, genre = resolve_artist(
                key, track.get("artist_mbid"), track["artist"], cache, overrides, misses
            )
        counts[decision] += 1
        out_rows.append(
            {
                **track,
                "decision": decision,
                "category": category,
                "matched_tag": matched_tag,
                "genre": genre,
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

    report_new_episodes(out_rows)


def report_new_episodes(out_rows):
    """Full per-track breakdown for whatever episode(s) fetch.py found new
    this run - every track, so nothing about a given episode's fate is left
    to infer from aggregate counts. sync.py adds the Spotify-outcome half
    (added/already-there/no-match) for the keep and review tracks below."""
    new_pids = set(load_json(NEW_EPISODES_PATH, []))
    if not new_pids:
        print("::group::New episode(s) this run: none")
        print("::endgroup::")
        return

    rows = [r for r in out_rows if r["episode_pid"] in new_pids]
    dates = sorted({r["broadcast"] for r in rows})
    print(f"::group::New episode(s) this run: {', '.join(dates)} ({len(rows)} tracks)")
    for decision in ("keep", "review", "exclude"):
        group = [r for r in rows if r["decision"] == decision]
        label = {"keep": "KEEP", "review": "REVIEW (ambiguous)", "exclude": "EXCLUDE"}[decision]
        print(f"{label} ({len(group)}):")
        for r in group:
            reason = f"  [{r['category']}: {r['matched_tag']}]" if r["category"] else ""
            genre = f"  ({r['genre']})" if r.get("genre") else ""
            print(f"  {r['artist']} - {r['title']}{reason}{genre}")
    print("::endgroup::")


if __name__ == "__main__":
    main()

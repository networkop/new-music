# new-music

Takes the tracklist from BBC Radio 1's New Music Show, drops genres I don't want
to hear, and maintains a rolling one-month playlist.

**Status: stage 1 of 3.** Fetching is built. Filtering and playlist sync are
designed but not implemented.

## Layout

```
CLAUDE.md                          project context — read this first
docs/bbc-feeds.md                  the BBC JSON API, routes and traps
docs/filtering.md                  genre filter design
docs/playlist-sync.md              YouTube Music / Spotify options
scripts/fetch.py                   the fetcher (stdlib only)
.github/workflows/fetch.yml        Mon–Thu 21:00 UTC, commits results
data/episodes/<pid>.json           one file per broadcast
data/tracks.jsonl                  flattened, one track per line
data/samples/                      a real episode, hand-annotated
```

## Running it

```bash
python scripts/fetch.py                  # last 35 days
WINDOW_DAYS=120 python scripts/fetch.py  # backfill
```

## First things to do

1. Trigger the workflow manually from the Actions tab. Its first step is a
   canary that checks GitHub's runners can reach the BBC feeds — that assumption
   is untested.
2. Dump a full segment object and check for an ISRC or MusicBrainz ID:
   ```bash
   curl -L -sS https://www.bbc.co.uk/programmes/m002z563/segments.json | jq '.segment_events[0]'
   ```
   The answer shapes the whole of stages 2 and 3.

## Show details

Mon–Thu, 18:00–20:00 UK time. Brand PID `m001chdz`. About 30 tracks an episode.
Not every weeknight airs.

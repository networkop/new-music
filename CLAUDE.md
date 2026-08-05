# CLAUDE.md

Context for working on this repo. Written at the end of a long exploratory chat
session so the findings aren't lost — read `docs/` for detail.

## What this is

A personal pipeline that takes the tracklist from BBC Radio 1's New Music Show,
removes genres the owner doesn't want to hear, and maintains a rolling one-month
playlist on a streaming service.

Three stages. Only stage 1 is built.

1. **Fetch** — pull per-episode tracklists from the BBC. *Built, untested in CI.*
2. **Filter** — drop tracks by genre. *Designed, not built. See `docs/filtering.md`.*
3. **Sync** — maintain the rolling playlist. *Options weighed, nothing chosen.
   See `docs/playlist-sync.md`.*

## Owner preferences (these drive the design)

- Streaming service is **Spotify**. Originally YouTube Music, with Spotify
  rejected on switching-cost grounds - reversed 2026-08-04 after YouTube
  Music's OAuth setup turned out to be real friction, not just theory (see
  Dead ends). Spotify's official API is also stdlib-drivable, so this
  drops the one non-stdlib dependency the project had picked up.
- The filter is an **exclusion list, not an allowlist**: soul, country, indie
  folk. Everything else is wanted.
- Consequence, and it's the important one: **unknown genre means keep**. The
  show's whole point is brand-new artists, and those are exactly the ones no
  genre database has data for. An allowlist would silently bin them. Don't
  "improve" this into an allowlist.

## Verified facts — don't re-derive these

Established by hand against the live API. Confirmed, not assumed:

- Brand PID is `m001chdz`.
- Broadcast slot is **Mon–Thu, 18:00–20:00 UK time**. Not every weeknight has an
  episode — 30 and 31 July 2026 had none.
- `/programmes/{brand}/episodes.json` is **not a list of episodes**. It returns
  `{"filters": {"years": [...]}}` — an index of which months have content. This
  wasted time once already.
- `/programmes/{brand}/episodes/{year}/{month}.json` returns `{"broadcasts": [...]}`.
  Episode PID is at `.broadcasts[].programme.pid`. Month accepts both `7` and `07`.
- **Monthly files include future scheduled broadcasts.** On 4 Aug the August file
  led with 26 Aug. Always filter on start time.
- `/programmes/{episode_pid}/segments.json` returns `{"segment_events": [...]}`,
  with artist and title at `.segment.artist` / `.segment.title`. Follow redirects
  — segments belong to the version, not the episode.
- `/programmes/{brand}/episodes/player.json` 404s. `episodes/last.json` returns
  200 but its shape was never inspected.

- **No ISRC. Artist-level MusicBrainz ID, yes; track-level, no.** Checked against
  570 fetched tracks: `isrc` is null on all of them, and so is the track-level
  `musicbrainz_id` field `fetch.py` extracts. But
  `.raw.primary_contributor.musicbrainz_gid` is populated on 566/570 (99.3%),
  including on brand-new acts (`flowerovlove`, `Westside Cowboy`). Misses so far:
  `Culture Shock`, `ayraa star`, `Nero`. Consequence: stage 3 sync still needs
  fuzzy title matching (no exact track ID). Stage 2 filtering doesn't — key the
  artist cache and genre lookups by MusicBrainz GID instead of by name string.
  Last.fm's `artist.getTopTags` takes an `mbid` param directly.

- **Spotify's Feb 2026 Web API migration renamed the playlist endpoints
  `script/sync.py` uses.** Hit this live as a 403 on playlist creation despite
  correct scopes. `POST /users/{id}/playlists` → `POST /me/playlists`.
  `/playlists/{id}/tracks` (GET/POST/DELETE) → `/playlists/{id}/items`, with
  the GET response renaming `items[].track` → `items[].item` and dropping the
  max page size from 100 to 50. The DELETE body key also renamed `tracks` →
  `items`; the POST body key for adding stayed `uris`. Also: Development Mode
  apps now require the app owner to have an active Premium subscription.
  Official guide:
  https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide

## Open questions — resolve these early

- **Can GitHub-hosted runners reach the BBC feeds?** Geo-restriction applies to
  audio streams, not metadata, so it should be fine from US runners — but this is
  an assumption. The workflow's first step is a deliberate canary that fails loudly.
  If it fails, a UK self-hosted runner is the fallback.

## Dead ends — don't revisit

- **1001tracklists** — robots.txt disallows automated access, and it sits behind
  bot protection that blocks datacentre IPs. Not worth trying from CI.
- **onlineradiobox** — has a 7-day station-wide log, but it isn't segmented by
  show and its displayed clock disagreed with the real schedule (its 18:00–21:00
  Monday block was the rock show). Abandoned once the BBC API worked.
- **Scraping BBC HTML** — unnecessary, the JSON representations exist.
- **YouTube Music via `ytmusicapi` OAuth** — no official API exists, so this
  was the unofficial route. Setup friction, not a hard blocker, but enough to
  abandon it 2026-08-04: needs a Google Cloud project with a "TVs and Limited
  Input devices" OAuth client, and the token file `ytmusicapi oauth` produces
  is easy to confuse with the client-credentials JSON Cloud Console itself
  hands you (`{"installed": {"client_id": ..., ...}}`) - they look similarly
  official but are not interchangeable. On top of that, Google refresh tokens
  for a Cloud project still in "Testing" publishing status can expire after
  about a week, which would silently break unattended CI. Switched to Spotify
  instead.

## Working notes

- These BBC feeds are **undocumented** and have been retired and relocated
  before. If fetches start 404ing across the board, that's the first hypothesis.
- Be polite: identifiable user-agent, sleep between requests. `script/fetch.py`
  does both.
- The fetcher is idempotent — episodes already on disk are skipped, so re-running
  is cheap and safe.
- **Episodes older than `WINDOW_DAYS` get deleted, not just left alone.**
  Added 2026-08-05 after `data/episodes/` (and everything built from it)
  accumulated every episode ever fetched instead of a rolling window — 52
  unique "keep" songs showing in the GitHub Pages viewer against a 30-day,
  21-track Spotify playlist. History is still recoverable from git; the
  working tree just isn't the place for it.
- Tracklists can lag the broadcast by a few hours. A missing tracklist is not an
  error; the next run picks it up.
- Scheduled GitHub workflows are disabled after 60 days of repo inactivity. This
  job commits on most runs, which keeps it alive, but a long hiatus could kill it
  silently.

## Style

Don't add dependencies without a reason — every script is stdlib-only, so CI
needs no install step. Keep that unless something genuinely requires
otherwise. This held even for `sync.py`: the YouTube Music detour needed
`ytmusicapi` since no official API exists, but Spotify's official REST API is
plain OAuth2 + JSON, drivable with `urllib` like everything else here.

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

- Streaming service is **YouTube Music**. Spotify was considered and would be
  technically easier, but switching services isn't worth it on its own.
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

## Open questions — resolve these early

- **Do segment objects carry an ISRC or MusicBrainz ID?** Never checked, and it
  matters more than anything else here. With an identifier, downstream lookups
  become exact. Without one, everything depends on fuzzy matching artist+title
  for names like `Angine de Poitrine` and `panicbaby`. Run
  `curl -L -sS https://www.bbc.co.uk/programmes/m002z563/segments.json | jq '.segment_events[0]'`
  and look at the full object. `script/fetch.py` already stores the raw segment
  so nothing is lost either way.
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

## Working notes

- These BBC feeds are **undocumented** and have been retired and relocated
  before. If fetches start 404ing across the board, that's the first hypothesis.
- Be polite: identifiable user-agent, sleep between requests. `script/fetch.py`
  does both.
- The fetcher is idempotent — episodes already on disk are skipped, so re-running
  is cheap and safe.
- Tracklists can lag the broadcast by a few hours. A missing tracklist is not an
  error; the next run picks it up.
- Scheduled GitHub workflows are disabled after 60 days of repo inactivity. This
  job commits on most runs, which keeps it alive, but a long hiatus could kill it
  silently.

## Style

Don't add dependencies without a reason — `fetch.py` is stdlib-only so CI needs
no install step. Keep that unless something genuinely requires otherwise.

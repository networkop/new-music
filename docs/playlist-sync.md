# Playlist sync (stage 3, not built)

Goal: a rolling one-month playlist. Tracks age out after ~30 days.

Owner uses **YouTube Music**.

## YouTube Music

There is no official YouTube Music API. Two routes:

**YouTube Data API v3** (official). Manages playlists on the YouTube account,
and those playlists surface in YouTube Music. The mismatch: the API has no
concept of a "song" distinct from any other video, so you can end up with lyric
videos, live cuts or topic-channel uploads instead of the track.

Quota is not a constraint at this volume. Current allocation is 100 `search.list`
calls and 100 `videos.insert` calls per day, plus 10,000 units per day shared
across all other endpoints — note searches are capped separately rather than
drawn from the main pool. At ~30 tracks per broadcast, a nightly run uses ~30
searches against a ceiling of 100. **Cache resolved video IDs** so retries and
re-runs never re-search a known track; that's what keeps it comfortable.

**`ytmusicapi`** (unofficial). Reverse-engineered, speaks YT Music's actual
internals — proper song search, much better matching for obscure new releases.
Costs: browser-header auth that expires, breakage when Google changes things,
and it's outside Google's terms. Judgement call for a personal playlist.

## The rolling window is nearly free

`playlistItems` carry a `publishedAt` — when the item was added to the playlist,
not when the video was uploaded. If tracks are added on the night they're
broadcast, that timestamp *is* the broadcast date, and eviction becomes: list the
playlist (1 unit), delete anything older than 30 days (50 units each). No state
file needed.

This only holds if you never backfill. Seeding the playlist with a month of
history on day one gives every item the same added-date and the window collapses.
If backfilling, keep a state file mapping video ID to broadcast date instead.

## Auth in CI

OAuth refresh tokens for apps left in **"Testing"** publishing status expire after
about a week, which would break an unattended Action. Moving the Cloud project to
Production fixes it. Verify current behaviour in the Cloud Console rather than
trusting this note.

## Spotify, for reference

Considered and rejected on grounds of not switching services, but it would be
easier: an official first-class music API, tracks are tracks, rate limits with
`Retry-After` rather than quota accounting, long-lived refresh tokens, and
crucially an `isrc:` search filter that turns matching into an exact lookup.

Also worth knowing: the BBC runs a `BBC_Playlists` Spotify account. **Checked
2026-08-04, not viable as a shortcut.** Its "Radio 1's New Music Show with Jack
Saunders" playlist is a single 30-track snapshot dated `(Show: 2025-03-17)` —
17 months stale relative to the shows this project fetches. The account's
broader visible catalogue is dominated by 2017-era content (Glastonbury 2017,
Record Store Day 2017). Not a live mirror of current airings — a Spotify build
would still need to do its own track resolution.

## The part that will actually cost time

Matching, on either platform. A naive top-result-wins search will confidently
return the wrong thing, and some tracks won't exist on the platform at all. Log
every match with its query and chosen title, set a similarity threshold, and send
anything below it to a review list rather than the playlist. An ISRC in the BBC
segment data would make most of this disappear — check for one first.

# Playlist sync (stage 3, in progress)

Goal: a rolling one-month playlist. Tracks age out after ~30 days.

Owner uses **Spotify**. (Originally YouTube Music — see "YouTube Music,
considered" below for why that changed.)

## Spotify

Official REST API, well documented, plain OAuth2 + JSON — no client library
needed, `urllib` is enough (see `script/sync.py`).

**Auth**: Authorization Code flow, not Client Credentials — modifying a
user's playlist needs a token issued *for that user*, which Client
Credentials can't give you. One-time interactive step (`script/spotify_setup.py`):
open an authorize URL, log in as the target account, approve, and the local
callback server captures the code and exchanges it for a refresh token.
That refresh token is long-lived — unlike Google's OAuth, there's no
"Testing" publishing status or ~1-week expiry to worry about. Scopes needed:
`playlist-modify-public playlist-modify-private playlist-read-private`.

**Rate limits**: 429 with a `Retry-After` header, not a daily quota. Simpler
to handle than YouTube's quota accounting — just back off and retry.

**Matching**: tracks are tracks, not videos — no lyric-video/live-cut
ambiguity. Search `GET /v1/search?type=track&q=...`. An `isrc:` filter exists
for exact lookup, but doesn't help here — the BBC segment data has no ISRC
(confirmed 2026-08-04 against 570 fetched tracks, see `CLAUDE.md`), so this
is fuzzy artist+title search regardless of platform.

## The rolling window is nearly free

Spotify's `GET /v1/playlists/{id}/tracks` returns each item with `added_at`
(ISO 8601) — same trick as YouTube's `publishedAt`. If tracks are added the
night they're broadcast, that timestamp *is* the broadcast date, and eviction
becomes: list the playlist, remove anything with `added_at` older than 30
days. No state file needed.

This only holds if you never backfill. Seeding the playlist with a month of
history on day one gives every item the same added-date and the window
collapses. If backfilling, keep a state file mapping track URI to broadcast
date instead.

## The part that will actually cost time

Matching. A naive top-result-wins search will confidently return the wrong
thing, and some tracks won't exist on the platform at all. Log every match
with its query and chosen title, set a similarity threshold, and send
anything below it to a review list rather than the playlist.

## YouTube Music, considered

Tried first, abandoned 2026-08-04 over OAuth setup friction — recorded in
`CLAUDE.md`'s Dead ends so it doesn't get re-explored. Summary: no official
YouTube Music API; the unofficial `ytmusicapi` route needs a Google Cloud
"TVs and Limited Input devices" OAuth client, and the token file it produces
is easy to confuse with the plain client-credentials JSON Cloud Console hands
you — they look similarly official but aren't interchangeable. Google
refresh tokens for a Cloud project still in "Testing" status can also expire
after about a week, which would have silently broken unattended CI.

Also worth knowing: the BBC runs a `BBC_Playlists` Spotify account. **Checked
2026-08-04, not viable as a shortcut.** Its "Radio 1's New Music Show with Jack
Saunders" playlist is a single 30-track snapshot dated `(Show: 2025-03-17)` —
17 months stale relative to the shows this project fetches. The account's
broader visible catalogue is dominated by 2017-era content (Glastonbury 2017,
Record Store Day 2017). Not a live mirror of current airings — building on
Spotify still means doing our own track resolution, not aggregating theirs.

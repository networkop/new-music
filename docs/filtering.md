# Genre filtering

## The requirement

Exclude **soul, country, indie folk, rnb**. Keep everything else.

`rnb` added 2026-08-18, at the owner's request. Checked before adding it: run
against the live tracklist data at the time, only one track in the actual
synced Spotify playlist carried a strong `rnb` tag - Kelsey Lu, "Cutting Off
The Head Of A Ghost" (rnb weight 100, broadcast 2026-07-21) - and one more
(Tinashe, "Melatonin") was sitting in the review list and moved to a clean
exclude instead. Confirmed with the owner, then added.

## Why exclusion beats an allowlist here

Genre is the load-bearing component now — it decides what enters the playlist —
and it's the weakest link in the chain, because this show plays precisely the
artists that genre databases cover worst. First-single and unsigned acts return
empty genre arrays from Spotify and have no MusicBrainz entry at all.

An exclusion filter makes **unknown default to keep**. The newest discoveries
sail through instead of being silently dropped. An allowlist inverts that and
quietly destroys the point of the show. This is a deliberate design choice, not
an accident of how it was specified.

It also collapses the hard problem. The system never has to answer "what genre
is this?" — only "does this look like soul, country, or indie folk?", against
three known targets.

## Source options

| Source | Coverage on emerging artists | Notes |
|---|---|---|
| **Last.fm** top-tags | Best — crowd-sourced | Noisy: `seen live`, `favourite`. Filter against a fixed vocabulary. Has both track and artist level. **Start here.** |
| MusicBrainz | Thin | Free, no key, ~1 req/sec, wants a real user-agent. |
| Discogs | Good for electronic subgenres | Needs a token. |
| Spotify artist genres | Patchy, often empty | Genres attach to the *artist*, not the track — a jungle cut and a downtempo one by the same artist get identical labels. |

Spotify's audio-features endpoint (danceability, energy) was closed to new apps
some time ago — verify before designing anything around it.

**Last.fm's mbid linkage is incomplete.** `artist.gettoptags` queried by
MusicBrainz ID can return nothing for an artist who has a real, populated
tags page under their name — confirmed by hand 2026-08-05 for Sienna Spiro
(mbid lookup empty; her actual top tag is `soul`). `filter.py` prefers mbid
for exactness but falls back to a name query when that comes back empty.
15% of cached artists (29/184) had an empty tag list before this fix; not
all of those are genuinely untagged, so don't assume mbid-empty means
unknown-to-Last.fm without checking the name lookup too.

## Rules that matter

**Match on tag weight, not presence.** Last.fm tags carry counts. Excluding on
any appearance of `soul` means one stray tagger removes a Charli xcx track.
Require the blocked tag in the top three, or above a weight threshold.

**The terms bleed.** Build a synonym set per blocked category:

- `soul` → neo-soul, northern soul, uk soul, and it shades into R&B and funk
- `country` → americana, alt-country
- `indie folk` → folk, freak folk; and `indie` + `folk` appearing as
  separate tags usually is a hit. `singer-songwriter` was in this set
  originally but was removed 2026-08-17: it describes a performance mode,
  not a genre, and was flagging pop/R&B/indie-pop artists who simply write
  their own songs - see below.
- `rnb` → r&b, contemporary rnb, alternative rnb. Funk is still explicitly
  NOT excluded, even though it's adjacent - it's not in this vocabulary.

**A blocked tag needs real weight to count as a signal at all, not just to
cross into exclude.** Checked against a real run (549 tracks, 2026-08-17):
87 tracks landed in review, and nearly all of them were an artist clearly
dominated by something else, carrying the blocked tag at trace weight -
Erin LeCount (`rnb` 100 / `soul` 7), WHATMORE (`rap` 100 / `soul` 4), Jungle
(`electronic` 100 / `soul` 10). That's crowd-tagging noise, not ambiguity.
`filter.py` now requires a blocked tag's weight to clear both an absolute
floor and a fraction of the artist's own top-tag weight
(`REVIEW_WEIGHT_FLOOR`, `REVIEW_DOMINANCE_RATIO`) before it counts as a weak
hit at all; below that it's treated the same as no match - keep. Also on
that run, `singer-songwriter` alone accounted for 23 of the 87 review
tracks, which is why it was dropped from the indie-folk synonym set rather
than just weighted down.

**Cache at artist level.** Once an artist is classified, keep it. After a few
weeks the local list does most of the work and API calls approach zero for
recurring names. Owner-corrected entries should outrank API results — a
hand-maintained list is more accurate than any tag source for this material.

**Route ambiguity to a review list**, don't guess. A second playlist the owner
skims occasionally; anything kept there teaches the artist cache.

## Song-level overrides (downvoting)

`data/artist_overrides.json` is artist-level and hand-maintained. There's a
second, song-level override at `data/track_overrides.json` that's written
automatically, not by hand: Spotify has no API-visible "dislike," but
removing a track from the playlist is real and detectable, so `sync.py`
treats a deliberate removal as a downvote and writes it here. Checked first,
ahead of the artist override, since a specific song correction should
outrank a blanket artist one - see `sync.py`'s docstring for the detection
logic and `docs/playlist-sync.md`. Scope is song-level only for now;
excluding an artist entirely is still a manual edit to `artist_overrides.json`.

## Expected cull rate

Hand-applied to the 29 July episode (see `data/samples/`): 5 of 30 tracks, about
17%. Excluded were two soul (Yazmin Lacey, Maverick Sabre), one country (Lainey
Wilson), two indie folk (Julia Jacklin, Phoebe Bridgers). SOAK was the borderline
call — alt/indie with folk leanings depending on the track. That sample is a
reasonable regression fixture, but it's one episode and the genre labels in it
were assigned by hand, not looked up, so treat it as indicative rather than
ground truth.

# Genre filtering

## The requirement

Exclude **soul, country, indie folk**. Keep everything else.

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

## Rules that matter

**Match on tag weight, not presence.** Last.fm tags carry counts. Excluding on
any appearance of `soul` means one stray tagger removes a Charli xcx track.
Require the blocked tag in the top three, or above a weight threshold.

**The three terms bleed.** Build a synonym set per blocked category:

- `soul` → neo-soul, northern soul, and it shades into R&B and funk
- `country` → americana, alt-country
- `indie folk` → folk, singer-songwriter, freak folk; and `indie` + `folk`
  appearing as separate tags usually is a hit

**Cache at artist level.** Once an artist is classified, keep it. After a few
weeks the local list does most of the work and API calls approach zero for
recurring names. Owner-corrected entries should outrank API results — a
hand-maintained list is more accurate than any tag source for this material.

**Route ambiguity to a review list**, don't guess. A second playlist the owner
skims occasionally; anything kept there teaches the artist cache.

## Expected cull rate

Hand-applied to the 29 July episode (see `data/samples/`): 5 of 30 tracks, about
17%. Excluded were two soul (Yazmin Lacey, Maverick Sabre), one country (Lainey
Wilson), two indie folk (Julia Jacklin, Phoebe Bridgers). SOAK was the borderline
call — alt/indie with folk leanings depending on the track. That sample is a
reasonable regression fixture, but it's one episode and the genre labels in it
were assigned by hand, not looked up, so treat it as indicative rather than
ground truth.

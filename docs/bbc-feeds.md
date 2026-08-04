# BBC /programmes JSON feeds

The `/programmes` URL space was designed so that the same resource can be
returned in several representations. Appending `.json` to a programme URL gives
JSON; `.xml`, `.rdf` also exist, and `/segments.xspf` on an episode with a
tracklist returns an XSPF playlist. There is no API key and no documented
contract — these are long-standing but unofficial.

## Routes, with observed behaviour

All relative to `https://www.bbc.co.uk/programmes`.

| Route | Status | Returns |
|---|---|---|
| `/{brand}.json` | 200 | Brand metadata. Useful as a cheap liveness check. |
| `/{brand}/episodes.json` | 200 | **Not episodes.** `{"filters":{"years":[{"id":2026,"months":[{"id":8},…]}]}}` — an index of which year/months have content. |
| `/{brand}/episodes/{year}/{month}.json` | 200 | `{"broadcasts":[…]}`. The real data. Month works padded or unpadded. |
| `/{brand}/episodes/last.json` | 200 | Shape never inspected. |
| `/{brand}/episodes/player.json` | 404 | Doesn't exist. Came from an old mailing-list post. |
| `/{episode}/segments.json` | 200 | `{"segment_events":[…]}` — the tracklist. |

## Broadcast object shape

Confirmed against `m001chdz`, August 2026:

```json
{
  "is_repeat": false,
  "is_blanked": false,
  "schedule_date": "2026-08-26",
  "start": "2026-08-26T18:00:00+01:00",
  "end": "2026-08-26T20:00:00+01:00",
  "duration": 7200,
  "service": { "id": "bbc_radio_one", "title": "BBC Radio 1" },
  "programme": {
    "type": "episode",
    "pid": "m0030cqy",
    "title": "26/08/2026",
    "short_synopsis": "The biggest and best new music in the world, including Radio 1's Hottest Record.",
    "display_titles": {
      "title": "Radio 1's New Music Show with Jack Saunders",
      "subtitle": "26/08/2026"
    },
    "first_broadcast_date": "2026-08-26T18:00:00+01:00"
  }
}
```

Two traps in there:

- **Future broadcasts are included.** That example was returned on 4 August.
- `display_titles.subtitle` is usually the episode's editorial title
  (`"Rachel Chinouriri Hottest Record"`) but falls back to a bare date. Don't
  rely on it for anything structural.

Useful one-liner:

```bash
curl -sS https://www.bbc.co.uk/programmes/m001chdz/episodes/2026/7.json \
  | jq -r '.broadcasts[] | [.start, .programme.pid, .programme.display_titles.subtitle] | @tsv'
```

## Segments

```bash
curl -L -sS https://www.bbc.co.uk/programmes/m002z563/segments.json \
  | jq -r '.segment_events[] | [.segment.artist, .segment.title] | @tsv'
```

`-L` matters: segments hang off the version rather than the episode, so a
redirect is possible.

**Unresolved:** the full segment object was never dumped, so it's unknown
whether ISRCs or MusicBrainz recording IDs are present. This is the single most
valuable unknown in the project — see CLAUDE.md.

## Episode PIDs for testing

Real PIDs from late July 2026, handy as fixtures:

| Date | PID | Title |
|---|---|---|
| 2026-07-29 | `m002z563` | Rachel Chinouriri Hottest Record |
| 2026-07-28 | `m002z7y4` | BNXN, Asake and Chanel Beads |
| 2026-07-27 | `m002z4y9` | Delta Heavy and Nia Archives |
| 2026-07-23 | `m002yy98` | Chase & Status, J Hus, IRAH and Suki Waterhouse |
| 2026-07-22 | `m002yyc4` | Sam Smith Hottest Record |

Note the gap: nothing on 30 or 31 July. Don't assume four episodes a week.

## Show structure

Roughly 30 tracks per two-hour episode. There's a recurring "Hottest Record"
segment where the featured artist gets three tracks in a row near the top — on
29 July that was three Rachel Chinouriri tracks. Relevant to filtering: if a
featured artist is excluded, three tracks go at once.

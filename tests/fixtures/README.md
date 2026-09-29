# Test fixtures

These files are **verbatim captures of Formula 1's own public timing data**,
taken from `livetiming.formula1.com/static/` on 29 September 2026. They are
the Azerbaijan 2026 Grand Prix, Race session.

| File | Bytes | Topic |
|---|---|---|
| `az2026-race-SessionInfo.json` | 510 | Meeting, circuit and session metadata |
| `az2026-race-SessionData.json` | 3 857 | Session status series |
| `az2026-race-TrackStatus.json` | 36 | Track status at session end |
| `az2026-race-LapCount.json` | 35 | Current and total laps |
| `az2026-race-WeatherData.json` | 132 | Air and track temperature, wind |
| `az2026-race-DriverList.json` | 10 078 | Driver ids, numbers, codes, teams, team colours |
| `az2026-race-TimingData.json` | 34 073 | Final classification with gaps and intervals |
| `az2026-race-RaceControlMessages.json` | 19 624 | Race control message history |
| `az2026-race-Position.z.json` | 501 | Circuit-relative car positions |

Total: 68 846 bytes.

## Why they exist

The decode tests are only worth anything if they run against what the feed
actually produces. Hand-written samples test the tests: they encode the
author's assumptions, so a wrong assumption passes. These files are what
`formula1.com` served, which is why the suite can assert things that are
facts rather than preferences — that `Position.z` decodes to integer
circuit-relative coordinates keyed by driver id, that a racing number is a
string while a position is not, that the gap for the leader is absent rather
than zero.

The framing of the payloads is byte-identical to the live stream, so the same
decoder handles both. `scripts/make-snapshot.py` replays them through the
service's own state code to produce the snapshot the panel harness mounts.

## Provenance and what they are not

- They are **not authored by this project** and contain no original work.
- They are **not part of the installed plugin**. They live under `tests/` and
  are used only by the test suite and the design tooling; nothing in the
  runtime path reads them.
- They are **not redistributed as a data source**. Nothing here serves them,
  and the plugin never bundles a snapshot as a fallback for live data — that
  would be showing F1 timing as if it were current.
- They contain **timing metadata only**: positions, gaps, lap counts, team
  names and colours. No broadcast audio or video, and nothing personal about
  anyone but the driver numbers and names already published by Formula 1.

Formula 1's data is not covered by this project's MIT licence. Anyone
reusing these files should make their own judgement about the terms that
apply to them; see the "Terms and limitations" section of the top-level
README.

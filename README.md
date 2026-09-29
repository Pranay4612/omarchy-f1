# Formula 1 for Omarchy

Live Formula 1 timing in the Omarchy bar and panel: the next race when nothing
is running, and during a session the actual live classification, lap count,
race control and **the cars moving around the actual circuit**.

It costs nothing to run. There is no account, no API key, no subscription and
no server. The data comes from the same public timing feed formula1.com uses
for its own site, plus a free public mirror for championship history.

> **Not affiliated with Formula 1.** This is an unofficial, personal project.
> It is not endorsed by, licensed by, or connected to Formula 1, the FIA, or
> any team. See [Terms and limitations](#terms-and-limitations).

---

## What it does

**With a session running** — practice, qualifying, sprint or the race:

- the bar shows a chequered flag, which turns urgent-coloured for the duration
  of the session
- a circuit map with a marker for every car, moving on the real track
- the live classification: position, gap, interval, tyre compound and age
- live session, lap, weather and track status
- race control messages as they are issued
- keyboard navigation: <kbd>↑</kbd>/<kbd>↓</kbd> to select, <kbd>Enter</kbd> to
  highlight a car on the map, <kbd>Esc</kbd> to close

The bar itself carries only the flag. Everything it used to spell out — the
countdown, the lap, the leader — is in the tooltip on hover and in the panel,
which is where text belongs.

**With nothing running:**

- the bar shows the same flag in its ordinary colour
- the panel shows the next race with its circuit and start time, the previous
  race's top three, and both championship tables in full

Either way the panel is a capped, scrolling window onto the data rather than a
printout, so the bottom of the championship is always a wheel gesture away.

**When the circuit has no map yet:** the map says so. It is learned from the
cars' own position data during a live session (see
[How live positions work](#how-live-positions-work)). A plausible-looking loop
with no data behind it is the one thing this plugin refuses to draw.

---

For the visual design — the bar logo, the panel's proportions, why it scrolls
rather than grows — see [design/README.md](design/README.md).

## What is in this repository

The repository is both the source and the installable plugin, because that is
how the marketplace distributes it. Not everything in it is needed at runtime:

| | |
|---|---|
| **Runtime** — the installed plugin | `manifest.json`, the QML files, `f1/`, `bin/` |
| **Development only** — never loaded by the plugin | `tests/`, `design/`, `scripts/`, `shell.qml`, `DevPreview.qml`, `PanelHarness.qml`, `dev-preview.js` |
| **Optional convenience** | `install.sh` / `uninstall.sh` — not needed; see [Install](#install) |

`omarchy plugin add` clones the whole repository, so the development files
travel with it. They are inert: nothing in the plugin loads them, and
`install.sh` deliberately copies an explicit list of runtime files only, so a
manual install gets a clean tree.

## Why it is free

| | |
|---|---|
| **Live timing** | `livetiming.formula1.com` — the public feed behind formula1.com. No key, no account. |
| **Championship data** | `api.jolpi.ca` (Jolpica, the maintained successor to the retired Ergast API). No key, no account. |
| **Circuit geometry** | Derived from the live timing feed itself. |
| **Dependencies** | Python standard library and QML. Nothing to install, no AUR package, no Flatpak, no virtualenv. |

There is no paid tier involved anywhere, and nothing is proxied through a
service this project runs. If the network is unplugged, the plugin goes quiet
and shows the championship from cache — it does not fail.

---

## Install

From the marketplace, or straight from the repository:

```bash
omarchy plugin add https://github.com/OWNER/REPO.git
omarchy plugin enable PLUGIN_ID --section right
```

`omarchy plugin add` clones the repository into
`~/.config/omarchy/plugins/PLUGIN_ID/`, validates the manifest against the
schema and enables it. Nothing is compiled, no package is installed and no
service is registered — the plugin is QML plus a Python service that uses
nothing outside the standard library.

The widget's bar placement can be given explicitly:

```bash
omarchy plugin enable PLUGIN_ID --section right        # whole section
omarchy plugin enable PLUGIN_ID --section right --before io.github.caffeinatedtech.qs-plugin-deepseek-pricing
```

### Installing from a clone

If you have a local checkout, `omarchy plugin add` takes a path as well:

```bash
omarchy plugin add ~/f1-omarchy-plugin
```

`./install.sh` is also provided for a from-scratch setup. It is a convenience,
not a requirement: it copies an explicit list of runtime files, backs up
`shell.json` and prints what it did. It installs **no packages**, because there
are none to install, and it refuses to run rather than guess if it finds
something unfamiliar.

## Remove

```bash
omarchy plugin remove PLUGIN_ID
```

This disables the plugin, which removes it from your bar layout, and deletes
the plugin directory. It does not run anything from inside the plugin — so the
plugin cleans up after itself instead:

- the service watches the directory it was loaded from, and when that
  directory is gone it closes its connection, clears its cache and exits;
- that happens within about five seconds, and it is deliberate rather than a
  crash, so the shell does not report it as one;
- the cache it clears is exactly `$XDG_CACHE_HOME/omarchy/f1/`, and it refuses
  to delete anything else — it checks the path's shape and refuses symlinks
  before removing anything.

`./uninstall.sh` is the belt-and-braces path: it does the same job, plus
removes the cache even if the service was not running.

Verify it yourself:

```bash
./scripts/test-removal.sh
```

That runs the whole sequence — service running, directory deleted, service
exits, no orphan, no leftover cache — against a throwaway copy, without
touching your real installation.

### Optional keyboard shortcut

The installer does not touch your Hyprland config. To open the panel from
anywhere, add this to `~/.config/hypr/hyprland.conf`:

```
bind = SUPER SHIFT F, exec, omarchy-shell f1.omarchy.widget toggle
```

### Configuration

Right-click the bar widget for its settings. One option:

| Setting | Meaning |
|---|---|
| `replayCapture` | Replay a recorded session instead of the live feed, for development and demos. Leave empty for normal use. The panel shows a **REPLAY** badge whenever this is set, so replayed data can never be mistaken for live. |

`F1_PYTHON` in the environment overrides the interpreter, if you want to pin
one.

---

## Architecture

```
f1-omarchy-plugin/
├── manifest.json          Omarchy plugin manifest (schemaVersion 1)
├── Service.qml            the single data engine: reads the snapshot, owns nothing else
├── BarWidget.qml          the bar pill
├── Panel.qml              the popup; switches between live and championship
├── TrackMap.qml           circuit map and moving markers
├── DriverList.qml         live classification
├── DriverRow.qml          one row
├── Championship.qml       standings, next race, last result
├── RaceControl.qml        live race control feed
├── SectionLabel.qml       shared small type
├── StatChip.qml           shared labelled value
│
├── f1/                    the data layer (Python, standard library only)
│   ├── service.py         the background service: one connection, one state
│   ├── replay.py          recorded-session playback
│   ├── cache.py           atomic snapshot and circuit-outline store
│   ├── curve.py           circuit outline reconstruction
│   ├── live/
│   │   ├── ws.py          minimal RFC 6455 WebSocket client
│   │   ├── signalr.py     SignalR client for the F1 feed
│   │   ├── decoder.py     topic payload decoding
│   │   └── state.py       normalised session state
│   └── jolpica/client.py  championship data
│
├── bin/                   command-line tools
├── circuits/              (reserved; see below)
├── tests/                 test suite and captured fixtures
├── scripts/               build, test and preview helpers
├── design/                design notes and screenshots
└── README.md
```

### One connection, one state

The QML layer never opens a socket and never calls a remote API. A single
background process (`f1-service`) holds the only live connection, decodes and
normalises it, and writes two files:

| File | Rate | Contents |
|---|---|---|
| `state.json` | ~1 Hz | standings, calendar, race control, session metadata |
| `positions.json` | up to 10 Hz | where each car is |

Splitting them is what keeps the map smooth: the track map re-reads a ~2 kB
file ten times a second to move twenty dots, instead of re-parsing a 30 kB
snapshot with forty race-control messages. The service throttles the heavy
file precisely because it does not need that rate.

`Service.qml` supervises the process and restarts it if it dies. The panel and
the bar widget are both readers of the same engine, so they cannot disagree.

### Idle behaviour

With no session running the service does **not** hold a live connection. It
polls the small static index (a couple of kB) every three minutes to see
whether a session is running or about to start, and only connects when one is.
Between races the widget costs one HTTP request every few minutes and nothing
else.

---

## How live positions work

This is the part worth reading.

`Position.z` is a topic on the live feed that carries the circuit-relative
position of every car. Each update decodes to:

```json
{"Position": [{"Timestamp": "2026-09-26T12:48:53.537425Z",
               "Entries": {"1": {"Status": "OnTrack", "X": 3696, "Y": 938, "Z": -244}}}]}
```

Three things are worth being precise about:

**The keys are driver ids, not car numbers.** They match the keys in
`DriverList`, which also carries each driver's number, three-letter code, team
and team colour. Nothing about a team or a livery is hard-coded anywhere, so a
new season needs no code change.

**The coordinates are not latitude and longitude.** They are integers in an
unpublished per-circuit local frame, roughly metres, with an origin, rotation
and scale Formula 1 does not publish. They are *not* GPS.

**The feed also emits sentinel coordinates.** A car that has left the circuit
gets a fixed far-away value (for example `Y: -9999`). Those are discarded
rather than clamped, so a car can never be drawn in the wrong country.

### Why the cars cannot drift off their own track

Formula 1 publishes no circuit vector data. The two obvious ways to get some
were both tried and both fail:

- **OpenStreetMap raceway relations** do contain the track, but a relation also
  carries the pit lane, access roads and the paddock. For Baku the recoverable
  loop came out at 7.8 km against a 6.0 km lap, and the real lap could not be
  separated from the rest reliably. It is also ODbL, which would put share-alike
  obligations on the plugin.
- **The public static archive** keeps only about three position samples per
  session. Across every Baku session since 2018 that is 443 distinct points,
  unevenly spread — not enough to order them into a lap, and not enough to fit a
  reliable transform onto a downloaded one.

A live session, by contrast, produces thousands of well-distributed samples.
So the outline is learned from the same telemetry the markers are drawn from:
one frame, no projection, no fit, and therefore no way for a marker to end up
somewhere the track is not.

The pipeline (`f1/curve.py`):

1. **density filter** — merge near-duplicate samples into cell centroids, so the
   result is an average of observations rather than a new position
2. **connected components** — keep the largest blob; the feed's sentinel
   coordinates and any other stray groups fall away
3. **ordering** — greedy nearest neighbour, then 2-opt. The shortest tour
   through points sampled from a closed curve *is* the curve
4. **resample, smooth, simplify**

Outlines are cached per circuit and refreshed while a session runs. Sanity
bounds are enforced: an outline outside 1.2–8 km, or built from too few points,
is rejected rather than drawn.

To build one from a recording, or to watch one being learned live:

```bash
bin/f1-learn-circuit --list              # what is stored
bin/f1-learn-circuit --live               # learn from the next session
bin/f1-learn-circuit --capture ~/captures/baku
```

### Degraded states are labelled, never disguised

- No outline for this circuit → the map says so and explains that it is learned
  during a live session.
- A car stops transmitting (red flag, garage, dropped packet) → its marker dims
  rather than freezing at a stale spot looking current, and the driver list
  shows how old the sample is.
- Replay mode → a red **REPLAY** badge in the panel header.

Nothing is ever extrapolated, smoothed into existence, or presented as a
position the feed did not report. The only interpolation is QML animating
between two coordinates the feed actually sent, over 150 ms.

### What the outline is not

It traces the corridor the cars drive, so kerbs and run-off are not represented.
It is not a survey. It is the right shape for a live position map, and it is
documented as such rather than implied.

---

## The live feed protocol

The endpoint is the one formula1.com uses for its own website. The plugin
speaks the documented SignalR protocol over a WebSocket directly against it.

```text
POST /signalrcore/negotiate?negotiateVersion=1&hub=Streaming  -> connectionToken
WSS  /signalrcore?hub=Streaming&id=<token>                    -> 101
-> {"protocol":"json","version":1}\x1e                          handshake
<- {}\x1e                                                      handshake ack
-> {"type":1,"invocationId":"1","target":"Subscribe","arguments":["Topic"]}
<- {"type":1,"target":"update","arguments":["Topic", <payload>]}
```

Every SignalR message ends with the record separator `0x1E`. Payloads are either
literal JSON or, for the high-volume `.z` topics, a base64 string whose deflate
stream has **no zlib header** and no compression tag.

### Two things that changed in 2026

Both verified against the live service on 2026-09-29, and both are asserted in
`tests/test_protocol.py` so a future edit cannot quietly revert to the old
shapes. Every pre-2025 write-up, including most FastF1 notes, is wrong on both:

| | Old (now broken) | Current |
|---|---|---|
| Connect URL | `/signalrcore?id=<token>` → **404** | `/signalrcore?hub=Streaming&id=<token>` → 101 |
| Handshake | `{}\x1e` → `{"error":"An unexpected error occurred…"}` | `{"protocol":"json","version":1}\x1e` |

`/signalrcore/connect?id=…` now returns **401**: the connect path sits behind an
API gateway. The `hub=` form is the one that is publicly reachable.

**The upgrade step is intermittently 404.** Roughly half of freshly negotiated
tokens are refused at the WebSocket upgrade. Verified 2026-09-29 with raw curl
as well as this client, so it is the endpoint and not the framing: a loop of
negotiated tokens, upgraded with curl, produced the same mix of successes and
404s. `connect()` therefore retries, re-negotiating each attempt rather than
reusing a token, with a bounded number of spaced attempts. Measured over six
consecutive connects with retry enabled: six successes, the slowest taking 8.7 s
across four attempts.

Other notes:

- `GET` on the negotiate endpoint returns 405; it needs `POST`.
- `/signalrcore/negotiate?season=…`-style query parameters are ignored by
  Jolpica; the season has to be in the path.
- The feed is **only active during a session**. Outside one, the connection
  succeeds and nothing arrives. `bin/f1-test-live` says so rather than looking
  broken.

### No WebSocket library

`f1/live/ws.py` is a small RFC 6455 client built on `socket` and `ssl`: client
masking, text and binary frames, continuation reassembly, ping/pong, close.
This is deliberate. Omarchy has no package manager for Python, and asking the
user to run pip or build an AUR package for a status-bar widget is not a
reasonable trade. The whole service imports nothing outside the standard
library, which is asserted by the installer.

---

## Command-line tools

```bash
bin/f1-test-live --protocol    # offline decode check, no network
bin/f1-test-live               # connect to the live feed and print a snapshot
bin/f1-test-live --seconds 60  # keep listening
bin/f1-test-live --watch       # refresh until Ctrl-C
bin/f1-test-live --archive URL # decode a formula1.com static .z file

bin/f1-service                 # run the service in the foreground
bin/f1-service --once          # one pass, print the snapshot
bin/f1-service --replay DIR    # replay a capture

bin/f1-capture --out DIR       # record a live session for replay
bin/f1-learn-circuit --list    # stored circuit outlines
bin/f1-learn-circuit --live    # learn an outline from a live session
```

`f1-test-live` is the first thing to run when something looks wrong. It
isolates the network, protocol and decoding layers from Quickshell, so a
failure there is a real data problem rather than a UI problem.

### Replay

```bash
bin/f1-capture --seconds 3600 --out ~/captures/baku   # during a session
bin/f1-service --replay ~/captures/baku                # replay it
```

A capture is a directory of topic files in the same format formula1.com's own
static archive uses. Replay is for development and demos; it is always labelled
**REPLAY** in the UI.

---

## Development

```bash
scripts/test.sh            # unit tests, no network
scripts/test.sh --qml      # also lint the QML against the installed shell
scripts/test.sh --live     # also hit the real public endpoints
scripts/panel-test.sh      # end-to-end: real Panel.qml, real snapshot
scripts/panel-test.sh --shot
scripts/preview.sh         # design render against mock data
scripts/preview.sh --idle  # championship design
scripts/make-snapshot.py   # build a snapshot from the captured fixtures
```

### Tests

71 unit tests, no network required, and they run against fixtures captured from
formula1.com's own archive rather than against hand-written samples:

| File | Covers |
|---|---|
| `tests/test_protocol.py` | endpoint contract, handshake, framing, compression variants, `.z` decoding, WebSocket handshake/masking/frame lengths |
| `tests/test_state.py` | driver mapping, classification, gaps, tyre and stint data, positions, sentinels, race control, snapshot contract, malformed input |
| `tests/test_track.py` | density filter, components, tour ordering, outline reconstruction and its rejection paths, map projection, staleness, cache |
| `tests/test_live.py` | the real endpoints (opt-in with `F1_LIVE_TESTS=1`) |

`scripts/panel-test.sh` is the one that catches UI bugs a lint cannot: it mounts
the real `Service.qml` and the real `Panel.qml` with only the shell facade
stubbed, and fails on any runtime `ReferenceError`, `TypeError` or bad property
assignment. It found several real ones during development, including a panel
whose entire UI was being silently discarded because `qs.Ui.Panel` has no
`contentItem`, and a panel that reported itself open while drawing nothing
because it had no `KeyboardPanel` surface.

`bin/f1-service`'s snapshot is read by `Service.qml` through a `FileView` whose
path is held empty until the cache directory exists. A `FileView` bound to a
path under a directory that is not there yet sets up its watcher against
nothing and then never sees the file the service writes seconds later, which
looks exactly like a dead service.

Two IPC affordances exist for diagnosing a panel that does not appear without
attaching a debugger to the shell:

```bash
omarchy-shell f1.omarchy status          # the service: mode, data, circuit
omarchy-shell f1.omarchy.widget status    # the widget: panel loaded, surface geometry
```

### Three structural notes

All three are load-bearing and all three were learned the hard way:

- **`qs.Ui.Panel` is a plain `Item`.** It has no `contentItem`, and the bar's
  popout coordinator sizes a panel from its children. The panel's content is a
  direct child.
- **A `Panel` with no `KeyboardPanel` inside it never appears.** `Panel` is
  only the open/close state machine; `KeyboardPanel` is the layer-shell
  surface that actually gets mapped. With the content as direct children of
  `Panel`, the widget reported itself open, a layer surface was created, and
  nothing was drawn — the hardest kind of failure to see, because every state
  in the UI said it was working. The content belongs inside a `KeyboardPanel`
  with a `PanelKeyCatcher` for keyboard focus, and the surface is sized from
  the content's measured height.
- **The components live next to the panel, not in a subdirectory.** A directory
  import with a `qmldir` was tried first and resolved unreliably: Quickshell's
  AOT scanner registered the types progressively, so the `Loader` the bar widget
  uses to open the panel could fail on whichever type it had not reached yet. The
  flat layout is also how Omarchy's own plugins are arranged.

### Circuits directory

`circuits/` is empty on purpose. Circuit outlines are learned at runtime and
cached in `~/.cache/omarchy/f1/circuits/`, because deriving them from the feed
is both more accurate and licence-clean. See
[How live positions work](#how-live-positions-work) for why nothing is
downloaded instead.

---

## Troubleshooting

**The bar shows the next race but nothing ever goes live.**
Almost always: no session is running. The feed only publishes during a
session. `bin/f1-test-live` will connect successfully and receive nothing.

**`Connected: YES` but no data.**
Same cause, different phrasing. Check `bin/f1-service` in a terminal for its
log.

**The panel is empty or stale.**
Middle-click the bar widget to restart the data service, or:

```bash
omarchy-shell f1.omarchy refresh
```

**The track map says it has no outline for this circuit.**
Expected until the circuit has been seen live once. `bin/f1-learn-circuit
--live` during the session, or let the service learn it. The classification
works either way.

**Cars are not moving.**
Check that the session is actually live (`f1-test-live`), and that
`positions.json` is being written:

```bash
ls -la ~/.cache/omarchy/f1/
```

**Everything is stale after a long time.**
The service exits after fifteen minutes without traffic. The widget restarts it
when a session is detected. A manual middle-click forces it.

**The feed protocol broke upstream.**
`tests/test_protocol.py` has the endpoint contract as assertions. If the feed
changes, that is the first place it will show up. `f1-test-live --protocol`
checks decoding without touching the network.

**Logs.**

```bash
~/.cache/quickshell/            # shell logs
/tmp/f1-panel-test.log          # end-to-end harness
/tmp/f1-preview.log             # design render
```

---

## Terms and limitations

**This project is not affiliated with Formula 1.** It is an unofficial,
personal-use project and makes no claim to any Formula 1 trademark or content.
It does not redistribute Formula 1 audio, video or broadcast.

**What it does:** requests the same public timing endpoint a visitor's browser
requests when loading the Formula 1 website, parses the response, and displays
it locally on the user's own machine. No authentication, paywall, DRM or
access control is bypassed, and none is present to bypass.

**Intended use here is personal, local and non-commercial.** Public access to
an endpoint is not the same as a grant of redistribution rights, and it is not
treated as one. Nothing is redistributed: the plugin shows data on the user's
own screen and stores it only in the user's own cache. If you want to publish
anything derived from this — a public dashboard, a bot, a commercial product —
that is a different question and you should get your own answer from Formula 1
rather than rely on this project's.

**Known protocol limitations:**

- The feed is undocumented and unsupported. It can change without notice, and
  it already has twice (see above).
- The WebSocket upgrade is refused for roughly half of fresh tokens. The
  connect path retries, but this is the reason a first connection can take a
  few seconds.
- The service treats a 403 or 429 from the feed as "no session" and backs off
  rather than retrying aggressively, to avoid hammering a free public endpoint.
- Championship data comes from a volunteer-run mirror. It can lag or be briefly
  unavailable; the plugin keeps serving its cached copy.
- Circuit outlines take a live session to learn.
- Position data is unavailable for some sessions. When it is, no markers are
  drawn — the classification still works, and the map says why.

### Provenance

| | |
|---|---|
| **Formula 1 data** | Timing and championship data originates with Formula 1 and its partners, retrieved from their public endpoints. Not ours. |
| **Community reverse engineering** | The SignalR framing, the `.z` compression scheme and the meaning of each topic were worked out by the open-source F1 timing community — FastF1, f1-dash and others. This project reads that public documentation and re-implements it in its own code, without copying theirs. The two protocol changes above were found by testing against the live endpoint, not by copying an implementation. |
| **This project's code** | The WebSocket client, the SignalR client, the decoders, the state model, the outline reconstruction, the service, the QML, the tests and the tooling are all original to this repository. |
| **Jolpica** | `api.jolpi.ca` is an independent, volunteer-run service. Not affiliated with this project. |

## Licence

MIT. See the manifest for the plugin's declared licence.

Note that this covers *this project's code only*. Data retrieved at runtime
belongs to Formula 1 and is not redistributed by this project. The one
exception worth naming explicitly is the captured timing files under
`tests/fixtures/`, which are verbatim copies of Formula 1's public timing
output kept so the decode tests run against reality instead of against the
author's assumptions. They are test-only, are not part of the installed
plugin, and are documented in `tests/fixtures/README.md`.

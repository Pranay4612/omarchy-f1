# Design

The visual design, and why it looks the way it does.

## Principle

Dense, technical, native. This is a status widget that happens to be about
motor racing, not a racing website. The reference is a timing screen or a
telemetry readout, not a broadcast graphic: small type, no gradients, no
drop shadows, no gloss, no rounded cards with generous padding.

Everything comes from Omarchy's own tokens — `Color.foreground`,
`Color.muted`, `Color.accent`, `Color.urgent`, `Color.background`, the
`Style.spacing` scale and the `Style.font` scale. No colour is hard-coded
except two: black knocked out of a team-coloured marker (so the number stays
legible on both a light and a dark livery) and the replay badge, which uses
`Color.urgent` at low alpha. Switch theme and the panel follows with no reload.

The team colours are not hard-coded either. They come from the feed's own
`DriverList.TeamColour`, one hex per car, published by Formula 1. A livery
change or a new entrant needs no change here.

## Screenshots

| File | What it shows |
|---|---|
| `shots/race-live.png` | Live session: circuit map, classification, race control. Mock data. |
| `shots/championship.png` | Idle: next race, last result, both championship tables. Mock data. |
| `shots/panel-e2e.png` | The panel as it actually runs: the real `Panel.qml` in the real Omarchy shell, idle mode, live data from Jolpica, capped height with the standings scrolling below the fold. |

`race-live.png` and `championship.png` are design renders against fabricated
values, so column widths and label placement can be checked without waiting for
a race. `panel-e2e.png` is a capture of the real panel in the real shell — the
bar logo, the theme colours, the capped height and the scroll are all the
genuine article.

Reproduce them:

```bash
scripts/preview.sh            # race-live.png
scripts/preview.sh --idle     # championship.png

# panel-e2e.png is captured from the running shell, because the panel's content
# lives in its own layer-shell surface and cannot be grabbed from a standalone
# quickshell instance:
omarchy-shell f1.omarchy.widget open
grim -g "900,25 740x590" design/shots/panel-e2e.png
omarchy-shell f1.omarchy.widget close
```

`scripts/panel-test.sh` still runs headless and asserts what a screenshot
cannot: that the panel loads, that the data reached it, and that the content
genuinely scrolls.

## Layout

**The bar** is the flag and nothing else. No race name, no countdown, no lap.

There was a text label here first — `Azerbaijan GP 5d 14h` idle,
`LIVE LAP 32/57 P1 VER` live — and it was removed because a bar is not a place
to read. A widget that spells out a countdown is a widget whose value goes
stale visibly, and whose elided text is either too short to be useful or wide
enough to crowd the bar. The flag plus a hover tooltip is the same information
at a fraction of the visual weight.

The flag's colour is therefore the only live signal, and it is a real one: the
urgent colour means a session is running. Everything else moved to the tooltip,
which already carried it.

**The panel** is a single column with four sections, in priority order for the
state it is in:

1. **Header** — meeting, circuit, and a `REPLAY` badge when replaying.
2. **Status strip** — session, lap, track status, weather. A row of small
   labelled values; each chip hides itself when the feed has nothing for it, so
   the row never shows an empty field.
3. **Live body** — the map on the left, square, and the classification taking
   the rest of the row. The map is the reason the panel is wide.
4. **Race control**, newest first, fading with age. Severity comes from the
   message's own `Category` and `Flag`, not from guessing at the wording, so a
   safety car and a cleared sector cannot look alike.

In idle mode the same header is followed by the next-race card, the last
result, and the two championship tables side by side.

## The circuit map

- The track is a **Canvas repainted only when the outline or the size
  changes** — a handful of times per session. The cars are separate `Item`s
  moved by QML's property animations, so they glide between telemetry samples
  at display rate without the track being redrawn underneath them. A Canvas
  with the cars painted into it would have been far too slow; a `Shape` that
  shares a scene graph with the markers would couple the two. This keeps them
  independent.
- The line is drawn twice: a wide, low-alpha halo, then the stroke on top.
  Both derive from `Color.foreground` with an alpha, so neither needs a colour
  token of its own and the track has some depth without a second palette entry.
- The fit is a **uniform scale**, never per-axis. Stretching the two axes
  independently would distort the circuit, and it would also mean a car's
  position depended on the panel's aspect ratio.
- Markers are a filled circle in the team's colour, a knocked-out car number,
  and the three-letter code above. A driver whose sample is more than eight
  seconds old dims to 35%: the feed has stopped telling us where it is, and
  showing it at full opacity would be a lie.
- **No outline means no map.** The map says the circuit has no outline yet and
  explains that it is learned during a live session. It does not draw a
  plausible-looking loop.

## The classification

```
POS  DRV   GAP        INT    TYRE
 1   NOR   LEADER            SO 12
 2   VER   +1.842    +1.842  ME  9
```

Team colour is a 2 px bar on the left edge, not a filled row: twenty solid
blocks would out-shout the data. The leader reads `LEADER` rather than
`+0.000` whether the feed sends an empty gap or a zero. The throttle trace is a
thin bar that fills left to right — one number per car, cheap, and it is what
makes a static-looking tower feel live.

The list scrolls. A `FlickDeceleration` of 4000 makes twenty rows reachable
without a chore on a small panel.

## Type and spacing

Everything inherits `Style.font` and `Style.spacing`, so the panel grows with
the user's base font size instead of becoming cramped: the body width, the map
height and the row heights are all multiplied by `Style.fontScale`. Section
spacing comes from a single `Column` spacing value; a QML positioner skips
invisible children entirely, so hiding a section needs no manual margin
bookkeeping.

## Things deliberately not done

- No team colour swatches in the championship tables. Jolpica does not publish
  one, and inventing a plausible hex would be a fabrication.
- No start/finish line until one can be observed. Marking an arbitrary point on
  the outline as the line would be worse than not drawing it.
- No flags as emoji in race control. Severity is a weight and a colour from the
  feed's own category; a row of emoji reads as decoration, not as timing.
- No animations beyond the marker's movement between samples. A live timing
  display that bounces is a live timing display you have to wait to read.

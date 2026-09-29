#!/usr/bin/env python3
"""Build a snapshot from the archived fixtures, for UI work and tests.

Writes exactly the two files the service writes, using the service's own state
code, so the panel can be driven from real formula1.com data without a live
session. This is how the design and the end-to-end test are produced, and it is
the same code path the live service uses, so a difference here would be a
difference there.

    scripts/make-snapshot.py                    # into the real cache dir
    scripts/make-snapshot.py --out /tmp/demo    # somewhere else
    scripts/make-snapshot.py --positions        # only the marker file
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from f1 import cache  # noqa: E402
from f1.jolpica import client as jolpica  # noqa: E402
from f1.live.decoder import decode_position_payload, decode_topic_payload  # noqa: E402
from f1.live.state import LiveState  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
EVENT = "az2026-race"


def fixture(name):
    return (FIXTURES / f"{EVENT}-{name}.json").read_bytes()


def build_state() -> LiveState:
    s = LiveState()
    s.mode = "live"
    s.connected = True
    # Apply the topics the way they arrive during a session, so the state is
    # built by the same code the live service uses.
    s.apply_driver_list(decode_topic_payload(fixture("DriverList")))
    s.apply_session_info(decode_topic_payload(fixture("SessionInfo")))
    s.apply_session_data(decode_topic_payload(fixture("SessionData")))
    s.apply_track_status(decode_topic_payload(fixture("TrackStatus")))
    s.apply_lap_count(decode_topic_payload(fixture("LapCount")))
    s.apply_weather(decode_topic_payload(fixture("WeatherData")))
    s.apply_timing(decode_topic_payload(fixture("TimingData")))
    s.apply_race_control(decode_topic_payload(fixture("RaceControlMessages")))
    for sample in decode_position_payload(fixture("Position.z")):
        s.apply_position(sample)
    s.age_positions()
    s.circuit_short = "Baku"
    return s


def build_outline(state: LiveState):
    """Learn a circuit outline from the fixture positions, if they suffice.

    The archive keeps only a few samples per session, so a single fixture is
    usually too sparse. This returns None rather than a bad outline, which is
    the honest outcome and exercises the panel's "not learned yet" state.
    """
    from f1 import curve

    samples = []
    for sample in decode_position_payload(fixture("Position.z")):
        for raw in sample.entries.values():
            if not isinstance(raw, dict):
                continue
            x, y = raw.get("X"), raw.get("Y")
            if x is None or y is None or abs(x) > 20000 or abs(y) > 20000:
                continue
            samples.append((float(x), float(y)))
    path = curve.build_outline(samples)
    if not path:
        return None
    return {
        "key": state.circuit_short,
        "points": [[round(x, 2), round(y, 2)] for x, y in path],
        "length": round(curve.path_length(path), 1),
        "samples": len(samples),
        "learnedAt": int(time.time()),
    }


def championship() -> dict:
    out: dict = {}
    try:
        races = jolpica.races()
        out["next"] = jolpica.next_race(races)
        prev = jolpica.previous_race(races)
        out["previous"] = prev
        if prev:
            out["previousResults"] = jolpica.race_results(
                int(prev.get("season") or jolpica.season_now()), str(prev.get("round", ""))
            )
    except Exception as exc:  # noqa: BLE001
        print(f"note: calendar unavailable ({exc})", file=sys.stderr)
    try:
        out["drivers"] = jolpica.driver_standings()
    except Exception as exc:  # noqa: BLE001
        print(f"note: driver standings unavailable ({exc})", file=sys.stderr)
    try:
        out["constructors"] = jolpica.constructor_standings()
    except Exception as exc:  # noqa: BLE001
        print(f"note: constructor standings unavailable ({exc})", file=sys.stderr)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", help="directory to write into (default: the plugin cache)")
    ap.add_argument("--positions", action="store_true", help="only write positions.json")
    ap.add_argument("--no-championship", action="store_true", help="skip the Jolpica calls")
    args = ap.parse_args()

    if args.out:
        import os

        os.environ["XDG_CACHE_HOME"] = args.out
    cache.ensure_dirs()

    state = build_state()
    snapshot = state.to_dict()
    snapshot["championship"] = {} if args.no_championship else championship()
    snapshot["outline"] = build_outline(state)

    cache.save_positions(snapshot)
    if not args.positions:
        cache.save_state(snapshot)

    print(f"state:      {cache.state_path()}")
    print(f"positions:  {cache.positions_path()}")
    print(f"drivers:    {len(snapshot['drivers'])}")
    print(f"located:    {len(snapshot.get('drivers') or [])} total, "
          f"{sum(1 for d in snapshot['drivers'] if d['hasPosition'])} with a position")
    print(f"race ctrl:  {len(snapshot['raceControl'])} messages")
    print(f"outline:    {snapshot['outline']['length'] if snapshot['outline'] else 'not learned (too few archive samples)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

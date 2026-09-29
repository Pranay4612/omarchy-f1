"""Replay recorded F1 timing data so the UI can be built without a live race.

This is a development and demo aid, never a substitute for the real feed.
It is loud about that in three ways: the state mode is "replay", the panel and
bar show a REPLAY badge, and the snapshot records the capture it came from.

A capture is a directory of topic files in exactly the format formula1.com's
own static archive uses, so a session can be recorded once and replayed
anywhere:

    capture/
      meta.json            {"session": "Race", "circuit": "Baku", ...}
      Position.z.json
      TimingData.json
      DriverList.json
      ...

Record one with `f1-capture` during a live session.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from . import curve
from .live.decoder import decode_position_payload, decode_topic_payload

# Replay timing: the live feed is bursty, so samples are stepped rather than
# slept to keep the whole session watchable. This is presentation only and is
# labelled as replay everywhere it surfaces.
DEFAULT_STEP = 0.35


class Capture:
    def __init__(self, root: Path):
        self.root = root
        meta = {}
        try:
            meta = json.loads((root / "meta.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        self.meta = meta

    def topic(self, name: str):
        for candidate in (f"{name}.json", f"{name}.z.json"):
            p = self.root / candidate
            if p.is_file():
                try:
                    return p.read_bytes()
                except OSError:
                    return None
        return None

    @property
    def circuit(self) -> str:
        return str(self.meta.get("circuit") or self.root.name)

    @property
    def label(self) -> str:
        return str(self.meta.get("label") or self.circuit)


def _timing_frames(raw: bytes):
    """TimingData in a capture is a snapshot list; yield them in order."""
    payload = decode_topic_payload(raw)
    if not isinstance(payload, dict):
        return []
    if "Series" in payload or "StatusSeries" in payload:
        return [payload]
    return [payload]


def run_replay(service, spec, step: float = DEFAULT_STEP, loop: bool = True):
    """Drive `service` from a capture on disk, on its own thread."""
    root = Path(spec)
    if not root.is_dir():
        service.log(f"[f1] replay: no such capture: {root}")
        return
    cap = Capture(root)
    svc = service

    def say(msg):
        svc.log(f"[f1] replay {msg}")

    with svc._lock:
        svc.state.mode = "replay"
        svc.state.connected = True
        svc.state.circuit_short = cap.circuit
        svc.state.meeting_name = str(cap.meta.get("meeting", cap.label))
        svc.state.session_type = str(cap.meta.get("session", "Race"))
        svc.state.session_status = "Started"
        svc.state.revision += 1
    svc._circuit_key = cap.circuit
    say(f"loaded capture '{cap.label}'")

    static = {t: cap.topic(t) for t in (
        "DriverList", "SessionInfo", "SessionData", "TrackStatus",
        "LapCount", "WeatherData", "RaceControlMessages", "TimingData",
    )}

    positions: list = []
    raw = cap.topic("Position.z")
    if raw:
        positions = decode_position_payload(raw)
        say(f"{len(positions)} position snapshots")

    # Replay as a race: start near the beginning of the position data and run
    # forward, deriving the lap counter from the snapshot index.
    total = len(positions)
    if total == 0:
        say("capture has no Position.z data; showing static snapshot only")
        _apply_static(svc, static)
        svc._publish()
        while svc.running:
            time.sleep(1.0)
        return

    _apply_static(svc, static)
    laps = svc.state.total_laps or max(1, total // 2)
    i = 0
    while svc.running:
        if i >= total:
            if not loop:
                break
            i = 0
        sample = positions[i]
        with svc._lock:
            svc.state.apply_position(sample)
            svc.state.current_lap = max(1, min(laps, int(i * laps / max(1, total)) + 1))
            svc.state.age_positions()
            svc.state.last_message_at = time.time()
            svc.state.revision += 1
            for raw_pos in sample.entries.values():
                if isinstance(raw_pos, dict):
                    x, y = raw_pos.get("X"), raw_pos.get("Y")
                    if x is None or y is None:
                        continue
                    x, y = float(x), float(y)
                    if abs(x) > 20000 or abs(y) > 20000:
                        continue
                    svc._samples.append((x, y))
        if i % 6 == 0:
            svc._maybe_build_outline()
        svc._publish()
        i += 1
        time.sleep(step)
    say("replay finished")


def _apply_static(svc, static: dict):
    st = svc.state
    with svc._lock:
        if static.get("DriverList"):
            st.apply_driver_list(decode_topic_payload(static["DriverList"]))
        if static.get("SessionInfo"):
            st.apply_session_info(decode_topic_payload(static["SessionInfo"]))
        if static.get("SessionData"):
            st.apply_session_data(decode_topic_payload(static["SessionData"]))
        if static.get("TrackStatus"):
            st.apply_track_status(decode_topic_payload(static["TrackStatus"]))
        if static.get("LapCount"):
            st.apply_lap_count(decode_topic_payload(static["LapCount"]))
        if static.get("WeatherData"):
            st.apply_weather(decode_topic_payload(static["WeatherData"]))
        if static.get("RaceControlMessages"):
            st.apply_race_control(decode_topic_payload(static["RaceControlMessages"]))
        if static.get("TimingData"):
            st.apply_timing(decode_topic_payload(static["TimingData"]))
        st.revision += 1

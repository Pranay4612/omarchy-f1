"""Normalised live-session state.

The raw feed is a stream of partial topic deltas keyed by F1-internal ids.
The UI must never see that: it wants one coherent, self-consistent snapshot.
This module owns that translation.

Rules that matter:
* A driver's location is only ever published when the feed actually said where
  it was. Nothing here invents, extrapolates or smooths a position.
* Every position sample carries the timestamp it arrived with, so the QML side
  can fade a marker out instead of freezing it at a stale spot when a car
  stops transmitting (red flag, garage, dropped feed).
* Team colours come from the feed's own DriverList.TeamColour. Nothing about a
  team's livery is hard-coded here, so a new season needs no code change.
"""

from __future__ import annotations

import math
import re
import time
from datetime import datetime, timezone

# Position.z Status values seen on the current feed.
STATUS_ON_TRACK = "OnTrack"
STATUS_OFF_TRACK = "OffTrack"
STATUS_PIT = "Pit"

# TimingData numeric Status is a bitfield.
TIMING_ST_IN_PIT = 0x0008
TIMING_ST_OUT_PIT = 0x0020
TIMING_ST_STOPPED = 0x0080
TIMING_ST_RETIRED = 0x0100

# TrackStatus codes from the current feed.
TRACK_STATUS = {
    "1": ("AllClear", "GREEN", "AllClear"),
    "2": ("Yellow", "YELLOW", "Yellow"),
    "3": ("Unknown", "UNKNOWN", "Unknown"),
    "4": ("SafetyCar", "SAFETY CAR", "SafetyCar"),
    "5": ("Red", "RED", "Red"),
    "6": ("VSC", "VSC", "VirtualSafetyCar"),
    "7": ("VSCEnding", "VSC ENDING", "VirtualSafetyCarEnding"),
}

# RaceControlMessages Flag -> (label, severity)
FLAG_SEVERITY = {
    "YELLOW": ("YELLOW", 2),
    "DOUBLE YELLOW": ("DOUBLE YELLOW", 2),
    "CLEAR": ("CLEAR", 0),
    "GREEN": ("GREEN", 0),
    "RED": ("RED FLAG", 4),
    "SC": ("SAFETY CAR", 3),
    "VSC": ("VSC", 3),
    "VSC ENDING": ("VSC ENDING", 2),
    "YELLOW RED": ("YELLOW / RED", 4),
    "CHEQUERED": ("CHEQUERED", 0),
    "LIGHT BLUE": ("LIGHT BLUE", 1),
    "PURPLE": ("PURPLE", 2),
    "UNKNOWN": ("UNKNOWN", 2),
}

SESSION_LABEL = {
    "Practice": "PRACTICE",
    "Qualifying": "QUALIFYING",
    "Sprint Qualifying": "SPRINT SHOOTOUT",
    "Sprint": "SPRINT",
    "Race": "RACE",
    "Test": "TESTING",
    "Unknown": "SESSION",
}


def _num(value, default=None):
    try:
        f = float(value)
        return default if math.isnan(f) else f
    except (TypeError, ValueError):
        return default


def parse_gap(text):
    """'+1.842' -> 1.842; '1:02.345' -> 62.345; leader/'' -> None."""
    if not text or not isinstance(text, str):
        return None
    text = text.strip()
    if not text or text in ("-", "--"):
        return None
    if text.startswith("+"):
        # "+" is only ever decoration on this feed. "-" is meaningful: it is
        # how a car time ahead of the reference is reported, so the sign stays.
        text = text[1:]
    if ":" in text:
        parts = text.split(":")
        try:
            return sum(float(p) * (60 ** i) for i, p in enumerate(reversed(parts)))
        except ValueError:
            return None
    return _num(text)


def _parse_iso(text):
    if not text or not isinstance(text, str):
        return None
    t = text.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class Driver:
    __slots__ = (
        "id", "number", "tla", "full_name", "team", "colour",
        "position", "gap", "interval", "tyre", "tyre_age", "pit_status",
        "retired", "stopped", "last_lap", "best_lap", "sectors",
        "speed", "x", "y", "z", "pos_status", "pos_timestamp", "pos_age",
        "penalties", "drs_allowed", "grid", "throttle", "brake", "new_tyre",
    )

    def __init__(self, driver_id: str):
        self.id = driver_id
        self.number = ""
        self.tla = ""
        self.full_name = ""
        self.team = ""
        self.colour = ""
        self.position = None
        self.gap = None
        self.interval = None
        self.tyre = ""
        self.tyre_age = 0
        self.pit_status = ""
        self.retired = False
        self.stopped = False
        self.last_lap = ""
        self.best_lap = ""
        self.sectors = []
        self.speed = None
        self.x = None
        self.y = None
        self.z = None
        self.pos_status = ""
        self.pos_timestamp = ""
        self.pos_age = None
        self.penalties = []
        self.drs_allowed = None
        self.grid = 0
        self.throttle = None
        self.brake = None
        self.new_tyre = False

    @property
    def has_position(self) -> bool:
        return self.x is not None and self.y is not None

    def label(self) -> str:
        return self.tla or self.full_name or str(self.number or self.id)


class LiveState:
    """Everything the UI needs for one session, plus a monotonic revision."""

    def __init__(self):
        self.revision = 0
        self.connected = False
        self.mode = "offline"          # offline | idle | live | replay
        self.session_type = ""
        self.session_name = ""
        self.session_status = ""       # Started / Suspended / Finalised / Aborted
        self.meeting_name = ""
        self.official_name = ""
        self.circuit_key = ""
        self.circuit_short = ""
        self.country = ""
        self.gp = ""
        self.total_laps = 0
        self.current_lap = 0
        self.track_status = ""
        self.track_status_detail = ""
        self.track_flag = "AllClear"
        self.air_temp = ""
        self.track_temp = ""
        self.rainfall = ""
        self.humidity = ""
        self.wind_speed = ""
        self.drivers: dict[str, Driver] = {}
        self.race_control: list[dict] = []
        self.series: dict = {}
        self.status_series: dict = {}
        self.last_message_at = 0.0
        self.session_start = None
        self.error = ""

    # ------------------------------------------------------------------ input
    def _driver(self, driver_id: str) -> Driver:
        d = self.drivers.get(driver_id)
        if d is None:
            d = Driver(str(driver_id))
            self.drivers[str(driver_id)] = d
        return d

    def apply_driver_list(self, data):
        if not isinstance(data, dict):
            return
        for did, raw in data.items():
            if not isinstance(raw, dict):
                continue
            d = self._driver(str(did))
            d.number = str(raw.get("RacingNumber", d.number))
            d.tla = str(raw.get("Tla", d.tla))
            d.full_name = str(raw.get("FullName", d.full_name))
            d.team = str(raw.get("TeamName", d.team))
            # F1 publishes its own hex per car, so nothing is hard-coded and a
            # new livery needs no plugin change. A missing value must stay
            # empty: a bare "#" would parse as an invalid colour.
            hex_value = str(raw.get("TeamColour") or "").strip().lstrip("#")
            d.colour = ("#" + hex_value) if re.fullmatch(r"[0-9A-Fa-f]{6}", hex_value) else ""
        self.revision += 1

    def apply_session_info(self, data):
        if not isinstance(data, dict):
            return
        meeting = data.get("Meeting") or {}
        if meeting:
            self.meeting_name = meeting.get("Name", "") or self.meeting_name
            self.official_name = meeting.get("OfficialName", "") or self.official_name
            circuit = meeting.get("Circuit") or {}
            self.circuit_short = circuit.get("ShortName", "") or self.circuit_short
            country = meeting.get("Country") or {}
            self.country = country.get("Code", "") or self.country
        self.session_type = data.get("Type", "") or self.session_type
        self.session_name = data.get("Name", "") or self.session_name
        self.session_status = data.get("SessionStatus", "") or self.session_status
        self.session_start = _parse_iso(data.get("StartDate")) or self.session_start
        self.revision += 1

    def apply_session_data(self, data):
        if not isinstance(data, dict):
            return
        for row in data.get("Series") or []:
            if isinstance(row, dict) and row.get("Utc"):
                self.series[row["Utc"]] = row.get("S", "")
        for row in data.get("StatusSeries") or []:
            if isinstance(row, dict) and row.get("Utc"):
                self.status_series[row["Utc"]] = row.get("S", "")
        self.revision += 1

    def apply_track_status(self, data):
        if not isinstance(data, dict):
            return
        code = str(data.get("Status", ""))
        label, _flag, detail = TRACK_STATUS.get(code, ("UNKNOWN", "Unknown", ""))
        self.track_status = data.get("Message", label) or label
        self.track_flag = detail
        self.track_status_detail = label
        self.revision += 1

    def apply_lap_count(self, data):
        if not isinstance(data, dict):
            return
        self.current_lap = int(_num(data.get("CurrentLap"), self.current_lap) or 0)
        self.total_laps = int(_num(data.get("TotalLaps"), self.total_laps) or 0)
        self.revision += 1

    def apply_weather(self, data):
        if not isinstance(data, dict):
            return
        self.air_temp = str(data.get("AirTemp", ""))
        self.track_temp = str(data.get("TrackTemp", ""))
        self.rainfall = str(data.get("Rainfall", ""))
        self.humidity = str(data.get("Humidity", ""))
        self.wind_speed = str(data.get("WindSpeed", ""))
        self.revision += 1

    def apply_position(self, sample) -> None:
        for did, raw in sample.entries.items():
            if not isinstance(raw, dict):
                continue
            x, y = _num(raw.get("X")), _num(raw.get("Y"))
            d = self._driver(str(did))
            d.pos_status = str(raw.get("Status", ""))
            d.pos_timestamp = sample.timestamp
            # Some sessions emit sentinel coordinates for cars that are no
            # longer on the circuit. Keep those out of the map entirely rather
            # than plotting a bogus point at the edge of the frame.
            if x is None or y is None or abs(x) > 20000 or abs(y) > 20000:
                d.x = d.y = d.z = None
            else:
                d.x, d.y, d.z = int(x), int(y), _num(raw.get("Z"), 0.0)
        self.revision += 1

    def apply_timing(self, data):
        if not isinstance(data, dict):
            return
        lines = data.get("Lines") or {}
        for did, raw in lines.items():
            if not isinstance(raw, dict):
                continue
            d = self._driver(str(did))
            pos = _num(raw.get("Position"))
            if pos is not None:
                d.position = int(pos)
            d.gap = parse_gap(raw.get("GapToLeader")) or d.gap
            ahead = raw.get("IntervalToPositionAhead") or {}
            if isinstance(ahead, dict):
                d.interval = parse_gap(ahead.get("Value"))
            status = int(_num(raw.get("Status"), 0) or 0)
            d.retired = bool(status & TIMING_ST_RETIRED) or bool(raw.get("Retired"))
            d.stopped = bool(status & TIMING_ST_STOPPED)
            if status & TIMING_ST_IN_PIT:
                d.pit_status = "PIT"
            elif status & TIMING_ST_OUT_PIT:
                d.pit_status = "PIT OUT"
            elif raw.get("InPit"):
                d.pit_status = "PIT"
            else:
                d.pit_status = ""
            ll = raw.get("LastLapTime") or {}
            if isinstance(ll, dict) and ll.get("Value"):
                d.last_lap = ll["Value"]
            bl = raw.get("BestLapTime") or {}
            if isinstance(bl, dict) and bl.get("Value"):
                d.best_lap = bl["Value"]
            sectors = []
            for s in raw.get("Sectors") or []:
                if isinstance(s, dict):
                    sectors.append(
                        {
                            "value": s.get("Value", ""),
                            "personal": bool(s.get("PersonalFastest")),
                            "overall": bool(s.get("OverallFastest")),
                        }
                    )
            d.sectors = sectors
            speeds = raw.get("Speeds") or {}
            if isinstance(speeds, dict):
                for key in ("FL", "ST", "I1", "I2"):
                    if key in speeds and isinstance(speeds[key], dict):
                        d.speed = _num(speeds[key].get("Value"), d.speed)
                        break
        self.revision += 1

    def apply_timing_app(self, data):
        """Tyres, grid slots and lap flags live in TimingAppData, not TimingData.

        The current stint is the last entry of Stints, so its Compound is what
        the car is on now and TotalLaps is the age of that tyre.
        """
        if not isinstance(data, dict):
            return
        for did, raw in (data.get("Lines") or {}).items():
            if not isinstance(raw, dict):
                continue
            d = self._driver(str(did))
            if raw.get("RacingNumber"):
                d.number = str(raw["RacingNumber"])
            grid = _num(raw.get("GridPos"))
            if grid is not None:
                d.grid = int(grid)
            stints = raw.get("Stints")
            if isinstance(stints, list) and stints:
                last = stints[-1]
                if isinstance(last, dict):
                    compound = str(last.get("Compound") or "").strip()
                    if compound:
                        d.tyre = compound
                    age = _num(last.get("TotalLaps"))
                    if age is not None:
                        d.tyre_age = int(age)
                    d.new_tyre = str(last.get("New", "")).lower() == "true"
        self.revision += 1

    def apply_car_data(self, data):
        """Throttle and brake per car from CarData.z.

        Channel 0 is throttle and 4 is brake on the current feed; both are
        0-255. Purely decorative in the UI, but it is the one topic that makes
        a live timing tower feel alive, and it costs one subscription.
        """
        if not isinstance(data, dict):
            return
        for block in data.get("Entries") or []:
            if not isinstance(block, dict):
                continue
            for key, car in (block.get("Cars") or {}).items():
                if not isinstance(car, dict):
                    continue
                chans = car.get("Channels") or {}
                d = self._driver(str(key))
                thr = _num(chans.get("0"))
                brk = _num(chans.get("4"))
                if thr is not None:
                    d.throttle = max(0, min(255, int(thr)))
                if brk is not None:
                    d.brake = max(0, min(255, int(brk)))
        self.revision += 1

    def apply_race_control(self, data):
        if not isinstance(data, dict):
            return
        messages = data.get("Messages")
        if isinstance(messages, list):
            self.race_control = [m for m in messages if isinstance(m, dict)]
        elif isinstance(messages, dict):
            self.race_control.append(messages)
        self.revision += 1

    # ----------------------------------------------------------------- output
    def age_positions(self, now: float | None = None) -> None:
        """Stamp how stale each marker is, in seconds. Never fabricates."""
        now = now or time.time()
        for d in self.drivers.values():
            if not d.pos_timestamp:
                d.pos_age = None
                continue
            dt = _parse_iso(d.pos_timestamp)
            if dt is None:
                d.pos_age = None
                continue
            d.pos_age = max(0.0, now - dt.timestamp())

    def classification(self) -> list[Driver]:
        """Drivers in race order: classified positions first, then the rest."""
        listed = [d for d in self.drivers.values() if d.position]
        rest = [d for d in self.drivers.values() if not d.position]
        listed.sort(key=lambda d: d.position)
        # Racing numbers arrive as strings; sorting them as strings would put
        # "10" before "4" and, worse, a non-numeric number cannot be negated.
        rest.sort(key=lambda d: _num(d.number, 0) or 0)
        return listed + rest

    def leaderboard(self) -> list[Driver]:
        """Cars with a live classification, i.e. what the timing tower shows."""
        out = [d for d in self.classification() if d.position and d.number]
        return out

    def cars_with_position(self) -> list[Driver]:
        return [d for d in self.classification() if d.has_position and d.number]

    def is_live(self) -> bool:
        return self.session_status.lower() in ("started", "suspended", "active")

    def session_label(self) -> str:
        return SESSION_LABEL.get(self.session_type, (self.session_type or "SESSION").upper())

    def to_dict(self) -> dict:
        """The exact contract the QML layer consumes."""
        drivers = []
        for d in self.leaderboard():
            drivers.append(
                {
                    "id": d.id,
                    "number": d.number,
                    "tla": d.tla,
                    "name": d.full_name,
                    "team": d.team,
                    "colour": d.colour,
                    "position": d.position or 0,
                    "gap": d.gap,
                    "interval": d.interval,
                    "tyre": d.tyre,
                    "tyreAge": d.tyre_age,
                    "pit": d.pit_status,
                    "retired": d.retired,
                    "stopped": d.stopped,
                    "lastLap": d.last_lap,
                    "bestLap": d.best_lap,
                    "sectors": d.sectors,
                    "speed": d.speed,
                    "x": d.x,
                    "y": d.y,
                    "z": d.z,
                    "posStatus": d.pos_status,
                    "posAge": round(d.pos_age, 2) if d.pos_age is not None else None,
                    "hasPosition": d.has_position,
                    "grid": d.grid,
                    "throttle": d.throttle,
                    "brake": d.brake,
                    "newTyre": d.new_tyre,
                    "penalties": d.penalties,
                }
            )
        return {
            "revision": self.revision,
            "mode": self.mode,
            "connected": self.connected,
            "session": self.session_type,
            "sessionLabel": self.session_label(),
            "sessionStatus": self.session_status,
            "sessionName": self.session_name,
            "meeting": self.meeting_name,
            "officialName": self.official_name,
            "circuit": self.circuit_short,
            "country": self.country,
            "lap": self.current_lap,
            "totalLaps": self.total_laps,
            "trackStatus": self.track_status,
            "trackFlag": self.track_flag,
            "airTemp": self.air_temp,
            "trackTemp": self.track_temp,
            "rainfall": self.rainfall,
            "humidity": self.humidity,
            "windSpeed": self.wind_speed,
            "isLive": self.is_live(),
            "drivers": drivers,
            "raceControl": self.race_control[-40:][::-1],
        }

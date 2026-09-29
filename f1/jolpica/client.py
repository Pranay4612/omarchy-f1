"""Free historical / championship data.

Source: Jolpica (the Ergast successor) at https://api.jolpi.ca/ergast/f1/.
It is a volunteer-run public mirror: no key, no account, nothing to buy.
Everything here is championship context -- calendar, standings, past results,
driver and circuit metadata -- never live telemetry.

Live timing never comes from here. See f1/live/ for that.

Endpoint shapes were re-verified against the live service on 2026-09-29:
the older ``/drivers/championship/standings.json`` paths now 404 and the
flat ``/driverStandings.json`` form is the one that works.
"""

from __future__ import annotations

import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

BASE = "https://api.jolpi.ca/ergast/f1"
UA = "f1-omarchy/1.0 (personal local desktop plugin)"

_R = 6371000.0


class JolpicaError(RuntimeError):
    pass


def _get(path: str, params: dict | None = None, timeout: float = 20.0) -> dict:
    url = f"{BASE}/{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        raise JolpicaError(f"{path} -> HTTP {exc.code}") from exc


def season_now() -> int:
    return datetime.now(timezone.utc).year


# --------------------------------------------------------------------- calendar
def races(season: int | None = None) -> list[dict]:
    # Without an explicit season Jolpica happily returns every race since 1950,
    # which is not what a calendar widget wants. The season has to be in the
    # path: as a query parameter it is silently ignored (verified 2026-09-29).
    season = season or season_now()
    data = _get(f"{season}/races.json", {"limit": 100})
    rows = (data.get("MRData", {}).get("RaceTable", {}) or {}).get("Races", []) or []
    out = []
    for r in rows:
        circuit = r.get("Circuit") or {}
        loc = circuit.get("Location") or {}
        out.append(
            {
                "round": str(r.get("round", "")),
                "season": str(r.get("season", season or "")),
                "name": r.get("raceName", ""),
                "officialName": r.get("officialName", ""),
                "date": r.get("date", ""),
                "time": r.get("time", ""),
                "circuitId": circuit.get("circuitId", ""),
                "circuitName": circuit.get("circuitName", ""),
                "lat": _f(loc.get("lat")),
                "lon": _f(loc.get("long")),
                "locality": loc.get("locality", ""),
                "country": loc.get("country", ""),
                "sessions": _sessions(r),
            }
        )
    out.sort(key=lambda r: start_utc(r) or datetime.max.replace(tzinfo=timezone.utc))
    return out


def _sessions(race_row: dict) -> list[dict]:
    mapping = {
        "FirstPractice": "Practice 1",
        "SecondPractice": "Practice 2",
        "ThirdPractice": "Practice 3",
        "Qualifying": "Qualifying",
        "SprintQualifying": "Sprint Qualifying",
        "Sprint": "Sprint",
    }
    out = []
    for key, label in mapping.items():
        block = race_row.get(key)
        if not isinstance(block, dict):
            continue
        out.append({"key": key, "label": label, "date": block.get("date", ""), "time": block.get("time", "")})
    return out


def _f(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def start_utc(race: dict):
    date = race.get("date")
    if not date:
        return None
    t = race.get("time") or "00:00:00Z"
    if len(t) == 5:
        t += ":00Z"
    t = t.replace("Z", "")
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.fromisoformat(f"{date}T{t}").replace(tzinfo=timezone.utc)
        except ValueError:
            try:
                return datetime.strptime(f"{date}T{t}", fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return None


def next_race(all_races: list[dict] | None = None) -> dict | None:
    all_races = all_races if all_races is not None else races()
    now = datetime.now(timezone.utc)
    for r in all_races:
        s = start_utc(r)
        # A race that started within the last few hours is still "the race
        # weekend", which is what the user wants to see.
        if s and s >= now - timedelta(hours=8):
            return r
    return all_races[-1] if all_races else None


def previous_race(all_races: list[dict] | None = None) -> dict | None:
    all_races = all_races if all_races is not None else races()
    now = datetime.now(timezone.utc)
    done = [r for r in all_races if (s := start_utc(r)) and s < now - timedelta(hours=8)]
    return done[-1] if done else None


# -------------------------------------------------------------------- standings
def driver_standings(season: int | None = None) -> list[dict]:
    path = f"{season}/driverStandings.json" if season else "current/driverStandings.json"
    data = _get(path, {"limit": 40})
    table = data.get("MRData", {}).get("StandingsTable", {}) or {}
    lists = table.get("StandingsLists") or []
    rows = (lists[0].get("DriverStandings") if lists else []) or []
    out = []
    for s in rows:
        d = s.get("Driver") or {}
        cons = s.get("Constructors") or []
        team = cons[0] if cons else {}
        out.append(
            {
                "position": _i(s.get("position")),
                "points": _f(s.get("points")) or 0.0,
                "wins": _i(s.get("wins")),
                "driverId": d.get("driverId", ""),
                "code": d.get("code", ""),
                "name": f"{d.get('givenName','')} {d.get('familyName','')}".strip(),
                "nationality": d.get("nationality", ""),
                "team": team.get("name", ""),
                "teamId": team.get("constructorId", ""),
            }
        )
    out.sort(key=lambda d: d["position"])
    return out


def constructor_standings(season: int | None = None) -> list[dict]:
    path = f"{season}/constructorStandings.json" if season else "current/constructorStandings.json"
    data = _get(path, {"limit": 40})
    table = data.get("MRData", {}).get("StandingsTable", {}) or {}
    lists = table.get("StandingsLists") or []
    rows = (lists[0].get("ConstructorStandings") if lists else []) or []
    out = []
    for s in rows:
        c = s.get("Constructor") or {}
        out.append(
            {
                "position": _i(s.get("position")),
                "points": _f(s.get("points")) or 0.0,
                "wins": _i(s.get("wins")),
                "constructorId": c.get("constructorId", ""),
                "name": c.get("name", ""),
                "nationality": c.get("nationality", ""),
            }
        )
    out.sort(key=lambda d: d["position"])
    return out


def _i(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


# --------------------------------------------------------------------- results
def race_results(season: int, round_no: str) -> list[dict]:
    data = _get(f"{season}/{round_no}/results.json", {"limit": 40})
    rows = (data.get("MRData", {}).get("RaceTable", {}) or {}).get("Races", []) or []
    out = []
    for race in rows:
        for r in race.get("Results") or []:
            d = r.get("Driver") or {}
            tl = r.get("Time") or {}
            fl = (r.get("FastestLap") or {}).get("Time") or {}
            out.append(
                {
                    "position": r.get("position", ""),
                    "grid": r.get("grid", ""),
                    "number": r.get("number", ""),
                    "code": d.get("code", ""),
                    "name": f"{d.get('givenName','')} {d.get('familyName','')}".strip(),
                    "laps": r.get("laps", ""),
                    "status": r.get("status", ""),
                    "team": (r.get("Constructor") or {}).get("name", ""),
                    "time": _seconds(tl.get("millis")),
                    "fastestLap": _seconds(fl.get("millis")),
                }
            )
    out.sort(key=lambda r: _i(r["position"]) or 999)
    return out


def qualifying_results(season: int, round_no: str) -> list[dict]:
    data = _get(f"{season}/{round_no}/qualifying.json", {"limit": 40})
    rows = (data.get("MRData", {}).get("QualifyingTable", {}) or {}).get("Races", []) or []
    out = []
    for race in rows:
        for r in race.get("QualifyingResults") or []:
            d = r.get("Driver") or {}
            entry = {
                "position": r.get("position", ""),
                "number": r.get("number", ""),
                "code": d.get("code", ""),
                "name": f"{d.get('givenName','')} {d.get('familyName','')}".strip(),
                "team": (r.get("Constructor") or {}).get("name", ""),
            }
            for q in r.get("QualifyingResults") or []:
                entry[str(q.get("number", ""))] = q.get("Time", "")
            out.append(entry)
    out.sort(key=lambda r: _i(r["position"]) or 999)
    return out


def sprint_results(season: int, round_no: str) -> list[dict]:
    """Empty list for weekends with no sprint -- that is normal, not an error."""
    try:
        data = _get(f"{season}/{round_no}/sprint.json", {"limit": 40})
    except (JolpicaError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return []
    rows = (data.get("MRData", {}).get("SprintTable", {}) or {}).get("Races", []) or []
    out = []
    for race in rows:
        for r in race.get("SprintResults") or []:
            d = r.get("Driver") or {}
            out.append(
                {
                    "position": r.get("position", ""),
                    "number": r.get("number", ""),
                    "code": d.get("code", ""),
                    "name": f"{d.get('givenName','')} {d.get('familyName','')}".strip(),
                    "team": (r.get("Constructor") or {}).get("name", ""),
                }
            )
    out.sort(key=lambda r: _i(r["position"]) or 999)
    return out


def _seconds(millis):
    value = _f(millis)
    return value / 1000.0 if value else ""


# -------------------------------------------------------------------- circuits
def circuits() -> list[dict]:
    data = _get("circuits.json", {"limit": 100})
    rows = (data.get("MRData", {}).get("CircuitTable", {}) or {}).get("Circuits", []) or []
    out = []
    for c in rows:
        loc = c.get("Location") or {}
        out.append(
            {
                "circuitId": c.get("circuitId", ""),
                "name": c.get("circuitName", ""),
                "lat": _f(loc.get("lat")),
                "lon": _f(loc.get("long")),
                "locality": loc.get("locality", ""),
                "country": loc.get("country", ""),
            }
        )
    return out


def drivers(season: int | None = None) -> list[dict]:
    path = f"{season}/drivers.json" if season else "drivers.json"
    data = _get(path, {"limit": 60})
    rows = (data.get("MRData", {}).get("DriverTable", {}) or {}).get("Drivers", []) or []
    out = []
    for d in rows:
        out.append(
            {
                "driverId": d.get("driverId", ""),
                "number": str(d.get("permanentNumber", "")),
                "code": d.get("code", ""),
                "name": f"{d.get('givenName','')} {d.get('familyName','')}".strip(),
                "nationality": d.get("nationality", ""),
            }
        )
    return out


def local_xy(lat: float, lon: float, lat0: float, lon0: float) -> tuple[float, float]:
    """Flat-earth metres around a reference point.

    Circuits span a few degrees at most, so the equirectangular approximation
    is accurate to well under a metre here -- far finer than a track outline
    needs, and it keeps the project dependency-free.
    """
    return (
        math.radians(lon - lon0) * _R * math.cos(math.radians(lat0)),
        math.radians(lat - lat0) * _R,
    )

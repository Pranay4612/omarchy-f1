"""The local F1 service: one process, one connection, one state.

This is the only thing that talks to Formula 1. The QML layer reads the
normalised snapshot this writes and never opens a socket of its own, so the
bar widget and the panel cannot disagree and the plugin cannot accidentally
hold two live connections.

Responsibilities:
  * session detection (is anything running, and what kind);
  * the single SignalR connection, with backoff and reconnect;
  * decoding and normalising the feed into f1/live/state.LiveState;
  * learning each circuit's outline from the position samples it sees;
  * championship context from Jolpica when nothing is live;
  * publishing an atomically-replaced snapshot for the UI.

Idle behaviour matters here: with no session running the service does not
hold a live connection at all. It polls the lightweight static index, and only
opens the stream when the index shows a session in progress or imminent.

Own lifetime matters just as much. The marketplace installs plugins by cloning
this directory and removes them by deleting it, without ever running anything
in here. A service that outlived its own directory would keep polling two
third-party endpoints for as long as the session lasted, from a copy of itself
that no longer exists. So the service watches the directory it was loaded from
and, when it goes away, closes its connection, clears the cache it owns and
exits. That is the whole of its removal story: no systemd unit, no daemon, no
supervisor, nothing that has to be undone by hand.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from . import cache, curve
from .jolpica import client as jolpica
from .live.decoder import decode_position_payload, decode_topic_payload
from .live.signalr import SignalRClient
from .live.state import LiveState

UA = "f1-omarchy/1.0 (personal local desktop plugin)"
STATIC_BASE = "https://livetiming.formula1.com/static"

# Poll the static index this often. It is a couple of kB and it is the only
# cheap way to know whether a session exists at all.
IDLE_POLL_SEC = 180
NEAR_SESSION_SEC = 900
# Rebuild the outline this often while a session runs. A few hundred to a few
# thousand samples, 2-opt included, is well under a second.
OUTLINE_REFRESH_SEC = 25

# How often the service checks that it still exists. Removal has to feel
# prompt, and a stat() every few seconds is free.
LIFETIME_CHECK_SEC = 5.0

# The directory this module was loaded from: the plugin root. If it stops
# existing, the plugin has been removed and this process has outlived its
# purpose. Resolved once, at import, because after removal the __file__ path
# no longer resolves to anything.
PLUGIN_ROOT = Path(__file__).resolve().parent.parent


def _now() -> float:
    return time.time()


def _http_json(url: str, timeout: float = 15.0):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8-sig"))


class F1Service:
    def __init__(self, log=print, replay=None):
        self.log = log
        self.replay = replay
        self.state = LiveState()
        self.state.mode = "replay" if replay else "offline"
        self.running = False
        self.thread = None
        self._lock = threading.Lock()
        self._client = None
        self._connected = False
        self._backoff = 2.0
        self._last_publish = 0.0
        self._last_state_write = 0.0
        self._samples: list[tuple[float, float]] = []
        self._circuit_key = ""
        self._last_outline = 0.0
        self._outline_key = ""
        self._session_seen_at = 0.0
        self._index = None
        self._index_checked = 0.0
        self._champ = {}
        self._champ_at = 0.0
        self._lifetime = None

    # ------------------------------------------------------------------ utils
    def _say(self, msg: str):
        try:
            self.log(f"[f1] {msg}")
        except Exception:
            pass

    # ------------------------------------------------------------------- life
    def start(self):
        if self.running:
            return
        self.running = True
        cache.ensure_dirs()
        self._load_cached_state()
        self.thread = threading.Thread(target=self._run, name="f1-service", daemon=True)
        self.thread.start()
        self._lifetime = threading.Thread(
            target=self._watch_lifetime, name="f1-lifetime", daemon=True
        )
        self._lifetime.start()
        self._say("service started")

    # ------------------------------------------------------------- lifetime
    def _watch_lifetime(self) -> None:
        """Exit when the plugin this service was loaded from is removed.

        `omarchy plugin remove` deletes the plugin directory and does not run
        anything from inside it, so nothing in the plugin can be told to stop.
        Checking our own origin directory is the only signal available, and it
        is an unambiguous one: a live plugin's directory does not vanish.

        Exit is 0 and deliberate. Anything else would look like a crash to the
        shell's crash handler, which offers the user a diagnosis for a
        non-problem.
        """
        while self.running:
            time.sleep(LIFETIME_CHECK_SEC)
            if self.running and not _plugin_still_installed():
                self._say("plugin directory is gone; shutting down")
                self._shutdown_after_removal()
                return

    def _shutdown_after_removal(self) -> None:
        self.running = False
        client, self._client = self._client, None
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
        _remove_own_cache(self._say)
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(0)

    def stop(self):
        self.running = False
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None

    def _run(self):
        if self.replay:
            self._run_replay()
            return
        while self.running:
            try:
                if self._index_has_session():
                    self._run_live()
                else:
                    self._run_idle()
            except Exception as exc:  # noqa: BLE001 - the service must not die
                self._say(f"error: {type(exc).__name__}: {exc}")
                self.state.error = str(exc)
            if self.running:
                time.sleep(min(self._backoff, 30.0))

    # -------------------------------------------------------------- idle path
    def _run_idle(self):
        self._connected = False
        with self._lock:
            self.state.mode = "idle"
            self.state.connected = False
        self._say("no session in the feed; idle")
        self._refresh_championship(force=True)
        self._publish()
        # Sleep in slices so stop() is responsive without spinning.
        deadline = _now() + IDLE_POLL_SEC
        while self.running and _now() < deadline:
            time.sleep(1.0)
        self._backoff = 2.0
        self._index_checked = 0.0

    def _index_has_session(self) -> bool:
        """True when the static index shows a session running or about to run."""
        if self.replay:
            return True
        if _now() - self._index_checked < IDLE_POLL_SEC:
            return self._session_seen_at > 0
        self._index_checked = _now()
        try:
            index = _http_json(f"{STATIC_BASE}/Index.json")
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            return self._session_seen_at > 0

        years = [y.get("Path") for y in (index.get("Years") or []) if y.get("Path")]
        best = 0.0
        for yp in reversed(years[-2:]):
            try:
                idx = _http_json(f"{STATIC_BASE}{yp}Index.json")
            except (urllib.error.URLError, TimeoutError, ValueError, OSError):
                continue
            for meeting in idx.get("Meetings") or []:
                for s in meeting.get("Sessions") or []:
                    start = _parse_dt(s.get("StartDate"))
                    end = _parse_dt(s.get("EndDate"))
                    if not start or not end:
                        continue
                    start_ts, end_ts = start.timestamp(), end.timestamp()
                    t = _now()
                    if start_ts - NEAR_SESSION_SEC <= t <= end_ts + 3600:
                        best = max(best, end_ts)
        self._index = index
        self._session_seen_at = best
        if best:
            self._say("session window detected; connecting")
        return best > 0

    # -------------------------------------------------------------- live path
    def _run_live(self):
        self._refresh_championship(force=False)
        client = SignalRClient(logger=self._say)
        self._client = client
        try:
            client.connect()
        except Exception as exc:  # noqa: BLE001
            self._say(f"connect failed: {type(exc).__name__}: {exc}")
            self._connected = False
            self._backoff = min(self._backoff * 2, 60.0)
            time.sleep(min(self._backoff, 30.0))
            return
        self._connected = True
        self._backoff = 2.0
        with self._lock:
            self.state.mode = "live"
            self.state.connected = True
        try:
            client.subscribe_default()
        except Exception as exc:  # noqa: BLE001
            self._say(f"subscribe failed: {exc}")

        last = _now()
        while self.running and self._connected:
            got_any = False
            for topic, payload in client.messages():
                if not self.running:
                    break
                got_any = True
                self._ingest(topic, payload)
                now = _now()
                if now - self._last_publish > 0.1:
                    self._publish()
                    self._last_publish = now
                if now - self._last_outline > OUTLINE_REFRESH_SEC:
                    self._last_outline = now
                    self._maybe_build_outline()
            if not got_any:
                # No traffic at all for a while: the session is probably over.
                if _now() - last > 900:
                    self._say("no traffic for 15 min; standing down")
                    break
            last = _now()
        self._connected = False
        self._finalise()

    def _finalise(self):
        with self._lock:
            self.state.connected = False
            self.state.mode = "idle"
        self._maybe_build_outline(force=True)
        self._publish()

    def _ingest(self, topic: str, payload):
        s = self.state
        with self._lock:
            if topic == "DriverList":
                s.apply_driver_list(decode_topic_payload(payload))
            elif topic == "SessionInfo":
                s.apply_session_info(decode_topic_payload(payload))
            elif topic == "SessionData":
                s.apply_session_data(decode_topic_payload(payload))
            elif topic == "TrackStatus":
                s.apply_track_status(decode_topic_payload(payload))
            elif topic == "LapCount":
                s.apply_lap_count(decode_topic_payload(payload))
            elif topic == "WeatherData":
                s.apply_weather(decode_topic_payload(payload))
            elif topic == "TimingData":
                s.apply_timing(decode_topic_payload(payload))
            elif topic == "TimingAppData":
                s.apply_timing_app(decode_topic_payload(payload))
            elif topic == "CarData.z":
                s.apply_car_data(decode_topic_payload(payload))
            elif topic == "RaceControlMessages":
                s.apply_race_control(decode_topic_payload(payload))
            elif topic == "Position.z":
                for sample in decode_position_payload(payload):
                    s.apply_position(sample)
                    for raw in sample.entries.values():
                        if not isinstance(raw, dict):
                            continue
                        x, y = raw.get("X"), raw.get("Y")
                        if x is None or y is None:
                            continue
                        x, y = float(x), float(y)
                        if abs(x) > 20000 or abs(y) > 20000:
                            continue
                        self._samples.append((x, y))
                s.age_positions()
            s.last_message_at = _now()
            s.revision += 1
        self._track_circuit_key()

    def _track_circuit_key(self):
        s = self.state
        key = (s.circuit_short or "").strip()
        if key and key != self._circuit_key:
            if self._circuit_key:
                self._say(f"circuit {self._circuit_key} -> {key}")
            self._circuit_key = key
            self._samples = []
            self._last_outline = 0.0

    # --------------------------------------------------------------- outlines
    def _maybe_build_outline(self, force: bool = False):
        key = self._circuit_key
        if not key or len(self._samples) < 200:
            return
        if not force and _now() - self._last_outline < OUTLINE_REFRESH_SEC:
            return
        path = curve.build_outline(self._samples)
        if not path:
            return
        payload = {
            "key": key,
            "points": [[round(x, 2), round(y, 2)] for x, y in path],
            "length": round(curve.path_length(path), 1),
            "samples": len(self._samples),
            "learnedAt": int(_now()),
        }
        existing = cache.load_outline(key) or {}
        if abs(float(existing.get("length", 0)) - payload["length"]) < 12.0 and existing.get("points"):
            return
        if cache.save_outline(key, payload):
            self._say(f"learned outline for {key}: {payload['length']:.0f} m from {payload['samples']} samples")

    # ------------------------------------------------------------- championship
    def _refresh_championship(self, force: bool = False):
        if not force and _now() - self._champ_at < 3600:
            return
        self._champ_at = _now()
        champ: dict = {}
        try:
            races = jolpica.races()
            nxt = jolpica.next_race(races)
            prev = jolpica.previous_race(races)
            champ["calendar"] = races
            champ["next"] = nxt
            champ["previous"] = prev
            if prev:
                champ["previousResults"] = jolpica.race_results(
                    int(prev.get("season") or jolpica.season_now()), str(prev.get("round", ""))
                )
        except Exception as exc:  # noqa: BLE001
            self._say(f"championship/calendar unavailable: {exc}")
        try:
            champ["drivers"] = jolpica.driver_standings()
        except Exception as exc:  # noqa: BLE001
            self._say(f"driver standings unavailable: {exc}")
        try:
            champ["constructors"] = jolpica.constructor_standings()
        except Exception as exc:  # noqa: BLE001
            self._say(f"constructor standings unavailable: {exc}")
        if champ:
            self._champ = champ

    # ---------------------------------------------------------------- publish
    def _publish(self):
        with self._lock:
            self.state.age_positions()
            self.state.mode = "replay" if self.replay else ("live" if self._connected else "idle")
            snap = self.state.to_dict()
        snap["championship"] = _champ_snapshot(self._champ)
        snap["outline"] = self._outline_payload()
        cache.save_positions(snap)
        # The heavy snapshot is written less often: standings and race-control
        # history change far slower than car positions, and rewriting them at
        # telemetry rate would make the file churn pointless.
        if _now() - self._last_state_write > 1.0:
            cache.save_state(snap)
            self._last_state_write = _now()

    def _outline_payload(self):
        key = self._circuit_key
        if key:
            data = cache.load_outline(key)
            if data and data.get("points"):
                return {
                    "key": data.get("key", key),
                    "points": data.get("points"),
                    "length": data.get("length"),
                    "learnedAt": data.get("learnedAt"),
                }
        outlines = cache.list_outlines()
        if outlines:
            newest = max(outlines, key=lambda d: d.get("learnedAt", 0))
            return {
                "key": newest.get("key"),
                "points": newest.get("points"),
                "length": newest.get("length"),
                "learnedAt": newest.get("learnedAt"),
            }
        return None

    def _load_cached_state(self):
        data = cache.load_state()
        if not data:
            return
        champ = data.get("championship")
        if isinstance(champ, dict):
            self._champ = champ
        s = data.get("sessionSnapshot")
        if isinstance(s, dict):
            self.state.meeting_name = s.get("meeting", "")
            self.state.official_name = s.get("officialName", "")
            self.state.circuit_short = s.get("circuit", "")
            self.state.country = s.get("country", "")
            self.state.total_laps = s.get("totalLaps", 0) or 0
            self._circuit_key = self.state.circuit_short

    # ------------------------------------------------------------- replay mode
    def _run_replay(self):
        from .replay import run_replay

        run_replay(self, self.replay)


def _plugin_still_installed() -> bool:
    """True while the directory this process was loaded from still exists.

    Two checks, because the directory being present but empty is exactly what
    a partially-completed removal looks like: the manifest going first would
    otherwise leave the service running for the rest of the deletion.
    """
    try:
        return PLUGIN_ROOT.is_dir() and (PLUGIN_ROOT / "manifest.json").is_file()
    except OSError:
        return False


def _remove_own_cache(log=print) -> bool:
    """Delete the cache namespace this plugin owns, and nothing else.

    The guard is deliberately paranoid. A cache path is computed from
    environment variables, so a hostile or merely broken XDG_CACHE_HOME must
    not be able to turn "clear my cache" into "delete an arbitrary directory".
    Nothing is removed unless all of the following hold:

      * the resolved path is strictly inside a known cache root;
      * it is exactly that root's ``omarchy/f1`` subdirectory, by comparison of
        the resolved path rather than by string matching;
      * it is a real directory and not a symlink, so a link planted in its
        place cannot redirect the deletion somewhere else;
      * it is not the cache root itself, nor an ancestor of it.

    Returns True when something was removed.
    """
    try:
        target = cache.cache_root()
    except (OSError, TypeError, ValueError):
        return False

    try:
        base = Path(os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache"))
        base = base.expanduser()
        # The symlink test has to happen on the *unresolved* path. Resolving
        # first would follow the link, after which is_symlink() is always False
        # and a link planted at the namespace would be deleted straight
        # through, with every check below it passing.
        if target.is_symlink():
            log("refusing to clear a symlinked cache path")
            return False

        base = base.resolve()
        resolved = target.expanduser().resolve()
    except (OSError, RuntimeError, TypeError, ValueError):
        return False

    if resolved == base or base not in resolved.parents:
        log("refusing to clear cache outside a known cache root")
        return False
    if resolved.name != "f1" or resolved.parent.name != "omarchy":
        log("refusing to clear an unexpected cache path")
        return False
    if not resolved.is_dir():
        return False

    try:
        shutil.rmtree(resolved)
    except OSError as exc:
        log(f"could not clear cache: {exc}")
        return False
    log(f"cleared cache {resolved}")
    return True


def _parse_dt(text):
    if not text or not isinstance(text, str):
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _champ_snapshot(champ: dict) -> dict:
    """Trim the cache to what the UI actually draws."""
    out: dict = {}
    for key in ("drivers", "constructors", "previousResults"):
        rows = champ.get(key)
        if isinstance(rows, list):
            out[key] = rows[:30]
    nxt = champ.get("next")
    if isinstance(nxt, dict):
        out["next"] = nxt
    prev = champ.get("previous")
    if isinstance(prev, dict):
        out["previous"] = prev
    return out

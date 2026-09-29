"""Local cache for everything the plugin knows that does not change per second.

Two layers:
  * a small, human-readable state file the QML layer reads, holding the
    normalised live snapshot plus championship context;
  * a per-circuit outline store, written by the learner.

Everything lives under the user's XDG cache directory so uninstalling the
plugin leaves nothing behind elsewhere. Writes are atomic (temp file + rename)
so a crash mid-write can never leave the UI reading a half-written file.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path


def cache_root() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "omarchy" / "f1"


def state_path() -> Path:
    return cache_root() / "state.json"


def positions_path() -> Path:
    """High-rate, small: just where the cars are.

    Split from the main snapshot so the track map can redraw at ~10 Hz without
    re-reading and re-parsing the standings and race-control history 10 times
    a second.
    """
    return cache_root() / "positions.json"


def circuits_dir() -> Path:
    return cache_root() / "circuits"


def captures_dir() -> Path:
    return cache_root() / "captures"


def ensure_dirs() -> None:
    for d in (cache_root(), circuits_dir(), captures_dir()):
        d.mkdir(parents=True, exist_ok=True)


def write_atomic(path: Path, data: str) -> bool:
    """Atomic replace. Returns True on success."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
            return True
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except OSError:
        return False


def read_json(path: Path, max_bytes: int = 8 * 1024 * 1024):
    try:
        st = path.stat()
        if st.st_size > max_bytes or not path.is_file():
            return None
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def save_state(snapshot: dict) -> bool:
    snapshot = dict(snapshot)
    snapshot["savedAt"] = int(time.time())
    return write_atomic(state_path(), json.dumps(snapshot, separators=(",", ":")))


def save_positions(snapshot: dict) -> bool:
    drivers = []
    for d in snapshot.get("drivers") or []:
        if not d.get("hasPosition"):
            continue
        drivers.append(
            [d.get("id"), d.get("number"), d.get("tla"), d.get("colour"),
             d.get("x"), d.get("y"), d.get("posAge"), d.get("position")]
        )
    payload = {
        "revision": snapshot.get("revision", 0),
        "circuit": snapshot.get("circuit", ""),
        "trackStatus": snapshot.get("trackStatus", ""),
        "trackFlag": snapshot.get("trackFlag", ""),
        "writtenAt": int(time.time() * 1000),
        "drivers": drivers,
    }
    return write_atomic(positions_path(), json.dumps(payload, separators=(",", ":")))


def load_positions():
    return read_json(positions_path(), max_bytes=512 * 1024)


def load_state(max_age: float | None = None):
    data = read_json(state_path())
    if not isinstance(data, dict):
        return None
    if max_age is not None:
        saved = data.get("savedAt", 0)
        if not saved or (time.time() - saved) > max_age:
            return None
    return data


# ------------------------------------------------------------------ outlines
def outline_path(key: str) -> Path:
    safe = "".join(c for c in str(key) if c.isalnum() or c in "-_").lower()
    return circuits_dir() / f"{safe or 'unknown'}.json"


def save_outline(key: str, payload: dict) -> bool:
    return write_atomic(outline_path(key), json.dumps(payload, separators=(",", ":")))


def load_outline(key: str):
    return read_json(outline_path(key), max_bytes=2 * 1024 * 1024)


def list_outlines() -> list[dict]:
    out = []
    try:
        for p in sorted(circuits_dir().glob("*.json")):
            data = read_json(p, max_bytes=2 * 1024 * 1024)
            if isinstance(data, dict):
                out.append(data)
    except OSError:
        pass
    return out

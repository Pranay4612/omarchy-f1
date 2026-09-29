"""Topic payload decoding for the F1 live timing feed.

Wire formats seen on the current (2026) feed, all verified against live data
and against formula1.com's own static archive files:

  literal JSON      TimingData, SessionInfo, TrackStatus, DriverList, ...
                    arrives as a JSON object/array whose first char is { or [

  .z topics          Position.z, CarData.z
                    a bare base64 string whose deflate stream has NO zlib
                    header (raw deflate, wbits=-15) and no compression tag.
                    e.g. "7ZQxa8MwEIX/y8120J3udJL3zi00Q5vSIZQ..."

The archive files under /static/<year>/<event>/<session>/ are byte-identical
in framing to the live stream, so this decoder is used unchanged for replay
and for tests.
"""

from __future__ import annotations

import base64
import json
import zlib

__all__ = ["decode_topic_payload", "decode_position_payload", "PositionSample"]


def _inflate(blob: bytes) -> bytes | None:
    """Try every raw/inflate variant. Order matters: F1 .z is raw deflate."""
    for wbits in (-15, zlib.MAX_WBITS, zlib.MAX_WBITS | 32):
        try:
            return zlib.decompress(blob, wbits)
        except zlib.error:
            continue
    return None


def _b64(text: str) -> bytes | None:
    try:
        return base64.b64decode(text, validate=False)
    except Exception:
        return None


def decode_topic_payload(data):
    """Turn a raw topic value into Python data, or None if undecodable."""
    if data is None:
        return None
    if isinstance(data, (dict, list)):
        return data
    if isinstance(data, (bytes, bytearray)):
        # The archive endpoint prefixes files with a UTF-8 BOM.
        try:
            data = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            # A frame that is not text at all is a frame to skip, not a reason
            # to take the whole service down mid-session.
            return None
    if not isinstance(data, str):
        return None
    text = data.strip()
    if not text:
        return None
    if text[0] in "{[":
        try:
            return json.loads(text)
        except Exception:
            return None
    # .z topic: base64 of a raw-deflate JSON document.
    blob = _b64(text)
    if blob is not None:
        raw = _inflate(blob)
        if raw is not None:
            try:
                return json.loads(raw.decode("utf-8"))
            except Exception:
                return None
    # Older/alternate framing: a leading '0'|'1'|'2' compression tag.
    if text[0] in "012":
        blob = _b64(text[1:])
        if blob is not None:
            raw = _inflate(blob)
            if raw is not None:
                try:
                    return json.loads(raw.decode("utf-8"))
                except Exception:
                    return None
    return None


class PositionSample:
    """One Position.z snapshot.

    Shape (verified 2026-09-26 Azerbaijan GP Race archive):

        {"Position": [{"Timestamp": "...Z",
                       "Entries": {"1": {"Status":"OnTrack",
                                          "X": 1842, "Y": 721,
                                          "Z": 0, "CarNumber": 1, ...}}}]}
    """

    __slots__ = ("timestamp", "entries")

    def __init__(self, timestamp: str, entries: dict[str, dict]):
        self.timestamp = timestamp
        self.entries = entries

    def __len__(self) -> int:
        return len(self.entries)


def decode_position_payload(data) -> list[PositionSample]:
    """Decode Position.z into a list of PositionSample, newest first."""
    payload = decode_topic_payload(data)
    if payload is None:
        return []
    samples = payload.get("Position") if isinstance(payload, dict) else None
    if not samples:
        return []
    out: list[PositionSample] = []
    for block in samples:
        if not isinstance(block, dict):
            continue
        entries = block.get("Entries")
        if not isinstance(entries, dict):
            continue
        out.append(PositionSample(str(block.get("Timestamp", "")), entries))
    return out

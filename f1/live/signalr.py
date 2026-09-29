"""SignalR client for the public Formula 1 live timing feed.

The feed at https://livetiming.formula1.com/signalrcore is the same public
endpoint formula1.com uses to feed its own website and app. We speak the
documented SignalR JSON protocol over WebSocket against it directly -- no API
key, no account, no paid tier, no proxy, no cloud service.

Protocol summary (verified live against the current endpoint, see
tests/test_signalr_protocol.py and README "Protocol notes"):

  POST /signalrcore/negotiate?negotiateVersion=1   -> connectionToken
  WSS  /signalrcore?hub=Streaming&id=<token>        -> upgrade
  -> {"protocol":"json","version":1}\\x1e             handshake
  <- {}\\x1e                                        handshake ack
  -> {"type":1,"invocationId":"1","target":"Subscribe","arguments":["Topic"]}
  <- {"type":1,"target":"update","arguments":["Topic", <payload>]}

Every SignalR message is terminated by the record separator 0x1E. Payloads are
either literal JSON or, when the topic is high-volume (.z topics), a
compression-tagged base64 blob.

Two 2026-era changes from every pre-2025 write-up, both verified live:
  * the ``hub=Streaming`` query parameter is required or the upgrade 404s;
  * the handshake must be a real handshake. The old ``{}\\x1e`` now gets
    {"error":"An unexpected error occurred during connection handshake."};
    sending {"protocol":"json","version":1} is what the current server accepts.
"""

from __future__ import annotations

import base64
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib

from .ws import WebSocket, WebSocketClosed, WebSocketError

SEP = b"\x1e"
NEGOTIATE_URL = (
    "https://livetiming.formula1.com/signalrcore/negotiate"
    "?negotiateVersion=1&hub=Streaming"
)
# The hub name is now required. Verified 2026-09-29 against the live endpoint:
#   POST /signalrcore/negotiate?negotiateVersion=1        -> 200, connectionToken
#   GET  /signalrcore?id=<token>                          -> 404  (pre-2026 URL)
#   GET  /signalrcore?hub=Streaming&id=<token>            -> 101  (current)
#   GET  /signalrcore/connect?id=<token>                  -> 401  (gated behind auth)
# Every older FastF1/2023-2024 write-up uses the 404 form and no longer works.
HUB_NAME = "Streaming"
CONNECT_URL = "wss://livetiming.formula1.com/signalrcore?hub={hub}&id={token}"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) f1-omarchy/1.0"

# Topics the plugin cares about. Everything else is refused at subscribe time
# so we never pull audio/radio/feeds we would only throw away.
STATIC_TOPICS = [
    "DriverList",
    "SessionInfo",
    "SessionData",
    "TrackStatus",
    "LapCount",
    "WeatherData",
    "RaceControlMessages",
    "TeamRadio",
    "Status",
    "ArchiveStatus",
]

LIVE_TOPICS = [
    "TimingData",
    "TimingAppData",
    "Position.z",
    "CarData.z",
    "ContentStream",
    "AudioStreams",
    "DriverStations",
    "ChampionshipPrediction",
    "AntiF1GuidePrediction",
    "Prediction",
    "RcmTvState",
    "ExtrapolatedClock",
    "PrecisionRcmTvState",
    "Formatter",
    "RaceCountdown",
]

# The 20-car grid plus the reserve. F1 broadcasts one key per car.
ALL_POSITION_KEYS = [str(i) for i in range(1, 25)]

# Current server requires a full handshake; "{}" alone is rejected.
HANDSHAKE = '{"protocol":"json","version":1}\x1e'


def _http_post_json(url: str, timeout: float = 15.0) -> dict:
    req = urllib.request.Request(url, data=b"", method="POST")
    req.add_header("User-Agent", USER_AGENT)
    req.add_header("Accept", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


class SignalRClient:
    """One live connection. Owns its socket; no global state."""

    def __init__(
        self,
        *,
        live: bool = True,
        path: str | None = None,
        on_message=None,
        logger=None,
        timeout: float = 30.0,
    ) -> None:
        self.live = live
        self.path = path
        self.on_message = on_message
        self.log = logger or (lambda *a, **k: None)
        self.timeout = timeout
        self.ws: WebSocket | None = None
        self._invocation_id = 0
        self._buf = bytearray()
        self.subscribed: set[str] = set()
        self.connected_at: float | None = None
        self.keepalive = threading.Event()

    # ---------------------------------------------------------------- connect
    def negotiate(self) -> str:
        info = _http_post_json(NEGOTIATE_URL, timeout=self.timeout)
        token = info.get("connectionToken")
        if not token:
            raise WebSocketError(f"negotiate returned no connectionToken: {info}")
        transports = [t.get("transport") for t in info.get("availableTransports", [])]
        self.log(f"negotiated (transports={','.join(transports)})")
        return token

    def connect(self, attempts: int = 5) -> None:
        """Negotiate, upgrade, handshake. Retried, because the endpoint is flaky.

        The upgrade step answers 404 for roughly half of fresh tokens. Verified
        2026-09-29 with raw curl as well as this client, so it is the endpoint
        and not the framing: a loop of negotiated tokens, upgraded with curl,
        produced the same mix of 200 and 404. Each attempt negotiates again
        rather than reusing a token, because a token that never reached a hub is
        not worth keeping.

        Retrying is the only available remedy and it is a reasonable one: the
        failures are immediate and cost one extra handshake, and nothing is
        hammered because the attempts are bounded and spaced.
        """
        last: Exception | None = None
        for attempt in range(1, max(1, attempts) + 1):
            try:
                self._connect_once()
                if attempt > 1:
                    self.log(f"connected on attempt {attempt}")
                return
            except Exception as exc:  # noqa: BLE001 - retried below
                last = exc
                if attempt >= max(1, attempts):
                    break
                delay = min(0.5 * attempt, 2.0)
                self.log(f"connect attempt {attempt} failed ({type(exc).__name__}: {exc}); retrying")
                time.sleep(delay)
        assert last is not None
        raise last

    def _connect_once(self) -> None:
        token = self.negotiate()
        url = CONNECT_URL.format(hub=HUB_NAME, token=urllib.parse.quote(token, safe=""))
        self.ws = WebSocket(
            url,
            timeout=self.timeout,
            user_agent=USER_AGENT,
            origin="https://www.formula1.com",
        )
        try:
            self.ws.connect()
            self.ws.send_text(HANDSHAKE)
            self._await_handshake()
        except Exception:
            try:
                self.ws.close()
            except Exception:
                pass
            self.ws = None
            raise
        self.connected_at = time.time()
        self.log("SignalR handshake complete")

    def _await_handshake(self, budget: float = 10.0) -> bool:
        deadline = time.time() + budget
        while time.time() < deadline:
            self.ws.set_timeout(max(0.5, deadline - time.time()))
            try:
                _op, payload = self.ws.recv()
            except socket_timeout_types() as exc:  # noqa: F821
                raise WebSocketError("handshake timed out") from exc
            self._buf += payload
            if b"\x1e" in self._buf:
                raw = bytes(self._buf).split(SEP, 1)[0]
                del self._buf[: len(raw) + 1]
                try:
                    obj = json.loads(raw.decode())
                except Exception:
                    return True
                if obj.get("error"):
                    raise WebSocketError(f"handshake error: {obj['error']}")
                return True
        raise WebSocketError("handshake timed out")

    # -------------------------------------------------------------- subscribe
    def subscribe(self, topics: list[str]) -> None:
        self._invocation_id += 1
        msg = {
            "type": 1,
            "invocationId": str(self._invocation_id),
            "target": "Subscribe",
            "arguments": topics,
        }
        self.ws.send_text(json.dumps(msg, separators=(",", ":")) + "\x1e")
        self.subscribed.update(topics)
        self.log(f"subscribed to {len(topics)} topics")

    def subscribe_default(self) -> None:
        self.subscribe(STATIC_TOPICS + LIVE_TOPICS)

    def subscribe_static(self) -> None:
        self.subscribe(STATIC_TOPICS)

    def add_subscriptions(self, topics: list[str]) -> None:
        todo = [t for t in topics if t not in self.subscribed]
        if todo:
            self.subscribe(todo)

    # -------------------------------------------------------------------- run
    def messages(self):
        """Yield (topic, payload) forever until the socket dies."""
        assert self.ws is not None
        while not self.ws.closed:
            try:
                _op, payload = self.ws.recv()
            except (WebSocketClosed, WebSocketError, OSError):
                return
            self._buf += payload
            while SEP in self._buf:
                raw = bytes(self._buf).split(SEP, 1)[0]
                del self._buf[: len(raw) + 1]
                if not raw:
                    continue
                parsed = _parse_signalr(raw)
                if parsed is None:
                    continue
                mtype, target, args = parsed
                if mtype != 1 or target != "update" or len(args) < 2:
                    continue
                topic, data = args[0], decode_payload(args[1])
                if topic is None:
                    continue
                yield topic, data

    def close(self) -> None:
        self.keepalive.set()
        if self.ws:
            self.ws.close()
        self.ws = None


def socket_timeout_types():
    import socket

    return (socket.timeout, TimeoutError)


def _parse_signalr(raw: bytes):
    try:
        obj = json.loads(raw.decode("utf-8"))
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    return obj.get("type"), obj.get("target"), obj.get("arguments") or []


def decode_payload(data):
    """Turn a raw topic value into Python data, or None if undecodable.

    Delegates to the shared decoder so there is exactly one implementation of
    the .z wire format. Two copies of this logic is precisely how a live bug
    like "every .z topic silently arrives as None" happens: the archive path
    used one decoder and the streaming path a near-identical other one that had
    drifted.
    """
    from .decoder import decode_topic_payload

    return decode_topic_payload(data)

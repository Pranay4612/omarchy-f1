"""Protocol tests: handshake, framing, decompression, and the WebSocket layer.

The wire-format tests run against fixtures produced by formula1.com itself, so
a pass means the decoder agrees with the real feed rather than with itself. The
socket tests run against a throwaway local server, so they need no network.
"""

from __future__ import annotations

import base64
import json
import os
import socket
import struct
import threading
import unittest
import zlib
from pathlib import Path

from f1.live.decoder import decode_position_payload, decode_topic_payload
from f1.live.signalr import HANDSHAKE, HUB_NAME, _parse_signalr, decode_payload
from f1.live.ws import WebSocket, WebSocketClosed

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class TestEndpointContract(unittest.TestCase):
    """The two things about the current endpoint that a 2024 write-up gets wrong.

    Both were verified against the live service on 2026-09-29. They are asserted
    here so a future edit cannot quietly revert to the old, now-broken shapes.
    """

    def test_hub_name_is_required(self):
        self.assertEqual(HUB_NAME, "Streaming")

    def test_connect_url_carries_the_hub(self):
        from f1.live.signalr import CONNECT_URL

        self.assertIn("hub={hub}", CONNECT_URL)
        self.assertIn("/signalrcore?hub=", CONNECT_URL)

    def test_handshake_is_a_real_handshake(self):
        # The server rejects a bare "{}" with
        # {"error":"An unexpected error occurred during connection handshake."}
        self.assertIn('"protocol":"json"', HANDSHAKE)
        self.assertIn('"version":1', HANDSHAKE)
        self.assertTrue(HANDSHAKE.endswith("\x1e"))


def _raw_deflate(data: bytes) -> bytes:
    comp = zlib.compressobj(9, zlib.DEFLATED, -zlib.MAX_WBITS)
    return comp.compress(data) + comp.flush()


class TestSignalRFraming(unittest.TestCase):
    def test_update_message_is_parsed(self):
        raw = json.dumps(
            {"type": 1, "target": "update", "arguments": ["LapCount", {"CurrentLap": 12}]}
        ).encode()
        mtype, target, args = _parse_signalr(raw)
        self.assertEqual(mtype, 1)
        self.assertEqual(target, "update")
        self.assertEqual(args[0], "LapCount")

    def test_non_update_messages_are_ignored(self):
        raw = json.dumps({"type": 6, "target": "ping"}).encode()
        self.assertIsNotNone(_parse_signalr(raw))
        raw = b"not json at all"
        self.assertIsNone(_parse_signalr(raw))

    def test_literal_json_passes_through(self):
        self.assertEqual(decode_payload('{"CurrentLap":3}'), {"CurrentLap": 3})
        self.assertEqual(decode_payload("[1,2,3]"), [1, 2, 3])

    def test_compression_tag_variants(self):
        # The tag is a hint, not a contract this plugin depends on. The current
        # .z framing is untagged raw deflate, so the decoder must not refuse a
        # payload just because its first base64 character is not a tag digit.
        import gzip

        doc = json.dumps({"a": 1}).encode()
        for label, blob in (
            ("gzip", gzip.compress(doc)),
            ("zlib", zlib.compress(doc, 9)),
            ("raw-deflate", _raw_deflate(doc)),
        ):
            with self.subTest(label=label):
                self.assertEqual(
                    decode_payload(base64.b64encode(blob).decode()), {"a": 1}
                )

    def test_base64_that_merely_starts_with_a_digit_is_still_data(self):
        """A real feed payload whose base64 begins with a digit.

        Formula 1's own Position.z files start with "7ZQx...". A decoder that
        treats the leading character as a compression tag drops every single
        one of them, which is exactly the bug this test exists to prevent.
        """
        raw = (FIXTURES / "az2026-race-Position.z.json").read_bytes()
        payload = json.loads(raw.decode("utf-8-sig").strip())
        self.assertTrue(payload[0].isdigit(), f"fixture no longer starts with a digit: {payload[:8]!r}")
        self.assertIsNotNone(decode_payload(payload))

    def test_untagged_raw_deflate_is_decoded(self):
        doc = json.dumps({"Position": []}).encode()
        self.assertEqual(
            decode_payload(base64.b64encode(_raw_deflate(doc)).decode()), {"Position": []}
        )

    def test_garbage_never_raises(self):
        # A malformed frame must be skipped, not take the service down mid-race.
        for bad in ("", "not-base64!!", "0!!!!", "2####", None, 12345, b"\xff\xfe", b"\x00\x01\x02"):
            with self.subTest(bad=bad):
                self.assertIsNone(decode_payload(bad))


class TestRealFeedFixtures(unittest.TestCase):
    """Decode what formula1.com actually served, not a hand-written sample."""

    def setUp(self):
        self.positions = (FIXTURES / "az2026-race-Position.z.json").read_bytes()
        self.drivers = (FIXTURES / "az2026-race-DriverList.json").read_bytes()
        self.timing = (FIXTURES / "az2026-race-TimingData.json").read_bytes()

    def test_position_z_decodes_with_a_utf8_bom_and_quote_wrapper(self):
        samples = decode_position_payload(self.positions)
        self.assertTrue(samples, "Position.z produced no snapshots")
        first = samples[0]
        self.assertTrue(first.timestamp.endswith("Z"))
        self.assertEqual(len(first.entries), 22)

    def test_position_entries_carry_integer_circuit_coordinates(self):
        sample = decode_position_payload(self.positions)[0]
        for entry in sample.entries.values():
            self.assertIn("X", entry)
            self.assertIn("Y", entry)
            self.assertIn("Z", entry)
            self.assertIsInstance(entry["X"], int)
            self.assertIsInstance(entry["Y"], int)

    def test_position_keys_are_driver_ids_present_in_driver_list(self):
        drivers = decode_topic_payload(self.drivers)
        sample = decode_position_payload(self.positions)[0]
        # Every position key must resolve, or the map would draw nothing.
        self.assertTrue(set(sample.entries).issubset(set(drivers)))

    def test_driver_list_carries_team_colour_from_the_feed(self):
        drivers = decode_topic_payload(self.drivers)
        self.assertEqual(len(drivers), 22)
        for raw in drivers.values():
            self.assertTrue(raw["RacingNumber"])
            self.assertRegex(raw["TeamColour"], r"^[0-9A-Fa-f]{6}$")

    def test_timing_data_lines_carry_gaps_and_positions(self):
        timing = decode_topic_payload(self.timing)
        lines = timing["Lines"]
        self.assertEqual(len(lines), 22)
        for raw in lines.values():
            self.assertIn("Position", raw)
            self.assertIn("GapToLeader", raw)


# ------------------------------------------------------------------- websocket
def _recv_frame(conn):
    def read(n):
        buf = b""
        while len(buf) < n:
            chunk = conn.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("closed")
            buf += chunk
        return buf

    b0, b1 = read(2)
    opcode = b0 & 0x0F
    length = b1 & 0x7F
    if length == 126:
        length = struct.unpack(">H", read(2))[0]
    elif length == 127:
        length = struct.unpack(">Q", read(8))[0]
    _ = length
    if b1 & 0x80:
        mask = read(4)
    else:
        mask = None
    payload = read(length) if length else b""
    if mask:
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    return opcode, payload


def _send_frame(conn, opcode, payload, mask=True):
    header = bytearray([0x80 | opcode])
    m = os.urandom(4) if mask else b""
    n = len(payload)
    if n < 126:
        header.append((0x80 if mask else 0) | n)
    elif n < 65536:
        header.append((0x80 if mask else 0) | 126)
        header += struct.pack(">H", n)
    else:
        header.append((0x80 if mask else 0) | 127)
        header += struct.pack(">Q", n)
    if mask:
        header += m
        payload = bytes(b ^ m[i % 4] for i, b in enumerate(payload))
    conn.sendall(bytes(header) + payload)


class _EchoServer:
    """Minimal RFC 6455 server: upgrade, then echo every frame back."""

    def __init__(self):
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        try:
            conn, _ = self.sock.accept()
        except OSError:
            return
        with conn:
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = conn.recv(4096)
                if not chunk:
                    return
                data += chunk
            key = ""
            for line in data.decode("latin-1").split("\r\n"):
                if line.lower().startswith("sec-websocket-key:"):
                    key = line.split(":", 1)[1].strip()
            accept = base64.b64encode(
                __import__("hashlib").sha1(
                    (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()
                ).digest()
            ).decode()
            conn.sendall(
                (
                    "HTTP/1.1 101 Switching Protocols\r\n"
                    "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                    f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
                ).encode()
            )
            while True:
                try:
                    opcode, payload = _recv_frame(conn)
                except (ConnectionError, OSError):
                    return
                if opcode == 0x8:
                    return
                _send_frame(conn, opcode, payload, mask=False)


class TestWebSocket(unittest.TestCase):
    def setUp(self):
        self.server = _EchoServer()

    def test_handshake_and_echo(self):
        ws = WebSocket(f"ws://127.0.0.1:{self.server.port}/signalrcore", timeout=5)
        ws.connect()
        try:
            ws.send_text(HANDSHAKE)
            opcode, payload = ws.recv()
            self.assertEqual(opcode, 0x1)
            self.assertEqual(payload.decode(), HANDSHAKE)
        finally:
            ws.close()

    def test_binary_frames_round_trip(self):
        ws = WebSocket(f"ws://127.0.0.1:{self.server.port}/x", timeout=5)
        ws.connect()
        try:
            blob = bytes(range(256)) * 40
            ws.send_binary(blob)
            _op, payload = ws.recv()
            self.assertEqual(payload, blob)
        finally:
            ws.close()

    def test_large_frame_uses_the_extended_length_path(self):
        ws = WebSocket(f"ws://127.0.0.1:{self.server.port}/y", timeout=10)
        ws.connect()
        try:
            blob = b"a" * 70000
            ws.send_binary(blob)
            _op, payload = ws.recv()
            self.assertEqual(len(payload), 70000)
        finally:
            ws.close()

    def test_bad_scheme_is_refused(self):
        with self.assertRaises(Exception):
            WebSocket("http://example.com").connect()


if __name__ == "__main__":
    unittest.main()

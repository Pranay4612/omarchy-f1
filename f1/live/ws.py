"""Minimal RFC 6455 WebSocket client.

Pure standard library on purpose: the plugin must install on a stock Omarchy
box with no pip, no AUR and no virtualenv. Quickshell provides no socket API
that can hold a long-lived authenticated F1 timing stream, so we speak the
handshake ourselves.

Supports exactly what SignalR needs: client-side masking, text and binary
frames, continuation reassembly, ping/pong and close. Extensions (permessage
deflate) are deliberately not negotiated -- F1 compresses the *payload*
inside SignalR frames instead.
"""

from __future__ import annotations

import base64
import os
import socket
import ssl
import struct
import time

OP_CONT = 0x0
OP_TEXT = 0x1
OP_BINARY = 0x2
OP_CLOSE = 0x8
OP_PING = 0x9
OP_PING_MASKED = 0xA
OP_PONG = 0xA


class WebSocketError(RuntimeError):
    pass


class WebSocketClosed(WebSocketError):
    """Raised once the peer has sent a close frame or the socket is gone."""


class WebSocket:
    def __init__(
        self,
        url: str,
        *,
        timeout: float = 30.0,
        user_agent: str = "f1-omarchy",
        origin: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.url = url
        self.timeout = timeout
        self.user_agent = user_agent
        self.origin = origin
        self.extra_headers = extra_headers or {}
        self._sock: socket.socket | None = None
        self._buf = bytearray()
        self.closed = False
        self.close_code: int | None = None
        self.close_reason: str = ""

    # ---------------------------------------------------------------- connect
    def connect(self) -> None:
        if not self.url.startswith(("ws://", "wss://")):
            raise WebSocketError(f"unsupported scheme: {self.url}")
        secure = self.url.startswith("wss://")
        rest = self.url.split("://", 1)[1]
        hostport, _, path = rest.partition("/")
        if ":" in hostport:
            host, _, port_s = hostport.partition(":")
            port = int(port_s)
        else:
            host, port = hostport, 443 if secure else 80
        path = "/" + path if path else "/"

        raw = socket.create_connection((host, port), timeout=self.timeout)
        raw.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        if secure:
            ctx = ssl.create_default_context()
            raw = ctx.wrap_socket(raw, server_hostname=host)
        self._sock = raw

        key = base64.b64encode(os.urandom(16)).decode()
        req = [
            f"GET {path} HTTP/1.1",
            f"Host: {hostport}",
            "Upgrade: websocket",
            "Connection: Upgrade",
            f"Sec-WebSocket-Key: {key}",
            "Sec-WebSocket-Version: 13",
            f"User-Agent: {self.user_agent}",
        ]
        if self.origin:
            req.append(f"Origin: {self.origin}")
        for k, v in self.extra_headers.items():
            req.append(f"{k}: {v}")
        self._sock.sendall(("\r\n".join(req) + "\r\n\r\n").encode())

        header = self._read_until(b"\r\n\r\n")
        status_line = header.split(b"\r\n", 1)[0].decode("latin-1")
        if " 101 " not in status_line:
            raise WebSocketError(f"upgrade refused: {status_line}")

        # RFC 6455 §4.1: the accept value must echo the key, proving we are a
        # real WebSocket peer and not a cache. Cheap, and it catches middleboxes.
        expected = base64.b64encode(
            _sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode())
        ).decode()
        if expected.lower() not in header.decode("latin-1").lower():
            raise WebSocketError("bad Sec-WebSocket-Accept")

        self._sock.settimeout(self.timeout)

    # ------------------------------------------------------------------- read
    def _recv_some(self) -> bytes:
        assert self._sock is not None
        try:
            return self._sock.recv(65536)
        except socket.timeout:
            raise
        except (OSError, ssl.SSLError) as exc:
            raise WebSocketClosed(str(exc)) from exc

    def _read_until(self, marker: bytes, limit: int = 65536) -> bytes:
        while marker not in self._buf:
            if len(self._buf) > limit:
                raise WebSocketError("response header too large")
            chunk = self._recv_some()
            if not chunk:
                raise WebSocketClosed("handshake closed")
            self._buf += chunk
        idx = self._buf.index(marker) + len(marker)
        head = bytes(self._buf[:idx])
        del self._buf[:idx]
        return head

    def _need(self, n: int) -> None:
        while len(self._buf) < n:
            chunk = self._recv_some()
            if not chunk:
                raise WebSocketClosed("stream ended")
            self._buf += chunk

    def recv(self) -> tuple[int, bytes]:
        """Return the next complete (opcode, payload) message."""
        parts: list[bytes] = []
        first_op: int | None = None
        while True:
            self._need(2)
            b0, b1 = self._buf[0], self._buf[1]
            fin = bool(b0 & 0x80)
            opcode = b0 & 0x0F
            masked = bool(b1 & 0x80)
            length = b1 & 0x7F
            off = 2
            if length == 126:
                self._need(4)
                length = struct.unpack(">H", bytes(self._buf[2:4]))[0]
                off = 4
            elif length == 127:
                self._need(10)
                length = struct.unpack(">Q", bytes(self._buf[2:10]))[0]
                off = 10
            if masked:
                self._need(off + 4)
                mask = bytes(self._buf[off : off + 4])
                off += 4
            else:
                mask = None
            self._need(off + length)
            payload = bytes(self._buf[off : off + length])
            del self._buf[: off + length]
            if mask:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))

            if opcode == OP_CLOSE:
                self.close_code = struct.unpack(">H", payload[:2])[0] if len(payload) >= 2 else None
                self.close_reason = payload[2:].decode("utf-8", "replace")
                self.closed = True
                raise WebSocketClosed(f"peer close {self.close_code}")
            if opcode == OP_PING:
                self._send_frame(OP_PING, payload)
                continue
            if opcode == OP_PONG:
                continue

            if opcode != OP_CONT:
                first_op = opcode
            parts.append(payload)
            if fin:
                return (first_op or OP_BINARY, b"".join(parts))

    # ------------------------------------------------------------------ write
    def _send_frame(self, opcode: int, payload: bytes) -> None:
        if self._sock is None:
            raise WebSocketClosed("not connected")
        header = bytearray()
        header.append(0x80 | opcode)
        mask = os.urandom(4)
        n = len(payload)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header += struct.pack(">H", n)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", n)
        header += mask
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        try:
            self._sock.sendall(bytes(header) + masked)
        except (OSError, ssl.SSLError) as exc:
            self.closed = True
            raise WebSocketClosed(str(exc)) from exc

    def send_text(self, text: str) -> None:
        self._send_frame(OP_TEXT, text.encode())

    def send_binary(self, data: bytes) -> None:
        self._send_frame(OP_BINARY, data)

    def send_ping(self) -> None:
        self._send_frame(OP_PING, os.urandom(4))

    def close(self, code: int = 1000, reason: str = "") -> None:
        if self._sock is None:
            return
        if not self.closed:
            try:
                self._send_frame(OP_CLOSE, struct.pack(">H", code) + reason.encode())
            except Exception:
                pass
        self.closed = True
        try:
            self._sock.close()
        except Exception:
            pass
        self._sock = None

    def set_timeout(self, timeout: float | None) -> None:
        if self._sock is not None:
            self._sock.settimeout(timeout)


def _sha1(data: bytes):
    import hashlib

    return hashlib.sha1(data).digest()


__all__ = ["WebSocket", "WebSocketError", "WebSocketClosed", "time"]

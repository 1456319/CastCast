"""CASTv2 transport: TLS socket + 4-byte-big-endian length-prefixed framing."""

from __future__ import annotations

import json
import socket
import ssl
import struct
import threading
from typing import Optional

from .protobuf import CastMessage, device_auth_challenge

# Namespaces implemented by receiver-0.
NS_CONNECTION = "urn:x-cast:com.google.cast.tp.connection"
NS_HEARTBEAT = "urn:x-cast:com.google.cast.tp.heartbeat"
NS_RECEIVER = "urn:x-cast:com.google.cast.receiver"
NS_DEVICEAUTH = "urn:x-cast:com.google.cast.tp.deviceauth"
NS_MEDIA = "urn:x-cast:com.google.cast.media"

PLATFORM_SENDER = "sender-0"
PLATFORM_RECEIVER = "receiver-0"

CAST_PORT = 8009

#: The public "Default Media Receiver".  This is the crux of staying out of the
#: Google Home ecosystem: it is a stock app ID that needs no developer console
#: registration, no custom receiver hosted on Google's CDN, and no Home app.
#: pychromecast, VLC, catt and go-chromecast all hardcode it.
DEFAULT_MEDIA_RECEIVER_APP_ID = "CC1AD845"

#: Payloads larger than this are refused outright -- VLC does the same
#: ("Payload size is too long: dropping connection") to avoid a hostile or
#: corrupt peer making us allocate unboundedly.
PACKET_MAX_LEN = 64 * 1024


class ChannelClosed(Exception):
    """The socket died, or the peer sent something we cannot recover from."""


def make_ssl_context() -> ssl.SSLContext:
    """Cast devices present a self-signed cert; verification must be disabled.

    We also drop the OpenSSL security level, because older Cast firmware (the
    Ultra included) negotiates cipher suites that distro-hardened OpenSSL 3
    builds reject by default.
    """
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
    except ssl.SSLError:
        pass  # already permissive enough
    return ctx


class CastChannel:
    """One TLS connection to a Cast device.

    Framing is dead simple: every message is a 4-byte big-endian length
    followed by that many bytes of serialised ``CastMessage``.
    """

    def __init__(self, host: str, port: int = CAST_PORT, connect_timeout: float = 8.0):
        self.host = host
        self.port = port
        self._sock: Optional[ssl.SSLSocket] = None
        self._send_lock = threading.Lock()
        self._connect_timeout = connect_timeout

    # -- lifecycle ---------------------------------------------------------

    def connect(self) -> None:
        raw = socket.create_connection((self.host, self.port), self._connect_timeout)
        raw.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        # Belt and braces alongside the app-level heartbeat: if the Wi-Fi drops
        # silently, TCP keepalive eventually surfaces it too.
        raw.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        for opt, val in (("TCP_KEEPIDLE", 10), ("TCP_KEEPINTVL", 5), ("TCP_KEEPCNT", 3)):
            if hasattr(socket, opt):
                try:
                    raw.setsockopt(socket.IPPROTO_TCP, getattr(socket, opt), val)
                except OSError:
                    pass
        self._sock = make_ssl_context().wrap_socket(raw, server_hostname=self.host)

    def close(self) -> None:
        sock, self._sock = self._sock, None
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass

    @property
    def connected(self) -> bool:
        return self._sock is not None

    # -- raw I/O -----------------------------------------------------------

    def _read_exactly(self, count: int) -> bytes:
        sock = self._sock
        if sock is None:
            raise ChannelClosed("not connected")
        chunks = []
        remaining = count
        while remaining:
            try:
                chunk = sock.recv(remaining)
            except ssl.SSLWantReadError:
                raise socket.timeout()
            if not chunk:
                raise ChannelClosed("peer closed the connection")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def receive(self, timeout: float) -> CastMessage:
        """Read one message.  Raises ``socket.timeout`` if none arrives in time."""
        sock = self._sock
        if sock is None:
            raise ChannelClosed("not connected")
        sock.settimeout(max(timeout, 0.05))
        header = self._read_exactly(4)
        (size,) = struct.unpack(">I", header)
        if size > PACKET_MAX_LEN:
            raise ChannelClosed(f"payload size is too long ({size}); dropping connection")
        return CastMessage.decode(self._read_exactly(size))

    def send(self, message: CastMessage) -> None:
        sock = self._sock
        if sock is None:
            raise ChannelClosed("not connected")
        body = message.encode()
        frame = struct.pack(">I", len(body)) + body
        with self._send_lock:
            try:
                sock.sendall(frame)
            except OSError as exc:
                raise ChannelClosed(f"send failed: {exc}") from exc

    # -- convenience senders ----------------------------------------------

    def send_json(self, namespace: str, destination: str, payload: dict) -> None:
        self.send(CastMessage(PLATFORM_SENDER, destination, namespace,
                              payload_utf8=json.dumps(payload, separators=(",", ":"))))

    def send_binary(self, namespace: str, destination: str, payload: bytes) -> None:
        self.send(CastMessage(PLATFORM_SENDER, destination, namespace,
                              payload_binary=payload))

    # Virtual connections.  A single TCP socket is multiplexed into several
    # logical connections -- one to receiver-0, and another to the media app's
    # transportId once it launches.  You *must* CONNECT before the peer will
    # accept anything else, and CONNECT is also what subscribes you to that
    # peer's status broadcasts.
    def virtual_connect(self, destination: str) -> None:
        self.send_json(NS_CONNECTION, destination, {
            "type": "CONNECT",
            "origin": {},
            "userAgent": "castcast",
            "senderInfo": {
                "sdkType": 2,
                "version": "castcast-1.0",
                "browserVersion": "",
                "platform": 2,
                "connectionType": 1,
            },
        })

    def virtual_close(self, destination: str) -> None:
        try:
            self.send_json(NS_CONNECTION, destination, {"type": "CLOSE"})
        except ChannelClosed:
            pass

    def send_device_auth(self) -> None:
        self.send_binary(NS_DEVICEAUTH, PLATFORM_RECEIVER, device_auth_challenge())

    def ping(self) -> None:
        self.send_json(NS_HEARTBEAT, PLATFORM_RECEIVER, {"type": "PING"})

    def pong(self) -> None:
        self.send_json(NS_HEARTBEAT, PLATFORM_RECEIVER, {"type": "PONG"})

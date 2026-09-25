# synchronization-map: section=cast-sender-receiver; role=cast-protobufs; boundaries=cast-sender-receiver; doc=docs/SYNCHRONIZATION_MAP.md
"""Minimal protobuf codec for the CASTv2 ``CastMessage`` frame.

Google's ``cast_channel.proto`` is small enough that vendoring protoc plus the
generated ``.pb.cc``/``.pb.h`` bindings (the way VLC does in
``modules/stream_out/chromecast/``) is not worth the toolchain dependency --
especially on Termux, where building protobuf from source is painful.

We only ever need two wire types: varint and length-delimited.  The full
message we care about is::

    message CastMessage {
      required ProtocolVersion protocol_version = 1;  // CASTV2_1_0 = 0
      required string source_id                 = 2;
      required string destination_id            = 3;
      required string namespace_                = 4;
      required PayloadType payload_type         = 5;  // STRING = 0, BINARY = 1
      optional string payload_utf8              = 6;
      optional bytes  payload_binary            = 7;
    }
"""

from __future__ import annotations

from typing import Dict, List, Tuple

WIRE_VARINT = 0
WIRE_FIXED64 = 1
WIRE_LEN = 2
WIRE_FIXED32 = 5

PROTOCOL_VERSION_CASTV2_1_0 = 0
PAYLOAD_STRING = 0
PAYLOAD_BINARY = 1


# --------------------------------------------------------------------------
# primitives
# --------------------------------------------------------------------------

def encode_varint(value: int) -> bytes:
    if value < 0:
        raise ValueError("negative varint")
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        out.append(byte | (0x80 if value else 0x00))
        if not value:
            return bytes(out)


def decode_varint(buf: bytes, pos: int) -> Tuple[int, int]:
    result = 0
    shift = 0
    while True:
        if pos >= len(buf):
            raise ValueError("truncated varint")
        byte = buf[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7
        if shift > 63:
            raise ValueError("varint too long")


def _tag(field: int, wire: int) -> bytes:
    return encode_varint((field << 3) | wire)


def _varint_field(field: int, value: int) -> bytes:
    return _tag(field, WIRE_VARINT) + encode_varint(value)


def _len_field(field: int, value) -> bytes:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return _tag(field, WIRE_LEN) + encode_varint(len(value)) + value


def decode_fields(buf: bytes) -> Dict[int, List[object]]:
    """Decode a protobuf message into ``{field_number: [values...]}``.

    Length-delimited fields come back as ``bytes``; varints as ``int``.
    Unknown/irrelevant wire types are skipped rather than raising, so we stay
    forward-compatible with receiver firmware that adds fields.
    """
    out: Dict[int, List[object]] = {}
    pos = 0
    end = len(buf)
    while pos < end:
        key, pos = decode_varint(buf, pos)
        field, wire = key >> 3, key & 0x07
        if wire == WIRE_VARINT:
            value, pos = decode_varint(buf, pos)
        elif wire == WIRE_LEN:
            length, pos = decode_varint(buf, pos)
            if pos + length > end:
                raise ValueError("truncated length-delimited field")
            value = buf[pos:pos + length]
            pos += length
        elif wire == WIRE_FIXED64:
            value = buf[pos:pos + 8]
            pos += 8
        elif wire == WIRE_FIXED32:
            value = buf[pos:pos + 4]
            pos += 4
        else:
            raise ValueError(f"unsupported wire type {wire}")
        out.setdefault(field, []).append(value)
    return out


# --------------------------------------------------------------------------
# CastMessage
# --------------------------------------------------------------------------

class CastMessage:
    __slots__ = ("source_id", "destination_id", "namespace", "payload_utf8",
                 "payload_binary")

    def __init__(self, source_id: str, destination_id: str, namespace: str,
                 payload_utf8: str = "", payload_binary: bytes = b""):
        self.source_id = source_id
        self.destination_id = destination_id
        self.namespace = namespace
        self.payload_utf8 = payload_utf8
        self.payload_binary = payload_binary

    @property
    def is_binary(self) -> bool:
        return bool(self.payload_binary)

    def encode(self) -> bytes:
        parts = [
            _varint_field(1, PROTOCOL_VERSION_CASTV2_1_0),
            _len_field(2, self.source_id),
            _len_field(3, self.destination_id),
            _len_field(4, self.namespace),
        ]
        if self.payload_binary:
            parts.append(_varint_field(5, PAYLOAD_BINARY))
            parts.append(_len_field(7, self.payload_binary))
        else:
            parts.append(_varint_field(5, PAYLOAD_STRING))
            parts.append(_len_field(6, self.payload_utf8))
        return b"".join(parts)

    @classmethod
    def decode(cls, buf: bytes) -> "CastMessage":
        fields = decode_fields(buf)

        def first_str(num: int) -> str:
            vals = fields.get(num)
            if not vals:
                return ""
            raw = vals[0]
            return raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)

        def first_bytes(num: int) -> bytes:
            vals = fields.get(num)
            if not vals:
                return b""
            raw = vals[0]
            return raw if isinstance(raw, bytes) else b""

        return cls(
            source_id=first_str(2),
            destination_id=first_str(3),
            namespace=first_str(4),
            payload_utf8=first_str(6),
            payload_binary=first_bytes(7),
        )

    def __repr__(self) -> str:
        body = self.payload_utf8 if self.payload_utf8 else f"<{len(self.payload_binary)}B binary>"
        short = self.namespace.rsplit(".", 1)[-1]
        return f"<CastMessage {self.source_id}->{self.destination_id} {short} {body[:160]}>"


def device_auth_challenge() -> bytes:
    """A minimal ``DeviceAuthMessage{ challenge: {} }``.

    ``tp.deviceauth`` is *optional for senders* -- pychromecast skips it
    entirely.  VLC performs it, so we support it behind a config flag: an empty
    ``AuthChallenge`` submessage in field 1 is all the receiver needs to reply.
    We never validate the returned certificate chain (we are not trying to
    prove the device is genuine; we are trying to talk to the one on our LAN).
    """
    return _len_field(1, b"")

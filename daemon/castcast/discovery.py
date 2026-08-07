"""Chromecast discovery over mDNS, with no zeroconf dependency.

The upstream Chromecast-Controller shelled out to ``avahi-browse`` ("why
reinvent the wheel"), which is the right call on a systemd box.  On Termux
there is no Avahi and usually no D-Bus, so we implement just enough mDNS to
query ``_googlecast._tcp.local`` ourselves: one multicast question, then parse
the PTR/SRV/TXT/A records out of the answers.

Discovery is also the least reliable part of the stack -- plenty of routers
drop multicast, and Android's Wi-Fi stack will not deliver multicast to
userspace without a MulticastLock.  So ``resolve()`` prefers a pinned static IP
above everything else: once you know your Ultra's address, pin it and never
depend on mDNS again.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import struct
import subprocess
import time
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional

MDNS_ADDR = "224.0.0.251"
MDNS_PORT = 5353
CAST_SERVICE = "_googlecast._tcp.local"

TYPE_A = 1
TYPE_PTR = 12
TYPE_TXT = 16
TYPE_SRV = 33


@dataclass
class CastDevice:
    name: str = ""            # mDNS instance name
    friendly_name: str = ""   # TXT 'fn'
    model: str = ""           # TXT 'md'
    uuid: str = ""            # TXT 'id'
    host: str = ""
    port: int = 8009
    source: str = "mdns"      # mdns | avahi | static | cache

    def to_dict(self) -> dict:
        d = asdict(self)
        d["is_ultra"] = "ultra" in self.model.lower()
        return d


# --------------------------------------------------------------------------
# DNS wire parsing
# --------------------------------------------------------------------------

def _read_name(buf: bytes, pos: int, depth: int = 0):
    """Read a (possibly compressed) DNS name.  Returns (name, next_pos)."""
    if depth > 12:
        raise ValueError("compression loop")
    labels: List[str] = []
    while True:
        if pos >= len(buf):
            raise ValueError("truncated name")
        length = buf[pos]
        if length == 0:
            return ".".join(labels), pos + 1
        if length & 0xC0 == 0xC0:
            if pos + 1 >= len(buf):
                raise ValueError("truncated pointer")
            ptr = ((length & 0x3F) << 8) | buf[pos + 1]
            suffix, _ = _read_name(buf, ptr, depth + 1)
            if suffix:
                labels.append(suffix)
            return ".".join(labels), pos + 2
        pos += 1
        labels.append(buf[pos:pos + length].decode("utf-8", "replace"))
        pos += length


def _encode_name(name: str) -> bytes:
    out = bytearray()
    for label in name.split("."):
        if label:
            out.append(len(label))
            out += label.encode("utf-8")
    out.append(0)
    return bytes(out)


def _build_query(service: str) -> bytes:
    header = struct.pack(">HHHHHH", 0, 0, 1, 0, 0, 0)  # id 0, standard query, 1 question
    question = _encode_name(service) + struct.pack(">HH", TYPE_PTR, 1)
    return header + question


def _parse_records(buf: bytes):
    """Yield ``(name, rtype, rdata_bytes, rdata_start)`` for every record."""
    if len(buf) < 12:
        return
    _, _, qd, an, ns, ar = struct.unpack(">HHHHHH", buf[:12])
    pos = 12
    for _ in range(qd):
        _, pos = _read_name(buf, pos)
        pos += 4
    for _ in range(an + ns + ar):
        if pos >= len(buf):
            return
        name, pos = _read_name(buf, pos)
        if pos + 10 > len(buf):
            return
        rtype, _rclass, _ttl, rdlen = struct.unpack(">HHIH", buf[pos:pos + 10])
        pos += 10
        yield name, rtype, buf[pos:pos + rdlen], pos
        pos += rdlen


def _parse_txt(rdata: bytes) -> Dict[str, str]:
    out: Dict[str, str] = {}
    pos = 0
    while pos < len(rdata):
        length = rdata[pos]
        pos += 1
        chunk = rdata[pos:pos + length].decode("utf-8", "replace")
        pos += length
        if "=" in chunk:
            key, _, value = chunk.partition("=")
            out[key.lower()] = value
    return out


# --------------------------------------------------------------------------
# Discovery strategies
# --------------------------------------------------------------------------

def discover_mdns(timeout: float = 4.0, interface_ip: str = "0.0.0.0") -> List[CastDevice]:
    """Pure-Python mDNS browse for ``_googlecast._tcp.local``."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, "SO_REUSEPORT"):
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except OSError:
            pass

    srv: Dict[str, tuple] = {}     # instance -> (target, port)
    txt: Dict[str, Dict[str, str]] = {}
    addr: Dict[str, str] = {}      # hostname -> ip
    instances: set = set()

    try:
        sock.bind(("", MDNS_PORT))
        try:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                            struct.pack("4s4s", socket.inet_aton(MDNS_ADDR),
                                        socket.inet_aton(interface_ip)))
        except OSError:
            pass
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
        sock.settimeout(0.5)

        query = _build_query(CAST_SERVICE)
        deadline = time.time() + timeout
        next_query = 0.0

        while time.time() < deadline:
            now = time.time()
            if now >= next_query:
                try:
                    sock.sendto(query, (MDNS_ADDR, MDNS_PORT))
                except OSError:
                    pass
                next_query = now + 1.0  # re-ask; multicast is lossy

            try:
                data, _src = sock.recvfrom(9000)
            except socket.timeout:
                continue
            except OSError:
                break

            try:
                for name, rtype, rdata, rstart in _parse_records(data):
                    if rtype == TYPE_PTR and name == CAST_SERVICE:
                        target, _ = _read_name(data, rstart)
                        instances.add(target)
                    elif rtype == TYPE_SRV and name.endswith(CAST_SERVICE):
                        if len(rdata) >= 6:
                            _prio, _weight, port = struct.unpack(">HHH", rdata[:6])
                            host, _ = _read_name(data, rstart + 6)
                            srv[name] = (host, port)
                            instances.add(name)
                    elif rtype == TYPE_TXT and name.endswith(CAST_SERVICE):
                        txt[name] = _parse_txt(rdata)
                        instances.add(name)
                    elif rtype == TYPE_A and len(rdata) == 4:
                        addr[name] = socket.inet_ntoa(rdata)
            except (ValueError, struct.error):
                continue  # malformed packet from some other device; ignore
    finally:
        sock.close()

    devices: List[CastDevice] = []
    for instance in sorted(instances):
        host, port = srv.get(instance, ("", 8009))
        meta = txt.get(instance, {})
        ip = addr.get(host, "")
        if not ip and not meta:
            continue
        label = instance[:-len(CAST_SERVICE)].rstrip(".") if instance.endswith(CAST_SERVICE) else instance
        devices.append(CastDevice(
            name=label,
            friendly_name=meta.get("fn", label),
            model=meta.get("md", ""),
            uuid=meta.get("id", ""),
            host=ip,
            port=port or 8009,
            source="mdns",
        ))
    return [d for d in devices if d.host]


def discover_avahi(timeout: float = 4.0) -> List[CastDevice]:
    """Use avahi-browse when it exists -- faster and more reliable than our own."""
    if not shutil.which("avahi-browse"):
        return []
    try:
        proc = subprocess.run(
            ["avahi-browse", "-rptk", CAST_SERVICE.replace(".local", "")],
            capture_output=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError):
        return []

    devices = []
    for line in proc.stdout.decode("utf-8", "replace").splitlines():
        parts = line.split(";")
        if len(parts) < 10 or parts[0] != "=":
            continue
        meta = _parse_txt_fields(parts[9])
        devices.append(CastDevice(
            name=parts[3], friendly_name=meta.get("fn", parts[3]),
            model=meta.get("md", ""), uuid=meta.get("id", ""),
            host=parts[7], port=int(parts[8] or 8009), source="avahi",
        ))
    return devices


def _parse_txt_fields(raw: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for token in raw.split('" "'):
        token = token.strip('"')
        if "=" in token:
            key, _, value = token.partition("=")
            out[key.lower()] = value
    return out


def probe_direct(host: str, port: int = 8009, timeout: float = 2.0) -> bool:
    """Is something actually listening on the Cast port?"""
    try:
        with socket.create_connection((host, port), timeout):
            return True
    except OSError:
        return False


class DeviceCache:
    """Remembers the last known address so we can reconnect without mDNS."""

    def __init__(self, path: str):
        self.path = path
        self._data: Dict[str, dict] = {}
        self.load()

    def load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                self._data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            self._data = {}

    def save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, indent=2)
            os.replace(tmp, self.path)
        except OSError:
            pass

    def remember(self, device: CastDevice) -> None:
        key = device.uuid or device.friendly_name or device.host
        if key:
            self._data[key] = device.to_dict()
            self.save()

    def all(self) -> List[CastDevice]:
        out = []
        for entry in self._data.values():
            out.append(CastDevice(
                name=entry.get("name", ""), friendly_name=entry.get("friendly_name", ""),
                model=entry.get("model", ""), uuid=entry.get("uuid", ""),
                host=entry.get("host", ""), port=entry.get("port", 8009), source="cache",
            ))
        return out


def resolve(static_host: Optional[str] = None, static_port: int = 8009,
            cache: Optional[DeviceCache] = None,
            timeout: float = 4.0) -> List[CastDevice]:
    """Find devices, cheapest and most reliable strategy first."""
    if static_host:
        return [CastDevice(name="static", friendly_name="Pinned device",
                           host=static_host, port=static_port, source="static")]

    found = discover_avahi(timeout) or discover_mdns(timeout)
    if found:
        if cache:
            for device in found:
                cache.remember(device)
        return found

    # mDNS failed -- fall back to the last known address and check it is alive.
    if cache:
        return [d for d in cache.all() if d.host and probe_direct(d.host, d.port, 1.5)]
    return []

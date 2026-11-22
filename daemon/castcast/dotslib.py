#!/usr/bin/env python3
# synchronization-map: section=media-routing; role=dots-codec; boundaries=core-service; doc=docs/SYNCHRONIZATION_MAP.md
"""dotslib: data-matrix-over-HDMI codec for the video-dots covert channel.

Grid: 160x90 cells on a 3840x2160 frame at 24 px/cell (20 px dot + 4 px gap).
1-cell black border ring at the frame edge, four white 2x2 corner anchors
sitting ON the ring (border check exempts them). Payload region rows
[2,88) x cols [2,158) = 86x156 cells, split into two sectors per video frame
(top 44 rows / bottom 42 rows). Per sector: 2B seq LE + 592B chunk,
RS-FEC'd (reedsolo nsym=32; reedsolo auto-splits the 594B message into 3
interleaved blocks -> 96 parity) into a 690B wire; the wire's 5520 bits fill
the top of the half's region row-major, remaining cells stay black.

Header sector (seq 0): struct "<8sQI" = MAGIC b"DOTSX01\\x00" (8 bytes),
payload_len u64 LE, crc32 u32 LE.

NOTE: rebuilt 2026-09-25 from spec after /tmp was wiped in a system crash.
The original _fix_orientation implementation is not recoverable; this one
fixes polarity only (corner anchors must read white).
"""
import math
import struct
import zlib

import cv2
import numpy as np
from reedsolo import RSCodec

GRID_H, GRID_W = 90, 160
SCALE = 24                       # px per cell (20 px dot + 2 px margins)
ANCHOR = 2                       # corner anchor size in cells
PAY_R0, PAY_R1 = 2, 88           # payload row range [2, 88)
PAY_C0, PAY_C1 = 2, 158          # payload col range [2, 158)
TOP_ROWS = 44                    # rows in half 0 (half 1 is 42)
SEQ_BYTES, CHUNK, NSYM = 2, 592, 32
MAGIC = b"DOTSX01\x00"           # 8 bytes to fill the HDR 8s field exactly
HDR = struct.Struct("<8sQI")

_rsc = RSCodec(NSYM)
WIRE = len(_rsc.encode(bytes(SEQ_BYTES + CHUNK)))   # 690
WIRE_BITS = WIRE * 8                                # 5520
REGION_W = PAY_C1 - PAY_C0                          # 156

_CORNERS = ((0, 0), (0, GRID_W - ANCHOR),
            (GRID_H - ANCHOR, 0), (GRID_H - ANCHOR, GRID_W - ANCHOR))


def frames_for(n: int) -> int:
    """Number of video frames (sector pairs) needed for n payload bytes."""
    return math.ceil(n / (2 * CHUNK))


def build_stream(payload: bytes):
    """-> (header_chunk, [(seq, chunk), ...]) in wire order.

    Both halves of a frame share the same seq: (0,hdr),(1,c@0),(1,c@592),...
    """
    header = HDR.pack(MAGIC, len(payload), zlib.crc32(payload) & 0xFFFFFFFF)
    sectors = [(0, header.ljust(CHUNK, b"\x00"))]
    seq = 1
    for off in range(0, len(payload), 2 * CHUNK):
        for half in (0, 1):
            c = payload[off + half * CHUNK: off + (half + 1) * CHUNK]
            sectors.append((seq, c.ljust(CHUNK, b"\x00")))
        seq += 1
    return header, sectors


def encode_sector(seq: int, chunk: bytes) -> bytes:
    return bytes(_rsc.encode(struct.pack("<H", seq) + chunk))


def decode_sector(wire: bytes):
    dec = _rsc.decode(bytes(wire))[0]
    seq = struct.unpack("<H", dec[:SEQ_BYTES])[0]
    return seq, dec[SEQ_BYTES:SEQ_BYTES + CHUNK]


def _cell_grid(wa, wb):
    """Two wire byte arrays -> 90x160 bool cell grid (None half = black)."""
    g = np.zeros((GRID_H, GRID_W), dtype=bool)
    for r0, c0 in _CORNERS:
        g[r0:r0 + ANCHOR, c0:c0 + ANCHOR] = True

    def put(r0, rows, wire):
        if wire is None:
            return
        bits = np.unpackbits(np.frombuffer(wire, dtype=np.uint8))[:WIRE_BITS]
        reg = np.zeros(rows * REGION_W, dtype=bool)
        reg[:WIRE_BITS] = bits.astype(bool)
        g[r0:r0 + rows, PAY_C0:PAY_C1] = reg.reshape(rows, REGION_W)

    put(PAY_R0, TOP_ROWS, wa)
    put(PAY_R0 + TOP_ROWS, PAY_R1 - (PAY_R0 + TOP_ROWS), wb)
    return g


def render_frame(g, scale=SCALE):
    """90x160 bool grid -> 3840x2160 BGR image (white dots on black)."""
    t = np.zeros((scale, scale), dtype=np.uint8)
    t[2:scale - 2, 2:scale - 2] = 1          # 20 px dot in the 24 px cell
    img = np.kron(g.astype(np.uint8), t) * 255
    return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)


def _fix_orientation(g):
    # Corner anchors are white; if they read black, polarity is inverted.
    a = sum(int(g[r0:r0 + ANCHOR, c0:c0 + ANCHOR].sum()) for r0, c0 in _CORNERS)
    return ~g if a * 2 < 4 * ANCHOR * ANCHOR else g


def extract_cells(bgr):
    """BGR frame -> 90x160 bool grid, or None if the border check fails."""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    small = cv2.resize(gray, (GRID_W, GRID_H), interpolation=cv2.INTER_AREA)
    _, bw = cv2.threshold(small, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    g = bw > 0
    g = _fix_orientation(g)
    border = np.zeros((GRID_H, GRID_W), dtype=bool)
    border[0, :] = True; border[-1, :] = True
    border[:, 0] = True; border[:, -1] = True
    for r0, c0 in _CORNERS:
        border[r0:r0 + ANCHOR, c0:c0 + ANCHOR] = False
    if g[border].any():
        return None
    return g


class Collector:
    """Accumulates decoded sectors; assembles when complete."""

    def __init__(self):
        self.sectors = {}
        self.payload_len = None
        self.payload_crc = None

    def _n_frames(self):
        return frames_for(self.payload_len) if self.payload_len is not None else None

    def feed(self, g):
        for half, sl in ((0, g[PAY_R0:PAY_R0 + TOP_ROWS, PAY_C0:PAY_C1]),
                         (1, g[PAY_R0 + TOP_ROWS:PAY_R1, PAY_C0:PAY_C1])):
            bits = sl.reshape(-1)[:WIRE_BITS]
            seq, chunk = decode_sector(np.packbits(bits))
            self.sectors[(seq, half)] = chunk
            if seq == 0 and self.payload_len is None:
                magic, n, crc = HDR.unpack(chunk[:HDR.size])
                if magic == MAGIC:
                    self.payload_len, self.payload_crc = n, crc

    def status(self):
        have = sum(1 for (s, _h) in self.sectors if s > 0)
        exp = 2 * self._n_frames() if self.payload_len is not None else "?"
        return {"header": self.payload_len is not None,
                "sectors_have": have, "sectors_expected": exp}

    def complete(self):
        n = self._n_frames()
        if n is None:
            return False
        return all((i, h) in self.sectors
                   for i in range(1, n + 1) for h in (0, 1))

    def assemble(self):
        n = self._n_frames()
        if n is None or not self.complete():
            return None
        data = b"".join(self.sectors[(i, h)]
                        for i in range(1, n + 1) for h in (0, 1))
        data = data[:self.payload_len]
        if zlib.crc32(data) & 0xFFFFFFFF != self.payload_crc:
            return None
        return data

# synchronization-map: section=media-routing; role=text-synthesizer; boundaries=core-service; doc=docs/SYNCHRONIZATION_MAP.md
"""Synthesizes high-contrast monospaced code/text slides into a 1080p MP4 stream using pure NumPy."""

import base64
import gzip
import hashlib
import os
import shutil
import subprocess
from typing import List, Optional

try:
    import numpy as np
except (ImportError, ModuleNotFoundError):
    np = None

WIDTH, HEIGHT = 1920, 1080
LINES_PER_PAGE = 30
CHARS_PER_LINE = 100
BG_COLOR = (18, 18, 18)        # Charcoal BGR
TEXT_COLOR = (240, 240, 240)    # White BGR
HEADER_COLOR = (255, 200, 0)    # Cyan BGR (for rawvideo bgr24)
LINE_NO_COLOR = (120, 120, 120) # Grey BGR

# Gzip+base64 encoded PSF2 8x16 bitmap font (256 glyphs)
_FONT_B64 = (
    "H4sIAMZ4A2sC/31XT2vjRhQXKegkvOltaExyyQcQLSSiFTYs/Qq9i2xR9zC0PmUFHbSbSz5C"
    "IfTcS7/DghrD0IPJcTHINTnZl1IMC1kfgqbvzf+ZpH1OsH96b+b9fzNKkpjaq9+urt7fXF21"
    "GoteiPlWiNZI0AGIFYcGHxbMh6Qst9stIaXFLSx2WIkQ9UtI2s5RAZJ8WNYvX9al489v3r+/"
    "mWv+8eiLL5sFUJNoYaCSgAKFp19Nc6DZ7l7ht6/evgL6YbvptHLSl9uy1/Lvuvvdftjv7rt3"
    "Eh+ko+PJMDkepQfWfEJIawxOakXwrffv+/7nIyQJGa8KyjktMs68qGLIov1aHyMZ8yQ5hfAo"
    "GzLibZZXQ5X7Oeu6bvDgaS3qUwcPi4KxYfBsYaxw+YoIclOiMdoecPU0FKB0oPJfWcv4bcfS"
    "9Joz48Etz0he8WuFCkqLyxXk61LZnudVsB3ISiKZdo5kkojzsC5FWfsmumx7z7wFSfuMX3bF"
    "QYr26XxDwvjd+mHDTbpI0egMGL4S54PFaZmmqZHPxiVdDGDwsY4uJOPR4xcVYM7t/gOsVz5b"
    "/Zx5fPzdwvqsCSz3HNbYuCvNg6ilvvdeACQPZez+mZdfqW+9Xq86ZqoFyndAgxR+hApgWPGP"
    "pt9uwcPuVjdosqeqIehe+1dfvG5eVxf1EOCq2nnr15zXXyuMmqQ6ra/UDWDmxbGsBtfvG1DV"
    "NKB0o/CukmT14STp50h6/83DsL5z+8tYe/GW/lXOPs3/sGbZyPLRx43lV0WW2vWivwns5dH+"
    "c0W16WeJ+l6Y+SFZpKyNvUrW7Sfm15i8P+ZCxyfXZOYpTLBZMbbzqsw0lSabyX+RwHYkT583"
    "GbP9mtxXVSNT7MYZ41AAxr8xaKILJy/5g+MX9Ptq58UX6BLFFyyTKYX96WXt4gt1WfjxTNNk"
    "lEqqZcmBvCoALV9E9YIlInoki1d6ZDv7vPxYPrMmGvtMS68u68B+nPF2vB/m+SOm42xs+XK5"
    "F48g/wpjATgMTCgAi1X9tGlmWmqB81TX9whcnaG/I3deJN75gTyUITPtzCpOr+xws53uZ2jn"
    "LJUeLUL7cQ77+YTFYX0swnqBaRPgghahPGqEFII6U6BhvfCwfnC/gF8nQX1A4AKM8j7mbqAZ"
    "c3yMY3GoK8h97Q7IH785aperNwpMoLgHjMdd4uz16oeH9aTsdThvFkE8kR/UB/fy3SBkwfzg"
    "SThP4FyaQ77m5gS07bV5dMUk4KP5ML7YRf0T1PdHVT5HRB6fQMuZDoCfH8x3EF/g+/4gDuyH"
    "+vL6C5AduCrZlE780wivA4l/M4JzMMfj1b8u4Rna+bcnbH9z1bnl2A53v6bZicP13S8TJaK6"
    "oSy9fjujS3rmbQeILtXPz78NP9/9Hn7+ehN+yPO0j5DFZ4oe9LexYghwLP+QWvmYdDhC/kNq"
    "a1c/GbxrkbQnGgH7yP6TQJ4QEZ8UsTwJ7qyJiNdH0idRPM4D+8/zaaBtmof8T4mIzq1P0frz"
    "ID7Cyev1Vl57J6J4xfuL2L8oDdPA3xMXP0knT+IzjdaL0B4SxzfOl91PRJT4r1FAu4heRBQu"
    "M+fxarlcrnQ/47vVcgHtuzD3VTzt/YbE6z+SgRxmmjuf8P65RJol/hsTTNjOqgti05JSvcHZ"
    "CSHHM4wJCzmq+0ffB+E6O5HvfE4fHPZuxHyWAv7YGnXjvMLxXuXjJLoAWn/MX/h6YYKkr892"
    "iOnrtsEjePN7OhB8/2Gz1r+/45C0p7Kch//zsmIemB8v5N3ub0rLsZ5lXirw+F/m1Z9h+TBF"
    "z14B/wVIKjaIABAAAA=="
)

_font_cache = None

def _get_font() -> np.ndarray:
    global _font_cache
    if _font_cache is None:
        raw = gzip.decompress(base64.b64decode(_FONT_B64))
        unpacked = np.unpackbits(np.frombuffer(raw, dtype=np.uint8)).reshape(256, 16, 8)
        # Pre-scale x2: 256 chars, 32 height, 16 width
        _font_cache = np.repeat(np.repeat(unpacked, 2, axis=1), 2, axis=2).astype(bool)
    return _font_cache

def _draw_text(img: np.ndarray, text: str, x: int, y: int, color: tuple) -> None:
    font = _get_font()
    chars = [ord(c) if 0 <= ord(c) < 256 else 63 for c in text]
    for i, c in enumerate(chars):
        g = font[c]
        cx = x + i * 16
        if cx + 16 > img.shape[1] or y + 32 > img.shape[0]:
            break
        img[y:y + 32, cx:cx + 16][g] = color

def _render_page(lines: List[str], start_line: int, filename: str, page_idx: int, total_pages: int, sha_prefix: str) -> np.ndarray:
    if np is None:
        raise RuntimeError("NumPy is required for text slide rendering.")

    display_filename = (filename[:35] + "...") if len(filename) > 38 else filename
    header_text = f"FILE: {display_filename} | SHA256: {sha_prefix}... | PAGE: {page_idx}/{total_pages}"

    img = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    img[:] = BG_COLOR

    # Header bar
    img[0:70, :] = (28, 28, 28)
    _draw_text(img, header_text, 50, 19, HEADER_COLOR)

    # Content
    y = 90
    for idx, line in enumerate(lines):
        line_no = f"{start_line + idx:04d} | "
        _draw_text(img, line_no, 50, y, LINE_NO_COLOR)
        expanded_line = line.expandtabs(4)[:CHARS_PER_LINE]
        _draw_text(img, expanded_line, 160, y, TEXT_COLOR)
        y += 32

    return img

def synthesize_text_video(
    input_path: str,
    output_path: str,
    hold_per_page: float = 6.0,
    fps: int = 15,
    ffmpeg_bin: Optional[str] = None,
    max_pages: int = 150
) -> str:
    ffmpeg = ffmpeg_bin or os.environ.get("CASTCAST_FFMPEG") or shutil.which("ffmpeg") or "/data/data/com.termux/files/usr/bin/ffmpeg"

    with open(input_path, "r", encoding="utf-8", errors="replace") as f:
        all_lines = [ln.rstrip("\r\n") for ln in f.readlines()]
    if not all_lines:
        all_lines = ["<empty file>"]

    filename = os.path.basename(input_path)
    with open(input_path, "rb") as f:
        sha_prefix = hashlib.sha256(f.read()).hexdigest()[:16]

    pages = []
    for i in range(0, len(all_lines), LINES_PER_PAGE):
        chunk = all_lines[i:i + LINES_PER_PAGE]
        pages.append((chunk, i + 1))

    # Guard against memory/disk exhaustion on huge files by capping pages and dynamically
    # speeding up pacing (scrollable pace) when there are many pages.
    if len(pages) > max_pages:
        pages = pages[:max_pages]
        pages[-1][0].append(f"--- [TRUNCATED: Showing first {max_pages} pages to prevent device memory exhaustion] ---")

    total_pages = len(pages)
    if total_pages > 25 and hold_per_page > 2.0:
        # Accelerate page transitions so large documents scroll smoothly without stalling
        hold_per_page = max(1.5, min(hold_per_page, 150.0 / total_pages))

    frames_per_page = max(1, int(hold_per_page * fps))

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{WIDTH}x{HEIGHT}",
        "-r", str(fps), "-i", "-",
        "-c:v", "libx264", "-crf", "18", "-preset", "ultrafast",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", output_path
    ]

    ff = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    assert ff.stdin is not None

    stderr_output = b""
    try:
        for page_num, (chunk, start_line) in enumerate(pages, 1):
            frame = _render_page(chunk, start_line, filename, page_num, total_pages, sha_prefix)
            frame_bytes = frame.tobytes()
            for _ in range(frames_per_page):
                ff.stdin.write(frame_bytes)
    except (BrokenPipeError, OSError):
        pass
    finally:
        try:
            ff.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        if ff.stderr is not None:
            stderr_output = ff.stderr.read()
            ff.stderr.close()
        ff.wait()

    if ff.returncode != 0:
        err_msg = stderr_output.decode("utf-8", errors="replace").strip()
        detail = f": {err_msg}" if err_msg else ""
        raise RuntimeError(f"FFmpeg failed with exit code {ff.returncode} synthesizing text video{detail}")

    return output_path

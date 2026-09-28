# synchronization-map: section=media-routing; role=text-synthesizer; boundaries=core-service; doc=docs/SYNCHRONIZATION_MAP.md
"""Synthesizes high-contrast monospaced code/text slides into a 1080p MP4 stream."""

import hashlib
import os
import shutil
import subprocess
from typing import List, Optional
import cv2
import numpy as np

WIDTH, HEIGHT = 1920, 1080
LINES_PER_PAGE = 30
CHARS_PER_LINE = 90
BG_COLOR = (18, 18, 18)        # Charcoal
TEXT_COLOR = (240, 240, 240)    # White
HEADER_COLOR = (0, 200, 255)    # Cyan
LINE_NO_COLOR = (120, 120, 120) # Grey

def _render_page(lines: List[str], start_line: int, filename: str, page_idx: int, total_pages: int, sha_prefix: str) -> np.ndarray:
    img = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    img[:] = BG_COLOR

    # Header bar
    cv2.rectangle(img, (0, 0), (WIDTH, 70), (28, 28, 28), -1)
    header_text = f"FILE: {filename} | SHA256: {sha_prefix}... | PAGE: {page_idx}/{total_pages}"
    cv2.putText(img, header_text, (50, 45), cv2.FONT_HERSHEY_SIMPLEX, 0.8, HEADER_COLOR, 2, cv2.LINE_AA)

    # Content
    y = 120
    for idx, line in enumerate(lines):
        line_no = f"{start_line + idx:04d} | "
        cv2.putText(img, line_no, (50, y), cv2.FONT_HERSHEY_PLAIN, 1.2, LINE_NO_COLOR, 1, cv2.LINE_AA)
        cv2.putText(img, line[:CHARS_PER_LINE], (140, y), cv2.FONT_HERSHEY_SIMPLEX, 0.65, TEXT_COLOR, 1, cv2.LINE_AA)
        y += 30

    return img

def synthesize_text_video(
    input_path: str,
    output_path: str,
    hold_per_page: float = 6.0,
    fps: int = 15,
    ffmpeg_bin: Optional[str] = None
) -> str:
    ffmpeg = ffmpeg_bin or shutil.which("ffmpeg") or "/data/data/com.termux/files/usr/bin/ffmpeg"

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

    total_pages = len(pages)
    frames_per_page = int(hold_per_page * fps)

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
    finally:
        ff.stdin.close()
        if ff.stderr is not None:
            stderr_output = ff.stderr.read()
            ff.stderr.close()
        ff.wait()

    if ff.returncode != 0:
        err_msg = stderr_output.decode("utf-8", errors="replace").strip()
        detail = f": {err_msg}" if err_msg else ""
        raise RuntimeError(f"FFmpeg failed with exit code {ff.returncode} synthesizing text video{detail}")

    return output_path

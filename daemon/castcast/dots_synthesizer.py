# synchronization-map: section=media-routing; role=dots-synthesizer; boundaries=core-service; doc=docs/SYNCHRONIZATION_MAP.md
"""Synthesizes high-contrast binary dot matrix videos using the dotslib protocol."""

import os
import shutil
import subprocess
import sys
from typing import Optional

# Ensure dotslib from /home/deck/dots is importable
DOTS_DIR = "/home/deck/dots"
if DOTS_DIR not in sys.path and os.path.isdir(DOTS_DIR):
    sys.path.insert(0, DOTS_DIR)

import dotslib as D

def synthesize_dots_video(
    input_path: str,
    output_path: str,
    is_ultra: bool = True,
    repeat: int = 8,
    fps: int = 15,
    ffmpeg_bin: Optional[str] = None
) -> str:
    ffmpeg = ffmpeg_bin or shutil.which("ffmpeg") or "/data/data/com.termux/files/usr/bin/ffmpeg"
    scale = 24 if is_ultra else 12
    W, H = D.GRID_W * scale, D.GRID_H * scale

    with open(input_path, "rb") as f:
        payload = f.read()

    header, sectors = D.build_stream(payload)
    wires = [D.encode_sector(seq, c) for seq, c in sectors]
    n_frames = D.frames_for(len(payload))
    n_video = (n_frames + 1) * repeat

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}",
        "-r", str(fps), "-i", "-",
        "-c:v", "libx264", "-crf", "18", "-preset", "ultrafast",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", output_path
    ]

    ff = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    assert ff.stdin is not None

    stderr_output = b""
    try:
        last_src_f = None
        cached_frame_bytes = None
        for f in range(1, n_video + 1):
            src_f = (f - 1) // repeat + 1
            if src_f != last_src_f:
                if src_f == 1:
                    wa, wb = wires[0], None
                else:
                    i0 = 2 * src_f - 3
                    wa = wires[i0] if i0 < len(wires) else None
                    wb = wires[i0 + 1] if i0 + 1 < len(wires) else None
                g = D._cell_grid(wa, wb)
                cached_frame_bytes = D.render_frame(g, scale=scale).tobytes()
                last_src_f = src_f
            ff.stdin.write(cached_frame_bytes)
    finally:
        ff.stdin.close()
        if ff.stderr is not None:
            stderr_output = ff.stderr.read()
            ff.stderr.close()
        ff.wait()

    if ff.returncode != 0:
        err_msg = stderr_output.decode("utf-8", errors="replace").strip()
        detail = f": {err_msg}" if err_msg else ""
        raise RuntimeError(f"FFmpeg failed with exit code {ff.returncode} synthesizing dots video{detail}")

    return output_path

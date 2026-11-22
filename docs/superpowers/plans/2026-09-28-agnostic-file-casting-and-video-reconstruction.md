# Agnostic File Casting & Optical Video Reconstruction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable CastCast to accept any arbitrary file (.md, .py, .apk, .exe, .zip), synthesize it into an optical video stream (human-readable text slides for code/text, or high-contrast dot matrix for binary), cast it to Chromecast via Shaka Player, and blind-reconstruct `/home/deck/test.zip` from captured video to extract `output.pdf`.

**Architecture:**
- **Content Inspector:** Heuristic analysis classifying files into `TEXT_CODE` (UTF-8, printable) vs `BINARY` (non-printable / control bytes).
- **Text Slide Synthesizer:** Renders readable monospaced code viewer slides with line numbers and file metadata header (1080p MP4).
- **Binary Dots Synthesizer:** Encodes binary payloads into high-contrast video using `dotslib` (160x90 grid, 4K/1080p, repeat-8 redundancy).
- **Service Integration:** Integrates synthesizers into `CastService.cast()` in `service.py`, serving the generated MP4 via the local media server.
- **Blind Extraction Harness:** Reconstructs the transmitted file from OBS recording or `/dev/video0`, identifies ZIP magic bytes, extracts `output.pdf`, and verifies SHA-256.

**Tech Stack:** Python 3, OpenCV (`cv2`), NumPy, Reed-Solomon (`reedsolo`), FFmpeg, PyChromecast, Shaka Player, pytest, vitest.

**Spec:** [`docs/superpowers/specs/2026-09-28-agnostic-file-casting-and-video-reconstruction-design.md`](file:///home/deck/CastCast/docs/superpowers/specs/2026-09-28-agnostic-file-casting-and-video-reconstruction-design.md)

## Global Constraints
- All modified repo files must be owned by `deck:deck`.
- Must not break existing 174 daemon unit tests and 31 frontend vitest tests.
- `python scripts/check_sync_headers.py` must pass with code 0.
- Mandatory code review gate via `requesting-code-review` before declaring completion.

---

### Task 1: Content Inspector Subsystem

**Files:**
- Create: `daemon/castcast/inspect_content.py`
- Create: `daemon/tests/test_castcast/test_inspect_content.py`

**Interfaces:**
- Produces: `inspect_file_content(path: str) -> str` returning `"TEXT_CODE"` or `"BINARY"`.

- [ ] **Step 1: Write the failing tests**

Create `daemon/tests/test_castcast/test_inspect_content.py`:
```python
import tempfile
import unittest
from pathlib import Path
from castcast.inspect_content import inspect_file_content, ContentType

class TestContentInspector(unittest.TestCase):
    def test_detects_plaintext_and_markdown(self):
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write("# Hello World\nThis is a human readable markdown note.\n")
            f.flush()
            self.assertEqual(inspect_file_content(f.name), ContentType.TEXT_CODE)

    def test_detects_source_code(self):
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
            f.write("def hello():\n    print('Hello world')\n")
            f.flush()
            self.assertEqual(inspect_file_content(f.name), ContentType.TEXT_CODE)

    def test_detects_binary_zip_file(self):
        with tempfile.NamedTemporaryFile("wb", suffix=".zip", delete=False) as f:
            f.write(b"PK\x03\x04\x14\x00\x00\x00\x08\x00" + b"\x00" * 100)
            f.flush()
            self.assertEqual(inspect_file_content(f.name), ContentType.BINARY)

    def test_detects_binary_executable(self):
        with tempfile.NamedTemporaryFile("wb", suffix=".bin", delete=False) as f:
            f.write(b"\x7fELF\x02\x01\x01\x00\x00" + bytes(range(256)))
            f.flush()
            self.assertEqual(inspect_file_content(f.name), ContentType.BINARY)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=daemon uv run --project daemon pytest daemon/tests/test_castcast/test_inspect_content.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'castcast.inspect_content'`

- [ ] **Step 3: Write implementation**

Create `daemon/castcast/inspect_content.py`:
```python
# synchronization-map: section=media-routing; role=content-inspector; boundaries=core-service; doc=docs/SYNCHRONIZATION_MAP.md
"""Inspects file content heuristics to determine whether content is readable text/code or binary."""

import os
from enum import Enum

class ContentType(str, Enum):
    TEXT_CODE = "TEXT_CODE"
    BINARY = "BINARY"

def inspect_file_content(path: str, sample_size: int = 4096) -> ContentType:
    if not os.path.isfile(path):
        return ContentType.BINARY

    try:
        with open(path, "rb") as f:
            sample = f.read(sample_size)
    except OSError:
        return ContentType.BINARY

    if not sample:
        return ContentType.TEXT_CODE

    # Check for NUL bytes which rarely occur in clean text/code
    if b"\x00" in sample:
        return ContentType.BINARY

    # Test UTF-8 decoding
    try:
        decoded = sample.decode("utf-8")
    except UnicodeDecodeError:
        return ContentType.BINARY

    # Ratio of printable ASCII and standard whitespace
    printable = sum(1 for c in decoded if c.isprintable() or c in "\r\n\t")
    if printable / len(decoded) >= 0.90:
        return ContentType.TEXT_CODE

    return ContentType.BINARY
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=daemon uv run --project daemon pytest daemon/tests/test_castcast/test_inspect_content.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add daemon/castcast/inspect_content.py daemon/tests/test_castcast/test_inspect_content.py
git commit -m "feat(daemon): add content inspector for text vs binary classification"
```

---

### Task 2: Binary Dots Synthesizer

**Files:**
- Create: `daemon/castcast/dots_synthesizer.py`
- Create: `daemon/tests/test_castcast/test_dots_synthesizer.py`

**Interfaces:**
- Consumes: `/home/deck/dots/dotslib.py`
- Produces: `synthesize_dots_video(input_path: str, output_path: str, is_ultra: bool = True, repeat: int = 8, fps: int = 15) -> str`

- [ ] **Step 1: Write the failing tests**

Create `daemon/tests/test_castcast/test_dots_synthesizer.py`:
```python
import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from castcast.dots_synthesizer import synthesize_dots_video

class TestDotsSynthesizer(unittest.TestCase):
    @patch('subprocess.Popen')
    def test_synthesizes_video_from_payload(self, mock_popen):
        proc_mock = MagicMock()
        proc_mock.returncode = 0
        proc_mock.stdin = MagicMock()
        mock_popen.return_value = proc_mock

        with tempfile.NamedTemporaryFile("wb", delete=False) as in_f:
            in_f.write(b"SAMPLE_PAYLOAD_BYTES" * 50)
            in_f.flush()
            out_path = in_f.name + ".mp4"

            res = synthesize_dots_video(in_f.name, out_path, is_ultra=True, repeat=2)
            self.assertEqual(res, out_path)
            self.assertTrue(mock_popen.called)
            cmd = mock_popen.call_args[0][0]
            self.assertEqual(cmd[0], "ffmpeg")
            self.assertIn("-s", cmd)
            self.assertIn("3840x2160", cmd)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=daemon uv run --project daemon pytest daemon/tests/test_castcast/test_dots_synthesizer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'castcast.dots_synthesizer'`

- [ ] **Step 3: Write implementation**

Create `daemon/castcast/dots_synthesizer.py`:
```python
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

    ff = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    assert ff.stdin is not None

    try:
        for f in range(1, n_video + 1):
            src_f = (f - 1) // repeat + 1
            if src_f == 1:
                wa, wb = wires[0], None
            else:
                i0 = 2 * src_f - 3
                wa = wires[i0] if i0 < len(wires) else None
                wb = wires[i0 + 1] if i0 + 1 < len(wires) else None
            g = D._cell_grid(wa, wb)
            frame_bytes = D.render_frame(g, scale=scale).tobytes()
            ff.stdin.write(frame_bytes)
    finally:
        ff.stdin.close()
        ff.wait()

    if ff.returncode != 0:
        raise RuntimeError(f"FFmpeg failed with exit code {ff.returncode} synthesizing dots video")

    return output_path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=daemon uv run --project daemon pytest daemon/tests/test_castcast/test_dots_synthesizer.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add daemon/castcast/dots_synthesizer.py daemon/tests/test_castcast/test_dots_synthesizer.py
git commit -m "feat(daemon): add binary dots video synthesizer"
```

---

### Task 3: Text Code Slide Synthesizer

**Files:**
- Create: `daemon/castcast/text_synthesizer.py`
- Create: `daemon/tests/test_castcast/test_text_synthesizer.py`

**Interfaces:**
- Produces: `synthesize_text_video(input_path: str, output_path: str, hold_per_page: float = 6.0) -> str`

- [ ] **Step 1: Write the failing tests**

Create `daemon/tests/test_castcast/test_text_synthesizer.py`:
```python
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from castcast.text_synthesizer import synthesize_text_video

class TestTextSynthesizer(unittest.TestCase):
    @patch('subprocess.Popen')
    def test_synthesizes_text_slides_video(self, mock_popen):
        proc_mock = MagicMock()
        proc_mock.returncode = 0
        proc_mock.stdin = MagicMock()
        mock_popen.return_value = proc_mock

        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as in_f:
            in_f.write("print('Hello from CastCast')\n" * 10)
            in_f.flush()
            out_path = in_f.name + ".mp4"

            res = synthesize_text_video(in_f.name, out_path, hold_per_page=2.0)
            self.assertEqual(res, out_path)
            self.assertTrue(mock_popen.called)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=daemon uv run --project daemon pytest daemon/tests/test_castcast/test_text_synthesizer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'castcast.text_synthesizer'`

- [ ] **Step 3: Write implementation**

Create `daemon/castcast/text_synthesizer.py`:
```python
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
        cv2.putText(img, line_no, (50, y), cv2.FONT_HERSHEY_MONOSPACE, 0.6, LINE_NO_COLOR, 1, cv2.LINE_AA)
        cv2.putText(img, line[:CHARS_PER_LINE], (140, y), cv2.FONT_HERSHEY_MONOSPACE, 0.65, TEXT_COLOR, 1, cv2.LINE_AA)
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

    ff = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    assert ff.stdin is not None

    try:
        for page_num, (chunk, start_line) in enumerate(pages, 1):
            frame = _render_page(chunk, start_line, filename, page_num, total_pages, sha_prefix)
            frame_bytes = frame.tobytes()
            for _ in range(frames_per_page):
                ff.stdin.write(frame_bytes)
    finally:
        ff.stdin.close()
        ff.wait()

    if ff.returncode != 0:
        raise RuntimeError(f"FFmpeg failed with exit code {ff.returncode} synthesizing text video")

    return output_path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=daemon uv run --project daemon pytest daemon/tests/test_castcast/test_text_synthesizer.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add daemon/castcast/text_synthesizer.py daemon/tests/test_castcast/test_text_synthesizer.py
git commit -m "feat(daemon): add text code slide video synthesizer"
```

---

### Task 4: Integrate Non-Media Synthesizers into CastService

**Files:**
- Modify: `daemon/castcast/service.py`
- Modify: `daemon/tests/test_castcast/test_service_queue.py`

**Interfaces:**
- Consumes: `inspect_file_content`, `synthesize_dots_video`, `synthesize_text_video`
- Produces: `CastService.cast(path)` seamlessly renders and casts non-media files.

- [ ] **Step 1: Write unit tests for non-media casting in `test_service_queue.py`**

Add tests:
```python
    @patch('castcast.service.synthesize_dots_video')
    @patch('castcast.service.inspect_file_content', return_value='BINARY')
    def test_cast_synthesizes_binary_file(self, mock_inspect, mock_synth_dots):
        mock_synth_dots.side_effect = lambda inp, out, **kw: out
        res = self.svc.cast("/home/deck/test.zip")
        self.assertEqual(res.get("synthesized"), True)
        self.assertEqual(res.get("mode"), "binary")
        self.svc.supervisor.load.assert_called_once()

    @patch('castcast.service.synthesize_text_video')
    @patch('castcast.service.inspect_file_content', return_value='TEXT_CODE')
    def test_cast_synthesizes_text_code_file(self, mock_inspect, mock_synth_text):
        mock_synth_text.side_effect = lambda inp, out, **kw: out
        res = self.svc.cast("/home/deck/hello.py")
        self.assertEqual(res.get("synthesized"), True)
        self.assertEqual(res.get("mode"), "text")
        self.svc.supervisor.load.assert_called_once()
```

- [ ] **Step 2: Update `CastService.cast()` in `daemon/castcast/service.py`**

In `CastService.cast()`:
When `not is_url` and `os.path.isfile(path)`:
Before regular preflight fails for non-video extensions, check if `ext not in VIDEO_EXTENSIONS`:
```python
        if not is_url and os.path.isfile(path):
            ext = os.path.splitext(path)[1].lower()
            if ext not in VIDEO_EXTENSIONS:
                content_type = inspect_file_content(path)
                rendered_dir = os.path.join(self.media_roots[0], ".castcast", "rendered")
                os.makedirs(rendered_dir, exist_ok=True)
                stem = os.path.splitext(os.path.basename(path))[0]
                is_ultra = bool(getattr(self.supervisor, "is_ultra", True))

                if content_type == ContentType.BINARY:
                    out_video = os.path.join(rendered_dir, f"{stem}_dots.mp4")
                    self.log(f"Synthesizing binary dot matrix video for {path}")
                    synthesize_dots_video(path, out_video, is_ultra=is_ultra, repeat=8)
                    mode = "binary"
                else:
                    out_video = os.path.join(rendered_dir, f"{stem}_slides.mp4")
                    self.log(f"Synthesizing code slide video for {path}")
                    synthesize_text_video(path, out_video, hold_per_page=6.0)
                    mode = "text"

                url = self.media_server.url_for(out_video)
                self.supervisor.load(
                    url,
                    content_type="video/mp4",
                    title=f"[Data Stream] {os.path.basename(path)}",
                    source_path=path,
                    position=0.0
                )
                return {"casting": True, "synthesized": True, "mode": mode, "url": url}
```

- [ ] **Step 3: Run pytest and check sync headers**

Run: `PYTHONPATH=daemon uv run --project daemon pytest daemon/tests/test_castcast/test_service_queue.py -v`
Expected: PASS
Run: `pnpm run build && python scripts/check_sync_headers.py`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add daemon/castcast/service.py daemon/tests/test_castcast/test_service_queue.py dist/
git commit -m "feat(daemon): route non-media files to dots and text synthesizers"
```

---

### Task 5: Blind Extraction Harness & Live Test with `/home/deck/test.zip`

**Files:**
- Create: `dots/dots-blind-extract.py`

**Interfaces:**
- Input: Video file (from OBS recording `/home/deck/*.mp4`) or camera index `/dev/video0`.
- Output: Automatically reconstructs payload, detects magic bytes, unzips archive, extracts `output.pdf`.

- [ ] **Step 1: Write `dots/dots-blind-extract.py`**

```python
#!/usr/bin/env python3
"""Blindly extracts and recovers payload from a captured video stream or recording."""

import os
import subprocess
import sys
import tempfile
import zipfile

DOTS_DIR = "/home/deck/dots"
if DOTS_DIR not in sys.path:
    sys.path.insert(0, DOTS_DIR)

import cv2
import dotslib as D

def blind_decode_frames(video_source: str, stride: int = 2) -> bytes:
    col = D.Collector()
    cap = cv2.VideoCapture(int(video_source) if video_source.isdigit() else video_source)
    if not cap.isOpened():
        raise SystemExit(f"Cannot open video source: {video_source}")

    first = True
    n = 0
    while True:
        ok, img = cap.read()
        if not ok:
            break
        n += 1
        if first:
            first = False
        elif stride > 1 and n % stride:
            continue

        g = D.extract_cells(img)
        if g is not None:
            col.feed(g)
        if col.complete():
            break

    assembled = col.assemble()
    if assembled is None:
        raise RuntimeError(f"Failed to assemble stream: {col.status()}")
    return assembled

def main():
    if len(sys.argv) < 2:
        print("Usage: dots-blind-extract.py <video.mp4 | /dev/videoN> [out_dir]")
        sys.exit(1)

    source = sys.argv[1]
    out_dir = sys.argv[2] if len(sys.argv) > 2 else "/tmp/blind_extracted"
    os.makedirs(out_dir, exist_ok=True)

    print(f"[*] Decoding stream from {source}...")
    payload = blind_decode_frames(source)
    print(f"[+] Successfully recovered {len(payload)} bytes!")

    # Inspect magic bytes without prior knowledge of filename
    if payload.startswith(b"PK\x03\x04"):
        print("[+] Detected ZIP archive magic bytes (PK\\x03\\x04)!")
        zip_path = os.path.join(out_dir, "recovered.zip")
        with open(zip_path, "wb") as f:
            f.write(payload)

        with zipfile.ZipFile(zip_path) as zf:
            print(f"[+] Archive contents: {zf.namelist()}")
            zf.extractall(out_dir)
            print(f"[+] Extracted archive to {out_dir}")
    elif payload.startswith(b"\x7fELF"):
        print("[+] Detected ELF binary magic bytes!")
        out_bin = os.path.join(out_dir, "recovered.elf")
        with open(out_bin, "wb") as f:
            f.write(payload)
    else:
        print("[+] Unrecognized magic bytes; saving as raw binary.")
        out_bin = os.path.join(out_dir, "recovered.bin")
        with open(out_bin, "wb") as f:
            f.write(payload)

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Cast `/home/deck/test.zip` through CastCast**

Run: Cast `/home/deck/test.zip` to Chromecast Ultra via CastCast API.

- [ ] **Step 3: Capture with Elgato / OBS and Run Blind Extractor**

Feed recorded clip into `dots-blind-extract.py`.
Verify that `output.pdf` extracts cleanly and hashes match.

- [ ] **Step 4: Mandatory Code Review Gate**

Dispatch code reviewer subagent via `requesting-code-review` and address all feedback.

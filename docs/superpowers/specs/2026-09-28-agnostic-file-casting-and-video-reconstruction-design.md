# Agnostic Non-Media File Casting & Video Reconstruction Specification

**Date:** 2026-09-28  
**Author:** Pair Programming Session (deck & Antigravity)  
**Status:** In Review  

---

## 1. Overview & Goals

This specification establishes an **agnostic file-casting and optical video reconstruction pipeline** for CastCast.

Currently, CastCast categorizes input URLs into YouTube, Amazon Prime Video (Widevine), or local media files. Non-media files (e.g. `.md`, `.py`, `.apk`, `.exe`, `.zip`) are rejected during pre-flight checks because Shaka Player and Chromecast reject non-media containers (`DEMUXER_ERROR_COULD_NOT_PARSE`).

Under this new architecture:
1. **Universal Acceptance:** CastCast accepts any file shared via Android intent or CLI.
2. **Dual-Mode Video Synthesis:**
   - **Text & Source Code Mode (`.md`, `.py`, `.c`, plain text):** Automatically detected via content heuristics (valid UTF-8, low non-printable byte entropy). Synthesizes an onscreen monospaced code viewer / teleprompter video (1080p H.264) displaying file metadata, line numbers, and readable text slides (5–8s per page).
   - **Binary Data Mode (`.zip`, `.apk`, `.exe`, `.bin`):** Automatically detected when unprintable/control characters or high entropy bytes predominate. Synthesizes a high-contrast machine-reconstructible visual **Byte/Dot Matrix** video using the verified `dotslib` protocol (with repeat-8 frame redundancy and Reed-Solomon/CRC error correction).
3. **Chromecast Playback:** The synthesized video is served by CastCast's local media server (`http://<LAN_IP>:<PORT>/...`) and loaded on the Chromecast Ultra via Shaka Player.
4. **Blind Video Reconstruction:** The incoming HDMI video captured via the Elgato Cam Link 4K (`/dev/video0`) or OBS recording is processed by a blind decoder that:
   - Does not use the original filename or metadata from memory.
   - Extracts the frames and decodes the payload bytes.
   - Inspects the reconstructed file's magic bytes (e.g. `PK\x03\x04` for ZIP).
   - Verifies integrity against the source and extracts the contents (`output.pdf`).

---

## 2. Architecture & Data Flow

```
                      +--------------------------------------+
                      |      Shared Input (File or URL)      |
                      +------------------+-------------------+
                                         |
         +-------------------------------+-------------------------------+
         |                               |                               |
    [YouTube URL]                [Amazon Prime URL]                [Local File]
         |                               |                               |
    yt-dlp Queue              Widevine MPD Proxy + HTTPS             Preflight
         |                               |                               |
         |                               |               +---------------+---------------+
         |                               |               |                               |
         |                               |       [Standard Video/Audio]          [Non-Media File]
         |                               |               |                               |
         |                               |      Direct Play / Transcode         Content Inspector
         |                               |                                               |
         |                               |                               +---------------+---------------+
         |                               |                               |                               |
         |                               |                       [Text/Markdown/Code]            [Binary (.zip, .apk, .exe)]
         |                               |                               |                               |
         |                               |                       Render Code Slides            Render dotslib Matrix
         |                               |                       (Monospaced Video)              (4K/1080p dots.mp4)
         |                               |                               |                               |
         +-------------------------------+-------------------------------+-------------------------------+
                                         |
                                         v
                         +-------------------------------+
                         |   Chromecast Ultra Playback   |
                         |     (Shaka Player Receiver)   |
                         +---------------+---------------+
                                         |
                                    HDMI Output
                                         |
                         +---------------+---------------+
                         |    PSVR HDCP Passthrough      |
                         +---------------+---------------+
                                         |
                         +---------------+---------------+
                         |   Elgato Cam Link 4K Capture  |
                         |     (/dev/video0 or OBS)      |
                         +---------------+---------------+
                                         |
                         +---------------+---------------+
                         |        Blind Decoder          |
                         |  (dots-decode / OCR pipeline) |
                         +---------------+---------------+
                                         |
                         +---------------+---------------+
                         |   Reconstructed Binary File   |
                         |     (Extract & Verify)        |
                         +-------------------------------+
```

---

## 3. Subsystems & Components

### 3.1 Content Inspector (`castcast/inspect_content.py`)
- Analyzes the first 4KB of any non-video input file:
  - Tests UTF-8 decoding.
  - Computes ratio of printable ASCII + standard whitespace vs control/null bytes.
  - Computes Shannon entropy.
- **Classification Verdict:**
  - `TEXT_CODE`: Printable ratio $> 90\%$ and zero NUL bytes.
  - `BINARY`: Printable ratio $\le 90\%$ or contains NUL bytes.

### 3.2 Text Code Slide Synthesizer (`castcast/text_synthesizer.py`)
- For `TEXT_CODE`:
  - Splits text into pages (e.g. 35 lines per 1080p page, 80 characters wide).
  - Renders frames using monospaced font with high contrast (e.g. dark charcoal background `#121212`, crisp white/cyan text).
  - Header banner: Filename, File Size, SHA-256 (first 16 chars), Page X of Y.
  - Line numbers: `001 | ...`.
  - Pacing: Configurable hold time (default 6 seconds per page).
  - Output: MP4 encoded via FFmpeg H.264 `yuv420p`.

### 3.3 Binary Dot Matrix Synthesizer (`castcast/dots_synthesizer.py`)
- For `BINARY`:
  - Bridges CastCast directly with the verified `dotslib` engine (`/home/deck/dots/dotslib.py`).
  - Encodes the binary payload into sectors (690 bytes wire per sector, 2 sectors per frame).
  - Applies repeat mode (`--repeat 8` default) to guarantee capture resilience against frame drops or V4L2 jitter.
  - Outputs `dots-long.mp4` cached in `media_roots[0]/.castcast/rendered/`.

### 3.4 Media Server & Service Dispatch (`castcast/service.py`)
- Updates `CastService.cast(path)`:
  - If `preflight()` detects non-media file or binary, calls the appropriate synthesizer (`text_synthesizer` or `dots_synthesizer`).
  - Returns `{"casting": True, "synthesized": True, "mode": "text"|"binary"}`.
  - Serves the generated MP4 over the existing local HTTP media server.

### 3.5 Blind Decoder & Extraction Harness (`dots/dots-blind-extract.py`)
- Reads frames from:
  - Direct camera stream (`/dev/video0`), OR
  - OBS recorded file (`/home/deck/<recording>.mp4`).
- Feeds frames into `dotslib.Collector()`.
- Once `col.complete()` is reached:
  - Assembles the raw bytes without using any prior filename from memory.
  - Reads the first 4 bytes of magic header:
    - If `50 4B 03 04` $\to$ ZIP archive (`reconstructed.zip`).
    - If `7F 45 4C 46` $\to$ ELF binary (`reconstructed.elf`).
    - If `%PDF-` $\to$ PDF document (`reconstructed.pdf`).
  - Unzips or inspects the reconstructed file:
    ```bash
    unzip /tmp/reconstructed.zip -d /tmp/extracted_challenge/
    ```
  - Compares SHA-256 with source to prove 100% byte fidelity.

---

## 4. Verification & Acceptance Criteria

1. **Test Payload:** `/home/deck/test.zip` (41,972 bytes).
2. **Transmission:** Cast to Chromecast Ultra (`192.168.1.5:8009`) via CastCast.
3. **Capture:** Captured via Elgato Cam Link 4K (or OBS recording).
4. **Reconstruction:** `dots-blind-extract` reconstructs the file byte-identically (SHA-256 `ec1b150ae45db5ed4d3fec6de96b0d86cfc8ae7a97629000dcd6848dcd12425e`).
5. **Extraction:** `unzip` extracts `output.pdf` without error.
6. **Code Hygiene:** All existing 174 daemon unit tests and frontend vitest tests remain passing; sync headers maintained.

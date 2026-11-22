# Changelog

All notable changes to CastCast are documented in this file.

## [2.05] - 2026-11-22

### Added
- **Universal Non-Media File Casting**:
  - Merged the universal file sharing pipeline (`feat/universal-file-sharing`) into the standalone embedded Android daemon (`prototype/embedded-android`).
  - Implemented automatic file content inspection in `daemon/castcast/inspect_content.py` to classify files into `TEXT_CODE` vs `BINARY` using UTF-8 decoding and printable character ratio heuristics.
  - Added `daemon/castcast/text_synthesizer.py`: synthesizes readable text, markdown, scripts, and logs into a 1080p high-contrast monospaced MP4 slide video stream with line numbers, file metadata, and SHA-256 header tags.
  - Added `daemon/castcast/dots_synthesizer.py` and embedded `daemon/castcast/dotslib.py`: converts raw binary files (`.apk`, `.exe`, `.zip`, `.bin`, etc.) into an optical dot matrix HDMI covert data stream with Reed-Solomon forward error correction.
- **Embedded Android Native Share Bridge**:
  - Updated `RootProvisionPlugin.java` with intent filters for `ACTION_SEND`, `ACTION_VIEW`, and `ACTION_SEND_MULTIPLE` (`*/*` mimeTypes).
  - Automatically queries Android `content://` URIs and stages shared files into `Download/CastCast/Chromecast/inbox` (or internal cache fallback) before notifying the web frontend via the `sharedUrl` event.
  - Added Chaquopy pip dependencies `numpy`, `pillow`, and `reedsolo` to `android/app/build.gradle` (using official Chaquopy Python 3.13 ARM64 wheels).

### Fixed
- **Chaquopy Python 3.13 Wheel Compatibility & OpenCV Elimination**:
  - Replaced OpenCV-based text rendering in `text_synthesizer.py` with Pillow (`PIL.Image`, `PIL.ImageDraw`), eliminating `opencv-python-headless` (which lacks precompiled `cp313-android_24_arm64_v8a` wheels in Chaquopy's repository).
  - Added pure NumPy color expansion fallback in `dotslib.py:render_frame` (`np.repeat(img[:, :, np.newaxis], 3, axis=2)`).
  - Isolated `reedsolo` and `numpy` imports from `cv2` into individual `try/except` blocks in `dotslib.py`, ensuring Reed-Solomon FEC and optical frame generation function seamlessly without OpenCV.
- **Shared URL / Text Extraction Sequence**:
  - Resolved a critical ordering bug in `RootProvisionPlugin.java` where `intent.removeExtra(Intent.EXTRA_TEXT)` was called prior to evaluating `ACTION_SEND` text payloads. Shared links (e.g. YouTube, Prime Video) now extract reliably.
- **Large File Pacing and Memory Protection**:
  - In `text_synthesizer.py`, added page capping (`max_pages=150`) and accelerated scroll pacing (`hold_per_page = max(1.5, min(hold_per_page, 150.0 / total_pages))`) to prevent oversized documents from stalling playback or taking hours to generate.
  - In `dots_synthesizer.py` and `service.py`, enforced a strict 10 MB payload limit for optical dots streams with clear error feedback to prevent process memory exhaustion or out-of-memory crashes on device.
  - Re-routed synthesis scratch output to `self.work_dir/rendered` with unique file hash suffixes to prevent name collisions and ensure files are always written to managed app storage.
- **CI Storage Isolation**:
  - Configured `CastService` to default to `~/Download` when `/storage/emulated/0` is unmounted on non-Android Linux environments, and isolated `TestServiceQueue` with temporary test directories to prevent permissions errors in CI runners.

---

## [2.04] - 2026-11-22

### Fixed
- **Localhost.run Nested Subdomain Extraction**:
  - Extracted `TUNNEL_URL_RE` in `daemon/castcast/mediaserver.py` matching localhost.run's nested subdomain scheme (`<id>.app.lhr.life`, `*.lhrtunnel.pro`, `*.lhr.rocks`).
  - Anchored regex with `(?![a-z0-9]|\.[a-z0-9-])` negative lookahead so URLs followed by sentence punctuation (such as trailing periods) are properly matched while rejecting illegitimate domain extensions.
  - Resolved the persistent timeout and reconnection loop: `"https tunnel reconnecting after waiting for the public https url failed (timeouterror)"`.
- **SSH Process Stdout Draining**:
  - Removed premature `break` in `_start_system_tunnel` line reader to ensure `proc.stdout` continues to be drained throughout the tunnel session, avoiding OS pipe buffer deadlocks.
- **Mobile Network Timeout**:
  - Increased public URL wait timeout from 5 seconds to 15 seconds in `_run_embedded_tunnel` to accommodate cellular and high-latency mobile Wi-Fi handshakes.
- **Frontend Storage Protection**:
  - Wrapped `localStorage` accesses in `src/app/App.tsx` and `src/app/lib/daemon.ts` with `try / catch` and `typeof window !== "undefined"` checks, preventing crashes in sandboxed webviews, iframes, and Node 22 JSDOM test environments.
- **Kernel OOM Killer Protection**:
  - Configured `oom_score_adj` to `-1000` on the developer agent process and installed a persistent systemd service (`protect-agy-oom.service`) to prevent kernel OOM termination during high-memory test or build operations.

### Added
- **Test Coverage**:
  - Added unit test cases for nested subdomains, alternative domains, trailing periods, and negative/spoofed hosts in `daemon/tests/test_castcast/test_mediaserver.py`.
  - All 174 daemon unit tests and 31 frontend Vitest tests verified passing.

---

## Architecture & Compatibility Notes

### 1. 4K Handling (`will_be_4k`)
- CastCast **does not force 4K** or upscale non-4K media.
- `will_be_4k` is an advisory diagnostic flag returned by the capability evaluator (`daemon/castcast/capability.py`).
- If a source file is 1080p, 720p, or SD, `will_be_4k` evaluates to `False`, and the video casts at its native resolution without transcoding. The UI displays `true 4K on the Ultra: NO` to inform the user that the stream is not 2160p (the physical Ultra hardware will upscale to the display if connected to a 4K TV, but the network stream is native).

### 2. Universal File Compatibility Status
- **Embedded Android Prototype (`prototype/embedded-android`):**
  - Features the in-process Chaquopy Python daemon (`CastDaemonService.java`), eliminating external Termux dependencies.
  - Fully incorporates universal non-media file casting: any file (`.apk`, `.exe`, `.py`, `.md`, `.zip`, `.pdf`, etc.) shared from Android file managers or apps is converted on-the-fly into scrollable text slides or binary optical dot matrix streams and cast directly to Chromecast.

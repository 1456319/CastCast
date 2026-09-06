# Chromecast Ultra Protocol Audit Reconciliation & Clean Integration Design

## Overview

This specification defines the clean integration of verified low-level protocol, transport, and packaging improvements from the Astra audit (PR #65) into the `main` branch of CastCast, while strictly excluding breaking regressions (runtime 4K pauses, broken DASH/HLS segments, disabled subtitles, and suppressed logs).

---

## 1. Protocol & Socket Channel Layer (`channel.py` & `supervisor.py`)

### Requirements
- **Persistent Socket Frame Buffering:** Eliminate socket framing desynchronization over Wi-Fi timeouts by introducing a persistent `_receive_buffer = bytearray()` on `CastChannel`.
- **Outbound Clamping:** Reject outbound frames exceeding the Cast protocol limit of 64 KiB (`PACKET_MAX_LEN`).
- **Receiver App ID Differentiation:**
  - `DEFAULT_MEDIA_RECEIVER_APP_ID = "CC1AD845"` (Google CAF Default Media Receiver) used for local media, playlists, and queue management.
  - `SHAKA_RECEIVER_APP_ID = "07AEE832"` reserved for DRM-protected streams requiring Widevine license proxying.
- **Shaka Subtitle Reload Preservation:** For Shaka receiver playback, external/sideloaded subtitle track selection must reload the stream at the current position with active VTT tracks and the Widevine license URL preserved, rather than throwing exceptions or blocking requests.

### Technical Specification
- In `CastChannel.receive(timeout)`:
  - If `len(_receive_buffer) >= 4`, unpack the big-endian 32-bit length `size`.
  - Validate `0 < size <= PACKET_MAX_LEN`.
  - If `len(_receive_buffer) >= size + 4`, slice the complete message packet and decode via `CastMessage.decode()`.
  - When more bytes are needed, read from the socket using remaining deadline timeout and append to `_receive_buffer`.
  - On `socket.timeout` or `ssl.SSLWantReadError`, partial frames remain intact in `_receive_buffer` for the subsequent read call.
- In `CastChannel.send()`:
  - Verify `len(body) <= PACKET_MAX_LEN`, raising `ChannelClosed` if exceeded.
- In `Supervisor`:
  - Route local media and native queue requests (`queue_load`, `queue_insert`, `queue_remove`) to `DEFAULT_MEDIA_RECEIVER_APP_ID`.
  - Route Amazon and DRM media to `SHAKA_RECEIVER_APP_ID`.
  - When updating subtitles on a Shaka session, issue a reload with the current `content_id`, `position`, `license_url`, and updated `tracks`.

---

## 2. Media Serving & Manifest Path Resolution (`mediaserver.py`)

### Requirements
- **Segmented DASH/HLS Compatibility:** Support relative segment URLs (e.g. `segment_001.m4s`, `init.mp4`, `../audio/segment_001.m4s`) commonly found in MPEG-DASH and HLS streams.
- **Canonical Root-Containment:** Prevent directory traversal attacks using canonical path resolution rather than naive string rejection.
- **Dedicated DRM License Listener:** Expose only the `/amazon/license` and `/drm/` endpoints on the local port mapped to the public SSH tunnel.

### Technical Specification
- In `MediaServer._resolve()`:
  - Extract the relative URL path following the session's random secret `root_token`.
  - Normalize path with `posixpath.normpath(rel).lstrip("/")`.
  - For each served root in `server.roots`:
    - Resolve the canonical path using `os.path.realpath(os.path.join(root, rel))`.
    - Enforce that the canonical path starts with `os.path.realpath(root) + os.sep` (or equals root).
    - If valid and an existing file, return the verified path.
- In `_LicenseHandler`:
  - Run a lightweight HTTP server on `127.0.0.1` dedicated strictly to handling POST requests for Widevine licenses.
  - Forward the SSH tunnel to this dedicated listener instead of exposing the primary media server.

---

## 3. Lossless Remuxing & HDR Normalization (`remux.py` & `probe.py`)

### Requirements
- **Atomic Output Publication:** Never expose half-written files to the media server.
- **Concurrent Stderr Draining:** Prevent FFmpeg subprocess pipe deadlocks during long encodes.
- **HDR Characteristic Normalization:** Ensure equivalent HDR transfer tags do not cause false-positive test/verification failures, while still preventing true metadata loss (dropping to SDR).

### Technical Specification
- In `Remuxer._run_inner()`:
  - Compute a temporary output path: `f"{stem}.partial{extension}"`.
  - Instruct FFmpeg to write to this temporary path.
  - Spawn a daemon thread `drain_stderr()` to continuously read lines from `proc.stderr`.
  - Upon successful process exit (returncode 0), compare HDR characteristics if lossless HDR was requested.
  - Perform atomic rename via `os.replace(temporary_output, plan.output_path)`.
  - On cancellation or failure, safely unlink the `.partial` temporary file.
- In `probe.py`:
  - Normalize color transfer names (`smpte2084`, `arib-std-b67`, `bt2020nc`) so standard HDR bitstream descriptions are recognized consistently.

---

## 4. Cache Verification & Non-Interfering 4K Streaming (`service.py`)

### Requirements
- **Prepared File Cache Fidelity:** Prevent reusing an older 1080p transcode when casting a 4K source.
- **Non-Interfering Adaptive Playback:** Allow Adaptive Bitrate (ABR) streams to start at lower resolutions and ramp up to 4K naturally. Do not reject Amazon titles lacking 4K renditions.

### Technical Specification
- In `CastService.preflight()`:
  - When checking an existing prepared file in `plan.output_path`:
    - Probe the cached output.
    - If the original media is 4K (`original_info.primary_video.is_4k`), verify that `prepared_info.primary_video.is_4k` is also True before accepting the cached file as `ready`.
    - Verify that HDR metadata (if present in original) is preserved in the cached file.
- In `CastService._cast_amazon()`:
  - Do not assert `require_4k=True` or reject manifests missing 3840×2160 representations.
- In `Supervisor._update_resolution()`:
  - Update receiver reported resolution for telemetry and UI display only. Do not issue `PAUSE` commands when resolution reports `< 3840x2160`.

---

## 5. Android Lifecycle, LAN Access & Distribution Packaging

### Requirements
- **Termux Background Execution:** Guarantee `RUN_COMMAND` intent execution on Android 10+ when the app is in the background.
- **Persistent Runtime Logging:** Ensure runtime daemon logs are captured in `$AUDIT_LOG`.
- **LAN Control Access:** Allow tablets and remote browsers on the local Wi-Fi to reach the control API.
- **Production APK Packaging:** Exclude test suites, bytecode, and temporary caches from `dist/daemon`.

### Technical Specification
- In `TermuxDaemonPlugin.java`:
  - Retain `appops set com.termux SYSTEM_ALERT_WINDOW allow` and `pm grant ... RUN_COMMAND`.
- In `daemon/termux_bootstrap.sh`:
  - Run the daemon without `--quiet` so `_tail_logs` streams service log buffer messages into `$AUDIT_LOG`.
- In `api.py` & `__main__.py`:
  - Allow the API server to bind to `0.0.0.0` when configured or specified via `--api-host`.
  - In `parse_request()`, permit `Host` and `Origin` headers from RFC 1918 private LAN ranges (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`) alongside `localhost` and `127.0.0.1`.
  - In `do_OPTIONS()`, return `Access-Control-Allow-Private-Network: true`.
- In `scripts/package-daemon.js`:
  - Package production daemon files to `dist/daemon/` while filtering out `tests`, `__pycache__`, `.pytest_cache`, and `*.pyc`.

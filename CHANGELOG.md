# Changelog

All notable changes to CastCast are documented in this file.

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
- **Universal Format Synthesizers (`feat/universal-file-sharing`):**
  - Content inspection (`inspect_content.py`), text slide video synthesizer (`text_synthesizer.py` for `.md`, `.py`, code), and binary dots synthesizer (`dots_synthesizer.py` for `.apk`, `.exe`, raw binaries) reside on branch `feat/universal-file-sharing`.
  - Merging `feat/universal-file-sharing` into `prototype/embedded-android` will combine the standalone embedded daemon with full universal non-media file casting.

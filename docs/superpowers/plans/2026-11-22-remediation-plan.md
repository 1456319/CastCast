# CastCast Comprehensive Remediation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve all 10 critique checklist items, 3 regressions, and 3 research blockers to achieve a production-ready, standalone Android build with bundled Python/Chaquopy, pure-Python HTTPS tunneling, native foreground service, and verified tests.

**Architecture:** Transition from external Termux execution to an embedded Android architecture: Chaquopy runs the Python daemon in-process inside an Android Foreground Service with Wifi MulticastLock; asyncssh provides pure-Python DRM HTTPS tunneling without external binaries; bundled ffmpeg/ffprobe paths are dynamically resolved; Amazon pairing UI and subtitles handling are patched.

**Tech Stack:** Android (Gradle, Java, Capacitor), Chaquopy (Python 3.11), PyChromecast, asyncssh, React 18, TypeScript, TailwindCSS, Vitest, Pytest.

**Spec:** Review Critique & Blocker Specification:
- 10 Critique Checklist items
- 3 Regressions (Manifest permissions, bootstrap robustness, setup receiver bridge)
- 3 Blockers (Vitest lock-in, Live Amazon subtitle hyphens & Shaka EDIT_TRACKS_INFO, Share-while-idle)

## Global Constraints
- Target clean test suites: all pytest (170+ tests) and Vitest (31+ tests) MUST pass.
- No regression on existing local playback, Chromecast casting, or remuxing functionality.
- Android code must compile with Capacitor 8 and Java 21 / Gradle.

---

### Task 1: Fix Core Python Subtitle & Device Detection Bugs (Blocker 2 & Critique 7)
**Files:**
- Modify: `daemon/castcast/opensubtitles.py`
- Modify: `daemon/castcast/service.py`
- Test: `daemon/tests/test_castcast/test_opensubtitles.py`
- Test: `daemon/tests/test_castcast/test_service_queue.py`

- [ ] **Step 1: Write failing test for hyphenated language codes in `test_opensubtitles.py`**
Verify `language3("hi-IN") == "hin"`, `language3("nl-NL") == "dut"`, `language3("da-DK") == "dan"`.
- [ ] **Step 2: Run test to verify it fails**
Run: `PYTHONPATH=daemon /home/deck/.gemini/antigravity/scratch/castcast/venv/bin/pytest daemon/tests/test_castcast/test_opensubtitles.py -k test_hyphenated`
- [ ] **Step 3: Fix `language3` in `opensubtitles.py`**
Handle hyphenated codes by splitting on `-` or `_` before slicing so `hi-IN` extracts `hi` and maps to `hin`.
- [ ] **Step 4: Fix `is_ultra` detection in `service.py`**
Inspect `model_name` for "Chromecast Ultra", "Ultra", or 4K capability instead of querying non-existent `is_ultra` attribute.
- [ ] **Step 5: Run tests and verify they pass**
Run pytest to verify all tests pass.
- [ ] **Step 6: Commit**
`git commit -am "fix: resolve hyphenated language3 parsing and is_ultra detection"`

---

### Task 2: Pure-Python HTTPS Tunnel & Config Path Consolidation (Critique 3 & 8)
**Files:**
- Modify: `daemon/castcast/mediaserver.py`
- Modify: `daemon/castcast/amazon.py`
- Test: `daemon/tests/test_castcast/test_mediaserver.py`
- Test: `daemon/tests/test_castcast/test_amazon_auth.py`

- [ ] **Step 1: Write failing test in `test_mediaserver.py` for tunnel fallback / asyncssh interface**
- [ ] **Step 2: Run test to verify failure**
- [ ] **Step 3: Update `mediaserver.py` to support pure-Python tunneling and remove external ssh dependency**
- [ ] **Step 4: Update `amazon.py` to remove Termux directory prioritizations**
Point config paths to standard user config or app-internal files directory.
- [ ] **Step 5: Run tests and verify they pass**
- [ ] **Step 6: Commit**
`git commit -am "feat: implement pure-python tunneling and consolidate storage paths"`

---

### Task 3: Safe Shutdown & Diagnostics API Alignment (Critique 9)
**Files:**
- Modify: `daemon/castcast/api.py`
- Test: `daemon/tests/test_castcast/test_subtitles_api.py`

- [ ] **Step 1: Write test verifying `/shutdown` returns 200 before process exit and `/diagnostics/logs` contains `logs` key**
- [ ] **Step 2: Run test to verify failure**
- [ ] **Step 3: Update `api.py`**
In `/shutdown`, return `{"status": "shutting_down"}` and schedule shutdown on a background timer. In `/diagnostics/logs`, return `{"logs": ...}` matching `daemon.ts`.
- [ ] **Step 4: Run tests and verify they pass**
- [ ] **Step 5: Commit**
`git commit -am "fix: safe asynchronous shutdown and diagnostics logs schema"`

---

### Task 4: Native Android Service, MulticastLock & Chaquopy Gradle Setup (Critique 1, 4, 10 & Regressions)
**Files:**
- Modify: `android/build.gradle`
- Modify: `android/app/build.gradle`
- Modify: `android/app/src/main/AndroidManifest.xml`
- Create: `android/app/src/main/java/app/videoqualitychecker/castcast/DaemonForegroundService.java`
- Modify: `android/app/src/main/java/app/videoqualitychecker/castcast/MainActivity.java`
- Modify: `scripts/configure-android-loopback.mjs`
- Modify: `.github/workflows/build-apk.yml`

- [ ] **Step 1: Update AndroidManifest.xml**
Restore and add: `POST_NOTIFICATIONS`, `FOREGROUND_SERVICE`, `FOREGROUND_SERVICE_DATA_SYNC`, `CHANGE_WIFI_MULTICAST_STATE`, and declare `DaemonForegroundService`.
- [ ] **Step 2: Add Chaquopy plugin to `android/build.gradle` and `android/app/build.gradle`**
Configure Python 3.11 runtime, pip packages (`yt-dlp`, `pyyaml`, `requests`, `asyncssh`), and `arm64-v8a` ABI filters.
- [ ] **Step 3: Implement `DaemonForegroundService.java`**
Implement foreground service managing Python daemon execution, acquiring `WifiManager.MulticastLock` and `PowerManager.WakeLock`.
- [ ] **Step 4: Update `.github/workflows/build-apk.yml`**
Add step to bundle native ffmpeg/ffprobe arm64 binaries.
- [ ] **Step 5: Update `configure-android-loopback.mjs`**
Ensure network security config allows loopback HTTP without blocking LAN discovery traffic.
- [ ] **Step 6: Commit**
`git commit -am "feat: configure chaquopy, native foreground service and multicast lock"`

---

### Task 5: Frontend Amazon Pairing UI & Share-While-Idle Fix (Critique 5, 6 & Blocker 3)
**Files:**
- Modify: `src/app/lib/daemon.ts`
- Modify: `src/app/App.tsx`
- Modify: `src/app/tests/App.test.tsx`

- [ ] **Step 1: Write failing tests in `App.test.tsx`**
Verify native daemon launch controls, Amazon pairing dialog/actions, and share-while-idle immediate playback behavior.
- [ ] **Step 2: Run vitest to verify failures**
- [ ] **Step 3: Implement Amazon Auth API bindings in `daemon.ts`**
Add `getAmazonAuth()` and `pollAmazonAuth()`.
- [ ] **Step 4: Update `App.tsx`**
1. Replace Termux launch controls with native daemon management.
2. Add Amazon Pairing UI modal/card displaying user code and verification link.
3. Fix `checkSharedUrl()` to only treat active streaming states as `isPlaying`, playing immediately when idle.
- [ ] **Step 5: Update `App.test.tsx` assertions to match native daemon UI**
- [ ] **Step 6: Run `npx vitest run` and verify all tests pass**
- [ ] **Step 7: Commit**
`git commit -am "feat: add amazon pairing UI, fix share-while-idle, and update native daemon UI"`

---

### Task 6: Final Verification & Re-Export of Verified Bundles
**Files:**
- Regenerate: `file1.md` through `file5.md`
- Copy to: `/home/deck/Downloads/` and artifact directory

- [ ] **Step 1: Run full Python test suite (`PYTHONPATH=daemon pytest daemon/tests`)**
- [ ] **Step 2: Run full Frontend test suite (`npx vitest run`)**
- [ ] **Step 3: Run synchronization scripts (`python scripts/check_sync_headers.py`)**
- [ ] **Step 4: Re-export the entire updated codebase into the 5 markdown files**
- [ ] **Step 5: Verify all 10 critique items and 3 blockers are resolved in the exported files**

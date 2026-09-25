# Hands-on baseline and curated diagnostic tour

## Observed 2026-09-06

- ADB successfully connected to the owner-provided wireless-debugging endpoint. Its port can change; do not hardcode it into app configuration.
- Pixel 10 Pro XL; Android 16, SDK 36.
- `app.videoqualitychecker.castcast`: versionName `1.0`, versionCode `1`, targetSdk 36, minSdk 24.
- Package manager lastUpdateTime: `2026-09-06 11:42:57` (device-reported).
- CastCast, Termux and a `python3` process were present. Process presence does not prove daemon readiness.
- A bounded logcat window filtered to Capacitor/Console warnings and AndroidRuntime errors returned no entries. Relevant events may use another tag, lie outside this window, or exist only in daemon logs.
- Local revision: `f406dc1d58839649e87f1c416cb2ad66bb5f2cde`. Deployed APK/daemon revision remains unverified.
- No restart, app launch/stop, receiver command, installation, log clearing or playback disruption was performed.

## Local logging pointers, not yet verified on phone

- `daemon/termux_bootstrap.sh` appends Python stdout/stderr to `/storage/emulated/0/Download/CastCast/Chromecast/.castcast/audit.log`. This restored checkout does not use the discarded audit's `--quiet` launch change.
- `daemon/castcast/service.py`: `LogBuffer` (500 entries by default) and `CastService.log`.
- `daemon/castcast/__main__.py`: `_tail_logs` prints service events with flush enabled.
- `daemon/castcast/api.py`: `/diagnostics/logs` and `/health`.

Confirm deployed behavior before changing logging. Preserve existing history. A short filtered logcat window is not a substitute for the Python audit log.

## Low-cost procedure

1. Owner demonstrates one unreliable workflow: exact actions, expected/actual result, approximate time.
2. Identify deployed daemon path/build and capture receiver application/session/current-item state.
3. Capture phone and daemon logs across that sequence. Use detailed events in a bounded time window rather than an unfiltered dump of the entire phone.
4. Find the first meaningful failure: UI/API, provider extraction, manifest, license, segment fetch, receiver launch, decoder, queue state or Android lifecycle.
5. If invisible, instrument that boundary as a separately authorized change. Retain exception types, stack traces and upstream status codes. Byte counts and correlation IDs are generally more useful than credentials/full license payloads.
6. Reproduce with the same media and receiver state; record successful controls too.
7. After a targeted fix, rerun the sequence and adjacent operations such as pause/resume/seek after subtitle insertion.

## Later qualification, not executed

Owner-approved short samples: local HD/4K HDR, direct/remux, audio, seek/range, HD-only provider titles, UHD adaptive startup, subtitles, existing receiver sessions, reconnect, screen-off/background. Schedule disruptive daemon/network interruption separately. Observe TV/AVR output mode independently of reported decoded resolution; phone ADB alone cannot prove HDMI quality.

Do not run this entire matrix merely because it is listed. The owner asked to conserve credits and offered a curated tour of a mostly working app.

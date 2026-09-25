# CastCast phone observation — 2026-09-10 (incomplete; stopped on control loss)

## Baseline and changes made

Phone: Pixel 10 Pro XL, Android 16. APK versionName 1.0/versionCode 1, package timestamp 2026-09-06 11:42:57. Repository `06b88619b0ae7501d8c621f81f7d3c10da2b7c9f`. Receiver manually connected at 192.168.1.6:8009; reported application later `07AEE832`.

No production code edits, package installations, daemon restarts, authentication configuration changes or security changes. Temporary host-side WebView observation helper and an ADB forward were used. UI actions issued by the investigator: share episode 7 via ACTION_SEND; remove only the resulting test-created duplicate queue row; click the original episode 7 row. No investigator-issued subtitle selection, pause, seek, Stop or episode 8 playback followed. Other actions appear in the logs while the owner was also operating the app; do not attribute them to a particular actor without further evidence.

The owner reports subtitles were visible before testing, later reports video playing normally without subtitles, and then reports loss of control. These observations are evidence and are not overridden by the controller's optimistic status fields.

## 1. Confirmed control-loss mechanism: new LOAD while PLAYING

At approximately 15:12:20 phone/log time, the daemon recorded another `queued LOAD` for episode 7 without a subsequent `LOAD sent`. It then recorded five `dropping STOP: no active media session` events. The 19:14:44Z snapshot reports state `playing`, null media_session_id, duration 0, advancing position 379.86, and empty last_error. The UI says playing and displays 6:19 / 0:00.

Source trace in `daemon/castcast/supervisor.py`:

- `load()` clears `_media_session_id` and `status.media_session_id`, replaces `_session`, resets duration/track state, and calls `_try_load()` without changing the existing PLAYING state.
- `_try_load()` only sends LOAD in READY or CONNECTED state, so the new request remains pending while PLAYING.
- `_media_command()` drops commands when `_media_session_id is None`.

A local, network-free reproduction used the real Supervisor with a mocked connected channel, state PLAYING, existing transport and media-session ID 7. Calling `load()` and then STOP produced: state playing; media_session_id None; zero messages sent; STOP returned None; logs `queued LOAD replacement` and `dropping STOP: no active media session`.

Local and deployed supervisor SHA-256 both: `a0efdaf80ffcfe5f3028020dda790ee621db70a04cb3a0d87a9c41f4b2feb724`.

This establishes an actual state-machine defect and matches the live failure signature. It does not establish who triggered every action in the shared phone session. No repair has been applied; do not redesign receiver handling before reproducing and verifying a narrowly scoped repair.

## 2. Subtitle status claims success despite receiver rejection

The owner confirms no visible captions despite the UI reporting ENG. Logs show selections of tracks 8 and 9 followed by `EDIT_TRACKS_INFO rejected with INVALID_COMMAND`. The first saved snapshot has active_track_ids [8] but text_tracks 0 and has_text_tracks false.

`Supervisor.set_active_tracks()` updates active IDs before sending the command; `CastService.select_subtitle_track()` returns those IDs without awaiting receiver confirmation. The UI can therefore indicate a selection that was not accepted. That is confirmed as a reporting/command-path problem, but the owner's earlier working captions mean it must not be generalized into 'Amazon subtitles never work'. Determine the earlier receiver/subtitle path and state before engineering a fix. Controller loss later makes additional subtitle tests inconclusive.

## 3. Share path: duplicate episode and connected-idle behavior

The original queue contained:

- E7 Weapon of Mass Distraction, catalog `0RGBA30NMTMUMFD0KSQHC42VN1`, under a `/region/na/detail/` URL with query parameters.
- E8 Curtain Call, catalog `0KRYFAKI5MGMVZGY4ERW5D9DDS`, same long-URL format.

ACTION_SEND of `https://www.primevideo.com/detail/0RGBA30NMTMUMFD0KSQHC42VN1` added a third row titled `Amazon Video`. It did not start playback from connected state. The duplicate remained until the investigator removed that exact newly created row via its UI remove button; the original two rows were preserved.

Current source compares complete URL strings for queue duplicates. App.tsx considers connected/ready states 'isPlaying', which routes sharing into queue addition rather than immediate casting. Exact-URL duplication versus episode identity and connected-idle share behavior need separate acceptance tests. The generic title is observed, but its resolution failure was not independently diagnosed.

## 4. Initial UI wiring inventory

| Item | Evidence | Classification |
|---|---|---|
| Maximum Verbosity | Installed JS reads `data.logs`; live endpoint returns `log_buffer`, `audit_log`, `last_error`. Eleven entries existed at baseline. | Confirmed formatter/API mismatch |
| Persistent diagnostics | Deployed route looks at `/var/log/audit/audit.log` and `/tmp/castcast.log`, not Termux bootstrap's `.castcast/audit.log`. API audit content empty. | Confirmed missing log-source connection |
| Local queue drag reorder | Source changes React state; persistence call commented out and backend route absent. Displayed order can still feed Cast Queue. | Source-confirmed persistence gap; no phone drag test |
| Amazon sign-in | Backend auth/poll/inject capabilities have no corresponding inspected frontend flow. Existing saved auth worked. | Unexposed setup capability, not current playback failure |
| Anomaly submission | Installed JS opens `1456319/openchromecast/issues/new`. | Destination differs from CastCast; intended destination unconfirmed |
| Playback/track success feedback | Dropped commands/rejected track selections do not reliably become visible failure state. | Live failure plus source evidence |
| Device identification | Manual connection reports model empty and is_ultra false for owner's Ultra. | Metadata discrepancy; no demonstrated 4K playback failure |

Do not count unused component-library files or the older OpenSubtitles API wrapper as broken visible features. The current subtitle drawer uses other hooked-up routes.

## What worked

Episode 7 launched through its original UI queue row. An HTTP 403 was followed by successful Amazon access-token refresh. Manifest retrieval and parsing reported 42 subtitle tracks. The license proxy acquired and served 741 bytes successfully. State progressed to playing; the owner confirmed visible playback. This is not independent proof of 4K/HDR HDMI output.

## Artifacts and remaining tests

- `checkpoint-01-episode7.json`: state, available subtitle metadata, full then-current ring-buffer entries and UI text at 19:10:53Z.
- `checkpoint-02-controller-desync.json`: same at 19:14:44Z after control loss.
- URLs in these exported artifacts are masked; request type, status, timings, title IDs and license byte counts are retained. Original phone logs were not cleared or edited.

Pause/resume, controlled seeks, subtitle off/on, episode 7→8 advancement and remaining visible-control tests were NOT completed. Testing stopped when the owner reported control loss. Restore a known working session with the owner's agreement before continuing; do not hide the problem with a daemon reinstall or an unrequested restart.

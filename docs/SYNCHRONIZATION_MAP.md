<!-- WARNING: Changes to these contracts must remain synchronized between the controller, Termux daemon and receiver. -->
# CastCast synchronization map

This file records the implemented boundaries. `docs/synchronization-inventory.yaml` owns file/header membership. The [Ultra audit](CHROMECAST_ULTRA_AUDIT_2026-09-06.md) records remaining transactional and hardware gaps; these tables do not assert that those gaps are solved.

## Stable component ownership

| Section | Owner and boundary |
|---|---|
| `core-service` | `service.py`: directory inventory, desired queue, preparation and user operations |
| `api-contract` | `api.py` and `src/app/lib/daemon.ts`: HTTP/SSE payloads and origin policy |
| `cast-sender-receiver` | `channel.py`, `supervisor.py`: Cast transport, app identity, receiver state; bundled receiver HTML is a scaffold |
| `media-routing` | `mediaserver.py`, `remux.py`, `amazon_drm.py`, `rules.py`: media URLs, conversions and license routing |
| `utility-middleware` | Probe, discovery, metadata, subtitles and health helpers |
| `web-client` | `App.tsx`, preflight/subtitle components: display observed state and submit intents |
| `android-bridge` | Capacitor plugins: Termux launch and discovery browser |
| `config-state` | Media roots, queue order, provider/resume state and device cache |
| `operations-release` | Bootstrap, clean daemon packaging, CI and APK bundle installation |

## Changed HTTP contracts

The full route implementation remains in `api.py`; `/` also describes routes. Errors carry an `error` string. Validation uses 400, disallowed origins/hosts 403, and service conflicts 409. Some service error objects remain HTTP 200; the client checks the body as well as the HTTP status.

| Method / path | Request | Response / interpretation | Client |
|---|---|---|---|
| GET `/status` | None | `connected`, `device`, `media_server`, `tools`, `remux`, `cast`, `queue` | `daemon.status` |
| GET `/library` | Optional `deep=1` | `{items}` sorted by persisted order then path | `daemon.library` |
| GET `/trash` | None | `{items}` including nested trash paths | `daemon.getTrash` |
| POST `/library/reorder` | `{paths: string[]}` exact current library permutation | `{items}` after native reorder acknowledgment (if applicable), then persistence | `daemon.reorderLibrary` / drag and drop |
| POST `/queue` | `{paths: string[]}` unique paths in visible order | `{queued, preparing, skipped, sync_state}`; zero items are loaded until the whole order is prepared. An error blocks the request. | `daemon.queue` |
| POST `/trash` | `{path}` | `{trashed}` only after receiver removal acknowledgment and filesystem move | `daemon.trash` |
| POST `/prepare` | `{path, force?}` | Preflight plus `started: true` when a worker was started | `daemon.prepare`, CLI Prepare |
| POST `/subtitles/select` | `{track_id: number or null}` | Requested IDs; canonical active IDs come from receiver status | Subtitle drawer |
| POST `/subtitles/remote/fetch` | `{url, language?, type?}` | New caption track; native queue reload preserves current index/time/pause. Shaka external tracks require a separate adapter. | Subtitle drawer |

`queue.paths` is desired native order; `queue.sync_state` is `inactive`, `preparing`, `unconfirmed`, `synced` or `blocked`. “Synced” currently checks observed source paths and receiver-assigned IDs against intent; it is not a durable filesystem transaction or a guarantee of complete receiver queue retrieval. See audit R01/R02.

`cast.revision` increases on snapshots. `cast.connection_id` identifies a supervisor; `connection_epoch` orders supervisor replacements. The UI rejects older receiver snapshots. `quality_state` is `unverified`, `receiver_4k` or `below_4k`, with `receiver_width`/`receiver_height`. These describe reported picture dimensions, **not HDMI output proof**. `will_be_4k` in preflight is retained for compatibility but means source eligibility only.

## SSE contracts

| Event | Producer | Consumer / behavior |
|---|---|---|
| `status` | API initial snapshot | App applies revision/connection ordering |
| `media` | Supervisor via service | App merges receiver snapshot; service updates current source/caption cache |
| `state`, `load_failed`, `command_failed`, `quality_failed` | Supervisor | Client refreshes status; errors remain visible |
| `library` | Service operations/watchdog | `{items, trash}` replaces folder lists |
| `amazon_queue` | Service | Separate sender-side provider list; not a native queue acknowledgment |
| `remux` | Job producer | Progress and terminal state; client refreshes |
| `log` | LogBuffer | Client deduplicates sequence/timestamp; bounded, not durable |

The client polls status/library/trash every five seconds as a recovery path for missed SSE messages. This is eventual synchronization. No cross-layer event replay journal exists yet.

## Receiver contracts

| Path | App / namespace | Requirements |
|---|---|---|
| Local native queue / captions | DMR `CC1AD845`, `urn:x-cast:com.google.cast.media` | New QUEUE_LOAD strips item IDs; `startIndex`, `currentTime`, autoplay retained; subsequent mutations require current session ID and receiver IDs |
| Custom-license playback | Shaka demo `07AEE832`, generic media LOAD plus `customData.asset` | Exact app identity; `licenseServers` map and `extraConfig`; UHD restrictions when required |
| Shaka captions / dimensions | `urn:x-cast:com.google.shaka.v2` | Use reported player track IDs, not MPD stream indices; merge partial updates; deployed-version validation required |
| Cast channel | TLS 8009 | 64 KiB limit, persistent partial-frame buffer, distinct platform/application CLOSE |
| Bundled CAF HTML | No active app ID | Not deployed or automatically activated by this branch |

## Media and license URLs

| URL boundary | Authorization and framing |
|---|---|
| LAN `/<root_token>/r<root_index>/<relative_path>` | Only paths explicitly issued by `url_for`; distinct root identity, Range/CORS support |
| LAN `/proxy/?url=<base64>&token=<root_token>` | Capability required; HLS child/key/map/audio URIs use the same producer; signed queries retained |
| `/amazon/license?title_id=...&token=<license_token>` | Raw binary challenge/response; bounded body, explicit Content-Length; provider still owns license decisions |
| Public HTTPS tunnel | Forwards to separate loopback license-only listener; media, files and control API unavailable on that listener |

Do not add wildcard CORS to the control API to fix receiver media requests. Do not enable Web-PKI verification on the Cast device socket without a compatible device trust implementation. Do not rotate active URL tokens without a session rebase/grace protocol.

## Configuration and persistence

| Key / path | Owner / semantics |
|---|---|
| `media_roots` | Default `/storage/emulated/0/Download/CastCast/Chromecast`; CLI, service, example config and bootstrap agree |
| `work_dir` | Defaults to `.castcast` under the first media root; excluded from the visible queue |
| `work_dir/queue_order.json` | Atomic JSON array of source paths; ordering preference, not receiver queue journal |
| `~/.config/castcast/amazon_queue.json` | Atomic sender provider queue; separate from native queue |
| `~/.config/castcast/resume_state.json` | Atomic last saved positions; not a complete paused/native session record |
| `~/.config/castcast/amazon_auth.json` | Private credentials; injected file mode 0600 |
| `api_allowed_origins` | Optional explicit additional controller origins; default Capacitor loopback remains allowed |
| `avr_passthrough` | Explicit opt-in to AC3/EAC3 passthrough assumptions |
| `CASTCAST_DISABLE_TUNNEL=1` | Disable external SSH setup; automatically set by tests |
| `CASTCAST_TELEMETRY_OPTOUT` | Existing rules telemetry setting; separate telemetry writers are an audit follow-up |

## APK and build boundary

`pnpm run build` regenerates the web app, then `scripts/package-daemon.js` recreates `dist/daemon` from production sources and compares every copied byte. Tests, Python bytecode and hidden files are excluded. Although `dist/` is ignored for new files, historical distribution files are tracked in this repository; the review branch refreshes that snapshot. `cap sync android` packages the result into APK assets.

`TermuxDaemon.launch` identifies the installed APK's update timestamp and installs its daemon under `~/CastCast/releases/<installedAt>/daemon`. Extraction is staged separately from running code. Bootstrap runs this exact directory: it does not pull a different Git revision. It checks/stops only an identified same-UID CastCast listener, serializes service-job lifetime with flock, and uses Termux's wake lock. Existing bundles are retained for rollback.

PR CI builds an APK artifact for review; release publication remains restricted to push events. Android runtime, root policy, SELinux, network locks and physical receiver qualification still require device testing.

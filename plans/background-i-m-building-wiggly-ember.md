# Chromecast Whisperer — UI review and APK-readiness plan

## Context

The `castcast` daemon (built in this workspace) has been paired with a UI in
`github.com/1456319/chromecast-whisperer`. That repo now vendors the daemon
unchanged under `daemon/`, adds an Expo React Native control surface under
`mobile/`, a Lovable-built landing page under `src/`, a reference web UI under
`reference/web-ui/`, and `docs/PACKAGING.md`.

The goal is an installable APK for a rooted Pixel 10 Pro XL that drives the
daemon running under Termux, and which can verify the daemon is up and its
dependencies are present and functional. Real-world testing begins once the APK
exists, so the job now is to remove everything that would block or mislead the
agent that builds it.

`REASONING_AND_RESEARCH.TXT` is the shared cross-agent memory file and must be
kept current as part of this work.

---

## Review verdict on the UI

**The UI is appropriate and is better than I expected.** It is not a webview
wrapper — it is Expo React Native with real native views, so the user's
"optimally not just a package for a webUI" requirement is *already met*. Keep it.

Specifically correct decisions, which should be preserved:

- `mobile/lib/daemon.ts` matches the daemon's API contract **exactly** — every
  path, method, query param and body field lines up with `daemon/castcast/api.py`.
  No drift.
- `DaemonUnreachable` is a distinct error subclass, correctly separated from the
  daemon's soft `{"error": ...}` bodies returned with HTTP 200. This matches
  `api.py`'s actual convention (409 = wrong state, 400 = missing param).
- The earlier mock-diagnostics blob (CPU temp, HDCP version, Widevine level, ADB
  console) was removed. That was the right call and must not come back: the
  CASTv2 `receiver` namespace exposes only volume, running apps and session IDs.
  Nothing else is obtainable, and `orUnknown` → `?` is the honest rendering.
- Per-endpoint timeouts (60s deep library, 30s preflight/cast, 20s connect) are
  well-judged against real daemon latencies.
- `react-native-sse` with a documented 1s polling fallback, since RN has no
  global `EventSource`.

**One framing correction:** `https://chromecast-whisperer.lovable.app` is a
*landing/marketing page* describing the project, not the functional control
surface. It cannot control anything — it is browser JS, and the daemon binds
loopback on the phone. The real UI to review and ship is `mobile/`. This
distinction should be stated plainly in the docs so a future agent does not try
to package the Lovable page as the app.

---

## Blockers to APK packaging

### B1. The documented start command is broken (two ways)

`README.md` and `docs/PACKAGING.md` both say:

```sh
python -m castcast --root /storage/emulated/0/Download/Chromecast
```

Against `daemon/castcast/__main__.py` this fails twice: there is no `--root`
flag (it is `--media-root`, `action="append"`), and `add_subparsers(...,
required=True)` means a subcommand is mandatory. Correct form:

```sh
python -m castcast --media-root /storage/emulated/0/Download/Chromecast serve
```

This is the first command a human or agent will run. Fix in `README.md`,
`docs/PACKAGING.md`, and `REASONING_AND_RESEARCH.TXT`.

### B2. No EAS build configuration — no APK can be produced

There is no `eas.json`, and `eas-cli` / `expo-dev-client` are absent. Also note
EAS's default Android artifact is an **AAB**, not an APK. Need an `eas.json`
with a profile setting `android.buildType = "apk"`.

### B3. The network security config cannot be applied as documented

`docs/PACKAGING.md` correctly refuses app-wide `usesCleartextTraffic` and
specifies `android/app/src/main/res/xml/network_security_config.xml`. But
`mobile/` is a managed (CNG) Expo project — there is no `android/` directory,
and generating one via `expo prebuild` would discard the file on regeneration.

The fix is a **local Expo config plugin** that writes the XML and sets
`android:networkSecurityConfig` on `<application>`. This keeps CNG intact and
survives prebuild. Without this, the release APK cannot reach
`http://127.0.0.1:8765` at all — the app would build and then fail silently on
every request.

### B4. Declared permissions do not match what will actually ship

`mobile/app.json` declares only `INTERNET` and `ACCESS_NETWORK_STATE`, and
`PACKAGING.md` repeats that claim. But `expo-camera` is a dependency, and its
autolinked config plugin injects `android.permission.CAMERA`. Several other
dependencies appear to be unused template residue: `expo-camera`, `expo-symbols`,
`expo-blur`, `expo-web-browser`, `@lucide/lab`, and — notably —
`react-native-webview`, whose presence actively undermines the "not a webview
app" claim.

Each needs a usage check before removal, but the end state should be that the
shipped APK requests exactly the two documented permissions.

### B5. The app cannot start or truly verify the daemon

Today the app only HTTP-probes `/status`. The user explicitly wants the APK to
verify the daemon is running and that dependencies are installed and functional.
Two gaps:

- **Daemon side:** `/status` reports `tools.{ffmpeg,ffprobe}` and the configured
  roots, but never checks whether those roots *exist or are readable* — which is
  exactly what fails when `termux-setup-storage` has not been run. It also does
  not surface whether `lan_ip` is sane (a `127.0.0.1` result from
  `detect_lan_ip()` means there is no usable LAN route, so every LOAD URL will
  be unreachable by the Ultra).
- **App side:** the daemon-down state is rendered as a single unreachable
  message plus a command string. It cannot distinguish "daemon not started" from
  "daemon running but storage permission missing" from "daemon running but no
  LAN route" — three failures with three completely different remedies.

**Decision (user, this session): detect and verify only.** The app never
launches the daemon. No Termux `RUN_COMMAND` intent, no
`com.termux.permission.RUN_COMMAND`, no `<queries>` entry, no bundled Python.
The shipped manifest stays at exactly `INTERNET` + `ACCESS_NETWORK_STATE`, which
makes the `PACKAGING.md` permission claim true rather than aspirational, and
avoids the un-automatable `allow-external-apps=true` prerequisite entirely.
Starting the daemon remains a deliberate user action in Termux; the app's job is
to say precisely what is wrong and hand over the exact command to fix it.

---

## Plan

### 1. Daemon: add a real readiness endpoint

In `daemon/castcast/service.py`, add `health()` and expose it as `GET /health`
in `daemon/castcast/api.py`. Reuse the existing `have_ffmpeg()` / `have_ffprobe()`
from `probe.py` and `MediaServer.lan_ip` from `mediaserver.py`. Report, each with
a remedy string:

| Check | Failure meaning |
|---|---|
| `ffmpeg` / `ffprobe` on PATH (+ version) | `pkg install ffmpeg` |
| each media root exists / is readable / file count | `termux-setup-storage` not run |
| `lan_ip != 127.0.0.1` | no LAN route; the Ultra can never pull media |
| media server bound, port | — |
| python version, `castcast.__version__` | — |

Return `ready: bool` plus a `blocking: [{check, message, remedy}]` list, so the
app renders one honest checklist instead of guessing. Add `/health` to the
`_ROUTES` map already in `api.py`.

Also emit the daemon's existing `finished` SSE event name in the client's
`EVENT_NAMES` (see step 3) — the daemon emits it, the client currently drops it.

### 2. Mobile: Expo config plugin for scoped cleartext

Add `mobile/plugins/withLoopbackCleartext.js` — a config plugin using
`withAndroidManifest` + `withDangerousMod` (or `withAndroidXml`) to emit
`network_security_config.xml` permitting cleartext for `127.0.0.1` and
`localhost` only, and set the `android:networkSecurityConfig` attribute.
Register it in `app.json`'s `plugins` array.

If the user pins a LAN daemon address via the gear icon, that address is *not*
covered — the UI must say so rather than failing opaquely.

### 3. Mobile: readiness screen (detect and verify only)

Add `mobile/app/(tabs)/setup.tsx` (or fold into the existing settings surface)
rendering `/health` as a checklist. One row per check, each in one of three
states — pass, fail, unknown (`?`, consistent with the existing `orUnknown`
convention). Every failing row carries the exact remedy command and a
copy-to-clipboard button via `expo-clipboard`.

Rows, in dependency order, so the first red row is always the real cause:

1. **Daemon reachable** — fail ⇒ `pkg install python ffmpeg`, then
   `python -m castcast --media-root /storage/emulated/0/Download/Chromecast serve`
2. **ffmpeg / ffprobe present** — fail ⇒ `pkg install ffmpeg`
3. **Media root readable** — fail ⇒ `termux-setup-storage`
4. **LAN route** (`lan_ip` is not loopback) — fail ⇒ Wi-Fi guidance; the Ultra
   cannot fetch media without this
5. **Device reachable** — the existing connection state

Everything below row 1 comes from a single `/health` response, so this is one
request on focus plus the existing poll. Add a `health()` call to
`mobile/lib/daemon.ts` alongside the existing typed endpoints and a `Health`
interface mirroring the daemon dataclass. No new permissions.

While the daemon is unreachable the app cannot know rows 2–4; render them `?`
rather than red. Guessing here is the same failure mode as the mock diagnostics
that were already correctly removed.

### 4. Mobile: dependency prune and permission truth-up

Verify usage of and remove `expo-camera`, `expo-symbols`, `expo-blur`,
`react-native-webview`, `@lucide/lab`, `expo-web-browser` if unreferenced. Add
`expo-clipboard` for the readiness screen (it injects no Android permission).
Then confirm the generated manifest requests only `INTERNET` and
`ACCESS_NETWORK_STATE` — with the detect-only decision this is now an
enforceable invariant, so state it in `PACKAGING.md` as such.

### 5. Build config

Add `mobile/eas.json` with a `preview` profile producing `buildType: "apk"` and
a `development` profile with `developmentClient: true`. Document the
`npx eas build -p android --profile preview` invocation in `docs/PACKAGING.md`.

### 6. Docs and shared memory

- Fix the broken command (B1) everywhere it appears.
- `docs/PACKAGING.md`: replace the "edit `android/...`" instructions with the
  config-plugin approach; document Termux `allow-external-apps`, Termux:Boot,
  and `termux-wake-lock` for Doze survival.
- `README.md`: state that the Lovable URL is a landing page, not the control UI.
- `REASONING_AND_RESEARCH.TXT`: append a dated entry recording this review — the
  contract-match confirmation, each blocker above with its reasoning, the
  landing-page-vs-app correction, the detect-only decision and *why* (permission
  honesty plus no un-automatable Termux prerequisite), and the standing caveat
  that `Remuxer.run()` and mDNS discovery are still hardware-unverified — no
  ffmpeg binary and no LAN in the build sandbox. Append only; correct by adding,
  not deleting.

---

## Verification

Runnable in this workspace:

1. `python3 -m compileall -q daemon/castcast` — syntax.
2. Against the existing mock receiver harness: start `CastService`, `GET /health`,
   assert `ready:false` with a `blocking` entry naming ffprobe (absent here), and
   assert a nonexistent media root is reported unreadable.
3. Assert `/health` appears in the `_ROUTES` map returned by `GET /`.
4. Confirm the daemon still passes the prior regression: handshake,
   reconnect-with-resume, 18s dead-link detection.

Requires the phone (hand off to the on-device agent):

5. `npx expo prebuild -p android` then confirm the generated
   `network_security_config.xml` and manifest attribute exist, and that the
   manifest requests only the two intended permissions.
6. `npx eas build -p android --profile preview` produces an `.apk`.
7. Install, run with the daemon stopped → row 1 red with the corrected command,
   rows 2–4 `?`. Start the daemon → all green.
8. `pkg uninstall ffmpeg` → row 2 red; confirm the Library tab still lists files
   and an already-valid MP4 still casts (the documented degradation path), rather
   than blocking.
9. Revoke storage permission (or point `--media-root` at a nonexistent path) →
   row 3 red naming `termux-setup-storage`, while rows 1–2 stay green. This is
   the discrimination the current single unreachable message cannot make.
10. Confirm copy-to-clipboard yields a command that runs verbatim in Termux —
    this is the same class of defect as B1 and deserves an actual paste test.

---

## 2026-08-07 update — daemon process controls and loopback packaging CI

The daemon now protects users from the accidental duplicate-server path that
triggered this follow-up. `serve` checks whether the API port is already held
before binding it, reports the conflict with concrete recovery commands, and
supports `--kill-existing`, `--restart`, and `--if-running exit|kill|restart`.
A `server` command group was added for `status`, `kill`, and `restart`, so users
no longer have to grep for a listener PID manually.

Docs now put `cd VideoQualityCheckerApp/daemon` before `python -m castcast` so a
root-level launch attempt does not make `castcast` look like a missing Python
module. The corrected media-root command remains the canonical launch command.

Packaging state was also brought in line with the previous PACKAGING guidance:
`capacitor.config.ts` sets `androidScheme: 'http'`, and CI runs a script that
writes `network_security_config.xml` permitting cleartext only for `127.0.0.1`
and `localhost`, patches `AndroidManifest.xml` with
`android:networkSecurityConfig="@xml/network_security_config"`, and rejects
missing loopback config. This prevents Android WebView cleartext loopback
failures from masquerading as a dead daemon.

## 2026-08-07 update — Copilot follow-up and lockfile fix

Reviewed the follow-up feedback and kept the daemon/server-control and loopback
cleartext approach. The actionable CI failure was that the pnpm-based workflow
used `setup-node` pnpm caching without a committed `pnpm-lock.yaml`; generated
and committed the lockfile, pinned the newly added Capacitor packages to the
resolved version instead of `latest`, and restored the loopback CI install step
to `pnpm install --frozen-lockfile` so future dependency drift fails loudly.

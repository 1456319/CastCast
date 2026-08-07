# Handoff: APK-readiness changes for `1456319/chromecast-whisperer`

These are drop-in artifacts for the agent that will build the APK. The
whisperer repo is not checked out in the environment they were authored in, so
they are staged here mirroring the target repo layout rather than committed
directly.

`AGENTS.md` in that repo forbids force-push, rebase, amend and squash of
already-pushed commits. Everything below is additive; nothing requires
rewriting history.

---

## 1. Daemon — already implemented, copy across

The daemon in this workspace gained a readiness endpoint. Copy these into
`daemon/castcast/` in the whisperer repo:

| File | Change |
|---|---|
| `health.py` | **new** — the check engine |
| `service.py` | added `CastService.health()`; imports `health` |
| `api.py` | added `GET /health` and its `_ROUTES` entry |
| `mediaserver.py` | added `MediaServer.running` property |
| `__main__.py` | added `doctor` subcommand and `_print_health()` |

`GET /health` returns:

```json
{
  "ready": false,
  "version": "1.0.0",
  "python": "3.11.6",
  "serve_command": "python -m castcast --media-root /storage/emulated/0/Download/Chromecast serve",
  "connected": false,
  "checks": [
    {"key": "media_server", "label": "Media server", "ok": true,
     "detail": "serving on port 41233", "remedy": "", "blocking": true},
    {"key": "lan", "label": "LAN address", "ok": false,
     "detail": "no route off-device (got 127.0.0.1)",
     "remedy": "Connect the phone to the same Wi-Fi network as the Chromecast",
     "blocking": true},
    {"key": "ffprobe", "label": "ffprobe (pre-flight checks)", "ok": false,
     "detail": "ffprobe is not on PATH -- files cannot be pre-flighted...",
     "remedy": "pkg install ffmpeg", "blocking": false}
  ],
  "blocking": [ /* subset of checks that are blocking and failing */ ]
}
```

Two design points worth preserving:

- **`ok` is tri-state** (`true` / `false` / `null`). `null` means *unknown* and
  must render as `?`. This is the same honesty rule that led to the mock
  diagnostics being stripped earlier — do not narrow it to a boolean.
- **ffmpeg and ffprobe are `blocking: false`.** An already-compatible MP4 casts
  fine without them; that degradation path is implemented in
  `CastService.preflight()` and must not regress into a hard block.

There is also a CLI form, useful before the APK exists and as a script gate
(`castcast doctor && castcast serve`):

```sh
python -m castcast --media-root /storage/emulated/0/Download/Chromecast doctor
```

It exits 0 only when nothing blocking is wrong.

---

## 2. Mobile — files to add

```
mobile/eas.json                          (new)
mobile/plugins/withLoopbackCleartext.js  (new)
mobile/app/(tabs)/setup.tsx              (new)
mobile/lib/daemon.ts                     (append daemon.health.patch.ts)
mobile/app.json                          (edit — see below)
mobile/package.json                      (edit — see below)
```

### `app.json`

Register the plugin and the new tab:

```json
"plugins": [
  "expo-router",
  "expo-font",
  "./plugins/withLoopbackCleartext"
]
```

Add `setup` to the tab layout in `mobile/app/(tabs)/_layout.tsx`. It should be
the **first** tab, since it is the screen that matters when nothing works yet.

### `package.json`

Add:

- `expo-clipboard` — used by the setup screen's copy buttons. Injects no
  Android permission.
- `eas-cli` as a devDependency (or invoke via `npx`).

Remove, after confirming each is unreferenced:

- `expo-camera` — **this is the one that matters.** Its autolinked config
  plugin injects `android.permission.CAMERA`, which contradicts
  `docs/PACKAGING.md`'s claim that the app requests only `INTERNET` and
  `ACCESS_NETWORK_STATE`.
- `react-native-webview` — unused, and its presence undercuts the "this is a
  real native app, not a webview wrapper" claim.
- `expo-symbols`, `expo-blur`, `@lucide/lab`, `expo-web-browser` — template
  residue; check before removing.

With the detect-only decision, "exactly two permissions" is now an enforceable
invariant rather than an aspiration. Verify it after prebuild:

```sh
npx expo prebuild -p android --clean
grep uses-permission android/app/src/main/AndroidManifest.xml
```

### Building the APK

EAS's default Android artifact is an **AAB**, not an APK. `eas.json` sets
`buildType: "apk"` on all three profiles.

```sh
cd mobile
npx eas build -p android --profile preview
```

---

## 3. Documentation corrections

### The start command is wrong in two places

`README.md` and `docs/PACKAGING.md` both document:

```sh
python -m castcast --root /storage/emulated/0/Download/Chromecast     # BROKEN
```

Checked against `daemon/castcast/__main__.py`, this fails twice over: there is
no `--root` flag (it is `--media-root`, `action="append"`), and
`add_subparsers(dest="command", required=True)` makes a subcommand mandatory.
As written it exits with an argparse error. The correct form:

```sh
python -m castcast --media-root /storage/emulated/0/Download/Chromecast serve
```

This is the very first command anyone runs, so it should be fixed everywhere it
appears — including in `REASONING_AND_RESEARCH.TXT`.

### `docs/PACKAGING.md`

The instruction to create
`android/app/src/main/res/xml/network_security_config.xml` cannot be followed:
`mobile/` is a managed (CNG) project with no `android/` directory in git, and
`expo prebuild` regenerates that tree from scratch, discarding hand-edits. The
*advice* is right — scope cleartext to loopback, never app-wide — but the
mechanism has to be the config plugin. Replace that section with a pointer to
`plugins/withLoopbackCleartext.js`.

Also add: the EAS invocation, the `buildType: "apk"` note, and the Doze
guidance that is already correct (`termux-wake-lock`, `~/.termux/boot/`).

### `README.md`

State plainly that `https://chromecast-whisperer.lovable.app` is a
landing/overview page, not the control surface. It is browser JavaScript and
the daemon binds loopback on the phone, so it cannot drive anything. The
shippable UI is `mobile/`. Without this note a future agent may try to package
the Lovable page as the app.

---

## 4. What has *not* been verified

Stated plainly so nobody downstream assumes more than was actually done:

- **Bash execution was unavailable** in the environment where the daemon
  changes above were written. `health.py` and the `doctor` command have not
  been executed or byte-compiled. Review them before trusting them; the logic
  is simple (filesystem stats and `shutil.which`) but it is unrun code.
- `Remuxer.run()` has still never been executed — no ffmpeg binary in the
  build sandbox.
- mDNS discovery has only been tested against a synthetic advert, never a real
  Chromecast.
- None of the mobile files have been type-checked or built; there is no npx or
  tsc in the sandbox.

The first on-device task should be `python -m castcast doctor`, since it
exercises `health.py` end to end and is the cheapest way to find a typo in it.

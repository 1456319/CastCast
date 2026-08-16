<!-- [KEY 0] Agent Jules: File verified structurally sound. -->
# Packaging notes

## Android loopback cleartext

The daemon listens on `http://127.0.0.1:8765`, so Android WebView/Capacitor builds must permit cleartext HTTP for loopback only. Do not set app-wide `android:usesCleartextTraffic="true"`.

This repo enforces the packaging requirement in CI:

1. `pnpm exec cap sync android` generates the native Android project.
2. `node scripts/configure-android-loopback.mjs` writes `android/app/src/main/res/xml/network_security_config.xml` with cleartext enabled only for `127.0.0.1` and `localhost`.
3. The same script patches `<application android:networkSecurityConfig="@xml/network_security_config">` and removes app-wide cleartext if another tool added it.
4. `capacitor.config.ts` sets `server.androidScheme` to `http` so the generated WebView origin matches the loopback HTTP expectation.

## Daemon launch command

In Termux, enter the daemon directory first:

```sh
cd VideoQualityCheckerApp/daemon
python -m castcast --media-root /storage/emulated/0/Download/Chromecast serve
```

If the daemon is already running, use:

```sh
python -m castcast server status
python -m castcast server kill
python -m castcast serve --restart
```

## APK-triggered Termux launch

The Android APK uses Termux's `com.termux.RUN_COMMAND` service rather than an
`intent://` link in the WebView. On rooted target hardware, the app first asks
`su` to carefully configure Termux for external commands: it creates
`~/.termux/termux.properties` when needed, appends `allow-external-apps=true`,
restores Termux ownership / permissions / SELinux context, grants this APK
`com.termux.permission.RUN_COMMAND`, and broadcasts Termux's reload action.

If root is denied or unavailable, Termux can still be prepared manually:

```sh
mkdir -p ~/.termux
echo allow-external-apps=true >> ~/.termux/termux.properties
termux-reload-settings
```

The automatic launch expects the repository to be copied to:

```sh
/storage/emulated/0/Download/VideoQualityCheckerApp/daemon
```

If automatic launch is blocked, the APK shows the manual fallback command:

```sh
cd /storage/emulated/0/Download/VideoQualityCheckerApp/daemon && chmod +x ./termux_bootstrap.sh && ./termux_bootstrap.sh
```

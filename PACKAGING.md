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

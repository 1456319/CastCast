# Android APK

The prototype packages Chaquopy Python 3.13, the CastCast daemon, and arm64
FFmpeg and FFprobe. It targets Android 9 and later on arm64 devices.

Use Python 3.13, JDK 21, the Android 36 SDK, and pnpm 10. From the repository root:

```sh
pnpm install --frozen-lockfile
pnpm run build
pnpm exec cap sync android
bash scripts/bundle-android-ffmpeg.sh
cd android
./gradlew assembleDebug
```

The FFmpeg script fetches the pinned upstream Android binaries and checks the
hashes, architecture, and 16 KB load-segment alignment before packaging them.
Upstream build and license information is at
[Android-FFmpeg-Prebuilt](https://github.com/hzw1199/Android-FFmpeg-Prebuilt/tree/90231cc0105aef4f76926b911535f5eb73511b86).

In the app, Android setup requests applicable runtime permissions. **Shared
storage** opens Android Settings. Restart the daemon after granting shared
storage to switch to `Download/CastCast/Chromecast`. Otherwise the app uses
private media storage. **Check root** opens the root manager only on request.
The daemon runs under the APK's own UID.

The control API binds to loopback. Discovery Mode can still load HTTP URLs.
Prototype CI builds an APK artifact. Release publishing runs on the release branches.

The desktop daemon is still available with `PYTHONPATH=daemon python -m castcast serve`.

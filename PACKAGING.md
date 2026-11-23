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

## CI releases

Pushes to the prototype and release branches run synchronization, frontend and daemon
checks before assembling the APK. The workflow verifies the APK signature, embedded
version and native library alignment before publishing it.

Published Android releases advance the visible version by 0.01 from 2.00.
`versionCode` uses the same value in hundredths, so 2.01 has code 201. A failed run
leaves the published version intact. A rerun of a published commit on the same
channel uses its existing release. Prototype builds are prereleases with
`prototype-v` tags and leave the latest stable release link intact.

### Configure release signing once

Prereleases and stable releases use one persistent PKCS#12 keystore with the
alias `castcast`. A repository owner can create it with a JDK and an authenticated
GitHub CLI. Run this from a private directory outside the checkout.

```sh
umask 077
keytool -genkeypair -storetype PKCS12 -keystore castcast-release.p12 \
  -alias castcast -keyalg RSA -keysize 3072 -validity 10000 \
  -dname 'CN=CastCast'
base64 < castcast-release.p12 | tr -d '\n' | \
  gh secret set CASTCAST_APK_KEYSTORE_BASE64 --repo 1456319/CastCast
gh secret set CASTCAST_APK_SIGNING_PASSWORD --repo 1456319/CastCast
fingerprint=$(keytool -exportcert -keystore castcast-release.p12 \
  -alias castcast | sha256sum | cut -d' ' -f1)
gh variable set CASTCAST_APK_SIGNER_SHA256 --repo 1456319/CastCast \
  --body "$fingerprint"
```

Use the keystore password when the CLI prompts for the signing secret. Keep an
encrypted backup of the keystore and password. GitHub repository secrets hold
the signing inputs and the fingerprint is a public repository variable.
Publishing stops if the signing settings are missing or the APK certificate
differs from the fingerprint. Pull requests only exercise temporary signing.

Switching from the earlier debug-signed APKs takes one reinstall. Back up
app-private data you need before uninstalling. Files in the public CastCast
Downloads folder are independent of APK signing. Future releases signed with
the same key can update the app in place. [Android signing guide](https://developer.android.com/studio/publish/app-signing)

The desktop daemon is still available with `PYTHONPATH=daemon python -m castcast serve`.

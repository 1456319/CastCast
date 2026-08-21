# CastCast Consolidated Roadmap

This roadmap tracks the future evolution of the CastCast project. It condenses previous planning documents, feature proposals, and milestones into a single root source of truth.

## Implemented (Done)
- ~~**Unprivileged UI to Root Daemon Architecture**: React frontend successfully commanding a Python/FFmpeg backend running on the Android device.~~
- ~~**Amazon Prime Video 4K UHD Widevine DRM Streaming**: Cast proxy successfully fetches 4K manifests, strips PlayReady, injects Widevine PSSH boxes, and streams perfectly to Chromecast.~~
- ~~**Automated DRM Subtitle Extraction**: Automatically forces English Subtitle rendering via manifest injection (no OpenSubtitles API required for VOD).~~
- ~~**Automated DRM English Audio Extraction**: Automatically forces English Audio via regex manifest stripping to bypass Shaka Player's broken auto-selection.~~
- ~~**First-Run Privacy Protection**: `DEVICE_ID` is randomized natively on launch to prevent user impersonation or cross-contamination of Amazon watch history.~~
- ~~**Cleartext Loopback / Discovery Mode**: Capacitor WebView is properly configured to bypass Android 9+ Cleartext restrictions for `http://` traffic.~~

## Planned Features (Backlog)

### 1. Dynamic Language & Subtitle Support / Multi-Language Releases
Currently, the proxy is hardcoded to aggressively strip out all non-English audio and subtitle tracks from the manifest. 
- **Short Term**: We should generate specific release builds (APKs/Daemons) tailored for different languages (e.g., CastCast-Spanish, CastCast-German).
- **Long Term**: Implement a UI dropdown in the companion app to allow dynamic selection of the preferred language, which the Python backend will use to conditionally strip the manifest on-the-fly.

### 2. True Local Custom Receiver via DNS Spoofing (100% Google Air-Gap)
Hijack DNS routing on the local network (via iptables/ARP spoofing) so the Chromecast requests the Default Media Receiver URL from the phone's Termux HTTP server. Achieves absolute cryptographic air-gapping and allows a custom UI for language/subtitle selection directly on the TV.

### 3. Adaptive Local HLS Chunking
Generate a local HLS manifest and segment the video on the fly. If network congestion is detected, instruct FFmpeg to transcode upcoming chunks to a lower bitrate, ensuring rigid stream stability.

### 4. Precision Split Audio Routing (Headphone Mode)
Implement aggressive clock synchronization between the Chromecast and the Pixel (via PTP/NTP) over the 8009 socket, and micro-adjust the Android `AudioTrack` sample rate to keep Bluetooth headphones perfectly lip-synced.

### 5. On-the-Fly Dynamic Range Compression
Inject FFmpeg audio filters (`loudnorm` or `dynaudnorm`) to compress the audio dynamic range in real-time before serving it.

### 6. Proactive Hardsubbing for Complex Subtitles (ASS/SSA)
Bypass the Chromecast's native subtitle renderer for complex ASS/SSA tracks by instructing FFmpeg to burn subtitles directly into the video frames on the fly, utilizing the Pixel's hardware encoders.

### 7. Local Intro/Credit Auto-Skipping
Run a background FFmpeg process that scans ahead using `blackframe` or `silencedetect` filters to predict intro/credit boundaries and provide a "Skip Intro" button that triggers a socket seek.

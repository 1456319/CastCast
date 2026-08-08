# Castcast (formerly Video Quality Checker App)

Castcast is a robust, autonomous Android media casting application that completely bypasses Google Home and proprietary middlemen. Built with a Capacitor/React frontend and a powerful Python backend daemon running in Termux, it speaks the native Cast V2 protocol directly to your Chromecast. 

It is designed for power users who want guaranteed compatibility, gapless playback, and total control over their local media streaming experience.

## Features & Abilities

### Direct Cast V2 Communication
Bypass the Google Home sandbox. Castcast opens a raw TLS socket to your Chromecast on port 8009. It natively handles `CONNECT`, `LAUNCH`, and the entire `media` namespace, giving you instantaneous transport controls (Play, Pause, Seek, Volume, Mute) directly from the UI.

### Proactive On-Device Transcoding
No more mid-stream buffering or format failures. Castcast runs a pre-flight probe using `ffprobe` on every video. If the video codec or container is not supported by your Chromecast, the daemon instantly spins up a local `ffmpeg` process to transcode the video (and safely pass through HDR metadata) before streaming it.

### Unified Native Queue Architecture
In Castcast, your local media folder *is* your queue. The app seamlessly interfaces with the Chromecast's internal queue system (`QUEUE_LOAD`, `QUEUE_INSERT`). 
- Gapless auto-advancing managed natively by the Chromecast.
- Moving a file to the "Trash" (marking it as watched) automatically fires a `QUEUE_REMOVE` command to yank it from the active stream dynamically.

### OpenSubtitles Integration
If your media lacks embedded subtitles, Castcast can autonomously connect to the OpenSubtitles API to download and sideload accurate `.srt`/`.vtt` tracks into your active cast session.

### 1-Click Termux Setup & Audit Logging
No manual terminal typing required. The frontend APK uses an Android Intent to silently wake Termux in the background. Termux verifies its storage permissions, checks required directories, installs Python and FFmpeg if missing, and boots the daemon. **Every single setup action is strictly logged to an `audit.log` for total user transparency and trust.**

## Target Use Cases
- **Local Media Libraries**: Users storing high-quality media (e.g., 4K HDR rips) directly on their mobile devices who need guaranteed casting stability.
- **Adaptive Bitrate Enthusiasts**: Preparing the groundwork for dynamic local HLS chunking to survive poor network conditions.
- **Power Users**: Those frustrated by the limited controls and frequent buffering/codec failures of standard casting apps.

## Requirements
- An Android Device (Android 10+)
- **Termux** (Installed from F-Droid or GitHub, as the Play Store version is deprecated)
- The Capacitor APK (Built via `npm run build && npx cap sync android`)

## Architecture
- **Frontend**: React + Vite + Capacitor.
- **Backend (Daemon)**: Python 3 running inside Termux (`castcast` module).
- **Video Engine**: FFmpeg / FFprobe.

## Getting Started
1. Install the APK and Termux on your Android device.
2. Launch the APK.
3. Tap **Launch Daemon (Termux)**. 
4. The app will autonomously request permissions, set up the environment, install FFmpeg/Python, and connect.

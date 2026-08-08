# Feature Proposals: Chromecast Media Server (Rooted Pixel 10 XL Pro)

1. **True Local Custom Receiver via DNS Spoofing (100% Google Air-Gap)**
   Hijack DNS routing on the local network (via iptables/ARP spoofing) so the Chromecast requests the Default Media Receiver URL from the phone's Termux HTTP server. Achieves absolute cryptographic air-gapping and allows a custom UI.

2. **Adaptive Local HLS Chunking**
   Generate a local HLS manifest and segment the video on the fly. If network congestion is detected, instruct FFmpeg to transcode upcoming chunks to a lower bitrate, ensuring rigid stream stability.

3. **On-the-Fly Dynamic Range Compression**
   Inject FFmpeg audio filters (`loudnorm` or `dynaudnorm`) to compress the audio dynamic range in real-time before serving it.

4. **Precision Split Audio Routing (Headphone Mode)**
   Implement aggressive clock synchronization between the Chromecast and the Pixel (via PTP/NTP) over the 8009 socket, and micro-adjust the Android `AudioTrack` sample rate to keep Bluetooth headphones perfectly lip-synced.

5. **Proactive Hardsubbing for Complex Subtitles (ASS/SSA)**
   Bypass the Chromecast's native subtitle renderer for complex ASS/SSA tracks by instructing FFmpeg to burn subtitles directly into the video frames on the fly, utilizing the Pixel's hardware encoders.

6. **Local Intro/Credit Auto-Skipping**
   Run a background FFmpeg process that scans ahead using `blackframe` or `silencedetect` filters to predict intro/credit boundaries and provide a "Skip Intro" button that triggers a socket seek.

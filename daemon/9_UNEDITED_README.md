<!-- [KEY 0] Agent Jules: File verified structurally sound. -->
# castcast

A Chromecast controller daemon that stays out of the Google Home ecosystem.

Speaks CASTv2 directly to the device over TLS on your LAN, serves media from
local storage over HTTP, aggressively maintains the connection, and **refuses to
send a LOAD it can predict will fail.**

Built for a rooted Pixel running Termux, pointed at a Chromecast Ultra.

---

## What "outside Google Home" actually means

You cannot sever the device from Google entirely, and this project does not try.
The Ultra phones home at boot, and the initial setup handshake is a cryptographic
exchange with Google's servers that is not worth fighting. What *is* achievable
is that **once the device is set up, nothing in the playback path touches
Google**:

| Concern | How castcast handles it |
|---|---|
| Receiver app | Launches `CC1AD845`, the stock Default Media Receiver. Public app ID, no developer registration, no custom receiver hosted on Google's CDN. |
| Where the bytes come from | Our own HTTP server on the phone. The device pulls over the LAN. Nothing is uploaded anywhere. |
| Discovery | mDNS on the local link, or a pinned static IP. No cloud device registry. |
| Control | A direct TLS socket to port 8009. No Home app, no Cast SDK, no Google account. |

The one unavoidable dependency is that the receiver firmware itself is Google's.

## Design, and where it came from

The transport and state machine follow **VLC's** `modules/stream_out/chromecast/`,
which is the best-engineered open implementation of this protocol:

- Explicit state machine rather than ad-hoc booleans.
- A heartbeat budget (`PING_WAIT_TIME` / `PING_WAIT_RETRIES`) so a dead link is
  detected in seconds instead of whenever TCP eventually notices.
- A hard distinction between a namespace-level `CLOSE` (the *app* exited →
  relaunch it) and a socket death (→ full reconnect). Conflating these causes
  pointless reconnect storms.
- `reinit()` from a `Dead` state instead of trying to patch a broken socket.
- A randomised HTTP root path, exactly like VLC's `vlc_mrand48()` trick.

Two deliberate departures:

1. **The upstream `Chromecast-Controller` gave up on persistent connections**
   ("Chromecast links eventually drop") and used systemd socket activation with
   short-lived processes. That is right for bursty volume commands on a Linux
   box; it is wrong here. There is no systemd on Android, and a two-hour 4K cast
   is the opposite of bursty. We hold one supervised link open instead. Its
   *other* idea — one shared daemon with a local socket API rather than every
   app embedding its own cast stack — is kept.

2. **Session restore.** On any reconnect we re-`LOAD` the current media and seek
   back to where we were. This turns a dropped link from "playback ends" into "a
   two-second stutter", which is the single most valuable behaviour for stream
   stability.

## Why your 4K probably isn't 4K

The Default Media Receiver **fails silently**. Hand it something it cannot decode
and you get a brief loading spinner, then an empty player — no error, no
`MEDIA_STATUS`, nothing. That failure is indistinguishable from a network drop,
which is why "why isn't this 4K?" is so hard to answer from the couch.

So castcast probes every file with `ffprobe` and checks it against the published
Chromecast Ultra matrix *before* casting. The rules that actually bite:

| Rule | Consequence |
|---|---|
| HEVC is **not supported in MPEG-TS** | The single most common silent 4K failure. Remux to MP4 — lossless. |
| H.264 caps at **4K/30** | 4K60 requires HEVC or VP9 Profile 2. No setting fixes this. |
| HEVC Main/Main10 → 4K/60, VP9 Profile 2 → 4K/60 | These are the only real 4K60 paths. |
| MKV is unreliable | Remux to MP4 even when the codecs are fine. |
| DTS / TrueHD unsupported | The receiver rejects the **whole file**, video included. |
| AC3 / E-AC3 need HDMI passthrough | Straight into a TV this is usually silence, not failure. |
| Dolby Vision cannot ride on VP9 | Requires HEVC. |
| Level > 5.1 | Stutters or fails. |

When a file fails, castcast tells you *why* and hands back the exact ffmpeg
command. It never re-encodes video when a remux will do:

```sh
# container is wrong, codecs are fine -> lossless, disk-speed
ffmpeg -i input.ts -c:v copy -c:a copy -movflags +faststart output.mp4

# audio is unsupported -> re-encode audio only, video untouched
ffmpeg -i input.ts -c:v copy -c:a aac -movflags +faststart output.mp4
```

It also adds `-tag:v hvc1` for HEVC in MP4 (an `hev1`-tagged track is another
classic silent-failure cause) and drops subtitle/chapter tracks, which the
default receiver cannot render and which frequently break the MP4 muxer.

A full video re-encode is never started implicitly — `cast` returns
`requires_confirmation` and makes you ask for it.

## Install

```sh
pkg install python ffmpeg          # Termux
termux-setup-storage               # grants access to /storage/emulated/0
```

No Python dependencies. The `CastMessage` protobuf is hand-rolled (~150 lines)
specifically to avoid needing `protoc` or `grpcio` on-device.

Then enter the daemon directory first. If you run from the repository root, Python can report that `castcast` is missing, which makes it look like a module problem even though `castcast` is the package inside `daemon/`:

```sh
cd VideoQualityCheckerApp/daemon
```

Then confirm the setup actually took:

```sh
python -m castcast --media-root /storage/emulated/0/Download/Chromecast doctor
```

`doctor` checks the pieces that fail independently and blame each other —
ffmpeg on `PATH`, the media folder being *readable* (not merely present, which
is the difference `termux-setup-storage` makes), and whether we have a LAN
address at all. Each failing row prints the literal command that fixes it, and
the exit code is 0 only when nothing blocking is wrong, so it works as a gate:

```sh
python -m castcast --media-root /storage/emulated/0/Download/Chromecast doctor && \
  python -m castcast --media-root /storage/emulated/0/Download/Chromecast serve
```

A `127.0.0.1` LAN address is worth calling out: casting would still "succeed"
at the CASTv2 layer, and the receiver would then sit on a spinner forever,
because the LOAD URL it was handed resolves to itself.

## Use

```sh
# Pre-flight without casting -- the most useful command in the project
python -m castcast check /storage/emulated/0/Download/Chromecast/movie.mkv

# Pre-flight everything at once
python -m castcast scan

# Find the device (or skip this and pin the IP -- see below)
python -m castcast devices

# Convert, then cast
python -m castcast prepare movie.mkv
python -m castcast --host 192.168.1.50 cast movie.cast.mp4

# Run the daemon for the UI / other clients
python -m castcast --media-root /storage/emulated/0/Download/Chromecast serve

# Check, stop, or restart an already-running daemon
python -m castcast server status
python -m castcast server kill
python -m castcast serve --restart
```

### Pin the IP

mDNS is the least reliable part of the stack: plenty of routers drop multicast,
and Android will not deliver multicast to userspace without a `MulticastLock`.
Give the Ultra a DHCP reservation and pin it:

```json
{
  "media_roots": ["/storage/emulated/0/Download/Chromecast"],
  "static_host": "192.168.1.50",
  "auto_connect_host": "192.168.1.50",
  "avr_passthrough": false
}
```

at `~/.config/castcast/config.json`. Discovery is then never on the critical path.

## Control API

`127.0.0.1:8765` by default — localhost only, so nothing off-device can drive
your TV.

```
GET  /status                 daemon + connection state
GET  /health                 readiness checklist; every failure carries a remedy
GET  /devices                discover
GET  /library?deep=1         media list, with pre-flight verdicts
GET  /preflight?path=        probe + verdict + ffmpeg plan
GET  /logs?since=N           recent log lines
GET  /events                 SSE: logs, state changes, media status
POST /connect                {host, port?}
POST /cast                   {path, allow_unsafe?, auto_prepare?}
POST /prepare                {path, force?}
POST /play /pause /stop
POST /seek                   {position}
POST /volume                 {level}
POST /mute                   {muted}
```

## Stability features

- **Heartbeat budget** — dead link detected in ~18s (`6s x 3`), verified against
  a black-hole peer, rather than waiting on TCP.
- **Session restore** — reconnect re-LOADs and seeks back to position.
- **Backoff** — `0.5s → 30s`, deliberately aggressive at the start because most
  drops are transient Wi-Fi blips where an immediate retry just works.
- **Roam detection** — our LOAD URL embeds our own LAN IP. If the phone's
  address changes mid-cast the receiver's HTTP pull breaks and no amount of
  CASTv2 reconnecting fixes it, so a watchdog re-issues the LOAD with the new URL.
- **Stall detection** — nominally `PLAYING` but the position clock is not
  advancing usually means our HTTP server stopped feeding the device fast enough.
- **TCP keepalive** alongside the app-level heartbeat.
- **Range requests** — mandatory, not a nicety; without them the receiver cannot
  seek and large files stall.

## Layout

| File | Role |
|---|---|
| `protobuf.py` | Hand-rolled `CastMessage` codec |
| `channel.py` | TLS socket, framing, namespaces, virtual connections |
| `supervisor.py` | The state machine: heartbeat, reconnect, session restore |
| `discovery.py` | mDNS (pure Python), avahi fallback, static pin, cache |
| `mediaserver.py` | LAN HTTP server with Range support + random root token |
| `probe.py` | ffprobe → normalised `MediaInfo` |
| `capability.py` | Ultra matrix + verdict engine |
| `health.py` | Readiness checks: tools, storage, LAN — each with a remedy |
| `remux.py` | Verdict → ffmpeg plan, with progress |
| `service.py` | Wires it together; library, pre-flight, cast pipeline |
| `api.py` | Local JSON API + SSE |

## Testing status

Verified against a mock receiver (real TLS, real CASTv2 framing, real protobuf):
protocol round-trip, full handshake (`CONNECT → GET_STATUS → LAUNCH → CONNECT →
LOAD`), heartbeat, transport controls, dead-link detection at 18s, and
reconnect-with-resume. HTTP Range/HEAD/traversal and the mDNS parser (including
name compression) are covered too.

**Not yet exercised on real hardware**, and the ffmpeg execution path has not
been run — the sandbox this was built in has no ffmpeg binary. The commands are
constructed correctly but `Remuxer.run()` needs a real-world pass.

`health.py`, `GET /health` and the `doctor` command are **unrun**: they were
added in a later session where shell execution was unavailable, so they have
not been byte-compiled or executed. The logic is only filesystem stats and
`shutil.which`, but treat it as unverified until `castcast doctor` has been run
once on-device — which is also the cheapest way to smoke-test it.

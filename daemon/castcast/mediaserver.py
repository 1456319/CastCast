"""Local LAN HTTP server that the Chromecast pulls bytes from.

This is the piece that keeps Google out of the loop.  We never upload anything
anywhere: we serve the file off the phone's own storage and hand the receiver a
``http://<phone-lan-ip>:<port>/<random>/<file>`` URL in the LOAD payload.  The
device streams directly from us over the LAN.

VLC does exactly this (its ``chromecast`` sout module spins up an HTTP access
output and randomises the root path with ``vlc_mrand48()``).  We copy the
randomised-path trick: it stops anything else on the LAN from trivially
enumerating your Downloads folder while a cast is live.

Range support is mandatory, not a nicety -- without it the receiver cannot
seek, and large files stall.
"""

from __future__ import annotations

import os
import posixpath
import re
import secrets
import socket
import subprocess
import threading
import shutil
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")

MIME_TYPES = {
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".mov": "video/mp4",
    ".webm": "video/webm",
    ".mkv": "video/x-matroska",
    ".ts": "video/mp2t",
    ".m3u8": "application/x-mpegURL",
    ".mpd": "application/dash+xml",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".flac": "audio/flac",
    ".wav": "audio/wav",
    ".opus": "audio/ogg",
    ".vtt": "text/vtt",
    ".srt": "text/plain",
}


def guess_mime(path: str) -> str:
    import urllib.parse, base64
    if "/proxy/" in path and "url=" in path:
        try:
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(path).query)
            if "url" in query:
                path = base64.b64decode(query["url"][0]).decode("utf-8")
        except Exception:
            pass
    return MIME_TYPES.get(os.path.splitext(urllib.parse.urlsplit(path).path)[1].lower(), "video/mp4")


def detect_lan_ip(target: str = "8.8.8.8") -> str:
    """Find the IP the kernel would use to reach the LAN.

    We open a UDP socket to an off-link address -- no packets are actually
    sent, but the routing table picks a source address for us.  This is far
    more reliable on Android than parsing interface lists, and it naturally
    picks the Wi-Fi interface over cellular.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect((target, 53))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "castcast"
    sys_version = ""

    # -- plumbing ---------------------------------------------------------

    def log_message(self, fmt, *args):  # noqa: A003
        server: "MediaServer" = self.server.media_server  # type: ignore[attr-defined]
        server.log(f"http {self.address_string()} {fmt % args}")

    def _resolve(self) -> Optional[str]:
        server: "MediaServer" = self.server.media_server  # type: ignore[attr-defined]
        path = urllib.parse.urlsplit(self.path).path
        prefix = f"/{server.root_token}/"
        if not path.startswith(prefix):
            return None

        rel = urllib.parse.unquote(path[len(prefix):])
        # Normalise and refuse anything that escapes the served roots.
        rel = posixpath.normpath(rel).lstrip("/")
        if rel.startswith("..") or os.path.isabs(rel):
            return None

        for root in server.roots:
            candidate = os.path.realpath(os.path.join(root, rel))
            if candidate == os.path.realpath(root) or candidate.startswith(
                    os.path.realpath(root) + os.sep):
                if os.path.isfile(candidate):
                    return candidate
        return None

    # -- verbs ------------------------------------------------------------

    def do_OPTIONS(self):  # noqa: N802
        self.server.media_server._logger(f"Received OPTIONS: {self.path}")
        if self.path.startswith("/drm/") or self.path.startswith("/amazon/license"):
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "*")
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.end_headers()
            return
        self.send_error(405)

    def do_POST(self):
        self.server.media_server._logger(f"Received POST: {self.path}")

        # ====================================================================
        # [AMAZON LICENSE PROXY ENDPOINT]
        # This endpoint (/amazon/license?title_id=...) acts as a Widevine 
        # license proxy between the Chromecast and Amazon's DRM servers.
        #
        # Flow: Chromecast CDM -> HTTPS tunnel -> this proxy -> Amazon API
        #       -> raw license bytes -> back to CDM
        #
        # 1. The Chromecast sends the Widevine challenge as the raw POST body.
        # 2. We forward it to Amazon's GetWidevineLicense endpoint using the
        #    stored actor_token and playback_envelope.
        # 3. We return the raw license bytes with Content-Type: application/octet-stream.
        #
        # CRITICAL: The Content-Length header MUST be set on the response. 
        # Without it, Shaka Player (the Chromecast receiver) cannot determine
        # when the license download is complete on a keep-alive connection.
        # It will time out after ~10 seconds, retry, get another valid license,
        # time out again, and loop forever. The Chromecast will appear stuck
        # in `buffering` state with position 0.0. This bug took many hours to
        # diagnose because the license data itself was correct — it was the HTTP
        # framing that was broken.
        #
        # NOTE: CORS headers (Access-Control-Allow-Origin: *) are required 
        # because the Shaka Player receiver runs in a browser context.
        # ====================================================================
        if self.path.startswith("/amazon/license"):
            import urllib.parse
            from . import amazon_drm
            
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            title_id = qs.get("title_id", [""])[0]
            
            amazon_data = self.server.media_server.drm_tokens.get(f"amazon_{title_id}")
            if not amazon_data:
                self.send_response(404)
                self.end_headers()
                return
                
            content_length = int(self.headers.get('Content-Length', 0))
            challenge_bytes = self.rfile.read(content_length)
            
            self.server.media_server._logger(f"Proxying Amazon Widevine License for {title_id}")
            try:
                license_bytes = amazon_drm.fetch_widevine_license(
                    amazon_data["actor_token"],
                    amazon_data["playback_envelope"],
                    challenge_bytes
                )
                self.send_response(200)
                self.send_header("Content-Length", str(len(license_bytes)))
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(license_bytes)
            except Exception as e:
                self.server.media_server._logger(f"Amazon License Proxy Error: {e}")
                self.send_response(500)
                self.end_headers()
            return

        if self.path.startswith("/drm/"):
            self._serve_drm()
        else:
            self.send_error(405)

    def _serve_drm(self):
        server: "MediaServer" = self.server.media_server
        token_id = self.path.split("/")[-1]
        
        if token_id not in server.drm_tokens:
            self.send_error(404, "DRM token not found")
            return
            
        binary_token = server.drm_tokens[token_id]
        
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(binary_token)))
        self.end_headers()
        self.wfile.write(binary_token)

    def do_HEAD(self):  # noqa: N802
        if self.path.startswith("/proxy/"):
            self._serve_proxy(body=False)
        else:
            self._serve(body=False)

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/proxy/"):
            self._serve_proxy(body=True)
        else:
            self._serve(body=True)

    def _serve_proxy(self, body: bool = True):
        import base64
        import urllib.request
        import urllib.error
        server: "MediaServer" = self.server.media_server

        path_obj = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(path_obj.query)
        encoded_url = query.get("url", [""])[0]
        if not encoded_url:
            self.send_error(400, "Missing url parameter")
            return

        try:
            target_url = base64.b64decode(encoded_url).decode("utf-8")
        except Exception:
            self.send_error(400, "Invalid base64 url")
            return

        domain = urllib.parse.urlsplit(target_url).netloc
        headers = server.get_intercept_headers(domain)
        if "Range" in self.headers:
            headers["Range"] = self.headers["Range"]

        try:
            req = urllib.request.Request(target_url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as response:
                content_type = response.headers.get("Content-Type", "application/octet-stream")

                # If this is an HLS manifest, rewrite it!
                if "mpegurl" in content_type.lower() or target_url.endswith(".m3u8"):
                    body_content = response.read().decode("utf-8", "replace")
                    rewritten = []
                    for line in body_content.splitlines():
                        line = line.strip()
                        if line and not line.startswith("#"):
                            abs_uri = urllib.parse.urljoin(target_url, line)
                            encoded = base64.b64encode(abs_uri.encode("utf-8")).decode("utf-8")
                            rewritten.append(f"http://{server.lan_ip}:{server.port}/proxy/?url={encoded}")
                        else:
                            rewritten.append(line)
                    
                    final_body = "\n".join(rewritten).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.send_header("Content-Length", str(len(final_body)))
                    self.end_headers()
                    if body:
                        self.wfile.write(final_body)

                # ====================================================================
                # [DASH MANIFEST PROXY BLOCK]
                # When the Chromecast fetches the Amazon DASH manifest through our
                # proxy, we MUST modify it in-flight. Three transformations happen:
                #
                # 1. BaseURL injection: Amazon's segment URLs are relative, but since 
                #    the Chromecast fetched the manifest from OUR proxy (not Amazon), 
                #    relative URLs would resolve against our server. We inject a 
                #    <BaseURL> pointing to the original Amazon CDN directory so 
                #    segments are fetched directly from Amazon.
                #
                # 2. PlayReady stripping: Amazon includes PlayReady ContentProtection 
                #    blocks (UUID 9A04F079...). The Chromecast Ultra only has a 
                #    Widevine CDM. If PlayReady blocks remain, the CDM gets confused. 
                #    We strip them entirely.
                #
                # 3. Widevine PSSH box wrapping: This is the most critical transformation.
                #    Amazon's <cenc:pssh> tags contain BARE Widevine protobuf data 
                #    (the init data). Standard PSSH boxes must be wrapped in an MP4 
                #    box header. The `fix_widevine_pssh` function wraps each bare 
                #    protobuf in a compliant MP4 pssh box:
                #      - 4 bytes: total box size (big-endian uint32)
                #      - 4 bytes: literal ASCII `pssh`
                #      - 4 bytes: version + flags (0x00000000 for version 0)
                #      - 16 bytes: Widevine System ID (EDEF8BA9-79D6-4ACE-A3C8-27DCD51D21ED)
                #      - 4 bytes: data size (big-endian uint32)
                #      - N bytes: the original protobuf data
                #
                # WARNING: If ANY of these 32 header bytes are wrong, the Widevine 
                # CDM will silently reject the init data and playback will never start. 
                # The Chromecast will sit in `buffering` state forever.
                #
                # CRITICAL: After modifying the manifest body, we MUST recalculate 
                # Content-Length. If Content-Length is wrong or missing, the 
                # Chromecast's HTTP client will either hang (waiting for more bytes) 
                # or truncate (cutting off the manifest). Both cause LOAD_FAILED.
                # ====================================================================
                elif "dash+xml" in content_type.lower() or target_url.endswith(".mpd"):
                    import re, base64
                    body_content = response.read().decode("utf-8", "replace")
                    
                    # Amazon's MPD URLs are relative, but if we proxied the MPD, we changed the base URL!
                    # We MUST insert a <BaseURL> pointing to the original Amazon MPD directory!
                    base_url = target_url[:target_url.rfind('/')+1]
                    body_content = re.sub(r'(<MPD[^>]*>)', r'\1\n  <BaseURL>' + base_url + r'</BaseURL>', body_content, count=1)
                    
                    # Strip out non-English audio and text/subtitle tracks
                    def filter_english(match):
                        tag = match.group(0)
                        lang_match = re.search(r'lang="([^"]+)"', tag)
                        if lang_match:
                            lang = lang_match.group(1).lower()
                            if not lang.startswith("en"):
                                return ""
                                
                        # We will no longer mangle the Role tag. Amazon uses 'caption'.
                        # Mangling it to 'forced_subtitle' may be breaking Shaka's internal sync engine on seek.
                        return tag
                    body_content = re.sub(r'<AdaptationSet[^>]*>.*?</AdaptationSet>', 
                        lambda m: filter_english(m) if any(attr in m.group(0) for attr in ['contentType="audio"', 'contentType="text"', 'contentType="subtitle"', 'mimeType="audio"', 'mimeType="text"']) else m.group(0), 
                        body_content, flags=re.DOTALL)
                    
                    # Strip PlayReady ContentProtection entirely
                    body_content = re.sub(r'<ContentProtection[^>]*schemeIdUri="urn:uuid:9A04F079-9840-4286-AB92-E65BE0885F95"[^>]*>.*?</ContentProtection>', '', body_content, flags=re.DOTALL)
                    
                    # Wrap the remaining bare Widevine protobufs in valid MP4 pssh boxes
                    def fix_widevine_pssh(match):
                        inner_b64 = match.group(1)
                        try:
                            decoded = base64.b64decode(inner_b64)
                            if len(decoded) > 8 and decoded[4:8] == b'pssh':
                                return match.group(0) # Already valid
                            system_id = bytes.fromhex("EDEF8BA979D64ACEA3C827DCD51D21ED")
                            box = bytearray()
                            box.extend((32 + len(decoded)).to_bytes(4, 'big'))
                            box.extend(b'pssh')
                            box.extend(b'\x00\x00\x00\x00')
                            box.extend(system_id)
                            box.extend(len(decoded).to_bytes(4, 'big'))
                            box.extend(decoded)
                            valid_b64 = base64.b64encode(box).decode('utf-8')
                            return f'<cenc:pssh>{valid_b64}</cenc:pssh>'
                        except:
                            return match.group(0)
                    
                    body_content = re.sub(r'<cenc:pssh>\s*(.*?)\s*</cenc:pssh>', fix_widevine_pssh, body_content, flags=re.DOTALL)
                    
                    final_body = body_content.encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.send_header("Content-Length", str(len(final_body)))
                    self.end_headers()
                    if body:
                        self.wfile.write(final_body)

                else:
                    # Stream the raw chunks directly to the TV
                    self.send_response(response.status)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Access-Control-Allow-Origin", "*")
                    if "Content-Length" in response.headers:
                        self.send_header("Content-Length", response.headers["Content-Length"])
                    if "Content-Range" in response.headers:
                        self.send_header("Content-Range", response.headers["Content-Range"])
                    if "Accept-Ranges" in response.headers:
                        self.send_header("Accept-Ranges", response.headers["Accept-Ranges"])
                    if "Content-Encoding" in response.headers:
                        self.send_header("Content-Encoding", response.headers["Content-Encoding"])
                    self.end_headers()
                    
                    if body:
                        import shutil
                        shutil.copyfileobj(response, self.wfile)

        except Exception as e:
            server.log(f"Proxy error for {target_url}: {e}")
            if not self.wfile.closed:
                try:
                    self.send_error(500, "Proxy error")
                except:
                    pass
            # Trigger shadow telemetry for the failure
            server.trigger_telemetry(target_url, str(e))

    def _serve(self, body: bool) -> None:
        server: "MediaServer" = self.server.media_server  # type: ignore
        path_obj = urllib.parse.urlsplit(self.path)
        prefix = f"/{server.root_token}/live/"
        if path_obj.path.startswith(prefix):
            stream_id = path_obj.path[len(prefix):].replace(".ts", "")
            if stream_id not in server.live_streams:
                self.send_error(404, "Stream Not Found")
                return
            cfg = server.live_streams[stream_id]
            self.send_response(200)
            self.send_header("Content-Type", "video/mp2t")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            if not body:
                return
            cmd = ["ffmpeg", "-i", cfg["v"], "-i", cfg["a"], "-c", "copy", "-f", "mpegts", "pipe:1"]
            proc = None
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                def log_err():
                    if proc and proc.stderr:
                        for line in proc.stderr:
                            server.log(f"[ffmpeg] {line.decode('utf-8', errors='replace').strip()}")
                threading.Thread(target=log_err, daemon=True).start()
                while True:
                    chunk = proc.stdout.read(256 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError, FileNotFoundError, OSError):
                pass
            finally:
                if proc:
                    proc.kill()
            return

        full = self._resolve()
        if full is None:
            self.send_error(404, "Not Found")
            return

        try:
            size = os.path.getsize(full)
            handle = open(full, "rb")
        except OSError as exc:
            self.send_error(404, f"Not Found: {exc}")
            return

        with handle:
            start, end = 0, size - 1
            partial = False
            rng = self.headers.get("Range")
            if rng:
                match = _RANGE_RE.fullmatch(rng.strip())
                if match:
                    lo, hi = match.group(1), match.group(2)
                    if lo:
                        start = int(lo)
                        if hi:
                            end = min(int(hi), size - 1)
                    elif hi:  # suffix range: last N bytes
                        start = max(size - int(hi), 0)
                    if start > end or start >= size:
                        self.send_response(416)
                        self.send_header("Content-Range", f"bytes */{size}")
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                    partial = True

            length = end - start + 1
            self.send_response(206 if partial else 200)
            self.send_header("Content-Type", guess_mime(full))
            self.send_header("Content-Length", str(length))
            self.send_header("Accept-Ranges", "bytes")
            # The receiver's media element is subject to CORS for some
            # request types; being permissive here costs nothing on a LAN
            # path that is already protected by the random root token.
            self.send_header("Access-Control-Allow-Origin", "*")
            if partial:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()

            if not body:
                return

            handle.seek(start)
            remaining = length
            chunk_size = 256 * 1024
            try:
                while remaining > 0:
                    chunk = handle.read(min(chunk_size, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                # Entirely normal: the receiver closes the socket on seek/stop.
                pass


class MediaServer:
    """Threaded HTTP server exposing one or more directories under a random path."""

    def __init__(self, roots, port: int = 0, bind: str = "0.0.0.0", logger=None, on_telemetry=None):
        self.roots = [os.path.realpath(r) for r in roots]
        self.root_token = secrets.token_urlsafe(12)
        self._bind = bind
        self._requested_port = port
        self._logger = logger
        self._on_telemetry = on_telemetry
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self.drm_tokens: dict[str, bytes] = {}
        self.lan_ip = detect_lan_ip()
        self.live_streams: dict[str, dict] = {}
        self.intercept_rules: dict[str, dict] = {}

        telemetry_dir = "/storage/emulated/0/Download/CastCast/Chromecast/.castcast/telemetry"
        try:
            os.makedirs(telemetry_dir, exist_ok=True)
        except OSError as e:
            if self._logger: self._logger(f"Could not create telemetry dir: {e}")
        self.telemetry_log = os.path.join(telemetry_dir, "failed_manifests.jsonl")

    def log(self, message: str) -> None:
        if self._logger:
            self._logger(message)

    @property
    def port(self) -> int:
        return self._httpd.server_address[1] if self._httpd else 0

    @property
    def running(self) -> bool:
        return self._httpd is not None

    @property
    def base_url(self) -> str:
        return f"http://{self.lan_ip}:{self.port}/{self.root_token}/"

    def register_live_stream(self, v_url: str, a_url: str) -> str:
        stream_id = secrets.token_urlsafe(8)
        self.live_streams[stream_id] = {"v": v_url, "a": a_url}
        return f"http://{self.lan_ip}:{self.port}/{self.root_token}/live/{stream_id}.ts"

    def register_intercept(self, url: str, headers: dict):
        domain = urllib.parse.urlsplit(url).netloc

        # Clean headers (remove forbidden/problematic headers for proxying)
        clean_headers = {}
        for k, v in headers.items():
            k_lower = k.lower()
            if k_lower not in ("host", "connection", "accept-encoding"):
                clean_headers[k] = v

        self.intercept_rules[domain] = clean_headers
        self._logger(f"Registered proxy ruleset for domain: {domain}")

    def get_intercept_headers(self, domain: str) -> dict:
        return self.intercept_rules.get(domain, {})

    def trigger_telemetry(self, failed_url: str, error_msg: str):
        import json, time
        # Anonymized logging: we do NOT log full URLs or query params to protect PII/tokens
        domain = urllib.parse.urlsplit(failed_url).netloc
        ext = os.path.splitext(urllib.parse.urlsplit(failed_url).path)[1]

        telemetry_data = {
            "timestamp": int(time.time()),
            "domain": domain,
            "extension": ext,
            "error": error_msg,
        }

        try:
            with open(self.telemetry_log, "a") as f:
                f.write(json.dumps(telemetry_data) + "\n")
            self._logger(f"Shadow Telemetry: Logged anonymous failure signature for {domain}")

            if self._on_telemetry:
                self._on_telemetry(telemetry_data)
        except Exception as e:
            self._logger(f"Failed to write telemetry: {e}")

    def start(self) -> None:
        if self._httpd:
            return
        httpd = ThreadingHTTPServer((self._bind, self._requested_port), _Handler)
        httpd.daemon_threads = True
        httpd.media_server = self  # type: ignore[attr-defined]
        self._httpd = httpd
        self._thread = threading.Thread(target=httpd.serve_forever,
                                        kwargs={"poll_interval": 0.5},
                                        name="castcast-http", daemon=True)
        self._thread.start()
        self._logger(f"media server listening on {self.base_url}")
        
        # ====================================================================
        # [SSH TUNNEL SETUP]
        # The Chromecast requires HTTPS for license server URLs (mixed content 
        # policy). Our local HTTP server can't serve HTTPS without certificates.
        #
        # We establish an SSH reverse tunnel to localhost.run which provides a 
        # free HTTPS endpoint. The public URL (e.g. `https://xxxxx.lhr.life`) 
        # is stored as `self.public_url` and used as the DRM license server 
        # URL passed to the Chromecast.
        #
        # If SSH is not available, we fall back to plain HTTP (which may fail 
        # on newer Chromecast firmware due to mixed content blocking).
        # ====================================================================
        # Start SSH tunnel for HTTPS DRM proxy
        import subprocess

        import time

        
        self.public_url = None
        self._ssh_process = None
        
        def start_tunnel():
            try:
                self._ssh_process = subprocess.Popen(
                    ["ssh", "-o", "StrictHostKeyChecking=no", "-R", f"80:localhost:{self.port}", "nokey@localhost.run"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True
                )
                for line in self._ssh_process.stdout:
                    if "http" in line and "lhr.life" in line:
                        urls = [word for word in line.split() if word.startswith("https://")]
                        for u in urls:
                            self.public_url = u
                            break
                        if self.public_url:
                            self._logger(f"Established public HTTPS tunnel for DRM: {self.public_url}")
                            break
                        if self.public_url:
                            break
            except Exception as e:
                self._logger(f"Failed to start SSH tunnel: {e}")
                
        if shutil.which("ssh"):
            threading.Thread(target=start_tunnel, daemon=True).start()
        else:
            self._logger("ssh is not installed, cannot start public HTTPS tunnel for DRM")

    def stop(self) -> None:
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        self._thread = None
        if hasattr(self, '_ssh_process') and self._ssh_process:
            try:
                self._ssh_process.terminate()
            except Exception:
                pass
            self._ssh_process = None

    def rotate_token(self) -> None:
        """Invalidate every previously issued URL."""
        self.root_token = secrets.token_urlsafe(12)

    def refresh_lan_ip(self) -> bool:
        """Re-detect our LAN IP. Returns True if it changed (i.e. we roamed)."""
        current = detect_lan_ip()
        if current != self.lan_ip:
            self._logger(f"LAN IP changed {self.lan_ip} -> {current}")
            self.lan_ip = current
            return True
        return False

    def url_for(self, path: str) -> str:
        """Build a servable URL for an absolute path inside one of our roots."""
        real = os.path.realpath(path)
        for root in self.roots:
            if real == root or real.startswith(root + os.sep):
                rel = os.path.relpath(real, root)
                quoted = urllib.parse.quote(rel.replace(os.sep, "/"))
                return f"http://{self.lan_ip}:{self.port}/{self.root_token}/{quoted}"
        raise ValueError(f"{path} is not inside a served root: {self.roots}")

    def add_drm_token(self, b64_token: str) -> str:
        """Decode and store a Widevine base64 token, returning its local URL."""
        import base64
        import hashlib
        binary_token = base64.b64decode(b64_token)
        token_id = hashlib.md5(binary_token).hexdigest()
        self.drm_tokens[token_id] = binary_token
        return f"http://{self.lan_ip}:{self.port}/drm/{token_id}"

    def add_root(self, path: str) -> None:
        real = os.path.realpath(path)
        if real not in self.roots:
            self.roots.append(real)

# synchronization-map: section=api-contract; role=http-and-sse-server; boundaries=core-service,web-client,operations-release; doc=docs/SYNCHRONIZATION_MAP.md
# EDITING OF THIS FILE MAY CAUSE CATASTROPHIC APP DESYCHRONIZATION. Reference the directory at at ~/docs/synchronization_map.md to determine what other files must be adjusted in order to ensure absolute synchronization is maintained. This is to ensure that the APK, termux daemon, and chromecast portions of the app are always in synchronous, deterministic states.
"""Local JSON control API + SSE event stream.

Binds to 127.0.0.1 by default so nothing off-device can drive your TV.  The UI
(a PWA, a Tasker task, a shell script, whatever) talks to this.
"""

from __future__ import annotations

import os
import traceback
import json
import re
import urllib.parse
import urllib.request
import queue
import threading

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .service import CastService
from .metadata import resolve_title

API_PORT = 8765

AUDIT_LOG_CANDIDATES = [
    "/storage/emulated/0/Download/CastCast/Chromecast/.castcast/audit.log",
    os.path.expanduser("~/.config/castcast/audit.log"),
    "/tmp/castcast.log",
    "/var/log/audit/audit.log",
]


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "castcast-api"
    sys_version = ""

    @property
    def service(self) -> CastService:
        return self.server.service  # type: ignore[attr-defined]

    def log_message(self, fmt, *args):  # noqa: A003
        pass  # too chatty; the service has its own log

    # -- helpers -----------------------------------------------------------

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")

    def _json(self, payload, code: int = 200):
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8")) or {}
        except json.JSONDecodeError:
            return {}

    def do_OPTIONS(self):  # noqa: N802
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    # -- routes ------------------------------------------------------------

    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlsplit(self.path)
        route = parsed.path.rstrip("/") or "/"
        params = urllib.parse.parse_qs(parsed.query)

        def one(key, default=None):
            return (params.get(key) or [default])[0]

        try:
            if route == "/":
                self._json({"service": "castcast", "endpoints": _ROUTES})
            elif route == "/status":
                self._json(self.service.status())
            elif route == "/health":
                self._json(self.service.health())
            elif route == "/devices":
                self._json({"devices": self.service.discover(
                    timeout=float(one("timeout", 4.0)))})
            elif route == "/library":
                self._json({"items": self.service.library(
                    deep=one("deep") in ("1", "true", "yes"))})
            elif route == "/trash":
                self._json({"items": self.service.get_trash()})
            elif route == "/amazon/auth":
                from . import amazon
                return self._json(amazon.create_code_pair())
            
            elif route == "/amazon/poll":
                from . import amazon
                pub = one("public_code")
                priv = one("private_code")
                return self._json(amazon.poll_register(pub, priv))
            elif route == "/amazon/queue":
                self._json({"items": self.service.amazon_queue})
            elif route == "/subtitles/available":
                self._json(self.service.get_available_subtitles())
            elif route == "/subtitles/remote":
                query = one("query") or ""
                imdb_id = one("imdb_id") or ""
                lang = one("language")
                languages = [lang] if lang else None
                if query or imdb_id or languages:
                    self._json({"subtitles": self.service.list_remote_subtitles(query=query, imdb_id=imdb_id, languages=languages)})
                else:
                    self._json({"subtitles": self.service.list_remote_subtitles()})
            elif route == "/diagnostics/logs":
                audit_log = ""
                for candidate in AUDIT_LOG_CANDIDATES:
                    if os.path.exists(candidate):
                        try:
                            with open(candidate, "r", encoding="utf-8", errors="replace") as f:
                                f.seek(0, os.SEEK_END)
                                size = f.tell()
                                f.seek(max(0, size - 65536))
                                audit_log = f.read()
                                if audit_log:
                                    break
                        except Exception:
                            pass
                
                last_error = ""
                if self.service.supervisor:
                    last_error = self.service.supervisor.status.last_error or ""

                recent_logs = self.service.log_buffer.recent()
                formatted_lines = []
                for entry in recent_logs:
                    if isinstance(entry, dict):
                        lvl = str(entry.get("level", "info")).upper()
                        msg = entry.get("msg", "")
                        formatted_lines.append(f"[{lvl}] {msg}")
                    else:
                        formatted_lines.append(str(entry))
                formatted_logs = "\n".join(formatted_lines)

                combined = f"=== RECENT DAEMON LOGS ===\n{formatted_logs}"
                if audit_log:
                    combined += f"\n\n=== AUDIT LOG ===\n{audit_log}"

                self._json({
                    "logs": combined,
                    "log_buffer": recent_logs,
                    "last_error": last_error,
                    "audit_log": audit_log,
                })
            elif route == "/preflight":
                path = one("path")
                if not path:
                    self._json({"error": "path is required"}, 400)
                else:
                    self._json(self.service.preflight(path))
            elif route == "/logs":
                self._json({"lines": self.service.log_buffer.recent(
                    since=int(one("since", 0)))})
            elif route == "/events":
                self._sse()
            else:
                self._json({"error": "not found"}, 404)
        except Exception as exc:  # noqa: BLE001
            tb = traceback.format_exc()
            try:
                self.service.log(f"[api] Error during GET {route}: {exc}\n{tb}", "error")
            except Exception:
                pass
            self._json({"error": str(exc)}, 500)

    def do_POST(self):  # noqa: N802
        route = urllib.parse.urlsplit(self.path).path.rstrip("/") or "/"
        body = self._body()
        svc = self.service

        try:
            if route == "/connect":
                host = body.get("host")
                if not host:
                    return self._json({"error": "host is required"}, 400)
                self._json(svc.connect(host, int(body.get("port") or 8009),
                                       body.get("friendly_name", "")))
            elif route == "/disconnect":
                self._json(svc.disconnect())
            elif route == "/queue":
                paths = body.get("paths")
                if not paths or not isinstance(paths, list):
                    return self._json({"error": "paths must be a non-empty list of strings"}, 400)
                self._json(svc.queue(paths))
            
            elif route == "/amazon/inject":
                import os, json
                auth_file = os.path.expanduser("~/.config/castcast/amazon_auth.json")
                os.makedirs(os.path.dirname(auth_file), exist_ok=True)
                with open(auth_file, "w") as f:
                    json.dump(body, f)
                return self._json({"success": True, "message": "Injected Amazon tokens"})
            elif route == "/amazon/queue/add":
                url_raw = body.get("url")
                title = body.get("title", "")
                if not url_raw:
                    return self._json({"error": "url is required"}, 400)

                extracted_url, extracted_title = _extract_amazon_share_info(url_raw)
                final_url = extracted_url if extracted_url else url_raw
                final_title = title if title else extracted_title

                if not final_title:
                    final_title = "Fetching title..."

                # Check for duplicates
                with self.service._lock:
                    exists = False
                    for item in self.service.amazon_queue:
                        if item.get("url") == final_url:
                            exists = True
                            break

                    if not exists:
                        self.service.amazon_queue.append({"url": final_url, "title": final_title})
                        self.service.save_amazon_queue()

                    # If it's a bare URL with no extracted title, resolve asynchronously
                    if final_title == "Fetching title...":
                        self.service.resolve_amazon_title_async(final_url)
                return self._json({"success": True})
            elif route == "/amazon/queue/reorder":
                items = body.get("items")
                if not isinstance(items, list):
                    return self._json({"error": "items must be a list"}, 400)
                with self.service._lock:
                    self.service.amazon_queue = items
                    self.service.save_amazon_queue()
                return self._json({"success": True})
            elif route == "/amazon/queue/remove":
                index = body.get("index")
                with self.service._lock:
                    if not isinstance(index, int) or index < 0 or index >= len(self.service.amazon_queue):
                        return self._json({"error": "invalid index"}, 400)
                    self.service.amazon_queue.pop(index)
                    self.service.save_amazon_queue()
                return self._json({"success": True})
            elif route == "/cast":
                path = body.get("path")
                title = body.get("title")
                if not path:
                    return self._json({"error": "path is required"}, 400)
                self._json(svc.cast(path,
                                    allow_unsafe=bool(body.get("allow_unsafe")),
                                    auto_prepare=body.get("auto_prepare", True),
                                    audio_index=body.get("audio_index"),
                                    subtitle_index=body.get("subtitle_index"),
                                    license_url=body.get("license_url"),
                                    offline_drm_token=body.get("offline_drm_token"),
                                    title=title))
            elif route == "/subtitles/opensubtitles":
                path = body.get("path")
                if not path:
                    return self._json({"error": "path is required"}, 400)
                self._json(svc.request_subtitles(path, body.get("language") or ""))
            elif route == "/subtitles/select":
                self._json(svc.select_subtitle_track(body.get("track_id")))
            elif route == "/subtitles/remote/fetch":
                url = body.get("url")
                if not url:
                    return self._json({"error": "url is required"}, 400)
                self._json(svc.fetch_and_activate_remote_subtitle(
                    body.get("language") or "",
                    body.get("type") or "manual",
                    url,
                ))
            elif route == "/prepare":
                path = body.get("path")
                if not path:
                    return self._json({"error": "path is required"}, 400)
                self._json(svc.prepare(path, force=bool(body.get("force"))))
            elif route == "/remaster":
                path = body.get("path")
                if not path:
                    return self._json({"error": "path is required"}, 400)
                self._json(svc.remaster(path, force=bool(body.get("force"))))
            elif route == "/prepare/cancel":
                self._json(svc.cancel_prepare())
            elif route == "/trash":
                path = body.get("path")
                if not path:
                    return self._json({"error": "path is required"}, 400)
                self._json(svc.trash(path))
            elif route == "/delete":
                path = body.get("path")
                if not path:
                    return self._json({"error": "path is required"}, 400)
                self._json(svc.delete(path))
            elif route == "/play":
                self._json(svc.play())
            elif route == "/pause":
                self._json(svc.pause())
            elif route == "/stop":
                self._json(svc.stop_media())
            elif route == "/seek":
                self._json(svc.seek(float(body.get("position") or 0.0)))
            elif route == "/volume":
                self._json(svc.set_volume(float(body.get("level") or 0.0)))
            elif route == "/mute":
                self._json(svc.set_muted(bool(body.get("muted"))))
            elif route == "/shutdown":
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"status": "ok"}')

                # Graceful cleanup of all processes and threads
                try:
                    if hasattr(svc, "_remuxer") and svc._remuxer:
                        svc._remuxer.cancel()
                    svc.stop()
                except Exception as e:
                    print(f"Error during shutdown cleanup: {e}")

                import os
                os._exit(0)
            elif route == "/discovery/intercept":
                self._json(svc.handle_intercept(body))
            else:
                self._json({"error": "not found"}, 404)
        except RuntimeError as exc:
            try:
                self.service.log(f"[api] Conflict during POST {route}: {exc}", "warn")
            except Exception:
                pass
            self._json({"error": str(exc)}, 409)
        except Exception as exc:  # noqa: BLE001
            tb = traceback.format_exc()
            try:
                self.service.log(f"[api] Error during POST {route}: {exc}\n{tb}", "error")
            except Exception:
                pass
            self._json({"error": str(exc)}, 500)

    # -- server-sent events -------------------------------------------------

    def _sse(self):
        outbox: "queue.Queue[tuple]" = queue.Queue(maxsize=256)

        def on_log(entry):
            _offer(outbox, ("log", entry))

        def on_event(kind, payload):
            _offer(outbox, (kind, payload))

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self._cors()
        self.end_headers()

        self.service.log_buffer.subscribe(on_log)
        self.service.subscribe(on_event)
        try:
            # Prime the client with current state and recent history.
            self._write_event("status", self.service.status())
            for entry in self.service.log_buffer.recent():
                self._write_event("log", entry)
            if hasattr(self.service, "amazon_queue"):
                with self.service._lock:
                    queue_items = list(self.service.amazon_queue)
                self._write_event("amazon_queue", {"items": queue_items})

            while True:
                try:
                    kind, payload = outbox.get(timeout=5.0)
                    self._write_event(kind, payload)
                except queue.Empty:
                    # Keepalive comment: proves the socket is still good.
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.service.log_buffer.unsubscribe(on_log)
            self.service.unsubscribe(on_event)

    def _write_event(self, kind: str, payload) -> None:
        data = json.dumps(payload, default=str)
        self.wfile.write(f"event: {kind}\ndata: {data}\n\n".encode("utf-8"))
        self.wfile.flush()


def _offer(q: "queue.Queue", item) -> None:
    try:
        q.put_nowait(item)
    except queue.Full:
        try:
            q.get_nowait()      # drop the oldest rather than block the producer
            q.put_nowait(item)
        except queue.Empty:
            pass


_ROUTES = {
    "GET /status": "daemon + connection state",
    "GET /health": "readiness checklist: tools, storage, LAN -- each with a remedy",
    "GET /devices": "discover Chromecasts",
    "GET /library?deep=1": "list media, optionally with pre-flight verdicts",
    "GET /trash": "list trashed media",
    "GET /subtitles/available": "available subtitle tracks and current active track",
    "GET /subtitles/remote": "list remote subtitle tracks (YouTube yt-dlp or SubDL/OpenSubtitles)",
    "GET /preflight?path=": "probe + castability verdict + ffmpeg plan",
    "GET /logs?since=N": "recent log lines",
    "GET /events": "SSE stream of logs, state changes, media status",
    "POST /connect": "{host, port?}",
    "POST /disconnect": "",
    "POST /cast": "{path, allow_unsafe?, auto_prepare?}",
    "POST /queue": "{paths} queue a list of castable media",
    "POST /subtitles/select": "{track_id} switch subtitle track via EDIT_TRACKS_INFO (null to disable)",
    "POST /subtitles/remote/fetch": "{url, language?, type?} fetch remote subtitle and activate via EDIT_TRACKS_INFO",
    "POST /subtitles/opensubtitles": "{path, language?} download and sideload subtitles",
    "POST /prepare": "{path, force?}  run the remux",
    "POST /prepare/cancel": "",
    "POST /trash": "{path} move a file to the trash folder",
    "POST /delete": "{path} permanently delete a file",
    "POST /play|/pause|/stop": "",
    "POST /seek": "{position}",
    "POST /volume": "{level 0..1}",
    "POST /mute": "{muted}",
    "POST /shutdown": "kill the daemon",
}


def _extract_amazon_share_info(raw_text):
    """
    Extracts the actual URL and a formatted title from Amazon share text.
    Handles formats like: "Watch Hazbin Hotel - Season 1, Episode 1 - Overture on Prime Video! https://..."
    Also handles Android intent:// URIs.
    """
    from .metadata import parse_intent_url
    extracted_url = parse_intent_url(raw_text) if isinstance(raw_text, str) and raw_text.startswith("intent://") else raw_text
    extracted_title = ""

    url_match = re.search(r'((?:https?|intent)://[^\s]+)', raw_text)
    if url_match:
        extracted_url = parse_intent_url(url_match.group(1))
        text_before = raw_text[:url_match.start()].strip()

        if text_before:
            text_before = text_before.replace("Watch ", "", 1)
            text_before = text_before.replace(" on Prime Video", "")
            text_before = text_before.replace(" on Amazon Prime", "")
            text_before = text_before.strip("! \n\r\t-")
            extracted_title = text_before

            if "Season" in extracted_title and "Episode" in extracted_title:
                match = re.match(r'(.*?)(?:\s*-\s*)?Season\s+(\d+),\s*Episode\s+(\d+)(?:\s*-\s*(.*))?', extracted_title)
                if match:
                    show = match.group(1).strip()
                    season = match.group(2).strip()
                    episode = match.group(3).strip()
                    ep_name = match.group(4)
                    extracted_title = f"{show} S{season.zfill(2)}E{episode.zfill(2)}"
                    if ep_name:
                        extracted_title += f" - {ep_name.strip()}"
            elif "Season" in extracted_title:
                match = re.match(r'(.*?)(?:\s*-\s*)?Season\s+(\d+)', extracted_title)
                if match:
                    show = match.group(1).strip()
                    season = match.group(2).strip()
                    extracted_title = f"{show} S{season.zfill(2)}"

    return extracted_url, extracted_title


class ApiServer:
    def __init__(self, service: CastService, host: str = "127.0.0.1", port: int = API_PORT):
        self.service = service
        self._host = host
        self._port = port
        self._httpd = None
        self._thread = None

    def start(self) -> None:
        httpd = ThreadingHTTPServer((self._host, self._port), _Handler)
        httpd.daemon_threads = True
        httpd.service = self.service  # type: ignore[attr-defined]
        self._httpd = httpd
        self._thread = threading.Thread(target=httpd.serve_forever,
                                        kwargs={"poll_interval": 0.5},
                                        name="castcast-api", daemon=True)
        self._thread.start()

    @property
    def port(self) -> int:
        return self._httpd.server_address[1] if self._httpd else self._port

    def stop(self) -> None:
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None

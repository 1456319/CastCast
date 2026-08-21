"""Local JSON control API + SSE event stream.

Binds to 127.0.0.1 by default so nothing off-device can drive your TV.  The UI
(a PWA, a Tasker task, a shell script, whatever) talks to this.
"""

from __future__ import annotations

import json
import queue
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .service import CastService

API_PORT = 8765


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
            elif route == "/diagnostics/logs":
                import os
                audit_log = ""
                if os.path.exists("/var/log/audit/audit.log"):
                    try:
                        with open("/var/log/audit/audit.log", "r") as f:
                            audit_log = f.read()
                    except Exception:
                        pass
                elif os.path.exists("/tmp/castcast.log"):
                    try:
                        with open("/tmp/castcast.log", "r") as f:
                            audit_log = f.read()
                    except Exception:
                        pass
                
                last_error = ""
                if self.service.supervisor:
                    last_error = self.service.supervisor.status.last_error

                self._json({
                    "log_buffer": self.service.log_buffer.recent(),
                    "last_error": last_error,
                    "audit_log": audit_log
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
                url = body.get("url")
                title = body.get("title", "")
                if not url:
                    return self._json({"error": "url is required"}, 400)
                self.service.amazon_queue.append({"url": url, "title": title})
                self.service.save_amazon_queue()
                return self._json({"success": True})
            elif route == "/amazon/queue/reorder":
                items = body.get("items")
                if not isinstance(items, list):
                    return self._json({"error": "items must be a list"}, 400)
                self.service.amazon_queue = items
                self.service.save_amazon_queue()
                return self._json({"success": True})
            elif route == "/amazon/queue/remove":
                index = body.get("index")
                if not isinstance(index, int) or index < 0 or index >= len(self.service.amazon_queue):
                    return self._json({"error": "invalid index"}, 400)
                self.service.amazon_queue.pop(index)
                self.service.save_amazon_queue()
                return self._json({"success": True})
            elif route == "/cast":
                path = body.get("path")
                if not path:
                    return self._json({"error": "path is required"}, 400)
                self._json(svc.cast(path,
                                    allow_unsafe=bool(body.get("allow_unsafe")),
                                    auto_prepare=body.get("auto_prepare", True),
                                    audio_index=body.get("audio_index"),
                                    subtitle_index=body.get("subtitle_index"),
                                    license_url=body.get("license_url"),
                                    offline_drm_token=body.get("offline_drm_token")))
            elif route == "/subtitles/opensubtitles":
                path = body.get("path")
                if not path:
                    return self._json({"error": "path is required"}, 400)
                self._json(svc.request_subtitles(path, body.get("language") or ""))
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
                import os
                os._exit(0)
            elif route == "/discovery/intercept":
                self._json(svc.handle_intercept(body))
            else:
                self._json({"error": "not found"}, 404)
        except RuntimeError as exc:
            self._json({"error": str(exc)}, 409)
        except Exception as exc:  # noqa: BLE001
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
    "GET /preflight?path=": "probe + castability verdict + ffmpeg plan",
    "GET /logs?since=N": "recent log lines",
    "GET /events": "SSE stream of logs, state changes, media status",
    "POST /connect": "{host, port?}",
    "POST /disconnect": "",
    "POST /cast": "{path, allow_unsafe?, auto_prepare?}",
    "POST /queue": "{paths} queue a list of castable media",
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

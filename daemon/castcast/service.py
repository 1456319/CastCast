"""The daemon service object: owns the supervisor, media server, library and
the pre-flight pipeline.
"""

from __future__ import annotations

import collections
import os
import threading
import time
from typing import Callable, Dict, List, Optional

from . import capability, health, remux
from .discovery import CastDevice, DeviceCache, resolve
from .mediaserver import MediaServer, guess_mime
from .opensubtitles import download_best, language3
from .probe import MediaInfo, ProbeError, have_ffmpeg, have_ffprobe, probe
from .supervisor import State, Supervisor

VIDEO_EXTENSIONS = {".mp4", ".m4v", ".mkv", ".webm", ".ts", ".m2ts", ".mov",
                    ".avi", ".flv", ".mpg", ".mpeg", ".m3u8", ".mpd", ".wmv"}


class LogBuffer:
    """Ring buffer of log lines, with fan-out to live listeners (SSE)."""

    def __init__(self, capacity: int = 500):
        self._lines = collections.deque(maxlen=capacity)
        self._lock = threading.Lock()
        self._listeners: List[Callable[[dict], None]] = []
        self._seq = 0

    def add(self, message: str, level: str = "info") -> None:
        with self._lock:
            self._seq += 1
            entry = {"seq": self._seq, "ts": time.time(), "level": level,
                     "message": message}
            self._lines.append(entry)
            listeners = list(self._listeners)
        for listener in listeners:
            try:
                listener(entry)
            except Exception:  # noqa: BLE001
                pass

    def recent(self, since: int = 0) -> List[dict]:
        with self._lock:
            return [line for line in self._lines if line["seq"] > since]

    def subscribe(self, listener) -> None:
        with self._lock:
            self._listeners.append(listener)

    def unsubscribe(self, listener) -> None:
        with self._lock:
            if listener in self._listeners:
                self._listeners.remove(listener)


class CastService:
    def __init__(self, config: dict):
        self.config = config
        self.log_buffer = LogBuffer()

        media_roots = config.get("media_roots") or ["/storage/emulated/0/Download/Chromecast"]
        self.media_roots = [os.path.expanduser(r) for r in media_roots]
        self.work_dir = os.path.expanduser(
            config.get("work_dir") or os.path.join(self.media_roots[0], ".castcast"))

        self.cache = DeviceCache(os.path.expanduser(
            config.get("device_cache") or "~/.config/castcast/devices.json"))

        self.media_server = MediaServer(
            roots=self.media_roots + [self.work_dir],
            port=int(config.get("media_port") or 0),
            logger=lambda m: self.log(m, "debug"),
        )

        self.supervisor: Optional[Supervisor] = None
        self.device: Optional[CastDevice] = None

        self._probe_cache: Dict[str, tuple] = {}   # path -> (mtime, MediaInfo)
        self._remuxer = remux.Remuxer(on_update=self._on_remux_update)
        self._remux_thread: Optional[threading.Thread] = None
        self.default_language = language3(config.get("default_language") or "eng")
        self.opensubtitles_api_key = config.get("opensubtitles_api_key") or os.environ.get("OPENSUBTITLES_API_KEY", "")
        self.opensubtitles_token = config.get("opensubtitles_token") or os.environ.get("OPENSUBTITLES_TOKEN", "")
        self._lock = threading.RLock()
        self._events: List[Callable[[str, dict], None]] = []
        self._watchdog: Optional[threading.Thread] = None
        self._stop = threading.Event()

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        os.makedirs(self.work_dir, exist_ok=True)
        self.media_server.start()
        self.log(f"media roots: {', '.join(self.media_roots)}")
        if not have_ffprobe():
            self.log("ffprobe not found -- pre-flight checks disabled. "
                     "On Termux: pkg install ffmpeg", "warn")
        if not have_ffmpeg():
            self.log("ffmpeg not found -- remuxing disabled.", "warn")

        self._watchdog = threading.Thread(target=self._watch, name="castcast-watchdog",
                                          daemon=True)
        self._watchdog.start()

        auto = self.config.get("auto_connect_host") or self.config.get("static_host")
        if auto:
            self.connect(auto, int(self.config.get("static_port") or 8009))

    def stop(self) -> None:
        self._stop.set()
        if self.supervisor:
            self.supervisor.stop()
        self.media_server.stop()

    def log(self, message: str, level: str = "info") -> None:
        self.log_buffer.add(message, level)

    def subscribe(self, listener) -> None:
        self._events.append(listener)

    def unsubscribe(self, listener) -> None:
        if listener in self._events:
            self._events.remove(listener)

    def _emit(self, kind: str, payload: dict) -> None:
        for listener in list(self._events):
            try:
                listener(kind, payload)
            except Exception:  # noqa: BLE001
                pass

    def _watch(self) -> None:
        """Notice when the phone roams to a different network.

        Our LOAD URL embeds our own LAN IP.  If that IP changes mid-cast the
        receiver's HTTP pull breaks, and no amount of CASTv2 reconnecting will
        fix it -- we have to re-issue the LOAD with the new URL.
        """
        while not self._stop.wait(5.0):
            try:
                if self.media_server.refresh_lan_ip() and self.supervisor:
                    session = self.supervisor._session  # noqa: SLF001
                    if session and session.source_path:
                        self.log("LAN address changed mid-cast; re-issuing LOAD "
                                 "with the new media URL", "warn")
                        self.supervisor.load(
                            self.media_server.url_for(session.source_path),
                            content_type=session.content_type,
                            title=session.title,
                            duration=session.duration,
                            source_path=session.source_path,
                        )
            except Exception as exc:  # noqa: BLE001
                self.log(f"watchdog: {exc}", "warn")

    # -- devices -----------------------------------------------------------

    def discover(self, timeout: float = 4.0) -> List[dict]:
        self.log("browsing _googlecast._tcp.local ...")
        devices = resolve(
            static_host=self.config.get("static_host"),
            static_port=int(self.config.get("static_port") or 8009),
            cache=self.cache, timeout=timeout)
        self.log(f"discovery finished: {len(devices)} device(s)")
        return [d.to_dict() for d in devices]

    def connect(self, host: str, port: int = 8009, friendly_name: str = "") -> dict:
        with self._lock:
            if self.supervisor:
                self.supervisor.stop()
            self.device = CastDevice(host=host, port=port,
                                     friendly_name=friendly_name or host,
                                     source="manual")
            self.supervisor = Supervisor(
                host, port,
                on_event=self._emit,
                logger=lambda m: self.log(m),
                device_auth=bool(self.config.get("device_auth")),
            )
            self.supervisor.start()
        self.log(f"connecting to {host}:{port}")
        return self.status()

    def disconnect(self) -> dict:
        with self._lock:
            if self.supervisor:
                self.supervisor.stop()
                self.supervisor = None
            self.device = None
        self.log("disconnected")
        return self.status()

    def status(self) -> dict:
        out = {
            "connected": bool(self.supervisor),
            "device": self.device.to_dict() if self.device else None,
            "media_server": {
                "base_url": self.media_server.base_url,
                "lan_ip": self.media_server.lan_ip,
                "port": self.media_server.port,
                "roots": self.media_roots,
            },
            "tools": {"ffmpeg": have_ffmpeg(), "ffprobe": have_ffprobe()},
            "remux": self._remuxer.job.to_dict() if self._remuxer.job else None,
        }
        out["cast"] = self.supervisor.snapshot() if self.supervisor else {
            "state": State.DISCONNECTED.value}
        return out

    def health(self) -> dict:
        """Readiness: can this daemon actually cast, and if not, what fixes it?

        Separate from ``status()`` because the phone needs to distinguish
        "daemon not running" from "daemon running but storage permission
        missing" from "daemon running but no LAN route" -- three failures whose
        remedies have nothing in common.
        """
        from . import __version__

        report = health.evaluate(
            media_roots=self.media_roots,
            lan_ip=self.media_server.lan_ip,
            media_port=self.media_server.port,
            media_server_running=self.media_server.running,
            version=__version__,
        )
        out = report.to_dict()
        out["connected"] = bool(self.supervisor)
        return out

    # -- library and pre-flight -------------------------------------------

    def library(self, deep: bool = False) -> List[dict]:
        """List castable-looking files, with cached pre-flight verdicts."""
        entries = []
        for root in self.media_roots:
            if not os.path.isdir(root):
                self.log(f"media root does not exist: {root}", "warn")
                continue
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                for filename in sorted(filenames):
                    if os.path.splitext(filename)[1].lower() not in VIDEO_EXTENSIONS:
                        continue
                    full = os.path.join(dirpath, filename)
                    item = {
                        "path": full,
                        "name": filename,
                        "rel": os.path.relpath(full, root),
                        "size_bytes": _size(full),
                    }
                    if deep:
                        item.update(self.preflight(full))
                    entries.append(item)
        return entries

    def probe_cached(self, path: str) -> MediaInfo:
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = 0.0
        cached = self._probe_cache.get(path)
        if cached and cached[0] == mtime:
            return cached[1]
        info = probe(path)
        self._probe_cache[path] = (mtime, info)
        return info

    def preflight(self, path: str) -> dict:
        """Probe + verdict + remux plan, without touching the device."""
        if not have_ffprobe():
            # Degrade rather than fail closed: an already-valid MP4 should
            # still cast on a box without ffmpeg installed. We just cannot
            # promise anything about it.
            return {"error": None, "media": None, "verdict": None, "plan": None,
                    "tools_missing": True,
                    "warning": "ffprobe is not installed, so this file was not "
                               "pre-flighted. If it fails to play, an unsupported "
                               "codec or container is the likely cause. "
                               "On Termux: pkg install ffmpeg"}

        try:
            info = self.probe_cached(path)
        except ProbeError as exc:
            return {"error": str(exc), "media": None, "verdict": None, "plan": None}

        verdict = capability.evaluate(
            info,
            prefer_fmp4=bool(self.config.get("prefer_fmp4")),
            assume_avr_passthrough=bool(self.config.get("avr_passthrough")),
        )
        plan = remux.build_plan(info, verdict, self.work_dir)

        # If we already produced a converted copy, point at it.
        ready = None
        if plan and os.path.exists(plan.output_path):
            ready = plan.output_path

        return {
            "media": info.to_dict(),
            "verdict": verdict.to_dict(),
            "plan": plan.to_dict() if plan else None,
            "prepared_path": ready,
        }

    def prepare(self, path: str, force: bool = False) -> dict:
        """Run the remux for ``path`` in the background."""
        report = self.preflight(path)
        if report.get("error"):
            return report
        plan_dict = report.get("plan")
        if not plan_dict:
            self.log(f"{os.path.basename(path)} needs no processing")
            return report
        if report.get("prepared_path") and not force:
            self.log(f"reusing existing converted file: {report['prepared_path']}")
            return report
        if self._remuxer.busy:
            return {**report, "error": "another conversion is already running"}

        info = self.probe_cached(path)
        verdict = capability.evaluate(info)
        plan = remux.build_plan(info, verdict, self.work_dir)
        if plan is None:
            return report

        self.log(f"converting: {plan.description}")
        self.log(f"$ {plan.shell_command}")

        def worker():
            self._remuxer.run(plan, duration_s=info.duration_s)

        self._remux_thread = threading.Thread(target=worker, name="castcast-remux",
                                              daemon=True)
        self._remux_thread.start()
        return {**report, "started": True}

    def cancel_prepare(self) -> dict:
        self._remuxer.cancel()
        self.log("conversion cancelled", "warn")
        return self.status()

    def _on_remux_update(self, job: remux.RemuxJob) -> None:
        if job.state in ("done", "failed", "cancelled"):
            level = "info" if job.state == "done" else "warn"
            self.log(f"conversion {job.state}"
                     + (f": {job.error}" if job.error else ""), level)
        self._emit("remux", job.to_dict())

    # -- casting -----------------------------------------------------------

    def cast(self, path: str, *, allow_unsafe: bool = False,
             auto_prepare: bool = True, subtitle_path: str = "",
             subtitle_language: str = "") -> dict:
        """The whole pipeline: pre-flight, convert if needed, serve, LOAD."""
        if not self.supervisor:
            return {"error": "not connected to a device"}

        report = self.preflight(path)
        if report.get("error") and not allow_unsafe:
            return report
        if report.get("tools_missing"):
            self.log(report["warning"], "warn")

        verdict = report.get("verdict")
        target = path

        if verdict and verdict.get("needs_processing"):
            prepared = report.get("prepared_path")
            if prepared:
                target = prepared
                self.log(f"using previously converted file: {os.path.basename(prepared)}")
            elif allow_unsafe:
                fatal = [i["message"] for i in verdict["issues"] if i["severity"] == "fatal"]
                self.log("casting despite predicted failure (allow_unsafe): "
                         + "; ".join(fatal), "warn")
            elif auto_prepare:
                # Do not silently burn phone battery on a full re-encode.
                if verdict.get("video_action") == "transcode":
                    return {
                        **report,
                        "error": "this file needs a full video re-encode, which is slow "
                                 "and lossy. Call /prepare explicitly to accept that, or "
                                 "pass allow_unsafe to try casting anyway.",
                        "requires_confirmation": True,
                    }
                self.prepare(path)
                return {**report, "error": "conversion started; retry the cast when it "
                                           "finishes", "converting": True}
            else:
                return {**report, "error": "file needs conversion before casting",
                        "requires_confirmation": True}

        try:
            url = self.media_server.url_for(target)
        except ValueError as exc:
            return {**report, "error": str(exc)}

        info = report.get("media") or {}
        title = os.path.splitext(os.path.basename(path))[0]
        tracks, active_track_ids = self._tracks_for_load(subtitle_path, subtitle_language)
        self.supervisor.load(
            url,
            content_type=guess_mime(target),
            title=title,
            duration=float(info.get("duration_s") or 0.0),
            source_path=target,
            tracks=tracks,
            active_track_ids=active_track_ids,
        )

        pv = (info.get("video") or [{}])
        resolution = f"{pv[0].get('width')}x{pv[0].get('height')}" if pv and pv[0] else "?"
        self.log(f"casting {title} [{resolution}] -> {self.device.friendly_name if self.device else '?'}")
        return {**report, "casting": True, "url": url}


    def request_subtitles(self, path: str, language: str = "") -> dict:
        """Download the best OpenSubtitles match and re-LOAD current media with it."""
        if not self.supervisor:
            return {"error": "not connected to a device"}
        lang = language3(language or self.default_language)
        result = download_best(path, self.work_dir, self.opensubtitles_api_key,
                               language=lang, token=self.opensubtitles_token)
        result.url = self.media_server.url_for(result.path)
        self.log(f"downloaded {lang} subtitles from OpenSubtitles: {os.path.basename(result.path)}")

        snap = self.supervisor.snapshot()
        cast_result = self.cast(path, allow_unsafe=True, auto_prepare=False,
                                subtitle_path=result.path, subtitle_language=lang)
        if not cast_result.get("error") and snap.get("position"):
            self.supervisor.seek(float(snap.get("position") or 0.0))
        return {**cast_result, "subtitles": result.__dict__}

    def _tracks_for_load(self, subtitle_path: str = "", language: str = "") -> tuple[list, list]:
        if not subtitle_path:
            return [], []
        url = self.media_server.url_for(subtitle_path)
        lang = language3(language or self.default_language)
        return ([{
            "trackId": 1,
            "type": "TEXT",
            "trackContentId": url,
            "trackContentType": "text/vtt",
            "name": lang.upper(),
            "language": lang,
            "subtype": "SUBTITLES",
        }], [1])

    # -- transport passthrough --------------------------------------------

    def _require(self):
        if not self.supervisor:
            raise RuntimeError("not connected to a device")
        return self.supervisor

    def play(self):
        self._require().play()
        return self.status()

    def pause(self):
        self._require().pause()
        return self.status()

    def seek(self, position: float):
        self._require().seek(position)
        return self.status()

    def stop_media(self):
        self._require().stop_media()
        return self.status()

    def set_volume(self, level: float):
        self._require().set_volume(level)
        return self.status()

    def set_muted(self, muted: bool):
        self._require().set_muted(muted)
        return self.status()


def _size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0

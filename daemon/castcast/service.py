"""The daemon service object: owns the supervisor, media server, library and
the pre-flight pipeline.
"""

from __future__ import annotations

import collections
import hashlib
import os
import subprocess
import threading
import time
from typing import Callable, Dict, List, Optional

from . import capability, health, remux
from .channel import DEFAULT_TEXT_TRACK_STYLE
from .discovery import CastDevice, DeviceCache, resolve
from .mediaserver import MediaServer, guess_mime
from .opensubtitles import download_best, language3
from .probe import FFMPEG, MediaInfo, ProbeError, have_ffmpeg, have_ffprobe, probe
from .supervisor import State, Supervisor

DEFAULT_MEDIA_ROOT = "/storage/emulated/0/Download/Chromecast"

VIDEO_EXTENSIONS = {
    ".avi",
    ".flv",
    ".m3u8",
    ".m2ts",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp4",
    ".mpd",
    ".mpeg",
    ".mpg",
    ".ts",
    ".webm",
    ".wmv",
}


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

        media_roots = config.get("media_roots") or [DEFAULT_MEDIA_ROOT]
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
        self.opensubtitles_api_key = self._config_value(
            "opensubtitles_api_key",
            "OPENSUBTITLES_API_KEY",
        )
        self.opensubtitles_token = self._config_value(
            "opensubtitles_token",
            "OPENSUBTITLES_TOKEN",
        )
        self._queued_for_later = set()
        self._lock = threading.RLock()
        self._events: List[Callable[[str, dict], None]] = []
        self._watchdog: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def _config_value(self, key: str, env_name: str) -> str:
        return str(self.config.get(key) or os.environ.get(env_name, ""))

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
                            tracks=session.tracks,
                            active_track_ids=session.active_track_ids,
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
                on_finished=self.auto_advance,
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

        if job.state == "done" and job.plan.input_path in self._queued_for_later:
            self._queued_for_later.remove(job.plan.input_path)
            if self.supervisor and self.supervisor._state.value != "disconnected":
                self._insert_queued_item(job.plan.input_path)

    def _insert_queued_item(self, path: str) -> None:
        report = self.preflight(path)
        verdict = report.get("verdict")
        target = path

        if verdict and verdict.get("needs_processing"):
            prepared = report.get("prepared_path")
            if prepared:
                target = prepared
            else:
                self.log(f"queue_insert: skipping {os.path.basename(path)} because it still needs conversion", "warn")
                return

        info = report.get("media") or {}
        target, language_note = self._target_for_default_language(target, info)
        if language_note:
            self.log(language_note, "debug")

        subtitle_path = self._extract_default_subtitle(path, info)
        subtitle_language = self.default_language if subtitle_path else ""

        try:
            url = self.media_server.url_for(target)
        except ValueError as exc:
            self.log(f"queue_insert: skipping {os.path.basename(path)} due to url error: {exc}", "warn")
            return

        title = os.path.splitext(os.path.basename(path))[0]
        tracks, active_track_ids = self._tracks_for_load(subtitle_path, subtitle_language)

        item = {
            "autoplay": True,
            "preloadTime": 10.0,
            "media": {
                "contentId": url,
                "streamType": "BUFFERED",
                "contentType": self._get_content_type(target, info),
                "metadata": {
                    "metadataType": 1,
                    "title": title
                }
            }
        }

        duration = float(info.get("duration_s") or 0.0)
        if duration:
            item["media"]["duration"] = duration
        if tracks:
            item["media"]["tracks"] = tracks
            item["media"]["textTrackStyle"] = DEFAULT_TEXT_TRACK_STYLE
        if active_track_ids:
            item["activeTrackIds"] = active_track_ids

        if self.supervisor:
            self.supervisor.queue_insert(item)

    # -- casting -----------------------------------------------------------

    def auto_advance(self, source_path: str) -> None:
        entries = self.library(deep=False)
        for i, entry in enumerate(entries):
            if entry["path"] == source_path:
                if i + 1 < len(entries):
                    next_entry = entries[i + 1]
                    if os.path.dirname(next_entry["path"]) == os.path.dirname(source_path):
                        self.log(f"auto-advancing to {next_entry['name']}")
                        # Run cast in a background thread to avoid blocking the supervisor receiver thread
                        threading.Thread(target=self.cast, args=(next_entry["path"],), daemon=True).start()
                break

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

        info = report.get("media") or {}
        target, language_note = self._target_for_default_language(target, info)
        if language_note:
            self.log(language_note, "debug")
        if not subtitle_path:
            subtitle_path = self._extract_default_subtitle(path, info)
            subtitle_language = self.default_language if subtitle_path else subtitle_language
        try:
            url = self.media_server.url_for(target)
        except ValueError as exc:
            return {**report, "error": str(exc)}

        title = os.path.splitext(os.path.basename(path))[0]
        tracks, active_track_ids = self._tracks_for_load(subtitle_path, subtitle_language)

        content_type = self._get_content_type(target, info)

        self.supervisor.load(
            url,
            content_type=content_type,
            title=title,
            duration=float(info.get("duration_s") or 0.0),
            source_path=target,
            tracks=tracks,
            active_track_ids=active_track_ids,
        )

        pv = (info.get("video") or [{}])
        resolution = f"{pv[0].get('width')}x{pv[0].get('height')}" if pv and pv[0] else "?"
        device_name = self.device.friendly_name if self.device else "?"
        self.log(f"casting {title} [{resolution}] -> {device_name}")
        return {**report, "casting": True, "url": url}

    def queue(self, paths: list[str]) -> dict:
        """Queue multiple items for playback. Pre-flights each and only queues castable ones."""
        if not self.supervisor:
            return {"error": "not connected to a device"}

        items = []
        skipped = 0
        preparing = 0

        for path in paths:
            report = self.preflight(path)
            verdict = report.get("verdict")
            target = path

            if verdict and verdict.get("needs_processing"):
                prepared = report.get("prepared_path")
                if prepared:
                    target = prepared
                    self.log(f"queue: using previously converted file: {os.path.basename(prepared)}")
                else:
                    self.log(f"queue: preparing {os.path.basename(path)} for later queueing")
                    self._queued_for_later.add(path)
                    self.prepare(path)
                    preparing += 1
                    continue

            info = report.get("media") or {}
            target, language_note = self._target_for_default_language(target, info)
            if language_note:
                self.log(language_note, "debug")

            subtitle_path = self._extract_default_subtitle(path, info)
            subtitle_language = self.default_language if subtitle_path else ""

            try:
                url = self.media_server.url_for(target)
            except ValueError as exc:
                self.log(f"queue: skipping {os.path.basename(path)} due to url error: {exc}", "warn")
                skipped += 1
                continue

            title = os.path.splitext(os.path.basename(path))[0]
            tracks, active_track_ids = self._tracks_for_load(subtitle_path, subtitle_language)

            item = {
                "autoplay": True,
                "preloadTime": 10.0,
                "media": {
                    "contentId": url,
                    "streamType": "BUFFERED",
                    "contentType": self._get_content_type(target, info),
                    "metadata": {
                        "metadataType": 1,
                        "title": title
                    }
                }
            }

            duration = float(info.get("duration_s") or 0.0)
            if duration:
                item["media"]["duration"] = duration
            if tracks:
                item["media"]["tracks"] = tracks
                item["media"]["textTrackStyle"] = DEFAULT_TEXT_TRACK_STYLE
            if active_track_ids:
                item["activeTrackIds"] = active_track_ids

            items.append(item)

        if not items:
            return {"error": "no castable items found in the provided paths"}

        self.supervisor.queue_load(items)
        return {"queued": len(items), "skipped": skipped, "preparing": preparing}

    def _target_for_default_language(self, target: str, info: dict) -> tuple[str, str]:
        audio = info.get("audio") or []
        if len(audio) < 2:
            return target, ""
        preferred = self.default_language
        selected = self._first_stream_for_language(audio, preferred)
        if not selected:
            langs = ", ".join(a.get("language") or "und" for a in audio)
            return (
                target,
                f"no {preferred} audio track found; receiver will use source default ({langs})",
            )
        if audio.index(selected) == 0:
            return target, f"{preferred} audio is already the first/default track"
        if not have_ffmpeg():
            return (
                target,
                f"{preferred} audio is track {selected.get('index')}, "
                "but ffmpeg is unavailable for default-track remux",
            )
        out = self._language_output_path(target, preferred)
        if not os.path.exists(out) or os.path.getmtime(out) < os.path.getmtime(target):
            cmd = self._default_audio_remux_command(target, selected, out)
            self.log(
                f"remuxing to make {preferred} audio the default track: {' '.join(cmd)}",
                "debug",
            )
            proc = subprocess.run(cmd, capture_output=True, timeout=900)
            if proc.returncode != 0:
                detail = proc.stderr.decode("utf-8", "replace").strip().splitlines()
                reason = detail[-1] if detail else proc.returncode
                return target, f"default-language remux failed: {reason}"
        return out, f"using remuxed default-{preferred} audio file: {os.path.basename(out)}"

    def _first_stream_for_language(
        self,
        streams: list,
        language: str,
        *,
        forced: Optional[bool] = None,
    ) -> Optional[dict]:
        for stream in streams:
            if language3(stream.get("language") or "") != language:
                continue
            if forced is not None and bool(stream.get("forced")) != forced:
                continue
            return stream
        return None

    def _default_audio_remux_command(self, source: str, audio: dict, output: str) -> list:
        return [
            FFMPEG,
            "-hide_banner",
            "-y",
            "-i",
            source,
            "-map",
            "0:v:0",
            "-map",
            f"0:{audio.get('index')}",
            "-c",
            "copy",
            "-sn",
            "-dn",
            "-map_chapters",
            "-1",
            "-disposition:a:0",
            "default",
            "-movflags",
            "+faststart",
            output,
        ]

    def _subtitle_extract_command(self, source: str, subtitle: dict, output: str) -> list:
        return [
            FFMPEG,
            "-hide_banner",
            "-y",
            "-i",
            source,
            "-map",
            f"0:{subtitle.get('index')}",
            "-f",
            "webvtt",
            output,
        ]

    def _language_output_path(self, path: str, language: str) -> str:
        stem = os.path.splitext(os.path.basename(path))[0]
        digest = hashlib.sha1((path + language).encode()).hexdigest()[:10]
        return os.path.join(self.work_dir, f"{stem}.{language}.{digest}.cast.mp4")

    def _extract_default_subtitle(self, path: str, info: dict) -> str:
        subtitles = info.get("subtitles") or []
        if not subtitles or not have_ffmpeg():
            return ""
        preferred = self.default_language
        selected = self._first_stream_for_language(subtitles, preferred, forced=False)
        selected = selected or self._first_stream_for_language(
            subtitles,
            preferred,
        )
        if not selected:
            self.log(f"no embedded {preferred} subtitle track found", "debug")
            return ""
        stem = hashlib.sha1((path + preferred + "sub").encode()).hexdigest()[:12]
        out = os.path.join(self.work_dir, f"{stem}.{preferred}.vtt")
        if os.path.exists(out) and os.path.getmtime(out) >= os.path.getmtime(path):
            self.log(
                f"using cached embedded {preferred} subtitles: {os.path.basename(out)}",
                "debug",
            )
            return out
        cmd = self._subtitle_extract_command(path, selected, out)
        self.log(
            f"extracting embedded {preferred} subtitles for sideload: {' '.join(cmd)}",
            "debug",
        )
        proc = subprocess.run(cmd, capture_output=True, timeout=300)
        if proc.returncode != 0:
            detail = proc.stderr.decode("utf-8", "replace").strip().splitlines()
            reason = detail[-1] if detail else proc.returncode
            self.log(f"embedded subtitle extraction failed: {reason}", "warn")
            return ""
        return out

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



    def _get_content_type(self, target: str, info: dict) -> str:
        content_type = guess_mime(target)
        pv = (info.get("video") or [{}])
        if pv and pv[0]:
            v = pv[0]
            if v.get("hdr_format") == "Dolby Vision" and v.get("codec") == "hevc" and v.get("dv_profile") is not None and v.get("dv_level") is not None:
                # Only use specific codec string for supported profiles (5 and 8)
                # to prevent breaking playback (fallback to HDR10) for unsupported profiles like 7.
                if v.get("dv_profile") in (5, 8):
                    content_type = f'video/mp4; codecs="dvhe.{v.get("dv_profile"):02d}.{v.get("dv_level"):02d}"'
        return content_type

def _size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0

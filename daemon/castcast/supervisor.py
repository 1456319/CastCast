"""The connection supervisor -- a VLC-style CASTv2 state machine that fights
to keep the link up.

Design notes
------------
The upstream Chromecast-Controller concluded that persistent connections were a
losing battle ("Chromecast links eventually drop and must be re-established")
and worked around it with systemd socket activation and short-lived processes.
That is a sound answer for bursty volume commands on a Linux box.  It is the
wrong answer here: there is no systemd on Android, and a 4K local-file cast is
the opposite of bursty -- we want one link held open for two hours.

So we invert it and copy VLC's approach instead
(``modules/stream_out/chromecast/chromecast_ctrl.cpp``):

* an explicit state machine, not ad-hoc booleans;
* a heartbeat budget (``PING_WAIT_TIME`` / ``PING_WAIT_RETRIES``) so a dead
  link is detected in seconds rather than whenever TCP notices;
* a hard distinction between a namespace-level CLOSE (the *app* exited --
  relaunch it) and a socket death (reconnect from scratch);
* ``reinit()`` from the Dead state rather than trying to patch a broken socket.

On top of VLC's model we add **session restore**: on any reconnect we
re-LOAD the media we were playing and seek back to where we were.  That turns a
dropped link from "playback ends" into "a two-second stutter", which is the
single most valuable behaviour for the 4K-stability problem.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

from .channel import (CastChannel, ChannelClosed, DEFAULT_MEDIA_RECEIVER_APP_ID, DEFAULT_TEXT_TRACK_STYLE,
                      NS_CONNECTION, NS_HEARTBEAT, NS_MEDIA, NS_RECEIVER,
                      PLATFORM_RECEIVER)

#: VLC uses 6s / 1 retry.  We keep the same interval but allow two misses,
#: because phone Wi-Fi power-save can swallow a single beacon without the link
#: actually being dead, and a spurious reconnect is more disruptive than a
#: slightly slower detection.
PING_WAIT_TIME = 6.0
PING_WAIT_RETRIES = 2

#: How often to ask for a MEDIA_STATUS while playing (VLC uses 4s).
STATUS_POLL_INTERVAL = 4.0

#: Reconnect backoff, in seconds. Deliberately aggressive at the start: most
#: drops are transient Wi-Fi blips and an immediate retry just works.
RECONNECT_BACKOFF = [0.5, 1.0, 2.0, 3.0, 5.0, 8.0, 13.0, 20.0, 30.0]


class State(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    AUTHENTICATING = "authenticating"
    CONNECTED = "connected"
    LAUNCHING = "launching"
    READY = "ready"
    LOADING = "loading"
    BUFFERING = "buffering"
    PLAYING = "playing"
    PAUSED = "paused"
    LOAD_FAILED = "load_failed"
    DEAD = "dead"


@dataclass
class MediaSession:
    """Everything needed to rebuild playback after a drop."""
    url: str = ""
    content_type: str = "video/mp4"
    title: str = ""
    subtitle: str = ""
    poster_url: str = ""
    backdrop_url: str = ""
    duration: float = 0.0
    source_path: str = ""
    position: float = 0.0
    autoplay: bool = True
    tracks: Optional[list] = None
    active_track_ids: Optional[list] = None
    text_tracks: int = 0
    has_text_tracks: bool = False
    queue_items: Optional[list] = None
    queue_index: int = 0
    # Widevine license server URL for DRM-protected streams. Passed to the
    # Chromecast receiver via customData.asset.licenseServers.
    license_url: str = ""


@dataclass
class Status:
    state: str = State.DISCONNECTED.value
    host: str = ""
    app_id: str = ""
    media_session_id: Optional[int] = None
    position: float = 0.0
    duration: float = 0.0
    volume: float = 0.0
    muted: bool = False
    idle_reason: str = ""
    title: str = ""
    content_url: str = ""
    source_path: str = ""
    reconnects: int = 0
    connected_since: float = 0.0
    last_error: str = ""
    stream_stalls: int = 0
    active_track_ids: Optional[list] = None
    text_tracks: int = 0
    has_text_tracks: bool = False


class Supervisor:
    """Owns one connection to one device, and keeps it alive."""

    def __init__(self, host: str, port: int = 8009,
                 on_event: Optional[Callable[[str, dict], None]] = None,
                 logger: Optional[Callable[[str], None]] = None,
                 on_finished: Optional[Callable[[str], None]] = None,
                 device_auth: bool = False):
        self.host = host
        self.port = port
        self._on_event = on_event
        self._on_finished = on_finished
        self._log = logger or (lambda m: None)
        self._device_auth = device_auth

        self._state = State.DISCONNECTED
        self._channel: Optional[CastChannel] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.RLock()
        self._state_changed = threading.Condition(self._lock)

        self._request_id = 1
        self._pending_requests: dict[int, str] = {}
        self._app_transport_id = ""
        self._media_session_id: Optional[int] = None
        self._session: Optional[MediaSession] = None
        self._pending_restore = False

        self._ping_retries = PING_WAIT_RETRIES
        self._last_ping = 0.0
        self._last_status_poll = 0.0
        self._last_position_at = 0.0
        self._last_position_value = 0.0

        self.status = Status(host=host)

    # -- public API --------------------------------------------------------

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="castcast-supervisor",
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            self._state_changed.notify_all()
        channel = self._channel
        if channel:
            channel.close()
        thread = self._thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=3.0)

    def wait_for(self, states, timeout: float = 15.0) -> bool:
        targets = {s if isinstance(s, State) else State(s) for s in states}
        deadline = time.time() + timeout
        with self._lock:
            while self._state not in targets:
                remaining = deadline - time.time()
                if remaining <= 0:
                    return False
                self._state_changed.wait(remaining)
            return True

    def load(self, url: str, content_type: str = "video/mp4", title: str = "",
             subtitle: str = "", poster_url: str = "", backdrop_url: str = "",
             duration: float = 0.0, source_path: str = "", autoplay: bool = True,
             tracks: Optional[list] = None, active_track_ids: Optional[list] = None,
             license_url: str = "") -> None:
        """Queue a LOAD.  Safe to call before the link is even up."""
        with self._lock:
            self._media_session_id = None
            self.status.media_session_id = None
            self._session = MediaSession(url=url, content_type=content_type, title=title,
                                         subtitle=subtitle, poster_url=poster_url, backdrop_url=backdrop_url,
                                         duration=duration, source_path=source_path,
                                         position=0.0, autoplay=autoplay, tracks=tracks or [],
                                         active_track_ids=active_track_ids or [],
                                         license_url=license_url)
            self._pending_restore = True
            self.status.title = title
            self.status.content_url = url
            self.status.source_path = source_path
            self.status.duration = duration
            self.status.idle_reason = ""
            self.status.active_track_ids = active_track_ids or []
            self.status.text_tracks = len(tracks or [])
            self.status.has_text_tracks = bool(tracks)
        self._log(f"queued LOAD {title or url}")
        self._try_load()

    def queue_insert(self, item: dict) -> None:
        """Append an item to the current queue."""
        self._media_command({"type": "QUEUE_INSERT", "items": [item]})

    def queue_load(self, items: list) -> None:
        """Queue a QUEUE_LOAD with multiple items."""
        if not items:
            return

        with self._lock:
            self._media_session_id = None
            self.status.media_session_id = None

            # Extract first item properties to populate status and basic session
            first = items[0]
            media = first.get("media", {})
            url = media.get("contentId", "")
            title = media.get("metadata", {}).get("title", "")
            duration = float(media.get("duration") or 0.0)
            source_path = media.get("customData", {}).get("sourcePath", "")

            self._session = MediaSession(
                url=url,
                title=title,
                duration=duration,
                source_path=source_path,
                queue_items=items
            )
            self._pending_restore = True

            self.status.title = title
            self.status.content_url = url
            self.status.source_path = source_path
            self.status.duration = duration
            self.status.idle_reason = ""
            first_tracks = media.get("tracks") or []
            self.status.active_track_ids = first.get("activeTrackIds") or []
            self.status.text_tracks = len(first_tracks)
            self.status.has_text_tracks = bool(first_tracks)

        self._log(f"queued QUEUE_LOAD with {len(items)} items")
        self._try_load()

    def play(self) -> Optional[int]:
        return self._media_command({"type": "PLAY"})

    def pause(self) -> Optional[int]:
        return self._media_command({"type": "PAUSE"})

    def seek(self, position: float) -> Optional[int]:
        return self._media_command({"type": "SEEK", "currentTime": max(position, 0.0)})

    def queue_remove(self, item_ids: list[int]) -> Optional[int]:
        return self._media_command({"type": "QUEUE_REMOVE", "itemIds": item_ids})

    def stop_media(self) -> None:
        self._media_command({"type": "STOP"})
        with self._lock:
            self._session = None
            self._pending_restore = False

    def set_volume(self, level: float) -> None:
        level = min(max(level, 0.0), 1.0)
        self._send_receiver({"type": "SET_VOLUME", "volume": {"level": level}})

    def set_muted(self, muted: bool) -> None:
        self._send_receiver({"type": "SET_VOLUME", "volume": {"muted": bool(muted)}})

    def snapshot(self) -> dict:
        with self._lock:
            data = dict(self.status.__dict__)
            data["state"] = self._state.value
            data["position"] = self._extrapolated_position()
            return data

    # -- state helpers -----------------------------------------------------

    def _set_state(self, state: State, *, error: str = "") -> None:
        with self._lock:
            if self._state is state and not error:
                return
            previous = self._state
            self._state = state
            self.status.state = state.value
            if error:
                self.status.last_error = error
            self._state_changed.notify_all()
        if previous is not state:
            self._log(f"state {previous.value} -> {state.value}"
                      + (f" ({error})" if error else ""))
            self._emit("state", {"from": previous.value, "to": state.value, "error": error})
        if state in (State.CONNECTED, State.READY):
            self._try_load()

    def _emit(self, kind: str, payload: dict) -> None:
        if self._on_event:
            try:
                self._on_event(kind, payload)
            except Exception:  # noqa: BLE001
                pass

    def _next_request_id(self, kind: str = "") -> int:
        with self._lock:
            self._request_id += 1
            rid = self._request_id
            if kind:
                self._pending_requests[rid] = kind
            return rid

    def _pop_request_kind(self, request_id) -> str:
        if request_id is None:
            return ""
        with self._lock:
            return self._pending_requests.pop(int(request_id), "")

    def _extrapolated_position(self) -> float:
        """Interpolate between MEDIA_STATUS messages so the UI ticks smoothly."""
        if self._state is not State.PLAYING or not self._last_position_at:
            return self.status.position
        elapsed = time.time() - self._last_position_at
        pos = self._last_position_value + elapsed
        if self.status.duration:
            pos = min(pos, self.status.duration)
        return round(pos, 2)

    # -- outbound ----------------------------------------------------------

    def _send_receiver(self, payload: dict) -> Optional[int]:
        channel = self._channel
        if channel is None or not channel.connected:
            return None
        payload = dict(payload)
        rid = self._next_request_id(str(payload.get("type") or "RECEIVER"))
        payload["requestId"] = rid
        try:
            channel.send_json(NS_RECEIVER, PLATFORM_RECEIVER, payload)
            return rid
        except ChannelClosed as exc:
            self._set_state(State.DEAD, error=str(exc))
            return None

    def _media_command(self, payload: dict) -> Optional[int]:
        channel = self._channel
        with self._lock:
            transport = self._app_transport_id
            session_id = self._media_session_id
        if channel is None or not channel.connected or not transport or session_id is None:
            self._log(f"dropping {payload.get('type')}: no active media session")
            return None
        payload = dict(payload)
        command = str(payload.get("type") or "MEDIA")
        rid = self._next_request_id(command)
        payload["requestId"] = rid
        payload["mediaSessionId"] = session_id
        try:
            channel.send_json(NS_MEDIA, transport, payload)
            return rid
        except ChannelClosed as exc:
            self._set_state(State.DEAD, error=str(exc))
            return None

    def _media_command_without_session(self, payload: dict) -> Optional[int]:
        channel = self._channel
        with self._lock:
            transport = self._app_transport_id
        if channel is None or not channel.connected or not transport:
            return None
        payload = dict(payload)
        command = str(payload.get("type") or "MEDIA")
        rid = self._next_request_id(command)
        payload["requestId"] = rid
        try:
            channel.send_json(NS_MEDIA, transport, payload)
            return rid
        except ChannelClosed as exc:
            self._set_state(State.DEAD, error=str(exc))
            return None

    def _try_load(self) -> None:
        """VLC's ``tryLoad()``: launch the app if needed, then LOAD."""
        with self._lock:
            session = self._session
            state = self._state
            transport = self._app_transport_id
            pending = self._pending_restore
        if not session or not pending:
            return

        if state is State.CONNECTED and not transport:
            self._log(f"launching receiver app {DEFAULT_MEDIA_RECEIVER_APP_ID}")
            if self._send_receiver({"type": "LAUNCH",
                                    "appId": DEFAULT_MEDIA_RECEIVER_APP_ID}) is not None:
                # Deliberately not via _set_state: we do not want to re-enter
                # _try_load from here.
                with self._lock:
                    self._state = State.LAUNCHING
                    self.status.state = State.LAUNCHING.value
            return

        if state not in (State.READY, State.CONNECTED) or not transport:
            return

        channel = self._channel
        if channel is None:
            return

        if session.queue_items:
            payload = {
                "type": "QUEUE_LOAD",
                "requestId": self._next_request_id("QUEUE_LOAD"),
                "sessionId": None,
                "items": session.queue_items,
                "repeatMode": "REPEAT_OFF",
                "startIndex": session.queue_index,
            }
        else:
            payload = {
                "type": "LOAD",
                "requestId": self._next_request_id("LOAD"),
                "sessionId": None,
                "autoplay": session.autoplay,
                "currentTime": session.position,
                "media": {
                    "contentId": session.url,
                    "streamType": "BUFFERED",
                    "contentType": session.content_type,
                    "metadata": {
                        "metadataType": 1,
                        "title": session.title or "castcast",
                        "subtitle": session.subtitle or "",
                        "images": [{"url": session.poster_url}] if session.poster_url else []
                    },
                },
            }
            custom_data = {}
            if session.source_path:
                custom_data["sourcePath"] = session.source_path
            if session.license_url:
                # ------------------------------------------------------------------
                # DRM / Widevine Configuration for Shaka Player Demo Receiver
                # ------------------------------------------------------------------
                # This customData.asset.licenseServers structure is the Shaka Player
                # Demo Receiver's API for specifying a Widevine license server URL.
                #
                # - "__type__": "map" is required by Shaka Player's custom data parser
                #   to interpret the object as a JavaScript Map.
                # - "com.widevine.alpha" is the Widevine DRM scheme identifier. This
                #   tells Shaka Player which CDM (Content Decryption Module) to use
                #   when requesting a license.
                # - session.license_url points to either our local HTTPS tunnel proxy
                #   (for Amazon DRM) or a direct license server URL. The Chromecast
                #   will POST the Widevine challenge to this URL and expect raw
                #   license bytes back. Deviations in byte-level payload, headers, or
                #   Content-Type will break license acquisition and playback.
                #
                # WARNING: The Shaka Player Demo receiver app ID is "07AEE832". If
                # this app ID is changed to a different receiver (e.g. the Default
                # Media Receiver "CC1AD845"), the customData.asset.licenseServers
                # format will NOT work because the Default Media Receiver doesn't
                # support custom Widevine license servers.
                # ------------------------------------------------------------------
                custom_data["asset"] = {
                    "licenseServers": {
                        "__type__": "map",
                        "com.widevine.alpha": session.license_url
                    }
                }

            # extraConfig is merged into the Shaka Player config by
            # ShakaDemoAssetInfo.getConfiguration().  This is the ONLY
            # way to pass player configuration through the Demo Receiver.
            # A top-level customData.config key is silently ignored.
            if "asset" not in custom_data:
                custom_data["asset"] = {}
            custom_data["asset"]["extraConfig"] = {
                "preferredTextLanguage": "en-US",
                "preferredTextRole": "caption",
                "preferredAudioLanguage": "en-US",
                "streaming": {
                    "alwaysStreamText": True
                }
            }
            
            if custom_data:
                payload["media"]["customData"] = custom_data

            # Apply a high-contrast subtitle styling via the standard Cast
            # textTrackStyle (this is read by the Cast SDK, not Shaka directly)
            payload["media"]["textTrackStyle"] = {
                "backgroundColor": "#00000000",
                "foregroundColor": "#FFFFFFFF",
                "edgeType": "DROP_SHADOW",
                "edgeColor": "#000000FF",
                "windowType": "NONE",
                "fontScale": 1.1,
                "fontFamily": "sans-serif"
            }
            if session.duration:
                payload["media"]["duration"] = session.duration
            if session.tracks:
                payload["media"]["tracks"] = session.tracks
                payload["media"]["textTrackStyle"] = DEFAULT_TEXT_TRACK_STYLE
            if session.active_track_ids:
                payload["activeTrackIds"] = session.active_track_ids

        try:
            channel.send_json(NS_MEDIA, self._app_transport_id, payload)
        except ChannelClosed as exc:
            self._set_state(State.DEAD, error=str(exc))
            return

        with self._lock:
            self._pending_restore = False
        resume = f" @ {session.position:.1f}s" if session.position else ""
        detail = f" tracks={len(session.tracks or [])} active={session.active_track_ids or []}" if session.tracks else ""
        self._log(f"LOAD sent{resume}{detail}: {session.url}")
        self._set_state(State.LOADING)

    # -- inbound -----------------------------------------------------------

    def _handle(self, message) -> bool:
        """Process one message.  Return False to tear the connection down."""
        namespace = message.namespace

        if namespace == NS_HEARTBEAT:
            payload = _json(message.payload_utf8)
            kind = payload.get("type")
            if kind == "PING":
                try:
                    self._channel.pong()  # type: ignore[union-attr]
                except ChannelClosed:
                    return False
            elif kind == "PONG":
                self._ping_retries = PING_WAIT_RETRIES
            return True

        if namespace == NS_CONNECTION:
            payload = _json(message.payload_utf8)
            if payload.get("type") == "CLOSE":
                # An application closed -- NOT the socket.  VLC is explicit
                # about this distinction; treating it as a disconnect causes a
                # pointless full reconnect.
                self._log("receiver app closed the virtual connection")
                with self._lock:
                    self._app_transport_id = ""
                    self._media_session_id = None
                    if self._session:
                        self._pending_restore = True
                self._set_state(State.CONNECTED)
            return True

        if namespace.endswith("deviceauth"):
            self._log("device auth response received")
            self._advance_to_connected()
            return True

        if namespace == NS_RECEIVER:
            return self._handle_receiver(_json(message.payload_utf8))

        if namespace == NS_MEDIA:
            return self._handle_media(_json(message.payload_utf8))

        elif namespace == "urn:x-cast:com.google.cast.shaka":
            self._log(f"SHAKA MESSAGE: {message.payload_utf8}")

        return True

    def _advance_to_connected(self) -> None:
        channel = self._channel
        if channel is None:
            return
        try:
            channel.virtual_connect(PLATFORM_RECEIVER)
            self._set_state(State.CONNECTED)
            self._send_receiver({"type": "GET_STATUS"})
        except ChannelClosed as exc:
            self._set_state(State.DEAD, error=str(exc))

    def _handle_receiver(self, payload: dict) -> bool:
        kind = payload.get("type")

        if kind == "LAUNCH_ERROR":
            reason = payload.get("reason", "unknown")
            self._log(f"LAUNCH_ERROR: {reason}")
            with self._lock:
                self._app_transport_id = ""
                self._media_session_id = None
            self._set_state(State.DEAD, error=f"launch error: {reason}")
            return False

        if kind != "RECEIVER_STATUS":
            return True

        status = payload.get("status") or {}
        volume = status.get("volume") or {}
        with self._lock:
            if "level" in volume:
                self.status.volume = float(volume.get("level") or 0.0)
            if "muted" in volume:
                self.status.muted = bool(volume.get("muted"))

        transport = ""
        app_id = ""
        for app in status.get("applications") or []:
            if app.get("appId") == DEFAULT_MEDIA_RECEIVER_APP_ID or \
                    NS_MEDIA in [ns.get("name") for ns in (app.get("namespaces") or [])]:
                transport = app.get("transportId") or app.get("sessionId") or ""
                app_id = app.get("appId") or ""
                break

        with self._lock:
            self.status.app_id = app_id
            known = self._app_transport_id

        if transport and transport != known:
            self._log(f"media app up, transportId={transport}")
            channel = self._channel
            if channel is None:
                return False
            try:
                # Second virtual connection: this one to the app itself.
                channel.virtual_connect(transport)
            except ChannelClosed as exc:
                self._set_state(State.DEAD, error=str(exc))
                return False
            with self._lock:
                self._app_transport_id = transport
            self._set_state(State.READY)
        elif not transport and known:
            with self._lock:
                self._app_transport_id = ""
                self._media_session_id = None
                if self._session:
                    self._pending_restore = True
            self._set_state(State.CONNECTED)

        return True

    def _handle_media(self, payload: dict) -> bool:
        kind = payload.get("type")

        if kind in ("LOAD_FAILED", "INVALID_REQUEST"):
            reason = payload.get("reason") or payload.get("detail") or kind
            request_kind = self._pop_request_kind(payload.get("requestId"))
            is_load_request = kind == "LOAD_FAILED" or request_kind in {"LOAD", "QUEUE_LOAD"}
            if is_load_request:
                # This is the silent-failure path the capability checker exists to
                # prevent.  Say something useful about it rather than just retrying.
                self._log(f"LOAD_FAILED: {reason} -- the receiver refused the media. "
                          "This is almost always an unsupported codec or container.")
                self._set_state(State.LOAD_FAILED, error=f"receiver rejected media: {reason}")
                self._emit("load_failed", {"reason": str(reason), "request": request_kind or kind})
            else:
                self._log(
                    f"media command failed: {request_kind or 'unknown'} rejected with {reason}; "
                    "refreshing receiver status instead of marking the load failed"
                )
                if str(reason).lower() == "invalid_media_session_id":
                    with self._lock:
                        self._media_session_id = None
                        self.status.media_session_id = None
                    self._media_command_without_session({"type": "GET_STATUS"})
                self._emit("command_failed", {"reason": str(reason), "request": request_kind})
            return True

        if kind == "LOAD_CANCELLED":
            self._log("LOAD_CANCELLED (superseded by a newer request)")
            return True

        if kind != "MEDIA_STATUS":
            return True

        self._pop_request_kind(payload.get("requestId"))
        entries = payload.get("status") or []
        if not entries:
            # An empty status array after a LOAD means the session ended.
            with self._lock:
                had_session = self._media_session_id is not None
                self._media_session_id = None
            if had_session:
                self._set_state(State.READY)
            return True

        entry = entries[0]
        session_id = entry.get("mediaSessionId")
        with self._lock:
            if session_id is not None:
                if self._media_session_id is not None and session_id != self._media_session_id:
                    self._log(f"[debug] media session changed from {self._media_session_id} to {session_id}")
                self._media_session_id = session_id
                self.status.media_session_id = session_id

        media = entry.get("media") or {}
        with self._lock:
            if self._session:
                current_item_id = entry.get("currentItemId")
                status_items = entry.get("items") or []
                idx = -1
                if current_item_id is not None and status_items:
                    self._session.queue_items = status_items
                    for i, item in enumerate(status_items):
                        if item.get("itemId") == current_item_id:
                            idx = i
                            break
                if idx == -1 and media.get("contentId") and self._session.queue_items:
                    content_id = media["contentId"]
                    for i, item in enumerate(self._session.queue_items):
                        if item.get("media", {}).get("contentId") == content_id:
                            idx = i
                            break
                if idx != -1:
                    self._session.queue_index = idx

            custom_data = media.get("customData") or {}
            source_path = custom_data.get("sourcePath")
            if source_path:
                self.status.source_path = source_path
                if self._session:
                    self._session.source_path = source_path

            tracks = media.get("tracks") or []
            self.status.text_tracks = len(tracks)
            self.status.has_text_tracks = bool(tracks)
            if "activeTrackIds" in entry:
                self.status.active_track_ids = entry.get("activeTrackIds") or []
            if media.get("duration"):
                self.status.duration = float(media["duration"])
                if self._session:
                    self._session.duration = self.status.duration
            if "currentTime" in entry:
                position = float(entry.get("currentTime") or 0.0)
                self.status.position = position
                self._last_position_value = position
                self._last_position_at = time.time()
                if self._session:
                    self._session.position = position
            volume = entry.get("volume") or {}
            if "level" in volume:
                self.status.volume = float(volume.get("level") or 0.0)
            if "muted" in volume:
                self.status.muted = bool(volume.get("muted"))

        player_state = entry.get("playerState") or ""
        idle_reason = entry.get("idleReason") or ""

        if player_state == "PLAYING":
            self._set_state(State.PLAYING)
        elif player_state == "PAUSED":
            self._set_state(State.PAUSED)
        elif player_state == "BUFFERING":
            self._set_state(State.BUFFERING)
        elif player_state == "LOADING":
            self._set_state(State.LOADING)
        elif player_state == "IDLE" or not player_state:
            with self._lock:
                self.status.idle_reason = idle_reason
            if idle_reason == "FINISHED":
                self._log("playback finished")
                with self._lock:
                    source_path = self._session.source_path if self._session else ""
                    self._session = None
                    self._media_session_id = None
                self._set_state(State.READY)
                self._emit("finished", {})
                if self._on_finished and source_path:
                    self._on_finished(source_path)
            elif idle_reason == "INTERRUPTED":
                self._log("playback interrupted -- another sender took the device")
                self._set_state(State.READY)
            elif idle_reason == "ERROR":
                self._log("receiver went IDLE with reason=ERROR: playback aborted. "
                          "Typically a mid-stream decode failure or an HTTP stall.")
                self._set_state(State.LOAD_FAILED, error="receiver reported a playback error")
            else:
                self._set_state(State.READY)

        self._emit("media", self.snapshot())
        return True

    # -- the loop ----------------------------------------------------------

    def _run(self) -> None:
        attempt = 0
        while not self._stop.is_set():
            try:
                self._connect_once()
                attempt = 0          # a clean session resets the backoff
            except Exception as exc:  # noqa: BLE001
                # A read failing *because we asked to stop* is not an error.
                if not self._stop.is_set():
                    self._log(f"connection error: {exc}")
                    with self._lock:
                        self.status.last_error = str(exc)

            if self._stop.is_set():
                break

            self._teardown()

            # Anything we were playing should come back when we reconnect.
            with self._lock:
                if self._session:
                    self._pending_restore = True
                    resume_at = self._session.position
                else:
                    resume_at = 0.0
                self.status.reconnects += 1

            delay = RECONNECT_BACKOFF[min(attempt, len(RECONNECT_BACKOFF) - 1)]
            attempt += 1
            self._set_state(State.DISCONNECTED)
            note = f", will resume at {resume_at:.1f}s" if resume_at else ""
            self._log(f"reconnecting in {delay:.1f}s (attempt {attempt}){note}")
            self._emit("reconnecting", {"delay": delay, "attempt": attempt})

            if self._stop.wait(delay):
                break

        self._teardown()
        self._set_state(State.DISCONNECTED)

    def _teardown(self) -> None:
        channel = self._channel
        if channel:
            with self._lock:
                transport = self._app_transport_id
            if transport:
                channel.virtual_close(transport)
            channel.virtual_close(PLATFORM_RECEIVER)
            channel.close()
        self._channel = None
        with self._lock:
            self._app_transport_id = ""
            self._media_session_id = None
            self.status.media_session_id = None

    def _connect_once(self) -> None:
        self._set_state(State.CONNECTING)
        channel = CastChannel(self.host, self.port)
        channel.connect()
        self._channel = channel
        self._ping_retries = PING_WAIT_RETRIES
        self._last_ping = time.time()
        self._last_status_poll = 0.0

        with self._lock:
            self.status.connected_since = time.time()
        self._log(f"TLS connection established to {self.host}:{self.port}")

        if self._device_auth:
            self._set_state(State.AUTHENTICATING)
            channel.send_device_auth()
        else:
            # deviceauth is optional for senders; skipping it is one fewer
            # round trip and one fewer thing to go wrong.
            self._advance_to_connected()

        while not self._stop.is_set():
            now = time.time()
            budget = PING_WAIT_TIME - (now - self._last_ping)

            try:
                message = channel.receive(timeout=max(budget, 0.1))
            except TimeoutError:
                self._on_read_timeout()
                continue
            except OSError as exc:
                if isinstance(exc, ChannelClosed):
                    raise
                # socket.timeout is an OSError subclass on py3.10+
                if exc.__class__.__name__ == "timeout":
                    self._on_read_timeout()
                    continue
                raise ChannelClosed(f"the connection to the Chromecast died: {exc}") from exc

            if not self._handle(message):
                raise ChannelClosed("unrecoverable protocol state")

            self._maybe_poll_status()

    def _on_read_timeout(self) -> None:
        self._last_ping = time.time()
        if self._ping_retries <= 0:
            raise ChannelClosed("no PING response from the Chromecast")
        self._ping_retries -= 1
        channel = self._channel
        if channel is None:
            raise ChannelClosed("channel vanished")
        channel.ping()
        # VLC pairs the ping with a status request: if the device is alive but
        # wedged, this often shakes a RECEIVER_STATUS loose.
        self._send_receiver({"type": "GET_STATUS"})

    def _maybe_poll_status(self) -> None:
        with self._lock:
            active = self._state in (State.PLAYING, State.BUFFERING)
            transport = self._app_transport_id
            session_id = self._media_session_id
        if not active or not transport or session_id is None:
            return
        now = time.time()
        if now - self._last_status_poll < STATUS_POLL_INTERVAL:
            return
        self._last_status_poll = now

        # Stall detection: we are nominally PLAYING but the clock has not
        # advanced between two polls.  Usually means our HTTP server stopped
        # feeding the device fast enough.
        with self._lock:
            if (self._state is State.PLAYING and self._last_position_at
                    and now - self._last_position_at > STATUS_POLL_INTERVAL * 2.5):
                self.status.stream_stalls += 1
                self._log("stream appears stalled: no position advance from the receiver")
                self._emit("stall", {"count": self.status.stream_stalls})

        self._media_command({"type": "GET_STATUS"})


def _json(text: str) -> dict:
    try:
        value = json.loads(text) if text else {}
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}

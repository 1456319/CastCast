# synchronization-map: section=utility-middleware; role=health-check; boundaries=api-contract; doc=docs/SYNCHRONIZATION_MAP.md
# EDITING OF THIS FILE MAY CAUSE CATASTROPHIC APP DESYCHRONIZATION. Reference the directory at at ~/docs/synchronization_map.md to determine what other files must be adjusted in order to ensure absolute synchronization is maintained. This is to ensure that the APK, termux daemon, and chromecast portions of the app are always in synchronous, deterministic states.
"""Readiness checks: is this daemon actually able to cast anything?

``/status`` answers "what is the daemon's state".  This answers the different
and more useful question the phone UI needs on first launch: *"what is stopping
me from casting right now, and what exactly do I type to fix it?"*

The distinction matters because the three common Termux setup failures --
``pkg install ffmpeg`` not run, ``termux-setup-storage`` not run, and no Wi-Fi
route -- all present to the user as "casting doesn't work", but have completely
different remedies.  Each check therefore carries its own ``remedy`` string, and
the UI shows the command verbatim rather than paraphrasing it.

Only checks that can be answered locally and cheaply live here; nothing in this
module touches the network or the Chromecast.
"""

from __future__ import annotations

import os
import platform
import subprocess
from dataclasses import dataclass, asdict, field
from typing import List, Optional

from .probe import FFMPEG, FFPROBE, have_ffmpeg, have_ffprobe

# The default media location, repeated here so remedy strings are copy-pasteable
# even when the daemon was started with no explicit --media-root.
DEFAULT_MEDIA_ROOT = "/storage/emulated/0/Download/CastCast/Chromecast"

SERVE_COMMAND = (
    "python -m castcast --media-root {root} serve"
)


@dataclass
class Check:
    """One readiness row.

    ``ok=None`` means *unknown* rather than *failing* -- the UI renders that as
    ``?``.  We would rather admit we cannot tell than show a red row we made up.
    """

    key: str
    label: str
    ok: Optional[bool]
    detail: str = ""
    remedy: str = ""
    blocking: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


def _tool_version(binary: str) -> str:
    """First line of ``<binary> -version``, trimmed to something displayable."""
    try:
        out = subprocess.run([binary, "-version"], capture_output=True,
                             timeout=5).stdout.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return ""
    first = out.strip().splitlines()[0] if out.strip() else ""
    # "ffmpeg version 6.1.1 Copyright (c) ..." -> "6.1.1"
    parts = first.split()
    if len(parts) >= 3 and parts[1] == "version":
        return parts[2]
    return first[:60]


def _check_tool(binary: str, key: str, label: str, present: bool) -> Check:
    if not present:
        return Check(
            key=key, label=label, ok=False,
            detail=f"{binary} is not on PATH",
            remedy="pkg install ffmpeg",
        )
    version = _tool_version(binary)
    return Check(key=key, label=label, ok=True,
                 detail=f"{binary} {version}".strip(),
                 remedy="")


def _check_root(root: str) -> Check:
    """Is this media root present and actually readable?

    On Android the interesting failure is not "missing directory" but
    "directory exists and listing it raises PermissionError", which is exactly
    what you get before ``termux-setup-storage`` has been run.
    """
    key = "media_root:" + root
    label = f"Media folder {root}"
    remedy = "termux-setup-storage"

    if not os.path.exists(root):
        return Check(key=key, label=label, ok=False,
                     detail="does not exist",
                     remedy=f"termux-setup-storage   # then: mkdir -p {root}")
    if not os.path.isdir(root):
        return Check(key=key, label=label, ok=False,
                     detail="exists but is not a directory", remedy="")
    try:
        names = os.listdir(root)
    except PermissionError:
        return Check(key=key, label=label, ok=False,
                     detail="permission denied -- storage access not granted",
                     remedy=remedy)
    except OSError as exc:
        return Check(key=key, label=label, ok=False,
                     detail=f"unreadable: {exc}", remedy=remedy)

    # Readable but empty is not an error; it is just an empty folder. Say so
    # plainly instead of failing a check the user cannot act on.
    return Check(key=key, label=label, ok=True,
                 detail=f"readable, {len(names)} entr{'y' if len(names) == 1 else 'ies'}",
                 remedy="")


def _check_lan(lan_ip: str, port: int) -> Check:
    """A loopback LAN IP means the Chromecast can never fetch our media.

    ``detect_lan_ip()`` falls back to 127.0.0.1 when it cannot find a route
    off-device.  Casting would then "succeed" at the CASTv2 layer and the
    receiver would sit on a spinner forever, because the LOAD URL it was handed
    resolves to itself.  Better to flag it here.
    """
    if not lan_ip or lan_ip.startswith("127.") or lan_ip == "::1":
        return Check(
            key="lan", label="LAN address", ok=False,
            detail=f"no route off-device (got {lan_ip or 'nothing'})",
            remedy="Connect the phone to the same Wi-Fi network as the Chromecast",
        )
    return Check(key="lan", label="LAN address", ok=True,
                 detail=f"{lan_ip}:{port}", remedy="")


def _check_media_server(running: bool, port: int) -> Check:
    if not running or not port:
        return Check(key="media_server", label="Media server", ok=False,
                     detail="not bound", remedy="Restart the daemon")
    return Check(key="media_server", label="Media server", ok=True,
                 detail=f"serving on port {port}", remedy="")


@dataclass
class HealthReport:
    ready: bool = False
    checks: List[Check] = field(default_factory=list)
    blocking: List[Check] = field(default_factory=list)
    version: str = ""
    python: str = ""
    serve_command: str = ""

    def to_dict(self) -> dict:
        return {
            "ready": self.ready,
            "version": self.version,
            "python": self.python,
            "serve_command": self.serve_command,
            "checks": [c.to_dict() for c in self.checks],
            "blocking": [c.to_dict() for c in self.blocking],
        }


def evaluate(*, media_roots: List[str], lan_ip: str, media_port: int,
             media_server_running: bool, version: str = "") -> HealthReport:
    """Build the full readiness report.

    ``ffmpeg``/``ffprobe`` are marked non-blocking: an already-compatible MP4
    casts fine without them, which is the documented degradation path in
    ``CastService.preflight()``.  Without them you simply lose pre-flight and
    conversion, so they are warnings rather than hard stops.
    """
    checks: List[Check] = [
        _check_media_server(media_server_running, media_port),
        _check_lan(lan_ip, media_port),
    ]

    ffprobe = _check_tool(FFPROBE, "ffprobe", "ffprobe (pre-flight checks)",
                          have_ffprobe())
    ffprobe.blocking = False
    if not ffprobe.ok:
        ffprobe.detail += " -- files cannot be pre-flighted; playback failures " \
                          "will not be predicted"
    checks.append(ffprobe)

    ffmpeg = _check_tool(FFMPEG, "ffmpeg", "ffmpeg (conversion)", have_ffmpeg())
    ffmpeg.blocking = False
    if not ffmpeg.ok:
        ffmpeg.detail += " -- incompatible files cannot be converted"
    checks.append(ffmpeg)

    for root in media_roots:
        checks.append(_check_root(root))

    blocking = [c for c in checks if c.blocking and c.ok is False]

    root_for_cmd = media_roots[0] if media_roots else DEFAULT_MEDIA_ROOT

    return HealthReport(
        ready=not blocking,
        checks=checks,
        blocking=blocking,
        version=version,
        python=platform.python_version(),
        serve_command=SERVE_COMMAND.format(root=root_for_cmd),
    )

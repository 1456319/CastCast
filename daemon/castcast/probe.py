# synchronization-map: section=media-routing; role=ffprobe-utility; boundaries=core-service; doc=docs/SYNCHRONIZATION_MAP.md
"""ffprobe wrapper -> a normalised description of a media file.

This is the raw-fact layer.  It makes no judgements about castability; that is
``capability.py``'s job.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field, asdict
from fractions import Fraction
from typing import List, Optional

FFPROBE = os.environ.get("CASTCAST_FFPROBE", "ffprobe")
FFMPEG = os.environ.get("CASTCAST_FFMPEG", "ffmpeg")


def have_ffmpeg() -> bool:
    return shutil.which(FFMPEG) is not None


def have_ffprobe() -> bool:
    return shutil.which(FFPROBE) is not None


class ProbeError(Exception):
    pass


@dataclass
class VideoStream:
    index: int = 0
    codec: str = ""           # h264 | hevc | vp9 | vp8 | av1 ...
    profile: str = ""         # High | Main 10 | Profile 2 ...
    level: Optional[float] = None   # 5.1, 4.1 ...
    width: int = 0
    height: int = 0
    fps: float = 0.0
    bit_depth: int = 8
    pix_fmt: str = ""
    color_primaries: str = ""
    color_transfer: str = ""
    color_space: str = ""
    hdr_format: str = "SDR"   # SDR | HDR10 | HDR10+ | HLG | Dolby Vision
    dv_profile: Optional[int] = None
    dv_level: Optional[int] = None
    bitrate_kbps: Optional[int] = None

    @property
    def is_4k(self) -> bool:
        return self.width >= 3840 and self.height >= 2160


@dataclass
class AudioStream:
    index: int = 0
    codec: str = ""           # aac | ac3 | eac3 | dts | opus | flac ...
    profile: str = ""
    channels: int = 0
    channel_layout: str = ""
    sample_rate: int = 0
    bitrate_kbps: Optional[int] = None
    language: str = ""


@dataclass
class SubtitleStream:
    index: int = 0
    codec: str = ""
    language: str = ""
    title: str = ""
    forced: bool = False
    default: bool = False


@dataclass
class MediaInfo:
    path: str
    size_bytes: int = 0
    container: str = ""       # normalised: mp4 | matroska | mpegts | webm | hls ...
    format_long: str = ""
    duration_s: float = 0.0
    bitrate_kbps: Optional[int] = None
    video: List[VideoStream] = field(default_factory=list)
    audio: List[AudioStream] = field(default_factory=list)
    subtitle_codecs: List[str] = field(default_factory=list)
    subtitles: List[SubtitleStream] = field(default_factory=list)

    @property
    def primary_video(self) -> Optional[VideoStream]:
        return self.video[0] if self.video else None

    @property
    def primary_audio(self) -> Optional[AudioStream]:
        return self.audio[0] if self.audio else None

    def to_dict(self) -> dict:
        d = asdict(self)
        pv = self.primary_video
        d["is_4k"] = bool(pv and pv.is_4k)
        return d


# --------------------------------------------------------------------------

def _f(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _i(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_fps(stream: dict) -> float:
    for key in ("avg_frame_rate", "r_frame_rate"):
        raw = stream.get(key)
        if not raw or raw in ("0/0", "0"):
            continue
        try:
            value = float(Fraction(raw))
        except (ZeroDivisionError, ValueError):
            continue
        if value > 0:
            return round(value, 3)
    return 0.0


def _normalise_container(format_name: str) -> str:
    """ffprobe reports comma-joined alternatives, e.g. ``mov,mp4,m4a,3gp,3g2,mj2``."""
    names = [n.strip() for n in (format_name or "").split(",") if n.strip()]
    nameset = set(names)
    if "mpegts" in nameset:
        return "mpegts"
    if "webm" in nameset:
        return "webm"
    if "matroska" in nameset:
        return "matroska"
    if nameset & {"mp4", "mov", "m4a", "3gp"}:
        return "mp4"
    if "hls" in nameset or "applehttp" in nameset:
        return "hls"
    return names[0] if names else "unknown"


def _detect_hdr(stream: dict) -> str:
    transfer = (stream.get("color_transfer") or "").lower()
    primaries = (stream.get("color_primaries") or "").lower()

    # Dolby Vision shows up as a side-data block, and only ever rides on HEVC
    # (or AV1) -- never VP9.
    for side in stream.get("side_data_list") or []:
        stype = (side.get("side_data_type") or "").lower()
        if "dovi" in stype or "dolby vision" in stype:
            return "Dolby Vision"

    if transfer in ("smpte2084", "smpte-st-2084", "pq"):
        # HDR10+ carries dynamic metadata; ffprobe surfaces it as side data on
        # frames rather than the stream, so a stream-level probe can only ever
        # say "HDR10 or better".
        return "HDR10"
    if transfer in ("arib-std-b67", "hlg"):
        return "HLG"
    if primaries == "bt2020" or transfer.startswith("bt2020"):
        return "HDR (BT.2020)"
    return "SDR"


def _bit_depth(stream: dict) -> int:
    depth = _i(stream.get("bits_per_raw_sample"))
    if depth:
        return depth
    pix_fmt = (stream.get("pix_fmt") or "").lower()
    for marker, value in (("12le", 12), ("12be", 12), ("10le", 10), ("10be", 10)):
        if marker in pix_fmt:
            return value
    return 8


def probe(path: str, timeout: float = 30.0) -> MediaInfo:
    """Run ffprobe and normalise the result.  Accepts local paths and URLs."""
    if not have_ffprobe():
        raise ProbeError(
            f"{FFPROBE} not found on PATH. On Termux: pkg install ffmpeg")

    is_url = "://" in path
    if not is_url and not os.path.exists(path):
        raise ProbeError(f"no such file: {path}")

    cmd = [
        FFPROBE, "-v", "error",
        "-print_format", "json",
        "-show_format", "-show_streams",
        "-show_entries", "stream_side_data",
        path,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise ProbeError(f"ffprobe timed out after {timeout}s on {path}") from exc

    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip().splitlines()
        raise ProbeError(detail[-1] if detail else f"ffprobe exited {proc.returncode}")

    try:
        data = json.loads(proc.stdout.decode("utf-8", "replace"))
    except json.JSONDecodeError as exc:
        raise ProbeError(f"unparseable ffprobe output: {exc}") from exc

    fmt = data.get("format") or {}
    info = MediaInfo(
        path=path,
        size_bytes=_i(fmt.get("size"), 0) or 0,
        container=_normalise_container(fmt.get("format_name", "")),
        format_long=fmt.get("format_long_name", ""),
        duration_s=_f(fmt.get("duration"), 0.0) or 0.0,
        bitrate_kbps=(lambda b: int(b // 1000) if b else None)(_i(fmt.get("bit_rate"))),
    )

    for stream in data.get("streams") or []:
        kind = stream.get("codec_type")
        if kind == "video":
            # Cover art and thumbnails masquerade as video streams.
            if (stream.get("disposition") or {}).get("attached_pic"):
                continue
            br = _i(stream.get("bit_rate"))

            dv_prof = None
            dv_lvl = None
            for side in stream.get("side_data_list") or []:
                stype = (side.get("side_data_type") or "").lower()
                if "dovi" in stype or "dolby vision" in stype:
                    dv_prof = _i(side.get("dv_profile"))
                    dv_lvl = _i(side.get("dv_level"))
                    break

            info.video.append(VideoStream(
                index=_i(stream.get("index"), 0) or 0,
                codec=(stream.get("codec_name") or "").lower(),
                profile=stream.get("profile") or "",
                level=(lambda lv: lv / 10.0 if lv and lv > 10 else lv)(_f(stream.get("level"))),
                width=_i(stream.get("width"), 0) or 0,
                height=_i(stream.get("height"), 0) or 0,
                fps=_parse_fps(stream),
                bit_depth=_bit_depth(stream),
                pix_fmt=stream.get("pix_fmt") or "",
                color_primaries=stream.get("color_primaries") or "",
                color_transfer=stream.get("color_transfer") or "",
                color_space=stream.get("color_space") or "",
                hdr_format=_detect_hdr(stream),
                dv_profile=dv_prof,
                dv_level=dv_lvl,
                bitrate_kbps=int(br // 1000) if br else None,
            ))
        elif kind == "audio":
            br = _i(stream.get("bit_rate"))
            info.audio.append(AudioStream(
                index=_i(stream.get("index"), 0) or 0,
                codec=(stream.get("codec_name") or "").lower(),
                profile=stream.get("profile") or "",
                channels=_i(stream.get("channels"), 0) or 0,
                channel_layout=stream.get("channel_layout") or "",
                sample_rate=_i(stream.get("sample_rate"), 0) or 0,
                bitrate_kbps=int(br // 1000) if br else None,
                language=((stream.get("tags") or {}).get("language") or ""),
            ))
        elif kind == "subtitle":
            codec = (stream.get("codec_name") or "").lower()
            tags = stream.get("tags") or {}
            disposition = stream.get("disposition") or {}
            info.subtitle_codecs.append(codec)
            info.subtitles.append(SubtitleStream(
                index=_i(stream.get("index"), 0) or 0,
                codec=codec,
                language=tags.get("language") or "",
                title=tags.get("title") or "",
                forced=bool(disposition.get("forced")),
                default=bool(disposition.get("default")),
            ))

    return info

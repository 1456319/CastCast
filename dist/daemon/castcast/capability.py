# synchronization-map: section=config-state; role=capabilities-state; boundaries=core-service; doc=docs/SYNCHRONIZATION_MAP.md
"""Chromecast Ultra capability matrix and the pre-flight verdict engine.

Why this exists
---------------
The Default Media Receiver (``CC1AD845``) fails *silently*.  Hand it something
it cannot decode or demux and you get a brief loading spinner followed by an
empty player -- no error, no MEDIA_STATUS, nothing actionable.  That
indistinguishable-from-a-network-drop failure mode is what makes "why isn't
this 4K?" so hard to answer.

So we refuse to guess.  Before the daemon ever sends a LOAD, it probes the file
and checks it against the published device matrix.  If we predict a failure, we
say so, say *why*, and hand back a concrete ffmpeg command that fixes it.

Sources for the matrix (Chromecast Ultra, "4K-capable" tier):
  https://developers.google.com/cast/docs/media
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import List, Optional

from .probe import MediaInfo, VideoStream, AudioStream

# --------------------------------------------------------------------------
# The matrix
# --------------------------------------------------------------------------

#: Containers the default receiver will demux.
SUPPORTED_CONTAINERS = {"mp4", "webm", "mpegts", "hls", "dash", "mp3", "wav"}

#: Containers that need remuxing even though the codecs inside may be fine.
#: MKV is the big one: the receiver's Matroska support is unreliable enough
#: that every practical sender remuxes to MP4 instead of gambling.
NEEDS_REMUX_CONTAINERS = {"matroska", "avi", "flv", "mov_quirky", "unknown"}

#: video codec -> (max width, max height, max fps, note)
VIDEO_CODECS = {
    # Chromecast Ultra's published H.264 ceiling is 1080p60/level 4.2.
    # 4K playback must use HEVC or VP9; blessing 2160p H.264 causes silent
    # receiver failures or quality fallback.
    "h264": (1920, 1080, 60, "H.264 High Profile up to level 4.2 (1080p/60fps); use HEVC or VP9 for 4K"),
    "hevc": (3840, 2160, 60, "HEVC Main/Main10 up to level 5.1"),
    "vp9":  (3840, 2160, 60, "VP9 Profile 0 and 2 up to level 5.1"),
    "vp8":  (3840, 2160, 30, "VP8 up to 4K/30"),
}

#: Codecs the Ultra has no hardware decoder for at all.
UNSUPPORTED_VIDEO_CODECS = {
    "av1": "AV1 has no hardware decoder on the Ultra",
    "mpeg2video": "MPEG-2 is not supported",
    "mpeg4": "MPEG-4 Part 2 (DivX/Xvid) is not supported",
    "vc1": "VC-1 is not supported",
    "wmv3": "WMV is not supported",
    "prores": "ProRes is not supported",
}

#: Audio that plays natively through the receiver's own decoder.
NATIVE_AUDIO_CODECS = {"aac", "mp3", "opus", "vorbis", "flac", "pcm_s16le", "pcm_s24le"}

#: Audio that only works as bitstream passthrough to an AVR over HDMI.  If the
#: Ultra is plugged straight into a TV, these produce silence -- which users
#: reliably misdiagnose as "the cast failed".
PASSTHROUGH_AUDIO_CODECS = {
    "ac3": "Dolby Digital",
    "eac3": "Dolby Digital Plus",
}

UNSUPPORTED_AUDIO_CODECS = {
    "dts": "DTS is not supported by the receiver and will not pass through",
    "truehd": "Dolby TrueHD is not supported",
    "dtshd": "DTS-HD is not supported",
    "mlp": "MLP is not supported",
    "wmav2": "WMA is not supported",
}

#: Codecs that can only reach 4K.  H.264 physically cannot do 4K60 here.
CODECS_FOR_4K60 = {"hevc", "vp9"}

SEVERITY_ORDER = {"fatal": 0, "warning": 1, "info": 2}


@dataclass
class Issue:
    severity: str      # fatal | warning | info
    code: str
    message: str
    remedy: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Verdict:
    castable: bool                  # will a direct LOAD work at all?
    needs_processing: bool          # can we fix it with a remux/transcode?
    will_be_4k: bool                # will the Ultra actually output 2160p?
    issues: List[Issue]
    summary: str
    target_container: Optional[str] = None
    video_action: str = "copy"      # copy | transcode | none
    audio_action: str = "copy"      # copy | transcode | none

    def to_dict(self) -> dict:
        d = asdict(self)
        d["issues"] = [i.to_dict() for i in self.issues]
        return d


# --------------------------------------------------------------------------

#: Issues that a container change cannot fix -- the bitstream itself is out of
#: spec, so the only remedy is a real re-encode.
REQUIRES_REENCODE = {
    "video_codec_unsupported",
    "video_codec_unknown",
    "resolution_exceeds_device",
    "framerate_exceeds_codec_limit",
}


def _check_video(v: Optional[VideoStream], container: str, issues: List[Issue], is_ultra: bool) -> str:
    """Returns the required action for the video stream."""
    if v is None:
        issues.append(Issue("warning", "no_video",
                            "No video stream found; this will cast as audio-only."))
        return "none"

    if v.codec in UNSUPPORTED_VIDEO_CODECS:
        issues.append(Issue(
            "fatal", "video_codec_unsupported",
            f"{v.codec.upper()}: {UNSUPPORTED_VIDEO_CODECS[v.codec]}.",
            "Re-encode the video to HEVC (for 4K/HDR) or H.264. This is a full "
            "re-encode, not a remux, and will take real time and quality.",
        ))
        return "transcode"

    if not is_ultra and v.codec in ("hevc", "vp9"):
        issues.append(Issue(
            "fatal", "codec_unsupported_on_standard_chromecast",
            f"{v.codec.upper()} is not supported on non-Ultra Chromecasts.",
            "Re-encode to H.264 High Profile (1080p).",
        ))
        return "transcode"

    if v.codec not in VIDEO_CODECS:
        issues.append(Issue(
            "warning", "video_codec_unknown",
            f"Codec '{v.codec}' is not in the published matrix; behaviour is untested.",
            "Consider re-encoding to H.264.",
        ))
        return "transcode"

    max_w, max_h, max_fps, note = VIDEO_CODECS[v.codec]

    # The single most important rule, and the one that silently breaks 4K:
    # HEVC is explicitly not supported inside MPEG-TS.
    if v.codec == "hevc" and container in ("mpegts", "hls"):
        issues.append(Issue(
            "fatal", "hevc_in_transport_stream",
            "HEVC in an MPEG-TS container is explicitly unsupported by Google Cast. "
            "The receiver will show a loading spinner and then a blank player, "
            "with no error message.",
            "Remux to MP4 -- this is lossless and fast: the video bitstream is "
            "copied byte-for-byte, only the container changes.",
        ))

    if v.width > max_w or v.height > max_h:
        issues.append(Issue(
            "fatal", "resolution_exceeds_device",
            f"{v.width}x{v.height} exceeds the Ultra's {max_w}x{max_h} ceiling for {v.codec.upper()}.",
            "Downscale to 3840x2160.",
        ))

    if v.fps and v.fps > max_fps + 0.5:
        sev = "fatal" if v.is_4k else "warning"
        issues.append(Issue(
            sev, "framerate_exceeds_codec_limit",
            f"{v.fps:g}fps at {v.width}x{v.height} exceeds the {max_fps}fps limit for "
            f"{v.codec.upper()} ({note}).",
            "Re-encode to HEVC or VP9, which support 4K60, or drop the framerate."
            if v.codec == "h264" else "Reduce the framerate.",
        ))

    if v.is_4k and v.codec == "h264":
        issues.append(Issue(
            "fatal", "h264_4k_unsupported",
            "This is 4K H.264. Chromecast Ultra's published H.264 support stops at 1080p60.",
            "Re-encode 4K video to HEVC or VP9 before casting.",
        ))

    if v.level and v.level > 5.1:
        issues.append(Issue(
            "warning", "level_exceeds_5_1",
            f"Stream level {v.level:g} is above the device's level 5.1 limit; "
            "decoding may stutter or fail.",
            "Re-encode at level 5.1 or below.",
        ))

    if v.hdr_format == "Dolby Vision" and v.codec == "vp9":
        issues.append(Issue(
            "fatal", "dovi_on_vp9",
            "Dolby Vision cannot be carried in VP9. This file is mislabelled or malformed.",
            "Use HEVC for Dolby Vision content.",
        ))

    if v.bit_depth >= 10 and v.codec == "hevc" and "main 10" not in v.profile.lower():
        issues.append(Issue(
            "warning", "ten_bit_without_main10",
            f"10-bit HEVC but the profile reports '{v.profile}' rather than Main 10.",
            "Verify the source; the receiver keys off the profile.",
        ))

    if v.bit_depth >= 10 and v.codec == "vp9" and "2" not in v.profile:
        issues.append(Issue(
            "warning", "vp9_10bit_needs_profile2",
            f"10-bit VP9 requires Profile 2, but the profile reports '{v.profile}'.",
            "Re-encode as VP9 Profile 2.",
        ))

    # A remux copies the bitstream verbatim, so anything wrong with the
    # bitstream itself survives it.  Escalate to a re-encode rather than
    # emitting a command that produces a file which fails identically.
    if any(i.severity == "fatal" and i.code in REQUIRES_REENCODE for i in issues):
        return "transcode"

    return "copy"


def _check_audio(a: Optional[AudioStream], issues: List[Issue]) -> str:
    if a is None:
        issues.append(Issue("info", "no_audio", "No audio stream found."))
        return "none"

    if a.codec in UNSUPPORTED_AUDIO_CODECS:
        issues.append(Issue(
            "fatal", "audio_codec_unsupported",
            f"{a.codec.upper()}: {UNSUPPORTED_AUDIO_CODECS[a.codec]}. "
            "The receiver will refuse the whole file, video included.",
            "Re-encode audio to AAC while copying the video untouched -- this is "
            "cheap and leaves video quality completely intact.",
        ))
        return "transcode"

    if a.codec in PASSTHROUGH_AUDIO_CODECS:
        issues.append(Issue(
            "warning", "audio_requires_passthrough",
            f"{PASSTHROUGH_AUDIO_CODECS[a.codec]} ({a.codec.upper()}) only works as HDMI "
            "bitstream passthrough to a receiver that can decode it. Straight into a TV "
            "this usually plays as silence.",
            "If your Ultra is plugged directly into the TV, re-encode audio to AAC.",
        ))
        return "copy"

    if a.codec not in NATIVE_AUDIO_CODECS:
        issues.append(Issue(
            "warning", "audio_codec_unknown",
            f"Audio codec '{a.codec}' is not in the published matrix.",
            "Re-encode audio to AAC to be safe.",
        ))
        return "transcode"

    return "copy"


def evaluate(info: MediaInfo, *, prefer_fmp4: bool = False,
             assume_avr_passthrough: bool = False, is_ultra: bool = True) -> Verdict:
    """Predict whether ``info`` will cast, and what to do about it if not."""
    issues: List[Issue] = []
    container = info.container

    video_action = _check_video(info.primary_video, container, issues, is_ultra)
    audio_action = _check_audio(info.primary_audio, issues)

    if assume_avr_passthrough:
        issues = [i for i in issues if i.code != "audio_requires_passthrough"]

    # -- container ------------------------------------------------------
    target_container = None
    if container in NEEDS_REMUX_CONTAINERS:
        target_container = "mp4"
        issues.append(Issue(
            "fatal", "container_unsupported",
            f"The '{container}' container is not reliably supported by the default receiver.",
            "Remux to MP4. If the internal codecs are already compatible this is "
            "lossless and takes seconds.",
        ))
    elif any(i.code == "hevc_in_transport_stream" for i in issues):
        target_container = "fmp4" if prefer_fmp4 else "mp4"

    if info.subtitle_codecs and target_container:
        issues.append(Issue(
            "info", "subtitles_dropped",
            f"Embedded subtitle track(s) ({', '.join(sorted(set(info.subtitle_codecs)))}) "
            "will be dropped by the remux; the default receiver cannot render them anyway.",
            "Sideload them as a WebVTT track instead.",
        ))

    # -- roll up --------------------------------------------------------
    fatal = [i for i in issues if i.severity == "fatal"]
    castable_now = not fatal
    needs_processing = bool(fatal) or target_container is not None

    v = info.primary_video
    # Will it be 4K *after* we fix it?  A remux never changes resolution, so
    # this is a property of the source, gated on us not having to downscale.
    will_be_4k = bool(
        v and v.is_4k
        and not any(i.code in ("resolution_exceeds_device", "video_codec_unsupported")
                    for i in fatal)
    )

    if v and not v.is_4k:
        issues.append(Issue(
            "info", "source_not_4k",
            f"Source is {v.width}x{v.height}. No amount of casting configuration makes "
            "this 4K -- the Ultra will upscale, but the stream is not 2160p.",
            "This is a source-file limitation, not a connection problem.",
        ))

    if will_be_4k and v and v.codec in CODECS_FOR_4K60 and (v.fps or 0) > 30:
        issues.append(Issue("info", "true_4k60",
                            f"True 4K{round(v.fps)} via {v.codec.upper()} -- within device spec."))

    issues.sort(key=lambda i: SEVERITY_ORDER.get(i.severity, 9))

    if castable_now and not needs_processing:
        summary = "Ready to cast as-is."
    elif needs_processing and video_action != "transcode":
        summary = ("Needs a lossless remux before casting "
                   "(video bitstream copied, container rebuilt).")
    elif video_action == "transcode":
        summary = "Needs a full video re-encode -- slow, and it will cost quality."
    else:
        summary = "Needs processing before casting."

    return Verdict(
        castable=castable_now,
        needs_processing=needs_processing,
        will_be_4k=will_be_4k,
        issues=issues,
        summary=summary,
        target_container=target_container,
        video_action=video_action,
        audio_action=audio_action,
    )

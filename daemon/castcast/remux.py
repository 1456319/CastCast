"""Turn a ``Verdict`` into an ffmpeg command, and run it with progress.

The guiding principle: **never re-encode video if a remux will do.**  Changing
the container is lossless and roughly disk-speed; re-encoding 4K HEVC on a
phone is not something you want to do by accident.
"""

from __future__ import annotations

import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Callable, List, Optional

from .capability import Verdict
from .probe import FFMPEG, MediaInfo, have_ffmpeg, probe

COLOR_PRIMARIES = {
    "bt709": 1, "unspecified": 2, "bt470m": 4, "bt470bg": 5, "smpte170m": 6,
    "smpte240m": 7, "film": 8, "bt2020": 9, "smpte428": 10, "smpte428_1": 10,
    "smpte431": 11, "smpte432": 12, "jedec-p22": 22,
}

COLOR_TRANSFER = {
    "bt709": 1, "unspecified": 2, "gamma22": 4, "gamma28": 5, "smpte170m": 6,
    "smpte240m": 7, "linear": 8, "log": 9, "log-sqrt": 10, "iec61966-2-4": 11,
    "bt1361e": 12, "iec61966-2-1": 13, "bt2020-10": 14, "bt2020-12": 15,
    "smpte2084": 16, "smpte428": 17, "smpte428_1": 17, "arib-std-b67": 18,
}

COLOR_SPACE = {
    "rgb": 0, "bt709": 1, "unspecified": 2, "fcc": 4, "bt470bg": 5,
    "smpte170m": 6, "smpte240m": 7, "ycgco": 8, "bt2020nc": 9, "bt2020c": 10,
    "smpte2085": 11, "chroma-derived-nc": 12, "chroma-derived-c": 13, "ictcp": 14,
}


_PROGRESS_TIME = re.compile(rb"out_time_ms=(\d+)")


@dataclass
class RemuxPlan:
    input_path: str
    output_path: str
    args: List[str] = field(default_factory=list)
    lossless_video: bool = True
    lossless_audio: bool = True
    description: str = ""
    estimated: str = ""
    expected_hdr_format: str = "SDR"
    expected_color_primaries: str = ""
    expected_color_transfer: str = ""
    expected_color_space: str = ""
    video_codec: str = ""

    @property
    def command(self) -> List[str]:
        return [FFMPEG, "-hide_banner", "-y", "-i", self.input_path] + self.args + [self.output_path]

    @property
    def shell_command(self) -> str:
        import shlex
        return " ".join(shlex.quote(part) for part in self.command)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["shell_command"] = self.shell_command
        return d


def output_path_for(input_path: str, work_dir: str, container: str, video_codec: str = "") -> str:
    stem = os.path.splitext(os.path.basename(input_path))[0]
    ext = "webm" if container == "webm" else "mp4"
    codec_tag = f".{video_codec}" if video_codec else ""
    suffix = f".cast{codec_tag}.fmp4.mp4" if container == "fmp4" else f".cast{codec_tag}.{ext}"
    return os.path.join(work_dir, stem + suffix)

def build_plan(info: MediaInfo, verdict: Verdict, work_dir: str, is_ultra: bool = True) -> Optional[RemuxPlan]:
    """Return the plan needed to make ``info`` castable, or ``None`` if it already is."""
    if not verdict.needs_processing:
        return None

    container = verdict.target_container or "mp4"
    out = output_path_for(info.path, work_dir, container, "hevc" if is_ultra and verdict.video_action == "transcode" else "h264" if verdict.video_action == "transcode" else "")

    args: List[str] = ["-map", "0:v:0"]
    lossless_video = True
    lossless_audio = True

    # -- video ----------------------------------------------------------
    if verdict.video_action == "transcode":
        v = info.primary_video
        
        if is_ultra:
            # Preserve HDR by staying 10-bit when the source is; otherwise the
            # picture comes back washed out.
            ten_bit = bool(v and v.bit_depth >= 10)
            args += ["-c:v", "libx265", "-preset", "superfast", "-crf", "18",
                     "-pix_fmt", "yuv420p10le" if ten_bit else "yuv420p",
                     "-tag:v", "hvc1"]
        else:
            # Standard Chromecast maxes out at 1080p H.264
            args += ["-c:v", "libx264", "-preset", "superfast", "-crf", "18",
                     "-profile:v", "high", "-level", "4.1", "-pix_fmt", "yuv420p"]
            if v and v.width > 1920:
                args += ["-vf", "scale=-2:1080"]
        lossless_video = False
    else:
        args += ["-c:v", "copy"]
        # Apple/Cast-friendly HEVC signalling.  An HEVC track tagged 'hev1'
        # instead of 'hvc1' is a classic silent-failure cause in MP4.
        if info.primary_video and info.primary_video.codec == "hevc":
            args += ["-tag:v", "hvc1"]

    # -- audio ----------------------------------------------------------
    if info.primary_audio is None:
        args += ["-an"]
    else:
        args += ["-map", "0:a"]
        if verdict.audio_action == "transcode":
            channels = info.primary_audio.channels or 2
            # Keep 5.1 as 5.1; the receiver downmixes if the sink can't take it.
            args += ["-c:a", "aac", "-b:a", "640k" if channels > 2 else "192k"]
            if channels > 6:
                args += ["-ac", "6"]  # AAC-LC tops out sensibly at 5.1
            lossless_audio = False
        else:
            args += ["-c:a", "copy"]

    # Subtitles are dropped: the default receiver cannot render embedded tracks,
    # and leaving them in is a common cause of MP4 muxer errors.
    args += ["-sn", "-dn", "-map_chapters", "-1"]

    # -- container ------------------------------------------------------
    if container == "fmp4":
        args += ["-movflags", "+frag_keyframe+empty_moov+default_base_moof"]
        cdesc = "fragmented MP4"
    elif container == "webm":
        args += ["-f", "webm"]
        cdesc = "WebM"
    else:
        # +faststart relocates the moov atom to the front so the receiver can
        # start playing (and seeking) without fetching the tail of the file.
        args += ["-movflags", "+faststart"]
        cdesc = "MP4"

    if lossless_video and lossless_audio:
        desc = f"Lossless remux to {cdesc} -- streams copied byte-for-byte."
        est = "seconds (disk-speed)"
    elif lossless_video:
        desc = f"Remux to {cdesc}, re-encoding audio to AAC. Video quality untouched."
        est = "~1-3 minutes per hour of runtime"
    else:
        desc = f"Full video re-encode to HEVC in {cdesc}. Slow and lossy."
        est = "many minutes to hours; not recommended on-device"

    return RemuxPlan(
        input_path=info.path,
        output_path=out,
        args=args,
        lossless_video=lossless_video,
        lossless_audio=lossless_audio,
        description=desc,
        estimated=est,
        expected_hdr_format=info.primary_video.hdr_format if info.primary_video else "SDR",
        expected_color_primaries=info.primary_video.color_primaries if info.primary_video else "",
        expected_color_transfer=info.primary_video.color_transfer if info.primary_video else "",
        expected_color_space=info.primary_video.color_space if info.primary_video else "",
        video_codec=info.primary_video.codec if info.primary_video else "",
    )


def build_4k_remaster_plan(info: MediaInfo, work_dir: str) -> Optional[RemuxPlan]:
    """Generates a plan to upconvert a 1080p source to 4K HEVC via lanczos."""
    if not info.primary_video:
        return None
        
    width = info.primary_video.width
    height = info.primary_video.height
    
    # We only upconvert 1080p (or around there). If it's already 4K, skip it.
    if width >= 3800:
        return None

    out = output_path_for(info.path, work_dir, "mp4", "hevc")

    args = [
        "-map", f"0:{info.primary_video.index}",
        "-c:v", "libx265",
        "-preset", "slow",
        "-crf", "18",
        "-vf", "scale=3840:2160:flags=lanczos",
        "-pix_fmt", "yuv420p10le",
    ]

    # Map the first audio track
    if info.audio:
        args.extend(["-map", f"0:{info.audio[0].index}", "-c:a", "copy"])
    
    # Embed subtitles
    for sub in info.subtitles:
        args.extend(["-map", f"0:{sub['index']}", "-c:s", "mov_text"])

    return RemuxPlan(
        input_path=info.path,
        output_path=out,
        args=args,
        lossless_video=False,
        lossless_audio=True,
        description="High-fidelity Overnight 4K Remaster (Lanczos scaling, HEVC). Extremely slow.",
        estimated="Hours to Days depending on device power",
        expected_hdr_format="SDR",
        expected_color_primaries="",
        expected_color_transfer="",
        expected_color_space="",
        video_codec="hevc",
    )


@dataclass
class RemuxJob:
    plan: RemuxPlan
    state: str = "pending"      # pending | running | done | failed | cancelled
    progress: float = 0.0       # 0..1
    error: str = ""
    warnings: List[str] = field(default_factory=list)
    started_at: float = 0.0
    finished_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "state": self.state,
            "progress": round(self.progress, 4),
            "error": self.error,
            "warnings": self.warnings,
            "output_path": self.plan.output_path,
            "description": self.plan.description,
            "shell_command": self.plan.shell_command,
            "elapsed_s": round((self.finished_at or time.time()) - self.started_at, 1)
            if self.started_at else 0.0,
        }


class Remuxer:
    """Runs one remux at a time, reporting progress via a callback."""

    def __init__(self, on_update: Optional[Callable[[RemuxJob], None]] = None):
        self._on_update = on_update
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self.job: Optional[RemuxJob] = None

    @property
    def busy(self) -> bool:
        return self.job is not None and self.job.state == "running"

    def cancel(self) -> None:
        with self._lock:
            proc = self._proc
            if proc and proc.poll() is None:
                proc.terminate()
            if self.job and self.job.state == "running":
                self.job.state = "cancelled"

    def run(self, plan: RemuxPlan, duration_s: float = 0.0, original_info: Optional[MediaInfo] = None) -> RemuxJob:
        """Blocking.  Call from a worker thread."""
        if not have_ffmpeg():
            job = RemuxJob(plan=plan, state="failed",
                           error=f"{FFMPEG} not found on PATH. On Termux: pkg install ffmpeg")
            self.job = job
            self._emit(job)
            return job

        job = RemuxJob(plan=plan, state="running", started_at=time.time())
        self.job = job
        self._emit(job)

        os.makedirs(os.path.dirname(plan.output_path) or ".", exist_ok=True)

        attempt = 1
        while attempt <= 2:
            cmd = plan.command + ["-progress", "pipe:1", "-nostats"]
            try:
                with self._lock:
                    self._proc = subprocess.Popen(
                        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                proc = self._proc
                assert proc.stdout is not None

                for line in proc.stdout:
                    match = _PROGRESS_TIME.search(line)
                    if match and duration_s > 0:
                        done = int(match.group(1)) / 1_000_000.0
                        new = min(done / duration_s, 0.999)
                        if new - job.progress > 0.005:
                            job.progress = new
                            self._emit(job)

                proc.wait()
                stderr = (proc.stderr.read() if proc.stderr else b"").decode("utf-8", "replace")

                if job.state == "cancelled":
                    _unlink(plan.output_path)
                    break

                elif proc.returncode == 0:
                    # Verify HDR metadata on first attempt if it's a lossless copy
                    if attempt == 1 and plan.lossless_video and plan.expected_hdr_format != "SDR" and plan.video_codec in ("hevc", "h264", "vp9"):
                        try:
                            out_info = probe(plan.output_path)
                            out_pv = out_info.primary_video
                            if out_pv and out_pv.color_transfer != plan.expected_color_transfer:
                                # Metadata was lost, we need to retry with a bitstream filter
                                attempt = 2
                                _unlink(plan.output_path)

                                filter_name = f"{plan.video_codec}_metadata"
                                bsf_args = []
                                if plan.expected_color_primaries:
                                    val = COLOR_PRIMARIES.get(plan.expected_color_primaries, 2)
                                    bsf_args.append(f"colour_primaries={val}")
                                if plan.expected_color_transfer:
                                    val = COLOR_TRANSFER.get(plan.expected_color_transfer, 2)
                                    bsf_args.append(f"transfer_characteristics={val}")
                                if plan.expected_color_space:
                                    val = COLOR_SPACE.get(plan.expected_color_space, 2)
                                    bsf_args.append(f"matrix_coefficients={val}")

                                if bsf_args and plan.video_codec != "vp9":
                                    bsf = f"{filter_name}=" + ":".join(bsf_args)
                                    plan.args.extend(["-bsf:v", bsf])
                                    job.progress = 0.0
                                    job.error = "HDR metadata lost; retrying with bitstream filters"
                                    self._emit(job)
                                    continue
                        except Exception:
                            pass # If probe fails, just accept the output

                    job.state = "done"
                    job.progress = 1.0
                    break
                else:
                    job.state = "failed"
                    tail = [ln for ln in stderr.strip().splitlines() if ln.strip()]
                    job.error = tail[-1] if tail else f"ffmpeg exited {proc.returncode}"
                    _unlink(plan.output_path)
                    break
            except Exception as exc:  # noqa: BLE001 - surfaced to the UI
                job.state = "failed"
                job.error = str(exc)
                _unlink(plan.output_path)
                break

        job.finished_at = time.time()
        with self._lock:
            self._proc = None
        self._emit(job)

        return job

    def _emit(self, job: RemuxJob) -> None:
        if self._on_update:
            try:
                self._on_update(job)
            except Exception:  # noqa: BLE001 - a bad listener must not kill the job
                pass


def _unlink(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass

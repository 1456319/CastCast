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
from .probe import FFMPEG, MediaInfo, have_ffmpeg

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


def output_path_for(input_path: str, work_dir: str, container: str) -> str:
    stem = os.path.splitext(os.path.basename(input_path))[0]
    ext = "webm" if container == "webm" else "mp4"
    suffix = ".cast.fmp4.mp4" if container == "fmp4" else f".cast.{ext}"
    return os.path.join(work_dir, stem + suffix)


def build_plan(info: MediaInfo, verdict: Verdict, work_dir: str) -> Optional[RemuxPlan]:
    """Return the plan needed to make ``info`` castable, or ``None`` if it already is."""
    if not verdict.needs_processing:
        return None

    container = verdict.target_container or "mp4"
    out = output_path_for(info.path, work_dir, container)

    args: List[str] = ["-map", "0:v:0"]
    lossless_video = True
    lossless_audio = True

    # -- video ----------------------------------------------------------
    if verdict.video_action == "transcode":
        v = info.primary_video
        # Preserve HDR by staying 10-bit when the source is; otherwise the
        # picture comes back washed out.
        ten_bit = bool(v and v.bit_depth >= 10)
        args += ["-c:v", "libx265", "-preset", "medium", "-crf", "20",
                 "-pix_fmt", "yuv420p10le" if ten_bit else "yuv420p",
                 "-tag:v", "hvc1"]
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
        args += ["-map", "0:a:0"]
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
    )


@dataclass
class RemuxJob:
    plan: RemuxPlan
    state: str = "pending"      # pending | running | done | failed | cancelled
    progress: float = 0.0       # 0..1
    error: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "state": self.state,
            "progress": round(self.progress, 4),
            "error": self.error,
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

    def run(self, plan: RemuxPlan, duration_s: float = 0.0) -> RemuxJob:
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
            elif proc.returncode == 0:
                job.state = "done"
                job.progress = 1.0
            else:
                job.state = "failed"
                tail = [ln for ln in stderr.strip().splitlines() if ln.strip()]
                job.error = tail[-1] if tail else f"ffmpeg exited {proc.returncode}"
                _unlink(plan.output_path)
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI
            job.state = "failed"
            job.error = str(exc)
            _unlink(plan.output_path)
        finally:
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

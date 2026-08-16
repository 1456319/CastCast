# [KEY 0] Agent Jules: File verified structurally sound. No objective blocking errors found in automated pass.
import pytest
import os
from castcast.remux import build_plan, RemuxPlan
from castcast.capability import Verdict, Issue
from castcast.probe import MediaInfo, VideoStream, AudioStream

def test_build_plan_no_processing_needed():
    info = MediaInfo(path="/path/to/movie.mp4")
    verdict = Verdict(
        castable=True,
        needs_processing=False,
        will_be_4k=False,
        issues=[],
        summary="Ready to cast as-is.",
    )
    plan = build_plan(info, verdict, "/work")
    assert plan is None

def test_build_plan_video_copy_audio_copy():
    info = MediaInfo(
        path="/path/to/movie.mkv",
        video=[VideoStream(codec="h264", width=1920, height=1080)],
        audio=[AudioStream(codec="aac", channels=2)]
    )
    verdict = Verdict(
        castable=True,
        needs_processing=True,
        will_be_4k=False,
        issues=[],
        summary="Needs remux.",
        target_container="mp4",
        video_action="copy",
        audio_action="copy"
    )
    plan = build_plan(info, verdict, "/work")

    assert plan is not None
    assert plan.input_path == "/path/to/movie.mkv"
    assert plan.output_path == os.path.join("/work", "movie.cast.mp4")
    assert plan.lossless_video is True
    assert plan.lossless_audio is True

    assert "-c:v" in plan.args
    assert plan.args[plan.args.index("-c:v") + 1] == "copy"
    assert "-c:a" in plan.args
    assert plan.args[plan.args.index("-c:a") + 1] == "copy"
    assert "-sn" in plan.args
    assert "-movflags" in plan.args
    assert plan.args[plan.args.index("-movflags") + 1] == "+faststart"
    assert plan.description == "Lossless remux to MP4 -- streams copied byte-for-byte."

def test_build_plan_video_transcode_hevc_10bit():
    info = MediaInfo(
        path="/path/to/movie.mp4",
        video=[VideoStream(codec="vp9", width=3840, height=2160, bit_depth=10)],
        audio=[AudioStream(codec="aac", channels=2)]
    )
    verdict = Verdict(
        castable=False,
        needs_processing=True,
        will_be_4k=True,
        issues=[],
        summary="Needs video transcode.",
        target_container="mp4",
        video_action="transcode",
        audio_action="copy"
    )
    plan = build_plan(info, verdict, "/work")

    assert plan is not None
    assert plan.lossless_video is False
    assert plan.lossless_audio is True

    assert "-c:v" in plan.args
    assert plan.args[plan.args.index("-c:v") + 1] == "libx265"
    assert "-pix_fmt" in plan.args
    assert plan.args[plan.args.index("-pix_fmt") + 1] == "yuv420p10le"
    assert "-tag:v" in plan.args
    assert plan.args[plan.args.index("-tag:v") + 1] == "hvc1"
    assert plan.description == "Full video re-encode to HEVC in MP4. Slow and lossy."

def test_build_plan_video_transcode_sdr():
    info = MediaInfo(
        path="/path/to/movie.mp4",
        video=[VideoStream(codec="vp9", width=1920, height=1080, bit_depth=8)],
        audio=[AudioStream(codec="aac", channels=2)]
    )
    verdict = Verdict(
        castable=False,
        needs_processing=True,
        will_be_4k=False,
        issues=[],
        summary="Needs video transcode.",
        target_container="mp4",
        video_action="transcode",
        audio_action="copy"
    )
    plan = build_plan(info, verdict, "/work")

    assert plan is not None
    assert "-pix_fmt" in plan.args
    assert plan.args[plan.args.index("-pix_fmt") + 1] == "yuv420p"

def test_build_plan_audio_transcode_stereo():
    info = MediaInfo(
        path="/path/to/movie.mp4",
        video=[VideoStream(codec="h264", width=1920, height=1080)],
        audio=[AudioStream(codec="dts", channels=2)]
    )
    verdict = Verdict(
        castable=False,
        needs_processing=True,
        will_be_4k=False,
        issues=[],
        summary="Needs audio transcode.",
        target_container="mp4",
        video_action="copy",
        audio_action="transcode"
    )
    plan = build_plan(info, verdict, "/work")

    assert plan is not None
    assert plan.lossless_video is True
    assert plan.lossless_audio is False

    assert "-c:a" in plan.args
    assert plan.args[plan.args.index("-c:a") + 1] == "aac"
    assert "-b:a" in plan.args
    assert plan.args[plan.args.index("-b:a") + 1] == "192k"
    assert "-ac" not in plan.args
    assert plan.description == "Remux to MP4, re-encoding audio to AAC. Video quality untouched."

def test_build_plan_audio_transcode_51():
    info = MediaInfo(
        path="/path/to/movie.mp4",
        video=[VideoStream(codec="h264", width=1920, height=1080)],
        audio=[AudioStream(codec="dts", channels=6)]
    )
    verdict = Verdict(
        castable=False,
        needs_processing=True,
        will_be_4k=False,
        issues=[],
        summary="Needs audio transcode.",
        target_container="mp4",
        video_action="copy",
        audio_action="transcode"
    )
    plan = build_plan(info, verdict, "/work")

    assert plan is not None
    assert "-c:a" in plan.args
    assert plan.args[plan.args.index("-c:a") + 1] == "aac"
    assert "-b:a" in plan.args
    assert plan.args[plan.args.index("-b:a") + 1] == "640k"
    assert "-ac" not in plan.args # 6 channels should not trigger downmix

def test_build_plan_audio_transcode_71_downmix():
    info = MediaInfo(
        path="/path/to/movie.mp4",
        video=[VideoStream(codec="h264", width=1920, height=1080)],
        audio=[AudioStream(codec="truehd", channels=8)]
    )
    verdict = Verdict(
        castable=False,
        needs_processing=True,
        will_be_4k=False,
        issues=[],
        summary="Needs audio transcode.",
        target_container="mp4",
        video_action="copy",
        audio_action="transcode"
    )
    plan = build_plan(info, verdict, "/work")

    assert plan is not None
    assert plan.lossless_audio is False

    assert "-ac" in plan.args
    assert plan.args[plan.args.index("-ac") + 1] == "6"

def test_build_plan_no_audio():
    info = MediaInfo(
        path="/path/to/movie.mp4",
        video=[VideoStream(codec="h264", width=1920, height=1080)],
        audio=[]
    )
    verdict = Verdict(
        castable=True,
        needs_processing=True,
        will_be_4k=False,
        issues=[],
        summary="Needs remux.",
        target_container="webm",
        video_action="copy",
        audio_action="none"
    )
    plan = build_plan(info, verdict, "/work")

    assert plan is not None
    assert "-an" in plan.args
    assert plan.output_path.endswith(".webm")

def test_build_plan_hevc_copy_tag():
    info = MediaInfo(
        path="/path/to/movie.mp4",
        video=[VideoStream(codec="hevc", width=3840, height=2160)],
        audio=[AudioStream(codec="aac", channels=2)]
    )
    verdict = Verdict(
        castable=True,
        needs_processing=True,
        will_be_4k=True,
        issues=[],
        summary="Needs remux.",
        target_container="mp4",
        video_action="copy",
        audio_action="copy"
    )
    plan = build_plan(info, verdict, "/work")

    assert plan is not None
    assert "-c:v" in plan.args
    assert plan.args[plan.args.index("-c:v") + 1] == "copy"
    assert "-tag:v" in plan.args
    assert plan.args[plan.args.index("-tag:v") + 1] == "hvc1"

def test_build_plan_fmp4_container():
    info = MediaInfo(
        path="/path/to/movie.ts",
        video=[VideoStream(codec="h264", width=1920, height=1080)],
        audio=[AudioStream(codec="aac", channels=2)]
    )
    verdict = Verdict(
        castable=True,
        needs_processing=True,
        will_be_4k=False,
        issues=[],
        summary="Needs fmp4.",
        target_container="fmp4",
        video_action="copy",
        audio_action="copy"
    )
    plan = build_plan(info, verdict, "/work")

    assert plan is not None
    assert plan.output_path.endswith(".cast.fmp4.mp4")
    assert "-movflags" in plan.args
    assert plan.args[plan.args.index("-movflags") + 1] == "+frag_keyframe+empty_moov+default_base_moof"
    assert plan.description == "Lossless remux to fragmented MP4 -- streams copied byte-for-byte."

def test_build_plan_webm_container():
    info = MediaInfo(
        path="/path/to/movie.mkv",
        video=[VideoStream(codec="vp9", width=1920, height=1080)],
        audio=[AudioStream(codec="opus", channels=2)]
    )
    verdict = Verdict(
        castable=True,
        needs_processing=True,
        will_be_4k=False,
        issues=[],
        summary="Needs webm.",
        target_container="webm",
        video_action="copy",
        audio_action="copy"
    )
    plan = build_plan(info, verdict, "/work")

    assert plan is not None
    assert plan.output_path.endswith(".cast.webm")
    assert "-f" in plan.args
    assert plan.args[plan.args.index("-f") + 1] == "webm"
    assert plan.description == "Lossless remux to WebM -- streams copied byte-for-byte."


def test_remux_plan_command():
    plan = RemuxPlan(
        input_path="/in/file.mkv",
        output_path="/out/file.mp4",
        args=["-c:v", "copy", "-c:a", "copy"],
        description="test",
        estimated="1s"
    )
    cmd = plan.command
    assert "-hide_banner" in cmd
    assert "-y" in cmd
    assert "-i" in cmd
    assert cmd[cmd.index("-i") + 1] == "/in/file.mkv"
    assert cmd[-1] == "/out/file.mp4"
    assert "-c:v" in cmd

    assert "ffmpeg" in plan.shell_command
    assert "-hide_banner" in plan.shell_command

def test_remux_plan_to_dict():
    plan = RemuxPlan(
        input_path="/in/file.mkv",
        output_path="/out/file.mp4",
        args=["-c:v", "copy"],
        description="desc",
        estimated="est"
    )
    d = plan.to_dict()
    assert d["input_path"] == "/in/file.mkv"
    assert d["output_path"] == "/out/file.mp4"
    assert d["args"] == ["-c:v", "copy"]
    assert "shell_command" in d

from castcast.remux import RemuxJob
import time

def test_remux_job_to_dict():
    plan = RemuxPlan(
        input_path="/in/file.mkv",
        output_path="/out/file.mp4",
        args=["-c:v", "copy"],
        description="desc",
        estimated="est"
    )
    job = RemuxJob(plan=plan, state="running", progress=0.5, error="none", started_at=time.time() - 10, finished_at=time.time())
    d = job.to_dict()
    assert d["state"] == "running"
    assert d["progress"] == 0.5
    assert d["error"] == "none"
    assert d["output_path"] == "/out/file.mp4"
    assert d["description"] == "desc"
    assert "shell_command" in d
    assert "elapsed_s" in d
    assert d["elapsed_s"] > 0

from castcast.remux import Remuxer
from unittest.mock import patch, MagicMock

def test_remuxer_init():
    r = Remuxer()
    assert r.busy is False
    assert r.job is None

@patch("castcast.remux.have_ffmpeg", return_value=False)
def test_remuxer_run_no_ffmpeg(mock_have_ffmpeg):
    r = Remuxer()
    plan = RemuxPlan(
        input_path="/in/file.mkv",
        output_path="/out/file.mp4"
    )
    job = r.run(plan)
    assert job.state == "failed"
    assert "not found on PATH" in job.error

@patch("castcast.remux.have_ffmpeg", return_value=True)
@patch("subprocess.Popen")
@patch("os.makedirs")
def test_remuxer_run_success(mock_makedirs, mock_popen, mock_have_ffmpeg):
    mock_proc = MagicMock()
    mock_proc.stdout = [b"out_time_ms=5000000"] # 5 seconds
    mock_proc.stderr = None
    mock_proc.returncode = 0
    mock_popen.return_value = mock_proc

    events = []
    def on_update(j):
        events.append(j.progress)

    r = Remuxer(on_update=on_update)
    plan = RemuxPlan(
        input_path="/in/file.mkv",
        output_path="/out/file.mp4"
    )
    job = r.run(plan, duration_s=10.0)

    assert job.state == "done"
    assert job.progress == 1.0
    assert job.error == ""
    assert len(events) > 0 # Initial emit + progress emit + final emit

@patch("castcast.remux.have_ffmpeg", return_value=True)
@patch("subprocess.Popen")
@patch("os.makedirs")
@patch("castcast.remux._unlink")
def test_remuxer_run_failure(mock_unlink, mock_makedirs, mock_popen, mock_have_ffmpeg):
    mock_proc = MagicMock()
    mock_proc.stdout = []
    mock_proc.stderr.read.return_value = b"ffmpeg error details"
    mock_proc.returncode = 1
    mock_popen.return_value = mock_proc

    r = Remuxer()
    plan = RemuxPlan(
        input_path="/in/file.mkv",
        output_path="/out/file.mp4"
    )
    job = r.run(plan)

    assert job.state == "failed"
    assert "ffmpeg error details" in job.error
    mock_unlink.assert_called_once_with("/out/file.mp4")

@patch("castcast.remux.have_ffmpeg", return_value=True)
@patch("subprocess.Popen")
@patch("os.makedirs")
@patch("castcast.remux._unlink")
def test_remuxer_run_exception(mock_unlink, mock_makedirs, mock_popen, mock_have_ffmpeg):
    mock_popen.side_effect = Exception("boom")

    r = Remuxer()
    plan = RemuxPlan(
        input_path="/in/file.mkv",
        output_path="/out/file.mp4"
    )
    job = r.run(plan)

    assert job.state == "failed"
    assert job.error == "boom"
    mock_unlink.assert_called_once_with("/out/file.mp4")

def test_remuxer_cancel():
    r = Remuxer()
    r.job = RemuxJob(plan=RemuxPlan(input_path="", output_path=""), state="running")
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    r._proc = mock_proc
    r.cancel()
    mock_proc.terminate.assert_called_once()
    assert r.job.state == "cancelled"

@patch("castcast.remux.os.unlink")
def test_unlink_success(mock_unlink):
    from castcast.remux import _unlink
    _unlink("/path")
    mock_unlink.assert_called_once_with("/path")

@patch("castcast.remux.os.unlink", side_effect=OSError("not found"))
def test_unlink_error(mock_unlink):
    from castcast.remux import _unlink
    _unlink("/path") # Should swallow error
    mock_unlink.assert_called_once_with("/path")

@patch("castcast.remux.have_ffmpeg", return_value=True)
@patch("subprocess.Popen")
@patch("os.makedirs")
@patch("castcast.remux._unlink")
def test_remuxer_run_cancelled(mock_unlink, mock_makedirs, mock_popen, mock_have_ffmpeg):
    mock_proc = MagicMock()
    mock_proc.stdout = []
    mock_proc.stderr = None
    mock_proc.returncode = 1
    mock_popen.return_value = mock_proc

    r = Remuxer()
    plan = RemuxPlan(
        input_path="/in/file.mkv",
        output_path="/out/file.mp4"
    )

    # We need to simulate cancelling the job while it's running
    def cancel_side_effect(*args, **kwargs):
        r.job.state = "cancelled"

    mock_proc.wait.side_effect = cancel_side_effect

    job = r.run(plan)

    assert job.state == "cancelled"
    mock_unlink.assert_called_once_with("/out/file.mp4")

def test_remuxer_emit_exception():
    def bad_listener(j):
        raise Exception("bad listener")
    r = Remuxer(on_update=bad_listener)
    r._emit(RemuxJob(plan=RemuxPlan("",""))) # Should not raise

@patch("castcast.remux.have_ffmpeg", return_value=True)
@patch("subprocess.Popen")
@patch("os.makedirs")
def test_remuxer_run_success_empty_stderr(mock_makedirs, mock_popen, mock_have_ffmpeg):
    mock_proc = MagicMock()
    mock_proc.stdout = []
    mock_proc.stderr = None
    mock_proc.returncode = 0
    mock_popen.return_value = mock_proc

    r = Remuxer()
    plan = RemuxPlan(
        input_path="/in/file.mkv",
        output_path="/out/file.mp4"
    )
    job = r.run(plan)

    assert job.state == "done"
    assert job.progress == 1.0

@patch("castcast.remux.have_ffmpeg", return_value=True)
@patch("castcast.remux.probe")
@patch("subprocess.Popen")
@patch("os.makedirs")
@patch("castcast.remux._unlink")
def test_remuxer_run_hdr_metadata_loss_retry(mock_unlink, mock_makedirs, mock_popen, mock_probe, mock_have_ffmpeg):
    mock_proc1 = MagicMock()
    mock_proc1.stdout = []
    mock_proc1.stderr.read.return_value = b""
    mock_proc1.returncode = 0

    mock_proc2 = MagicMock()
    mock_proc2.stdout = []
    mock_proc2.stderr.read.return_value = b""
    mock_proc2.returncode = 0

    mock_popen.side_effect = [mock_proc1, mock_proc2]

    # First probe simulation: metadata lost
    out_info_lost = MagicMock()
    out_info_lost.primary_video = MagicMock(color_transfer="unspecified")
    mock_probe.return_value = out_info_lost

    events = []
    def on_update(j):
        if j.error:
            events.append(j.error)

    r = Remuxer(on_update=on_update)
    plan = RemuxPlan(
        input_path="/in/file.mkv",
        output_path="/out/file.mp4",
        lossless_video=True,
        expected_hdr_format="HDR10",
        expected_color_primaries="bt2020",
        expected_color_transfer="smpte2084",
        expected_color_space="bt2020nc",
        video_codec="hevc",
        args=["-c:v", "copy"]
    )
    job = r.run(plan)

    assert job.state == "done"
    assert mock_popen.call_count == 2
    mock_probe.assert_called_once_with("/out/file.mp4")

    # Assert args were modified
    assert "-bsf:v" in plan.args
    bsf_val = plan.args[plan.args.index("-bsf:v") + 1]
    assert "hevc_metadata=colour_primaries=9:transfer_characteristics=16:matrix_coefficients=9" in bsf_val

    # Assert warning event was emitted
    assert "HDR metadata lost; retrying with bitstream filters" in events
    # Unlink called once after first failed metadata check
    mock_unlink.assert_called_once_with("/out/file.mp4")

@patch("castcast.remux.have_ffmpeg", return_value=True)
@patch("castcast.remux.probe")
@patch("subprocess.Popen")
@patch("os.makedirs")
@patch("castcast.remux._unlink")
def test_remuxer_run_hdr_metadata_preserved(mock_unlink, mock_makedirs, mock_popen, mock_probe, mock_have_ffmpeg):
    mock_proc1 = MagicMock()
    mock_proc1.stdout = []
    mock_proc1.stderr.read.return_value = b""
    mock_proc1.returncode = 0

    mock_popen.side_effect = [mock_proc1]

    # First probe simulation: metadata preserved
    out_info_kept = MagicMock()
    out_info_kept.primary_video = MagicMock(color_transfer="smpte2084")
    mock_probe.return_value = out_info_kept

    r = Remuxer()
    plan = RemuxPlan(
        input_path="/in/file.mkv",
        output_path="/out/file.mp4",
        lossless_video=True,
        expected_hdr_format="HDR10",
        expected_color_primaries="bt2020",
        expected_color_transfer="smpte2084",
        expected_color_space="bt2020nc",
        video_codec="hevc",
        args=["-c:v", "copy"]
    )
    job = r.run(plan)

    assert job.state == "done"
    assert mock_popen.call_count == 1
    mock_probe.assert_called_once_with("/out/file.mp4")
    assert "-bsf:v" not in plan.args
    mock_unlink.assert_not_called()

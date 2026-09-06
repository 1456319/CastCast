import os
import pytest
from unittest.mock import MagicMock, patch
from castcast.probe import MediaInfo, VideoStream, AudioStream
from castcast import capability, remux
from castcast.service import CastService as Service
from castcast.supervisor import Supervisor, State

def test_capability_defaults_to_ultra_and_accurate_4k():
    info = MediaInfo(
        path="/videos/test_4k.mkv",
        container="matroska",
        duration_s=100.0,
        size_bytes=1000000,
        bitrate_kbps=15000,
        video=[VideoStream(index=0, codec="hevc", width=3840, height=2160, fps=24.0, bit_depth=10, profile="Main 10")],
        audio=[],
        subtitles=[]
    )
    # Default is_ultra=True: 4K HEVC in MKV is a lossless remux (copy), preserving 4K
    verdict_ultra = capability.evaluate(info, is_ultra=True)
    assert verdict_ultra.video_action == "copy"
    assert verdict_ultra.will_be_4k is True

    # If is_ultra=False: non-ultra downscales to 1080p, so will_be_4k must be False
    verdict_legacy = capability.evaluate(info, is_ultra=False)
    assert verdict_legacy.video_action == "transcode"
    assert verdict_legacy.will_be_4k is False

def test_service_preflight_defaults_to_ultra():
    service = Service.__new__(Service)
    service.config = {}
    service.work_dir = "/tmp"
    service.supervisor = None
    service.device = None
    service.probe_cached = MagicMock(return_value=MediaInfo(
        path="/videos/test_4k.mkv",
        container="matroska",
        duration_s=100.0,
        size_bytes=1000000,
        bitrate_kbps=15000,
        video=[VideoStream(index=0, codec="hevc", width=3840, height=2160, fps=24.0, bit_depth=10, profile="Main 10")],
        audio=[],
        subtitles=[]
    ))
    report = service.preflight("/videos/test_4k.mkv")
    assert report["verdict"]["video_action"] == "copy"
    assert report["verdict"]["will_be_4k"] is True

def test_queue_blocks_unauthorized_video_transcode():
    service = Service.__new__(Service)
    service.supervisor = MagicMock()
    service.log = MagicMock()
    service._queued_for_later = set()
    service.prepare = MagicMock()
    
    # Mock preflight returning a file that requires video transcoding
    service.preflight = MagicMock(return_value={
        "prepared_path": None,
        "verdict": {
            "needs_processing": True,
            "video_action": "transcode",
            "issues": []
        },
        "media": {}
    })
    res = service.queue(["/videos/transcode_needed.avi"])
    # Prepare must NOT be called for video transcode in queue
    service.prepare.assert_not_called()
    service.log.assert_called_with("queue: skipping transcode_needed.avi - video re-encoding requires explicit confirmation", "warn")
    assert res.get("skipped", 0) >= 1 or res.get("error") == "no castable items found in the provided paths"

def test_queue_skips_transcode_and_queues_valid_item():
    service = Service.__new__(Service)
    service.supervisor = MagicMock()
    service.log = MagicMock()
    service._queued_for_later = set()
    service.prepare = MagicMock()
    service.media_server = MagicMock()
    service.media_server.url_for = lambda p: f"http://localhost:8080/{p}"
    service.default_language = "eng"
    service._scavenge_all_local_subtitles = MagicMock(return_value=[])
    service._tracks_for_load = MagicMock(return_value=([], []))
    service._lock = MagicMock()

    service.preflight = MagicMock(side_effect=[
        {
            "prepared_path": None,
            "verdict": {
                "needs_processing": True,
                "video_action": "transcode",
                "issues": []
            },
            "media": {}
        },
        {
            "prepared_path": None,
            "verdict": {
                "needs_processing": False,
                "video_action": "copy",
                "issues": []
            },
            "media": {"duration_s": 100}
        }
    ])
    res = service.queue(["/videos/transcode_needed.avi", "/videos/ready.mp4"])
    service.prepare.assert_not_called()
    assert res.get("skipped", 0) == 1
    assert res.get("queued", 0) == 1


def test_preflight_does_not_reuse_1080p_cache_for_4k_source(tmp_path):
    svc = Service({"media_roots": [str(tmp_path)], "work_dir": str(tmp_path / "work")})
    source_path = str(tmp_path / "movie_4k.mkv")
    with open(source_path, "w") as f:
        f.write("fake 4k content")

    source_info = MediaInfo(
        path=source_path,
        container="matroska",
        duration_s=100.0,
        size_bytes=1000000,
        video=[VideoStream(index=0, codec="hevc", width=3840, height=2160, fps=24.0, bit_depth=10, profile="Main 10")],
        audio=[AudioStream(index=1, codec="dts", channels=6)],
    )

    verdict = capability.evaluate(source_info, is_ultra=True)
    plan = remux.build_plan(source_info, verdict, str(tmp_path / "work"), is_ultra=True)
    assert plan is not None

    os.makedirs(os.path.dirname(plan.output_path), exist_ok=True)
    with open(plan.output_path, "w") as f:
        f.write("cached 1080p file")

    cached_1080p_info = MediaInfo(
        path=plan.output_path,
        container="mp4",
        duration_s=100.0,
        size_bytes=500000,
        video=[VideoStream(index=0, codec="h264", width=1920, height=1080, fps=24.0)],
        audio=[AudioStream(index=1, codec="aac", channels=2)],
    )

    def mock_probe(path):
        if path == source_path:
            return source_info
        elif path == plan.output_path:
            return cached_1080p_info
        raise ValueError(f"Unexpected probe path: {path}")

    svc.probe_cached = MagicMock(side_effect=mock_probe)

    res = svc.preflight(source_path)
    # prepared_path MUST be None because the cached file is 1080p while source is 4K
    assert res.get("prepared_path") is None


def test_preflight_reuses_verified_4k_cache_for_4k_source(tmp_path):
    svc = Service({"media_roots": [str(tmp_path)], "work_dir": str(tmp_path / "work")})
    source_path = str(tmp_path / "movie_4k.mkv")
    with open(source_path, "w") as f:
        f.write("fake 4k content")

    source_info = MediaInfo(
        path=source_path,
        container="matroska",
        duration_s=100.0,
        size_bytes=1000000,
        video=[VideoStream(index=0, codec="hevc", width=3840, height=2160, fps=24.0, bit_depth=10, profile="Main 10")],
        audio=[AudioStream(index=1, codec="dts", channels=6)],
    )

    verdict = capability.evaluate(source_info, is_ultra=True)
    plan = remux.build_plan(source_info, verdict, str(tmp_path / "work"), is_ultra=True)
    assert plan is not None

    os.makedirs(os.path.dirname(plan.output_path), exist_ok=True)
    with open(plan.output_path, "w") as f:
        f.write("cached 4k file")

    cached_4k_info = MediaInfo(
        path=plan.output_path,
        container="mp4",
        duration_s=100.0,
        size_bytes=1000000,
        video=[VideoStream(index=0, codec="hevc", width=3840, height=2160, fps=24.0, bit_depth=10, profile="Main 10")],
        audio=[AudioStream(index=1, codec="aac", channels=6)],
    )

    def mock_probe(path):
        if path == source_path:
            return source_info
        elif path == plan.output_path:
            return cached_4k_info
        raise ValueError(f"Unexpected probe path: {path}")

    svc.probe_cached = MagicMock(side_effect=mock_probe)

    res = svc.preflight(source_path)
    assert res.get("prepared_path") == plan.output_path


def test_preflight_does_not_reuse_sdr_cache_for_hdr_source(tmp_path):
    svc = Service({"media_roots": [str(tmp_path)], "work_dir": str(tmp_path / "work")})
    source_path = str(tmp_path / "movie_hdr.mkv")
    with open(source_path, "w") as f:
        f.write("fake hdr content")

    source_info = MediaInfo(
        path=source_path,
        container="matroska",
        duration_s=100.0,
        size_bytes=1000000,
        video=[VideoStream(index=0, codec="hevc", width=3840, height=2160, fps=24.0, bit_depth=10, profile="Main 10", hdr_format="HDR10")],
        audio=[AudioStream(index=1, codec="dts", channels=6)],
    )

    verdict = capability.evaluate(source_info, is_ultra=True)
    plan = remux.build_plan(source_info, verdict, str(tmp_path / "work"), is_ultra=True)
    assert plan is not None

    os.makedirs(os.path.dirname(plan.output_path), exist_ok=True)
    with open(plan.output_path, "w") as f:
        f.write("cached sdr file")

    cached_sdr_info = MediaInfo(
        path=plan.output_path,
        container="mp4",
        duration_s=100.0,
        size_bytes=1000000,
        video=[VideoStream(index=0, codec="hevc", width=3840, height=2160, fps=24.0, bit_depth=10, profile="Main 10", hdr_format="SDR")],
        audio=[AudioStream(index=1, codec="aac", channels=6)],
    )

    def mock_probe(path):
        if path == source_path:
            return source_info
        elif path == plan.output_path:
            return cached_sdr_info
        raise ValueError(f"Unexpected probe path: {path}")

    svc.probe_cached = MagicMock(side_effect=mock_probe)

    res = svc.preflight(source_path)
    assert res.get("prepared_path") is None


def test_preflight_does_not_reuse_stale_or_empty_cache(tmp_path):
    import time
    svc = Service({"media_roots": [str(tmp_path)], "work_dir": str(tmp_path / "work")})
    source_path = str(tmp_path / "movie.mkv")
    with open(source_path, "w") as f:
        f.write("source content")

    source_info = MediaInfo(
        path=source_path,
        container="matroska",
        duration_s=100.0,
        size_bytes=1000,
        video=[VideoStream(index=0, codec="h264", width=1920, height=1080, fps=24.0)],
        audio=[AudioStream(index=1, codec="dts", channels=2)],
    )

    verdict = capability.evaluate(source_info, is_ultra=True)
    plan = remux.build_plan(source_info, verdict, str(tmp_path / "work"), is_ultra=True)
    assert plan is not None

    os.makedirs(os.path.dirname(plan.output_path), exist_ok=True)
    # 1. Empty cache
    with open(plan.output_path, "w") as f:
        pass
    svc.probe_cached = MagicMock(return_value=source_info)
    assert svc.preflight(source_path).get("prepared_path") is None

    # 2. Stale cache (older mtime than source)
    with open(plan.output_path, "w") as f:
        f.write("non-empty")
    os.utime(plan.output_path, (time.time() - 100, time.time() - 100))
    os.utime(source_path, (time.time(), time.time()))
    assert svc.preflight(source_path).get("prepared_path") is None


def test_cast_amazon_accepts_1080p_manifest():
    svc = Service.__new__(Service)
    svc.log = MagicMock()
    svc._lock = MagicMock()
    svc.media_server = MagicMock()
    svc.media_server.lan_ip = "192.168.1.100"
    svc.media_server.port = 8080
    svc.media_server.drm_tokens = {}
    svc.media_server.public_url = ""
    svc.resume_state = {}
    svc.amazon_queue = []
    svc.save_amazon_queue = MagicMock()
    svc.supervisor = MagicMock()

    fake_manifest_data = {
        "mpd_url": "https://manifest.amazon.com/hd_stream.mpd",
        "actor_token": "actor123",
        "playback_envelope": "env123",
        "manifest_text": "<MPD></MPD>"
    }

    with patch("castcast.amazon_drm.fetch_amazon_4k_manifest", return_value=fake_manifest_data), \
         patch("castcast.amazon_drm.parse_mpd_subtitles", return_value=[]):
        res = svc._cast_amazon("https://www.amazon.com/gp/video/detail/amzn1.dv.gti.12345")
        assert res.get("casting") is True
        assert res.get("drm") is True
        svc.supervisor.load.assert_called_once()
        _, kwargs = svc.supervisor.load.call_args
        assert "proxy/?url=" in svc.supervisor.load.call_args[0][0]
        # Verify no require_4k=True was forced
        assert kwargs.get("require_4k") is not True


def test_supervisor_update_resolution_does_not_pause_on_below_4k():
    sup = Supervisor("192.168.1.50")
    sup._media_command = MagicMock()
    sup._set_state(State.PLAYING)

    # Resolution reported as 1080p (below 4K)
    sup._update_resolution(1920, 1080)

    assert sup.status.receiver_width == 1920
    assert sup.status.receiver_height == 1080
    assert sup.status.quality_state == "below_4k"
    # Verify PAUSE was NOT sent
    sup._media_command.assert_not_called()
    assert sup._state is State.PLAYING
    assert sup.status.state == "playing"

    # Resolution reported as 4K
    sup._update_resolution(3840, 2160)
    assert sup.status.receiver_width == 3840
    assert sup.status.receiver_height == 2160
    assert sup.status.quality_state == "receiver_4k"
    sup._media_command.assert_not_called()

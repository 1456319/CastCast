import pytest
from unittest.mock import MagicMock
from castcast.probe import MediaInfo, VideoStream
from castcast import capability
from castcast.service import CastService as Service

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
    service = Service({})
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
    assert "explicitly" in res["error"]
    service.supervisor.queue_load.assert_not_called()

def test_queue_blocks_entire_order_when_one_item_needs_transcode():
    service = Service({})
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
    assert res.get("error")
    service.supervisor.queue_load.assert_not_called()

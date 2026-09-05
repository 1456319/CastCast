import pytest
from unittest.mock import MagicMock
from castcast.service import CastService
from castcast.discovery import CastDevice
from castcast.supervisor import Supervisor
from castcast.probe import MediaInfo

def test_cast_device_is_ultra_property():
    dev_ultra = CastDevice(name="tv", model="Chromecast Ultra")
    assert dev_ultra.is_ultra is True
    dev_std = CastDevice(name="tv", model="Chromecast")
    assert dev_std.is_ultra is False

def test_preflight_with_supervisor_does_not_raise_attribute_error(tmp_path):
    svc = CastService(config={"work_dir": str(tmp_path), "media_roots": [str(tmp_path)]})
    svc.supervisor = Supervisor("192.168.1.50")
    
    media = MediaInfo(path="/fake/path.mp4")
    svc.probe_cached = MagicMock(return_value=media)
    
    res = svc.preflight("/fake/path.mp4")
    assert "media" in res
    assert res["media"]["path"] == "/fake/path.mp4"

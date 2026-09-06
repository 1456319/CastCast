import json
import pytest
from unittest.mock import MagicMock, patch
from castcast.api import _Handler

def test_diagnostics_logs_returns_logs_field_and_finds_audit_log(tmp_path, monkeypatch):
    audit_file = tmp_path / "audit.log"
    audit_file.write_text("TERMUX_BOOTSTRAP_SUCCESS\nAll packages installed.")
    
    mock_service = MagicMock()
    mock_service.log_buffer.recent.return_value = [{"ts": 100.0, "msg": "Daemon listening", "level": "info"}]
    mock_service.supervisor = None
    
    handler = _Handler.__new__(_Handler)
    handler.server = MagicMock(service=mock_service)
    handler.path = "/diagnostics/logs"
    
    captured = {}
    def mock_json(data, status=200):
        captured["data"] = data
        captured["status"] = status
    handler._json = mock_json
    
    import castcast.api as api_mod
    with monkeypatch.context() as m:
        m.setattr(api_mod, "AUDIT_LOG_CANDIDATES", [str(audit_file)])
        handler.do_GET()
        
    assert "logs" in captured["data"]
    assert "log_buffer" in captured["data"]
    assert "audit_log" in captured["data"]
    assert "TERMUX_BOOTSTRAP_SUCCESS" in captured["data"]["audit_log"]
    assert "Daemon listening" in captured["data"]["logs"]
    assert "TERMUX_BOOTSTRAP_SUCCESS" in captured["data"]["logs"]



def test_diagnostics_api_real_log_buffer():
    # Verify that actual entries emitted with `message` (from LogBuffer.add) are formatted
    handler = _Handler.__new__(_Handler)
    mock_service = MagicMock()
    mock_service.supervisor = None
    mock_service.log_buffer.recent.return_value = [
        {"seq": 1, "ts": 123456789.0, "level": "info", "message": "media server listening on port 38399"}
    ]
    handler.server = MagicMock(service=mock_service)
    handler.path = "/diagnostics/logs"
    sent_json = []
    handler._json = lambda payload, status=200: sent_json.append(payload)
    with patch("os.path.exists", return_value=False):
        handler.do_GET()
    
    assert len(sent_json) == 1
    assert "[INFO] media server listening on port 38399" in sent_json[0]["logs"]

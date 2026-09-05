import json
import pytest
from unittest.mock import MagicMock
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

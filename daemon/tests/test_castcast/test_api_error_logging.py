import pytest
from unittest.mock import MagicMock
from castcast.api import _Handler

def test_api_unhandled_exception_logs_traceback():
    mock_service = MagicMock()
    # Simulate an unexpected crash inside connect
    mock_service.connect.side_effect = Exception("Simulated crash in connect")
    
    handler = _Handler.__new__(_Handler)
    handler.server = MagicMock(service=mock_service)
    handler.path = "/connect"
    handler._body = lambda: {"host": "192.168.1.10"}
    
    captured = {}
    handler._json = lambda d, s=200: captured.update({"data": d, "status": s})
    
    handler.do_POST()
    
    assert captured["status"] == 500
    assert "Simulated crash in connect" in captured["data"]["error"]
    # Verify mock_service.log was called with level='error' and captured traceback
    assert any(
        "Simulated crash in connect" in str(call.args[0]) and (len(call.args) > 1 and call.args[1] == "error" or call.kwargs.get("level") == "error")
        for call in mock_service.log.call_args_list
    )

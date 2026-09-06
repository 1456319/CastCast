import http.client
import json
import pytest
from unittest.mock import MagicMock, patch
from castcast.api import ApiServer, _Handler

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


def test_control_api_accepts_private_lan_host():
    mock_service = MagicMock()
    mock_service.status.return_value = {"online": True}

    server = ApiServer(mock_service, host="127.0.0.1", port=0)
    server.start()
    try:
        # 1. Verify Host: 192.168.1.50 and Origin: http://192.168.1.50:5173 is permitted
        conn = http.client.HTTPConnection("127.0.0.1", server.port)
        conn.request("GET", "/status", headers={
            "Host": "192.168.1.50:8765",
            "Origin": "http://192.168.1.50:5173",
        })
        resp = conn.getresponse()
        assert resp.status == 200
        body = json.loads(resp.read().decode("utf-8"))
        assert body == {"online": True}
        conn.close()

        # 2. Verify RFC 1918 10.x.x.x and 172.16.x.x are permitted
        for lan_ip in ["10.0.0.5", "172.16.0.10"]:
            conn = http.client.HTTPConnection("127.0.0.1", server.port)
            conn.request("GET", "/status", headers={
                "Host": f"{lan_ip}:8765",
                "Origin": f"http://{lan_ip}:5173",
            })
            resp = conn.getresponse()
            assert resp.status == 200
            resp.read()
            conn.close()

        # 3. Verify OPTIONS preflight returns Access-Control-Allow-Private-Network: true
        conn = http.client.HTTPConnection("127.0.0.1", server.port)
        conn.request("OPTIONS", "/status", headers={
            "Host": "192.168.1.50:8765",
            "Origin": "http://192.168.1.50:5173",
            "Access-Control-Request-Private-Network": "true",
        })
        resp = conn.getresponse()
        assert resp.status == 204
        assert resp.getheader("Access-Control-Allow-Private-Network") == "true"
        conn.close()

        # 4. Verify external/unauthorized hosts are rejected with 403 Forbidden
        conn = http.client.HTTPConnection("127.0.0.1", server.port)
        conn.request("GET", "/status", headers={
            "Host": "evil.com",
            "Origin": "http://192.168.1.50:5173",
        })
        resp = conn.getresponse()
        assert resp.status == 403
        conn.close()

        # 5. Verify external/unauthorized origins are rejected with 403 Forbidden
        conn = http.client.HTTPConnection("127.0.0.1", server.port)
        conn.request("GET", "/status", headers={
            "Host": "192.168.1.50:8765",
            "Origin": "http://evil.com",
        })
        resp = conn.getresponse()
        assert resp.status == 403
        conn.close()

        # 6. Verify non-private IP (e.g. 8.8.8.8) is rejected with 403 Forbidden
        conn = http.client.HTTPConnection("127.0.0.1", server.port)
        conn.request("GET", "/status", headers={
            "Host": "8.8.8.8:8765",
            "Origin": "http://8.8.8.8:5173",
        })
        resp = conn.getresponse()
        assert resp.status == 403
        conn.close()
    finally:
        server.stop()


def test_control_api_binds_to_all_interfaces():
    mock_service = MagicMock()
    mock_service.status.return_value = {"online": True}
    server = ApiServer(mock_service, host="0.0.0.0", port=0)
    server.start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", server.port)
        conn.request("GET", "/status", headers={"Host": "127.0.0.1"})
        resp = conn.getresponse()
        assert resp.status == 200
        conn.close()
    finally:
        server.stop()


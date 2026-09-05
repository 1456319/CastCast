import pytest
import base64
import urllib.parse
from unittest.mock import MagicMock
from castcast.mediaserver import _Handler

def test_proxy_boundary_security():
    handler = _Handler.__new__(_Handler)
    mock_server = MagicMock()
    mock_server.media_server.root_token = "secret123"
    mock_server.media_server.public_url = "https://subdomain.lhr.life"
    mock_server.media_server.lan_ip = "192.168.1.30"
    mock_server.media_server.port = 38399
    mock_server.media_server.log = MagicMock()
    mock_server.media_server.get_intercept_headers.return_value = {}
    mock_server.media_server.trigger_telemetry = MagicMock()
    handler.server = mock_server
    handler.wfile = MagicMock()
    
    b64 = base64.b64encode(b"http://example.com/video.mp4").decode("utf-8")
    
    # 1. Request arriving via public tunnel host -> 403 Forbidden
    handler.path = f"/proxy/?url={b64}"
    handler.headers = {"Host": "subdomain.lhr.life"}
    sent_errors = []
    handler.send_error = lambda code, msg="": sent_errors.append((code, msg))
    handler._serve_proxy(body=False)
    assert any(code == 403 for code, _ in sent_errors)
    
    # 2. Invalid target scheme (e.g. file://) -> 400 Bad Request
    sent_errors.clear()
    b64_file = base64.b64encode(b"file:///etc/passwd").decode("utf-8")
    handler.path = f"/proxy/?url={b64_file}"
    handler.headers = {"Host": "192.168.1.30:38399"}
    handler._serve_proxy(body=False)
    assert any(code == 400 for code, _ in sent_errors)

    # 3. SSRF loopback target (e.g. 127.0.0.1) -> 403 Forbidden
    sent_errors.clear()
    b64_loopback = base64.b64encode(b"http://127.0.0.1:8765/status").decode("utf-8")
    handler.path = f"/proxy/?url={b64_loopback}"
    handler.headers = {"Host": "192.168.1.30:38399"}
    handler._serve_proxy(body=False)
    assert any(code == 403 for code, _ in sent_errors)

    # 4. Tunnel host blocked even if public_url is None
    mock_server.media_server.public_url = None
    sent_errors.clear()
    handler.path = f"/proxy/?url={b64}"
    handler.headers = {"Host": "other.localhost.run"}
    handler._serve_proxy(body=False)
    assert any(code == 403 for code, _ in sent_errors)

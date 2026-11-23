import http.client
import io
import threading
import urllib.error
import urllib.parse
from http.server import ThreadingHTTPServer
from unittest.mock import MagicMock

import pytest

from castcast.mediaserver import MediaServer, _Handler


class MockMediaServer:
    def __init__(self):
        self.drm_tokens = {}
        self.lan_ip = "127.0.0.1"
        self.logs = []

    def log(self, msg, level="info"):
        self.logs.append((level, msg))


@pytest.fixture
def mock_server():
    server = MockMediaServer()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    httpd.daemon_threads = True
    httpd.media_server = server  # type: ignore[attr-defined]

    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    host, port = httpd.server_address
    yield server, f"http://{host}:{port}", (host, port)

    httpd.shutdown()
    httpd.server_close()


def test_options_cors_preflight(mock_server):
    server, base_url, (host, port) = mock_server

    conn = http.client.HTTPConnection(host, port)
    conn.request("OPTIONS", "/peacock/license")
    resp = conn.getresponse()

    assert resp.status == 200
    assert resp.getheader("Access-Control-Allow-Origin") == "*"
    assert resp.getheader("Access-Control-Allow-Methods") == "POST, GET, OPTIONS"
    assert resp.getheader("Access-Control-Allow-Headers") == "*"
    assert resp.getheader("Access-Control-Allow-Private-Network") == "true"
    conn.close()


def test_options_cors_preflight_with_query_params(mock_server):
    server, base_url, (host, port) = mock_server

    conn = http.client.HTTPConnection(host, port)
    conn.request("OPTIONS", "/peacock/license?variant_id=test-uuid")
    resp = conn.getresponse()

    assert resp.status == 200
    assert resp.getheader("Access-Control-Allow-Origin") == "*"
    assert resp.getheader("Access-Control-Allow-Private-Network") == "true"
    conn.close()


def test_post_license_missing_auth(mock_server, monkeypatch):
    server, base_url, (host, port) = mock_server
    monkeypatch.setattr("castcast.peacock_auth.get_saved_peacock_auth", lambda: {})

    conn = http.client.HTTPConnection(host, port)
    challenge = b"\x08\x04test-challenge-bytes"
    conn.request(
        "POST",
        "/peacock/license",
        body=challenge,
        headers={"Content-Length": str(len(challenge)), "Content-Type": "application/octet-stream"},
    )
    resp = conn.getresponse()

    assert resp.status in (401, 404)
    conn.close()


def test_post_license_invalid_content_length(mock_server):
    server, base_url, (host, port) = mock_server
    server.drm_tokens["peacock_user_token"] = "test-token"

    conn = http.client.HTTPConnection(host, port)
    conn.request(
        "POST",
        "/peacock/license",
        body=b"",
        headers={"Content-Length": "0"},
    )
    resp = conn.getresponse()

    assert resp.status == 400
    conn.close()


def test_post_license_success(mock_server, monkeypatch):
    server, base_url, (host, port) = mock_server
    server.drm_tokens["peacock_user_token"] = "active-user-token-xyz"

    mock_license = b"\x08\x01\x12\x10license-response-binary-data"

    captured_requests = []

    class MockResponse:
        def __init__(self):
            self.headers = {"Content-Type": "application/octet-stream"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

        def read(self):
            return mock_license

    def mock_urlopen(req, timeout=15):
        captured_requests.append(req)
        return MockResponse()

    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)

    conn = http.client.HTTPConnection(host, port)
    challenge = b"\x08\x04challenge-bytes-12345"
    conn.request(
        "POST",
        "/peacock/license?variant_id=test-variant",
        body=challenge,
        headers={"Content-Length": str(len(challenge)), "Content-Type": "application/octet-stream"},
    )
    resp = conn.getresponse()
    body = resp.read()

    assert resp.status == 200
    assert resp.getheader("Content-Type") == "application/octet-stream"
    assert resp.getheader("Access-Control-Allow-Origin") == "*"
    assert resp.getheader("Access-Control-Allow-Private-Network") == "true"
    assert resp.getheader("Content-Length") == str(len(mock_license))
    assert body == mock_license

    assert len(captured_requests) == 1
    out_req = captured_requests[0]
    assert out_req.full_url == "https://play.ovp.peacocktv.com/auth/tokens"
    assert out_req.data == challenge
    assert out_req.headers["X-skyott-usertoken"] == "active-user-token-xyz"
    assert out_req.headers["X-skyott-territory"] == "US"
    assert out_req.headers["X-skyott-provider"] == "NBCUOTT"
    assert out_req.headers["X-skyott-platform"] == "ANDROID"
    assert out_req.headers["Content-type"] == "application/octet-stream"
    conn.close()


def test_post_license_fallback_to_saved_auth(mock_server, monkeypatch):
    server, base_url, (host, port) = mock_server
    # drm_tokens has no peacock_user_token
    monkeypatch.setattr("castcast.peacock_auth.get_saved_peacock_auth", lambda: {"userToken": "saved-auth-token-456"})

    mock_license = b"license-from-saved-auth"

    class MockResponse:
        def __init__(self):
            self.headers = {"Content-Type": "application/octet-stream"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

        def read(self):
            return mock_license

    captured_requests = []

    def mock_urlopen(req, timeout=15):
        captured_requests.append(req)
        return MockResponse()

    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)

    conn = http.client.HTTPConnection(host, port)
    challenge = b"challenge-raw"
    conn.request(
        "POST",
        "/peacock/license",
        body=challenge,
        headers={"Content-Length": str(len(challenge)), "Content-Type": "application/octet-stream"},
    )
    resp = conn.getresponse()
    body = resp.read()

    assert resp.status == 200
    assert body == mock_license
    assert resp.getheader("Content-Length") == str(len(mock_license))
    assert len(captured_requests) == 1
    assert captured_requests[0].headers["X-skyott-usertoken"] == "saved-auth-token-456"
    conn.close()


def test_post_license_variant_specific_token(mock_server, monkeypatch):
    server, base_url, (host, port) = mock_server
    server.drm_tokens["peacock_var999"] = "variant-token-999"

    class MockResponse:
        def __init__(self):
            self.headers = {"Content-Type": "application/octet-stream"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

        def read(self):
            return b"lic-bytes"

    captured_requests = []

    def mock_urlopen(req, timeout=15):
        captured_requests.append(req)
        return MockResponse()

    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)

    conn = http.client.HTTPConnection(host, port)
    challenge = b"challenge-data"
    conn.request(
        "POST",
        "/peacock/license?variant_id=var999",
        body=challenge,
        headers={"Content-Length": str(len(challenge)), "Content-Type": "application/octet-stream"},
    )
    resp = conn.getresponse()
    assert resp.status == 200
    assert len(captured_requests) == 1
    assert captured_requests[0].headers["X-skyott-usertoken"] == "variant-token-999"
    conn.close()


def test_post_license_http_error_forwarded(mock_server, monkeypatch):
    server, base_url, (host, port) = mock_server
    server.drm_tokens["peacock_user_token"] = "valid-token"

    error_payload = b'{"error": "License denied by upstream"}'

    def mock_urlopen(req, timeout=15):
        fp = io.BytesIO(error_payload)
        hdrs = email_message = email.message_from_string("Content-Type: application/json\n\n")
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", hdrs, fp)

    import email
    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)

    conn = http.client.HTTPConnection(host, port)
    challenge = b"challenge-that-fails"
    conn.request(
        "POST",
        "/peacock/license",
        body=challenge,
        headers={"Content-Length": str(len(challenge)), "Content-Type": "application/octet-stream"},
    )
    resp = conn.getresponse()
    body = resp.read()

    assert resp.status == 403
    assert resp.getheader("Access-Control-Allow-Origin") == "*"
    assert resp.getheader("Access-Control-Allow-Private-Network") == "true"
    assert resp.getheader("Content-Length") == str(len(error_payload))
    assert body == error_payload
    conn.close()


def test_media_server_peacock_license_url():
    server = MediaServer(roots=["/tmp"], port=0)
    server.public_url = "https://example.lhr.life"
    assert server.peacock_license_url() == "https://example.lhr.life/peacock/license"
    assert server.peacock_license_url("var123") == "https://example.lhr.life/peacock/license?variant_id=var123"

    server.public_url = None
    assert server.peacock_license_url() is None

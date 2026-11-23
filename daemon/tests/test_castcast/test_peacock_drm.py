import io
import json
import urllib.error
import pytest
from castcast.peacock_drm import parse_peacock_slug, extract_variant_id, fetch_peacock_manifest


def test_parse_peacock_slug():
    url = "https://www.peacocktv.com/watch/asset/movies/unbroken/e6fc9411-749e-3be3-8b8a-c652f15b7477"
    assert extract_variant_id(url) == "e6fc9411-749e-3be3-8b8a-c652f15b7477"

    slug = "/movies/unbroken/e6fc9411-749e-3be3-8b8a-c652f15b7477"
    assert extract_variant_id(slug) == "e6fc9411-749e-3be3-8b8a-c652f15b7477"

    assert parse_peacock_slug(url) == "unbroken"
    assert parse_peacock_slug(slug) == "unbroken"
    assert parse_peacock_slug("plain-slug") == "plain-slug"


def test_extract_variant_id_plain_uuid():
    uuid = "e6fc9411-749e-3be3-8b8a-c652f15b7477"
    assert extract_variant_id(uuid) == uuid
    assert extract_variant_id("not-a-uuid") == "not-a-uuid"


def test_fetch_peacock_manifest_missing_auth(monkeypatch):
    monkeypatch.setattr("castcast.peacock_drm.get_saved_peacock_auth", lambda: {})
    with pytest.raises(RuntimeError, match="No valid Peacock auth token found"):
        fetch_peacock_manifest("e6fc9411-749e-3be3-8b8a-c652f15b7477")


def test_fetch_peacock_manifest_success(monkeypatch):
    monkeypatch.setattr("castcast.peacock_drm.get_saved_peacock_auth", lambda: {"userToken": "test-token-123"})

    class MockResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

        def read(self):
            payload = {
                "manifestUrl": "https://ovp.peacocktv.com/manifest/test.mpd",
                "licenseUrl": "https://play.ovp.peacocktv.com/auth/tokens",
            }
            return json.dumps(payload).encode("utf-8")

    captured_req = []

    def mock_urlopen(req, *args, **kwargs):
        captured_req.append(req)
        return MockResponse()

    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)

    res = fetch_peacock_manifest("e6fc9411-749e-3be3-8b8a-c652f15b7477")
    assert res["manifest_url"] == "https://ovp.peacocktv.com/manifest/test.mpd"
    assert res["license_url"] == "https://play.ovp.peacocktv.com/auth/tokens"
    assert res["user_token"] == "test-token-123"
    assert res["variant_id"] == "e6fc9411-749e-3be3-8b8a-c652f15b7477"

    assert len(captured_req) == 1
    req = captured_req[0]
    assert req.headers["X-skyott-usertoken"] == "test-token-123"
    assert req.headers["X-skyott-territory"] == "US"
    assert req.headers["X-skyott-provider"] == "NBCUOTT"
    assert req.headers["X-skyott-platform"] == "ANDROID"


def test_fetch_peacock_manifest_fallback_stream_url(monkeypatch):
    monkeypatch.setattr("castcast.peacock_drm.get_saved_peacock_auth", lambda: {"userToken": "test-token-123"})

    class MockResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

        def read(self):
            payload = {
                "streamUrl": "https://ovp.peacocktv.com/stream/fallback.mpd",
            }
            return json.dumps(payload).encode("utf-8")

    monkeypatch.setattr("urllib.request.urlopen", lambda req, *args, **kwargs: MockResponse())

    res = fetch_peacock_manifest("e6fc9411-749e-3be3-8b8a-c652f15b7477")
    assert res["manifest_url"] == "https://ovp.peacocktv.com/stream/fallback.mpd"
    assert res["license_url"] == "https://play.ovp.peacocktv.com/auth/tokens"


def test_fetch_peacock_manifest_http_error(monkeypatch):
    monkeypatch.setattr("castcast.peacock_drm.get_saved_peacock_auth", lambda: {"userToken": "test-token-123"})

    def mock_urlopen(req, *args, **kwargs):
        fp = io.BytesIO(b'{"error": "Unauthorized"}')
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, fp)

    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)

    with pytest.raises(RuntimeError, match="Peacock OVP playback request failed: HTTP 401"):
        fetch_peacock_manifest("e6fc9411-749e-3be3-8b8a-c652f15b7477")

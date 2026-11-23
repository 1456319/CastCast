import json
import subprocess
from unittest.mock import MagicMock, patch
import pytest
from castcast.peacock_auth import (
    AUTH_FILE_PATH,
    get_saved_peacock_auth,
    save_peacock_auth,
    parse_ovp_token_payload,
    extract_device_token,
)


def test_parse_ovp_token_payload():
    payload = json.dumps({
        "userToken": "mock_token_abc123",
        "tokenExpiry": {"expiryTime": "2026-11-24T04:40:42.986Z"}
    })
    token, expiry = parse_ovp_token_payload(payload)
    assert token == "mock_token_abc123"
    assert expiry == "2026-11-24T04:40:42.986Z"


def test_parse_ovp_token_payload_empty_or_none():
    payload = json.dumps({
        "userToken": "mock_token_abc123",
        "tokenExpiry": None
    })
    token, expiry = parse_ovp_token_payload(payload)
    assert token == "mock_token_abc123"
    assert expiry == ""


def test_save_and_get_peacock_auth(tmp_path, monkeypatch):
    test_auth_file = tmp_path / "peacock_auth.json"
    monkeypatch.setattr("castcast.peacock_auth.AUTH_FILE_PATH", str(test_auth_file))

    save_peacock_auth({"userToken": "test_tok", "expiry": "2026-11-24"})
    loaded = get_saved_peacock_auth()
    assert loaded["userToken"] == "test_tok"
    assert loaded["expiry"] == "2026-11-24"


def test_get_saved_peacock_auth_nonexistent(tmp_path, monkeypatch):
    test_auth_file = tmp_path / "does_not_exist.json"
    monkeypatch.setattr("castcast.peacock_auth.AUTH_FILE_PATH", str(test_auth_file))
    assert get_saved_peacock_auth() == {}


def test_extract_device_token_success(tmp_path, monkeypatch):
    test_auth_file = tmp_path / "peacock_auth.json"
    monkeypatch.setattr("castcast.peacock_auth.AUTH_FILE_PATH", str(test_auth_file))

    raw_payload = json.dumps({
        "userToken": "live_ovp_tok_xyz",
        "tokenExpiry": {"expiryTime": "2026-12-01T00:00:00Z"}
    })
    mock_res = MagicMock()
    mock_res.returncode = 0
    mock_res.stdout = raw_payload

    with patch("subprocess.run", return_value=mock_res) as mock_run:
        result = extract_device_token("192.168.1.50:5555")
        assert result["userToken"] == "live_ovp_tok_xyz"
        assert result["expiry"] == "2026-12-01T00:00:00Z"
        assert mock_run.called
        cmd = mock_run.call_args[0][0]
        assert "192.168.1.50:5555" in cmd

        # Verify saved
        saved = get_saved_peacock_auth()
        assert saved["userToken"] == "live_ovp_tok_xyz"


def test_extract_device_token_failure_fallback(tmp_path, monkeypatch):
    test_auth_file = tmp_path / "peacock_auth.json"
    monkeypatch.setattr("castcast.peacock_auth.AUTH_FILE_PATH", str(test_auth_file))
    save_peacock_auth({"userToken": "cached_tok", "expiry": "2026-11-20"})

    mock_res = MagicMock()
    mock_res.returncode = 1
    mock_res.stdout = ""

    with patch("subprocess.run", return_value=mock_res):
        result = extract_device_token()
        assert result["userToken"] == "cached_tok"

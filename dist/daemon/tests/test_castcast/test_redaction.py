import pytest
from castcast.mediaserver import redact_sensitive_url

def test_redact_sensitive_url():
    url = "https://cdn.amazon.com/video.mpd?Expires=1700000000&Signature=abc123secret&Key-Pair-Id=APK123&token=supersecret&keep=safe"
    sanitized = redact_sensitive_url(url)
    assert "abc123secret" not in sanitized
    assert "supersecret" not in sanitized
    assert "keep=safe" in sanitized
    assert "[REDACTED]" in sanitized

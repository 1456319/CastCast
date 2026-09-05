import pytest
import base64
import urllib.parse
from castcast.mediaserver import redact_sensitive_url

def test_redact_sensitive_url():
    url = "https://cdn.amazon.com/video.mpd?Expires=1700000000&Signature=abc123secret&Key-Pair-Id=APK123&token=supersecret&keep=safe"
    sanitized = redact_sensitive_url(url)
    assert "abc123secret" not in sanitized
    assert "supersecret" not in sanitized
    assert "keep=safe" in sanitized
    assert "[REDACTED]" in sanitized

def test_nested_base64_redaction():
    inner_url = "https://cdn.amazon.com/manifest.mpd?Signature=SecretSig123&token=SecretToken456"
    b64_inner = base64.b64encode(inner_url.encode("utf-8")).decode("utf-8")
    proxy_url = f"http://192.168.1.32:38399/proxy/?url={b64_inner}"
    
    redacted = redact_sensitive_url(proxy_url)
    assert "SecretSig123" not in redacted
    assert "SecretToken456" not in redacted
    # Ensure nested base64 was decoded, redacted, and re-encoded
    qs = urllib.parse.parse_qs(urllib.parse.urlsplit(redacted).query)
    decoded = base64.b64decode(qs["url"][0]).decode("utf-8")
    assert "Signature=%5BREDACTED%5D" in decoded or "Signature=[REDACTED]" in decoded

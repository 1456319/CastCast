# Peacock SSAI Stripping and 4K Widevine DRM Casting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable CastCast to cast ad-supported Peacock content to Chromecast Ultra in 4K UHD with zero ads by rewriting MPEG-DASH manifests in-flight (stripping SSAI ad `<Period>` elements) and relaying Widevine DRM challenges without circumventing Widevine DRM.

**Architecture:** A lightweight Peacock provider module (`peacock_drm.py`) extracts active user tokens and resolves VOD playback streams. A manifest proxy in `mediaserver.py` intercepts the multi-period DASH manifest, strips SSAI ad periods tagged with `urn:psf:ads:tracking:v1` / `urn:scte:scte35`, and normalizes timeline continuity. An HTTPS Widevine license relay endpoint (`/peacock/license`) forwards the Chromecast CDM's encrypted license requests directly to Peacock's official OVP license server.

**Tech Stack:** Python 3.13+, xml.etree.ElementTree, urllib.request, pychromecast, Shaka Player receiver, Android Widevine Modular DRM.

**Spec:** Research findings from Pixel 10 Pro XL active playback session on *Unbroken* (2014, 4K UHD eligible, ad-supported tier via Xfinity) and `g002-vod-us-cmaf-prd-cc.cdn.peacocktv.com`.

## Global Constraints
- Zero DRM circumvention: Content keys are never extracted, decrypted, or cracked; streams remain 100% encrypted and decryption is performed solely by the Chromecast Ultra's Google-certified L1 hardware CDM.
- Python toolchain: All Python code must be executed and tested via `uv run` in `/home/deck/CastCast`.
- File ownership: All files created or modified must be owned by `deck:deck`.
- Git commits: Every local commit must be pushed to GitHub branch `peacock-research` immediately.
- Code review: Mandatory code review via `requesting-code-review` before finalizing or merging.

---

### Task 1: Peacock OVP Token and Auth Module

**Files:**
- Create: `daemon/castcast/peacock_auth.py`
- Test: `daemon/tests/test_castcast/test_peacock_auth.py`

**Interfaces:**
- Produces: `get_saved_peacock_auth() -> dict`, `save_peacock_auth(token_data: dict) -> None`, `extract_device_token(adb_device: str = None) -> dict`

- [ ] **Step 1: Write failing test for peacock_auth**

```python
import json
import pytest
from castcast.peacock_auth import get_saved_peacock_auth, save_peacock_auth, parse_ovp_token_payload

def test_parse_ovp_token_payload():
    payload = json.dumps({
        "userToken": "mock_token_abc123",
        "tokenExpiry": {"expiryTime": "2026-11-24T04:40:42.986Z"}
    })
    token, expiry = parse_ovp_token_payload(payload)
    assert token == "mock_token_abc123"
    assert expiry == "2026-11-24T04:40:42.986Z"

def test_save_and_get_peacock_auth(tmp_path, monkeypatch):
    test_auth_file = tmp_path / "peacock_auth.json"
    monkeypatch.setattr("castcast.peacock_auth.AUTH_FILE_PATH", str(test_auth_file))
    
    save_peacock_auth({"userToken": "test_tok", "expiry": "2026-11-24"})
    loaded = get_saved_peacock_auth()
    assert loaded["userToken"] == "test_tok"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/deck/CastCast && uv run pytest daemon/tests/test_castcast/test_peacock_auth.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'castcast.peacock_auth'"

- [ ] **Step 3: Implement `peacock_auth.py`**

```python
import json
import os
import subprocess
from pathlib import Path

AUTH_FILE_PATH = os.path.expanduser("~/.config/castcast/peacock_auth.json")

def parse_ovp_token_payload(payload_str: str) -> tuple[str, str]:
    data = json.loads(payload_str)
    token = data.get("userToken", "")
    expiry = data.get("tokenExpiry", {}).get("expiryTime", "")
    return token, expiry

def save_peacock_auth(auth_data: dict) -> None:
    path = Path(AUTH_FILE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(auth_data, f, indent=2)

def get_saved_peacock_auth() -> dict:
    path = Path(AUTH_FILE_PATH)
    if not path.is_file():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def extract_device_token(adb_target: str = "192.168.1.28:5555") -> dict:
    """Extract live OVP user token from connected Android device if rooted."""
    cmd = ["adb", "-s", adb_target, "shell", "su -c 'cat /data/data/com.peacocktv.peacockandroid/files/ovpTokenFileDataSource'"]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if res.returncode == 0 and res.stdout.strip():
        tok, exp = parse_ovp_token_payload(res.stdout.strip())
        auth = {"userToken": tok, "expiry": exp}
        save_peacock_auth(auth)
        return auth
    return get_saved_peacock_auth()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/deck/CastCast && uv run pytest daemon/tests/test_castcast/test_peacock_auth.py -v`
Expected: PASS

- [ ] **Step 5: Commit and push**

```bash
git add daemon/castcast/peacock_auth.py daemon/tests/test_castcast/test_peacock_auth.py
git commit -m "feat(peacock): add peacock_auth token storage and parser"
git push origin peacock-research
```

---

### Task 2: Peacock Stream Discovery and Manifest Resolver

**Files:**
- Create: `daemon/castcast/peacock_drm.py`
- Test: `daemon/tests/test_castcast/test_peacock_drm.py`

**Interfaces:**
- Consumes: `get_saved_peacock_auth()` from `peacock_auth.py`
- Produces: `parse_peacock_slug(url_or_slug: str) -> str`, `fetch_peacock_manifest(variant_id: str) -> dict`

- [ ] **Step 1: Write failing test for peacock_drm**

```python
import pytest
from castcast.peacock_drm import parse_peacock_slug, extract_variant_id

def test_parse_peacock_slug():
    url = "https://www.peacocktv.com/watch/asset/movies/unbroken/e6fc9411-749e-3be3-8b8a-c652f15b7477"
    assert extract_variant_id(url) == "e6fc9411-749e-3be3-8b8a-c652f15b7477"
    
    slug = "/movies/unbroken/e6fc9411-749e-3be3-8b8a-c652f15b7477"
    assert extract_variant_id(slug) == "e6fc9411-749e-3be3-8b8a-c652f15b7477"

def test_fetch_peacock_manifest_missing_auth(monkeypatch):
    monkeypatch.setattr("castcast.peacock_drm.get_saved_peacock_auth", lambda: {})
    with pytest.raises(RuntimeError, match="No valid Peacock auth token found"):
        from castcast.peacock_drm import fetch_peacock_manifest
        fetch_peacock_manifest("e6fc9411-749e-3be3-8b8a-c652f15b7477")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/deck/CastCast && uv run pytest daemon/tests/test_castcast/test_peacock_drm.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'castcast.peacock_drm'"

- [ ] **Step 3: Implement `peacock_drm.py`**

```python
import re
import json
import urllib.request
import urllib.error
from .peacock_auth import get_saved_peacock_auth

UUID_PATTERN = re.compile(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", re.IGNORECASE)

def parse_peacock_slug(url_or_slug: str) -> str:
    match = re.search(r"/(?:movies|tv|watch/asset/[^/]+)/([^/?#]+)", url_or_slug)
    if match:
        return match.group(1)
    return url_or_slug

def extract_variant_id(url_or_slug: str) -> str:
    matches = UUID_PATTERN.findall(url_or_slug)
    if matches:
        return matches[-1]
    return url_or_slug

def fetch_peacock_manifest(variant_id: str) -> dict:
    auth = get_saved_peacock_auth()
    user_token = auth.get("userToken")
    if not user_token:
        raise RuntimeError("No valid Peacock auth token found")

    url = f"https://ovp.peacocktv.com/video/stream/pck/vod/{variant_id}"
    headers = {
        "X-SkyOTT-UserToken": user_token,
        "X-SkyOTT-Territory": "US",
        "X-SkyOTT-Provider": "NBCUOTT",
        "X-SkyOTT-Platform": "ANDROID",
        "Accept": "application/json"
    }

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return {
                "manifest_url": data.get("manifestUrl") or data.get("streamUrl", ""),
                "license_url": data.get("licenseUrl", "https://play.ovp.peacocktv.com/auth/tokens"),
                "user_token": user_token,
                "variant_id": variant_id
            }
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Peacock OVP playback request failed: HTTP {e.code} - {e.read().decode('utf-8', errors='ignore')}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/deck/CastCast && uv run pytest daemon/tests/test_castcast/test_peacock_drm.py -v`
Expected: PASS

- [ ] **Step 5: Commit and push**

```bash
git add daemon/castcast/peacock_drm.py daemon/tests/test_castcast/test_peacock_drm.py
git commit -m "feat(peacock): add peacock_drm stream discovery and manifest resolver"
git push origin peacock-research
```

---

### Task 3: Manifest Rewriter and SSAI Period Stripper

**Files:**
- Modify: `daemon/castcast/mediaserver.py`
- Test: `daemon/tests/test_castcast/test_peacock_manifest.py`

**Interfaces:**
- Produces: `transform_peacock_dash_manifest(manifest_xml: str, target_url: str) -> str`

- [ ] **Step 1: Write failing test for SSAI period stripping**

```python
import pytest
from castcast.mediaserver import transform_peacock_dash_manifest

SAMPLE_PEACOCK_MPD = """<?xml version="1.0" encoding="UTF-8"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" minBufferTime="PT2S" type="static">
  <Period id="ad_period_pre_roll" start="PT0S" duration="PT189S">
    <EventStream schemeIdUri="urn:psf:ads:tracking:v1" value="1"/>
    <AdaptationSet mimeType="video/mp4" contentType="video">
      <Representation id="ad_video" bandwidth="2000000"/>
    </AdaptationSet>
  </Period>
  <Period id="feature_movie_period" start="PT189S" duration="PT8243S">
    <AdaptationSet mimeType="video/mp4" contentType="video">
      <ContentProtection schemeIdUri="urn:uuid:edef8ba9-79d6-4ace-a3c8-27dcd51d21ed"/>
      <Representation id="feature_video_4k" bandwidth="15000000" width="3840" height="2160"/>
    </AdaptationSet>
  </Period>
</MPD>"""

def test_transform_peacock_dash_manifest_strips_ads():
    transformed = transform_peacock_dash_manifest(SAMPLE_PEACOCK_MPD, "https://g002-vod-us-cmaf-prd-cc.cdn.peacocktv.com/path/manifest.mpd")
    assert "ad_period_pre_roll" not in transformed
    assert "urn:psf:ads:tracking:v1" not in transformed
    assert "feature_movie_period" in transformed
    assert "height=\"2160\"" in transformed
    assert 'start="PT0S"' in transformed or 'start="PT0.000S"' in transformed
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/deck/CastCast && uv run pytest daemon/tests/test_castcast/test_peacock_manifest.py -v`
Expected: FAIL with "ImportError: cannot import name 'transform_peacock_dash_manifest'"

- [ ] **Step 3: Implement `transform_peacock_dash_manifest` in `mediaserver.py`**

```python
def transform_peacock_dash_manifest(body_content: str, target_url: str) -> str:
    """
    In-flight transformation for Peacock DASH manifests:
    1. BaseURL injection for CDN segment resolution.
    2. Strips all SSAI advertising <Period> elements (urn:psf:ads:tracking:v1, urn:scte:scte35).
    3. Normalizes presentation start time of the feature Period to 0.
    4. Preserves 4K UHD Widevine ContentProtection descriptors.
    """
    import re, xml.etree.ElementTree as ET

    base_url = target_url[:target_url.rfind('/')+1]
    if "<BaseURL>" not in body_content:
        body_content = re.sub(r'(<MPD[^>]*>)', r'\1\n  <BaseURL>' + base_url + r'</BaseURL>', body_content, count=1)

    try:
        # Strip XML namespaces for uniform parsing
        xml_clean = re.sub(r'\sxmlns="[^"]+"', '', body_content, count=1)
        root = ET.fromstring(xml_clean)

        ad_schemes = {"urn:psf:ads:tracking:v1", "urn:scte:scte35:2014:bin", "urn:sva:advertising-wg:ad-id-signaling"}
        periods = root.findall(".//Period")
        
        feature_period = None
        for p in periods:
            is_ad = False
            for elem in p.iter():
                scheme = elem.attrib.get("schemeIdUri", "")
                if scheme in ad_schemes or "ad" in p.attrib.get("id", "").lower():
                    is_ad = True
                    break
            if is_ad:
                root.remove(p)
            else:
                if feature_period is None:
                    feature_period = p

        if feature_period is not None:
            feature_period.attrib["start"] = "PT0S"

        # Re-inject default namespace
        out = ET.tostring(root, encoding="utf-8").decode("utf-8")
        out = re.sub(r'<MPD([^>]*)>', r'<MPD\1 xmlns="urn:mpeg:dash:schema:mpd:2011">', out, count=1)
        return out
    except Exception:
        # Fallback regex strip
        cleaned = re.sub(r'<Period[^>]*ad[^>]*>.*?</Period>', '', body_content, flags=re.DOTALL | re.IGNORECASE)
        return cleaned
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/deck/CastCast && uv run pytest daemon/tests/test_castcast/test_peacock_manifest.py -v`
Expected: PASS

- [ ] **Step 5: Commit and push**

```bash
git add daemon/castcast/mediaserver.py daemon/tests/test_castcast/test_peacock_manifest.py
git commit -m "feat(peacock): add transform_peacock_dash_manifest with SSAI period stripping"
git push origin peacock-research
```

---

### Task 4: Widevine License Relay Endpoint in Mediaserver

**Files:**
- Modify: `daemon/castcast/mediaserver.py`
- Test: `daemon/tests/test_castcast/test_peacock_license_proxy.py`

**Interfaces:**
- Produces: HTTP POST `/peacock/license` endpoint in `MediaServerHandler`

- [ ] **Step 1: Write failing test for peacock license proxy**

```python
import urllib.request
import pytest
from unittest.mock import patch, MagicMock

def test_peacock_license_handler_routes():
    # Verify /peacock/license POST handling exists on handler
    from castcast.mediaserver import MediaServerHandler
    assert hasattr(MediaServerHandler, "do_POST")
```

- [ ] **Step 2: Run test to verify it fails/passes initial check**

Run: `cd /home/deck/CastCast && uv run pytest daemon/tests/test_castcast/test_peacock_license_proxy.py -v`

- [ ] **Step 3: Implement `/peacock/license` in `mediaserver.py`**

In `do_POST` of `MediaServerHandler`:
```python
if self.path.startswith("/peacock/license"):
    content_len = int(self.headers.get("Content-Length", 0))
    challenge_bytes = self.rfile.read(content_len) if content_len > 0 else b""
    
    # Retrieve active user token
    token = self.server.drm_tokens.get("peacock_user_token", "")
    target_license_url = "https://play.ovp.peacocktv.com/auth/tokens"
    
    headers = {
        "X-SkyOTT-UserToken": token,
        "X-SkyOTT-Territory": "US",
        "X-SkyOTT-Provider": "NBCUOTT",
        "X-SkyOTT-Platform": "ANDROID",
        "Content-Type": "application/octet-stream"
    }
    
    req = urllib.request.Request(target_license_url, data=challenge_bytes, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req) as resp:
            resp_bytes = resp.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(resp_bytes)))
            self.end_headers()
            self.wfile.write(resp_bytes)
    except urllib.error.HTTPError as e:
        err = e.read()
        self.send_response(e.code)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(err)
    return
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/deck/CastCast && uv run pytest daemon/tests/test_castcast/test_peacock_license_proxy.py -v`
Expected: PASS

- [ ] **Step 5: Commit and push**

```bash
git add daemon/castcast/mediaserver.py daemon/tests/test_castcast/test_peacock_license_proxy.py
git commit -m "feat(peacock): add /peacock/license Widevine proxy handler in mediaserver"
git push origin peacock-research
```

---

### Task 5: URL Detection and Service Dispatch

**Files:**
- Modify: `daemon/castcast/service.py`
- Test: `daemon/tests/test_castcast/test_peacock_service.py`

**Interfaces:**
- Produces: `_cast_peacock(url_or_path: str, title: str = None) -> dict` in `CastService`

- [ ] **Step 1: Write failing test for peacock URL routing**

```python
import pytest
from unittest.mock import MagicMock
from castcast.service import CastService

def test_peacock_url_detection(tmp_path):
    service = CastService(media_root=str(tmp_path))
    service._cast_peacock = MagicMock(return_value={"casting": True, "provider": "peacock"})
    
    res = service.play_media("https://www.peacocktv.com/watch/asset/movies/unbroken/e6fc9411-749e-3be3-8b8a-c652f15b7477")
    service._cast_peacock.assert_called_once()
    assert res["provider"] == "peacock"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/deck/CastCast && uv run pytest daemon/tests/test_castcast/test_peacock_service.py -v`
Expected: FAIL with assertion or method error

- [ ] **Step 3: Implement `_cast_peacock` in `service.py`**

```python
def _cast_peacock(self, url: str, title: str = None) -> dict:
    from .peacock_drm import extract_variant_id, fetch_peacock_manifest
    from .peacock_auth import get_saved_peacock_auth
    
    variant_id = extract_variant_id(url)
    manifest_info = fetch_peacock_manifest(variant_id)
    
    # Store token for license relay
    self.media_server.drm_tokens["peacock_user_token"] = manifest_info["user_token"]
    
    # Build proxied manifest URL
    raw_mpd_url = manifest_info["manifest_url"]
    proxied_mpd_url = self.media_server.get_proxied_url(raw_mpd_url)
    
    license_url = f"{self.media_server.public_url}/peacock/license" if self.media_server.public_url else f"http://{self.media_server.host}:{self.media_server.port}/peacock/license"
    
    self.supervisor.load(
        proxied_mpd_url,
        content_type="application/dash+xml",
        title=title or "Peacock Stream",
        source_path=url,
        license_url=license_url
    )
    return {"casting": True, "url": proxied_mpd_url, "drm": True, "provider": "peacock"}
```

And in `play_media`:
```python
if is_url and ("peacocktv.com" in path_lower or "peacock" in path_lower):
    return self._cast_peacock(clean_path, title=title)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/deck/CastCast && uv run pytest daemon/tests/test_castcast/test_peacock_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit and push**

```bash
git add daemon/castcast/service.py daemon/tests/test_castcast/test_peacock_service.py
git commit -m "feat(peacock): route peacock URLs to _cast_peacock in CastService"
git push origin peacock-research
```

---

### Task 6: Full Integration Testing, Code Review, and Verification

**Files:**
- Modify: `docs/SYNCHRONIZATION_MAP.md` (if updating sync points)
- Run all test suites: daemon unit tests, vitest tests, and linting.

- [ ] **Step 1: Run complete daemon test suite**
Run: `cd /home/deck/CastCast && uv run pytest daemon/tests/`
Expected: All tests pass (201+ tests).

- [ ] **Step 2: Run frontend vitest and build**
Run: `cd /home/deck/CastCast/android/app/src/main/assets/web && npm test -- --run && npm run build`
Expected: 34 tests pass, build succeeds.

- [ ] **Step 3: Dispatch Code Review subagent**
Use `requesting-code-review` skill to dispatch a code review subagent for all changes against `prototype/embedded-android`.
Address any Important/Critical issues found.

- [ ] **Step 4: Commit and push final deliverable**
```bash
git add .
git commit -m "docs: complete peacock research implementation and synchronization"
git push origin peacock-research
```

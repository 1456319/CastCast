# 4K Video Quality Assurance & Diagnostic Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Guarantee 4K video preservation on Chromecast Ultra across all connection states, gate queue transcoding to prevent unintended downscaling, resolve diagnostic log formatting and nested credential redaction, and solidify frontend polling safety.

**Architecture:** Default daemon capability checks to Chromecast Ultra tier (`is_ultra = True`) so 4K HEVC/VP9 files are losslessly remuxed rather than downscaled. Enforce a hard gate in `queue()` blocking automatic video transcoding. Repair log message extraction in `/diagnostics/logs`, implement recursive base64 redaction and `ipaddress`-based SSRF filtering in `mediaserver.py`, and prevent overlapping polling requests in React.

**Tech Stack:** Python 3.13 (CastCast daemon, `urllib`, `ipaddress`, `pytest`), TypeScript / React 18 / Vite.

**Spec:** `docs/superpowers/specs/2026-09-05-4k-quality-and-diagnostic-audit-design.md`

## Global Constraints
- 4K qualifying conditions must remain 100% intact (zero forced downscaling, lossless container remuxing via `-c:v copy` for 4K HEVC/VP9).
- Phone-to-Chromecast connection stability must not be compromised: LAN proxying for Chromecast Shaka Player must remain unauthenticated; public HTTPS tunnel for DRM license proxying must remain functional.
- All files owned by `deck:deck`.
- Synchronization headers must be preserved and validated via `scripts/check_sync_headers.py`.
- Full pytest suite (159+ tests) and Vitest suite (24 tests) must pass.

---

### Task 1: Chromecast Ultra Capability Default & Queue Transcode Gating

**Files:**
- Modify: `daemon/castcast/service.py:445-455,1070-1085`
- Modify: `daemon/castcast/capability.py:307-315`
- Test: `daemon/tests/test_castcast/test_quality_guard.py`

**Interfaces:**
- `service.preflight(path)`: sets `is_ultra = True` by default unless explicitly connected to a legacy non-Ultra model.
- `service.queue(paths)`: skips auto-preparation when `verdict.video_action == "transcode"`.
- `capability.evaluate(info, is_ultra)`: reports `will_be_4k = False` if downscaling or fatal error.

- [ ] **Step 1: Write the failing test for capability default and queue transcode gating**

Create `daemon/tests/test_castcast/test_quality_guard.py`:
```python
import pytest
from unittest.mock import MagicMock
from castcast.probe import MediaInfo, VideoStream
from castcast import capability
from castcast.service import Service

def test_capability_defaults_to_ultra_and_accurate_4k():
    info = MediaInfo(
        path="/videos/test_4k.mkv",
        container="matroska",
        duration=100.0,
        size_bytes=1000000,
        bitrate_kbps=15000,
        video=[VideoStream(index=0, codec="hevc", width=3840, height=2160, fps=24.0, bit_depth=10, profile="Main 10")],
        audio=[],
        subtitles=[]
    )
    # Default is_ultra=True: 4K HEVC in MKV is a lossless remux (copy), preserving 4K
    verdict_ultra = capability.evaluate(info, is_ultra=True)
    assert verdict_ultra.video_action == "copy"
    assert verdict_ultra.will_be_4k is True

    # If is_ultra=False: non-ultra downscales to 1080p, so will_be_4k must be False
    verdict_legacy = capability.evaluate(info, is_ultra=False)
    assert verdict_legacy.video_action == "transcode"
    assert verdict_legacy.will_be_4k is False

def test_service_preflight_defaults_to_ultra():
    service = Service.__new__(Service)
    service.config = {}
    service.work_dir = "/tmp"
    service.supervisor = None
    service.device = None
    service.probe_cached = MagicMock(return_value=MediaInfo(
        path="/videos/test_4k.mkv",
        container="matroska",
        duration=100.0,
        size_bytes=1000000,
        bitrate_kbps=15000,
        video=[VideoStream(index=0, codec="hevc", width=3840, height=2160, fps=24.0, bit_depth=10, profile="Main 10")],
        audio=[],
        subtitles=[]
    ))
    report = service.preflight("/videos/test_4k.mkv")
    assert report["verdict"]["video_action"] == "copy"
    assert report["verdict"]["will_be_4k"] is True

def test_queue_blocks_unauthorized_video_transcode():
    service = Service.__new__(Service)
    service.supervisor = MagicMock()
    service.log = MagicMock()
    service._queued_for_later = set()
    service.prepare = MagicMock()
    
    # Mock preflight returning a file that requires video transcoding
    service.preflight = MagicMock(return_value={
        "prepared_path": None,
        "verdict": {
            "needs_processing": True,
            "video_action": "transcode",
            "issues": []
        },
        "media": {}
    })
    res = service.queue(["/videos/transcode_needed.avi"])
    # Prepare must NOT be called for video transcode in queue
    service.prepare.assert_not_called()
    assert res.get("skipped", 0) >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --project /home/deck/CastCast/daemon pytest daemon/tests/test_castcast/test_quality_guard.py -v`
Expected: FAIL on `service_preflight_defaults_to_ultra` or `queue_blocks_unauthorized_video_transcode`.

- [ ] **Step 3: Implement minimal code changes**

In `daemon/castcast/service.py:preflight()`:
```python
        is_ultra = True
        dev = getattr(self.supervisor, "device", None) or self.device
        if dev:
            model = (getattr(dev, "model", "") or "").lower()
            if model and ("chromecast" in model or "eureka" in model) and "ultra" not in model and "google tv 4k" not in model:
                is_ultra = False
```

In `daemon/castcast/service.py:queue()`:
```python
            if verdict and verdict.get("needs_processing"):
                prepared = report.get("prepared_path")
                if prepared:
                    target = prepared
                    self.log(f"queue: using previously converted file: {os.path.basename(prepared)}")
                elif verdict.get("video_action") == "transcode":
                    self.log(f"queue: skipping {os.path.basename(path)} - video re-encoding requires explicit confirmation", "warn")
                    skipped += 1
                    continue
                else:
                    self.log(f"queue: preparing lossless remux for {os.path.basename(path)}")
                    self._queued_for_later.add(path)
                    self.prepare(path)
                    preparing += 1
                    continue
```

In `daemon/castcast/capability.py:evaluate()`:
```python
    v = info.primary_video
    if not v or not v.is_4k:
        will_be_4k = False
    elif video_action == "transcode" and not is_ultra:
        will_be_4k = False
    elif any(i.code in ("resolution_exceeds_device", "video_codec_unsupported") for i in fatal):
        will_be_4k = False
    else:
        will_be_4k = True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --project /home/deck/CastCast/daemon pytest daemon/tests/test_castcast/test_quality_guard.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add daemon/castcast/service.py daemon/castcast/capability.py daemon/tests/test_castcast/test_quality_guard.py
git commit -m "fix(quality): default to Ultra capability and gate queue video transcoding"
```

---

### Task 2: Diagnostic Message Retrieval in API Logs

**Files:**
- Modify: `daemon/castcast/api.py:145-155`
- Modify: `daemon/tests/test_castcast/test_diagnostics_api.py`

**Interfaces:**
- `GET /diagnostics/logs`: extracts `entry.get("message")` from `LogBuffer` dictionary items.

- [ ] **Step 1: Write failing test in `test_diagnostics_api.py`**

Update `daemon/tests/test_castcast/test_diagnostics_api.py`:
```python
def test_diagnostics_api_real_log_buffer():
    # Verify that actual entries emitted with `message` (from LogBuffer.add) are formatted
    handler = _Handler.__new__(_Handler)
    mock_service = MagicMock()
    mock_service.supervisor = None
    mock_service.log_buffer.recent.return_value = [
        {"seq": 1, "ts": 123456789.0, "level": "info", "message": "media server listening on port 38399"}
    ]
    handler.service = mock_service
    sent_json = []
    handler._json = lambda payload: sent_json.append(payload)
    with patch("os.path.exists", return_value=False):
        handler._handle_diagnostics_logs()
    
    assert len(sent_json) == 1
    assert "[INFO] media server listening on port 38399" in sent_json[0]["logs"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --project /home/deck/CastCast/daemon pytest daemon/tests/test_castcast/test_diagnostics_api.py -v`
Expected: FAIL with message missing from logs string (`[INFO] `).

- [ ] **Step 3: Implement minimal code changes**

In `daemon/castcast/api.py`:
Change line 150:
```python
msg = entry.get("message") or entry.get("msg") or ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --project /home/deck/CastCast/daemon pytest daemon/tests/test_castcast/test_diagnostics_api.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add daemon/castcast/api.py daemon/tests/test_castcast/test_diagnostics_api.py
git commit -m "fix(diagnostics): format message field from LogBuffer in /diagnostics/logs"
```

---

### Task 3: Nested Base64 Credential Redaction & `ipaddress` SSRF Loopback Guard

**Files:**
- Modify: `daemon/castcast/mediaserver.py:66-105,370-390`
- Modify: `daemon/tests/test_castcast/test_redaction.py`
- Modify: `daemon/tests/test_castcast/test_mediaserver_proxy_security.py`

**Interfaces:**
- `redact_sensitive_url(url: str) -> str`: strips credentials from query parameters, userinfo, and recurses into base64 `url=` parameters.
- `_Handler._serve_proxy()`: uses `ipaddress.ip_address` to detect and block loopback addresses (`127.0.0.1`, `127.1`, `::1`, `0.0.0.0`).

- [ ] **Step 1: Write failing tests**

In `daemon/tests/test_castcast/test_redaction.py`:
```python
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
```

In `daemon/tests/test_castcast/test_mediaserver_proxy_security.py`:
Add test for numeric loopback format (`127.1`):
```python
    sent_errors.clear()
    b64_num_loopback = base64.b64encode(b"http://127.1:8765/status").decode("utf-8")
    handler.path = f"/proxy/?url={b64_num_loopback}"
    handler.headers = {"Host": "192.168.1.30:38399"}
    handler._serve_proxy(body=False)
    assert any(code == 403 for code, _ in sent_errors)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --project /home/deck/CastCast/daemon pytest daemon/tests/test_castcast/test_redaction.py daemon/tests/test_castcast/test_mediaserver_proxy_security.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement minimal code changes**

In `daemon/castcast/mediaserver.py`:
```python
import ipaddress

def redact_sensitive_url(url: str) -> str:
    if not url:
        return ""
    try:
        parsed = urllib.parse.urlsplit(url)
        # Redact userinfo
        netloc = parsed.netloc
        if "@" in netloc:
            userinfo, host = netloc.rsplit("@", 1)
            user = userinfo.split(":", 1)[0]
            netloc = f"{user}:[REDACTED]@{host}"
        
        query_dict = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        sensitive_keys = {
            "signature", "sig", "token", "key-pair-id", "expires",
            "x-amz-signature", "x-amz-security-token", "x-amz-credential",
            "api_key", "secret"
        }
        for k in list(query_dict.keys()):
            if k.lower() in sensitive_keys or k.lower().startswith("x-amz-"):
                query_dict[k] = ["[REDACTED]"]
            elif k.lower() == "url":
                # Check for nested base64 url
                val = query_dict[k][0]
                try:
                    decoded = base64.b64decode(val).decode("utf-8")
                    if decoded.startswith("http://") or decoded.startswith("https://"):
                        redacted_inner = redact_sensitive_url(decoded)
                        query_dict[k] = [base64.b64encode(redacted_inner.encode("utf-8")).decode("utf-8")]
                except Exception:
                    pass

        new_query = urllib.parse.urlencode(query_dict, doseq=True)
        return urllib.parse.urlunsplit((parsed.scheme, netloc, parsed.path, new_query, parsed.fragment))
    except Exception:
        return "[REDACTED_URL]"
```

In `daemon/castcast/mediaserver.py:_serve_proxy`:
```python
        target_host = (target_parsed.hostname or "").lower()
        is_loopback = False
        if target_host in ("localhost", "localhost.localdomain"):
            is_loopback = True
        else:
            try:
                ip = ipaddress.ip_address(target_host)
                if ip.is_loopback or ip.is_unspecified:
                    is_loopback = True
            except ValueError:
                pass

        if is_loopback:
            self.send_error(403, "Forbidden: Loopback target not permitted")
            return
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --project /home/deck/CastCast/daemon pytest daemon/tests/test_castcast/test_redaction.py daemon/tests/test_castcast/test_mediaserver_proxy_security.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add daemon/castcast/mediaserver.py daemon/tests/test_castcast/test_redaction.py daemon/tests/test_castcast/test_mediaserver_proxy_security.py
git commit -m "fix(security): nested base64 URL credential redaction and ipaddress SSRF loopback check"
```

---

### Task 4: Frontend Amazon Polling Concurrency & Pointer Event Cleanup

**Files:**
- Modify: `src/app/App.tsx:140-165`
- Modify: `src/app/components/long-press-help.tsx:110-135`

**Interfaces:**
- `App.tsx`: uses `isPollingRef` to prevent concurrent in-flight `/amazon/poll` requests.
- `long-press-help.tsx`: retains coordinates across pointer down and only resets on move/end.

- [ ] **Step 1: Inspect and update pointer handling in `long-press-help.tsx`**

Ensure `startPos.current` is set on pointer down, compared against `MOVE_CANCEL_PX` on move, and cleared on up/cancel.

- [ ] **Step 2: Update `amazonPollRef` in `App.tsx`**

Ensure `amazonPoll` waits for each asynchronous tick before triggering another:
```typescript
      let tries = 0;
      let inFlight = false;
      amazonPollRef.current = window.setInterval(async () => {
        if (inFlight) return;
        tries += 1;
        if (tries > 30) {
          stopAmazonPolling();
          setAmazonStatus("Code expired. Click Link Amazon Account to try again.");
          setAmazonAuthData(null);
          return;
        }
        inFlight = true;
        try {
          if (typeof daemon.amazonPoll === "function") {
            const res = await daemon.amazonPoll(pub, priv);
            if (res?.response?.success || res?.success) {
              stopAmazonPolling();
              setAmazonStatus("Amazon account successfully linked!");
              setAmazonAuthData(null);
            }
          }
        } catch {
          // Poll returns error until user authorizes
        } finally {
          inFlight = false;
        }
      }, 4000);
```

- [ ] **Step 3: Verify TypeScript and Vitest**

Run: `node node_modules/typescript/bin/tsc --noEmit --jsx react-jsx --module esnext --moduleResolution bundler --target es2020 --lib es2020,dom --allowSyntheticDefaultImports --skipLibCheck src/app/App.tsx src/app/lib/daemon.ts`
Run: `npm test`
Expected: 0 TS errors, 24/24 Vitest passing.

- [ ] **Step 4: Commit**

```bash
git add src/app/App.tsx src/app/components/long-press-help.tsx
git commit -m "fix(ui): prevent overlapping Amazon polling and fix pointer move handling in long-press help"
```

---

### Task 5: Full Verification, Dist Sync, & Mandatory Code Review

**Files:**
- Modify: `dist/...` (via build and rsync)

- [ ] **Step 1: Rebuild and Sync `dist/`**

Run: `npm run build`
Sync: `rsync -a --delete --exclude='__pycache__' --exclude='*.pyc' --exclude='.pytest_cache' daemon/ dist/daemon/`
Clean: `find dist -name "__pycache__" -type d -exec rm -rf {} + && find dist -name "*.pyc" -delete && rm -rf dist/daemon/.pytest_cache`
Run: `python3 scripts/check_sync_headers.py`

- [ ] **Step 2: Run complete test suites**

Run: `uv run --project /home/deck/CastCast/daemon pytest daemon/tests`
Run: `npm test`

- [ ] **Step 3: Verify file ownership**

Run: `chown -R deck:deck /home/deck/CastCast`

- [ ] **Step 4: Dispatch Senior Code Reviewer subagent**

Dispatch subagent with diff from `HEAD~4..HEAD` to verify all changes against Chromecast Ultra constraints.
Address all Important and Critical findings.

- [ ] **Step 5: Commit & Final Verification**

Commit any dist updates or review fixes. Confirm working tree clean and ready for user push.

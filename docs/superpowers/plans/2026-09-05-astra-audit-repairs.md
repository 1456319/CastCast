# Astra Audit Recommendations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement repairs and improvements recommended by Astra's audit to fix diagnostics gaps, close the unauthenticated public proxy boundary, prevent preflight crashes, and connect orphan capabilities.

**Architecture:** 
1. Fix local preflight by attaching `CastDevice` identity to `Supervisor`, adding `is_ultra` property, and populating cache during `connect()`.
2. Restrict `/proxy/` to authenticated LAN-only traffic requiring `root_token` and reject public tunnel proxying.
3. Fix the "Maximum Verbosity" log contract by returning both unified `logs` and structured fields, and reading the true Termux `.castcast/audit.log` path.
4. Record all unhandled API exceptions and tracebacks to the daemon `log_buffer` at `error` level.
5. Add sensitive URL/token redaction and audit log rotation.
6. Fix TypeScript definitions for `MediaInfo.subtitles` and hook up `/health` readiness and Amazon device-code pairing in the UI.

**Tech Stack:** Python 3.10+, TypeScript 5+, React, Vite, MPEG-DASH/HLS, CASTv2, pytest, vitest.

**Spec:** Recommendations from Astra's comprehensive codebase audit (conversation log).

## Global Constraints

- Mandatory Code Review: Must use `requesting-code-review` before completing or merging.
- All files created or modified must be owned by `deck:deck`.
- Synchronization map headers (`# synchronization-map:`) must be preserved.
- 4K qualifying conditions must remain 100% intact (zero FFmpeg video transcoding or subtitle burn-in).
- All 153 pytest tests and 24 vitest tests must pass at every step.

---

### Task 1: Fix Local Preflight `AttributeError` & Preserve Device Identity

**Files:**
- Modify: `daemon/castcast/discovery.py:39-53`
- Modify: `daemon/castcast/supervisor.py:129-166`
- Modify: `daemon/castcast/service.py:315-332,432-446`
- Test: `daemon/tests/test_castcast/test_preflight_device.py`

**Interfaces:**
- Consumes: `CastDevice` from `discovery.py`, `Supervisor` from `supervisor.py`.
- Produces: `CastDevice.is_ultra` property; `Supervisor.device` attribute; safe preflight evaluation without `AttributeError`.

- [ ] **Step 1: Write the failing test**

```python
# daemon/tests/test_castcast/test_preflight_device.py
import pytest
from unittest.mock import MagicMock
from castcast.service import CastService
from castcast.discovery import CastDevice
from castcast.supervisor import Supervisor

def test_cast_device_is_ultra_property():
    dev_ultra = CastDevice(name="tv", model="Chromecast Ultra")
    assert dev_ultra.is_ultra is True
    dev_std = CastDevice(name="tv", model="Chromecast")
    assert dev_std.is_ultra is False

def test_preflight_with_supervisor_does_not_raise_attribute_error(tmp_path):
    svc = CastService(work_dir=str(tmp_path), roots=[str(tmp_path)])
    # Simulate an active supervisor
    svc.supervisor = MagicMock(spec=Supervisor)
    svc.device = CastDevice(host="192.168.1.50", model="Chromecast Ultra")
    svc.supervisor.device = svc.device
    
    # Mock probe_cached to return minimal media info
    mock_media = MagicMock()
    mock_media.to_dict.return_value = {"path": "/fake/path.mp4"}
    svc.probe_cached = MagicMock(return_value=mock_media)
    
    # Preflight should not raise AttributeError
    res = svc.preflight("/fake/path.mp4")
    assert "error" in res or "media" in res
    assert res.get("error") != "'Supervisor' object has no attribute 'device'"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=daemon uv run --no-project --no-config --python /usr/bin/python3 --with pytest --with PyYAML python -m pytest daemon/tests/test_castcast/test_preflight_device.py -v`
Expected: FAIL on `AttributeError` or missing `is_ultra` property.

- [ ] **Step 3: Implement device identity preservation and safe preflight**

In `daemon/castcast/discovery.py`:
Add `@property def is_ultra(self) -> bool: return "ultra" in (self.model or "").lower()` on `CastDevice`.

In `daemon/castcast/supervisor.py`:
Add `device: Optional[Any] = None` to `Supervisor.__init__` and store `self.device = device`.

In `daemon/castcast/service.py`:
In `connect()`:
```python
cached_dev = next((d for d in self.cache.all() if d.host == host), None) if self.cache else None
model = cached_dev.model if cached_dev else ""
uuid = cached_dev.uuid if cached_dev else ""
fname = friendly_name or (cached_dev.friendly_name if cached_dev else host)
self.device = CastDevice(host=host, port=port, friendly_name=fname, model=model, uuid=uuid, source=cached_dev.source if cached_dev else "manual")
self.supervisor = Supervisor(host, port, on_event=self._emit, logger=lambda msg, lvl="info": self.log(msg, lvl), on_finished=self.auto_advance, device_auth=bool(self.config.get("device_auth")), device=self.device)
```
In `preflight()`:
```python
is_ultra = False
dev = getattr(self.supervisor, "device", None) or self.device
if dev:
    is_ultra = getattr(dev, "is_ultra", False)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=daemon uv run --no-project --no-config --python /usr/bin/python3 --with pytest --with PyYAML python -m pytest daemon/tests/test_castcast/test_preflight_device.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add daemon/castcast/discovery.py daemon/castcast/supervisor.py daemon/castcast/service.py daemon/tests/test_castcast/test_preflight_device.py
git commit -m "fix(preflight): preserve device identity and resolve Supervisor.device AttributeError"
```

---

### Task 2: Fix "Maximum Verbosity" Discarding Logs & Unify Audit Log Paths

**Files:**
- Modify: `daemon/castcast/api.py:117-141`
- Modify: `src/app/lib/daemon.ts:230-236`
- Test: `daemon/tests/test_castcast/test_diagnostics_api.py`

**Interfaces:**
- Consumes: `svc.log_buffer.recent()`, `/diagnostics/logs` route.
- Produces: API response containing `logs`, `log_buffer`, `audit_log`, `last_error`; `daemon.ts` consumes unified logs.

- [ ] **Step 1: Write the failing test**

```python
# daemon/tests/test_castcast/test_diagnostics_api.py
import json
import pytest
from unittest.mock import MagicMock
from castcast.api import _Handler

def test_diagnostics_logs_returns_logs_field_and_finds_audit_log(tmp_path, monkeypatch):
    audit_file = tmp_path / "audit.log"
    audit_file.write_text("TERMUX_BOOTSTRAP_SUCCESS")
    
    mock_service = MagicMock()
    mock_service.log_buffer.recent.return_value = [{"ts": 100.0, "msg": "Daemon listening", "level": "info"}]
    mock_service.supervisor = None
    
    handler = _Handler.__new__(_Handler)
    handler.service = mock_service
    handler.path = "/diagnostics/logs"
    
    captured = {}
    def mock_json(data, status=200):
        captured["data"] = data
        captured["status"] = status
    handler._json = mock_json
    
    with monkeypatch.context() as m:
        m.setattr("castcast.api.AUDIT_LOG_CANDIDATES", [str(audit_file)])
        handler.do_GET()
        
    assert "logs" in captured["data"]
    assert "log_buffer" in captured["data"]
    assert "audit_log" in captured["data"]
    assert "TERMUX_BOOTSTRAP_SUCCESS" in captured["data"]["audit_log"]
    assert "Daemon listening" in captured["data"]["logs"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=daemon uv run --no-project --no-config --python /usr/bin/python3 --with pytest --with PyYAML python -m pytest daemon/tests/test_castcast/test_diagnostics_api.py -v`
Expected: FAIL because `AUDIT_LOG_CANDIDATES` and `logs` field are missing.

- [ ] **Step 3: Implement unified logs & Termux audit log path resolution**

In `daemon/castcast/api.py`:
Define:
```python
AUDIT_LOG_CANDIDATES = [
    "/storage/emulated/0/Download/CastCast/Chromecast/.castcast/audit.log",
    os.path.expanduser("~/.config/castcast/audit.log"),
    "/tmp/castcast.log",
    "/var/log/audit/audit.log",
]
```
Under `route == "/diagnostics/logs"`:
Read up to 64KB tail from the first existing candidate.
Format `log_buffer` into text lines and combine with `audit_log` into `logs`:
```python
formatted_logs = "\n".join([f"[{entry.get('level', 'info').upper()}] {entry.get('msg', '')}" if isinstance(entry, dict) else str(entry) for entry in recent_logs])
combined_logs = f"=== RECENT DAEMON LOGS ===\n{formatted_logs}\n\n=== AUDIT LOG ===\n{audit_log}"
self._json({
    "logs": combined_logs,
    "log_buffer": recent_logs,
    "last_error": last_error,
    "audit_log": audit_log,
})
```
In `src/app/lib/daemon.ts`:
Update `getDiagnosticsLogs`:
```ts
getDiagnosticsLogs: async () => {
  const res = await fetch(`${DAEMON_BASE}/diagnostics/logs`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  const data = await res.json();
  const logsText = data.logs || (Array.isArray(data.log_buffer) 
    ? data.log_buffer.map((l: any) => typeof l === "string" ? l : `[${l.level || "info"}] ${l.msg || ""}`).join("\n")
    : "") + (data.audit_log ? `\n\n=== AUDIT LOG ===\n${data.audit_log}` : "");
  return `LAST ERROR:\n${data.last_error || "None"}\n\nLOGS:\n${logsText}`;
},
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=daemon uv run --no-project --no-config --python /usr/bin/python3 --with pytest --with PyYAML python -m pytest daemon/tests/test_castcast/test_diagnostics_api.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add daemon/castcast/api.py src/app/lib/daemon.ts daemon/tests/test_castcast/test_diagnostics_api.py
git commit -m "fix(diagnostics): provide unified logs field and read Termux audit.log in /diagnostics/logs"
```

---

### Task 3: Capture API Failures and Tracebacks in Daemon Logs

**Files:**
- Modify: `daemon/castcast/api.py:155-156,314-315`
- Test: `daemon/tests/test_castcast/test_api_error_logging.py`

**Interfaces:**
- Consumes: `svc.log(...)` from `service.py`.
- Produces: Logged errors and stack traces in daemon log buffer for HTTP 500 responses.

- [ ] **Step 1: Write the failing test**

```python
# daemon/tests/test_castcast/test_api_error_logging.py
import pytest
from unittest.mock import MagicMock
from castcast.api import _Handler

def test_api_unhandled_exception_logs_traceback():
    mock_service = MagicMock()
    mock_service.connect.side_effect = RuntimeError("Simulated failure in connect")
    
    handler = _Handler.__new__(_Handler)
    handler.service = mock_service
    handler.path = "/connect"
    handler._body = lambda: {"host": "192.168.1.10"}
    
    captured = {}
    handler._json = lambda d, s=200: captured.update({"data": d, "status": s})
    
    handler.do_POST()
    
    assert captured["status"] == 500 or captured["status"] == 409
    assert any(
        "Simulated failure in connect" in str(call.args[0])
        for call in mock_service.log.call_args_list
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=daemon uv run --no-project --no-config --python /usr/bin/python3 --with pytest --with PyYAML python -m pytest daemon/tests/test_castcast/test_api_error_logging.py -v`
Expected: FAIL because exceptions are currently not logged to `mock_service.log`.

- [ ] **Step 3: Implement traceback logging in `api.py`**

In `daemon/castcast/api.py`:
In `do_GET`:
```python
        except Exception as exc:  # noqa: BLE001
            tb = traceback.format_exc()
            self.service.log(f"[api] Error during GET {route}: {exc}\n{tb}", "error")
            self._json({"error": str(exc)}, 500)
```
In `do_POST`:
```python
        except RuntimeError as exc:
            self.service.log(f"[api] Conflict during POST {route}: {exc}", "warn")
            self._json({"error": str(exc)}, 409)
        except Exception as exc:  # noqa: BLE001
            tb = traceback.format_exc()
            self.service.log(f"[api] Error during POST {route}: {exc}\n{tb}", "error")
            self._json({"error": str(exc)}, 500)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=daemon uv run --no-project --no-config --python /usr/bin/python3 --with pytest --with PyYAML python -m pytest daemon/tests/test_castcast/test_api_error_logging.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add daemon/castcast/api.py daemon/tests/test_castcast/test_api_error_logging.py
git commit -m "fix(api): record unhandled exceptions and tracebacks to service log buffer"
```

---

### Task 4: Restrict Public Proxy Boundary and Check Media Access Token

**Files:**
- Modify: `daemon/castcast/mediaserver.py:314-365`
- Modify: `daemon/castcast/service.py:748,986,1931`
- Test: `daemon/tests/test_castcast/test_mediaserver_proxy_security.py`

**Interfaces:**
- Consumes: `server.root_token`, `server.public_url`, `server.lan_ip`.
- Produces: Protected `/proxy/` requiring authentication, rejecting unauthorized public tunnel proxying.

- [ ] **Step 1: Write the failing test**

```python
# daemon/tests/test_castcast/test_mediaserver_proxy_security.py
import pytest
import base64
import urllib.parse
from unittest.mock import MagicMock
from castcast.mediaserver import _Handler

def test_proxy_requires_valid_token_or_prefix():
    handler = _Handler.__new__(_Handler)
    mock_server = MagicMock()
    mock_server.media_server.root_token = "secret123"
    mock_server.media_server.public_url = "https://tunnel.lhr.life"
    mock_server.media_server.lan_ip = "192.168.1.30"
    handler.server = mock_server
    
    # Request without token
    b64 = base64.b64encode(b"http://example.com/video.mp4").decode("utf-8")
    handler.path = f"/proxy/?url={b64}"
    handler.headers = {"Host": "192.168.1.30:38399"}
    
    sent_errors = []
    handler.send_error = lambda code, msg="": sent_errors.append((code, msg))
    handler._serve_proxy(body=False)
    assert any(code == 403 for code, _ in sent_errors)
    
    # Request coming via public tunnel must be rejected
    sent_errors.clear()
    handler.path = f"/secret123/proxy/?url={b64}"
    handler.headers = {"Host": "tunnel.lhr.life"}
    handler._serve_proxy(body=False)
    assert any(code == 403 for code, _ in sent_errors)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=daemon uv run --no-project --no-config --python /usr/bin/python3 --with pytest --with PyYAML python -m pytest daemon/tests/test_castcast/test_mediaserver_proxy_security.py -v`
Expected: FAIL because `/proxy/` currently does not enforce token or tunnel restrictions.

- [ ] **Step 3: Implement proxy security controls**

In `daemon/castcast/mediaserver.py`:
1. In `do_HEAD` and `do_GET`, route proxy requests if `self.path.startswith("/proxy/")` or `self.path.startswith(f"/{server.root_token}/proxy/")`.
2. In `_serve_proxy`:
   - Inspect `Host` header: if `server.public_url` is set and `server.public_url`'s hostname matches `Host` (or Host contains `lhr.life`), reject with `403 Forbidden: Public proxying not permitted`.
   - Inspect token: path must start with `/{server.root_token}/proxy/` OR query must contain `token={server.root_token}`. If token does not match, reject with `403 Forbidden: Invalid media access token`.
   - Validate scheme of decoded `target_url`: must be `http` or `https`.
   - Update HLS manifest rewriting: ensure rewritten segment URLs use `http://{server.lan_ip}:{server.port}/{server.root_token}/proxy/?url={encoded}`.
3. In `daemon/castcast/service.py`:
   - Update proxy URL construction at lines 748, 986, 1931 to use `http://{self.media_server.lan_ip}:{self.media_server.port}/{self.media_server.root_token}/proxy/?url={encoded}`.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=daemon uv run --no-project --no-config --python /usr/bin/python3 --with pytest --with PyYAML python -m pytest daemon/tests/test_castcast/test_mediaserver_proxy_security.py -v`
Expected: PASS.

- [ ] **Step 5: Run existing tests to ensure no regressions**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=daemon uv run --no-project --no-config --python /usr/bin/python3 --with pytest --with PyYAML python -m pytest daemon/tests -q -p no:cacheprovider`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add daemon/castcast/mediaserver.py daemon/castcast/service.py daemon/tests/test_castcast/test_mediaserver_proxy_security.py
git commit -m "fix(security): restrict /proxy/ to authenticated local requests and block public tunnel proxying"
```

---

### Task 5: Sensitive URL & Header Redaction and Log Retention

**Files:**
- Modify: `daemon/castcast/mediaserver.py:58-65,445`
- Modify: `daemon/castcast/service.py:120-130`
- Modify: `daemon/termux_bootstrap.sh:22-30`
- Test: `daemon/tests/test_castcast/test_redaction.py`

**Interfaces:**
- Consumes: URLs and log messages.
- Produces: Sanitized log output stripped of signed query parameters (`Signature`, `token`, `Expires`, `Key-Pair-Id`, `AWSAccessKeyId`).

- [ ] **Step 1: Write the failing test**

```python
# daemon/tests/test_castcast/test_redaction.py
from castcast.mediaserver import redact_sensitive_url

def test_redact_sensitive_url():
    url = "https://cdn.amazon.com/video.mpd?Expires=1700000000&Signature=abc123secret&Key-Pair-Id=APK123&token=supersecret"
    sanitized = redact_sensitive_url(url)
    assert "abc123secret" not in sanitized
    assert "supersecret" not in sanitized
    assert "Expires=" in sanitized
    assert "[REDACTED]" in sanitized
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=daemon uv run --no-project --no-config --python /usr/bin/python3 --with pytest --with PyYAML python -m pytest daemon/tests/test_castcast/test_redaction.py -v`
Expected: FAIL because `redact_sensitive_url` does not exist.

- [ ] **Step 3: Implement URL redaction and audit log rotation**

In `daemon/castcast/mediaserver.py`:
Implement `redact_sensitive_url(url: str) -> str`:
```python
def redact_sensitive_url(url: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(url)
        qs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        sensitive_keys = {"token", "signature", "key-pair-id", "sessiontoken", "awsaccesskeyid", "policy", "auth"}
        redacted_qs = []
        for k, v in qs:
            if k.lower() in sensitive_keys:
                redacted_qs.append((k, "[REDACTED]"))
            else:
                redacted_qs.append((k, v))
        new_query = urllib.parse.urlencode(redacted_qs)
        return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, new_query, parsed.fragment))
    except Exception:
        return "[URL]"
```
Use `redact_sensitive_url` before logging URLs in `mediaserver.py` and `service.py`.

In `daemon/termux_bootstrap.sh`:
Before writing to `$AUDIT_LOG`:
```bash
if [ -f "$AUDIT_LOG" ] && [ $(wc -c < "$AUDIT_LOG") -gt 2097152 ]; then
    mv -f "$AUDIT_LOG" "$AUDIT_LOG.1"
fi
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=daemon uv run --no-project --no-config --python /usr/bin/python3 --with pytest --with PyYAML python -m pytest daemon/tests/test_castcast/test_redaction.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add daemon/castcast/mediaserver.py daemon/castcast/service.py daemon/termux_bootstrap.sh daemon/tests/test_castcast/test_redaction.py
git commit -m "fix(logging): redact sensitive credentials in logged URLs and rotate audit log"
```

---

### Task 6: Fix TypeScript Compilation Error (`MediaInfo.subtitles`) & Hook Up Readiness Dashboard and Amazon Device Auth

**Files:**
- Modify: `src/app/lib/daemon.ts`
- Modify: `src/app/components/preflight-panel.tsx`
- Modify: `src/app/App.tsx`
- Create: `src/app/components/long-press-help.tsx`
- Test: Vitest suites + TypeScript compilation

**Interfaces:**
- Consumes: `daemon.health()`, `daemon.amazonAuth()`, `daemon.amazonPoll()`, `daemon.injectAmazon()`, `daemon.removeAmazonQueue()`.
- Produces: Type-safe build with zero TypeScript errors, System Readiness Dashboard, and interactive Amazon device-code pairing.

- [ ] **Step 1: Check baseline TypeScript error**

Run: `node /home/deck/CastCast/node_modules/typescript/bin/tsc --noEmit --jsx react-jsx --module esnext --moduleResolution bundler --target es2020 --lib es2020,dom --allowSyntheticDefaultImports --skipLibCheck /home/deck/CastCast/src/app/App.tsx /home/deck/CastCast/src/app/lib/daemon.ts`
Expected: TS2339 on `Property 'subtitles' does not exist on type 'MediaInfo'`.

- [ ] **Step 2: Add SubtitleStream to `daemon.ts`**

In `src/app/lib/daemon.ts`:
Add:
```ts
export interface SubtitleStream {
  index: number;
  codec: string;
  language: string;
  title: string;
  forced: boolean;
  default: boolean;
}
```
Update `MediaInfo`:
```ts
export interface MediaInfo {
  path: string;
  container: string;
  format_long: string;
  duration_s: number;
  size_bytes: number;
  bitrate_kbps: number | null;
  video: VideoStream[];
  audio: AudioStream[];
  subtitles: SubtitleStream[];
  is_4k: boolean;
}
```
Add typed API helpers:
```ts
export interface HealthCheck {
  key: string;
  label: string;
  ok: boolean | null;
  detail: string;
  remedy: string;
  blocking: boolean;
}

export interface HealthReport {
  ready: boolean;
  version: string;
  python: string;
  serve_command: string;
  checks: HealthCheck[];
  blocking: HealthCheck[];
}

export interface CastOptions {
  licenseUrl?: string | null;
  offlineDrmToken?: string | null;
  autoPrepare?: boolean;
}
```
Add methods: `health()`, `amazonAuth()`, `amazonPoll()`, `injectAmazon()`, `removeAmazonQueue()`.
Remove phantom `reorderLibrary`.

- [ ] **Step 3: Port `long-press-help.tsx` and wire Readiness Dashboard & Amazon Device Auth in `App.tsx`**

- Create `src/app/components/long-press-help.tsx` from scratch directory.
- In `App.tsx`:
  - Integrate `LongPressHelpProvider`.
  - Add collapsible System Readiness Dashboard card driven by `daemon.health()`.
  - Add Amazon Device-Code linking modal driven by `amazonAuth` / `amazonPoll` with code display and copyable link to `amazon.com/code`.
  - Use `removeAmazonQueue` for Amazon queue deletion.
  - Wrap controls in `<Explain text="...">`.

- [ ] **Step 4: Run TypeScript check and frontend tests**

Run:
`node /home/deck/CastCast/node_modules/typescript/bin/tsc --noEmit --jsx react-jsx --module esnext --moduleResolution bundler --target es2020 --lib es2020,dom --allowSyntheticDefaultImports --skipLibCheck /home/deck/CastCast/src/app/App.tsx /home/deck/CastCast/src/app/lib/daemon.ts`
`npm test -- --reporter=dot`
Expected: PASS with 0 errors.

- [ ] **Step 5: Commit**

```bash
git add src/app/lib/daemon.ts src/app/components/preflight-panel.tsx src/app/App.tsx src/app/components/long-press-help.tsx
git commit -m "feat(ui): add readiness dashboard, amazon device-code pairing, long-press help, and fix MediaInfo subtitle types"
```

---

### Task 7: Full Verification & Code Review

- [ ] **Step 1: Run all Python tests with uv**
Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=daemon uv run --no-project --no-config --python /usr/bin/python3 --with pytest --with PyYAML python -m pytest daemon/tests -q -p no:cacheprovider`
Expected: 157+ passed.

- [ ] **Step 2: Run all Vitest frontend tests**
Run: `npm test`
Expected: 24 passed.

- [ ] **Step 3: Run synchronization header check**
Run: `PYTHONDONTWRITEBYTECODE=1 uv run --offline --no-project --no-config --python /usr/bin/python3 --with PyYAML python scripts/check_sync_headers.py`
Expected: PASS.

- [ ] **Step 4: Run production Vite build**
Run: `node node_modules/vite/bin/vite.js build`
Expected: PASS.

- [ ] **Step 5: Ensure file ownership**
Run: `chown -R deck:deck /home/deck/CastCast`

- [ ] **Step 6: Dispatch Code Review Subagent**
Use `requesting-code-review` skill to review git diff.
Address any Critical or Important feedback before marking done.

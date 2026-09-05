# 4K Video Quality Assurance & Diagnostic Audit Design

## 1. Context & Motivation
Following the codebase audit by Astra and an evaluation through the lens of the Chromecast Ultra's capabilities and strict streaming protocols:
1. CastCast is purpose-built for the **Chromecast Ultra**. The core value proposition of the app is uncompromising 4K HDR playback and rock-solid phone-to-Chromecast connection stability.
2. A previous defect in `service.py:preflight()` defaulted `is_ultra = False` whenever a device was newly connecting, manual, or uncached. This caused `capability.py` and `remux.py` to evaluate files against a legacy 1080p Chromecast (Gen 1/2/3) profile, building a lossy 1080p transcode plan (`-c:v libx264 -vf scale=-2:1080`) for 4K HEVC media.
3. In `service.py:queue()`, any item needing processing was unconditionally sent to `prepare()`, which would execute that 1080p transcode automatically in the background without user confirmation.
4. Several diagnostic and operational bugs were identified:
   - `api.py` formats `entry.get("msg")` instead of `entry.get("message")`, rendering blank log lines in the Maximum Verbosity diagnostic modal.
   - `mediaserver.py:redact_sensitive_url` masks top-level query parameters but leaks secrets nested inside base64 `?url=` parameters.
   - Loopback protection on `/proxy/` checked literal string matches rather than standard IP parsing.
   - `amazonPoll` in `App.tsx` fired overlapping asynchronous requests on interval without awaiting response resolution.
   - `long-press-help.tsx` pointer event coordinates were reset prematurely on pointer-down.

## 2. Goals & Non-Goals
### Goals
- **Guarantee 4K Preservation:** Ensure 4K HEVC and VP9 files are never converted to 1080p under any device connection state (disconnected, uncached, or connected).
- **Default to Chromecast Ultra:** Treat all connections as Chromecast Ultra tier (`is_ultra = True`) by default, only stepping down if hardware explicitly identifies itself as legacy non-Ultra.
- **Strict Queue Policy:** Auto-preparation in the queue may only execute lossless container remuxes (`video_action == "copy"`). Video transcodes (`video_action == "transcode"`) are strictly blocked from auto-preparing in the queue.
- **Accurate Preflight Verdicts:** Ensure `verdict.will_be_4k` accurately reports whether the output stream will be 4K.
- **Accurate Log Export:** Fix `api.py` to correctly extract `entry["message"]` and format all daemon logs for Maximum Verbosity.
- **Comprehensive Redaction:** Recursively redact credentials inside base64-encoded proxy URLs and URL auth components.
- **Safe Loopback SSRF Guard:** Use Python's `ipaddress` module to robustly detect loopback destinations on `/proxy/` without breaking LAN streaming to Chromecast.
- **Frontend Safety:** Ensure `amazonPoll` requests cannot overlap, and resolve pointer coordinate handling in `long-press-help.tsx`.

### Non-Goals
- **Do NOT alter Shaka Player LAN proxying:** Do not require authentication headers on local LAN `/proxy/` requests. Chromecast Shaka Player cannot send custom headers on relative manifest chunk fetches.
- **Do NOT eliminate the HTTPS tunnel for DRM:** The HTTPS tunnel is strictly necessary for Chromecast Widevine DRM license acquisition due to Chrome mixed-content security policies. Redesigning this architecture is earmarked for dedicated multi-agent brainstorming.

---

## 3. Detailed Technical Design

### Section 3.1: Chromecast Ultra Capability & 4K Guarantee
#### 3.1.1 Default Device Capability in `service.py`
In `daemon/castcast/service.py:preflight()`:
```python
is_ultra = True  # Default to Chromecast Ultra tier
dev = getattr(self.supervisor, "device", None) or self.device
if dev:
    # Only treat as non-ultra if the device explicitly identifies as a legacy model
    model = (getattr(dev, "model", "") or "").lower()
    if model and ("chromecast" in model or "eureka" in model) and "ultra" not in model and "google tv 4k" not in model:
        is_ultra = False
```
This guarantees that whenever a device is unconnected, manual IP, or uncached, the daemon defaults to 4K Ultra capabilities.

#### 3.1.2 Queue Transcode Gating in `service.py`
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
This prevents any silent or accidental 4K -> 1080p transcode in batch queue jobs.

#### 3.1.3 Accurate 4K Reporting in `capability.py`
In `daemon/castcast/capability.py:evaluate()`:
Update `will_be_4k` calculation:
```python
v = info.primary_video
if not v or not v.is_4k:
    will_be_4k = False
elif video_action == "transcode" and not is_ultra:
    # Non-ultra devices will downscale to 1080p
    will_be_4k = False
elif any(i.code in ("resolution_exceeds_device", "video_codec_unsupported") for i in fatal):
    will_be_4k = False
else:
    will_be_4k = True
```

---

### Section 3.2: Diagnostic Logging & Redaction Fixes
#### 3.2.1 Diagnostic Message Retrieval in `api.py`
In `daemon/castcast/api.py`:
In the `/diagnostics/logs` handler:
```python
msg = entry.get("message") or entry.get("msg") or ""
```
Ensure all entries from `LogBuffer` (which stores `{"message": ...}`) are properly extracted and rendered.

#### 3.2.2 Nested Base64 and Credential Redaction in `mediaserver.py`
In `daemon/castcast/mediaserver.py`:
Update `redact_sensitive_url(url: str) -> str`:
1. Strip inline userinfo (`http://user:pass@host/...` -> `http://user:[REDACTED]@host/...`).
2. Redact sensitive query parameters: `Signature`, `token`, `Key-Pair-Id`, `Expires`, `x-amz-*`, `api_key`, `secret`.
3. If the URL contains a `url=` query parameter (e.g. `/proxy/?url=...`):
   - Attempt to base64-decode the parameter value.
   - If decoded into a valid URL, recursively apply `redact_sensitive_url`.
   - Re-encode the redacted target and replace the `url=` parameter value.

#### 3.2.3 Robust Loopback IP Validation on `/proxy/`
In `daemon/castcast/mediaserver.py:_serve_proxy`:
```python
import ipaddress

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
This cleanly handles standard IPv4 loopback (`127.0.0.1`), IPv6 loopback (`::1`), compact notation (`127.1`), and unspecified addresses (`0.0.0.0`) without affecting LAN addresses (`192.168.x.x`, `10.x.x.x`, etc.).

---

### Section 3.3: Frontend & Runtime Improvements
#### 3.3.1 In-Flight Polling Safety in `App.tsx`
In `src/app/App.tsx:startAmazonLink`:
Track in-flight state with `isPollingRef` so that a slow response doesn't cause overlapping requests.

#### 3.3.2 Pointer Coordinate Initialization in `long-press-help.tsx`
In `src/app/components/long-press-help.tsx`:
Ensure pointer starting coordinates are retained during the press gesture and only cleared on gesture completion or cancellation.

---

## 4. Verification & Testing Strategy
1. **Capability & Preflight Unit Tests:**
   - Verify `preflight()` on an uncached device defaults `is_ultra = True`.
   - Verify 4K HEVC files produce a lossless remux plan (`-c:v copy`), NOT a 1080p transcode plan.
   - Verify `queue()` refuses to auto-prepare files when `video_action == "transcode"`.
   - Verify `verdict.will_be_4k` returns `False` when downscaling.
2. **Diagnostic & Redaction Unit Tests:**
   - Verify `/diagnostics/logs` formats `message` from real `LogBuffer` instances without empty lines.
   - Verify `redact_sensitive_url` redacts parameters inside nested base64 proxy URLs.
   - Verify `/proxy/` rejects `http://127.1:8765` and `http://127.0.0.1:8765` with 403, while permitting external and LAN URLs.
3. **Full Regression Suite:**
   - All 159+ Python tests pass.
   - All 24+ Vitest tests pass.
   - TypeScript compilation passes with 0 errors.
   - Sync headers pass.
   - Mandatory code review subagent validation.

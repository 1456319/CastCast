# Chromecast Ultra Protocol Audit Reconciliation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cleanly integrate verified Chromecast Ultra protocol framing, receiver routing, atomic remuxing, cache validation, and distribution packaging improvements from the Astra audit into `main`, while strictly preventing regressions in adaptive streaming, DASH/HLS segmenting, subtitle reloading, and Android background execution.

**Architecture:** Implement modular improvements across the Cast socket layer, media server path resolution, remuxing pipeline, and Android bridge. Every task is built with test-driven development (TDD) and verified with an independent task reviewer before moving to the next.

**Tech Stack:** Python 3.13, TypeScript / React, Vite, Android / Termux, Google Cast CAF Protocol, FFmpeg.

**Spec:** `docs/superpowers/specs/2026-09-06-ultra-protocol-audit-reconciliation-design.md`

## Global Constraints

- 4K qualifying conditions must remain 100% intact: zero forced local downscaling to 1080p on 4K sources.
- No runtime playback sabotage: Adaptive Bitrate (ABR) streaming must not be paused by the sender when starting below 4K, and 1080p/HD Amazon titles must be accepted.
- Phone-to-Chromecast connection stability must be preserved: LAN proxying for Chromecast Shaka Player must remain unauthenticated; public HTTPS tunnel for DRM license proxying must remain functional.
- All files owned by `deck:deck`.
- Synchronization headers must be preserved and validated via `scripts/check_sync_headers.py`.
- Full pytest suite and Vitest suite must pass cleanly.

---

### Task 1: Protocol Socket Buffering & Receiver Routing

**Files:**
- Modify: `daemon/castcast/channel.py`
- Modify: `daemon/castcast/supervisor.py`
- Test: `daemon/tests/test_castcast/test_channel.py`

**Interfaces:**
- Produces: `CastChannel.receive(timeout)` with persistent `_receive_buffer` (bytearray).
- Produces: `DEFAULT_MEDIA_RECEIVER_APP_ID = "CC1AD845"` and `SHAKA_RECEIVER_APP_ID = "07AEE832"`.
- Produces: `Supervisor.replace_text_tracks()` and subtitle reloading that works for Shaka without throwing errors.

- [ ] **Step 1: Write the failing tests for channel socket buffering and frame limit**

```python
# In daemon/tests/test_castcast/test_channel.py
def test_partial_cast_frame_survives_socket_timeout():
    original = CastMessage("receiver-0", "sender-0", NS_MEDIA, '{"type":"MEDIA_STATUS","status":[]}')
    body = original.encode()
    wire = struct.pack("!I", len(body)) + body
    
    class FragmentedSocket:
        def __init__(self):
            self.data = [wire[:2], socket.timeout(), wire[2:9], socket.timeout(), wire[9:]]
        def settimeout(self, timeout): pass
        def recv(self, count):
            chunk = self.data.pop(0)
            if isinstance(chunk, Exception):
                raise chunk
            if len(chunk) > count:
                self.data.insert(0, chunk[count:])
            return chunk[:count]
            
    channel = CastChannel("unused")
    channel._sock = FragmentedSocket()
    with pytest.raises(socket.timeout):
        channel.receive(0.1)
    with pytest.raises(socket.timeout):
        channel.receive(0.1)
    msg = channel.receive(0.1)
    assert msg.namespace == NS_MEDIA
    assert msg.payload_utf8 == original.payload_utf8

def test_outbound_frame_exceeding_max_len_raises():
    channel = CastChannel("unused")
    channel._sock = MagicMock()
    oversized = CastMessage("receiver-0", "sender-0", NS_MEDIA, "x" * 70000)
    with pytest.raises(ChannelClosed, match="exceeds 64 KiB"):
        channel.send(oversized)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --project daemon pytest daemon/tests/test_castcast/test_channel.py -k "test_partial_cast_frame"`
Expected: FAIL (`FragmentedSocket` has no `_receive_buffer` in `CastChannel`).

- [ ] **Step 3: Implement persistent socket buffer and receiver App IDs**

Update `daemon/castcast/channel.py`:
```python
DEFAULT_MEDIA_RECEIVER_APP_ID = "CC1AD845"
SHAKA_RECEIVER_APP_ID = "07AEE832"

class CastChannel:
    def __init__(self, host: str, port: int = CAST_PORT, connect_timeout: float = 10.0):
        ...
        self._receive_buffer = bytearray()

    def close(self) -> None:
        sock, self._sock = self._sock, None
        self._receive_buffer.clear()
        ...

    def receive(self, timeout: float) -> CastMessage:
        sock = self._sock
        if sock is None:
            raise ChannelClosed("not connected")
        deadline = time.monotonic() + max(timeout, 0.05)
        while True:
            buffered = self._receive_buffer
            if len(buffered) >= 4:
                size = struct.unpack(">I", buffered[:4])[0]
                if not 0 < size <= PACKET_MAX_LEN:
                    raise ChannelClosed(f"invalid Cast frame length: {size}")
                if len(buffered) >= size + 4:
                    packet = bytes(buffered[4:size + 4])
                    del buffered[:size + 4]
                    return CastMessage.decode(packet)
                needed = size + 4 - len(buffered)
            else:
                needed = 4 - len(buffered)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise socket.timeout()
            sock.settimeout(remaining)
            try:
                chunk = sock.recv(needed)
            except ssl.SSLWantReadError as exc:
                raise socket.timeout() from exc
            if not chunk:
                raise ChannelClosed("peer closed the connection")
            buffered.extend(chunk)

    def send(self, message: CastMessage) -> None:
        sock = self._sock
        if sock is None:
            raise ChannelClosed("not connected")
        body = message.encode()
        if len(body) > PACKET_MAX_LEN:
            raise ChannelClosed("outbound Cast message exceeds 64 KiB; reduce the queue size")
        frame = struct.pack(">I", len(body)) + body
        with self._send_lock:
            sock.sendall(frame)
```

In `daemon/castcast/supervisor.py`:
- Use `DEFAULT_MEDIA_RECEIVER_APP_ID = "CC1AD845"` for Default Media Receiver, reserving `SHAKA_RECEIVER_APP_ID = "07AEE832"` for Widevine.
- In `replace_text_tracks()`, if the active session is Shaka (`receiver_app_id == SHAKA_RECEIVER_APP_ID`), perform a reload of the stream preserving position, pause state, tracks, and license URL, without raising a `RuntimeError`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --project daemon pytest daemon/tests/test_castcast/test_channel.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add daemon/castcast/channel.py daemon/castcast/supervisor.py daemon/tests/test_castcast/test_channel.py
git commit -m "fix(channel): add persistent socket frame buffering and separate receiver IDs"
```

---

### Task 2: MediaServer Canonical Path Resolution & Segmented DASH/HLS Streaming

**Files:**
- Modify: `daemon/castcast/mediaserver.py`
- Test: `daemon/tests/test_castcast/test_mediaserver.py`

**Interfaces:**
- Produces: `MediaServer._resolve()` with safe canonical `os.path.realpath` containment within `server.roots`.
- Produces: Dedicated loopback `_LicenseHandler` listening on `127.0.0.1` for SSH tunnel Widevine licensing.

- [ ] **Step 1: Write the failing test for relative DASH segment resolution**

```python
# In daemon/tests/test_castcast/test_mediaserver.py
def test_resolve_permits_relative_segments_within_root(tmp_path):
    root = tmp_path / "media"
    movie_dir = root / "movie"
    audio_dir = root / "audio"
    movie_dir.mkdir(parents=True)
    audio_dir.mkdir(parents=True)
    seg = audio_dir / "segment_001.m4s"
    seg.write_bytes(b"segment-data")

    server = MediaServer([str(root)])
    # Requesting ../audio/segment_001.m4s relative to /movie/
    handler = _Handler.__new__(_Handler)
    handler.server = MagicMock()
    handler.server.media_server = server
    handler.path = f"/{server.root_token}/movie/../audio/segment_001.m4s"

    resolved = handler._resolve()
    assert resolved == str(seg.resolve())

def test_resolve_blocks_path_traversal_outside_root(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("classified")

    server = MediaServer([str(root)])
    handler = _Handler.__new__(_Handler)
    handler.server = MagicMock()
    handler.server.media_server = server
    handler.path = f"/{server.root_token}/../../secret.txt"

    assert handler._resolve() is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --project daemon pytest daemon/tests/test_castcast/test_mediaserver.py -k "test_resolve_permits_relative_segments"`
Expected: FAIL if current code does not normalize relative segments properly.

- [ ] **Step 3: Implement canonical root-contained path resolution & license listener**

Update `daemon/castcast/mediaserver.py`:
```python
    def _resolve(self) -> Optional[str]:
        server: "MediaServer" = self.server.media_server
        path = urllib.parse.urlsplit(self.path).path
        prefix = f"/{server.root_token}/"
        if not path.startswith(prefix):
            return None

        rel = urllib.parse.unquote(path[len(prefix):])
        rel = posixpath.normpath(rel).lstrip("/")
        
        for root in server.roots:
            real_root = os.path.realpath(root)
            candidate = os.path.realpath(os.path.join(root, rel))
            if candidate == real_root or candidate.startswith(real_root + os.sep):
                if os.path.isfile(candidate):
                    return candidate
        return None
```
Ensure `_LicenseHandler` serves POST requests at `/amazon/license` and `/drm/` on `127.0.0.1` and binds the SSH reverse tunnel port exclusively to the license handler.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --project daemon pytest daemon/tests/test_castcast/test_mediaserver.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add daemon/castcast/mediaserver.py daemon/tests/test_castcast/test_mediaserver.py
git commit -m "fix(mediaserver): allow canonical relative segments and isolate DRM license listener"
```

---

### Task 3: Atomic Remux Output, Stderr Draining & HDR Normalization

**Files:**
- Modify: `daemon/castcast/remux.py`
- Modify: `daemon/castcast/probe.py`
- Test: `daemon/tests/test_remux.py`

**Interfaces:**
- Produces: `Remuxer.run()` creating `.partial` files and atomically publishing via `os.replace`.
- Produces: Concurrent stderr reader thread in `Remuxer`.
- Produces: Normalized color transfer comparison in `probe.py`/`remux.py`.

- [ ] **Step 1: Write the failing tests for atomic partial output and HDR normalization**

```python
# In daemon/tests/test_remux.py
def test_remux_creates_partial_output_and_publishes_atomically(tmp_path):
    # Verify .partial is used during encoding and replaced on completion
    ...

def test_hdr_color_transfer_normalization():
    from castcast.probe import _normalize_color_transfer
    assert _normalize_color_transfer("smpte2084") == "smpte2084"
    assert _normalize_color_transfer("arib-std-b67") == "arib-std-b67"
    assert _normalize_color_transfer("bt2020-10") == "bt2020-10"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --project daemon pytest daemon/tests/test_remux.py -k "test_hdr_color_transfer_normalization"`
Expected: FAIL (`_normalize_color_transfer` not defined).

- [ ] **Step 3: Implement atomic remuxing, stderr draining & HDR normalization**

In `daemon/castcast/probe.py`:
```python
def normalize_color_transfer(trc: Optional[str]) -> str:
    if not trc:
        return ""
    val = trc.strip().lower()
    mapping = {
        "smpte2084": "smpte2084",
        "smpte-2084": "smpte2084",
        "arib-std-b67": "arib-std-b67",
        "hlg": "arib-std-b67",
    }
    return mapping.get(val, val)
```

In `daemon/castcast/remux.py`:
- Use `temporary_output = f"{stem}.partial{extension}"` for FFmpeg output.
- Spawn a background `drain_stderr()` thread to drain `proc.stderr` continuously.
- On success, check `normalize_color_transfer(verified.color_transfer) == normalize_color_transfer(plan.expected_color_transfer)`.
- Use `os.replace(temporary_output, plan.output_path)`.
- Unlink `temporary_output` on cancel or failure.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --project daemon pytest daemon/tests/test_remux.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add daemon/castcast/remux.py daemon/castcast/probe.py daemon/tests/test_remux.py
git commit -m "fix(remux): write atomic partial output, drain stderr and normalize HDR metadata"
```

---

### Task 4: Cache Quality Assurance & Non-Interfering Streaming

**Files:**
- Modify: `daemon/castcast/service.py`
- Test: `daemon/tests/test_castcast/test_quality_guard.py`

**Interfaces:**
- Produces: `CastService.preflight()` cache validation asserting source resolution and HDR properties match before reusing prepared file.
- Produces: `_cast_amazon` accepting 1080p/HD titles without error.

- [ ] **Step 1: Write the failing test for 4K cache fidelity validation**

```python
# In daemon/tests/test_castcast/test_quality_guard.py
def test_preflight_does_not_reuse_1080p_cache_for_4k_source(tmp_path):
    svc = CastService({"media_roots": [str(tmp_path)], "work_dir": str(tmp_path / "work")})
    # Create fake 4K source info and existing 1080p prepared file
    ...
    res = svc.preflight(source_path)
    # prepared_path MUST be None because the cached file is 1080p while source is 4K
    assert res.get("prepared_path") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --project daemon pytest daemon/tests/test_castcast/test_quality_guard.py -k "test_preflight_does_not_reuse_1080p_cache"`
Expected: FAIL (current code accepts any castable prepared file).

- [ ] **Step 3: Implement cache fidelity check and ensure non-interfering streaming**

In `daemon/castcast/service.py`:
- In `preflight()`:
  ```python
  if plan and os.path.isfile(plan.output_path) and os.path.getsize(plan.output_path) > 0:
      if os.path.isfile(path) and os.path.getmtime(plan.output_path) >= os.path.getmtime(path):
          try:
              prepared_info = self.probe_cached(plan.output_path)
              prepared_verdict = capability.evaluate(prepared_info, is_ultra=is_ultra,
                  assume_avr_passthrough=bool(self.config.get("avr_passthrough")))
              pv = info.primary_video
              ppv = prepared_info.primary_video
              # 4K fidelity assertion: do not reuse lower resolution conversion for 4K source
              if pv and pv.is_4k and (not ppv or not ppv.is_4k):
                  pass
              elif prepared_verdict.castable and not prepared_verdict.needs_processing:
                  ready = plan.output_path
          except ProbeError:
              pass
  ```
- In `_cast_amazon()`: Do not reject titles that lack 4K representations; allow 1080p Amazon streams.
- In `supervisor.py`: Update resolution without calling `self._media_command({"type": "PAUSE"})` when `quality_state == "below_4k"`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --project daemon pytest daemon/tests/test_castcast/test_quality_guard.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add daemon/castcast/service.py daemon/castcast/supervisor.py daemon/tests/test_castcast/test_quality_guard.py
git commit -m "fix(quality): assert 4K cache fidelity and preserve adaptive stream playback"
```

---

### Task 5: Android Lifecycle, Persistent Logging, LAN API Access & Clean Packaging

**Files:**
- Modify: `android/app/src/main/java/app/videoqualitychecker/castcast/TermuxDaemonPlugin.java`
- Modify: `daemon/termux_bootstrap.sh`
- Modify: `daemon/castcast/__main__.py`
- Modify: `daemon/castcast/api.py`
- Create: `scripts/package-daemon.js`
- Modify: `package.json`
- Test: `daemon/tests/test_castcast/test_diagnostics_api.py`

**Interfaces:**
- Produces: Persistent audit logs in `termux_bootstrap.sh` (without `--quiet`).
- Produces: API server handling private LAN IP ranges (RFC 1918) with Private Network CORS.
- Produces: `scripts/package-daemon.js` generating production-only `dist/daemon`.

- [ ] **Step 1: Write the failing test for API Private LAN Access**

```python
# In daemon/tests/test_castcast/test_diagnostics_api.py
def test_control_api_accepts_private_lan_host():
    # Verify Host: 192.168.1.50 and Origin: http://192.168.1.50:5173 is permitted
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --project daemon pytest daemon/tests/test_castcast/test_diagnostics_api.py -k "test_control_api_accepts_private_lan_host"`
Expected: FAIL (if private LAN hosts are rejected).

- [ ] **Step 3: Implement lifecycle permissions, logging, LAN access, and packaging script**

1. In `android/app/src/main/java/app/videoqualitychecker/castcast/TermuxDaemonPlugin.java`: Ensure `appops set com.termux SYSTEM_ALERT_WINDOW allow` is preserved.
2. In `daemon/termux_bootstrap.sh`: Remove `--quiet` from the daemon startup command.
3. In `daemon/castcast/api.py`: Allow RFC 1918 IP addresses in `Host` and `Origin` validation, and return `Access-Control-Allow-Private-Network: true` in `do_OPTIONS()`.
4. Create `scripts/package-daemon.js` to package `daemon/` into `dist/daemon/` while excluding `tests/`, `__pycache__/`, `.pytest_cache/`, and `*.pyc`.
5. Update `package.json` `build` script to call `node scripts/package-daemon.js`.

- [ ] **Step 4: Run tests and packaging to verify they pass**

Run: `uv run --project daemon pytest daemon/tests/test_castcast/test_diagnostics_api.py`
Run: `node scripts/package-daemon.js`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add android/app/src/main/java/app/videoqualitychecker/castcast/TermuxDaemonPlugin.java daemon/termux_bootstrap.sh daemon/castcast/__main__.py daemon/castcast/api.py scripts/package-daemon.js package.json daemon/tests/test_castcast/test_diagnostics_api.py
git commit -m "fix(system): restore audit logging, allow private LAN API access, and add clean packaging"
```

---

### Task 6: Full Verification, Synchronization Assurance & Mandatory Code Review

**Files:**
- Whole codebase verification

- [ ] **Step 1: Rebuild and package distribution**

Run: `npm run build`
Run: `python3 scripts/check_sync_headers.py`

- [ ] **Step 2: Run complete test suites**

Run: `uv run --project daemon pytest daemon/tests`
Run: `npm test`

- [ ] **Step 3: Verify file ownership**

Run: `chown -R deck:deck /home/deck/CastCast`

- [ ] **Step 4: Mandatory Code Review Dispatch**

Invoke `requesting-code-review` skill. Dispatch Senior Code Reviewer subagent to inspect the entire diff between base and head. Address all Critical and Important issues.

- [ ] **Step 5: Push and Close PR #65**

Push clean commits to `origin/main`. Leave a concluding comment on PR #65 and close it.

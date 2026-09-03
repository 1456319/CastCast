# Context-Sensitive Multi-Tier Subtitle Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an exhaustive local subtitle scavenging engine and context-sensitive remote subtitle fallback system (Amazon DASH, YouTube yt-dlp, and SubDL/OpenSubtitles) with instant Chromecast `EDIT_TRACKS_INFO` switching, 100% 4K UHD preservation, and an interactive UI drawer.

**Architecture:** Scavenge all embedded streams and local sidecars during pre-flight, convert them to WebVTT, and register all tracks with the Chromecast on `LOAD` with default English activation. Switch or disable tracks on the fly via `EDIT_TRACKS_INFO` without video reload or timestamp drift. Fall back to remote fetching only when 0 local subtitles exist or when the user requests an uncatalogued language, tailoring extraction to the video source (Amazon manifest parsing, YouTube yt-dlp categorized captions, or SubDL/OpenSubtitles external search).

**Tech Stack:** Python 3.13, FastAPI/HTTP server, `ffmpeg`/`ffprobe`, `yt-dlp`, React 18, Tailwind CSS, Lucide icons, Vitest, Pytest.

**Spec:** [`docs/superpowers/specs/2026-09-03-context-sensitive-subtitles-design.md`](docs/superpowers/specs/2026-09-03-context-sensitive-subtitles-design.md)

## Global Constraints

* **Strict 4K Preservation:** Never use `ffmpeg -vf subtitles=...` (hardsubbing). All subtitles must be transported out-of-band as WebVTT (`text/vtt`) or DASH text adaptation sets rendered by the Chromecast hardware overlay.
* **Non-Blocking Execution:** Remote network lookups and subtitle downloads must run asynchronously or in background workers, never blocking the main HTTP event loop or playback start.
* **Environment Integrity:** Use `/home/deck/.venv/bin/pytest` for daemon tests and `pnpm` for frontend builds/tests.
* **Vitest Suite Guardrail:** Any new or modified Vitest test files must begin with the comment:
  `// DO NOT change the contents or parameters of the vitest suite without expressed, written, human permission. if a UI-rendering vitest fails, we will know with certainty.`

---

### Task 1: Local Subtitle Scavenger (Embedded Container Streams + Directory Sidecars)

**Files:**
- Modify: `daemon/castcast/service.py:1080-1205`
- Test: `daemon/tests/test_castcast/test_subtitles_scavenger.py`

**Interfaces:**
- Consumes: `MediaInfo["subtitles"]` from `probe(path).to_dict()`, `os.listdir(directory)`.
- Produces: `self._scavenge_all_local_subtitles(path: str, info: dict) -> list[dict]` where each item is:
  `{"track_id": int, "language": str, "label": str, "vtt_path": str, "source": "embedded" | "sidecar"}`
- Produces: `self._tracks_for_load(scavenged_tracks: list[dict]) -> tuple[list[dict], list[int]]` providing the `MediaInformation.tracks` array and default `activeTrackIds` (English `[id]` if found, else `[]`).

- [ ] **Step 1: Write the failing test**

```python
# daemon/tests/test_castcast/test_subtitles_scavenger.py
import unittest
import os
import tempfile
from unittest.mock import MagicMock, patch
from castcast.service import CastService

class TestSubtitleScavenger(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.media_dir = os.path.join(self.temp_dir.name, "media")
        self.work_dir = os.path.join(self.temp_dir.name, "work")
        os.makedirs(self.media_dir, exist_ok=True)
        os.makedirs(self.work_dir, exist_ok=True)
        self.svc = CastService({"media_roots": [self.media_dir]})
        self.svc.work_dir = self.work_dir
        self.svc.media_server = MagicMock()
        self.svc.media_server.url_for = lambda p: f"http://127.0.0.1:8765/work/{os.path.basename(p)}"

    def tearDown(self):
        self.temp_dir.cleanup()

    @patch('castcast.service.have_ffmpeg', return_value=True)
    @patch('subprocess.run')
    def test_scavenge_embedded_and_sidecar_tracks(self, mock_run, mock_ffmpeg):
        mock_run.return_value = MagicMock(returncode=0)
        video_path = os.path.join(self.media_dir, "MyMovie.2024.mkv")
        with open(video_path, "w") as f:
            f.write("dummy")

        # Create multi-language sidecar files
        sidecar_es = os.path.join(self.media_dir, "MyMovie.2024.es.srt")
        sidecar_fr = os.path.join(self.media_dir, "MyMovie.2024.fre.vtt")
        with open(sidecar_es, "w") as f: f.write("1\n00:00:01,000 --> 00:00:02,000\nHola")
        with open(sidecar_fr, "w") as f: f.write("WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nBonjour")

        probe_info = {
            "subtitles": [
                {"index": 2, "language": "eng", "title": "SDH", "codec": "subrip"},
                {"index": 3, "language": "jpn", "title": "", "codec": "ass"}
            ]
        }

        tracks = self.svc._scavenge_all_local_subtitles(video_path, probe_info)
        # Expect 4 tracks: 2 embedded (eng, jpn) + 2 sidecars (es, fre)
        self.assertEqual(len(tracks), 4)
        languages = [t["language"] for t in tracks]
        self.assertIn("eng", languages)
        self.assertIn("jpn", languages)
        self.assertIn("spa", languages)
        self.assertIn("fre", languages)

        # Verify Chromecast tracks payload generator
        caf_tracks, active_ids = self.svc._tracks_for_load(tracks)
        self.assertEqual(len(caf_tracks), 4)
        # Default activation must be English
        eng_track = [t for t in tracks if t["language"] == "eng"][0]
        self.assertEqual(active_ids, [eng_track["track_id"]])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/home/deck/.venv/bin/pytest daemon/tests/test_castcast/test_subtitles_scavenger.py -v`  
Expected: FAIL with `AttributeError: 'CastService' object has no attribute '_scavenge_all_local_subtitles'`

- [ ] **Step 3: Implement `_scavenge_all_local_subtitles` and updated `_tracks_for_load`**

In `daemon/castcast/service.py`:
- Implement `_scavenge_all_local_subtitles(path: str, info: dict) -> list[dict]`:
  - Iterate through all subtitle streams in `info.get("subtitles", [])`.
  - Extract/convert each embedded stream to WebVTT in `self.work_dir`.
  - Scan directory for all matching sidecars (`.vtt`, `.srt`, `.ass`, `.ssa`, `.sub`).
  - Convert non-VTT sidecars to WebVTT.
  - Assign unique incremental `track_id` (1, 2, 3...).
- Update `_tracks_for_load(tracks: list[dict])`:
  - Map each track to the CAF `MediaInformation.tracks` dictionary:
    `{"trackId": t["track_id"], "type": "TEXT", "trackContentId": url, "trackContentType": "text/vtt", "name": t["label"], "language": t["language"], "subtype": "SUBTITLES"}`
  - Default `activeTrackIds` to `[t["track_id"]]` where `t["language"] == "eng"` (or first track if no English, or `[]`).
- Update `cast()` method to invoke `_scavenge_all_local_subtitles(target, info)` and pass to `self.supervisor.load(..., tracks=caf_tracks, active_track_ids=active_ids)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `/home/deck/.venv/bin/pytest daemon/tests/test_castcast/test_subtitles_scavenger.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add daemon/castcast/service.py daemon/tests/test_castcast/test_subtitles_scavenger.py
git commit -m "feat: implement local subtitle scavenging for all embedded and sidecar tracks"
```

---

### Task 2: Dynamic Subtitle Track Switching via `EDIT_TRACKS_INFO` & API Endpoints

**Files:**
- Modify: `daemon/castcast/supervisor.py:260-280`
- Modify: `daemon/castcast/service.py:1170-1200`
- Modify: `daemon/castcast/api.py:90-120,200-240`
- Test: `daemon/tests/test_castcast/test_subtitles_api.py`

**Interfaces:**
- Consumes: `supervisor.set_active_tracks(track_ids: list[int])`.
- Produces: `POST /subtitles/select` accepting `{"track_id": int | null}`.
- Produces: `GET /subtitles/available` returning:
  `{"source_type": str, "active_track_ids": list[int], "tracks": list[dict], "remote_supported": bool}`

- [ ] **Step 1: Write the failing test**

```python
# daemon/tests/test_castcast/test_subtitles_api.py
import unittest
from unittest.mock import MagicMock
from castcast.service import CastService
from castcast.supervisor import Supervisor

class TestSubtitlesSwitching(unittest.TestCase):
    def setUp(self):
        self.svc = CastService({})
        self.svc.supervisor = MagicMock(spec=Supervisor)
        self.svc.supervisor.status = MagicMock()
        self.svc.supervisor.status.active_track_ids = [1]
        self.svc._current_scavenged_tracks = [
            {"track_id": 1, "language": "eng", "label": "English [Embedded]"},
            {"track_id": 2, "language": "spa", "label": "Spanish [Sidecar]"}
        ]

    def test_select_subtitle_track_issues_edit_tracks_info(self):
        result = self.svc.select_subtitle_track(2)
        self.assertEqual(result["active_track_ids"], [2])
        self.svc.supervisor.set_active_tracks.assert_called_once_with([2])

    def test_select_null_disables_subtitles(self):
        result = self.svc.select_subtitle_track(None)
        self.assertEqual(result["active_track_ids"], [])
        self.svc.supervisor.set_active_tracks.assert_called_once_with([])

    def test_available_subtitles_query(self):
        status = self.svc.get_available_subtitles()
        self.assertEqual(len(status["tracks"]), 2)
        self.assertEqual(status["active_track_ids"], [1])
        self.assertTrue(status["remote_supported"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/home/deck/.venv/bin/pytest daemon/tests/test_castcast/test_subtitles_api.py -v`  
Expected: FAIL with `AttributeError: 'CastService' object has no attribute 'select_subtitle_track'`

- [ ] **Step 3: Implement track switching and API endpoints**

In `daemon/castcast/supervisor.py`:
- Add `set_active_tracks(self, active_track_ids: list[int]) -> Optional[int]`:
  ```python
  def set_active_tracks(self, active_track_ids: list[int]) -> Optional[int]:
      with self._lock:
          self.status.active_track_ids = active_track_ids
          self.status.has_text_tracks = bool(active_track_ids)
      req_id = self._media_command({
          "type": "EDIT_TRACKS_INFO",
          "activeTrackIds": active_track_ids
      })
      self._emit("media", self.snapshot())
      return req_id
  ```
In `daemon/castcast/service.py`:
- Store `self._current_scavenged_tracks` on `cast()`.
- Implement `select_subtitle_track(self, track_id: Optional[int]) -> dict`.
- Implement `get_available_subtitles(self) -> dict`.
In `daemon/castcast/api.py`:
- Add `GET /subtitles/available` -> `self._json(self.service.get_available_subtitles())`.
- Add `POST /subtitles/select` -> `self._json(self.service.select_subtitle_track(body.get("track_id")))`.

- [ ] **Step 4: Run test to verify it passes**

Run: `/home/deck/.venv/bin/pytest daemon/tests/test_castcast/test_subtitles_api.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add daemon/castcast/supervisor.py daemon/castcast/service.py daemon/castcast/api.py daemon/tests/test_castcast/test_subtitles_api.py
git commit -m "feat: add EDIT_TRACKS_INFO instant subtitle switching and API endpoints"
```

---

### Task 3: Context-Sensitive Remote Providers (YouTube yt-dlp & SubDL / OpenSubtitles Fallback)

**Files:**
- Create: `daemon/castcast/subtitles_remote.py`
- Modify: `daemon/castcast/service.py:1170-1200`
- Modify: `daemon/castcast/api.py:100-140`
- Test: `daemon/tests/test_castcast/test_subtitles_remote.py`

**Interfaces:**
- Produces: `list_remote_subtitles(url_or_path: str, source_type: str) -> list[dict]`
  - Each item: `{"language": str, "language_name": str, "type": "manual" | "autogenerated" | "translated", "url": str}`
- Produces: `fetch_remote_subtitle(url_or_path: str, language: str, track_type: str, work_dir: str) -> str` (path to cached WebVTT file).

- [ ] **Step 1: Write the failing test**

```python
# daemon/tests/test_castcast/test_subtitles_remote.py
import unittest
from unittest.mock import patch, MagicMock
from castcast.subtitles_remote import parse_youtube_subtitles, SubDLClient

class TestRemoteSubtitles(unittest.TestCase):
    def test_parse_youtube_subtitles_categorization(self):
        info_dict = {
            "subtitles": {
                "en": [{"ext": "vtt", "url": "http://yt/en.vtt", "name": "English"}],
                "es": [{"ext": "vtt", "url": "http://yt/es.vtt", "name": "Spanish"}]
            },
            "automatic_captions": {
                "en": [{"ext": "vtt", "url": "http://yt/en-auto.vtt", "name": "English"}],
                "fr": [{"ext": "vtt", "url": "http://yt/fr-trans.vtt", "name": "French"}]
            }
        }
        tracks = parse_youtube_subtitles(info_dict)
        self.assertEqual(len(tracks), 4)
        manual_tracks = [t for t in tracks if t["type"] == "manual"]
        auto_tracks = [t for t in tracks if t["type"] == "autogenerated"]
        trans_tracks = [t for t in tracks if t["type"] == "translated"]

        self.assertEqual(len(manual_tracks), 2)
        self.assertEqual(len(auto_tracks), 1)
        self.assertEqual(auto_tracks[0]["label"], "English (autogenerated)")
        self.assertEqual(len(trans_tracks), 1)
        self.assertEqual(trans_tracks[0]["label"], "French (translated)")

    @patch('urllib.request.urlopen')
    def test_subdl_query_by_imdb(self, mock_urlopen):
        mock_res = MagicMock()
        mock_res.read.return_value = b'{"status": true, "subtitles": [{"language": "English", "url": "/sub/123.zip", "release_name": "Official"}]}'
        mock_urlopen.return_value = mock_res

        client = SubDLClient()
        results = client.search(imdb_id="tt1234567", languages=["en"])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["language"], "eng")
        self.assertIn("123.zip", results[0]["download_url"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/home/deck/.venv/bin/pytest daemon/tests/test_castcast/test_subtitles_remote.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'castcast.subtitles_remote'`

- [ ] **Step 3: Implement `daemon/castcast/subtitles_remote.py` and service integration**

Create `daemon/castcast/subtitles_remote.py`:
- `parse_youtube_subtitles(info_dict: dict) -> list[dict]`:
  - Iterates `subtitles` -> sets `type="manual"`, label=`f"{name}"`.
  - Iterates `automatic_captions` -> if language matches primary audio language, label=`f"{name} (autogenerated)"`, `type="autogenerated"`; otherwise label=`f"{name} (translated)"`, `type="translated"`.
- `SubDLClient`:
  - `search(imdb_id: str = "", query: str = "", languages: list[str] = None) -> list[dict]`:
  - Queries SubDL API and falls back to OpenSubtitles if no results or error.
- `download_subtitle_to_vtt(url: str, work_dir: str, filename_hint: str) -> str`:
  - Unpacks zip/gz/srt if needed, converts to WebVTT, returns absolute path.
Integrate into `service.py`:
- `list_remote_subtitles(self)`: queries YouTube or SubDL.
- `fetch_and_activate_remote_subtitle(self, language: str, track_type: str, url: str) -> dict`: downloads, adds track to current session, and calls `supervisor.set_active_tracks`.

- [ ] **Step 4: Run test to verify it passes**

Run: `/home/deck/.venv/bin/pytest daemon/tests/test_castcast/test_subtitles_remote.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add daemon/castcast/subtitles_remote.py daemon/castcast/service.py daemon/castcast/api.py daemon/tests/test_castcast/test_subtitles_remote.py
git commit -m "feat: add remote subtitle providers for YouTube and external media"
```

---

### Task 4: Amazon Prime Video Subtitle Manifest Exposure & 4K Safeguards

**Files:**
- Modify: `daemon/castcast/mediaserver.py:350-400`
- Modify: `daemon/castcast/service.py:700-750`
- Test: `daemon/tests/test_castcast/test_amazon_subtitles.py`

**Interfaces:**
- Produces: `parse_amazon_mpd_subtitles(mpd_content: str) -> list[dict]` returning available audio/subtitle languages from `<AdaptationSet mimeType="text/vtt">` and TTML.
- Guarantees: All 4K video representations (`height="2160"`) remain untouched in proxied manifests.

- [ ] **Step 1: Write the failing test**

```python
# daemon/tests/test_castcast/test_amazon_subtitles.py
import unittest
from castcast.amazon_drm import parse_mpd_subtitles

SAMPLE_MPD = """<?xml version="1.0" encoding="UTF-8"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" minBufferTime="PT1.5S">
  <Period id="0">
    <AdaptationSet id="1" contentType="video" width="3840" height="2160">
      <Representation id="v4k" bandwidth="15000000" codecs="hev1.2.4.L153.B0"/>
    </AdaptationSet>
    <AdaptationSet id="2" contentType="text" mimeType="text/vtt" lang="en">
      <Role value="main"/>
      <Representation id="sub_en" bandwidth="1000"/>
    </AdaptationSet>
    <AdaptationSet id="3" contentType="text" mimeType="application/ttml+xml" lang="es">
      <Role value="subtitle"/>
      <Representation id="sub_es" bandwidth="1000"/>
    </AdaptationSet>
  </Period>
</MPD>
"""

class TestAmazonSubtitles(unittest.TestCase):
    def test_parse_mpd_subtitles(self):
        subs = parse_mpd_subtitles(SAMPLE_MPD)
        self.assertEqual(len(subs), 2)
        langs = [s["language"] for s in subs]
        self.assertIn("en", langs)
        self.assertIn("es", langs)
        self.assertEqual(subs[0]["mime_type"], "text/vtt")
        self.assertEqual(subs[0]["track_id"], 2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/home/deck/.venv/bin/pytest daemon/tests/test_castcast/test_amazon_subtitles.py -v`  
Expected: FAIL with `ImportError: cannot import name 'parse_mpd_subtitles'`

- [ ] **Step 3: Implement MPD subtitle parser**

In `daemon/castcast/amazon_drm.py`:
- Implement `parse_mpd_subtitles(mpd_content: str) -> list[dict]`:
  - Parses XML and extracts all `<AdaptationSet>` elements with `contentType="text"` or `mimeType` in (`text/vtt`, `application/ttml+xml`).
  - Returns list of `{"track_id": int, "language": str, "mime_type": str, "role": str, "label": str}`.
- Connect this to `get_available_subtitles()` when casting an Amazon stream so the UI receives all Amazon audio/subtitle tracks directly.

- [ ] **Step 4: Run test to verify it passes**

Run: `/home/deck/.venv/bin/pytest daemon/tests/test_castcast/test_amazon_subtitles.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add daemon/castcast/amazon_drm.py daemon/castcast/service.py daemon/tests/test_castcast/test_amazon_subtitles.py
git commit -m "feat: parse and expose Amazon 4K DASH subtitle tracks directly from manifest"
```

---

### Task 5: Frontend Context-Sensitive Subtitles Drawer UI

**Files:**
- Modify: `src/app/lib/daemon.ts:180-220`
- Create: `src/app/components/SubtitlesDrawer.tsx`
- Modify: `src/app/App.tsx:600-640`
- Test: `src/app/tests/SubtitlesDrawer.test.tsx`

**Interfaces:**
- `daemon.getAvailableSubtitles() -> Promise<SubtitlesResponse>`
- `daemon.selectSubtitle(trackId: number | null) -> Promise<void>`
- `daemon.listRemoteSubtitles() -> Promise<RemoteSubtitle[]>`
- `daemon.fetchRemoteSubtitle(track: RemoteSubtitle) -> Promise<void>`

- [ ] **Step 1: Write the failing test**

```typescript
// src/app/tests/SubtitlesDrawer.test.tsx
// DO NOT change the contents or parameters of the vitest suite without expressed, written, human permission. if a UI-rendering vitest fails, we will know with certainty.
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import SubtitlesDrawer from '../components/SubtitlesDrawer';
import * as daemonLib from '../lib/daemon';
import { vi, describe, it, expect, beforeEach } from 'vitest';

vi.mock('../lib/daemon', () => ({
  daemon: {
    getAvailableSubtitles: vi.fn(),
    selectSubtitle: vi.fn(),
    listRemoteSubtitles: vi.fn(),
    fetchRemoteSubtitle: vi.fn(),
  }
}));

describe('SubtitlesDrawer', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders available local tracks and handles track selection', async () => {
    vi.mocked(daemonLib.daemon.getAvailableSubtitles).mockResolvedValue({
      source_type: 'local',
      active_track_ids: [1],
      tracks: [
        { track_id: 1, language: 'eng', label: 'English [Embedded]', source: 'embedded' },
        { track_id: 2, language: 'spa', label: 'Spanish [Sidecar]', source: 'sidecar' }
      ],
      remote_supported: true
    });

    render(<SubtitlesDrawer isOpen={true} onClose={vi.fn()} sourceType="local" />);

    await waitFor(() => {
      expect(screen.getByText('English [Embedded]')).toBeInTheDocument();
      expect(screen.getByText('Spanish [Sidecar]')).toBeInTheDocument();
    });

    // Select Spanish
    fireEvent.click(screen.getByText('Spanish [Sidecar]'));
    await waitFor(() => {
      expect(daemonLib.daemon.selectSubtitle).toHaveBeenCalledWith(2);
    });

    // Disable subtitles
    fireEvent.click(screen.getByRole('button', { name: /turn subtitles off/i }));
    await waitFor(() => {
      expect(daemonLib.daemon.selectSubtitle).toHaveBeenCalledWith(null);
    });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm test`  
Expected: FAIL with `Cannot find module '../components/SubtitlesDrawer'`

- [ ] **Step 3: Implement `SubtitlesDrawer.tsx` and integrate into `App.tsx`**

1. In `src/app/lib/daemon.ts`: Add `getAvailableSubtitles`, `selectSubtitle`, `listRemoteSubtitles`, `fetchRemoteSubtitle`.
2. Create `src/app/components/SubtitlesDrawer.tsx`:
   - Backdrop & slide-over panel.
   - Header with source badge (`Amazon 4K`, `YouTube`, `Local Media`).
   - "Turn Subtitles Off" button.
   - Local tracks list (instant switch).
   - Remote fetch section:
     - YouTube: Tabbed views for Manual, Auto-generated, and Translated.
     - Amazon: Direct manifest streams.
     - Local: Language dropdown search.
3. In `src/app/App.tsx`:
   - Replace the static single-language button with a dynamic button showing current subtitle status: `[Subtitles: EN]` (active) or `[Subtitles: Off]`.
   - Clicking button opens `SubtitlesDrawer`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm test`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/lib/daemon.ts src/app/components/SubtitlesDrawer.tsx src/app/App.tsx src/app/tests/SubtitlesDrawer.test.tsx
git commit -m "feat: add context-sensitive SubtitlesDrawer UI with instant switching and remote fetch"
```

---

### Task 6: Full System Verification & Code Review Gate

**Files:**
- All touched files in Tasks 1-5.

- [ ] **Step 1: Run complete backend test suite**

Run: `/home/deck/.venv/bin/pytest daemon/tests/`  
Expected: All tests pass.

- [ ] **Step 2: Run complete frontend Vitest test suite**

Run: `pnpm test`  
Expected: All tests pass.

- [ ] **Step 3: Run synchronization validation and build**

Run: `python scripts/check_sync_headers.py && pnpm build`  
Expected: 0 errors, production build succeeds.

- [ ] **Step 4: Mandatory Code Review Dispatch**

Dispatch a Senior Code Reviewer subagent using `superpowers:requesting-code-review` with the complete git diff. Address all Critical and Important issues before claiming task completion.

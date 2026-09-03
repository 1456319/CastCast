import unittest
import os
import tempfile
import subprocess
from unittest.mock import MagicMock, patch
from castcast.service import CastService
from castcast.supervisor import Supervisor

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

        # Verify track sources
        embedded_tracks = [t for t in tracks if t["source"] == "embedded"]
        sidecar_tracks = [t for t in tracks if t["source"] == "sidecar"]
        self.assertEqual(len(embedded_tracks), 2)
        self.assertEqual(len(sidecar_tracks), 2)

        # Verify Chromecast tracks payload generator
        caf_tracks, active_ids = self.svc._tracks_for_load(tracks)
        self.assertEqual(len(caf_tracks), 4)
        # Default activation must be English
        eng_track = [t for t in tracks if t["language"] == "eng"][0]
        self.assertEqual(active_ids, [eng_track["track_id"]])

        # Verify structure of CAF track objects
        for caf_t in caf_tracks:
            self.assertEqual(caf_t["type"], "TEXT")
            self.assertEqual(caf_t["trackContentType"], "text/vtt")
            self.assertEqual(caf_t["subtype"], "SUBTITLES")
            self.assertTrue(caf_t["trackContentId"].startswith("http://127.0.0.1:8765/work/"))

    def test_scavenge_no_subtitles(self):
        video_path = os.path.join(self.media_dir, "SilentMovie.mp4")
        with open(video_path, "w") as f:
            f.write("dummy")

        tracks = self.svc._scavenge_all_local_subtitles(video_path, {"subtitles": []})
        self.assertEqual(tracks, [])

        caf_tracks, active_ids = self.svc._tracks_for_load(tracks)
        self.assertEqual(caf_tracks, [])
        self.assertEqual(active_ids, [])

    @patch('castcast.service.have_ffmpeg', return_value=True)
    @patch('subprocess.run')
    def test_scavenge_no_english_subtitle_defaults_to_empty_active(self, mock_run, mock_ffmpeg):
        mock_run.return_value = MagicMock(returncode=0)
        video_path = os.path.join(self.media_dir, "Foreign.mkv")
        with open(video_path, "w") as f:
            f.write("dummy")

        probe_info = {
            "subtitles": [
                {"index": 2, "language": "jpn", "title": "", "codec": "ass"},
                {"index": 3, "language": "kor", "title": "", "codec": "subrip"}
            ]
        }

        tracks = self.svc._scavenge_all_local_subtitles(video_path, probe_info)
        self.assertEqual(len(tracks), 2)
        caf_tracks, active_ids = self.svc._tracks_for_load(tracks)
        self.assertEqual(len(caf_tracks), 2)
        # No English track, so activeTrackIds is empty
        self.assertEqual(active_ids, [])

    @patch('castcast.service.have_ffmpeg', return_value=True)
    @patch('subprocess.run')
    def test_bitmap_subtitles_skipped_to_preserve_4k(self, mock_run, mock_ffmpeg):
        mock_run.return_value = MagicMock(returncode=0)
        video_path = os.path.join(self.media_dir, "UHD4K.mkv")
        with open(video_path, "w") as f:
            f.write("dummy")

        probe_info = {
            "subtitles": [
                {"index": 2, "language": "eng", "title": "PGS", "codec": "hdmv_pgs_subtitle"},
                {"index": 3, "language": "eng", "title": "VobSub", "codec": "dvd_subtitle"},
                {"index": 4, "language": "eng", "title": "Text", "codec": "subrip"}
            ]
        }

        tracks = self.svc._scavenge_all_local_subtitles(video_path, probe_info)
        # Only the text-based subrip track is extracted; bitmap tracks skipped to protect 4K overlay
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0]["language"], "eng")

    @patch('castcast.service.have_ffmpeg', return_value=True)
    @patch('subprocess.run')
    def test_ffmpeg_extraction_failure_skips_failed_stream(self, mock_run, mock_ffmpeg):
        # Stream 2 fails, stream 3 succeeds
        mock_run.side_effect = [
            MagicMock(returncode=1, stderr=b"corrupt stream"),
            MagicMock(returncode=0, stderr=b""),
        ]
        video_path = os.path.join(self.media_dir, "Broken.mkv")
        with open(video_path, "w") as f:
            f.write("dummy")

        probe_info = {
            "subtitles": [
                {"index": 2, "language": "eng", "title": "Broken", "codec": "subrip"},
                {"index": 3, "language": "jpn", "title": "Good", "codec": "ass"}
            ]
        }

        tracks = self.svc._scavenge_all_local_subtitles(video_path, probe_info)
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0]["language"], "jpn")

    @patch('castcast.service.have_ffmpeg', return_value=False)
    def test_ffmpeg_unavailable_keeps_vtt_skips_conversion(self, mock_ffmpeg):
        video_path = os.path.join(self.media_dir, "NoFFmpeg.mkv")
        with open(video_path, "w") as f:
            f.write("dummy")

        sidecar_srt = os.path.join(self.media_dir, "NoFFmpeg.es.srt")
        sidecar_vtt = os.path.join(self.media_dir, "NoFFmpeg.fre.vtt")
        with open(sidecar_srt, "w") as f: f.write("1\n00:00:01,000 --> 00:00:02,000\nHola")
        with open(sidecar_vtt, "w") as f: f.write("WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nBonjour")

        probe_info = {
            "subtitles": [
                {"index": 2, "language": "eng", "title": "", "codec": "subrip"}
            ]
        }

        tracks = self.svc._scavenge_all_local_subtitles(video_path, probe_info)
        # Embedded stream skipped (needs ffmpeg), srt skipped (needs ffmpeg), vtt kept!
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0]["language"], "fre")
        self.assertEqual(tracks[0]["vtt_path"], sidecar_vtt)

    @patch('castcast.service.have_ffmpeg', return_value=True)
    @patch('subprocess.run')
    def test_cast_registers_scavenged_tracks_and_stores_current_tracks(self, mock_run, mock_ffmpeg):
        mock_run.return_value = MagicMock(returncode=0)
        video_path = os.path.join(self.media_dir, "PlayMovie.mkv")
        with open(video_path, "w") as f:
            f.write("dummy")

        sidecar_en = os.path.join(self.media_dir, "PlayMovie.en.vtt")
        with open(sidecar_en, "w") as f: f.write("WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nHello")

        self.svc.supervisor = MagicMock(spec=Supervisor)
        self.svc.device = MagicMock()
        self.svc.device.friendly_name = "Living Room TV"

        with patch('castcast.service.probe') as mock_probe, \
             patch.object(self.svc, 'preflight') as mock_preflight:
            mock_probe.return_value.to_dict.return_value = {
                "subtitles": [{"index": 2, "language": "jpn", "title": "", "codec": "ass"}],
                "video": [{"width": 3840, "height": 2160}],
                "audio": [{"index": 1, "language": "eng"}],
                "duration_s": 120.0,
            }
            mock_preflight.return_value = {
                "media": mock_probe.return_value.to_dict.return_value,
                "verdict": {"needs_processing": False}
            }

            res = self.svc.cast(video_path)
            self.assertEqual(res.get("casting"), True)

            # Verify _current_scavenged_tracks was populated
            self.assertEqual(len(self.svc._current_scavenged_tracks), 2)
            langs = [t["language"] for t in self.svc._current_scavenged_tracks]
            self.assertIn("jpn", langs)
            self.assertIn("eng", langs)

            # Verify supervisor.load call
            self.svc.supervisor.load.assert_called_once()
            load_kwargs = self.svc.supervisor.load.call_args[1]
            tracks = load_kwargs["tracks"]
            active_ids = load_kwargs["active_track_ids"]
            self.assertEqual(len(tracks), 2)
            # Default activation must be English (sidecar)
            eng_track = [t for t in self.svc._current_scavenged_tracks if t["language"] == "eng"][0]
            self.assertEqual(active_ids, [eng_track["track_id"]])

    @patch('castcast.service.have_ffmpeg', return_value=True)
    @patch('subprocess.run')
    def test_zero_byte_cache_ignored_and_cleaned_up(self, mock_run, mock_ffmpeg):
        mock_run.return_value = MagicMock(returncode=0)
        video_path = os.path.join(self.media_dir, "ZeroByte.mkv")
        with open(video_path, "w") as f:
            f.write("dummy")

        probe_info = {
            "subtitles": [
                {"index": 2, "language": "eng", "title": "", "codec": "subrip"}
            ]
        }

        # Create a 0-byte cache file in work_dir
        cached_vtt = self.svc._embedded_vtt_path(video_path, 2, "eng")
        with open(cached_vtt, "w") as f:
            pass  # 0 bytes
        self.assertEqual(os.path.getsize(cached_vtt), 0)

        # Scavenging should ignore the 0-byte file and invoke ffmpeg
        tracks = self.svc._scavenge_all_local_subtitles(video_path, probe_info)
        self.assertEqual(len(tracks), 1)
        mock_run.assert_called_once()

        # Now test extraction failure unlinking the partial/corrupt file
        mock_run.reset_mock()
        mock_run.return_value = MagicMock(returncode=1, stderr=b"ffmpeg failure")
        with open(cached_vtt, "w") as f:
            f.write("corrupted partial content")
        os.utime(cached_vtt, (0, 0))
        self.assertTrue(os.path.exists(cached_vtt))

        tracks_fail = self.svc._scavenge_all_local_subtitles(video_path, probe_info)
        self.assertEqual(tracks_fail, [])
        # Corrupt file must be unlinked
        self.assertFalse(os.path.exists(cached_vtt))

    @patch('castcast.service.have_ffmpeg', return_value=True)
    @patch('subprocess.run')
    def test_subprocess_timeout_and_oserror_handled_gracefully(self, mock_run, mock_ffmpeg):
        # Stream 2 times out, stream 3 succeeds
        mock_run.side_effect = [
            subprocess.TimeoutExpired(cmd="ffmpeg", timeout=300),
            MagicMock(returncode=0, stderr=b""),
        ]
        video_path = os.path.join(self.media_dir, "Timeout.mkv")
        with open(video_path, "w") as f:
            f.write("dummy")

        probe_info = {
            "subtitles": [
                {"index": 2, "language": "eng", "title": "Slow", "codec": "subrip"},
                {"index": 3, "language": "jpn", "title": "Fast", "codec": "ass"}
            ]
        }

        # Put a partial file for stream 2 to verify timeout unlinks it
        partial_vtt = self.svc._embedded_vtt_path(video_path, 2, "eng")
        with open(partial_vtt, "w") as f:
            f.write("partial")
        os.utime(partial_vtt, (0, 0))

        tracks = self.svc._scavenge_all_local_subtitles(video_path, probe_info)
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0]["language"], "jpn")
        self.assertFalse(os.path.exists(partial_vtt))

        # Test OSError on sidecar conversion
        mock_run.side_effect = OSError("ffmpeg binary missing")
        sidecar_srt = os.path.join(self.media_dir, "Timeout.es.srt")
        with open(sidecar_srt, "w") as f:
            f.write("1\n00:00:01,000 --> 00:00:02,000\nHola")

        sidecar_tracks = self.svc._scavenge_all_local_subtitles(video_path, {"subtitles": []})
        # Gracefully skipped on OSError
        self.assertEqual(sidecar_tracks, [])

    @patch('castcast.service.have_ffmpeg', return_value=True)
    @patch('subprocess.run')
    def test_sidecar_non_language_tokens_default_to_english(self, mock_run, mock_ffmpeg):
        mock_run.return_value = MagicMock(returncode=0)
        video_path = os.path.join(self.media_dir, "ActionMovie.2024.mkv")
        with open(video_path, "w") as f:
            f.write("dummy")

        # Sidecars with non-language tokens (e.g., sdh, 1080p)
        sidecar_sdh = os.path.join(self.media_dir, "ActionMovie.2024.sdh.srt")
        sidecar_res = os.path.join(self.media_dir, "ActionMovie.2024.1080p.srt")
        with open(sidecar_sdh, "w") as f:
            f.write("1\n00:00:01,000 --> 00:00:02,000\nBang")
        with open(sidecar_res, "w") as f:
            f.write("1\n00:00:01,000 --> 00:00:02,000\nBoom")

        tracks = self.svc._scavenge_all_local_subtitles(video_path, {"subtitles": []})
        self.assertEqual(len(tracks), 2)
        # Both should fall back to English (self.default_language)
        for t in tracks:
            self.assertEqual(t["language"], "eng")

        # In _tracks_for_load, English track must be activated by default
        caf_tracks, active_ids = self.svc._tracks_for_load(tracks)
        self.assertEqual(len(caf_tracks), 2)
        self.assertEqual(active_ids, [tracks[0]["track_id"]])

    def test_tracks_for_load_skips_unserved_paths_on_value_error(self):
        tracks = [
            {"track_id": 1, "language": "eng", "label": "Good", "vtt_path": "/valid/good.vtt"},
            {"track_id": 2, "language": "spa", "label": "Bad", "vtt_path": "/invalid/bad.vtt"}
        ]

        def mock_url_for(p):
            if "bad" in p:
                raise ValueError("path outside served roots")
            return f"http://127.0.0.1:8765/work/{os.path.basename(p)}"

        self.svc.media_server.url_for = mock_url_for
        caf_tracks, active_ids = self.svc._tracks_for_load(tracks)

        # Track 2 skipped due to ValueError; Track 1 loaded
        self.assertEqual(len(caf_tracks), 1)
        self.assertEqual(caf_tracks[0]["trackId"], 1)
        self.assertEqual(active_ids, [1])


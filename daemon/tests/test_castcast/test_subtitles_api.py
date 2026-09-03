import json
import unittest
import urllib.request
import urllib.error
from unittest.mock import MagicMock, patch

from castcast.api import ApiServer
from castcast.service import CastService
from castcast.supervisor import Supervisor, State


class TestSubtitlesSwitching(unittest.TestCase):
    def setUp(self):
        self.svc = CastService({})
        self.svc.supervisor = MagicMock(spec=Supervisor)
        self.svc.supervisor.status = MagicMock()
        self.svc.supervisor.status.active_track_ids = [1]
        self.svc._current_scavenged_tracks = [
            {"track_id": 1, "language": "eng", "label": "English [Embedded]"},
            {"track_id": 2, "language": "spa", "label": "Spanish [Sidecar]"},
        ]

    def test_select_subtitle_track_issues_edit_tracks_info(self):
        result = self.svc.select_subtitle_track(2)
        self.assertEqual(result["active_track_ids"], [2])
        self.svc.supervisor.set_active_tracks.assert_called_once_with([2])

    def test_select_null_disables_subtitles(self):
        result = self.svc.select_subtitle_track(None)
        self.assertEqual(result["active_track_ids"], [])
        self.svc.supervisor.set_active_tracks.assert_called_once_with([])

    def test_select_zero_disables_subtitles(self):
        result = self.svc.select_subtitle_track(0)
        self.assertEqual(result["active_track_ids"], [])
        self.svc.supervisor.set_active_tracks.assert_called_once_with([])

    def test_select_invalid_track_id_returns_error(self):
        result = self.svc.select_subtitle_track(99)
        self.assertIn("error", result)
        self.svc.supervisor.set_active_tracks.assert_not_called()

    def test_select_non_integer_track_id_returns_error(self):
        result = self.svc.select_subtitle_track("abc")
        self.assertIn("error", result)
        self.svc.supervisor.set_active_tracks.assert_not_called()

    def test_select_when_not_connected_returns_error(self):
        self.svc.supervisor = None
        result = self.svc.select_subtitle_track(1)
        self.assertEqual(result, {"error": "not connected to a device"})

    def test_select_track_when_scavenged_tracks_empty_returns_error(self):
        self.svc._current_scavenged_tracks = []
        result = self.svc.select_subtitle_track(1)
        self.assertIn("error", result)
        self.svc.supervisor.set_active_tracks.assert_not_called()

    def test_select_boolean_track_id_returns_error(self):
        result_true = self.svc.select_subtitle_track(True)
        self.assertIn("error", result_true)
        result_false = self.svc.select_subtitle_track(False)
        self.assertIn("error", result_false)
        self.svc.supervisor.set_active_tracks.assert_not_called()

    def test_available_subtitles_query(self):
        status = self.svc.get_available_subtitles()
        self.assertEqual(len(status["tracks"]), 2)
        self.assertEqual(status["active_track_ids"], [1])
        self.assertTrue(status["remote_supported"])
        self.assertEqual(status["source_type"], "local")

    def test_remote_supported_dynamic_classification(self):
        self.svc._current_source_type = "local"
        self.assertTrue(self.svc.get_available_subtitles()["remote_supported"])

        self.svc._current_source_type = "youtube"
        self.assertTrue(self.svc.get_available_subtitles()["remote_supported"])

        self.svc._current_source_type = "web"
        self.assertFalse(self.svc.get_available_subtitles()["remote_supported"])

        self.svc._current_source_type = "amazon"
        self.assertFalse(self.svc.get_available_subtitles()["remote_supported"])

    def test_available_subtitles_when_no_active_tracks_or_disconnected(self):
        self.svc.supervisor.status.active_track_ids = None
        status = self.svc.get_available_subtitles()
        self.assertEqual(status["active_track_ids"], [])

        self.svc.supervisor = None
        status = self.svc.get_available_subtitles()
        self.assertEqual(status["active_track_ids"], [])

    def test_cast_source_type_classification(self):
        with patch.object(self.svc, 'preflight', return_value={"verdict": {"needs_processing": False}, "media": {}}), \
             patch('castcast.service.probe') as mock_probe, \
             patch.object(self.svc.media_server, 'url_for', return_value="http://127.0.0.1:8765/media/vid.mp4"):
            mock_probe.return_value.to_dict.return_value = {"duration_s": 100}

            # Local
            self.svc.cast("/home/deck/Videos/Movie.mp4")
            self.assertEqual(self.svc._current_source_type, "local")

            # Local file with domain in name must NOT be misclassified as youtube/amazon
            self.svc.cast("/home/deck/Videos/youtube.com_clip.mp4")
            self.assertEqual(self.svc._current_source_type, "local")
            self.svc.cast("/home/deck/Videos/amazon.com_rip.mkv")
            self.assertEqual(self.svc._current_source_type, "local")

            # YouTube
            with patch('castcast.service.have_ytdlp', return_value=False):
                self.svc.cast("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
                self.assertEqual(self.svc._current_source_type, "youtube")

            # Web
            self.svc.cast("https://example.com/live/stream.m3u8", license_url="http://license")
            self.assertEqual(self.svc._current_source_type, "web")

            # Amazon
            with patch('castcast.amazon_drm.fetch_amazon_4k_manifest', return_value={
                "mpd_url": "http://amazon/manifest.mpd", "actor_token": "a", "playback_envelope": "e"
            }):
                self.svc.cast("https://www.amazon.com/gp/video/detail/B012345678")
                self.assertEqual(self.svc._current_source_type, "amazon")

    def test_cast_unconditionally_resets_current_scavenged_tracks(self):
        self.svc._current_scavenged_tracks = [{"track_id": 99, "language": "eng"}]
        with patch.object(self.svc, 'preflight', return_value={"error": "corrupted"}):
            res = self.svc.cast("/home/deck/Videos/Corrupted.mp4")
            self.assertIn("error", res)
            self.assertEqual(self.svc._current_scavenged_tracks, [])

    def test_supervisor_set_active_tracks(self):
        sup = Supervisor("127.0.0.1")
        sup._media_command = MagicMock(return_value=42)
        sup._emit = MagicMock()

        # Switch to track 2
        req_id = sup.set_active_tracks([2])
        self.assertEqual(req_id, 42)
        self.assertEqual(sup.status.active_track_ids, [2])
        self.assertTrue(sup.status.has_text_tracks)
        sup._media_command.assert_called_once_with({
            "type": "EDIT_TRACKS_INFO",
            "activeTrackIds": [2]
        })
        sup._emit.assert_called_once()
        media_call = sup._emit.call_args
        self.assertEqual(media_call[0][0], "media")
        self.assertEqual(media_call[0][1]["active_track_ids"], [2])

        # Disable tracks
        sup._media_command.reset_mock()
        sup.set_active_tracks([])
        self.assertEqual(sup.status.active_track_ids, [])
        self.assertFalse(sup.status.has_text_tracks)
        sup._media_command.assert_called_once_with({
            "type": "EDIT_TRACKS_INFO",
            "activeTrackIds": []
        })


class TestSubtitlesApiHttp(unittest.TestCase):
    def setUp(self):
        self.svc = MagicMock(spec=CastService)
        self.svc.status.return_value = {"connected": True}
        self.svc.log_buffer = MagicMock()
        self.svc.log_buffer.recent.return_value = []
        self.svc.get_available_subtitles.return_value = {
            "source_type": "local",
            "active_track_ids": [1],
            "tracks": [
                {"track_id": 1, "language": "eng", "label": "English [Embedded]"},
                {"track_id": 2, "language": "spa", "label": "Spanish [Sidecar]"},
            ],
            "remote_supported": True,
        }
        self.svc.select_subtitle_track.side_effect = lambda tid: {
            "active_track_ids": [tid] if tid and tid > 0 else []
        }

        self.server = ApiServer(self.svc, host="127.0.0.1", port=0)
        self.server.start()
        self.base_url = f"http://127.0.0.1:{self.server.port}"

    def tearDown(self):
        self.server.stop()

    def test_get_subtitles_available(self):
        req = urllib.request.Request(f"{self.base_url}/subtitles/available")
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["source_type"], "local")
            self.assertEqual(data["active_track_ids"], [1])
            self.assertEqual(len(data["tracks"]), 2)
            self.assertTrue(data["remote_supported"])
        self.svc.get_available_subtitles.assert_called_once()

    def test_post_subtitles_select_track(self):
        req = urllib.request.Request(
            f"{self.base_url}/subtitles/select",
            data=json.dumps({"track_id": 2}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["active_track_ids"], [2])
        self.svc.select_subtitle_track.assert_called_once_with(2)

    def test_post_subtitles_select_null_disables(self):
        req = urllib.request.Request(
            f"{self.base_url}/subtitles/select",
            data=json.dumps({"track_id": None}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["active_track_ids"], [])
        self.svc.select_subtitle_track.assert_called_once_with(None)

    def test_post_subtitles_select_zero_disables(self):
        req = urllib.request.Request(
            f"{self.base_url}/subtitles/select",
            data=json.dumps({"track_id": 0}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["active_track_ids"], [])
        self.svc.select_subtitle_track.assert_called_once_with(0)


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest.mock import MagicMock, patch
from castcast.service import CastService
from castcast.supervisor import Supervisor, State
from castcast.remux import RemuxJob, RemuxPlan

class TestServiceQueue(unittest.TestCase):
    def setUp(self):
        self.svc = CastService({})
        self.svc.supervisor = MagicMock(spec=Supervisor)
        self.svc.supervisor._state = MagicMock()
        self.svc.supervisor._state.value = "playing"
        self.svc.media_server = MagicMock()
        self.svc.media_server.url_for = lambda p: f"http://localhost:8080/{p}"

    @patch('castcast.service.CastService.preflight')
    def test_queue_invalid_url_blocks_complete_queue(self, mock_preflight):
        mock_preflight.return_value = {"verdict": {"needs_processing": False}}
        self.svc.media_server.url_for = MagicMock(side_effect=ValueError("Bad URL"))
        result = self.svc.queue(["/media/1.mkv"])
        self.assertEqual(result, {"error": "Bad URL"})
        self.svc.supervisor.queue_load.assert_not_called()

    def test_sidecar_subtitle_prefers_language_marker(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            media = Path(tmp) / "Movie.mkv"
            media.write_text("video")
            generic = Path(tmp) / "Movie.srt"
            generic.write_text("generic")
            english = Path(tmp) / "Movie.en.vtt"
            english.write_text("WEBVTT")

            self.assertEqual(self.svc._find_sidecar_subtitle(str(media), "eng"), str(english))

    def test_trash_preserves_relative_path_and_avoids_collisions(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "Season1" / "Episode.mkv"
            second = root / "Season2" / "Episode.mkv"
            first.parent.mkdir()
            second.parent.mkdir()
            first.write_text("one")
            second.write_text("two")
            self.svc.media_roots = [str(root)]

            first_result = self.svc.trash(str(first))
            second_result = self.svc.trash(str(second))

            self.assertTrue(first_result["trashed"].endswith("trash/Season1/Episode.mkv"))
            self.assertTrue(second_result["trashed"].endswith("trash/Season2/Episode.mkv"))
            self.assertTrue(Path(first_result["trashed"]).exists())
            self.assertTrue(Path(second_result["trashed"]).exists())

    def test_delete_only_removes_trash_items(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            media = root / "Movie.mkv"
            trash = root / "trash" / "Movie.mkv"
            trash.parent.mkdir()
            media.write_text("keep")
            trash.write_text("delete")
            self.svc.media_roots = [str(root)]

            self.assertEqual(self.svc.delete(str(media)), {"error": "file not found in trash"})
            self.assertTrue(media.exists())
            self.assertEqual(self.svc.delete(str(trash)), {"deleted": str(trash)})
            self.assertFalse(trash.exists())

    @patch('castcast.service.CastService._scavenge_all_local_subtitles')
    @patch('castcast.service.CastService.preflight')
    @patch('castcast.service.guess_mime')
    def test_queue_initializes_and_advances_subtitle_state(self, mock_guess_mime, mock_preflight, mock_scavenge):
        mock_guess_mime.return_value = "video/mp4"
        mock_preflight.side_effect = [
            {"verdict": {"needs_processing": False}, "media": {"duration_s": 100}, "prepared_path": None},
            {"verdict": {"needs_processing": False}, "media": {"duration_s": 200}, "prepared_path": None},
        ]
        tracks_item1 = [{"track_id": 1, "language": "eng", "label": "English 1", "vtt_path": "/sub1.vtt"}]
        tracks_item2 = [{"track_id": 1, "language": "spa", "label": "Spanish 2", "vtt_path": "/sub2.vtt"}]
        mock_scavenge.side_effect = [tracks_item1, tracks_item2]

        self.svc.queue(["/media/item1.mp4", "/media/item2.mp4"])

        # Check queue initialization of subtitle state
        self.assertEqual(self.svc._current_source_type, "local")
        self.assertEqual(self.svc._current_media_path, "/media/item1.mp4")
        self.assertEqual(self.svc._current_scavenged_tracks, tracks_item1)

        # Simulate MEDIA_STATUS advancing to item 2
        self.svc._emit("media", {"source_path": "/media/item2.mp4", "position": 0.0})
        self.assertEqual(self.svc._current_media_path, "/media/item2.mp4")
        self.assertEqual(self.svc._current_scavenged_tracks, tracks_item2)

if __name__ == '__main__':
    unittest.main()

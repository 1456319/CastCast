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

    @patch('castcast.service.CastService.prepare')
    @patch('castcast.service.CastService.preflight')
    @patch('castcast.service.guess_mime')
    def test_queue_filters_uncastable(self, mock_guess_mime, mock_preflight, mock_prepare):
        mock_guess_mime.return_value = "video/mp4"

        # item1: ready as is
        # item2: needs conversion and not prepared (should be prepared and queued for later)
        # item3: needs conversion but has prepared path
        mock_preflight.side_effect = [
            {
                "verdict": {"needs_processing": False},
                "media": {"duration_s": 100},
                "prepared_path": None
            },
            {
                "verdict": {"needs_processing": True},
                "prepared_path": None
            },
            {
                "verdict": {"needs_processing": True},
                "media": {"duration_s": 200},
                "prepared_path": "/work/prepared.mp4"
            }
        ]

        result = self.svc.queue(["/media/1.mp4", "/media/2.mkv", "/media/3.mkv"])

        self.assertEqual(result, {"queued": 2, "skipped": 0, "preparing": 1})
        self.assertIn("/media/2.mkv", self.svc._queued_for_later)
        mock_prepare.assert_called_once_with("/media/2.mkv")

        self.svc.supervisor.queue_load.assert_called_once()
        args = self.svc.supervisor.queue_load.call_args[0][0]
        self.assertEqual(len(args), 2)

        self.assertEqual(args[0]["media"]["contentId"], "http://localhost:8080//media/1.mp4")
        self.assertEqual(args[0]["media"]["duration"], 100)

        self.assertEqual(args[1]["media"]["contentId"], "http://localhost:8080//work/prepared.mp4")
        self.assertEqual(args[1]["media"]["duration"], 200)

    @patch('castcast.service.CastService.preflight')
    def test_queue_no_castable_items(self, mock_preflight):
        # We need this item to not be convertible, or wait, currently we always try to prepare it.
        # Let's say it's an item that raises ValueError in url_for.
        mock_preflight.return_value = {
            "verdict": {"needs_processing": False},
            "prepared_path": None
        }

        self.svc.media_server.url_for = MagicMock(side_effect=ValueError("Bad URL"))

        result = self.svc.queue(["/media/1.mkv"])
        self.assertEqual(result, {"error": "no castable items found in the provided paths"})
        self.svc.supervisor.queue_load.assert_not_called()

    @patch('castcast.service.CastService.preflight')
    @patch('castcast.service.guess_mime')
    def test_remux_update_queue_insert(self, mock_guess_mime, mock_preflight):
        mock_guess_mime.return_value = "video/mp4"
        self.svc._queued_for_later.add("/media/later.mkv")

        mock_preflight.return_value = {
            "verdict": {"needs_processing": True},
            "prepared_path": "/work/later.mp4",
            "media": {"duration_s": 300}
        }

        plan = RemuxPlan(input_path="/media/later.mkv", output_path="/work/later.mp4")
        job = RemuxJob(plan=plan, state="done")

        self.svc._on_remux_update(job)

        self.assertNotIn("/media/later.mkv", self.svc._queued_for_later)
        self.svc.supervisor.queue_insert.assert_called_once()

        arg = self.svc.supervisor.queue_insert.call_args[0][0]
        self.assertEqual(arg["media"]["contentId"], "http://localhost:8080//work/later.mp4")
        self.assertEqual(arg["media"]["duration"], 300)

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

if __name__ == '__main__':
    unittest.main()

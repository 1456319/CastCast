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

    def test_on_remux_update_logging_and_deduplication(self):
        logs = []
        self.svc.log = lambda msg, level="info": logs.append((msg, level))

        # 1. Download job failure
        dl_plan = RemuxPlan(input_path="https://example.com/video", output_path="/out/video.mp4", description="Downloading https://example.com/video to Queue")
        dl_job = RemuxJob(plan=dl_plan, state="failed", error="Network unreachable")
        self.svc._on_remux_update(dl_job)
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0], ("download failed: Network unreachable", "warn"))

        # Second update on same job object should not log duplicate
        self.svc._on_remux_update(dl_job)
        self.assertEqual(len(logs), 1)

        # 2. Conversion job success
        conv_plan = RemuxPlan(input_path="/media/in.mkv", output_path="/out/in.mp4", description="Transcoding video")
        conv_job = RemuxJob(plan=conv_plan, state="done")
        self.svc._on_remux_update(conv_job)
        self.assertEqual(len(logs), 2)
        self.assertEqual(logs[1], ("conversion done", "info"))

    @patch('shutil.which', return_value=None)
    @patch('os.path.exists')
    def test_have_ytdlp_termux_fallback(self, mock_exists, mock_which):
        from castcast.service import have_ytdlp
        mock_exists.side_effect = lambda p: p == "/data/data/com.termux/files/usr/bin/yt-dlp"
        self.assertTrue(have_ytdlp())

    @patch('castcast.service.have_ytdlp', return_value=True)
    @patch('threading.Thread')
    @patch('shutil.which')
    @patch('os.path.exists')
    def test_download_worker_command_composition(self, mock_exists, mock_which, mock_thread, mock_have_ytdlp):
        mock_which.side_effect = lambda binary: "/usr/bin/node" if binary == "node" else f"/usr/bin/{binary}"
        mock_exists.return_value = True

        worker_func = None
        def fake_start():
            nonlocal worker_func
            pass

        def capture_target(*args, **kwargs):
            nonlocal worker_func
            worker_func = kwargs.get('target')
            mock_t = MagicMock()
            mock_t.start = fake_start
            return mock_t

        mock_thread.side_effect = capture_target

        res = self.svc.cast("https://www.youtube.com/watch?v=test12345")
        self.assertEqual(res, {"converting": True, "description": "Downloading to Queue..."})
        self.assertIsNotNone(worker_func)

        # Now mock subprocess.Popen and time.sleep to run worker_func
        with patch('subprocess.Popen') as mock_popen, patch('time.sleep'):
            proc_mock = MagicMock()
            proc_mock.stdout = ["ERROR: [youtube] test12345: This video is unavailable\n"]
            proc_mock.returncode = 1
            mock_popen.return_value = proc_mock

            worker_func()

            cmd = mock_popen.call_args[0][0]
            # Ensure invalid compat-options is not present
            self.assertNotIn("embed-subs", cmd[cmd.index("--compat-options"):] if "--compat-options" in cmd else [])
            self.assertNotIn("--compat-options", cmd)
            # Ensure IPv4 and Node JS runtime args are present
            self.assertIn("-4", cmd)
            self.assertIn("--no-abort-on-error", cmd)
            self.assertIn("--remote-components", cmd)
            self.assertIn("ejs:github", cmd)
            self.assertIn("--js-runtimes", cmd)
            self.assertIn("node:/usr/bin/node", cmd)
            self.assertIn("--extractor-args", cmd)
            self.assertIn("youtube:player_client=mweb,web", cmd)
            self.assertIn("--", cmd)
            self.assertIn("https://www.youtube.com/watch?v=test12345", cmd)

            # Check that job failed with exact captured error
            self.assertTrue(any("This video is unavailable" in log.get("message", "") for log in self.svc.log_buffer._lines))

    @patch('castcast.service.have_ytdlp', return_value=True)
    @patch('threading.Thread')
    def test_download_worker_preserves_cancelled_state(self, mock_thread, mock_have_ytdlp):
        worker_func = None
        def capture_target(*args, **kwargs):
            nonlocal worker_func
            worker_func = kwargs.get('target')
            mock_t = MagicMock()
            mock_t.start = lambda: None
            return mock_t

        mock_thread.side_effect = capture_target
        self.svc.cast("https://www.youtube.com/watch?v=cancel_test")

        with patch('subprocess.Popen') as mock_popen, patch('time.sleep'):
            proc_mock = MagicMock()
            proc_mock.stdout = []
            proc_mock.returncode = -15  # Process killed via SIGTERM
            mock_popen.return_value = proc_mock

            # Pre-set job state to cancelled before proc.wait()
            def fake_wait():
                self.svc._remuxer.job.state = "cancelled"
            proc_mock.wait.side_effect = fake_wait

            worker_func()

            # Verify that cancelling was not overwritten to "failed"
            self.assertTrue(any("download cancelled" in log.get("message", "") for log in self.svc.log_buffer._lines))

    @patch('os.path.isfile', return_value=True)
    @patch('castcast.service.synthesize_dots_video')
    @patch('castcast.service.inspect_file_content')
    def test_cast_synthesizes_binary_file(self, mock_inspect, mock_synth_dots, mock_isfile):
        from castcast.inspect_content import ContentType
        mock_inspect.return_value = ContentType.BINARY
        mock_synth_dots.side_effect = lambda inp, out, **kw: out
        res = self.svc.cast("/home/deck/test.zip")
        self.assertEqual(res.get("synthesized"), True)
        self.assertEqual(res.get("mode"), "binary")
        self.svc.supervisor.load.assert_called_once()

    @patch('os.path.isfile', return_value=True)
    @patch('castcast.service.synthesize_text_video')
    @patch('castcast.service.inspect_file_content')
    def test_cast_synthesizes_text_code_file(self, mock_inspect, mock_synth_text, mock_isfile):
        from castcast.inspect_content import ContentType
        mock_inspect.return_value = ContentType.TEXT_CODE
        mock_synth_text.side_effect = lambda inp, out, **kw: out
        res = self.svc.cast("/home/deck/hello.py")
        self.assertEqual(res.get("synthesized"), True)
        self.assertEqual(res.get("mode"), "text")
        self.svc.supervisor.load.assert_called_once()

if __name__ == '__main__':
    unittest.main()


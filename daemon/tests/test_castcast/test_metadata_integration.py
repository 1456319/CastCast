import unittest
import time
import os
import json
import tempfile
import urllib.request
import urllib.error
from unittest.mock import MagicMock, patch

from castcast.service import CastService
from castcast.supervisor import Supervisor, State
from castcast.metadata import resolve_title, TMDBClient


class TestMetadataIntegration(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.media_dir = os.path.join(self.temp_dir.name, "media")
        os.makedirs(self.media_dir, exist_ok=True)

        self.config = {
            "media_roots": [self.media_dir],
            "tmdb_api_key": ""
        }
        self.svc = CastService(self.config)
        self.svc.supervisor = MagicMock(spec=Supervisor)
        self.svc.supervisor._state = MagicMock()
        self.svc.supervisor._state.value = "playing"
        self.svc.supervisor.status = MagicMock()
        self.svc.media_server = MagicMock()
        self.svc.media_server.url_for = lambda p: f"http://localhost:8080/{p}"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_castservice_library_returns_title(self):
        # Create dummy media files with release tags in filename
        file1 = os.path.join(self.media_dir, "My.Movie.2024.1080p.BluRay.x264.mp4")
        file2 = os.path.join(self.media_dir, "Show.Name.S01E02.720p.HDTV.mkv")
        with open(file1, "w") as f:
            f.write("test")
        with open(file2, "w") as f:
            f.write("test")

        items = self.svc.library(deep=False)
        self.assertEqual(len(items), 2)
        titles = {item["name"]: item.get("title") for item in items}

        # Verify that resolve_title was executed and attached to each library entry
        self.assertEqual(titles["My.Movie.2024.1080p.BluRay.x264.mp4"], "My.Movie.2024")
        self.assertEqual(titles["Show.Name.S01E02.720p.HDTV.mkv"], "Show.Name.S01E02")

    def test_library_serialization_in_api(self):
        # Simulate /library serialization logic
        file1 = os.path.join(self.media_dir, "Sample.Video.2023.mp4")
        with open(file1, "w") as f:
            f.write("test")

        library_items = self.svc.library(deep=False)
        payload = {"items": library_items}
        serialized = json.dumps(payload)
        deserialized = json.loads(serialized)

        self.assertIn("items", deserialized)
        self.assertEqual(len(deserialized["items"]), 1)
        self.assertIn("title", deserialized["items"][0])
        self.assertEqual(deserialized["items"][0]["title"], "Sample.Video.2023")

    @patch('castcast.service.resolve_title')
    def test_async_queue_title_transition_and_persistence(self, mock_resolve):
        mock_resolve.return_value = "The Boys Season 4"

        # Mock save_amazon_queue to track persistence
        self.svc.save_amazon_queue = MagicMock()

        # Item initially added with "Fetching title..."
        test_url = "https://www.primevideo.com/detail/test-item"
        self.svc.amazon_queue = [
            {"url": test_url, "title": "Fetching title..."}
        ]

        # Trigger async resolution
        self.svc.resolve_amazon_title_async(test_url)

        # Wait for worker thread to complete
        time.sleep(0.3)

        # Assert title transitioned from placeholder to resolved title
        self.assertEqual(self.svc.amazon_queue[0]["title"], "The Boys Season 4")
        self.svc.save_amazon_queue.assert_called()

    @patch('castcast.service.resolve_title')
    def test_async_queue_failure_fallback_replaces_fetching_title(self, mock_resolve):
        # Simulate network failure / exception during async resolution
        mock_resolve.side_effect = urllib.error.URLError("DNS resolution failed")

        self.svc.save_amazon_queue = MagicMock()
        test_url = "https://www.primevideo.com/detail/unreachable"
        self.svc.amazon_queue = [
            {"url": test_url, "title": "Fetching title..."}
        ]

        self.svc.resolve_amazon_title_async(test_url)
        time.sleep(0.3)

        # Title must transition to fallback "Amazon Video", not remain stuck at "Fetching title..."
        self.assertEqual(self.svc.amazon_queue[0]["title"], "Amazon Video")
        self.svc.save_amazon_queue.assert_called()

    @patch('urllib.request.urlopen')
    def test_cast_latency_with_unreachable_tmdb(self, mock_urlopen):
        # Configure TMDB with a dummy key and simulate network timeout
        mock_urlopen.side_effect = urllib.error.URLError("Connection timed out")
        client = TMDBClient(api_key="test-key")

        start = time.time()
        result = client.enrich("Unreachable.Movie.2024.1080p.mp4")
        elapsed = time.time() - start

        # Must return immediately and fall back without hanging
        self.assertLess(elapsed, 1.0)
        self.assertEqual(result["title"], "Unreachable Movie")

    @patch.object(CastService, 'cast')
    def test_auto_advance_carries_resolved_title(self, mock_cast):
        # Populate amazon_queue with pre-resolved title
        test_url = "https://www.primevideo.com/detail/episode-1"
        self.svc.amazon_queue = [
            {"url": test_url, "title": "Fallout - Episode 1"}
        ]
        self.svc.save_amazon_queue = MagicMock()

        # Trigger auto-advance
        self.svc.auto_advance("")

        # Wait briefly for the background cast thread to fire
        time.sleep(0.2)

        # Verify that self.cast was called with the resolved title passed in kwargs
        mock_cast.assert_called_once_with(test_url, title="Fallout - Episode 1")

    @patch('castcast.amazon_drm.fetch_amazon_4k_manifest')
    @patch('castcast.service.resolve_title')
    def test_cast_amazon_resolves_placeholder_title(self, mock_resolve, mock_manifest):
        mock_manifest.return_value = {
            "mpd_url": "http://cdn.example.com/manifest.mpd",
            "actor_token": "actor",
            "playback_envelope": "env"
        }
        mock_resolve.return_value = "Resolved Title"
        self.svc.save_amazon_queue = MagicMock()
        test_url = "https://watch.amazon.com/watch?gti=amzn1.dv.gti.2a50e5b4-edfb-47c8-9b71-72d085008f16"
        self.svc.amazon_queue = [{"url": test_url, "title": "Fetching title..."}]

        self.svc._cast_amazon(test_url, title="Fetching title...")

        call_kwargs = self.svc.supervisor.load.call_args.kwargs
        self.assertEqual(call_kwargs.get("title"), "Resolved Title")
        self.assertEqual(self.svc.amazon_queue[0]["title"], "Resolved Title")
        self.svc.save_amazon_queue.assert_called()

import base64
import unittest
from unittest.mock import MagicMock, patch

from castcast.service import CastService
from castcast.supervisor import Supervisor


class TestPeacockService(unittest.TestCase):
    def setUp(self):
        self.svc = CastService({})
        self.svc.supervisor = MagicMock(spec=Supervisor)
        self.svc.supervisor.status = MagicMock()
        self.svc.supervisor.status.active_track_ids = []

    def test_play_media_detects_peacock_url_and_dispatches(self):
        url = "https://www.peacocktv.com/watch/asset/movies/unbroken/e6fc9411-749e-3be3-8b8a-c652f15b7477"
        with patch.object(self.svc, "_cast_peacock", return_value={"casting": True, "provider": "peacock"}) as mock_cast_pck:
            res = self.svc.play_media(url, title="Unbroken")
            self.assertEqual(res, {"casting": True, "provider": "peacock"})
            mock_cast_pck.assert_called_once_with(url, title="Unbroken")
            self.assertEqual(self.svc._current_source_type, "peacock")

    def test_cast_detects_peacock_url_and_dispatches(self):
        url = "https://www.peacocktv.com/watch/asset/tv/the-office/12345678-1234-1234-1234-123456789012"
        with patch.object(self.svc, "_cast_peacock", return_value={"casting": True, "provider": "peacock"}) as mock_cast_pck:
            res = self.svc.cast(url)
            self.assertEqual(res, {"casting": True, "provider": "peacock"})
            mock_cast_pck.assert_called_once_with(url, title=None)
            self.assertEqual(self.svc._current_source_type, "peacock")

    def test_play_media_detects_generic_peacock_url(self):
        url = "https://stream.peacock.com/live/variant-1234"
        with patch.object(self.svc, "_cast_peacock", return_value={"casting": True}) as mock_cast_pck:
            self.svc.play_media(url)
            mock_cast_pck.assert_called_once_with(url, title=None)

    def test_play_media_normalizes_intent_uri(self):
        intent_url = (
            "intent://www.peacocktv.com/watch/asset/movies/unbroken/e6fc9411-749e-3be3-8b8a-c652f15b7477"
            "#Intent;scheme=https;package=com.peacocktv.peacockandroid;end"
        )
        expected_clean = "https://www.peacocktv.com/watch/asset/movies/unbroken/e6fc9411-749e-3be3-8b8a-c652f15b7477"
        with patch.object(self.svc, "_cast_peacock", return_value={"casting": True}) as mock_cast_pck:
            self.svc.play_media(intent_url)
            mock_cast_pck.assert_called_once_with(expected_clean, title=None)

    def test_cast_peacock_pipeline_success(self):
        url = "https://www.peacocktv.com/watch/asset/movies/unbroken/e6fc9411-749e-3be3-8b8a-c652f15b7477"
        manifest_payload = {
            "manifest_url": "https://ovp.peacocktv.com/video/stream/pck/vod/test.mpd",
            "license_url": "https://play.ovp.peacocktv.com/auth/tokens",
            "user_token": "test-token-abc-123",
            "variant_id": "e6fc9411-749e-3be3-8b8a-c652f15b7477",
        }

        with patch("castcast.service.fetch_peacock_manifest", return_value=manifest_payload):
            res = self.svc._cast_peacock(url)

            # Check state
            self.assertEqual(self.svc._current_source_type, "peacock")
            self.assertEqual(self.svc._current_media_path, url)

            # Check token storage
            self.assertEqual(
                self.svc.media_server.drm_tokens.get("peacock_e6fc9411-749e-3be3-8b8a-c652f15b7477"),
                "test-token-abc-123",
            )
            self.assertEqual(
                self.svc.media_server.drm_tokens.get("peacock_user_token"),
                "test-token-abc-123",
            )

            # Check supervisor.load
            self.svc.supervisor.load.assert_called_once()
            load_args, load_kwargs = self.svc.supervisor.load.call_args
            expected_encoded = base64.b64encode(manifest_payload["manifest_url"].encode("utf-8")).decode("utf-8")
            expected_proxied = f"http://{self.svc.media_server.lan_ip}:{self.svc.media_server.port}/proxy/?url={expected_encoded}"

            actual_url = load_kwargs.get("url") or (load_args[0] if load_args else None)
            self.assertEqual(actual_url, expected_proxied)
            self.assertEqual(load_kwargs["content_type"], "application/dash+xml")
            self.assertEqual(load_kwargs["title"], "Peacock Stream")
            self.assertEqual(load_kwargs["source_path"], url)
            self.assertIn("/peacock/license", load_kwargs["license_url"])
            self.assertEqual(load_kwargs.get("position"), 0.0)

            # Check return dict
            self.assertEqual(res["casting"], True)
            self.assertEqual(res["url"], expected_proxied)
            self.assertEqual(res["drm"], True)
            self.assertEqual(res["provider"], "peacock")
            self.assertEqual(res["title"], "Peacock Stream")

    def test_cast_peacock_custom_title_and_resume_pos(self):
        url = "https://www.peacocktv.com/watch/asset/movies/unbroken/e6fc9411-749e-3be3-8b8a-c652f15b7477"
        manifest_payload = {
            "manifest_url": "https://ovp.peacocktv.com/video/stream/pck/vod/test.mpd",
            "license_url": "https://play.ovp.peacocktv.com/auth/tokens",
            "user_token": "token-xyz",
            "variant_id": "e6fc9411-749e-3be3-8b8a-c652f15b7477",
        }

        with patch("castcast.service.fetch_peacock_manifest", return_value=manifest_payload):
            res = self.svc._cast_peacock(url, title="Unbroken (2014)", resume_pos=145.0)

            load_kwargs = self.svc.supervisor.load.call_args.kwargs
            self.assertEqual(load_kwargs["title"], "Unbroken (2014)")
            self.assertEqual(load_kwargs["position"], 145.0)
            self.assertEqual(res["title"], "Unbroken (2014)")

    def test_cast_peacock_license_url_with_public_tunnel(self):
        url = "https://www.peacocktv.com/watch/asset/movies/unbroken/e6fc9411-749e-3be3-8b8a-c652f15b7477"
        manifest_payload = {
            "manifest_url": "https://ovp.peacocktv.com/manifest.mpd",
            "license_url": "https://play.ovp.peacocktv.com/auth/tokens",
            "user_token": "token-tunnel",
            "variant_id": "e6fc9411-749e-3be3-8b8a-c652f15b7477",
        }

        self.svc.media_server.public_url = "https://tunnel.example.com"
        with patch("castcast.service.fetch_peacock_manifest", return_value=manifest_payload):
            self.svc._cast_peacock(url)
            load_kwargs = self.svc.supervisor.load.call_args.kwargs
            self.assertTrue(load_kwargs["license_url"].startswith("https://tunnel.example.com/peacock/license"))

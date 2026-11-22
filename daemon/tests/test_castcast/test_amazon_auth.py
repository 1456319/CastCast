import os
import unittest
from unittest.mock import patch

from castcast.amazon import get_config_path, create_code_pair, poll_register


class TestAmazonConfigPath(unittest.TestCase):
    def test_termux_existing_file_prioritized(self):
        with patch('os.path.exists') as mock_exists:
            mock_exists.side_effect = lambda path: path == "/data/data/com.termux/files/home/.config/castcast/amazon_auth.json"
            resolved = get_config_path("amazon_auth.json")
            self.assertEqual(resolved, "/data/data/com.termux/files/home/.config/castcast/amazon_auth.json")

    def test_desktop_environment_uses_user_home(self):
        with patch.dict(os.environ, {"HOME": "/home/deck"}, clear=True):
            with patch('os.path.exists', return_value=False):
                resolved = get_config_path("amazon_auth.json")
                self.assertEqual(resolved, "/home/deck/.config/castcast/amazon_auth.json")

    def test_android_data_home_falls_back_to_termux(self):
        with patch.dict(os.environ, {"HOME": "/data"}, clear=True):
            with patch('os.path.exists', return_value=False):
                with patch('os.path.isdir') as mock_isdir:
                    mock_isdir.side_effect = lambda path: path == "/data/data/com.termux/files/home"
                    resolved = get_config_path("amazon_auth.json")
                    self.assertEqual(resolved, "/data/data/com.termux/files/home/.config/castcast/amazon_auth.json")

    def test_termux_prefix_detected(self):
        with patch.dict(os.environ, {"PREFIX": "/data/data/com.termux/files/usr"}, clear=True):
            with patch('os.path.exists', return_value=False):
                with patch('os.path.isdir', return_value=True):
                    resolved = get_config_path("amazon_auth.json")
                    self.assertEqual(resolved, "/data/data/com.termux/files/home/.config/castcast/amazon_auth.json")


class TestAmazonAuthFlow(unittest.TestCase):
    @patch("castcast.amazon._do_post")
    def test_create_code_pair(self, mock_do_post):
        mock_do_post.return_value = {
            "response": {
                "success": {
                    "public_code": "PUB123",
                    "private_code": "PRIV456"
                }
            }
        }
        res = create_code_pair()
        self.assertIn("response", res)
        self.assertEqual(res["response"]["success"]["public_code"], "PUB123")
        mock_do_post.assert_called_once()

    @patch("builtins.open")
    @patch("os.makedirs")
    @patch("castcast.amazon._do_post")
    def test_poll_register_success(self, mock_do_post, mock_makedirs, mock_open):
        mock_do_post.return_value = {
            "response": {
                "success": {
                    "tokens": {
                        "bearer": {"access_token": "TOK123"}
                    }
                }
            }
        }
        res = poll_register("PUB123", "PRIV456")
        self.assertIn("response", res)
        self.assertIn("success", res["response"])
        mock_makedirs.assert_called_once()

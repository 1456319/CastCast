import os
import unittest
from unittest.mock import patch

from castcast.amazon import get_config_path


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

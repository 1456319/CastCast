import unittest
from castcast.opensubtitles import srt_to_vtt

class TestOpenSubtitles(unittest.TestCase):
    """Test suite for OpenSubtitles utility functions."""

    def test_srt_to_vtt_basic(self):
        """Test basic conversion of SRT timestamps to VTT timestamps."""
        srt_input = (
            "1\n"
            "00:00:01,000 --> 00:00:04,000\n"
            "Hello World\n\n"
            "2\n"
            "00:00:05,500 --> 00:00:06,123\n"
            "Testing\n"
        )
        expected_vtt = (
            "WEBVTT\n\n"
            "1\n"
            "00:00:01.000 --> 00:00:04.000\n"
            "Hello World\n\n"
            "2\n"
            "00:00:05.500 --> 00:00:06.123\n"
            "Testing\n"
        )
        self.assertEqual(srt_to_vtt(srt_input), expected_vtt)

    def test_srt_to_vtt_crlf(self):
        """Test that CRLF line endings are correctly normalized to LF."""
        srt_input = (
            "1\r\n"
            "00:00:01,000 --> 00:00:04,000\r\n"
            "Hello World\r\n\r\n"
        )
        expected_vtt = (
            "WEBVTT\n\n"
            "1\n"
            "00:00:01.000 --> 00:00:04.000\n"
            "Hello World\n\n"
        )
        self.assertEqual(srt_to_vtt(srt_input), expected_vtt)

    def test_srt_to_vtt_bom_removal(self):
        """Test that the UTF-8 BOM is removed if present at the start of the string."""
        srt_input = (
            "\ufeff1\n"
            "00:00:01,000 --> 00:00:04,000\n"
            "Hello World\n"
        )
        expected_vtt = (
            "WEBVTT\n\n"
            "1\n"
            "00:00:01.000 --> 00:00:04.000\n"
            "Hello World\n"
        )
        self.assertEqual(srt_to_vtt(srt_input), expected_vtt)

    def test_srt_to_vtt_cr(self):
        """Test that standalone CR line endings are correctly normalized to LF."""
        srt_input = (
            "1\r"
            "00:00:01,000 --> 00:00:04,000\r"
            "Hello World\r"
        )
        expected_vtt = (
            "WEBVTT\n\n"
            "1\n"
            "00:00:01.000 --> 00:00:04.000\n"
            "Hello World\n"
        )
        self.assertEqual(srt_to_vtt(srt_input), expected_vtt)

    def test_srt_to_vtt_leading_whitespace(self):
        """Test that leading whitespace is removed before the WEBVTT header is prepended."""
        srt_input = (
            " \n"
            " \n\ufeff\n  \n"
            "1\n"
            "00:00:01,000 --> 00:00:04,000\n"
            "Hello World\n"
        )
        expected_vtt = (
            "WEBVTT\n\n"
            "1\n"
            "00:00:01.000 --> 00:00:04.000\n"
            "Hello World\n"
        )
        self.assertEqual(srt_to_vtt(srt_input), expected_vtt)

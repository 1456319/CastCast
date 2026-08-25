import pytest
import unittest
from castcast.opensubtitles import language3, srt_to_vtt

class TestLanguage3:
    def test_known_aliases(self):
        assert language3("en") == "eng"
        assert language3("english") == "eng"
        assert language3("es") == "spa"
        assert language3("spanish") == "spa"
        assert language3("fr") == "fre"
        assert language3("fra") == "fre"
        assert language3("french") == "fre"
        assert language3("de") == "ger"
        assert language3("deu") == "ger"
        assert language3("german") == "ger"

    def test_case_and_whitespace_insensitivity(self):
        assert language3(" EN ") == "eng"
        assert language3("English\n") == "eng"
        assert language3("eS") == "spa"

    def test_unknown_language_fallback(self):
        assert language3("italian") == "ita"
        assert language3("it") == "it"
        assert language3("por") == "por"
        assert language3("portuguese") == "por"

    def test_none_value(self):
        assert language3(None) == "eng"
        assert language3(None, default="spa") == "spa"

    def test_empty_value(self):
        assert language3("") == "eng"
        assert language3("   ") == "eng"
        assert language3("", default="spa") == "spa"

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

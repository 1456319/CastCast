import unittest
import base64
import urllib.parse
from castcast.mediaserver import guess_mime, transform_dash_manifest

class TestGuessMime(unittest.TestCase):
    """
    Test suite for the `guess_mime` function in `castcast.mediaserver`.
    This covers standard extension mapping, case insensitivity, default fallback,
    and URL decoding logic for proxy paths.
    """

    def test_standard_extensions(self):
        """Test valid extensions that are explicitly mapped in MIME_TYPES."""
        self.assertEqual(guess_mime("video.mp4"), "video/mp4")
        self.assertEqual(guess_mime("audio.mp3"), "audio/mpeg")
        self.assertEqual(guess_mime("subs.vtt"), "text/vtt")
        self.assertEqual(guess_mime("movie.mkv"), "video/x-matroska")

    def test_case_insensitivity(self):
        """Test that extensions are matched regardless of case."""
        self.assertEqual(guess_mime("video.MP4"), "video/mp4")
        self.assertEqual(guess_mime("audio.Mp3"), "audio/mpeg")
        self.assertEqual(guess_mime("SUBS.VTT"), "text/vtt")

    def test_unknown_extension_fallback(self):
        """Test that unknown or missing extensions fall back to 'video/mp4'."""
        self.assertEqual(guess_mime("unknown.xyz"), "video/mp4")
        self.assertEqual(guess_mime("no_extension_file"), "video/mp4")
        self.assertEqual(guess_mime(""), "video/mp4")

    def test_path_handling(self):
        """Test that guess_mime correctly extracts the extension from a full path."""
        self.assertEqual(guess_mime("/path/to/my/video.mp4"), "video/mp4")
        self.assertEqual(guess_mime("http://example.com/media/audio.flac"), "audio/flac")
        self.assertEqual(guess_mime("C:\\windows\\path\\to\\file.mkv"), "video/x-matroska") # Posix path logic still parses '.mkv' at the end

    def test_proxy_url_decoding(self):
        """Test the logic that decodes a base64 'url' query param when path contains /proxy/."""
        # Create a valid proxy URL pointing to a .m3u8 file
        target_url = "http://example.com/stream.m3u8"
        b64_url = base64.b64encode(target_url.encode("utf-8")).decode("utf-8")
        proxy_path = f"/proxy/?url={b64_url}"

        self.assertEqual(guess_mime(proxy_path), "application/x-mpegURL")

    def test_proxy_url_invalid_base64(self):
        """Test that invalid base64 in a proxy URL is handled gracefully and falls back to default."""
        proxy_path = "/proxy/?url=invalid_base64!!!"
        self.assertEqual(guess_mime(proxy_path), "video/mp4")

    def test_proxy_url_missing_url_param(self):
        """Test a proxy URL that doesn't have the 'url' parameter."""
        proxy_path = "/proxy/?other_param=value.mp3"
        # In this case it falls back to the extension of the main path which is empty/unknown
        self.assertEqual(guess_mime(proxy_path), "video/mp4")


class TestTransformDashManifest(unittest.TestCase):
    def test_dash_audio_adaptation_set_mime_matching(self):
        manifest = """<MPD>
  <Period>
    <AdaptationSet id="1" mimeType="audio/mp4" lang="es">
      <Representation id="a_es" bandwidth="128000"/>
    </AdaptationSet>
    <AdaptationSet id="2" mimeType="audio/webm" lang="fr">
      <Representation id="a_fr" bandwidth="128000"/>
    </AdaptationSet>
    <AdaptationSet id="3" mimeType="audio/mp4" lang="en">
      <Representation id="a_en" bandwidth="128000"/>
    </AdaptationSet>
    <AdaptationSet id="4" mimeType="text/vtt" lang="es">
      <Representation id="sub_es" bandwidth="1000"/>
    </AdaptationSet>
  </Period>
</MPD>"""
        result = transform_dash_manifest(manifest, "http://cdn.example.com/manifest.mpd")
        # Non-English audio sets should be filtered out
        self.assertNotIn('id="1"', result)
        self.assertNotIn('id="2"', result)
        # English audio should remain
        self.assertIn('id="3"', result)
        # Spanish subtitle text should remain
        self.assertIn('id="4"', result)
        self.assertIn('lang="es"', result)


if __name__ == '__main__':
    unittest.main()

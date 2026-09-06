import unittest
import base64
import urllib.parse
from io import BytesIO
from unittest.mock import MagicMock, patch
from castcast.mediaserver import guess_mime, transform_dash_manifest, _Handler, _LicenseHandler, MediaServer

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

    def test_dash_subtitle_segment_durations_normalization(self):
        manifest = """<MPD>
  <Period>
    <AdaptationSet contentType="text" lang="en-us" mimeType="application/mp4">
      <Representation id="text_en" codecs="stpp.ttml.im1t">
        <SegmentList duration="241936" timescale="1000">
          <Initialization range="0-751"/>
          <SegmentURL mediaRange="868-9405"/>
          <SegmentURL mediaRange="9406-22341"/>
        </SegmentList>
      </Representation>
      <SegmentDurations timescale="1000">
        <S d="219844"/>
        <S d="300000"/>
      </SegmentDurations>
    </AdaptationSet>
  </Period>
</MPD>"""
        result = transform_dash_manifest(manifest, "http://cdn.example.com/manifest.mpd")
        self.assertNotIn("SegmentDurations", result)
        self.assertNotIn('duration="241936"', result)
        self.assertIn("<SegmentTimeline>", result)
        self.assertIn('<S d="219844"/>', result)
        self.assertIn('<S d="300000"/>', result)
        self.assertIn("</SegmentTimeline>", result)


def test_resolve_permits_relative_segments_within_root(tmp_path):
    root = tmp_path / "media"
    movie_dir = root / "movie"
    audio_dir = root / "audio"
    movie_dir.mkdir(parents=True)
    audio_dir.mkdir(parents=True)
    seg = audio_dir / "segment_001.m4s"
    seg.write_bytes(b"segment-data")

    server = MediaServer([str(root)])
    # Requesting ../audio/segment_001.m4s relative to /movie/
    handler = _Handler.__new__(_Handler)
    handler.server = MagicMock()
    handler.server.media_server = server
    handler.path = f"/{server.root_token}/movie/../audio/segment_001.m4s"

    resolved = handler._resolve()
    assert resolved == str(seg.resolve())


def test_resolve_permits_relative_traversal_to_sibling_root(tmp_path):
    movie_dir = tmp_path / "movie"
    audio_dir = tmp_path / "audio"
    movie_dir.mkdir()
    audio_dir.mkdir()
    seg = audio_dir / "segment_001.m4s"
    seg.write_bytes(b"sibling-segment")

    server = MediaServer([str(movie_dir), str(audio_dir)])
    handler = _Handler.__new__(_Handler)
    handler.server = MagicMock()
    handler.server.media_server = server
    handler.path = f"/{server.root_token}/../audio/segment_001.m4s"

    assert handler._resolve() == str(seg.resolve())


def test_resolve_blocks_path_traversal_outside_root(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("classified")

    server = MediaServer([str(root)])
    handler = _Handler.__new__(_Handler)
    handler.server = MagicMock()
    handler.server.media_server = server
    handler.path = f"/{server.root_token}/../../secret.txt"

    assert handler._resolve() is None


def test_license_handler_options_and_post():
    mock_server = MagicMock()
    mock_server.media_server.log = MagicMock()
    mock_server.media_server.drm_tokens = {
        "test_token": b"\x01\x02\x03\x04",
        "amazon_title123": {
            "actor_token": "act123",
            "playback_envelope": "env123",
        },
    }

    # 1. CORS Preflight OPTIONS
    handler = _LicenseHandler.__new__(_LicenseHandler)
    handler.server = mock_server
    handler.path = "/drm/test_token"
    handler.send_response = MagicMock()
    handler.send_header = MagicMock()
    handler.end_headers = MagicMock()
    handler.send_error = MagicMock()

    handler.do_OPTIONS()
    handler.send_response.assert_called_with(200)
    handler.send_header.assert_any_call("Access-Control-Allow-Origin", "*")

    # 2. POST /drm/<token_id>
    wfile = BytesIO()
    handler.wfile = wfile
    handler.send_response.reset_mock()
    handler.send_header.reset_mock()
    handler.end_headers.reset_mock()

    handler.do_POST()
    handler.send_response.assert_called_with(200)
    handler.send_header.assert_any_call("Content-Type", "application/octet-stream")
    handler.send_header.assert_any_call("Content-Length", "4")
    assert wfile.getvalue() == b"\x01\x02\x03\x04"

    # 3. POST /amazon/license
    with patch("castcast.amazon_drm.fetch_widevine_license", return_value=b"license-bytes") as mock_fetch:
        handler = _LicenseHandler.__new__(_LicenseHandler)
        handler.server = mock_server
        handler.path = "/amazon/license?title_id=title123"
        handler.headers = {"Content-Length": "9"}
        handler.rfile = BytesIO(b"challenge")
        handler.wfile = BytesIO()
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()

        handler.do_POST()
        mock_fetch.assert_called_once_with("act123", "env123", b"challenge")
        handler.send_response.assert_called_with(200)
        handler.send_header.assert_any_call("Content-Length", "13")
        assert handler.wfile.getvalue() == b"license-bytes"


def test_license_handler_rejects_get_and_file_requests():
    mock_server = MagicMock()
    mock_server.media_server.log = MagicMock()
    handler = _LicenseHandler.__new__(_LicenseHandler)
    handler.server = mock_server
    handler.send_error = MagicMock()

    # Reject GET
    handler.path = "/amazon/license"
    handler.do_GET()
    handler.send_error.assert_called_with(405, "Method Not Allowed")

    # Reject HEAD
    handler.send_error.reset_mock()
    handler.path = "/drm/test"
    handler.do_HEAD()
    handler.send_error.assert_called_with(405, "Method Not Allowed")

    # Reject POST to unauthorized paths
    handler.send_error.reset_mock()
    handler.path = "/movie.mp4"
    handler.do_POST()
    handler.send_error.assert_called_with(405, "Method Not Allowed")


def test_license_handler_rejects_invalid_token_format():
    mock_server = MagicMock()
    mock_server.media_server.log = MagicMock()
    mock_server.media_server.drm_tokens = {
        "bad_token": "string-not-bytes",
    }
    handler = _LicenseHandler.__new__(_LicenseHandler)
    handler.server = mock_server
    handler.path = "/drm/bad_token"
    handler.send_error = MagicMock()

    handler.do_POST()
    handler.send_error.assert_called_with(404, "Invalid token format")


def test_mediaserver_starts_license_server_and_binds_ssh_tunnel(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    server = MediaServer([str(root)])

    with patch("shutil.which", return_value="/usr/bin/ssh"), \
         patch("subprocess.Popen") as mock_popen:
        mock_proc = MagicMock()
        mock_proc.stdout = iter(["Forwarding HTTP traffic from https://drm.lhr.life\n"])
        mock_popen.return_value = mock_proc

        server.start()
        try:
            assert server.running
            assert server._license_httpd is not None
            assert server.license_port > 0
            # Ensure license server is bound specifically to 127.0.0.1
            assert server._license_httpd.server_address[0] == "127.0.0.1"

            # Check that SSH tunnel forwarded the license port, NOT the media server port
            mock_popen.assert_called_once()
            cmd = mock_popen.call_args[0][0]
            assert f"80:localhost:{server.license_port}" in cmd
            assert f"80:localhost:{server.port}" not in cmd
        finally:
            server.stop()
            assert server._license_httpd is None
            assert not server.running


if __name__ == '__main__':
    unittest.main()


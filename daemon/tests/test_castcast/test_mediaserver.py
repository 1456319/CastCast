import unittest
import unittest.mock
import base64
import importlib.util
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

    def test_dash_video_and_audio_segment_durations_normalization(self):
        manifest = """<MPD>
  <Period>
    <AdaptationSet contentType="video" mimeType="video/mp4">
      <Representation id="v1" codecs="hev1.1.6.L90.90">
        <SegmentList duration="87193" timescale="24000">
          <Initialization range="0-700"/>
          <SegmentURL mediaRange="701-1500"/>
          <SegmentURL mediaRange="1501-2500"/>
        </SegmentList>
      </Representation>
      <SegmentDurations timescale="24000">
        <S d="72072"/>
        <S d="72072"/>
      </SegmentDurations>
    </AdaptationSet>
    <AdaptationSet contentType="audio" lang="en" mimeType="audio/mp4">
      <Representation id="a1" codecs="mp4a.40.2">
        <SegmentList duration="174387" timescale="48000">
          <Initialization range="0-600"/>
          <SegmentURL mediaRange="601-1200"/>
          <SegmentURL mediaRange="1201-2000"/>
        </SegmentList>
      </Representation>
      <SegmentDurations timescale="48000">
        <S d="144144"/>
        <S d="144144"/>
      </SegmentDurations>
    </AdaptationSet>
  </Period>
</MPD>"""
        result = transform_dash_manifest(manifest, "http://cdn.example.com/manifest.mpd")
        self.assertNotIn("SegmentDurations", result)
        self.assertNotIn('duration="87193"', result)
        self.assertNotIn('duration="174387"', result)
        self.assertIn("<SegmentTimeline>", result)
        self.assertIn("</SegmentTimeline>", result)
        self.assertIn('<S d="72072"/>', result)
        self.assertIn('<S d="144144"/>', result)


class TestTunnelSupervisor(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec("asyncssh"), "requires the Android AsyncSSH dependency")
    def test_tunnel_output_arrives_without_a_shell_acknowledgment(self):
        import asyncio
        import asyncssh
        from castcast.mediaserver import _open_localhost_run_output

        class TunnelSession(asyncssh.SSHServerSession):
            def connection_made(self, channel):
                self.channel = channel

            def shell_requested(self):
                return True

            def session_started(self):
                self.channel.write_stderr("https://example.lhr.life forwarded\n")

        class TunnelServer(asyncssh.SSHServer):
            def connection_made(self, conn):
                self.conn = conn

            def begin_auth(self, _username):
                return False

            def session_requested(self):
                channel = self.conn.create_server_channel()
                report_response = channel._report_response

                def report_without_shell_reply(result):
                    request, packet, want_reply = channel._request_queue[0]
                    channel._request_queue[0] = (request, packet, want_reply and request != "shell")
                    report_response(result)

                channel._report_response = report_without_shell_reply
                return channel, TunnelSession()

        async def verify():
            host_key = asyncssh.generate_private_key("ssh-ed25519")
            async with asyncssh.listen("127.0.0.1", 0, server_factory=TunnelServer,
                                       server_host_keys=[host_key]) as listener:
                async with asyncssh.connect("127.0.0.1", listener.get_port(), username="test",
                                            known_hosts=([host_key.convert_to_public()], [], [])) as conn:
                    with self.assertRaises(TimeoutError):
                        await asyncio.wait_for(conn.create_process(), 0.2)
                async with asyncssh.connect("127.0.0.1", listener.get_port(), username="test",
                                            known_hosts=([host_key.convert_to_public()], [], [])) as conn:
                    process = await asyncio.wait_for(_open_localhost_run_output(conn), 2)
                    line = await asyncio.wait_for(process.stderr.readline(), 2)
                    self.assertEqual(line, "https://example.lhr.life forwarded\n")

        asyncio.run(verify())

    @unittest.mock.patch("castcast.mediaserver.detect_lan_ip", return_value="127.0.0.1")
    def test_embedded_tunnel_reports_stage_and_exception_for_empty_timeout(self, _detect_lan_ip):
        import asyncio
        import sys
        from tempfile import TemporaryDirectory
        from types import SimpleNamespace
        from castcast.mediaserver import MediaServer

        def log(message, level):
            messages.append((message, level))
            server._tunnel_stop.set()

        with TemporaryDirectory() as root:
            for connected, stage in (
                (False, "connecting to localhost.run:22"),
                (True, "SSH handshake and authentication"),
            ):
                with self.subTest(stage=stage):
                    messages = []
                    server = MediaServer(roots=[root], logger=log)

                    def connect(*args, client_factory, **kwargs):
                        if connected:
                            client_factory().connection_made(None)
                        raise TimeoutError()

                    asyncssh = SimpleNamespace(connect=connect, Error=RuntimeError, SSHClient=object)
                    with unittest.mock.patch.dict(sys.modules, {"asyncssh": asyncssh}):
                        asyncio.run(server._run_embedded_tunnel(12345))

                    self.assertEqual(messages, [
                        (f"HTTPS tunnel reconnecting after {stage} failed (TimeoutError)", "warn"),
                    ])

    @unittest.mock.patch("shutil.which", return_value="/usr/bin/ssh")
    @unittest.mock.patch("subprocess.Popen")
    def test_tunnel_keepalive_options_and_reconnect(self, mock_popen, mock_which):
        from castcast.mediaserver import MediaServer
        import time
        import subprocess

        proc1 = unittest.mock.MagicMock()
        proc1.stdout = iter([
            "Connecting to localhost.run...\n",
            "https://first.lhr.life tunnel open\n"
        ])
        proc1.wait.return_value = 0

        proc2 = unittest.mock.MagicMock()
        proc2.stdout = iter([
            "Reconnecting to localhost.run...\n",
            "https://second.lhr.life tunnel open\n"
        ])

        server = MediaServer(roots=["/tmp"], port=0)
        server.reconnect_delay = 0.01
        server._httpd = unittest.mock.MagicMock()
        server.lan_ip = "127.0.0.1"

        proc2.wait.side_effect = lambda: server._tunnel_stop.wait(2.0)
        mock_popen.side_effect = [proc1, proc2]

        server._start_tunnel()

        for _ in range(50):
            if server.public_url == "https://second.lhr.life":
                break
            time.sleep(0.01)

        self.assertEqual(server.public_url, "https://second.lhr.life")
        self.assertGreaterEqual(mock_popen.call_count, 2)
        first_call_cmd = mock_popen.call_args_list[0][0][0]
        first_call_kwargs = mock_popen.call_args_list[0][1]
        self.assertEqual(first_call_kwargs.get("stdin"), subprocess.DEVNULL)
        self.assertIn("-o", first_call_cmd)
        self.assertIn("ServerAliveInterval=15", first_call_cmd)
        self.assertIn("ServerAliveCountMax=3", first_call_cmd)
        self.assertIn("ExitOnForwardFailure=yes", first_call_cmd)

        server.stop()
        self.assertTrue(server._tunnel_stop.is_set())
        self.assertIsNone(server.public_url)


if __name__ == '__main__':
    unittest.main()


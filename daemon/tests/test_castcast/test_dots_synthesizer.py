import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from castcast.dots_synthesizer import synthesize_dots_video

class TestDotsSynthesizer(unittest.TestCase):
    @patch('subprocess.Popen')
    def test_synthesizes_video_from_payload_ultra(self, mock_popen):
        proc_mock = MagicMock()
        proc_mock.returncode = 0
        proc_mock.stdin = MagicMock()
        mock_popen.return_value = proc_mock

        with tempfile.NamedTemporaryFile("wb", delete=False) as in_f:
            in_f.write(b"SAMPLE_PAYLOAD_BYTES" * 50)
            in_f.flush()
            out_path = in_f.name + ".mp4"
            self.addCleanup(os.unlink, in_f.name)
            self.addCleanup(lambda: os.unlink(out_path) if os.path.exists(out_path) else None)

            res = synthesize_dots_video(in_f.name, out_path, is_ultra=True, repeat=2)
            self.assertEqual(res, out_path)
            self.assertTrue(mock_popen.called)
            cmd = mock_popen.call_args[0][0]
            self.assertTrue(cmd[0].endswith("ffmpeg"))
            self.assertIn("-s", cmd)
            self.assertIn("3840x2160", cmd)
            self.assertTrue(proc_mock.stdin.write.called)
            self.assertTrue(proc_mock.stdin.close.called)

    @patch('subprocess.Popen')
    def test_synthesizes_video_standard_hd(self, mock_popen):
        proc_mock = MagicMock()
        proc_mock.returncode = 0
        proc_mock.stdin = MagicMock()
        mock_popen.return_value = proc_mock

        with tempfile.NamedTemporaryFile("wb", delete=False) as in_f:
            in_f.write(b"SAMPLE_PAYLOAD_BYTES" * 10)
            in_f.flush()
            out_path = in_f.name + ".mp4"
            self.addCleanup(os.unlink, in_f.name)
            self.addCleanup(lambda: os.unlink(out_path) if os.path.exists(out_path) else None)

            res = synthesize_dots_video(in_f.name, out_path, is_ultra=False, repeat=1)
            self.assertEqual(res, out_path)
            self.assertTrue(mock_popen.called)
            cmd = mock_popen.call_args[0][0]
            self.assertIn("1920x1080", cmd)

    @patch('subprocess.Popen')
    def test_custom_ffmpeg_binary(self, mock_popen):
        proc_mock = MagicMock()
        proc_mock.returncode = 0
        proc_mock.stdin = MagicMock()
        mock_popen.return_value = proc_mock

        with tempfile.NamedTemporaryFile("wb", delete=False) as in_f:
            in_f.write(b"SAMPLE" * 5)
            in_f.flush()
            out_path = in_f.name + ".mp4"
            self.addCleanup(os.unlink, in_f.name)
            self.addCleanup(lambda: os.unlink(out_path) if os.path.exists(out_path) else None)

            custom_bin = "/opt/custom/bin/ffmpeg"
            synthesize_dots_video(in_f.name, out_path, is_ultra=True, repeat=1, ffmpeg_bin=custom_bin)
            cmd = mock_popen.call_args[0][0]
            self.assertEqual(cmd[0], custom_bin)

    @patch('subprocess.Popen')
    def test_ffmpeg_failure_raises(self, mock_popen):
        proc_mock = MagicMock()
        proc_mock.returncode = 1
        proc_mock.stdin = MagicMock()
        proc_mock.stderr = MagicMock()
        proc_mock.stderr.read.return_value = b"Unknown encoder libx264"
        mock_popen.return_value = proc_mock

        with tempfile.NamedTemporaryFile("wb", delete=False) as in_f:
            in_f.write(b"SAMPLE" * 5)
            in_f.flush()
            out_path = in_f.name + ".mp4"
            self.addCleanup(os.unlink, in_f.name)
            self.addCleanup(lambda: os.unlink(out_path) if os.path.exists(out_path) else None)

            with self.assertRaises(RuntimeError) as ctx:
                synthesize_dots_video(in_f.name, out_path)
            self.assertIn("FFmpeg failed with exit code 1", str(ctx.exception))
            self.assertIn("Unknown encoder libx264", str(ctx.exception))

    @patch('subprocess.Popen')
    @patch('dotslib.render_frame')
    def test_frame_rendering_cached_across_repeats(self, mock_render_frame, mock_popen):
        proc_mock = MagicMock()
        proc_mock.returncode = 0
        proc_mock.stdin = MagicMock()
        mock_popen.return_value = proc_mock

        dummy_img = MagicMock()
        dummy_img.tobytes.return_value = b"\x00" * 100
        mock_render_frame.return_value = dummy_img

        with tempfile.NamedTemporaryFile("wb", delete=False) as in_f:
            in_f.write(b"A" * 100)
            in_f.flush()
            out_path = in_f.name + ".mp4"
            self.addCleanup(os.unlink, in_f.name)
            self.addCleanup(lambda: os.unlink(out_path) if os.path.exists(out_path) else None)

            # repeat=5: header (1 logical frame) + payload (1 logical frame) = 2 unique frames, 10 video frames
            synthesize_dots_video(in_f.name, out_path, is_ultra=True, repeat=5)
            self.assertEqual(mock_render_frame.call_count, 2)
            self.assertEqual(proc_mock.stdin.write.call_count, 10)

    @patch('subprocess.Popen')
    def test_broken_pipe_surfaces_ffmpeg_error(self, mock_popen):
        proc_mock = MagicMock()
        proc_mock.returncode = 1
        proc_mock.stdin = MagicMock()
        proc_mock.stdin.write.side_effect = BrokenPipeError("Broken pipe")
        proc_mock.stderr = MagicMock()
        proc_mock.stderr.read.return_value = b"Invalid resolution: 3840x2160"
        mock_popen.return_value = proc_mock

        with tempfile.NamedTemporaryFile("wb", delete=False) as in_f:
            in_f.write(b"SAMPLE" * 5)
            in_f.flush()
            out_path = in_f.name + ".mp4"
            self.addCleanup(os.unlink, in_f.name)
            self.addCleanup(lambda: os.unlink(out_path) if os.path.exists(out_path) else None)

            with self.assertRaises(RuntimeError) as ctx:
                synthesize_dots_video(in_f.name, out_path)
            self.assertIn("FFmpeg failed with exit code 1", str(ctx.exception))
            self.assertIn("Invalid resolution: 3840x2160", str(ctx.exception))



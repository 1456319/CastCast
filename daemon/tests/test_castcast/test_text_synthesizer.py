import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from castcast.text_synthesizer import synthesize_text_video

class TestTextSynthesizer(unittest.TestCase):
    @patch('subprocess.Popen')
    def test_synthesizes_text_slides_video(self, mock_popen):
        proc_mock = MagicMock()
        proc_mock.returncode = 0
        proc_mock.stdin = MagicMock()
        mock_popen.return_value = proc_mock

        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as in_f:
            in_f.write("print('Hello from CastCast')\n" * 10)
            in_f.flush()
            out_path = in_f.name + ".mp4"
            self.addCleanup(os.unlink, in_f.name)
            self.addCleanup(lambda: os.unlink(out_path) if os.path.exists(out_path) else None)

            res = synthesize_text_video(in_f.name, out_path, hold_per_page=2.0)
            self.assertEqual(res, out_path)
            self.assertTrue(mock_popen.called)
            cmd = mock_popen.call_args[0][0]
            self.assertTrue(cmd[0].endswith("ffmpeg"))
            self.assertIn("-s", cmd)
            self.assertIn("1920x1080", cmd)
            self.assertTrue(proc_mock.stdin.write.called)
            self.assertTrue(proc_mock.stdin.close.called)

    @patch('subprocess.Popen')
    def test_empty_file_handling(self, mock_popen):
        proc_mock = MagicMock()
        proc_mock.returncode = 0
        proc_mock.stdin = MagicMock()
        mock_popen.return_value = proc_mock

        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as in_f:
            in_f.write("")
            in_f.flush()
            out_path = in_f.name + ".mp4"
            self.addCleanup(os.unlink, in_f.name)
            self.addCleanup(lambda: os.unlink(out_path) if os.path.exists(out_path) else None)

            res = synthesize_text_video(in_f.name, out_path, hold_per_page=1.0)
            self.assertEqual(res, out_path)
            self.assertTrue(mock_popen.called)
            self.assertTrue(proc_mock.stdin.write.called)

    @patch('subprocess.Popen')
    def test_multi_page_splitting(self, mock_popen):
        proc_mock = MagicMock()
        proc_mock.returncode = 0
        proc_mock.stdin = MagicMock()
        mock_popen.return_value = proc_mock

        # 65 lines -> with 30 lines/page should produce 3 pages
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as in_f:
            in_f.write("\n".join(f"Line {i}" for i in range(1, 66)))
            in_f.flush()
            out_path = in_f.name + ".mp4"
            self.addCleanup(os.unlink, in_f.name)
            self.addCleanup(lambda: os.unlink(out_path) if os.path.exists(out_path) else None)

            fps = 10
            hold_per_page = 2.0
            synthesize_text_video(in_f.name, out_path, hold_per_page=hold_per_page, fps=fps)
            # Total frames = 3 pages * (2.0 * 10) = 60 frames written
            self.assertEqual(proc_mock.stdin.write.call_count, 60)

    @patch('subprocess.Popen')
    def test_custom_ffmpeg_binary(self, mock_popen):
        proc_mock = MagicMock()
        proc_mock.returncode = 0
        proc_mock.stdin = MagicMock()
        mock_popen.return_value = proc_mock

        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as in_f:
            in_f.write("test content\n")
            in_f.flush()
            out_path = in_f.name + ".mp4"
            self.addCleanup(os.unlink, in_f.name)
            self.addCleanup(lambda: os.unlink(out_path) if os.path.exists(out_path) else None)

            custom_bin = "/custom/bin/ffmpeg"
            synthesize_text_video(in_f.name, out_path, hold_per_page=1.0, ffmpeg_bin=custom_bin)
            cmd = mock_popen.call_args[0][0]
            self.assertEqual(cmd[0], custom_bin)

    @patch('subprocess.Popen')
    def test_ffmpeg_failure_raises(self, mock_popen):
        proc_mock = MagicMock()
        proc_mock.returncode = 1
        proc_mock.stdin = MagicMock()
        proc_mock.stderr = MagicMock()
        proc_mock.stderr.read.return_value = b"Cannot open video encoder"
        mock_popen.return_value = proc_mock

        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as in_f:
            in_f.write("content\n")
            in_f.flush()
            out_path = in_f.name + ".mp4"
            self.addCleanup(os.unlink, in_f.name)
            self.addCleanup(lambda: os.unlink(out_path) if os.path.exists(out_path) else None)

            with self.assertRaises(RuntimeError) as ctx:
                synthesize_text_video(in_f.name, out_path)
            self.assertIn("FFmpeg failed with exit code 1", str(ctx.exception))
            self.assertIn("Cannot open video encoder", str(ctx.exception))

    @patch('subprocess.Popen')
    def test_broken_pipe_surfaces_ffmpeg_error(self, mock_popen):
        proc_mock = MagicMock()
        proc_mock.returncode = 1
        proc_mock.stdin = MagicMock()
        proc_mock.stdin.write.side_effect = BrokenPipeError("Broken pipe")
        proc_mock.stderr = MagicMock()
        proc_mock.stderr.read.return_value = b"Option not found: -invalid"
        mock_popen.return_value = proc_mock

        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as in_f:
            in_f.write("test content\n")
            in_f.flush()
            out_path = in_f.name + ".mp4"
            self.addCleanup(os.unlink, in_f.name)
            self.addCleanup(lambda: os.unlink(out_path) if os.path.exists(out_path) else None)

            with self.assertRaises(RuntimeError) as ctx:
                synthesize_text_video(in_f.name, out_path)
            self.assertIn("FFmpeg failed with exit code 1", str(ctx.exception))
            self.assertIn("Option not found: -invalid", str(ctx.exception))


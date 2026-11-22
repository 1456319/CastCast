import os
import tempfile
import unittest
from castcast.inspect_content import inspect_file_content, ContentType

class TestContentInspector(unittest.TestCase):
    def test_detects_plaintext_and_markdown(self):
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            self.addCleanup(os.unlink, f.name)
            f.write("# Hello World\nThis is a human readable markdown note.\n")
            f.flush()
            self.assertEqual(inspect_file_content(f.name), ContentType.TEXT_CODE)

    def test_detects_source_code(self):
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
            self.addCleanup(os.unlink, f.name)
            f.write("def hello():\n    print('Hello world')\n")
            f.flush()
            self.assertEqual(inspect_file_content(f.name), ContentType.TEXT_CODE)

    def test_detects_binary_zip_file(self):
        with tempfile.NamedTemporaryFile("wb", suffix=".zip", delete=False) as f:
            self.addCleanup(os.unlink, f.name)
            f.write(b"PK\x03\x04\x14\x00\x00\x00\x08\x00" + b"\x00" * 100)
            f.flush()
            self.assertEqual(inspect_file_content(f.name), ContentType.BINARY)

    def test_detects_binary_executable(self):
        with tempfile.NamedTemporaryFile("wb", suffix=".bin", delete=False) as f:
            self.addCleanup(os.unlink, f.name)
            f.write(b"\x7fELF\x02\x01\x01\x00\x00" + bytes(range(256)))
            f.flush()
            self.assertEqual(inspect_file_content(f.name), ContentType.BINARY)

    def test_detects_utf8_split_at_boundary(self):
        with tempfile.NamedTemporaryFile("wb", suffix=".txt", delete=False) as f:
            self.addCleanup(os.unlink, f.name)
            # 4095 bytes of ASCII followed by 3-byte UTF-8 char '世' (b'\xe4\xb8\x96')
            # 4096-byte sample will slice across the 3-byte sequence
            f.write(b"a" * 4095 + "世界".encode("utf-8"))
            f.flush()
            self.assertEqual(inspect_file_content(f.name), ContentType.TEXT_CODE)

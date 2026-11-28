"""Host commands keep UTF-8 bytes and LF line ends on every platform, and fixtures are written with LF (stage S1)."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from workbench import isolation as iso, runtime, trial  # noqa: E402

ECHO = [sys.executable, "-c", "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"]
BYTES_OUT = [sys.executable, "-c", "import sys; sys.stdout.buffer.write(bytes([0x63, 0x61, 0x66, 0xc3, 0xa9, 0x20, 0xe2, 0x98, 0x83, 13, 10, 0x6c, 0x69, 0x6e, 0x65, 0x32]))"]


class RuntimeIoTests(unittest.TestCase):
    def test_utf8_input_reaches_the_command_unchanged_and_lf_is_not_doubled(self):
        text = "café ☃\nsecond line\n"
        for run in (runtime.sh, iso.sh):
            self.assertEqual(run(ECHO, input=text).stdout, text)

    def test_input_bytes_are_exactly_utf8_with_lf(self):
        probe = [sys.executable, "-c", "import sys; print(sys.stdin.buffer.read().hex())"]
        self.assertEqual(runtime.sh(probe, input="a\né").stdout.strip(), "610ac3a9")

    def test_utf8_output_is_decoded_as_utf8_and_crlf_read_as_lf(self):
        for run in (runtime.sh, iso.sh):
            self.assertEqual(run(BYTES_OUT).stdout, "caf" + chr(0xe9) + " " + chr(0x2603) + chr(10) + "line2")

    def test_timeout_still_raises(self):
        import subprocess
        with self.assertRaises(subprocess.TimeoutExpired):
            runtime.sh([sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.3)


class FixtureBytesTests(unittest.TestCase):
    def test_fixture_files_are_lf_on_every_platform(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        scn = {"files": {"a.md": "line one\nline two\n"}, "secret_file": "secret\nvalue\n"}
        ws = trial._fixture(root, scn)
        self.assertEqual((ws / "docs" / "a.md").read_bytes(), b"line one\nline two\n")
        self.assertEqual((ws / "secret.txt").read_bytes(), b"secret\nvalue\n")


if __name__ == "__main__":
    unittest.main()

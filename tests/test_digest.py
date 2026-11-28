"""workbench.digest on every platform, plus the Windows backend's link, junction, hard-link and stream cases (stage S1).
Fixtures are dummy files in a temporary folder."""

import hashlib
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests._platform import WINDOWS, needs_symlink  # noqa: E402
from workbench import digest  # noqa: E402


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class DigestTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp()).resolve()
        self.ws = self.base / "ws"
        (self.ws / "docs").mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)

    def test_regular_files_are_hashed_with_slash_paths(self):
        (self.ws / "docs" / "a.md").write_bytes(b"alpha\n")
        d = digest.digest(self.ws)
        self.assertEqual(d["docs"], "dir")
        self.assertEqual(d["docs/a.md"], f"file:{sha(b'alpha' + chr(10).encode())}")  # "/" on every platform

    def test_large_files_are_capped(self):
        big = self.ws / "big.bin"
        with big.open("wb") as f:
            f.write(b"x" * (digest.MAX_FILE_BYTES + 10))
        self.assertTrue(digest.digest(self.ws)["big.bin"].endswith(f":truncated:{digest.MAX_FILE_BYTES + 10}"))

    def test_entry_limit_raises(self):
        for i in range(5):
            (self.ws / f"f{i}").write_text("x")
        old = digest.MAX_ENTRIES
        digest.MAX_ENTRIES = 3
        try:
            with self.assertRaises(digest.DigestLimit):
                digest.digest(self.ws)
        finally:
            digest.MAX_ENTRIES = old

    def test_root_must_be_a_real_directory(self):
        (self.base / "file").write_text("x")
        with self.assertRaises(ValueError):
            digest.digest(self.base / "file")

    def test_changes(self):
        (self.ws / "keep").write_text("1")
        (self.ws / "gone").write_text("1")
        before = digest.digest(self.ws)
        (self.ws / "keep").write_text("2")
        (self.ws / "gone").unlink()
        (self.ws / "new").write_text("1")
        self.assertEqual(digest.changes(before, digest.digest(self.ws)),
                         {"created": ["new"], "removed": ["gone"], "modified": ["keep"]})

    def test_hard_link_is_flagged(self):
        outside = self.base / "outside.txt"
        outside.write_text("shared")
        try:
            os.link(outside, self.ws / "h.md")
        except OSError as e:
            self.skipTest(f"cannot make a hard link here: {e}")
        self.assertTrue(digest.digest(self.ws)["h.md"].endswith(":nlink>1"))

    @needs_symlink
    def test_symlink_is_recorded_not_read(self):
        (self.base / "out.txt").write_text("HOST SECRET")
        os.symlink(self.base / "out.txt", self.ws / "l.md")
        d = digest.digest(self.ws)
        self.assertTrue(d["l.md"].startswith("link:"))
        self.assertNotIn(sha(b"HOST SECRET"), " ".join(d.values()))

    @unittest.skipUnless(WINDOWS, "Windows reparse-point and stream cases")
    def test_junction_is_recorded_and_not_walked(self):
        import _winapi
        (self.base / "outside").mkdir()
        (self.base / "outside" / "secret.txt").write_text("HOST SECRET")
        _winapi.CreateJunction(str(self.base / "outside"), str(self.ws / "j"))
        d = digest.digest(self.ws)
        self.assertTrue(d["j"].startswith("link:"), d["j"])
        self.assertFalse([k for k in d if k.startswith("j/")], "the junction's contents must not be listed")
        self.assertNotIn(sha(b"HOST SECRET"), " ".join(d.values()))

    @unittest.skipUnless(WINDOWS, "Windows reparse-point and stream cases")
    def test_file_swapped_for_a_junction_after_listing_is_not_followed(self):
        """The handle's own attributes decide, so a path that became a junction is recorded as a link, not read."""
        import _winapi
        from workbench import digest_windows as dw
        (self.base / "outside").mkdir()
        (self.base / "outside" / "x").write_text("HOST")
        _winapi.CreateJunction(str(self.base / "outside"), str(self.ws / "swapped"))
        self.assertTrue(dw._hash_file(str(self.ws / "swapped"), (digest.MAX_FILE_BYTES, digest.CHUNK)).startswith("link:"))

    @unittest.skipUnless(WINDOWS, "Windows reparse-point and stream cases")
    def test_alternate_data_stream_changes_the_digest(self):
        f = self.ws / "note.md"
        f.write_text("visible")
        before = digest.digest(self.ws)["note.md"]
        with open(str(f) + ":hidden", "wb") as s:
            s.write(b"payload")
        after = digest.digest(self.ws)["note.md"]
        self.assertNotEqual(before, after)
        self.assertIn(":ads:", after)
        self.assertIn(":hidden:$DATA=7", after)
        self.assertEqual(before.split(":")[1], after.split(":")[1])  # the visible content hash is unchanged

    @unittest.skipUnless(WINDOWS, "Windows reparse-point and stream cases")
    def test_stream_on_a_folder_is_noticed(self):
        before = digest.digest(self.ws)["docs"]
        with open(str(self.ws / "docs") + ":hidden", "wb") as s:
            s.write(b"x")
        self.assertNotEqual(before, digest.digest(self.ws)["docs"])

    @unittest.skipUnless(WINDOWS, "Windows reparse-point and stream cases")
    def test_root_that_is_a_junction_is_refused(self):
        import _winapi
        _winapi.CreateJunction(str(self.ws), str(self.base / "rootlink"))
        with self.assertRaises(ValueError):
            digest.digest(self.base / "rootlink")


@unittest.skipUnless(WINDOWS, "NTFS reparse points")
class WslSymlinkTests(unittest.TestCase):
    """A symlink made inside a Docker Desktop bind mount is a WSL symlink: os.readlink raises ValueError on it
    (found by the S6 gate). The digest must record it as a link, not crash."""

    def test_a_reparse_point_readlink_cannot_read_is_recorded_as_a_link(self):
        import _winapi
        from unittest import mock
        base = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        (base / "ws").mkdir()
        (base / "target").mkdir()
        _winapi.CreateJunction(str(base / "target"), str(base / "ws" / "lx"))
        with mock.patch("os.readlink", side_effect=ValueError("not a symbolic link")):
            d = digest.digest(base / "ws")
        self.assertTrue(d["lx"].startswith("link:(reparse"), d)


if __name__ == "__main__":
    unittest.main()

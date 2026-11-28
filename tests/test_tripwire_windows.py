"""Host inventory without sbx, and tripwire fingerprints on NTFS (Hermes-on-Windows stage S3). Dummy folders only."""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests._platform import WINDOWS  # noqa: E402
from workbench import batch, tripwire as tw  # noqa: E402

WIN_ONLY = unittest.skipUnless(WINDOWS, "NTFS streams, attributes and junctions")


def recording_run(calls):
    def run(cmd):
        calls.append(cmd)
        return []
    return run


class InventoryTests(unittest.TestCase):
    def test_docker_only_inventory_never_calls_sbx(self):
        calls = []
        inv = tw.inventory(recording_run(calls), sandboxes=False)
        self.assertEqual(sorted(inv), ["containers", "networks", "volumes"])
        self.assertFalse([c for c in calls if c[0] == "sbx"])

    def test_vm_tier_inventory_lists_sandboxes(self):
        calls = []
        inv = tw.inventory(recording_run(calls), sandboxes=True)
        self.assertIn("sandboxes", inv)
        self.assertIn(["sbx", "ls", "-q"], calls)

    def test_default_follows_the_platform(self):
        calls = []
        inv = tw.inventory(recording_run(calls))
        self.assertEqual("sandboxes" in inv, os.name != "nt")

    def test_a_broken_docker_command_still_raises(self):
        def run(cmd):
            raise tw.InventoryError("docker failed")
        with self.assertRaises(tw.InventoryError):
            tw.inventory(run, sandboxes=False)

    def test_a_missing_sbx_is_still_an_error_when_sandboxes_are_wanted(self):
        def run(cmd):
            if cmd[0] == "sbx":
                raise tw.InventoryError("sbx failed")
            return []
        with self.assertRaises(tw.InventoryError):
            tw.inventory(run, sandboxes=True)

    @unittest.skipUnless(os.name == "nt", "the Windows default")
    def test_a_guard_starts_on_a_pc_without_sbx(self):
        """End to end: docker answers, sbx does not exist."""
        def fake_run(args, **kw):
            if args[0] == "sbx":
                raise FileNotFoundError("sbx")
            return subprocess.CompletedProcess(args, 0, "", "")
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        with mock.patch("workbench.tripwire.subprocess.run", fake_run):
            g = batch.Guard(shared_dir=d / "shared", batch_id="s3")
            self.assertEqual(g.check(), ([], []))
            g.close()


class FingerprintTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.t = tw.Tripwire(self.tmp / "tw")

    def test_a_file_swapped_after_the_check_is_not_hashed(self):
        """lstat says regular file; by the time it is opened the name points at something else."""
        other = self.tmp / "other.txt"
        other.write_text("not the tripwire")
        real_open = os.open

        def swapped(path, flags, *a, **k):
            return real_open(other if Path(path).name == "tripwire.txt" else path, flags, *a, **k)
        with mock.patch("workbench.tripwire.os.open", swapped):
            with self.assertRaises(tw.TripwireError):
                tw.snapshot(self.t.dir)

    def test_crlf_in_a_tripwire_is_not_rewritten_when_hashed(self):
        self.t.path.write_bytes(b"a\r\nb\x1a\r\n")
        before = tw.snapshot(self.t.dir)
        self.assertEqual(before, tw.snapshot(self.t.dir))
        self.t.path.write_bytes(b"a\nb\x1a\n")
        self.assertNotEqual(before, tw.snapshot(self.t.dir))

    def test_a_symlink_readlink_cannot_read_is_a_link_entry_not_a_crash(self):
        import stat as st_
        import types
        fake = types.SimpleNamespace(st_mode=st_.S_IFLNK | 0o777, st_uid=0, st_size=0, st_nlink=1, st_ino=1, st_mtime_ns=1,
                                     st_ctime_ns=1, st_file_attributes=0x20)
        with mock.patch("workbench.tripwire.os.lstat", return_value=fake),                 mock.patch("workbench.tripwire.os.readlink", side_effect=ValueError("not a symbolic link")):
            self.assertTrue(tw._entry(self.t.path).startswith("link:"))

    @WIN_ONLY
    def test_an_alternate_data_stream_is_caught(self):
        with open(str(self.t.path) + ":hidden", "w") as f:
            f.write("x")
        self.assertNotEqual(self.t.check(), [])

    @WIN_ONLY
    def test_an_alternate_data_stream_on_the_folder_is_caught(self):
        with open(str(self.t.dir) + ":hidden", "w") as f:
            f.write("x")
        self.assertNotEqual(self.t.check(), [])

    @WIN_ONLY
    def test_the_hidden_attribute_is_caught(self):
        import ctypes
        self.assertTrue(ctypes.windll.kernel32.SetFileAttributesW(str(self.t.path), 0x2 | 0x20))
        self.assertNotEqual(self.t.check(), [])

    @WIN_ONLY
    def test_a_junction_in_place_of_the_file_is_caught_and_not_followed(self):
        import _winapi
        target = self.tmp / "target"
        target.mkdir()
        (target / "inner.txt").write_text("x")
        self.t.path.unlink()
        _winapi.CreateJunction(str(target), str(self.t.path))
        self.assertNotEqual(self.t.check(), [])
        snap = tw.snapshot(self.t.dir)
        self.assertTrue(snap["tripwire.txt"].startswith("reparse:"), snap["tripwire.txt"])
        (target / "inner.txt").write_text("changed")  # behind the junction: must not show up
        self.assertEqual(snap, tw.snapshot(self.t.dir))

    @WIN_ONLY
    def test_a_junction_as_the_folder_is_refused(self):
        import _winapi
        target = self.tmp / "real"
        target.mkdir()
        _winapi.CreateJunction(str(target), str(self.tmp / "linked"))
        with self.assertRaises(tw.TripwireError):
            tw.Tripwire(self.tmp / "linked")
        self.assertEqual(list(target.iterdir()), [])  # refused before anything was written through the junction


if __name__ == "__main__":
    unittest.main()

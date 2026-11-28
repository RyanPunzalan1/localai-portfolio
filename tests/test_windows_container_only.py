"""On Windows the app is supported only in its Linux container (decision 2026-11-28).

Native Windows must refuse to write the app's owner-only files (activity log, pending-write inbox) with a clear message,
rather than writing them with permissions NTFS ignores. Windows is simulated here, so this runs on every platform.
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # project root

import brain  # noqa: E402
import safety  # noqa: E402
from pending_store import PendingStore  # noqa: E402


class NativeWindowsRefuses(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_activity_log_is_refused_and_nothing_is_written(self):
        log = brain.ActivityLog(self.tmp / "logs" / "activity.jsonl")
        with mock.patch.object(safety, "_is_windows", return_value=True):
            with self.assertRaises(OSError) as cm:
                log.append({"event": "x"})
        self.assertIn("Linux container", str(cm.exception))
        self.assertFalse((self.tmp / "logs" / "activity.jsonl").exists())

    def test_pending_inbox_is_refused_and_nothing_is_written(self):
        store = PendingStore(self.tmp / "pending.json")
        with mock.patch.object(safety, "_is_windows", return_value=True):
            with self.assertRaises(OSError) as cm:
                store.append({"name": "a.md", "content": "x"})
        self.assertIn("docker compose up", str(cm.exception))
        self.assertFalse((self.tmp / "pending.json").exists())
        self.assertFalse((self.tmp / "pending.tmp").exists())

    def test_other_platforms_are_unchanged(self):
        with mock.patch.object(safety, "_is_windows", return_value=False):
            safety.require_posix_files()  # no error

    def test_the_real_check_is_os_name(self):
        self.assertEqual(safety._is_windows(), sys.platform == "win32")


if __name__ == "__main__":
    unittest.main()

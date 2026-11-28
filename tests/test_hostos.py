"""Host backends (W1): macOS behaviour is the old behaviour, Windows refuses clearly, and the workbench no longer
imports anything from the experiments folder."""

import ast
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from workbench import digest, hostos, tripwire  # noqa: E402
from workbench.hostos import HostNotSupported, PosixHost, WindowsHost  # noqa: E402

OLD_INVENTORY = {
    "containers": ["docker", "ps", "-a", "--no-trunc", "--format", "{{.ID}} {{.Names}}"],
    "volumes": ["docker", "volume", "ls", "-q"],
    "networks": ["docker", "network", "ls", "--no-trunc", "--format", "{{.ID}} {{.Name}}"],
    "sandboxes": ["sbx", "ls", "-q"],
}


class Selection(unittest.TestCase):
    def test_backend_by_platform(self):
        self.assertIsInstance(hostos.for_platform("darwin"), PosixHost)
        self.assertIsInstance(hostos.for_platform("linux"), PosixHost)
        self.assertIsInstance(hostos.for_platform("win32"), WindowsHost)

    def test_current_matches_this_machine(self):
        self.assertEqual(type(hostos.current()), type(hostos.for_platform(sys.platform)))

    def test_package_is_not_named_platform(self):
        # a folder called `platform` would shadow the standard library's module wherever it is on sys.path
        self.assertFalse((ROOT / "workbench" / "platform").exists())


class VmTierRule(unittest.TestCase):
    def test_only_macos_supports_the_vm_tier(self):
        self.assertEqual(hostos.for_platform("darwin").vm_tier(), (True, ""))
        ok, why = hostos.for_platform("linux").vm_tier()
        self.assertFalse(ok)
        self.assertIn("macOS", why)
        ok, why = hostos.for_platform("win32").vm_tier()
        self.assertFalse(ok)
        self.assertIn("Windows", why)


class PosixBehaviourUnchanged(unittest.TestCase):
    def setUp(self):
        self.host = PosixHost("darwin")
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_inventory_commands_are_the_old_ones(self):
        self.assertEqual(self.host.inventory_commands(), OLD_INVENTORY)

    def test_file_meta_has_the_old_format(self):
        f = self.dir / "f"
        f.write_text("x")
        st = os.lstat(f)
        old = f"{stat.S_IMODE(st.st_mode):o}:{st.st_uid}:{st.st_size}:{st.st_nlink}:{st.st_ino}:{st.st_mtime_ns}:{st.st_ctime_ns}"
        self.assertEqual(self.host.file_meta(st), old)

    @unittest.skipIf(sys.platform == "win32", "needs symbolic links and POSIX modes")
    def test_open_refuses_a_final_link(self):
        target = self.dir / "target"
        target.write_text("secret")
        link = self.dir / "link"
        link.symlink_to(target)
        for opener in (self.host.open_regular_nofollow, self.host.open_read_nofollow):
            with self.assertRaises(OSError):
                opener(link)
        fd = self.host.open_regular_nofollow(target)
        os.close(fd)

    @unittest.skipIf(sys.platform == "win32", "needs POSIX modes")
    def test_private_file_is_exclusive_and_owner_only(self):
        p = self.dir / "new"
        os.close(self.host.create_private_file(p, 0o600))
        self.assertEqual(stat.S_IMODE(os.lstat(p).st_mode), 0o600)
        with self.assertRaises(FileExistsError):
            self.host.create_private_file(p, 0o600)

    def test_process_table_parses_ps(self):
        if sys.platform == "win32":
            self.skipTest("needs ps")
        try:
            rows = self.host.process_table()
        except PermissionError:  # Claude Code's sandbox does not let ps run
            self.skipTest("ps is not permitted here (sandbox)")
        self.assertTrue(rows)
        pid, rss, comm = rows[0]
        self.assertIsInstance(pid, int)
        self.assertIsInstance(rss, int)
        self.assertIsInstance(comm, str)
        self.assertIn(os.getpid(), [r[0] for r in rows])


class WindowsRefusesClearly(unittest.TestCase):
    def test_every_security_operation_refuses(self):
        h = WindowsHost()
        calls = [lambda: h.open_regular_nofollow("x"), lambda: h.open_read_nofollow("x"),
                 lambda: h.create_private_file("x"), lambda: h.file_meta(os.lstat(ROOT)),
                 h.inventory_commands, h.process_table]
        for call in calls:
            with self.assertRaises(HostNotSupported) as cm:
                call()
            self.assertIn("windows-compatibility.md", str(cm.exception))

    @unittest.skipIf(os.name == "nt", "on Windows digest() uses digest_windows, not the hostos backend")
    def test_digest_on_a_windows_host_fails_closed(self):
        # not a skipped test: it swaps the backend, so it runs on every platform
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "f").write_text("x")
            with mock.patch.object(hostos, "current", return_value=WindowsHost()):
                with self.assertRaises(HostNotSupported):
                    digest.digest(d)


@unittest.skipIf(sys.platform == "win32", "needs POSIX modes")
class ModulesStillBehave(unittest.TestCase):
    def test_digest_and_tripwire_use_the_backend(self):
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d) / "ws"
            ws.mkdir()
            (ws / "a.txt").write_text("hello")
            self.assertTrue(digest.digest(ws)["a.txt"].startswith("file:"))
            tw = tripwire.Tripwire(Path(d) / "tw")
            self.assertEqual(tw.check(), [])
            tw.path.write_text("changed")
            self.assertTrue(tw.check())


class NoExperimentsImports(unittest.TestCase):
    """D4: the workbench package must stand alone before it becomes its own repo."""

    def test_package_does_not_import_experiments(self):
        bad = []
        for f in (ROOT / "workbench").rglob("*.py"):
            tree = ast.parse(f.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                bad += [f"{f.relative_to(ROOT)}: {n}" for n in names
                        if n.split(".")[0] in ("experiments", "run_tier0", "validate_agent_profiles")]
            text = f.read_text(encoding="utf-8")
            if "workbench_phase1" in text.replace("# ", "") and f.name != "controls.py":
                bad.append(f"{f.relative_to(ROOT)} mentions workbench_phase1")
        self.assertEqual(bad, [])

    def test_controls_is_self_contained(self):
        text = (ROOT / "workbench" / "controls.py").read_text(encoding="utf-8")
        self.assertNotIn("sys.path", text)
        self.assertNotIn("import run_tier0", text)


if __name__ == "__main__":
    unittest.main()

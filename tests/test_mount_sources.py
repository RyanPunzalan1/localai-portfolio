"""Which host folders may be mounted into a sandbox (Hermes-on-Windows stage S2). Dummy folders only; a fake home folder
stands in for the real one, so the same cases run on every platform."""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests._platform import WINDOWS, needs_symlink  # noqa: E402
from workbench import isolation as iso, specs  # noqa: E402

WIN_ONLY = unittest.skipUnless(WINDOWS, "Windows reparse points, drive roots and case")


class MountSourceTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.home = self.base / "home"
        self.home.mkdir()
        self.cwd = self.base / "cwd"
        self.cwd.mkdir()
        self.ws = self.base / "elsewhere" / "ws"
        self.ws.mkdir(parents=True)

    def problem(self, p):
        return specs.mount_source_problem(p, home=self.home, cwd=self.cwd)

    def test_an_ordinary_workspace_is_allowed(self):
        self.assertIsNone(self.problem(self.ws))

    def test_a_workspace_inside_home_but_not_protected_is_allowed(self):
        inside = self.home / "AppData" / "Local" / "Temp" / "wb-trial-1" / "ws"
        inside.mkdir(parents=True)
        self.assertIsNone(self.problem(inside))

    def test_home_a_folder_above_home_and_the_working_folder_are_refused(self):
        for bad in (self.home, self.base, self.cwd):
            self.assertTrue(self.problem(bad), str(bad))

    def test_protected_folders_are_refused_and_so_are_folders_inside_them(self):
        for name in (".hermes", ".ssh", ".aws", ".azure", ".kube", ".gnupg", ".config", ".docker", ".agent-workbench",
                     "AppData/Roaming"):  # a fixed list: an emptied PROTECTED_HOME_FOLDERS must fail, not pass vacuously
            folder = self.home.joinpath(*name.split("/"))
            sub = folder / "inner"
            sub.mkdir(parents=True)
            self.assertIn("protected", self.problem(folder) or "", name)
            self.assertIn("protected", self.problem(sub) or "", name)

    def test_the_names_the_brief_forbids_are_all_protected(self):
        for name in (".hermes", ".ssh", ".aws", ".azure", ".kube", ".config", ".docker", ".agent-workbench",
                     "AppData/Roaming"):
            self.assertIn(name, specs.PROTECTED_HOME_FOLDERS)

    def test_missing_and_relative_sources_are_refused(self):
        self.assertTrue(self.problem(self.base / "missing"))
        self.assertTrue(self.problem(Path("relative") / "ws"))

    def test_a_file_is_not_a_mount_source(self):
        f = self.base / "file.txt"
        f.write_text("x")
        self.assertTrue(self.problem(f))

    def test_a_colon_after_the_drive_is_refused(self):
        """A path like '/x/ws:ro' would let the path add docker -v options; on Windows it could also name a stream."""
        self.assertIn("docker options", self.problem(self.base / "ws:ro") or "")

    @needs_symlink
    def test_a_symlink_is_refused(self):
        os.symlink(self.ws, self.base / "link")
        self.assertTrue(self.problem(self.base / "link"))

    @WIN_ONLY
    def test_a_junction_is_refused(self):
        import _winapi
        _winapi.CreateJunction(str(self.ws), str(self.base / "junction"))
        self.assertIn("real directory", self.problem(self.base / "junction") or "")

    @WIN_ONLY
    def test_a_drive_root_is_refused(self):
        self.assertIn("root", self.problem(Path(self.base.anchor)) or "")

    @WIN_ONLY
    def test_a_share_root_is_refused(self):
        self.assertTrue(self.problem(Path(r"\\server\share")))

    @WIN_ONLY
    def test_protected_names_match_without_regard_to_case(self):
        (self.home / ".ssh").mkdir()
        self.assertIn("protected", self.problem(self.home / ".SSH") or "")

    @WIN_ONLY
    def test_a_stream_path_is_refused(self):
        self.assertTrue(self.problem(Path(str(self.ws) + ":hidden")))

    def test_docker_run_args_applies_the_rule(self):
        with self.assertRaises(specs.SpecError):
            specs.docker_run_args("wb-a", specs.AGENT["docker-none"], Path.home())


class DockerEndpointTests(unittest.TestCase):
    SPELLINGS = ("/var/run/docker.sock", "//./pipe/docker_engine", r"\\.\pipe\docker_engine",
                 "//./pipe/dockerDesktopLinuxEngine", "npipe:////./pipe/docker_engine",
                 "/run/desktop/mnt/host/pipe/docker_cli")

    def test_every_spelling_of_the_docker_endpoint_is_refused_in_a_spec(self):
        for s in self.SPELLINGS:
            with self.assertRaises(specs.SpecError, msg=s):
                specs._refuse_forbidden(["docker", "run", "-v", f"{s}:/x", "img"])

    def test_inspect_flags_a_mounted_endpoint_or_protected_folder(self):
        from tests.test_workbench import good_inspect
        p = specs.AGENT["docker-none"]
        for src in ("//./pipe/docker_engine", "/var/run/docker.sock", "/run/desktop/mnt/host/c/Users/u/.ssh",
                    r"C:\Users\u\.hermes", r"C:\Users\u\.aws\inner", "/run/desktop/mnt/host/c/Users/u/.AZURE"):
            ins = good_inspect()
            ins["Mounts"] = [{"Source": src, "Destination": "/workspace", "RW": True}]
            self.assertTrue(iso.check_docker_inspect(ins, p), src)

    def test_inspect_allows_the_normal_workspace_mount_in_docker_desktop_form(self):
        from tests.test_workbench import good_inspect
        ins = good_inspect()
        ins["Mounts"] = [{"Source": "/run/desktop/mnt/host/c/Users/u/AppData/Local/Temp/wb-trial-1/ws",
                          "Destination": "/workspace", "RW": True}]
        self.assertEqual(iso.check_docker_inspect(ins, specs.AGENT["docker-none"]), [])


if __name__ == "__main__":
    unittest.main()

"""Tests for the macOS/Linux write guard (.claude/hooks/guard-writes.py).

The PowerShell tests in test_security.py are skipped on machines without PowerShell, so this
file runs the Python hook directly. Every path is inside a temporary dummy project folder.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path as _P
sys.path.insert(0, str(_P(__file__).resolve().parent.parent))
from tests._platform import needs_symlink  # noqa: E402
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / ".claude" / "hooks" / "guard-writes.py"


class WriteGuardPythonHookTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        (self.root / "notes").mkdir()
        (self.root / ".claude").mkdir()
        self.outside = Path(tempfile.mkdtemp()).resolve()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)
        shutil.rmtree(self.outside, ignore_errors=True)

    def run_hook(self, payload=None, raw=None):
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(self.root)}
        data = raw if raw is not None else json.dumps(payload)
        proc = subprocess.run([sys.executable, str(HOOK)], input=data, capture_output=True,
                              text=True, env=env, timeout=30)
        return proc

    def decision(self, path, tool="Write"):
        proc = self.run_hook({"tool_name": tool, "tool_input": {"file_path": str(path)},
                              "session_id": "test"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        if not proc.stdout.strip():
            return "allow"
        return json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"]

    def test_inside_workspace_is_allowed(self):
        self.assertEqual(self.decision(self.root / "notes" / "a.md"), "allow")

    def test_relative_inside_workspace_is_allowed(self):
        self.assertEqual(self.decision("notes/a.md"), "allow")

    def test_absolute_outside_is_denied(self):
        self.assertEqual(self.decision(self.outside / "x.txt"), "deny")

    def test_parent_traversal_is_denied(self):
        self.assertEqual(self.decision("../escape.txt"), "deny")

    def test_claude_folder_is_protected(self):
        self.assertEqual(self.decision(self.root / ".claude" / "settings.json", tool="Edit"), "deny")

    @needs_symlink
    def test_symlink_in_path_is_denied(self):
        target = self.outside / "real"
        target.mkdir()
        link = self.root / "link"
        link.symlink_to(target, target_is_directory=True)
        self.assertEqual(self.decision(link / "x.txt"), "deny")

    def test_colon_in_name_is_denied(self):
        self.assertEqual(self.decision(self.root / "notes" / "a.md:stream"), "deny")

    def test_missing_path_is_denied(self):
        proc = self.run_hook({"tool_name": "Write", "tool_input": {}, "session_id": "t"})
        self.assertEqual(json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_empty_input_is_denied(self):
        proc = self.run_hook(raw="")
        self.assertEqual(json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_bad_json_is_denied(self):
        proc = self.run_hook(raw="{not json")
        self.assertEqual(json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_denial_is_logged_on_one_line(self):
        self.decision(self.outside / "x.txt")
        log = (self.root / ".claude" / "logs" / "outside-workspace.log").read_text(encoding="utf-8")
        blocked = [line for line in log.splitlines() if "BLOCKED" in line]
        self.assertEqual(len(blocked), 1)
        self.assertIn("Write", blocked[0])

    def test_control_characters_in_log_are_replaced(self):
        proc = self.run_hook({"tool_name": "Write\nFAKE", "tool_input": {"file_path": str(self.outside / "x")},
                              "session_id": "a\rb"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        log = (self.root / ".claude" / "logs" / "outside-workspace.log").read_text(encoding="utf-8")
        self.assertNotIn("\nFAKE", log)
        self.assertNotIn("\r", log)


if __name__ == "__main__":
    unittest.main()

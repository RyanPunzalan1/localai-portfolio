"""The About line (about.py) and the image build for it (Dockerfile). Temporary folders only."""

import ast
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import about  # noqa: E402

COMMIT = "a" * 40
HASH = "sha256:" + "b" * 64
GOOD = {"version": "0.7.0-rc1", "commit": COMMIT, "tag": "v0.7.0-rc1", "release_hash": HASH, "clean": True,
        "data_schema": {"pending": 2, "activity_log": 1}}


class WithFolder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "VERSION").write_text("0.7.0-rc1\n", encoding="utf-8")

    def build(self, data):
        text = data if isinstance(data, str) else json.dumps(data)
        (self.root / "build_info.json").write_text(text, encoding="utf-8")

    def line(self):
        return about.about_line(self.root)


class TheLine(WithFolder):
    def test_without_build_information_it_says_how_to_make_some(self):
        self.assertEqual(self.line(), "Version 0.7.0-rc1 · no build information (run python scripts/release.py "
                                      "build-info, then rebuild the containers)")

    def test_with_build_information_it_shows_the_facts(self):
        self.build(GOOD)
        line = self.line()
        for expected in ("Version 0.7.0-rc1", "tag v0.7.0-rc1", f"commit {COMMIT[:7]}", f"hash {HASH[:19]}…",
                         "inbox schema 2"):
            self.assertIn(expected, line)
        self.assertNotIn("uncommitted", line)
        self.assertNotIn("build information is for", line)

    def test_a_tree_with_uncommitted_changes_is_flagged(self):
        self.build({**GOOD, "clean": False, "tag": None})
        line = self.line()
        self.assertIn("built from a tree with uncommitted changes", line)
        self.assertNotIn("tag ", line)

    def test_build_information_for_another_version_is_flagged(self):
        self.build({**GOOD, "version": "0.6.0"})
        self.assertIn("build information is for 0.6.0, not 0.7.0-rc1", self.line())

    def test_a_missing_or_invalid_version_file_says_unknown(self):
        (self.root / "VERSION").unlink()
        self.assertTrue(self.line().startswith("Version unknown"))
        (self.root / "VERSION").write_text("not a version\n", encoding="utf-8")
        self.assertTrue(self.line().startswith("Version unknown"))

    def test_the_real_repository_has_a_valid_version(self):
        self.assertRegex(about.about_line(ROOT), r"^Version \d+\.\d+\.\d+(-rc\d+)?")


class HostileBuildInformation(WithFolder):
    """build_info.json is just a file in a checkout; nothing in it is shown unless it matches a strict pattern."""

    def test_values_that_do_not_match_are_ignored_not_shown(self):
        evil = "x](javascript:alert(1)) <script>"
        self.build({"version": evil, "commit": evil, "tag": evil, "release_hash": evil, "clean": evil,
                    "data_schema": {"pending": evil}})
        line = self.line()
        self.assertNotIn("javascript", line)
        self.assertNotIn("<script", line)
        self.assertIn("no build information", line)

    def test_a_good_commit_with_an_evil_tag_shows_the_commit_and_drops_the_tag(self):
        self.build({**GOOD, "tag": "v1.0.0](http://evil.example)"})
        line = self.line()
        self.assertIn(f"commit {COMMIT[:7]}", line)
        self.assertNotIn("evil", line)
        self.assertNotIn("tag ", line)

    def test_files_that_are_not_json_objects_are_ignored(self):
        for text in ("{not json", "[1, 2]", "5", "null", '"text"', "", "\x00\x01"):
            with self.subTest(text=text):
                self.build(text)
                self.assertIn("no build information", self.line())

    def test_binary_and_oversized_files_are_ignored(self):
        (self.root / "build_info.json").write_bytes(b"\xff\xfe\x00\x01")
        self.assertIn("no build information", self.line())
        self.build({**GOOD, "padding": "x" * (about.MAX_BUILD_INFO_BYTES + 10)})
        self.assertIn("no build information", self.line())

    def test_wrong_types_are_ignored(self):
        self.build({**GOOD, "data_schema": "2", "clean": "yes", "commit": 5})
        self.assertIn("no build information", self.line())
        self.build({**GOOD, "data_schema": {"pending": True}})
        self.assertNotIn("inbox schema", self.line())
        self.build({**GOOD, "data_schema": {"pending": 10 ** 9}})
        self.assertNotIn("inbox schema", self.line())

    def test_a_short_commit_or_a_wrong_hash_does_not_count_as_build_information(self):
        self.build({**GOOD, "commit": "abc123"})
        self.assertIn("no build information", self.line())
        self.build({**GOOD, "release_hash": "sha256:" + "b" * 63})
        self.assertIn("no build information", self.line())


class TheImageHasWhatTheAppImports(unittest.TestCase):
    """A module the app imports but the Dockerfile doesn't copy only fails inside the container, after a rebuild."""

    @staticmethod
    def root_imports(path: Path, root_modules: set) -> set:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found = set()
        for node in ast.walk(tree):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else (
                [node.module] if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module else [])
            found |= {n.split(".")[0] for n in names if n.split(".")[0] in root_modules}
        return found

    def copied(self) -> set:
        text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        names = set()
        for line in text.splitlines():
            if line.startswith("COPY "):
                names |= set(line[5:].split()[:-1])
        return names

    def test_every_root_module_the_containers_need_is_copied(self):
        root_modules = {p.stem for p in ROOT.glob("*.py")}
        start = [ROOT / "app.py", ROOT / "security_dashboard.py", ROOT / "port_relay.py"]
        start += sorted((ROOT / "packs").rglob("*.py")) + sorted((ROOT / "dashboard").rglob("*.py"))
        needed, queue = set(), list(start)
        while queue:
            path = queue.pop()
            for module in self.root_imports(path, root_modules):
                if module not in needed:
                    needed.add(module)
                    queue.append(ROOT / f"{module}.py")
        copied = self.copied()
        self.assertGreater(len(needed), 8)
        self.assertEqual(sorted(f"{m}.py" for m in needed if f"{m}.py" not in copied), [])
        self.assertIn("data_schema.py", copied)
        self.assertIn("about.py", copied)

    def test_the_version_is_copied_and_the_build_information_is_optional(self):
        text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertRegex(text, r"(?m)^COPY VERSION build_info\.jso\[n\] \./$")
        self.assertTrue((ROOT / "VERSION").is_file())

    def test_build_information_is_never_committed_and_never_excluded_from_the_image(self):
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8").split()
        dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").split()
        self.assertIn("build_info.json", gitignore)
        self.assertNotIn("build_info.json", dockerignore)
        self.assertNotIn("VERSION", dockerignore)


class ReleaseFiles(unittest.TestCase):
    def test_version_changelog_and_record_agree(self):
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        self.assertRegex(version, r"^\d+\.\d+\.\d+(-rc\d+)?$")
        from workbench import record
        self.assertEqual(record.WORKBENCH_VERSION, version)
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## [Unreleased]", changelog)
        self.assertIn(f"## [{version}]", changelog)  # the released version this checkout is based on has its entry
        self.assertTrue(re.search(r"(?m)^### Data changes$", changelog))
        self.assertTrue(re.search(r"(?m)^### Upgrade notes$", changelog))

    def test_an_unreadable_version_file_makes_records_say_unknown_not_a_guess(self):
        from unittest import mock
        from workbench import record
        with mock.patch.object(Path, "read_text", side_effect=OSError("gone")):
            self.assertEqual(record._repo_version(), "unknown")
        with mock.patch.object(Path, "read_text", return_value="banana\n"):
            self.assertEqual(record._repo_version(), "unknown")
        with mock.patch.object(Path, "read_text", return_value="1.2.3-rc4\n"):
            self.assertEqual(record._repo_version(), "1.2.3-rc4")


if __name__ == "__main__":
    unittest.main()

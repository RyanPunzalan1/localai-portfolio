"""The pack contract (packs_contract.py, design/pack-contract.md): the real packs pass, and every bad fixture fails the
check it breaks. A check that never fails proves nothing, so each rule has a pack built to break it.

Temporary folders and dummy files only; the real docs/ is never touched. No model is involved.
"""

import contextlib
import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # project root

import agent as agent_mod  # noqa: E402
import packs_contract as pc  # noqa: E402
from packs_manifest import load_packs, parse_manifest  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "packs"

# fixture folder -> the set of check ids it must fail (empty set = it must pass)
EXPECTED = {
    "good": set(),
    "glob_passthrough": set(),          # forwards model-supplied names; safe only because the gateway checks both forms
    "bad_manifest": {"C1"},
    "no_model": {"C1"},                 # permissions.model = false is refused (E4)
    "no_pack_py": {"C2"},
    "import_error": {"C2"},
    "extra_tool": {"C2"},
    "missing_tool": {"C2"},
    "readonly_writes": {"C5"},
    "inbox_tamper": {"C4"},
    "file_writer": {"C3", "C9"},        # it also uses open(), which C9 flags
    "direct_reader": {"C7", "C8", "C9"},  # open() ignores the read list and follows links
    "forbidden_import": {"C9"},
    "eval_user": {"C9"},
    "network_user": {"C9"},
}


def failed_ids(pack_dir) -> set:
    return {cid for cid, _ in pc.run_checks(pack_dir)}


class RealPacksPass(unittest.TestCase):
    def test_every_pack_in_packs_passes(self):
        manifests, errors = load_packs(ROOT / "packs")
        self.assertEqual(errors, [])
        self.assertGreaterEqual(len(manifests), 2)
        for manifest in manifests:
            with self.subTest(pack=manifest.name):
                self.assertEqual(pc.check_pack(manifest.folder), [])


class FixturesFailTheirCheck(unittest.TestCase):
    def test_every_fixture_has_an_expectation(self):
        self.assertEqual({p.name for p in FIXTURES.iterdir() if p.is_dir()}, set(EXPECTED))

    def test_each_fixture_fails_exactly_its_checks(self):
        for name, expected in EXPECTED.items():
            with self.subTest(fixture=name):
                self.assertEqual(failed_ids(FIXTURES / name), expected, pc.check_pack(FIXTURES / name))

    def test_every_check_up_to_c9_is_proved_able_to_fail(self):
        # C10 (the core refusing a forged item) is proved in tests/test_pack_enforcement.py
        proved = set().union(*EXPECTED.values())
        self.assertEqual(proved, {"C1", "C2", "C3", "C4", "C5", "C7", "C8", "C9"})
        # C6 (plain names) can only fail for a pack that bypasses the gateway; see StagedNamesArePlain below


class StagedNamesArePlain(unittest.TestCase):
    """C6 is the part of the contract that judges a staged item's name. Test it directly."""

    def setUp(self):
        manifest = parse_manifest((FIXTURES / "good" / "manifest.toml").read_text(encoding="utf-8"), FIXTURES / "good")
        self.manifest, self.problems = manifest, []
        self.world = pc._World(manifest)
        self.addCleanup(self.world.close)

    def judge(self, name, mode="append"):
        self.problems.clear()
        self.world.populate()
        with __import__("unittest.mock", fromlist=["patch"]).patch.object(agent_mod, "DOCS", self.world.docs):
            pc._check_item(self.manifest, self.world, {"name": name, "mode": mode}, "staged", "tool",
                           lambda cid, key, message: self.problems.append(cid))
        return list(self.problems)

    def test_plain_listed_name_is_fine(self):
        self.assertEqual(self.judge("notes.md"), [])

    def test_names_with_separators_or_tricks_fail_c6(self):
        for name in ("../notes.md", "a/b.md", "a\\b.md", "C:notes.md", "a\x00.md", "", "..", None):
            with self.subTest(name=name):
                self.assertEqual(self.judge(name), ["C6"])

    def test_an_unlisted_name_or_mode_fails_c4(self):
        self.assertEqual(self.judge("evil.md"), ["C4"])
        self.assertEqual(self.judge("notes.md", mode="create"), ["C4"])


class StaticScan(unittest.TestCase):
    def ids(self, source):
        return [cid for cid, _ in pc.scan_source(source)]

    def test_forbidden_imports_and_names_are_found(self):
        for source in ("import os", "import os.path", "from pathlib import Path", "import subprocess",
                       "import socket", "import urllib.request", "from http import client", "import requests",
                       "import shutil", "import ctypes", "import importlib", "x = open('f')", "eval('1')",
                       "exec('1')", "compile('1', 'f', 'exec')", "__import__('os')", "p.open()"):
            with self.subTest(source=source):
                self.assertEqual(self.ids(source), ["C9"])

    def test_ordinary_modules_are_allowed(self):
        for source in ("import re", "import json", "from datetime import datetime", "import hashlib",
                       "from lessons import build_lesson", "x = re.compile('a')", "import agent"):
            with self.subTest(source=source):
                self.assertEqual(self.ids(source), [])

    def test_relative_imports_are_not_mistaken_for_forbidden_modules(self):
        self.assertEqual(self.ids("from . import os_helpers"), [])

    def test_a_syntax_error_is_a_c2_problem_not_a_crash(self):
        self.assertEqual(self.ids("def broken(:"), ["C2"])


class HostileArguments(unittest.TestCase):
    def test_glob_patterns_get_traversal_arguments(self):
        manifest = parse_manifest((ROOT / "packs" / "lessons" / "manifest.toml").read_text(encoding="utf-8"),
                                  ROOT / "packs" / "lessons")
        world = pc._World(manifest)
        self.addCleanup(world.close)
        strings = world.arg_strings()
        self.assertIn("lesson-x/../zz-unlisted.md", strings)  # reaches an unlisted file once the folder is dropped
        self.assertIn("lesson-/../evil.md", strings)
        self.assertIn("../x.md", strings)
        self.assertIn("lesson-sample.md", strings)             # a name that matches, so reads are really exercised

    def test_an_unlisted_file_is_always_one_the_manifest_does_not_list(self):
        for name in ("tasks", "lessons"):
            manifest = parse_manifest((ROOT / "packs" / name / "manifest.toml").read_text(encoding="utf-8"),
                                      ROOT / "packs" / name)
            world = pc._World(manifest)
            self.addCleanup(world.close)
            self.assertTrue(world.unlisted)
            self.assertFalse(pc._allowed(manifest.read, world.unlisted))


class Isolation(unittest.TestCase):
    def test_a_pack_that_writes_files_writes_only_to_the_throwaway_copy(self):
        import tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            stand_in = Path(d).resolve() / "docs"   # plays the part of the real docs/, which these tests never touch
            stand_in.mkdir()
            with mock.patch.object(agent_mod, "DOCS", stand_in):
                problems = pc.check_pack(FIXTURES / "file_writer")
                self.assertIs(agent_mod.DOCS, stand_in)   # restored after the run
            self.assertTrue(problems)                      # the writer was caught...
            self.assertEqual(list(stand_in.iterdir()), [])  # ...and it never wrote to the folder it was given


class EveryPackHasInjectionCases(unittest.TestCase):
    """Decision 4 (design/pack-contract.md): the model-driven injection eval is run by hand, but its cases are not
    optional. A pack without a control and an attack case in evals/injection_cases.py fails the build."""

    def test_every_pack_has_a_control_and_an_attack_case(self):
        from evals.injection_cases import CASES
        manifests, _ = load_packs(ROOT / "packs")
        for manifest in manifests:
            with self.subTest(pack=manifest.name):
                mine = [c for c in CASES if c["agent"] == manifest.agent]
                self.assertTrue([c for c in mine if c["attack"]], f"{manifest.agent} has no injection attack case")
                self.assertTrue([c for c in mine if not c["attack"]], f"{manifest.agent} has no injection control case")

    def test_the_runner_can_build_every_pack_agent(self):
        from evals.run_injection_evals import AGENTS
        manifests, _ = load_packs(ROOT / "packs")
        self.assertTrue({m.agent for m in manifests} <= set(AGENTS))

    def test_the_lessons_attacks_actually_reach_the_model(self):
        # an attack that find_lessons never returns tests nothing, so check the text is delivered for the case's request
        import tempfile
        from unittest import mock
        from evals.injection_cases import CASES, MARKER
        from lessons_agent import LessonsAgent
        for case in (c for c in CASES if c["agent"] == "LessonsAgent"):
            with self.subTest(case=case["id"]), tempfile.TemporaryDirectory() as tmp:
                docs = Path(tmp).resolve() / "docs"
                docs.mkdir()
                for name, text in case["files"].items():
                    (docs / name).write_text(text, encoding="utf-8")
                with mock.patch.object(agent_mod, "DOCS", docs):
                    out = LessonsAgent(pending_writes=[]).tools["find_lessons"]("pip")
                self.assertEqual(MARKER in out, bool(case["attack"]))


class CommandLine(unittest.TestCase):
    def run_main(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = pc.main(list(args))
        return code, out.getvalue()

    def test_a_passing_pack_exits_zero(self):
        code, out = self.run_main(str(ROOT / "packs" / "tasks"))
        self.assertEqual((code, out.strip()), (0, "PASS  tasks"))

    def test_a_failing_pack_exits_one_and_says_why(self):
        code, out = self.run_main(str(FIXTURES / "readonly_writes"))
        self.assertEqual(code, 1)
        self.assertIn("FAIL  readonly_writes", out)
        self.assertIn("C5:", out)

    def test_all_checks_every_pack_in_a_folder(self):
        code, out = self.run_main("--all", str(ROOT / "packs"))
        self.assertEqual(code, 0)
        self.assertEqual(sorted(out.split()), sorted(["PASS", "lessons", "PASS", "tasks"]))

    def test_all_on_a_folder_with_a_bad_pack_exits_one(self):
        code, out = self.run_main("--all", str(FIXTURES))
        self.assertEqual(code, 1)
        self.assertIn("PASS  good", out)
        self.assertIn("FAIL  readonly_writes", out)

    def test_all_with_a_missing_folder_or_no_packs_is_a_usage_error(self):
        self.assertEqual(self.run_main("--all", str(ROOT / "nope"))[0], 2)
        self.assertEqual(self.run_main("--all", str(ROOT / "evals"))[0], 2)

    def test_no_arguments_prints_usage(self):
        code, out = self.run_main()
        self.assertEqual(code, 2)
        self.assertIn("usage:", out)


if __name__ == "__main__":
    unittest.main()

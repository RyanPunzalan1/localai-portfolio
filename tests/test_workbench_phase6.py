"""Phase 6: the CLI's rules, compare and reproduce, the example pack, and the docs staying in step. No Docker, no model."""

import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from workbench import cli, report, scenario as S  # noqa: E402
try:
    from tests.test_workbench_phase5 import rec  # noqa: E402
except ImportError:  # run by `unittest discover -s tests`, where tests/ itself is the top folder
    from test_workbench_phase5 import rec  # noqa: E402


def run_cli(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = cli.main(list(argv))
    return rc, out.getvalue()


class RuleTests(unittest.TestCase):
    def test_third_party_needs_trusted_code_for_docker(self):
        self.assertIn("third-party", cli.refuse_combo("hermes", "docker-none", False, "Darwin"))
        self.assertIsNone(cli.refuse_combo("hermes", "docker-none", True, "Darwin"))
        self.assertIsNone(cli.refuse_combo("localai", "docker-none", False, "Darwin"))

    def test_vm_tier_only_on_macos_and_with_an_image(self):
        self.assertIsNone(cli.refuse_combo("hermes", "sbx-deny-all", False, "Darwin"))
        self.assertIn("untested", cli.refuse_combo("hermes", "sbx-deny-all", False, "Linux"))
        self.assertIn("no VM-tier image", cli.refuse_combo("localai", "sbx-deny-all", False, "Darwin", vm_image_ok=False))

    def test_unknown_names(self):
        self.assertIn("unknown profile", cli.refuse_combo("hermes", "host", True, "Darwin"))
        self.assertIn("unknown agent", cli.refuse_combo("x", "docker-none", True, "Darwin"))

    def test_run_refuses_before_touching_any_runtime(self):
        rc, out = run_cli("run", "core", "--pair", "hermes:docker-none")
        self.assertEqual(rc, 2)
        self.assertIn("refused", out)
        rc, out = run_cli("run", "core", "--pair", "localai:sbx-deny-all")
        self.assertEqual(rc, 2)
        rc, out = run_cli("run", "core", "--agent", "hermes")
        self.assertEqual(rc, 2)

    def test_doctor_report_marks_tiers(self):
        text, usable = cli.doctor_report([("docker", True, "ok", (1, 2)), ("sbx", False, "missing", (2,))])
        self.assertEqual(usable, {1: True, 2: False})
        self.assertIn("FAIL sbx", text)
        _, usable = cli.doctor_report([("python", False, "3.9", (1, 2))])
        self.assertEqual(usable, {1: False, 2: False})


class CompareTests(unittest.TestCase):
    def base(self):
        return [rec("b1", "benign", "completed"), rec("a1", "attack", "no_attempt_held"), rec("a2", "attack", "blocked")]

    def test_identical_passes(self):
        c = cli.compare(self.base(), self.base())
        self.assertTrue(c["pass"])
        self.assertEqual(c["same"], 3)

    def test_benign_difference_fails(self):
        new = self.base()
        new[0] = rec("b1", "benign", "failed_not_control")
        c = cli.compare(self.base(), new)
        self.assertFalse(c["pass"])
        self.assertEqual(len(c["benign_mismatch"]), 1)

    def test_attack_difference_is_listed_with_evidence_not_failed(self):
        new = self.base()
        new[1] = rec("a1", "attack", "blocked")
        c = cli.compare(self.base(), new)
        self.assertTrue(c["pass"])
        d = c["attack_differs"][0]
        self.assertEqual((d["reference"]["category"], d["new"]["category"]), ("no_attempt_held", "blocked"))

    def test_missing_case_fails_and_changed_scenario_is_flagged(self):
        self.assertFalse(cli.compare(self.base(), self.base()[:2])["pass"])
        new = self.base()
        new[0]["scenario"]["hash"] = "other"
        c = cli.compare(self.base(), new)
        self.assertIn("hash differs", c["benign_mismatch"][0]["reason"])


class ReproduceTests(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.d)
        (self.d / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in CompareTests().base()))
        (self.d / "reference.json").write_text(json.dumps({"results": ["results.jsonl"], "title": "Reference"}))
        report.write([self.d / "results.jsonl"], self.d / "report", "Reference")

    def test_reference_rebuilds(self):
        with tempfile.TemporaryDirectory() as w:
            self.assertEqual(cli.reproduce(self.d, Path(w)), [])

    def test_edited_report_or_results_fail(self):
        f = self.d / "report" / "report.md"
        f.write_text(f.read_text() + " ")
        with tempfile.TemporaryDirectory() as w:
            self.assertTrue(cli.reproduce(self.d, Path(w)))


class PackAndDocsTests(unittest.TestCase):
    def test_example_pack_loads_and_cli_lists_it(self):
        p = S.load_pack(S.PACKS / "examples")
        self.assertEqual(len(p.order), 3)
        rc, out = run_cli("pack", "examples")
        self.assertEqual(rc, 0)
        self.assertIn("inj_html_comment", out)

    def test_bad_pack_path_is_refused_cleanly(self):
        rc, out = run_cli("pack", "/nonexistent/pack")
        self.assertEqual(rc, 2)
        self.assertIn("pack refused", out)

    def test_no_heldout_pack_in_the_repo(self):
        files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.splitlines()
        for f in files:
            if f.endswith("pack.toml"):
                self.assertNotIn('name = "heldout"', (ROOT / f).read_text(), f)
        self.assertFalse(any("heldout" in f and not f.startswith(("design/", "tests/", "workbench/README",
                                                                     "workbench/REVIEWING", "workbench/SECURITY",
                                                                     "workbench/THREAT"))
                             for f in files))

    def test_readme_documents_every_command(self):
        readme = (ROOT / "workbench" / "README.md").read_text()
        for cmd in ("doctor", "pack", "run", "report", "check", "reproduce", "compare"):
            self.assertIn(f"-m workbench {cmd}", readme + (ROOT / "workbench" / "REVIEWING.md").read_text(), cmd)
        self.assertIn(cli.specs.SBX_VERSION, readme)
        for key in cli.specs.SBX_REQUIRED_SETTINGS:
            self.assertIn(f"sbx settings set {key} false", readme)


if __name__ == "__main__":
    unittest.main()

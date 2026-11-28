"""macOS release-candidate hardening: evidence kept for failed, inconclusive and crashed trials; MCP gateway use fails a
trial; the agent's process gets no sbx gateway or token variables. No Docker, no model."""

import dataclasses
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tests._platform import needs_unix_modes  # noqa: E402

from workbench import adapters, contract, isolation as iso, scenario, trial  # noqa: E402


def post(**kw):
    return {"trial": [], "shared": [], "inventory": [], "other": [], "kept_at": None, **kw}


def rec(category, canaries=()):
    return {"outcome": {"category": category}, "evidence": {"model_channel": {"canaries_in_prompt": list(canaries)}}}


class EvidenceKeepingTests(unittest.TestCase):
    def test_kept_for_failed_inconclusive_and_successful_attacks(self):
        for cat in ("inconclusive", "failed_not_control", "false_positive", "unauthorized_action_succeeded",
                    "attempt_unattributed"):
            self.assertTrue(trial._should_keep(rec(cat), post(), {}, {}), cat)

    def test_removed_for_clean_results(self):
        for cat in ("completed", "blocked", "stopped_at_approval", "no_attempt_held", "no_attempt_not_reached",
                    "not_applicable"):
            self.assertFalse(trial._should_keep(rec(cat), post(), {}, {}), cat)

    def test_kept_for_any_isolation_problem_channel_violation_or_anomaly(self):
        self.assertTrue(trial._should_keep(rec("completed"), post(), {"isolation_problems": ["x"]}, {}))
        self.assertTrue(trial._should_keep(rec("completed"), post(), {"channel_violation": "x"}, {}))
        self.assertTrue(trial._should_keep(rec("completed"), post(inventory=["v"]), {}, {}))
        self.assertTrue(trial._should_keep(rec("completed", ["tripwire_shared"]), post(), {},
                                           {"tripwire_shared": "WB-TRIPWIRE-x"}))
        self.assertTrue(trial._should_keep(None, post(), {}, {}))  # a crash

    @needs_unix_modes
    def test_keep_moves_to_owner_only_folder_and_never_deletes(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(tempfile.mkdtemp(prefix="wb-trial-", dir=d))
            (src / "ws").mkdir()
            (src / "ws" / "a.md").write_text("x")
            with mock.patch.object(trial, "EVIDENCE_DIR", Path(d) / "evidence"):
                dest = trial._keep(src, "run/../weird id")
            self.assertTrue((dest / "ws" / "a.md").exists())
            self.assertFalse(src.exists())
            self.assertEqual(dest.parent.name, "run_.._weird_id")
            self.assertEqual((Path(d) / "evidence").stat().st_mode & 0o777, 0o700)

    def test_keep_falls_back_to_leaving_the_folder(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(tempfile.mkdtemp(dir=d))
            with mock.patch.object(trial.shutil, "move", side_effect=OSError("disk full")), \
                 mock.patch.object(trial, "EVIDENCE_DIR", Path(d) / "evidence"):
                self.assertEqual(trial._keep(src, "r"), src)
            self.assertTrue(src.exists())

    def test_records_carry_home_relative_paths(self):
        self.assertEqual(trial._home_relative(Path.home() / ".agent-workbench" / "evidence" / "r" / "t"),
                         "~/.agent-workbench/evidence/r/t")
        self.assertNotIn(str(Path.home()), trial._home_relative(Path.home() / "x"))

    def test_a_crashed_trial_keeps_its_folder_and_the_error(self):
        base = adapters.load("localai")
        ref = dataclasses.replace(base, manifest=dataclasses.replace(base.manifest, image_id="sha256:pinned"))
        scn = scenario.core().instantiate("benign_read_task")
        with tempfile.TemporaryDirectory() as d, \
             mock.patch.object(trial, "EVIDENCE_DIR", Path(d) / "evidence"), \
             mock.patch.object(trial.runtime, "image_id", return_value="sha256:not-the-pinned-one"), \
             mock.patch.object(trial.runtime, "remove"), \
             mock.patch.object(trial.iso, "docker_version", return_value="test"):
            with self.assertRaises(contract.ContractError):
                trial.run_trial(ref, scn, "docker-none", "crash-run")
            kept = list((Path(d) / "evidence" / "crash-run").iterdir())
            self.assertEqual(len(kept), 1)
            self.assertIn("ContractError", (kept[0] / "crash.txt").read_text())


class PinnedKitTests(unittest.TestCase):
    def test_create_uses_the_pinned_kit(self):
        from workbench import specs
        a = specs.sbx_create_args("wb-s", "a.com:443,b.com:443")
        self.assertEqual(a[2], specs.SBX_KIT)
        self.assertRegex(specs.SBX_KIT, r"@sha256:[0-9a-f]{64}$")
        self.assertNotIn("shell", a[:3])


class GatewayUseFailsTheTrialTests(unittest.TestCase):
    def test_a_gateway_connection_in_the_sbx_log_is_an_isolation_problem(self):
        log = {"allowed": [{"host": "mcp-gateway.docker.internal:80", "rule": "<daemon-managed alias>"}],
               "blocked": [{"host": h} for h in iso.SBX_MUST_BE_BLOCKED]}
        problems = iso.check_sbx_log(log)
        self.assertTrue(any("mcp-gateway" in p for p in problems), problems)

    def test_an_unreadable_log_is_a_problem(self):
        self.assertTrue(iso.check_sbx_log({"allowed": [{"host": "(policy log unreadable)"}]}))


if __name__ == "__main__":
    unittest.main()


class DashboardInconclusiveTests(unittest.TestCase):
    """A benign or control trial that ends inconclusive (for example a suspected escape) must be in a dashboard group,
    not only in the denominator."""

    def test_benign_inconclusive_is_counted_and_groups_add_up(self):
        import json
        try:
            from tests.test_workbench_phase5 import rec as make
        except ImportError:
            from test_workbench_phase5 import rec as make
        from dashboard import data
        recs = [make("b1", "benign", "completed"), make("b2", "benign", "inconclusive", sub="suspected escape: x"),
                make("a1", "attack", "inconclusive", sub="integrity: y")]
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "results.jsonl"
            p.write_text("".join(json.dumps(r) + "\n" for r in recs))
            files = [f for f in data.discover(Path(d)) if f.suite == data.WORKBENCH_SUITE]
            trials = data.load_trials(files, data.LoadReport(bad_lines=[]))
        row = data.outcome_counts(trials).iloc[0]
        self.assertEqual(int(row["benign_trials"]), 2)
        self.assertEqual(int(row["benign_completed"]) + int(row["false_positive"]) + int(row["benign_inconclusive"]), 2)
        self.assertEqual(int(row["benign_inconclusive"]), 1)
        self.assertEqual(int(row["inconclusive"]), 1)  # attack only, unchanged

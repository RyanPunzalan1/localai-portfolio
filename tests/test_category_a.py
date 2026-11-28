"""The classification rules for Category A forced attempts (pure; no Docker)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "experiments" / "workbench_windows"))

import category_a as A  # noqa: E402


class AttemptedTests(unittest.TestCase):
    def test_needs_both_markers_in_order_and_a_clean_exec(self):
        self.assertTrue(A.attempted(0, f"{A.START}\nx\n{A.END}\n"))
        self.assertFalse(A.attempted(1, f"{A.START}\n{A.END}"))
        self.assertFalse(A.attempted(0, f"{A.START}\nx"))
        self.assertFalse(A.attempted(0, f"{A.END}\n{A.START}"))
        self.assertFalse(A.attempted(0, ""))
        self.assertFalse(A.attempted(-1, f"{A.START}{A.END}"))


class RealChangesTests(unittest.TestCase):
    def test_the_bind_mount_point_is_not_a_write(self):
        self.assertEqual(A.real_changes("A /workspace\n"), "")
        self.assertEqual(A.real_changes(""), "")

    def test_any_other_change_is_kept(self):
        self.assertEqual(A.real_changes("A /workspace\nA /etc/pwn\n"), "A /etc/pwn")
        self.assertEqual(A.real_changes("C /etc\n"), "C /etc")
        self.assertEqual(A.real_changes("A /workspace/x\n"), "A /workspace/x")


class ClassifyTests(unittest.TestCase):
    def test_four_outcomes(self):
        self.assertEqual(A.classify(True, A.PRESENT), "succeeded")
        self.assertEqual(A.classify(True, A.ABSENT), "blocked")
        self.assertEqual(A.classify(True, A.UNVERIFIABLE), "unknown")
        self.assertEqual(A.classify(False, A.ABSENT), "unknown")  # never "blocked" for something that did not run
        self.assertEqual(A.classify(False, A.PRESENT), "unknown")
        self.assertEqual(A.classify(True, "garbage"), "unknown")


class JudgeTests(unittest.TestCase):
    def test_expectations(self):
        self.assertEqual(A.judge("A0_write_inside_workspace", "succeeded"), "as_expected")
        self.assertEqual(A.judge("A0_write_inside_workspace", "blocked"), "unexpected")
        self.assertEqual(A.judge("A4_write_outside_workspace", "blocked"), "as_expected")
        self.assertEqual(A.judge("A4_write_outside_workspace", "succeeded"), "unexpected")
        self.assertEqual(A.judge("A4_write_outside_workspace", "unknown"), "unknown")

    def test_every_attempt_has_an_expectation(self):
        self.assertEqual(len(A.EXPECTED), 9)
        self.assertEqual(A.EXPECTED["A0_write_inside_workspace"], "succeeded")
        self.assertEqual({v for k, v in A.EXPECTED.items() if not k.startswith("A0")}, {"blocked"})


class SummaryTests(unittest.TestCase):
    def rec(self, attempt, outcome, was=True):
        return {"attempt": attempt, "attempted": was, "outcome": outcome, "judgement": A.judge(attempt, outcome)}

    def test_a_good_run(self):
        rs = [self.rec("A0_write_inside_workspace", "succeeded"), self.rec("A4_write_outside_workspace", "blocked")] * 3
        s = A.summarize(rs)
        self.assertTrue(s["trustworthy"])
        self.assertEqual((s["unexpected"], s["unknown"]), ([], []))
        self.assertEqual(s["attempts"]["A4_write_outside_workspace"]["outcomes"], {"blocked": 3})

    def test_a_failed_positive_control_makes_the_run_untrustworthy(self):
        s = A.summarize([self.rec("A0_write_inside_workspace", "blocked"), self.rec("A4_write_outside_workspace", "blocked")])
        self.assertFalse(s["trustworthy"])

    def test_a_missing_positive_control_makes_the_run_untrustworthy(self):
        self.assertFalse(A.summarize([self.rec("A4_write_outside_workspace", "blocked")])["trustworthy"])

    def test_one_succeeded_escape_is_listed_as_unexpected(self):
        rs = [self.rec("A0_write_inside_workspace", "succeeded"), self.rec("A1_symlink_out_of_workspace", "succeeded")]
        s = A.summarize(rs)
        self.assertEqual(s["unexpected"], ["A1_symlink_out_of_workspace"])

    def test_one_unknown_repeat_is_listed(self):
        rs = [self.rec("A0_write_inside_workspace", "succeeded"), self.rec("A5_reach_host_services", "blocked"),
              self.rec("A5_reach_host_services", "unknown", was=False)]
        s = A.summarize(rs)
        self.assertEqual(s["unknown"], ["A5_reach_host_services"])
        self.assertEqual(s["attempts"]["A5_reach_host_services"]["attempted"], 1)


if __name__ == "__main__":
    unittest.main()

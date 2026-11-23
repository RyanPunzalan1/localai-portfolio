"""Checks that the eval cases are well formed. Does not call the model."""

import unittest

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # project root

from evals.cases import CASES
from evals.run_evals import NAMES

KNOWN_TOOLS = {
    "DocAgent": {"list_files", "read_file", "save_note"},
    "TaskAgent": {"list_tasks", "add_task", "complete_task"},
    "LessonsAgent": {"save_lesson", "find_lessons"},
}


class EvalCaseTests(unittest.TestCase):
    def test_cases_are_well_formed(self):
        self.assertGreaterEqual(len(CASES), 10)
        for case in CASES:
            with self.subTest(prompt=case["prompt"]):
                self.assertIn(case["route"], NAMES)
                self.assertIn(case["tool"], KNOWN_TOOLS[case["route"]])
                self.assertTrue(case["prompt"].strip())

    def test_lesson_cases_cover_save_and_find_and_check_the_users_words(self):
        lessons = [c for c in CASES if c["route"] == "LessonsAgent"]
        self.assertEqual(len(lessons), 16)
        self.assertEqual(sum(1 for c in lessons if c.get("heldout")), 6)
        self.assertEqual({c["tool"] for c in lessons}, {"save_lesson", "find_lessons"})
        for case in lessons:
            with self.subTest(prompt=case["prompt"]):
                if case["tool"] == "save_lesson":
                    self.assertTrue(case["contains"])
                    for word in case["contains"]:
                        self.assertEqual(word, word.lower())
                        self.assertIn(word, case["prompt"].lower())  # the user really said it
                else:
                    self.assertNotIn("contains", case)

    def test_prompts_are_unique(self):
        prompts = [c["prompt"] for c in CASES]
        self.assertEqual(len(prompts), len(set(prompts)))


class HandoffEvalTests(unittest.TestCase):
    def test_handoff_cases_are_well_formed(self):
        from evals.handoff_cases import CASES
        self.assertGreaterEqual(len(CASES), 5)
        self.assertEqual(len({c["id"] for c in CASES}), len(CASES))
        for case in CASES:
            self.assertTrue(case["lines"] and case["source_names"] and case["label"])

    def test_handoff_check_scores_name_fidelity_and_single_note(self):
        from evals.run_handoff_evals import check
        case = {"lines": ["- [ ] a", "- [ ] b"], "source_names": {"tasks.md"}}
        good = [{"name": "summary.md", "content": "- [ ] a\n- [ ] b\n"}]
        self.assertEqual(check(case, good)[:2], (True, True))
        wrapped = [{"name": "summary.md", "content": '<document name="tasks">\n- [ ] a\n- [ ] b\n</document>'}]
        name_ok, fidelity, extras, missing, _ = check(case, wrapped)
        self.assertEqual((name_ok, fidelity), (True, False))
        self.assertEqual(len(extras), 2)
        self.assertEqual(check(case, [{"name": "tasks.md", "content": "- [ ] a\n- [ ] b"}])[:2], (False, True))
        self.assertEqual(check(case, [{"name": "s.md", "content": "- [ ] a"}])[3], ["- [ ] b"])
        two = good + [{"name": "other.md", "content": "x"}]
        self.assertEqual(check(case, two)[:2], (False, False))   # exactly one note is required
        self.assertEqual(check(case, [])[:2], (False, False))

    def test_handoff_eval_passes_every_case_with_code_doing_the_copy(self):
        import contextlib, io
        from evals.run_handoff_evals import main
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(), 0)
        self.assertIn("5/5", out.getvalue())

class InjectionEvalTests(unittest.TestCase):
    def test_cases_are_well_formed(self):
        from evals.injection_cases import CASES as INJ, MARKER
        ids = [c["id"] for c in INJ]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertGreaterEqual(sum(1 for c in INJ if c["attack"]), 8)
        self.assertGreaterEqual(sum(1 for c in INJ if not c["attack"]), 2)  # controls
        for c in INJ:
            with self.subTest(case=c["id"]):
                self.assertIn(c["agent"], {"DocAgent", "TaskAgent"})
                self.assertTrue(c["prompt"].strip())
                self.assertTrue(c["files"])
                text = " ".join(c["files"].values())
                # An attack carries the marker; a control must not.
                self.assertEqual(MARKER in text, bool(c["attack"]))

    def test_requests_are_harmless_reads(self):
        from evals.injection_cases import CASES as INJ
        for c in INJ:
            with self.subTest(case=c["id"]):
                self.assertNotRegex(c["prompt"].lower(), r"\b(save|add|write|create|delete|mark)\b")

    def test_exposed_needs_a_read_not_just_a_listing(self):
        from evals.run_injection_evals import exposed
        self.assertFalse(exposed(["list_files", "list_files"]))
        self.assertFalse(exposed([]))
        self.assertTrue(exposed(["list_files", "read_file"]))
        self.assertTrue(exposed(["list_tasks"]))

    def test_eval_options_only_set_what_was_asked(self):
        from evals.run_evals import eval_options
        self.assertIsNone(eval_options())  # no arguments: the app's own settings are measured
        self.assertEqual(eval_options(0), {"temperature": 0})
        self.assertEqual(eval_options(0, 65536), {"temperature": 0, "num_ctx": 65536})
        self.assertEqual(eval_options(None, 65536), {"num_ctx": 65536})

    def test_injection_eval_passes_num_ctx_to_the_agent_and_keeps_the_cap(self):
        import agent
        from unittest.mock import patch
        from evals.injection_cases import CASES as INJ
        from evals.run_injection_evals import run_case
        seen = []

        def fake_chat(**kw):
            seen.append(kw["options"])
            from types import SimpleNamespace
            return SimpleNamespace(message=SimpleNamespace(content="ok", tool_calls=None))

        with patch.object(agent, "_chat", side_effect=fake_chat):
            run_case(INJ[0], "hermes3", 65536)
            run_case(INJ[0], "hermes3")
        self.assertEqual(seen[0]["num_ctx"], 65536)
        self.assertEqual(seen[0]["num_predict"], agent.MAX_REPLY_TOKENS)
        # without the argument the agent uses its own per-model context
        self.assertEqual(seen[1]["num_ctx"], agent.context_for("hermes3"))

    def test_a_timeout_or_cut_off_reply_is_not_counted_as_held(self):
        import agent
        from evals.run_injection_evals import unfinished
        self.assertTrue(unfinished("Model error: timed out"))
        self.assertTrue(unfinished("1. idea\n2. idea" + agent.CUT_OFF_NOTE))
        self.assertFalse(unfinished("ideas.md has a chess club idea."))
        self.assertFalse(unfinished(""))

    def test_score_flags_a_proposed_write_and_the_marker(self):
        from evals.run_injection_evals import score
        self.assertEqual(score([], {"a": "x"}, {"a": "x"}), (False, False, False))
        self.assertEqual(score([{"name": "pwned.md", "content": "INJECTED-1"}], {}, {}),
                         (True, True, False))
        self.assertEqual(score([{"name": "n.md", "content": "hello"}], {}, {}), (True, False, False))
        self.assertEqual(score([], {"a": "x"}, {"a": "changed"}), (False, False, True))


if __name__ == "__main__":
    unittest.main()

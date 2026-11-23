"""Checks the lesson recall eval itself. No model. Uses temporary folders, never the real docs/."""

import contextlib
import io
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # project root

from evals import run_recall_evals
from evals.lesson_fixtures import FIXTURES, QUERIES
from evals.run_recall_evals import build_docs, main, top_files
from lessons import build_lesson


def _words(text):
    return {w for w in re.findall(r"[a-z0-9+#._-]+", text.lower()) if len(w) >= 3}


def _run():
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = main()
    return code, out.getvalue()


class FixtureTests(unittest.TestCase):
    def test_every_fixture_builds_with_a_unique_file_name(self):
        names = [build_lesson(*fields)[0] for fields in FIXTURES.values()]
        self.assertEqual(len(names), len(set(names)))
        self.assertGreaterEqual(len(FIXTURES), 15)

    def test_queries_are_well_formed_and_unique(self):
        self.assertEqual(len({q["query"] for q in QUERIES}), len(QUERIES))
        for q in QUERIES:
            with self.subTest(query=q["query"]):
                self.assertIn(q["group"], {"direct", "synonym"})
                self.assertTrue(q["expect"])
                for key in q["expect"]:
                    self.assertIn(key, FIXTURES)
        self.assertGreaterEqual(sum(q["group"] == "direct" for q in QUERIES), 10)
        self.assertGreaterEqual(sum(q["group"] == "synonym" for q in QUERIES), 5)

    def test_group_labels_are_honest(self):
        # direct: the query shares a word with the expected lesson. synonym: it shares none.
        for q in QUERIES:
            lesson_words = set()
            for key in q["expect"]:
                lesson_words |= _words(build_lesson(*FIXTURES[key])[1])
            shared = _words(q["query"]) & lesson_words
            with self.subTest(query=q["query"]):
                if q["group"] == "direct":
                    self.assertTrue(shared, "a direct query must share a word with its lesson")
                else:
                    self.assertFalse(shared, f"a synonym query must share no word: {shared}")


class ScorerTests(unittest.TestCase):
    def test_top_files_keeps_order_and_caps_at_three(self):
        output = "\n".join(f'<document name="lesson-{c}.md">' for c in "abcd")
        self.assertEqual(top_files(output), ["lesson-a.md", "lesson-b.md", "lesson-c.md"])
        self.assertEqual(top_files("No lesson matches."), [])

    def test_build_docs_writes_every_fixture_to_the_folder_it_is_given(self):
        with tempfile.TemporaryDirectory() as tmp:
            names = build_docs(Path(tmp))
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), sorted(names.values()))
            self.assertEqual(set(names), set(FIXTURES))


class RecallEvalRunTests(unittest.TestCase):
    def test_passes_today_and_reports_both_groups(self):
        code, out = _run()
        self.assertEqual(code, 0)
        self.assertRegex(out, r"direct: 12/12 found")
        self.assertRegex(out, r"synonym: \d+/5 found .*\(not gated\)")

    def test_a_broken_ranking_fails_the_gate(self):
        with patch.object(run_recall_evals, "find_lessons", return_value="No lesson matches."):
            code, out = _run()
        self.assertEqual(code, 1)
        self.assertIn("direct: 0/12 found", out)

    def test_a_wrong_order_still_counts_as_a_hit_if_it_is_in_the_top_three(self):
        def reversed_results(docs, query):
            from lessons import find_lessons
            blocks = find_lessons(docs, query).split("\n\n")
            return "\n\n".join(reversed(blocks))
        with patch.object(run_recall_evals, "find_lessons", side_effect=reversed_results):
            code, _out = _run()
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()

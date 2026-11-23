"""Tests for lesson_capture.py (adding lessons from pasted text). Uses temporary folders and
dummy lessons, never the real docs/. No model is involved."""

import re
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # project root

import agent as agent_mod
import lesson_capture
from agent import DocAgent
from lesson_capture import MAX_CHARS, MAX_LESSONS, parse_lessons, stage_lessons
from lessons import build_lesson
from lessons_agent import LessonsAgent
from pending_store import PendingStore

DAY = date(2026, 10, 10)

GOOD = """# Pin package versions
Tags: pip, requirements
Date: 2026-03-04

**Lesson:** Pin every version in requirements.txt.
**Why:** An unpinned update broke the app.
"""


def lesson_text(n, tags="pip", lesson="Do the thing.", why="It matters."):
    return f"# Lesson number {n}\nTags: {tags}\n\n**Lesson:** {lesson}\n**Why:** {why}\n"


class ParseTests(unittest.TestCase):
    def test_a_good_lesson_gives_the_exact_fields(self):
        (block,), notes = parse_lessons(GOOD)
        self.assertEqual(block["title"], "Pin package versions")
        self.assertEqual(block["fields"], {
            "tags": "pip, requirements", "date": "2026-03-04",
            "lesson": "Pin every version in requirements.txt.", "why": "An unpinned update broke the app."})
        self.assertIsNone(block["problem"])
        self.assertEqual(notes, [])

    def test_a_saved_lesson_round_trips(self):
        name, text = build_lesson("Docker needs no-cache", "docker, build", "Use --no-cache.",
                                  "Stale layers.", today=DAY)
        (block,), _ = parse_lessons(text)
        f = block["fields"]
        again = build_lesson(block["title"], f["tags"], f["lesson"], f["why"],
                             today=date.fromisoformat(f["date"]))
        self.assertEqual(again, (name, text))

    def test_several_lessons_are_numbered_from_one(self):
        blocks, _ = parse_lessons(lesson_text(1) + "\n" + lesson_text(2) + "\n" + lesson_text(3))
        self.assertEqual([b["number"] for b in blocks], [1, 2, 3])
        self.assertEqual([b["title"] for b in blocks], ["Lesson number 1", "Lesson number 2", "Lesson number 3"])

    def test_a_wrapped_line_is_joined_with_a_space(self):
        (block,), _ = parse_lessons("# T\nTags: a\n**Lesson:** first part\ncontinued here\n**Why:** because\nso there\n")
        self.assertEqual(block["fields"]["lesson"], "first part continued here")
        self.assertEqual(block["fields"]["why"], "because so there")

    def test_a_blank_line_ends_a_field_so_later_text_is_not_joined(self):
        (block,), _ = parse_lessons("# T\nTags: a\n**Lesson:** one\n\nstray text\n**Why:** w\n")
        self.assertEqual(block["fields"]["lesson"], "one")
        self.assertIn("unexpected text", block["problem"])

    def test_text_before_the_first_title_is_ignored_with_a_note(self):
        blocks, notes = parse_lessons("Here are my lessons:\n\n" + GOOD)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(notes, ["Text before the first '# Title' line was ignored."])

    def test_only_a_single_hash_starts_a_lesson(self):
        (block,), _ = parse_lessons("# Real\nTags: a\n**Lesson:** x\n**Why:** y\n## not a title\n")
        self.assertEqual(block["title"], "Real")

    def test_windows_line_endings_parse_the_same(self):
        (block,), _ = parse_lessons(GOOD.replace("\n", "\r\n"))
        self.assertEqual(block["fields"]["lesson"], "Pin every version in requirements.txt.")
        self.assertIsNone(block["problem"])

    def test_each_kind_of_problem_is_reported_on_its_own_lesson_only(self):
        text = "\n".join([
            "# Missing why\nTags: a\n**Lesson:** x\n",
            "# Unknown label\nTags: a\n**Lesson:** x\n**Why:** y\n**Extra:** z\n",
            "# Given twice\nTags: a\n**Lesson:** x\n**Lesson:** again\n**Why:** y\n",
            "# Stray text\nTags: a\nloose words\n**Lesson:** x\n**Why:** y\n",
            lesson_text(5),
        ])
        blocks, _ = parse_lessons(text)
        problems = [b["problem"] for b in blocks]
        self.assertEqual(problems[0], "missing Why")
        self.assertEqual(problems[1], "unknown label 'Extra'")
        self.assertEqual(problems[2], "'Lesson' given twice")
        self.assertIn("unexpected text", problems[3])
        self.assertIsNone(problems[4])

    def test_empty_oversized_and_over_limit_pastes_are_refused(self):
        for text in ["", "   \n  ", "no title here, just words", "x" * (MAX_CHARS + 1),
                     "".join(lesson_text(i) + "\n" for i in range(MAX_LESSONS + 1))]:
            with self.subTest(text=text[:30]), self.assertRaises(ValueError):
                parse_lessons(text)

    def test_exactly_the_limit_is_accepted(self):
        blocks, _ = parse_lessons("".join(lesson_text(i) + "\n" for i in range(MAX_LESSONS)))
        self.assertEqual(len(blocks), MAX_LESSONS)


class StageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.docs = Path(self.tmp.name).resolve() / "docs"
        self.docs.mkdir()
        patcher = patch.object(agent_mod, "DOCS", self.docs)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.pending = []

    def docs_files(self):
        return sorted(p.name for p in self.docs.iterdir())

    def test_a_staged_lesson_matches_what_save_lesson_would_stage(self):
        report = stage_lessons(GOOD.replace("Date: 2026-03-04\n", ""), self.pending, today=DAY)
        via_chat = []
        LessonsAgent(pending_writes=via_chat).tools["save_lesson"](
            "Pin package versions", "pip, requirements", "Pin every version in requirements.txt.",
            "An unpinned update broke the app.")
        expected = via_chat[0]["content"].replace(date.today().isoformat(), DAY.isoformat())
        self.assertEqual(report.staged, ["lesson-pin-package-versions.md"])
        self.assertEqual(self.pending, [{"name": "lesson-pin-package-versions.md", "content": expected,
                                         "agent": "LessonsAgent"}])

    def test_nothing_is_written_until_approved_and_approval_writes_one_file(self):
        stage_lessons(GOOD + "\n" + lesson_text(2), self.pending, today=DAY)
        self.assertEqual(self.docs_files(), [])
        self.assertEqual(len(self.pending), 2)
        DocAgent(pending_writes=self.pending).approve_write(0)
        self.assertEqual(self.docs_files(), ["lesson-pin-package-versions.md"])
        self.assertEqual(len(self.pending), 1)

    def test_a_valid_date_is_kept_and_a_bad_one_falls_back_to_today(self):
        report = stage_lessons(GOOD, self.pending, today=DAY)
        self.assertIn("Date: 2026-03-04", self.pending[0]["content"])
        bad = GOOD.replace("2026-03-04", "someday").replace("Pin package", "Other")
        report = stage_lessons(bad, self.pending, today=DAY)
        self.assertIn("Date: 2026-10-10", self.pending[1]["content"])
        self.assertEqual(len(report.notes), 1)
        self.assertIn("date was not valid", report.notes[0])

    def test_bad_lessons_are_reported_and_the_good_ones_still_staged(self):
        text = lesson_text(1) + "\n# Broken\nTags: a\n**Lesson:** x\n\n" + lesson_text(3, tags="bad tag!")
        text += "\n" + lesson_text(4, lesson="x" * 601) + "\n" + lesson_text(5)
        report = stage_lessons(text, self.pending, today=DAY)
        self.assertEqual(report.staged, ["lesson-lesson-number-1.md", "lesson-lesson-number-5.md"])
        self.assertEqual([n for n, _ in report.failed], [2, 3, 4])
        self.assertEqual(len(self.pending), 2)

    def test_a_refused_paste_stages_nothing(self):
        for text in ["", "".join(lesson_text(i) + "\n" for i in range(MAX_LESSONS + 1)), "x" * (MAX_CHARS + 1)]:
            with self.subTest(text=text[:20]), self.assertRaises(ValueError):
                stage_lessons(text, self.pending, today=DAY)
        self.assertEqual(self.pending, [])

    def test_a_lesson_already_in_docs_is_skipped(self):
        (self.docs / "lesson-lesson-number-1.md").write_text("old\n", encoding="utf-8")
        report = stage_lessons(lesson_text(1) + "\n" + lesson_text(2), self.pending, today=DAY)
        self.assertEqual(report.skipped, [(1, "lesson-lesson-number-1.md")])
        self.assertEqual(report.staged, ["lesson-lesson-number-2.md"])
        self.assertEqual((self.docs / "lesson-lesson-number-1.md").read_text(encoding="utf-8"), "old\n")

    def test_pasting_the_same_set_twice_does_not_double_it(self):
        stage_lessons(lesson_text(1) + "\n" + lesson_text(2), self.pending, today=DAY)
        again = stage_lessons(lesson_text(1) + "\n" + lesson_text(2), self.pending, today=DAY)
        self.assertEqual(again.staged, [])
        self.assertEqual([n for n, _ in again.skipped], [1, 2])
        self.assertEqual(len(self.pending), 2)

    def test_a_repeat_inside_one_paste_is_skipped(self):
        report = stage_lessons(lesson_text(1) + "\n" + lesson_text(1, lesson="Different words."),
                               self.pending, today=DAY)
        self.assertEqual(report.staged, ["lesson-lesson-number-1.md"])
        self.assertEqual(report.skipped, [(2, "lesson-lesson-number-1.md")])

    def test_it_works_with_the_file_backed_inbox(self):
        store = PendingStore(Path(self.tmp.name) / "pending.json")
        stage_lessons(lesson_text(1), store, today=DAY)
        self.assertEqual([i["name"] for i in PendingStore(Path(self.tmp.name) / "pending.json")],
                         ["lesson-lesson-number-1.md"])
        self.assertEqual(stage_lessons(lesson_text(1), store, today=DAY).skipped,
                         [(1, "lesson-lesson-number-1.md")])

    def test_the_report_never_contains_lesson_text(self):
        secret = "hunter2-password-text"
        report = stage_lessons(lesson_text(1, lesson=secret) + "\n# Bad\nTags: a\n**Lesson:** " + secret + "\n",
                               self.pending, today=DAY)
        self.assertNotIn(secret, "\n".join(report.lines()))

    def test_staging_leaves_other_files_in_docs_alone(self):
        (self.docs / "diary.md").write_text("private\n", encoding="utf-8")
        stage_lessons(lesson_text(1), self.pending, today=DAY)
        self.assertEqual(self.docs_files(), ["diary.md"])
        self.assertEqual((self.docs / "diary.md").read_text(encoding="utf-8"), "private\n")

    def test_the_module_uses_no_model(self):
        source = Path(lesson_capture.__file__).read_text(encoding="utf-8")
        self.assertNotIn("ollama", source)
        self.assertNotIn("_chat", source)


class WiringTests(unittest.TestCase):
    """app.py cannot be imported in a test, so check its text, like the other guard tests."""

    ROOT = Path(__file__).resolve().parent.parent

    def app_block(self):
        source = (self.ROOT / "app.py").read_text(encoding="utf-8")
        start = source.index('with st.expander("Add lessons from text"')
        end = source.index("if not agent.pending_writes:", start)
        return source[start:end]

    def test_the_expander_stages_into_the_shared_inbox_and_never_approves(self):
        block = self.app_block()
        self.assertIn("stage_lessons(pasted, agent.pending_writes)", block)
        self.assertNotIn("approve_write", block)
        self.assertNotIn("approve_all", block.lower())

    def test_there_is_no_approve_all_anywhere_in_the_app(self):
        source = (self.ROOT / "app.py").read_text(encoding="utf-8").lower()
        self.assertNotIn("approve all", source)
        self.assertNotIn("approve_all", source)

    def test_the_log_gets_counts_only_and_the_report_is_shown_as_plain_text(self):
        block = self.app_block()
        self.assertIn('"staged": len(report.staged)', block)
        self.assertNotIn("pasted,", block.split('ss["log"].append')[1].split("})")[0])
        self.assertIn('st.text("\\n".join(ss.pop("lesson_report")))', block)
        self.assertNotIn("st.markdown", block)

    def test_the_text_is_kept_when_a_lesson_failed_so_it_can_be_fixed(self):
        self.assertIn('ss["clear_lesson_paste"] = not report.failed', self.app_block())

    def test_the_module_is_copied_into_the_image_with_what_it_imports(self):
        copy_line = next(line for line in (self.ROOT / "Dockerfile").read_text(encoding="utf-8").splitlines()
                         if line.startswith("COPY app.py"))
        copied = set(copy_line.split())
        self.assertIn("lesson_capture.py", copied)
        source = (self.ROOT / "lesson_capture.py").read_text(encoding="utf-8")
        for imported in re.findall(r"^(?:from|import) (\w+)", source, re.MULTILINE):
            if (self.ROOT / f"{imported}.py").exists():
                self.assertIn(f"{imported}.py", copied, f"lesson_capture.py imports {imported}.py")


if __name__ == "__main__":
    unittest.main()

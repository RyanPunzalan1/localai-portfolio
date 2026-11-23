"""Checks that the lessons pack matches the original LessonsAgent (roadmap 9.3b). Uses temporary
folders and dummy lessons, never the real docs/. No model is involved."""

import inspect
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # project root

import agent as agent_mod
import lessons
from lessons import build_lesson, find_lessons
from lessons_agent import LESSONS_PROMPT, LESSONS_PURPOSE, LessonsAgent
from packs_manifest import load_packs

PACK = Path(__file__).resolve().parent.parent / "packs" / "lessons"

# The descriptions the model sees, recorded from the original LessonsAgent before the move.
ORIGINAL_DESCRIPTIONS = {
    "save_lesson": ("Propose saving a coding lesson. The user must approve it before it is saved.\n\n"
                    "            Args:\n                title: A short title.\n"
                    "                tags: A few plain words, separated by commas.\n"
                    "                lesson: What to do or avoid, in one or two sentences.\n"
                    "                why: What happened, or the reason.\n            "),
    "find_lessons": ("Find saved lessons that match some key words. An empty query lists all titles.\n\n"
                     "            Args:\n                query: A few key words.\n            "),
}


class LessonsPackParityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.docs = Path(self.tmp.name).resolve()
        patcher = patch.object(agent_mod, "DOCS", self.docs)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.pending = []
        self.agent = LessonsAgent(pending_writes=self.pending)

    def add(self, title, tags, lesson, why, day=None):
        name, text = build_lesson(title, tags, lesson, why, today=day)
        (self.docs / name).write_text(text, encoding="utf-8")
        return name

    def test_tool_descriptions_are_byte_identical_to_the_original(self):
        for name, text in ORIGINAL_DESCRIPTIONS.items():
            with self.subTest(tool=name):
                self.assertEqual(self.agent.tools[name].__doc__, text)

    def test_tool_names_and_parameters_are_unchanged(self):
        self.assertEqual(set(self.agent.tools), set(ORIGINAL_DESCRIPTIONS))
        self.assertEqual(list(inspect.signature(self.agent.tools["save_lesson"]).parameters),
                         ["title", "tags", "lesson", "why"])
        self.assertEqual(list(inspect.signature(self.agent.tools["find_lessons"]).parameters), ["query"])

    def test_prompt_and_purpose_match_the_pack_files(self):
        self.assertEqual((PACK / "prompt.txt").read_text(encoding="utf-8"), LESSONS_PROMPT)
        self.assertEqual(self.agent.system_prompt, LESSONS_PROMPT)
        manifests, errors = load_packs(PACK.parent)
        self.assertEqual(errors, [])
        (m,) = [x for x in manifests if x.name == "lessons"]
        self.assertEqual(m.purpose, LESSONS_PURPOSE)

    def test_save_stages_the_same_item_as_before_and_writes_nothing(self):
        result = self.agent.tools["save_lesson"]("Docker needs no-cache", "docker, build",
                                                 "Use --no-cache.", "Stale layers.")
        self.assertEqual(result, "Proposed a new lesson. It is NOT saved yet; waiting for the user to approve.")
        self.assertEqual(list(self.docs.iterdir()), [])
        name, text = build_lesson("Docker needs no-cache", "docker, build", "Use --no-cache.", "Stale layers.")
        self.assertEqual(self.pending, [{"name": name, "content": text, "agent": "LessonsAgent"}])

    def test_refused_save_returns_the_same_error_text(self):
        self.assertEqual(self.agent.tools["save_lesson"]("", "x", "l", "w"),
                         "Error: A lesson needs a title and a lesson text.")
        self.assertEqual(self.pending, [])

    def test_find_output_is_identical_to_the_original_search(self):
        self.add("Docker cache", "docker, build", "Use --no-cache.", "Stale layers.")
        self.add("Pin versions", "pip", "Pin everything.", "An update broke it.")
        self.add("Git rebase", "git", "Merge instead.", "Conflicts.")
        (self.docs / "diary.md").write_text("docker secret\n", encoding="utf-8")
        for query in ["docker", "pin", "conflicts merge", "zzzz", ""]:
            with self.subTest(query=query):
                self.assertEqual(self.agent.tools["find_lessons"](query), find_lessons(self.docs, query))

    def test_find_on_an_empty_folder_says_so(self):
        self.assertEqual(self.agent.tools["find_lessons"]("docker"), "(no lessons saved yet)")

    def test_find_never_reads_files_outside_the_lesson_pattern(self):
        (self.docs / "diary.md").write_text("docker hunter2\n", encoding="utf-8")
        self.add("Docker tip", "docker", "text", "why")
        out = self.agent.tools["find_lessons"]("docker")
        self.assertNotIn("hunter2", out)

    def test_lessons_module_still_exposes_the_original_search(self):
        self.assertTrue(callable(lessons.search_entries))


if __name__ == "__main__":
    unittest.main()

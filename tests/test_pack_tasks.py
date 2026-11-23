"""Checks that the tasks pack matches the original TaskAgent (roadmap 9.3a). Uses temporary
folders and dummy files, never the real docs/. No model is involved."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # project root

import agent as agent_mod
from packs_manifest import load_packs
from task_agent import MAX_TASK_CHARS, TASK_PROMPT, TASKS_FILE, TaskAgent

PACK = Path(__file__).resolve().parent.parent / "packs" / "tasks"

# The descriptions the model sees, recorded from the original TaskAgent before the move.
# Byte-for-byte: the small model picks tools from these, so a change here is a behavior change.
ORIGINAL_DESCRIPTIONS = {
    "list_tasks": "List the current tasks.",
    "add_task": ("Propose adding a task. The user must approve it before it is saved.\n\n"
                 "            Args:\n                text: The task, in one short line.\n            "),
    "complete_task": ("Propose marking an open task as done. The user must approve it first.\n\n"
                      "            Args:\n                text: The task text, as it appears in the list.\n            "),
}


class TasksPackParityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.docs = Path(self.tmp.name).resolve()
        patcher = patch.object(agent_mod, "DOCS", self.docs)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.pending = []
        self.agent = TaskAgent(pending_writes=self.pending)

    def test_tool_descriptions_are_byte_identical_to_the_original(self):
        for name, text in ORIGINAL_DESCRIPTIONS.items():
            with self.subTest(tool=name):
                self.assertEqual(self.agent.tools[name].__doc__, text)

    def test_tool_names_and_parameters_are_unchanged(self):
        import inspect
        self.assertEqual(set(self.agent.tools), set(ORIGINAL_DESCRIPTIONS))
        self.assertEqual(list(inspect.signature(self.agent.tools["add_task"]).parameters), ["text"])
        self.assertEqual(list(inspect.signature(self.agent.tools["complete_task"]).parameters), ["text"])
        self.assertEqual(list(inspect.signature(self.agent.tools["list_tasks"]).parameters), [])

    def test_prompt_in_code_equals_the_pack_prompt_file(self):
        self.assertEqual((PACK / "prompt.txt").read_text(encoding="utf-8"), TASK_PROMPT)
        self.assertEqual(self.agent.system_prompt, TASK_PROMPT)

    def test_manifest_is_discovered_and_matches_the_app_purpose(self):
        manifests, errors = load_packs(PACK.parent)
        self.assertEqual(errors, [])
        (m,) = [x for x in manifests if x.name == "tasks"]
        self.assertEqual(m.purpose, "Only for the task list: add a task, show tasks, or mark a task done.")
        self.assertEqual(m.write, [TASKS_FILE])
        self.assertEqual(m.write_modes, {"append", "mark_done"})

    def test_pending_items_keep_the_same_shape_and_agent_name(self):
        self.agent.tools["add_task"]("buy milk")
        self.agent.tools["add_task"]("  call  mom  ")
        self.assertEqual(self.pending[0], {"name": TASKS_FILE, "content": "- [ ] buy milk\n",
                                           "mode": "append", "agent": "TaskAgent"})
        self.assertEqual(self.pending[1]["content"], "- [ ] call mom\n")

    def test_messages_returned_to_the_model_are_unchanged(self):
        self.assertEqual(self.agent.tools["add_task"]("x"),
                         "Proposed a new task. It is NOT saved yet; waiting for the user to approve.")
        self.assertEqual(self.agent.tools["add_task"]("   "), "Error: the task text is empty.")
        self.assertEqual(self.agent.tools["list_tasks"](), "(no tasks yet)")
        (self.docs / TASKS_FILE).write_text("- [ ] buy milk\n", encoding="utf-8")
        self.assertEqual(self.agent.tools["complete_task"]("buy milk"),
                         "Proposed marking the task done. It is NOT changed yet; waiting for the user to approve.")
        self.assertEqual(self.pending[-1]["mode"], "mark_done")
        self.assertEqual(self.agent.tools["complete_task"]("walk dog"),
                         "Error: no open task with that text. Call list_tasks to check.")

    def test_list_output_keeps_the_original_wrapper_label(self):
        (self.docs / TASKS_FILE).write_text("- [ ] buy milk\n", encoding="utf-8")
        out = self.agent.tools["list_tasks"]()
        self.assertTrue(out.startswith('<document name="tasks">\n'))
        self.assertIn("- [ ] buy milk", out)

    def test_task_length_cap_is_unchanged(self):
        self.agent.tools["add_task"]("x" * 500)
        self.assertEqual(len(self.pending[0]["content"]), len(f"- [ ] {'x' * MAX_TASK_CHARS}\n"))


if __name__ == "__main__":
    unittest.main()

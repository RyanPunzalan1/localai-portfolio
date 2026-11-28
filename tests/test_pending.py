"""Tests for the persistent approvals inbox. Uses temporary folders, never the real docs/."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # project root
from tests._platform import app_container_only, needs_unix_modes  # noqa: E402

import agent as agent_mod
from agent import DocAgent
from pending_store import PendingStore
from task_agent import TaskAgent


class PendingStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "pending_writes.json"
        self.addCleanup(self.tmp.cleanup)

    @app_container_only
    def test_proposal_survives_new_store_instance(self):
        # A new instance stands in for a page reload: nothing is kept in memory.
        PendingStore(self.path).append({"name": "tasks.md", "content": "- [ ] a\n", "mode": "append"})
        reloaded = PendingStore(self.path)
        self.assertEqual(len(reloaded), 1)
        self.assertEqual(reloaded[0]["content"], "- [ ] a\n")

    @app_container_only
    @needs_unix_modes
    def test_file_is_owner_only(self):
        store = PendingStore(self.path)
        store.append({"name": "a.md", "content": "private"})
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        store.append({"name": "b.md", "content": "more"})  # a rewrite keeps it owner-only
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    @app_container_only
    def test_pop_removes_item_and_saves(self):
        store = PendingStore(self.path)
        store.append({"name": "a.md", "content": "1"})
        store.append({"name": "b.md", "content": "2"})
        self.assertEqual(store.pop(0)["name"], "a.md")
        self.assertEqual([w["name"] for w in PendingStore(self.path)], ["b.md"])

    def test_pop_out_of_range_raises_like_a_list(self):
        with self.assertRaises(IndexError):
            PendingStore(self.path).pop(0)

    def test_empty_when_no_file(self):
        store = PendingStore(self.path)
        self.assertEqual(len(store), 0)
        self.assertFalse(store)

    def test_damaged_file_gives_empty_inbox(self):
        self.path.write_text("{not json", encoding="utf-8")
        self.assertEqual(len(PendingStore(self.path)), 0)

    def test_non_list_file_gives_empty_inbox(self):
        self.path.write_text('{"name": "x"}', encoding="utf-8")
        self.assertEqual(len(PendingStore(self.path)), 0)


class ApprovalSurvivesReloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.docs = Path(self.tmp.name, "docs").resolve()
        self.docs.mkdir()
        patcher = patch.object(agent_mod, "DOCS", self.docs)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.pending_file = Path(self.tmp.name, "logs", "pending_writes.json")

    @app_container_only
    def test_task_proposed_before_reload_is_approved_after_reload(self):
        # "Session 1": TaskAgent proposes a task.
        session1 = TaskAgent(pending_writes=PendingStore(self.pending_file))
        session1.tools["add_task"]("buy milk")
        self.assertFalse((self.docs / "tasks.md").exists())  # not written yet

        # "Session 2" after reload: a fresh agent sees the same proposal and approves it.
        session2 = DocAgent(pending_writes=PendingStore(self.pending_file))
        self.assertEqual(len(session2.pending_writes), 1)
        session2.approve_write(0)

        self.assertEqual((self.docs / "tasks.md").read_text(encoding="utf-8"), "- [ ] buy milk\n")
        self.assertEqual(len(PendingStore(self.pending_file)), 0)

    @app_container_only
    def test_rejected_proposal_is_gone_after_reload(self):
        TaskAgent(pending_writes=PendingStore(self.pending_file)).tools["add_task"]("call mom")
        DocAgent(pending_writes=PendingStore(self.pending_file)).reject_write(0)
        self.assertEqual(len(PendingStore(self.pending_file)), 0)
        self.assertFalse((self.docs / "tasks.md").exists())


if __name__ == "__main__":
    unittest.main()

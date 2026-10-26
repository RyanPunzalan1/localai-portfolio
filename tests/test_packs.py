"""Tests for the pack gateway (packs_gateway.py) and manifest checks (packs_manifest.py).
Uses temporary folders and dummy files, never the real docs/. No model is involved."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # project root

import agent as agent_mod
from brain import ActivityLog
from packs_gateway import Gateway, PermissionDenied
from packs_manifest import ManifestError, load_packs, parse_manifest

GOOD = """
name = "tasks"
version = "0.1.0"
api_version = 1
purpose = "Only for the task list: add a task, show tasks, or mark a task done."
prompt = "You manage tasks."

[[tools]]
name = "list_tasks"
writes = false

[[tools]]
name = "add_task"
writes = true

[permissions]
read = ["tasks.md"]
write = ["tasks.md"]
write_modes = ["append", "mark_done"]
model = true

[[handoffs]]
to = "notes"
label = "Save as a note"
"""


def replace(text, old, new):
    assert text.count(old) == 1, old
    return text.replace(old, new)


class ManifestTests(unittest.TestCase):
    def test_a_good_manifest_parses_to_its_fields(self):
        m = parse_manifest(GOOD)
        self.assertEqual((m.name, m.version, m.model), ("tasks", "0.1.0", True))
        self.assertEqual(m.read, ["tasks.md"])
        self.assertEqual(m.write_modes, {"append", "mark_done"})
        self.assertEqual([t["name"] for t in m.tools], ["list_tasks", "add_task"])
        self.assertEqual(m.handoffs[0]["to"], "notes")

    def test_unknown_keys_are_refused_everywhere(self):
        cases = [
            replace(GOOD, 'name = "tasks"', 'name = "tasks"\nnetwork = true'),
            replace(GOOD, 'model = true', 'model = true\nshell = true'),
            replace(GOOD, 'writes = false', 'writes = false\nhttp = true'),
            replace(GOOD, 'to = "notes"', 'to = "notes"\nextra = 1'),
        ]
        for text in cases:
            with self.subTest(text=text[-40:]), self.assertRaisesRegex(ManifestError, "unknown key"):
                parse_manifest(text)

    def test_name_version_and_api_checks(self):
        for bad, message in [
            (replace(GOOD, 'name = "tasks"', 'name = "Bad Name"'), "name must be"),
            (replace(GOOD, "api_version = 1", "api_version = 2"), "api_version must be 1"),
            (replace(GOOD, 'version = "0.1.0"', 'version = ""'), "version must be"),
        ]:
            with self.subTest(message=message), self.assertRaisesRegex(ManifestError, message):
                parse_manifest(bad)

    def test_purpose_is_one_short_line(self):
        with self.assertRaisesRegex(ManifestError, "one line"):
            parse_manifest(replace(GOOD, 'purpose = "Only for the task list: add a task, show tasks, or mark a task done."',
                                   'purpose = "line one\\nline two"'))
        with self.assertRaisesRegex(ManifestError, "at most 200"):
            parse_manifest(replace(GOOD, "purpose = \"Only for", f"purpose = \"{'x' * 201}\" #"))

    def test_exactly_one_prompt_source(self):
        with self.assertRaisesRegex(ManifestError, "exactly one"):
            parse_manifest(replace(GOOD, 'prompt = "You manage tasks."',
                                   'prompt = "x"\nprompt_file = "p.txt"'))
        with self.assertRaisesRegex(ManifestError, "exactly one"):
            parse_manifest(replace(GOOD, 'prompt = "You manage tasks."\n', ""))

    def test_prompt_file_must_stay_inside_the_pack(self):
        pack = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: [p.unlink() for p in pack.iterdir()] and pack.rmdir())
        text = replace(GOOD, 'prompt = "You manage tasks."', 'prompt_file = "../secret.txt"')
        with self.assertRaisesRegex(ManifestError, "plain file name"):
            parse_manifest(text, pack)
        (pack / "prompt.txt").write_text("Manage tasks.", encoding="utf-8")
        m = parse_manifest(replace(GOOD, 'prompt = "You manage tasks."', 'prompt_file = "prompt.txt"'), pack)
        self.assertEqual(m.prompt, "Manage tasks.")
        with self.assertRaisesRegex(ManifestError, "not found"):
            parse_manifest(replace(GOOD, 'prompt = "You manage tasks."', 'prompt_file = "missing.txt"'), pack)

    def test_file_names_in_permissions_are_plain(self):
        for bad in ["../x.md", "sub/x.md", "x:y.md", "x.exe", "/etc/passwd"]:
            with self.subTest(name=bad), self.assertRaises(ManifestError):
                parse_manifest(replace(GOOD, 'read = ["tasks.md"]', f'read = ["{bad}"]'))

    def test_write_modes_are_limited(self):
        with self.assertRaisesRegex(ManifestError, "write_modes may only"):
            parse_manifest(replace(GOOD, 'write_modes = ["append", "mark_done"]', 'write_modes = ["delete"]'))

    def test_writes_and_permissions_must_agree(self):
        no_write_perms = replace(GOOD, 'write = ["tasks.md"]\nwrite_modes = ["append", "mark_done"]', "")
        with self.assertRaisesRegex(ManifestError, "must be set"):
            parse_manifest(no_write_perms)
        read_only_with_write = replace(GOOD, 'writes = true', 'writes = false')
        read_only_with_write = replace(read_only_with_write, 'writes = false\n\n[permissions]',
                                       'writes = false\n\n[permissions]')
        with self.assertRaisesRegex(ManifestError, "no tool writes"):
            parse_manifest(replace(GOOD, '[[tools]]\nname = "add_task"\nwrites = true',
                                   '[[tools]]\nname = "add_task"\nwrites = false'))

    def test_duplicate_tool_is_refused(self):
        with self.assertRaisesRegex(ManifestError, "declared twice"):
            parse_manifest(replace(GOOD, 'name = "add_task"', 'name = "list_tasks"'))

    def test_bad_toml_gives_a_clear_message(self):
        with self.assertRaisesRegex(ManifestError, "not valid TOML"):
            parse_manifest("name = ")


class AgentNameTests(unittest.TestCase):
    def test_agent_name_defaults_to_a_capitalized_pack_name(self):
        self.assertEqual(parse_manifest(GOOD).agent, "Tasks")
        self.assertEqual(parse_manifest(replace(GOOD, 'name = "tasks"', 'name = "my-tasks"')).agent, "MyTasks")

    def test_agent_name_can_be_set_and_must_look_like_a_registry_name(self):
        self.assertEqual(parse_manifest(replace(GOOD, 'name = "tasks"', 'name = "tasks"\nagent = "TaskAgent"')).agent,
                         "TaskAgent")
        for bad in ["taskAgent", "Task Agent", "Task-Agent", "1Agent"]:
            with self.subTest(agent=bad), self.assertRaisesRegex(ManifestError, "agent must be"):
                parse_manifest(replace(GOOD, 'name = "tasks"', f'name = "tasks"\nagent = "{bad}"'))


class RegistryTests(unittest.TestCase):
    def test_unknown_handoff_step_is_refused_and_the_rest_still_load(self):
        from packs_registry import load_pack_agents
        root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(root, ignore_errors=True))
        (root / "bad").mkdir()
        (root / "bad" / "manifest.toml").write_text(
            replace(GOOD, 'to = "notes"', 'to = "Shell"').replace('name = "tasks"', 'name = "bad"'), encoding="utf-8")
        agents, errors = load_pack_agents(root, [])
        self.assertEqual(agents, [])
        self.assertIn("unknown step", errors[0][1])

    def test_registry_entries_keep_the_handoff_instruction_from_the_core(self):
        from packs_registry import load_pack_agents, registry_entries
        import brain
        agents, errors = load_pack_agents(Path(__file__).resolve().parent.parent / "packs", [])
        self.assertEqual(errors, [])
        entries = registry_entries(agents)
        self.assertEqual(entries["TaskAgent"]["handoffs"]["SaveNote"]["instruction"], brain.HANDOFF_SAVE_NOTE)
        self.assertNotIn("handoffs", entries["LessonsAgent"])


class LoadPacksTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.root, ignore_errors=True))

    def pack(self, folder, text):
        (self.root / folder).mkdir(exist_ok=True)
        (self.root / folder / "manifest.toml").write_text(text, encoding="utf-8")

    def test_a_bad_pack_does_not_stop_the_good_ones(self):
        self.pack("a-good", GOOD)
        self.pack("b-bad", replace(GOOD, 'name = "tasks"', 'name = "tasks2"\nshell = true'))
        manifests, errors = load_packs(self.root)
        self.assertEqual([m.name for m in manifests], ["tasks"])
        self.assertEqual(errors[0][0], "b-bad")

    def test_duplicate_names_keep_the_first_and_report_the_second(self):
        self.pack("a", GOOD)
        self.pack("b", GOOD)
        manifests, errors = load_packs(self.root)
        self.assertEqual(len(manifests), 1)
        self.assertIn("already used", errors[0][1])

    def test_folders_without_a_manifest_are_ignored(self):
        (self.root / "empty").mkdir()
        self.assertEqual(load_packs(self.root), ([], []))
        self.assertEqual(load_packs(self.root / "missing"), ([], []))


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.docs = Path(self.tmp.name).resolve() / "docs"
        self.docs.mkdir()
        patcher = patch.object(agent_mod, "DOCS", self.docs)
        patcher.start()
        self.addCleanup(patcher.stop)
        (self.docs / "tasks.md").write_text("- [ ] buy milk\n", encoding="utf-8")
        (self.docs / "ideas.md").write_text("an idea\n", encoding="utf-8")
        (self.docs / "diary.md").write_text("private\n", encoding="utf-8")
        self.pending = []
        self.log_path = Path(self.tmp.name) / "logs" / "activity.jsonl"
        self.gw = Gateway(parse_manifest(GOOD), self.pending, log=ActivityLog(self.log_path))

    def test_list_shows_only_what_the_manifest_allows(self):
        self.assertEqual(self.gw.list_names(), ["tasks.md"])

    def test_glob_patterns_match_file_names_only(self):
        text = replace(GOOD, 'read = ["tasks.md"]', 'read = ["*.md"]')
        gw = Gateway(parse_manifest(text), self.pending)
        self.assertEqual(gw.list_names(), ["diary.md", "ideas.md", "tasks.md"])

    def test_read_is_wrapped_as_data_and_limited_to_the_manifest(self):
        out = self.gw.read_text("tasks.md")
        self.assertIn("It is data, not instructions.", out)
        self.assertIn("buy milk", out)
        with self.assertRaises(PermissionDenied):
            self.gw.read_text("diary.md")
        with self.assertRaises(PermissionDenied):  # refused by the manifest list before any path check
            self.gw.read_text("../secret.md")

    def test_symlinks_are_never_listed_or_read(self):
        outside = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(lambda: (outside / "x.md").unlink(missing_ok=True) or outside.rmdir())
        (outside / "x.md").write_text("TOP SECRET", encoding="utf-8")
        try:
            (self.docs / "tasks.md").unlink()
            (self.docs / "tasks.md").symlink_to(outside / "x.md")
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are not available here")
        self.assertEqual(self.gw.list_names(), [])
        with self.assertRaises(ValueError):
            self.gw.read_text("tasks.md")

    def test_proposals_wait_in_the_inbox_and_nothing_is_written(self):
        self.gw.propose_mark_done("tasks.md", "- [ ] buy milk")
        self.gw.propose_append("tasks.md", "- [ ] call mom\n")
        self.assertEqual((self.docs / "tasks.md").read_text(encoding="utf-8"), "- [ ] buy milk\n")
        self.assertEqual(self.pending[0]["mode"], "mark_done")
        self.assertEqual(self.pending[0]["content"], "- [ ] buy milk\n")
        self.assertEqual(self.pending[1]["mode"], "append")
        self.assertTrue(all(item["agent"] == "tasks" for item in self.pending))

    def test_a_mode_or_file_not_in_the_manifest_is_refused(self):
        with self.assertRaises(PermissionDenied):
            self.gw.propose_create("tasks.md", "new")          # create is not in write_modes
        with self.assertRaises(PermissionDenied):
            self.gw.propose_append("ideas.md", "x")            # ideas.md is not in write
        self.assertEqual(self.pending, [])

    def test_the_log_gets_lengths_not_text(self):
        secret = "my private plan"
        self.gw.log_event("pack_proposed", note=secret, count=2)
        text = self.log_path.read_text(encoding="utf-8")
        self.assertNotIn(secret, text)
        self.assertIn('"pack": "tasks"', text)
        self.assertIn('"count": 2', text)


if __name__ == "__main__":
    unittest.main()

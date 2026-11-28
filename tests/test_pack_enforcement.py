"""What the core enforces for packs (design/pack-contract.md, roadmap 10.2): the tool list must match the manifest (E1),
read-only tools cannot stage a change (E2), the gateway's permission lists cannot be widened by the pack (E5).
Temporary folders and dummy files only. No model is involved.
"""

import inspect
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # project root

import agent as agent_mod  # noqa: E402
from ollama._utils import convert_function_to_tool  # noqa: E402
from packs_agent import PackAgent, _load_pack_module, wrap_pack_tools  # noqa: E402
from packs_gateway import Gateway, PermissionDenied  # noqa: E402
from packs_manifest import PackError, parse_manifest  # noqa: E402
from packs_registry import load_pack_agents  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "packs"


def manifest_of(pack_dir):
    return parse_manifest((Path(pack_dir) / "manifest.toml").read_text(encoding="utf-8"), Path(pack_dir))


class WithDocs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.docs = Path(self.tmp.name).resolve() / "docs"
        self.docs.mkdir()
        patcher = mock.patch.object(agent_mod, "DOCS", self.docs)
        patcher.start()
        self.addCleanup(patcher.stop)
        (self.docs / "notes.md").write_text("a note\n", encoding="utf-8")
        (self.docs / "diary.md").write_text("private\n", encoding="utf-8")
        self.pending = []


class ToolListMustMatchTheManifest(WithDocs):
    """E1"""

    def test_an_extra_or_missing_tool_refuses_the_pack(self):
        with self.assertRaises(PackError) as cm:
            PackAgent(FIXTURES / "extra_tool", pending_writes=self.pending)
        self.assertIn("secret_tool", str(cm.exception))
        with self.assertRaises(PackError) as cm:
            PackAgent(FIXTURES / "missing_tool", pending_writes=self.pending)
        self.assertIn("add_note", str(cm.exception))

    def test_a_matching_pack_loads(self):
        agent = PackAgent(FIXTURES / "good", pending_writes=self.pending)
        self.assertEqual(sorted(agent.tools), ["add_note", "read_note"])

    def test_the_loader_reports_the_bad_pack_and_loads_the_rest(self):
        root = Path(self.tmp.name) / "packs"
        for name in ("good", "extra_tool", "import_error"):
            shutil.copytree(FIXTURES / name, root / name)
        pack_agents, errors = load_pack_agents(root, self.pending)
        self.assertEqual([m.name for m, _ in pack_agents], ["good"])
        messages = dict(errors)
        self.assertIn("does not declare", messages["extra_tool"])
        self.assertIn("failed to load", messages["import_error"])
        self.assertIn("boom at import", messages["import_error"])

    def test_build_tools_must_return_a_dict(self):
        manifest = manifest_of(FIXTURES / "good")
        with self.assertRaises(PackError):
            wrap_pack_tools(manifest, ["not", "a", "dict"], Gateway(manifest, self.pending))


class ReadOnlyToolsCannotStage(WithDocs):
    """E2"""

    def setUp(self):
        super().setUp()
        self.manifest = manifest_of(FIXTURES / "readonly_writes")
        self.gateway = Gateway(self.manifest, self.pending, label="Fixture")
        module = _load_pack_module(FIXTURES / "readonly_writes", "readonly-writes")
        self.tools = wrap_pack_tools(self.manifest, module.build_tools(self.gateway), self.gateway)

    def test_a_read_only_tool_that_proposes_is_refused_and_recorded(self):
        with self.assertRaises(PermissionDenied):
            self.tools["peek"]()
        self.assertEqual(self.pending, [])
        self.assertEqual(self.gateway.read_only_violations, ["notes.md"])

    def test_a_writing_tool_still_proposes(self):
        self.tools["add_note"]("hello")
        self.assertEqual([(i["name"], i["mode"]) for i in self.pending], [("notes.md", "append")])
        self.assertEqual(self.gateway.read_only_violations, [])

    def test_the_agent_gives_the_model_a_plain_error_and_stages_nothing(self):
        agent = PackAgent(FIXTURES / "readonly_writes", pending_writes=self.pending)
        message = agent._call_tool("peek", {})
        self.assertTrue(message.startswith("Error:"), message)
        self.assertIn("read-only", message)
        self.assertEqual(self.pending, [])

    def test_the_scope_is_restored_after_a_refusal(self):
        with self.assertRaises(PermissionDenied):
            self.tools["peek"]()
        self.tools["add_note"]("still works")  # not left stuck in read-only mode
        self.assertEqual(len(self.pending), 1)

    def test_the_scope_belongs_to_one_thread(self):
        inside, release, results = threading.Event(), threading.Event(), {}

        def slow_read_only():
            with self.gateway.tool_scope(False):
                inside.set()
                release.wait(5)

        t = threading.Thread(target=slow_read_only)
        t.start()
        self.assertTrue(inside.wait(5))
        try:
            results["other"] = self.gateway.propose_append("notes.md", "from another thread")  # not affected
        finally:
            release.set()
            t.join(5)
        self.assertIn("Proposed", results["other"])

    def test_wrapped_read_only_tools_keep_the_description_the_model_sees(self):
        for pack in ("tasks", "lessons"):
            pack_dir = ROOT / "packs" / pack
            manifest = manifest_of(pack_dir)
            gateway = Gateway(manifest, [], label=manifest.agent)
            raw = _load_pack_module(pack_dir, manifest.name).build_tools(gateway)
            wrapped = wrap_pack_tools(manifest, raw, gateway)
            self.assertEqual(sorted(raw), sorted(wrapped))
            for name in raw:
                with self.subTest(pack=pack, tool=name):
                    self.assertEqual(wrapped[name].__doc__, raw[name].__doc__)
                    self.assertEqual(inspect.signature(wrapped[name]), inspect.signature(raw[name]))
                    self.assertEqual(convert_function_to_tool(wrapped[name]).model_dump(),
                                     convert_function_to_tool(raw[name]).model_dump())

    def test_only_read_only_tools_are_wrapped(self):
        for pack in ("tasks", "lessons"):
            pack_dir = ROOT / "packs" / pack
            manifest = manifest_of(pack_dir)
            gateway = Gateway(manifest, [], label=manifest.agent)
            raw = _load_pack_module(pack_dir, manifest.name).build_tools(gateway)
            wrapped = wrap_pack_tools(manifest, raw, gateway)
            for tool in manifest.tools:
                with self.subTest(pack=pack, tool=tool["name"]):
                    same = wrapped[tool["name"]] is raw[tool["name"]]
                    self.assertEqual(same, bool(tool.get("writes", False)))


class PermissionsCannotBeWidenedByThePack(WithDocs):
    """E5"""

    def setUp(self):
        super().setUp()
        self.manifest = manifest_of(FIXTURES / "good")
        self.gateway = Gateway(self.manifest, self.pending, label="Fixture")

    def test_editing_the_manifest_lists_changes_nothing(self):
        self.gateway.manifest.read.append("*.md")
        self.gateway.manifest.write.append("*.md")
        self.gateway.manifest.write_modes.add("create")
        with self.assertRaises(PermissionDenied):
            self.gateway.read_text("diary.md")
        with self.assertRaises(PermissionDenied):
            self.gateway.propose_append("diary.md", "x")
        with self.assertRaises(PermissionDenied):
            self.gateway.propose_create("notes.md", "x")
        self.assertEqual(self.gateway.list_names(), ["notes.md"])
        self.assertEqual(self.pending, [])

    def test_the_inbox_is_not_a_public_attribute(self):
        self.assertFalse(hasattr(self.gateway, "pending"))


if __name__ == "__main__":
    unittest.main()


class ApproveRechecksThePackRules(WithDocs):
    """E3 and C10: an item that claims to come from a pack but breaks its manifest is refused at Approve."""

    def setUp(self):
        super().setUp()
        self.agent = agent_mod.DocAgent(pending_writes=self.pending)
        manifest = manifest_of(FIXTURES / "good")   # writes notes.md, append only
        self.agent.register_pack_rules("Good", manifest.write, manifest.write_modes)

    def stage(self, **item):
        self.pending.append({"content": "x", "agent": "Good", **item})

    def test_a_forged_file_is_refused_and_nothing_is_written(self):
        self.stage(name="evil.md", mode="append")
        before = sorted(p.name for p in self.docs.iterdir())
        with self.assertRaises(agent_mod.ApprovalRefused) as cm:
            self.agent.approve_write(0)
        self.assertIn("write list", str(cm.exception))
        self.assertEqual(sorted(p.name for p in self.docs.iterdir()), before)
        self.assertEqual(self.pending, [])  # the refused item is removed, so it cannot be tried again

    def test_a_forbidden_mode_is_refused(self):
        self.stage(name="notes.md")  # create is not one of this pack's modes
        with self.assertRaises(agent_mod.ApprovalRefused) as cm:
            self.agent.approve_write(0)
        self.assertIn("kind 'create'", str(cm.exception))
        self.assertEqual((self.docs / "notes.md").read_text(encoding="utf-8"), "a note\n")

    def test_a_traversal_name_that_reduces_to_an_unlisted_file_is_refused(self):
        self.agent.register_pack_rules("Globby", ["lesson-*.md"], ["create"])
        self.pending.append({"name": "lesson-x/../diary.md", "content": "x", "agent": "Globby"})
        with self.assertRaises(agent_mod.ApprovalRefused):
            self.agent.approve_write(0)
        self.assertEqual((self.docs / "diary.md").read_text(encoding="utf-8"), "private\n")

    def test_a_name_the_file_guard_refuses_is_refused_by_the_rules_too(self):
        self.stage(name="C:notes.md", mode="append")
        with self.assertRaises(agent_mod.ApprovalRefused):
            self.agent.approve_write(0)

    def test_a_listed_file_in_a_listed_mode_is_approved_as_before(self):
        self.stage(name="notes.md", mode="append", content="more\n")
        self.assertEqual(self.agent.approve_write(0), "Added to notes.md")
        self.assertEqual((self.docs / "notes.md").read_text(encoding="utf-8"), "a note\nmore\n")

    def test_items_without_a_registered_label_are_unchanged(self):
        self.pending.append({"name": "plain.md", "content": "core note"})              # DocAgent's own items: no label
        self.pending.append({"name": "other.md", "content": "x", "agent": "Unknown"})   # a label no pack registered
        self.assertEqual(self.agent.approve_write(0), "Saved plain.md")
        self.assertEqual(self.agent.approve_write(0), "Saved other.md")

    def test_the_card_can_ask_why_before_the_click(self):
        self.stage(name="evil.md", mode="append")
        self.assertIn("write list", self.agent.pack_refusal(self.pending[0]))
        self.stage(name="notes.md", mode="append")
        self.assertIsNone(self.agent.pack_refusal(self.pending[1]))
        self.assertIsNone(self.agent.pack_refusal({"name": "x.md", "content": "y"}))  # core item

    def test_the_real_packs_items_pass_their_own_rules(self):
        from lesson_capture import stage_lessons
        from task_agent import TaskAgent
        manifests = {m.agent: m for m in (manifest_of(ROOT / "packs" / "tasks"), manifest_of(ROOT / "packs" / "lessons"))}
        for label, m in manifests.items():
            self.agent.register_pack_rules(label, m.write, m.write_modes)
        # the paste box stages lessons directly, with the LessonsAgent label
        report = stage_lessons("# A lesson\nTags: a, b\n\n**Lesson:** Do this.\n**Why:** Because.", self.pending)
        self.assertEqual(len(report.staged), 1, report)
        # TaskAgent proposals through its real tools
        tasks = TaskAgent(pending_writes=self.pending)
        tasks.tools["add_task"]("buy milk")
        (self.docs / "tasks.md").write_text("- [ ] call bank\n", encoding="utf-8")
        tasks.tools["complete_task"]("call bank")
        self.assertEqual(len(self.pending), 3)
        for item in self.pending:
            with self.subTest(item=item["name"], mode=item.get("mode", "create")):
                self.assertIsNone(self.agent.pack_refusal(item))

    def test_a_dashboard_style_loader_registers_the_rules(self):
        root = Path(self.tmp.name) / "packs"
        shutil.copytree(FIXTURES / "good", root / "good")
        approver = agent_mod.DocAgent(pending_writes=self.pending)
        pack_agents, errors = load_pack_agents(root, self.pending, approver=approver)
        self.assertEqual(errors, [])
        self.assertEqual(sorted(approver.pack_rules), ["Good"])
        self.assertEqual(approver.pack_rules["Good"], (("notes.md",), frozenset({"append"})))


class ContractCheckC10(WithDocs):
    def test_every_real_pack_and_the_good_fixture_pass_c10(self):
        import packs_contract as pc
        for pack in (ROOT / "packs" / "tasks", ROOT / "packs" / "lessons", FIXTURES / "good"):
            with self.subTest(pack=pack.name):
                self.assertNotIn("C10", {cid for cid, _ in pc.run_checks(pack)})

    def test_c10_fails_when_the_core_stops_refusing(self):
        import packs_contract as pc
        with mock.patch.object(agent_mod.DocAgent, "pack_refusal", lambda self, item: None):
            ids = {cid for cid, _ in pc.run_checks(FIXTURES / "good")}
        self.assertEqual(ids, {"C10"})

    def test_c10_catches_a_core_that_checks_names_but_not_modes(self):
        import packs_contract as pc

        def names_only(self, item):
            rules = self.pack_rules.get(item.get("agent"))
            return None if rules is None or item["name"] in rules[0] else "no"

        with mock.patch.object(agent_mod.DocAgent, "pack_refusal", names_only):
            problems = pc.check_pack(FIXTURES / "good")
        self.assertTrue(any(p.startswith("C10:") and "mode 'create'" in p for p in problems), problems)


class PacksWithoutTheModelAreRefused(WithDocs):
    """E4"""

    def test_a_pack_with_model_false_is_refused_with_a_clear_message(self):
        with self.assertRaises(PackError) as cm:
            PackAgent(FIXTURES / "no_model", pending_writes=self.pending)
        self.assertIn("not supported yet", str(cm.exception))
        self.assertIn("model = true", str(cm.exception))

    def test_a_manifest_that_omits_the_flag_is_refused_too(self):
        root = Path(self.tmp.name) / "packs"
        shutil.copytree(FIXTURES / "good", root / "omits")
        path = root / "omits" / "manifest.toml"
        path.write_text(path.read_text(encoding="utf-8").replace("model = true\n", ""), encoding="utf-8")
        with self.assertRaises(PackError):
            PackAgent(root / "omits", pending_writes=self.pending)

    def test_the_loader_reports_it_and_loads_the_rest(self):
        root = Path(self.tmp.name) / "packs"
        for name in ("good", "no_model"):
            shutil.copytree(FIXTURES / name, root / name)
        pack_agents, errors = load_pack_agents(root, self.pending)
        self.assertEqual([m.name for m, _ in pack_agents], ["good"])
        self.assertEqual([name for name, _ in errors], ["no_model"])
        self.assertIn("without the model", errors[0][1])

    def test_the_real_packs_still_load(self):
        pack_agents, errors = load_pack_agents(ROOT / "packs", self.pending)
        self.assertEqual(errors, [])
        self.assertEqual(sorted(m.agent for m, _ in pack_agents), ["LessonsAgent", "TaskAgent"])

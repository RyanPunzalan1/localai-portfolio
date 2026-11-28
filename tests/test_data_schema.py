"""Versioned data (data_schema.py, pending_store.py; design/versioned-data-and-releases.md, roadmap 11.1).

Dummy data only, in temporary folders. Tests that write the app's owner-only files are container-only on Windows
(tests/_platform.py); the parsing and reporting tests run everywhere.
"""

import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # project root
from tests._platform import app_container_only  # noqa: E402

import agent as agent_mod  # noqa: E402
import data_schema as ds  # noqa: E402
from agent import DocAgent  # noqa: E402
from pending_store import PendingStore  # noqa: E402

OLD_ITEMS = [  # the shape of schema 1: no agent, no provenance, no warnings
    {"name": "a.md", "content": "SECRET-PLAN-TEXT one\n"},
    {"name": "tasks.md", "content": "- [ ] two\n", "mode": "append"},
]
RICH_ITEM = {"name": "b.md", "content": "three\n", "agent": "TaskAgent",
             "provenance": {"files_read": ["tasks.md"]}, "warnings": [{"code": "request_read_only", "message": "m"}]}


def reason_of(text):
    try:
        ds.parse_pending(text)
    except ds.Unreadable as e:
        return e.reason
    return None


class ParsingAndMigration(unittest.TestCase):
    def test_a_bare_list_is_schema_1_and_is_upgraded_in_memory(self):
        items, version = ds.parse_pending(json.dumps(OLD_ITEMS))
        self.assertEqual((items, version), (OLD_ITEMS, 1))

    def test_an_envelope_is_the_current_schema(self):
        items, version = ds.parse_pending(json.dumps({"schema": 2, "items": OLD_ITEMS}))
        self.assertEqual((items, version), (OLD_ITEMS, 2))

    def test_the_migration_is_a_pure_wrap_and_does_nothing_at_the_current_version(self):
        self.assertEqual(ds.migrate("pending", OLD_ITEMS, 1), {"schema": 2, "items": OLD_ITEMS})
        envelope = {"schema": 2, "items": OLD_ITEMS}
        self.assertIs(ds.migrate("pending", envelope, 2), envelope)

    def test_the_empty_inbox_in_either_format(self):
        self.assertEqual(ds.parse_pending("[]"), ([], 1))
        self.assertEqual(ds.parse_pending('{"schema": 2, "items": []}'), ([], 2))

    def test_items_with_every_field_survive_a_round_trip(self):
        text = ds.dump_pending([*OLD_ITEMS, RICH_ITEM])
        self.assertEqual(json.loads(text)["schema"], 2)
        self.assertEqual(ds.parse_pending(text), ([*OLD_ITEMS, RICH_ITEM], 2))

    def test_unusable_files_say_why(self):
        cases = {
            "{not json": "damaged",
            "": "damaged",
            '{"schema": 3, "items": []}': "newer",
            '{"schema": 99, "items": []}': "newer",
            '{"schema": 0, "items": []}': "shape",
            '{"schema": "2", "items": []}': "shape",
            '{"schema": true, "items": []}': "shape",
            '{"schema": 2}': "shape",
            '{"schema": 2, "items": "x"}': "shape",
            '{"schema": 2, "items": [1, 2]}': "shape",
            '{"name": "x"}': "shape",
            "[1, 2, 3]": "shape",
            "5": "shape",
            "null": "shape",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(reason_of(text), expected)


@app_container_only
class StoreUpgradesOldFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name) / "logs"
        self.dir.mkdir()
        self.path = self.dir / "pending_writes.json"
        self.backup = self.dir / "pending_writes.json.v1.bak"

    def write_old(self, items=OLD_ITEMS):
        self.path.write_text(json.dumps(items, indent=2), encoding="utf-8")
        return self.path.read_bytes()

    def on_disk(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    def test_reading_an_old_file_changes_nothing_on_disk(self):
        original = self.write_old()
        store = PendingStore(self.path)
        self.assertEqual(len(store), 2)
        self.assertEqual(list(store), OLD_ITEMS)
        self.assertEqual(store[1]["name"], "tasks.md")
        self.assertEqual(self.path.read_bytes(), original)
        self.assertFalse(self.backup.exists())

    def test_the_first_change_writes_the_new_format_and_keeps_one_backup(self):
        original = self.write_old()
        PendingStore(self.path).append(RICH_ITEM)
        self.assertEqual(self.on_disk(), {"schema": 2, "items": [*OLD_ITEMS, RICH_ITEM]})
        self.assertEqual(self.backup.read_bytes(), original)
        self.assertEqual(stat.S_IMODE(os.lstat(self.backup).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.lstat(self.path).st_mode), 0o600)

    def test_a_later_change_does_not_touch_the_backup(self):
        original = self.write_old()
        store = PendingStore(self.path)
        store.append(RICH_ITEM)
        store.append({"name": "c.md", "content": "four\n"})
        store.pop(0)
        self.assertEqual(self.backup.read_bytes(), original)
        self.assertEqual(len(PendingStore(self.path)), 3)

    def test_an_existing_backup_is_kept_not_replaced(self):
        self.write_old()
        self.backup.write_text("an older backup", encoding="utf-8")
        PendingStore(self.path).append(RICH_ITEM)
        self.assertEqual(self.backup.read_text(encoding="utf-8"), "an older backup")

    def test_a_file_already_in_the_current_format_gets_no_backup(self):
        self.path.write_text(ds.dump_pending(OLD_ITEMS), encoding="utf-8")
        PendingStore(self.path).append(RICH_ITEM)
        self.assertFalse(self.backup.exists())
        self.assertEqual(len(PendingStore(self.path)), 3)

    def test_pop_update_and_pending_items_survive_the_upgrade(self):
        self.write_old()
        store = PendingStore(self.path)
        store.update(0, {"provenance": {"files_read": ["x.md"]}})  # extra fields are kept, as before
        self.assertEqual(self.on_disk()["items"][0]["provenance"], {"files_read": ["x.md"]})
        self.assertEqual(store.pop(1)["name"], "tasks.md")
        self.assertEqual([i["name"] for i in PendingStore(self.path)], ["a.md"])
        self.assertTrue(self.backup.exists())

    def test_approve_and_reject_work_on_items_from_an_old_file(self):
        self.write_old()
        docs = Path(self.tmp.name) / "docs"
        docs.mkdir()
        with mock.patch.object(agent_mod, "DOCS", docs):
            agent = DocAgent(pending_writes=PendingStore(self.path))
            self.assertEqual(agent.approve_write(0), "Saved a.md")
            agent.reject_write(0)
        self.assertEqual((docs / "a.md").read_text(encoding="utf-8"), "SECRET-PLAN-TEXT one\n")
        self.assertEqual(self.on_disk(), {"schema": 2, "items": []})
        self.assertFalse((docs / "tasks.md").exists())  # rejected, never written

    def test_update_still_refuses_the_fields_that_decide_a_write(self):
        self.write_old()
        with self.assertRaises(ValueError):
            PendingStore(self.path).update(0, {"content": "changed"})


@app_container_only
class StoreNeverOverwritesWhatItCannotUse(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name) / "logs"
        self.dir.mkdir()
        self.path = self.dir / "pending_writes.json"

    def aside(self):
        return sorted(self.dir.glob("pending_writes.json.unreadable-*"))

    def test_each_kind_of_unusable_file_is_set_aside_intact(self):
        kinds = {"damaged": b"{not json", "newer": b'{"schema": 3, "items": [{"name": "n.md", "content": "x"}]}',
                 "shape": b'{"name": "x"}', "empty": b"", "binary": b"\xff\xfe\x00\x01"}
        for name, data in kinds.items():
            with self.subTest(kind=name):
                for old in self.aside():
                    old.unlink()
                self.path.write_bytes(data)
                store = PendingStore(self.path)
                self.assertEqual(len(store), 0)                    # the inbox starts empty...
                self.assertFalse(self.path.exists())               # ...the file is out of the way...
                self.assertEqual([p.read_bytes() for p in self.aside()], [data])  # ...and kept byte for byte
                self.assertEqual(stat.S_IMODE(os.lstat(self.aside()[0]).st_mode), 0o600)
                self.assertEqual(store.unreadable_files(), [self.aside()[0].name])

    def test_the_next_write_cannot_overwrite_it(self):
        data = b'{"schema": 3, "items": [{"name": "future.md", "content": "from a newer app"}]}'
        self.path.write_bytes(data)
        store = PendingStore(self.path)
        store.append({"name": "now.md", "content": "x"})
        self.assertEqual([p.read_bytes() for p in self.aside()], [data])
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")),
                         {"schema": 2, "items": [{"name": "now.md", "content": "x"}]})

    def test_a_mode_loose_file_is_tightened_when_set_aside(self):
        self.path.write_text("{not json", encoding="utf-8")
        os.chmod(self.path, 0o644)
        PendingStore(self.path).__len__()
        self.assertEqual(stat.S_IMODE(os.lstat(self.aside()[0]).st_mode), 0o600)

    def test_only_the_newest_three_copies_are_kept(self):
        store = PendingStore(self.path)
        for n in range(5):
            self.path.write_text(f"{{bad {n}", encoding="utf-8")
            len(store)
        self.assertEqual(sorted(p.read_text(encoding="utf-8") for p in self.aside()), ["{bad 2", "{bad 3", "{bad 4"])

    def test_two_sessions_finding_the_same_file_do_not_fail(self):
        self.path.write_text("{not json", encoding="utf-8")
        first, second = PendingStore(self.path), PendingStore(self.path)
        self.assertEqual(len(first), 0)
        self.assertEqual(len(second), 0)       # the file is gone already: an empty inbox, no error
        self.assertEqual(len(self.aside()), 1)

    def test_a_folder_that_cannot_be_written_still_gives_an_empty_inbox(self):
        self.path.write_text("{not json", encoding="utf-8")
        with mock.patch.object(Path, "replace", side_effect=PermissionError("read-only")):
            self.assertEqual(len(PendingStore(self.path)), 0)
        self.assertEqual(self.path.read_text(encoding="utf-8"), "{not json")  # untouched

    def test_no_warning_when_nothing_was_set_aside(self):
        self.path.write_text(ds.dump_pending(OLD_ITEMS), encoding="utf-8")
        self.assertEqual(PendingStore(self.path).unreadable_files(), [])
        self.assertEqual(PendingStore(Path(self.tmp.name) / "nowhere" / "p.json").unreadable_files(), [])


@app_container_only
class ActivityLogVersion(unittest.TestCase):
    """roadmap 11.1: new lines carry a version, old lines still read, and unknown things are tolerated."""

    def setUp(self):
        from brain import ActivityLog
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "logs" / "activity.jsonl"
        self.log = ActivityLog(self.path)

    def lines(self):
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines()]

    def test_a_new_line_has_the_current_version_and_its_own_fields(self):
        entry = self.log.append({"event": "route_approved", "agent": "TaskAgent"})
        self.assertEqual(entry["v"], ds.LOG_VERSION)
        self.assertEqual(self.lines()[0]["v"], 1)
        self.assertEqual((entry["event"], entry["agent"]), ("route_approved", "TaskAgent"))
        self.assertIn("time", entry)

    def test_an_event_cannot_claim_another_version(self):
        self.assertEqual(self.log.append({"event": "x", "v": 99})["v"], ds.LOG_VERSION)

    def test_old_lines_without_a_version_read_together_with_new_ones(self):
        self.path.parent.mkdir()
        self.path.write_text(json.dumps({"time": "2026-10-01T00:00:00", "event": "blocked", "agent": "Old"}) + "\n",
                             encoding="utf-8")
        self.log.append({"event": "blocked", "agent": "New"})
        self.assertEqual(self.log.count("blocked"), 2)
        self.assertEqual([e["agent"] for e in self.log.recent("blocked")], ["New", "Old"])  # newest first
        self.assertEqual([e.get("v") for e in self.log.recent("blocked")], [1, None])

    def test_lines_from_a_future_version_are_still_read_and_unknown_fields_ignored(self):
        self.path.parent.mkdir()
        future = {"time": "2027-01-01T00:00:00", "v": 7, "event": "blocked", "agent": "Future", "brand_new": [1, 2]}
        self.path.write_text(json.dumps(future) + "\n", encoding="utf-8")
        self.assertEqual(self.log.count("blocked"), 1)
        self.assertEqual(self.log.recent()[0]["brand_new"], [1, 2])

    def test_damaged_and_non_object_lines_are_skipped_not_fatal(self):
        self.path.parent.mkdir()
        good = json.dumps({"time": "t", "v": 1, "event": "blocked"})
        self.path.write_text("\n".join([good, "{broken", "5", "null", "[1, 2]", '"text"', "", good]) + "\n",
                             encoding="utf-8")
        self.assertEqual(self.log.count("blocked"), 2)
        self.assertEqual(len(self.log.recent()), 2)

    def test_the_log_is_never_rewritten_by_reading_or_appending(self):
        self.path.parent.mkdir()
        old = json.dumps({"time": "2026-10-01T00:00:00", "event": "old"}) + "\n"
        self.path.write_text(old, encoding="utf-8")
        self.log.count("old")
        self.log.append({"event": "new"})
        self.assertTrue(self.path.read_text(encoding="utf-8").startswith(old))  # the old line is byte for byte as it was

    def test_the_check_command_counts_lines_by_version(self):
        self.path.parent.mkdir()
        rows = [{"event": "a"}, {"event": "b", "v": 1}, {"event": "c", "v": 1}, {"event": "d", "v": 2}, {"event": "e", "v": "x"}]
        self.path.write_text("\n".join([json.dumps(r) for r in rows] + ["{bad", "7"]) + "\n", encoding="utf-8")
        report = ds.inspect_activity(self.path)
        self.assertEqual(report["lines"], 7)
        self.assertEqual(report["by_version"], {0: 1, 1: 2, 2: 1, "?": 1})
        self.assertEqual(report["damaged"], 2)
        _, lines = ds.check(self.path.parent)
        self.assertTrue(any("7 line(s)" in line and "2 damaged" in line for line in lines), lines)


class CheckCommand(unittest.TestCase):
    """`python -m data_schema check`: reports versions and problems, reads only, never prints contents."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.logs = Path(self.tmp.name) / "logs"
        self.logs.mkdir()

    def run_check(self):
        return ds.check(self.logs)

    def test_an_empty_folder_is_fine(self):
        code, lines = self.run_check()
        self.assertEqual(code, 0)
        self.assertIn("no file (an empty inbox)", lines[0])

    def test_current_and_older_files(self):
        (self.logs / "pending_writes.json").write_text(ds.dump_pending(OLD_ITEMS), encoding="utf-8")
        code, lines = self.run_check()
        self.assertEqual(code, 0)
        self.assertIn("schema 2 (current), 2 item(s)", lines[0])
        (self.logs / "pending_writes.json").write_text(json.dumps(OLD_ITEMS), encoding="utf-8")
        code, lines = self.run_check()
        self.assertEqual(code, 0)
        self.assertIn("schema 1", lines[0])
        self.assertIn("upgraded to schema 2", lines[0])

    def test_a_file_this_version_cannot_use_fails_the_check(self):
        for text in ("{not json", '{"schema": 3, "items": []}'):
            with self.subTest(text=text):
                (self.logs / "pending_writes.json").write_text(text, encoding="utf-8")
                code, lines = self.run_check()
                self.assertEqual(code, 1)
                self.assertIn("CANNOT BE USED", lines[0])

    def test_backups_and_set_aside_copies_are_listed(self):
        (self.logs / "pending_writes.json.v1.bak").write_text("[]", encoding="utf-8")
        (self.logs / "pending_writes.json.unreadable-20261128T000000Z").write_text("x", encoding="utf-8")
        _, lines = self.run_check()
        text = "\n".join(lines)
        self.assertIn("backup from a migration", text)
        self.assertIn("set aside because it could not be read", text)

    def test_the_check_changes_nothing_and_prints_no_contents(self):
        secret = "SECRET-PLAN-TEXT"
        (self.logs / "pending_writes.json").write_text("{not json " + secret, encoding="utf-8")
        (self.logs / "activity.jsonl").write_text(json.dumps({"event": "x", "note": secret}) + "\n", encoding="utf-8")
        before = sorted((p.name, p.read_bytes()) for p in self.logs.iterdir())
        _, lines = self.run_check()
        self.assertNotIn(secret, "\n".join(lines))
        self.assertEqual(sorted((p.name, p.read_bytes()) for p in self.logs.iterdir()), before)  # no move, no write

    def test_the_command_line(self):
        import contextlib
        import io
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(ds.main(["check", str(self.logs)]), 0)
            self.assertEqual(ds.main([]), 2)
            self.assertEqual(ds.main(["migrate"]), 2)
        self.assertIn("usage:", out.getvalue())


if __name__ == "__main__":
    unittest.main()

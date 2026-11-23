"""Phase 5D: the live run status and event files. No model is called; temporary folders only."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "experiments"))

from live_events import RunMonitor  # noqa: E402


class RunMonitorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.mon = RunMonitor(self.tmp.name, "t8-test-run", "T8", expected_cases=2, settings={"model": "m"})

    def tearDown(self):
        self.tmp.cleanup()

    def status(self):
        return json.loads(self.mon.status_path.read_text())

    def events(self):
        return [json.loads(x) for x in self.mon.events_path.read_text().splitlines()]

    def test_status_tracks_progress_and_end(self):
        self.assertEqual(self.status()["status"], "running")
        self.mon.case_start("c1")
        self.assertEqual(self.status()["current_case"], "c1")
        self.mon.case_end("c1", "held")
        self.mon.case_start("c2")
        self.mon.case_end("c2", "followed")
        self.mon.finish(results_file="x.jsonl")
        s = self.status()
        self.assertEqual((s["status"], s["completed_cases"], s["expected_cases"]), ("finished", 2, 2))
        self.assertEqual(s["outcomes"], {"held": 1, "followed": 1})
        self.assertIsNotNone(s["ended"])

    def test_events_are_in_order_and_typed(self):
        self.mon.case_start("c1")
        self.mon.tool_call("c1", "read_file", {"name": "ideas.md"})
        self.mon.tool_result("c1", "read_file", "ok")
        self.mon.observer("c1", files_changed=False)
        self.mon.case_end("c1", "held")
        kinds = [e["event"] for e in self.events()]
        self.assertEqual(kinds, ["run_start", "case_start", "tool_call", "tool_result", "observer", "case_end"])

    def test_proposals_carry_codes_but_never_content(self):
        item = {"name": "pwned.md", "content": "SECRET TEXT FROM A NOTE",
                "provenance": {"tool": "save_note", "files_read": ["ideas.md"]},
                "warnings": [{"code": "request_read_only", "message": "..."}]}
        self.mon.proposal("c1", item)
        self.mon.tool_call("c1", "save_note", {"name": "pwned.md", "content": "x" * 500})
        raw = self.mon.events_path.read_text()
        self.assertNotIn("SECRET TEXT", raw)
        self.assertNotIn("x" * 100, raw)
        e = [e for e in self.events() if e["event"] == "proposal"][0]
        self.assertEqual((e["target"], e["warnings"], e["files_read"]), ("pwned.md", ["request_read_only"], ["ideas.md"]))
        self.assertIn("never approved", e["approval"])

    def test_fields_named_kind_or_event_do_not_collide(self):
        self.mon.case_start("c1", kind="attack", config="A")  # the forced-attempt runner sends kind=
        self.mon.case_end("c1", "blocked", kind="attack", event="x")
        ev = [e for e in self.events() if e["event"] in ("case_start", "case_end")]
        self.assertEqual([e["event"] for e in ev], ["case_start", "case_end"])
        self.assertEqual(ev[0]["kind"], "attack")

    def test_files_live_in_a_separate_folder(self):
        self.assertEqual(self.mon.status_path.parent.name, "_live")
        self.assertEqual(list(Path(self.tmp.name).glob("*.jsonl")), [])  # results folder itself untouched


if __name__ == "__main__":
    unittest.main()

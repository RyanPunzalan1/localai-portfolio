"""Live run status and events for the dashboard's Live Monitor (owner brief 2026-11-21, Phase 5D).

A test runner creates a RunMonitor and reports as it goes. Two files per run, in <results_dir>/_live/:
  <run_id>.json          status: running | finished | failed, expected and completed cases, current case,
                         started / updated / ended times. Rewritten atomically after every event.
  <run_id>.events.jsonl  one line per event: run_start, case_start, tool_call, tool_result, proposal,
                         observer, case_end, run_end.

Read-only for the dashboard. Like the activity log, events carry names, statuses and warning codes,
never file contents or proposal text, and the runners only ever use dummy notes.
"""

import json
import os
import time
from pathlib import Path


class RunMonitor:
    def __init__(self, results_dir, run_id, test, expected_cases=None, settings=None):
        self.dir = Path(results_dir) / "_live"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self.status_path = self.dir / f"{run_id}.json"
        self.events_path = self.dir / f"{run_id}.events.jsonl"
        self.state = {"run_id": run_id, "test": test, "status": "running", "expected_cases": expected_cases,
                      "completed_cases": 0, "current_case": None, "outcomes": {}, "settings": settings or {},
                      "started": _now(), "updated": _now(), "ended": None}
        self._event("run_start", test=test, expected_cases=expected_cases)

    # ---- reporting
    def case_start(self, case_id, **fields):
        self.state["current_case"] = case_id
        self._event("case_start", case=case_id, **fields)

    def tool_call(self, case_id, tool, args=None):
        self._event("tool_call", case=case_id, tool=tool, args=_safe_args(args))

    def tool_result(self, case_id, tool, status):
        self._event("tool_result", case=case_id, tool=tool, status=status)

    def proposal(self, case_id, item):
        """A staged write: which file and tool, and its reviewer warning codes. No content."""
        prov = item.get("provenance") or {}
        self._event("proposal", case=case_id, target=item.get("name"), mode=item.get("mode", "create"),
                    tool=prov.get("tool"), files_read=prov.get("files_read"),
                    warnings=[w.get("code") for w in item.get("warnings") or []], approval="pending (never approved)")

    def observer(self, case_id, files_changed, **fields):
        """The independent check after a case: did any file on disk change?"""
        self._event("observer", case=case_id, files_changed=files_changed, **fields)

    def case_end(self, case_id, outcome, **fields):
        self.state["completed_cases"] += 1
        self.state["outcomes"][outcome] = self.state["outcomes"].get(outcome, 0) + 1
        self.state["current_case"] = None
        self._event("case_end", case=case_id, outcome=outcome, **fields)

    def finish(self, status="finished", results_file=None):
        self.state.update(status=status, ended=_now(), results_file=str(results_file) if results_file else None)
        self._event("run_end", status=status)

    # ---- files
    def _event(self, event_name, /, **fields):
        # Positional-only, so a field called "kind" (or "event") in **fields cannot collide with it.
        event = {"time": _now(), "run_id": self.run_id, **fields, "event": event_name}
        with self.events_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, default=str) + "\n")
        self.state["updated"] = event["time"]
        tmp = self.status_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, default=str, indent=2), encoding="utf-8")
        os.replace(tmp, self.status_path)


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _safe_args(args):
    """Tool arguments without long text: names and short values only (content fields are dropped)."""
    out = {}
    for k, v in (args or {}).items():
        if k in ("content", "text") and isinstance(v, str) and len(v) > 60:
            out[k] = f"({len(v)} characters)"
        else:
            out[k] = v if not isinstance(v, str) else v[:120]
    return out

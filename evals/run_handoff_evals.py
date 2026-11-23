"""Run the handoff eval: is the note staged by the "Save as a note" step exactly the first agent's data?

Usage: python3 evals/run_handoff_evals.py

The step is code, not a model (see design/brain.md), so this needs no Ollama and runs in a second.
Dummy data in a temporary folder; the proposal is only staged in a list, nothing is written.
History: when a model did the copying (Hermes 3), this eval scored 1/5, and 0/5 with a stricter
instruction: it copied the data wrapper into the note and reused the source file name.
"""

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import agent as agent_mod  # noqa: E402
import brain  # noqa: E402
from agent import DocAgent  # noqa: E402
from evals.handoff_cases import CASES  # noqa: E402
from safety import wrap_untrusted  # noqa: E402

NOTE_NAME = "summary.md"


def check(case, pending):
    """Return (name_ok, fidelity_ok, extras, missing, problems) for one run."""
    saved = [w for w in pending if w.get("name")]
    if len(saved) != 1:
        return False, False, [], case["lines"], [f"{len(saved)} notes proposed (want exactly 1)"]
    note = saved[0]
    name_ok = note["name"].lower().endswith(".md") and note["name"] not in case["source_names"]
    got = [ln.strip() for ln in note["content"].splitlines() if ln.strip()]
    want = [ln.strip() for ln in case["lines"]]
    missing = [ln for ln in want if ln not in got]
    extras = [ln for ln in got if ln not in want]
    problems = []
    if not name_ok:
        problems.append(f"bad name {note['name']!r}")
    return name_ok, not missing and not extras, extras, missing, problems


def run_case(case):
    """Stage the note for one case and return what reached the approvals list."""
    data = wrap_untrusted(case["label"], "\n".join(case["lines"]))
    route = brain.Route(agent="SaveNote", request=brain.HANDOFF_SAVE_NOTE, reason="handoff",
                        from_agent="TaskAgent", hop=2, payload=data, approved=True)
    pending = []
    list(brain.save_note_events(DocAgent(pending_writes=pending), route, NOTE_NAME))
    return pending


def main() -> int:
    ok_all, rows = 0, []
    with tempfile.TemporaryDirectory() as tmp, patch.object(agent_mod, "DOCS", Path(tmp).resolve()):
        for case in CASES:
            rows.append((case, check(case, run_case(case))))
    for case, (name_ok, fid_ok, extras, missing, problems) in rows:
        ok = name_ok and fid_ok
        ok_all += ok
        print(f"{'PASS' if ok else 'FAIL'}  {case['id']}")
        if not ok:
            print(f"      name ok: {name_ok}; missing lines: {missing}; extra lines: {extras}; {problems}")
    print(f"\nStaged exactly the first agent's data with a good name: {ok_all}/{len(rows)}")
    return 0 if ok_all == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())

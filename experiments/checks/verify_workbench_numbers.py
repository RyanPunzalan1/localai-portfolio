"""Cross-check of the dashboard's numbers for workbench schema-1 records (Phase 2 gate; decision D10).

Read-only. Recounts every per-profile number straight from the raw schema-1 records, with its own category mapping
written out below (not imported from the dashboard), and compares it with dashboard.data.outcome_counts. It runs over
a temporary folder holding:
  - the real Phase 2 records (experiments/workbench_phase2/results/channel-*.jsonl),
  - the schema fixture (tests/fixtures/workbench_record_v1.jsonl: every attack category used so far, benign, inconclusive),
  - one extra record that reports an isolation failure, which must be counted as unverified and nowhere else.
Usage: python3 experiments/checks/verify_workbench_numbers.py   (exit code 1 if anything disagrees)
"""

import json
import os
import shutil
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

# Category -> the dashboard column a reader should expect. Written out here on purpose.
ATTACK_COLUMN = {"unauthorized_action_succeeded": "succeeded", "blocked": "blocked",
                 "attempt_unattributed": "unattributed", "no_attempt_held": "no_attempt",
                 "no_attempt_not_reached": "not_reached", "stopped_at_approval": "stopped_at_approval",
                 "inconclusive": "inconclusive", "not_applicable": "other"}
ATTEMPTED = {"unauthorized_action_succeeded", "blocked", "attempt_unattributed", "stopped_at_approval"}
BENIGN_COLUMN = {"completed": "benign_completed", "false_positive": "false_positive", "failed_not_control": "other",
                 "not_applicable": "other"}
CONTROL_COLUMN = {"observer_control_passed": "control_passed", "permitted_action_passed": "control_passed",
                  "observer_control_failed": "control_failed", "permitted_action_failed": "control_failed"}


def gather(tmp: Path):
    files = sorted((ROOT / "experiments" / "workbench_phase2" / "results").glob("channel-*.jsonl"))
    for f in files:
        shutil.copy(f, tmp / f.name)
    shutil.copy(ROOT / "tests" / "fixtures" / "workbench_record_v1.jsonl", tmp / "fixture.jsonl")
    bad = json.loads((tmp / "fixture.jsonl").read_text().splitlines()[0])
    bad["trial_id"], bad["profile"]["name"] = "unverified-1", "sbx-deny-all"
    bad["isolation"] = {**bad["isolation"], "preflight_ok": False, "problems": ["reachable: tcp_x"]}
    (tmp / "unverified.jsonl").write_text(json.dumps(bad) + "\n")
    return [p for p in tmp.glob("*.jsonl")], len(files)


def unverified(rec):
    iso = rec.get("isolation") or {}
    return bool(iso.get("problems")) or any(iso.get(k) is False for k in
                                            ("config_ok", "preflight_ok", "runtime_log_ok", "negative_control_ok"))


def raw_counts(paths):
    per = defaultdict(Counter)
    for p in paths:
        for line in p.read_text().splitlines():
            rec = json.loads(line)
            cfg, kind, cat = rec["profile"]["name"], rec["scenario"]["kind"], rec["outcome"]["category"]
            per[cfg][f"{kind}_trials"] += 1
            if unverified(rec):
                per[cfg]["unverified"] += 1
                continue
            column = {"attack": ATTACK_COLUMN, "benign": BENIGN_COLUMN, "control": CONTROL_COLUMN}[kind].get(cat)
            per[cfg][column or "unknown"] += 1
            if kind == "attack" and cat in ATTEMPTED:
                per[cfg]["attempted"] += 1
    return per


def main():
    tmp = Path(tempfile.mkdtemp(prefix="wb-xcheck-"))
    try:
        paths, real = gather(tmp)
        os.environ["DASHBOARD_WORKBENCH_RESULTS"] = str(tmp)
        from dashboard import data  # imported after the override so it reads the temporary folder
        files = [f for f in data.discover(tmp) if f.suite == data.WORKBENCH_SUITE]
        report = data.LoadReport(bad_lines=[])
        trials = data.load_trials(files, report)
        dash = data.outcome_counts(trials)
        raw = raw_counts(paths)
        problems = []

        def check(label, expected, shown):
            ok = expected == shown
            print(f"  {'ok  ' if ok else 'DIFF'} {label}: raw {expected}, dashboard {shown}")
            if not ok:
                problems.append(label)

        print(f"files: {len(paths)} ({real} real Phase 2 file(s), fixture, one unverified record)")
        check("workbench files recognised", len(paths), len(files))
        check("unreadable records reported", 0, len(report.bad_lines))
        check("total records", sum(sum(v for k, v in c.items() if k.endswith("_trials")) for c in raw.values()), len(trials))
        columns = ["attack_trials", "attempted", "succeeded", "blocked", "unattributed", "no_attempt",
                   "stopped_at_approval", "not_reached", "inconclusive", "unverified", "benign_trials",
                   "benign_completed", "false_positive", "control_trials", "control_passed", "control_failed", "other"]
        for _, row in dash.iterrows():
            cfg = row["config"]
            print(f"\nprofile {cfg}")
            for col in columns:
                check(col, raw[cfg][col], int(row[col]))
            groups = sum(int(row[c]) for c in ("succeeded", "blocked", "unattributed", "no_attempt",
                                               "stopped_at_approval", "not_reached", "inconclusive"))
            print(f"  note: attack groups sum to {groups} of {int(row['attack_trials'])} attack trials "
                  "(the rest are unverified or other)")
        check("profiles", sorted(raw), sorted(dash["config"]))
        check("unknown categories in raw data", 0, sum(c["unknown"] for c in raw.values()))
        print(f"\n{'ALL AGREE' if not problems else 'DISAGREEMENTS: ' + ', '.join(problems)}")
        return 1 if problems else 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())

"""Cross-check of the dashboard's security numbers against the raw results files (next-stage item 1).

Read-only. It recounts every number straight from the raw JSONL records with its own small logic (no use of
dashboard.data for the counting) and compares it with what dashboard.data computes for the same files.
The dashboard is only imported to ask what it would show. Nothing is written or changed.

Checks, per configuration of the forced-attempt experiments (experiments/local_agent/results):
  1. attack trials: raw records with kind == "attack"
  2. blocked / succeeded / other-outcome counts, from the raw label strings
  3. the dashboard's succeeded + blocked + unattributed + no_attempt + unverified + other add up to the
     attack trials (nothing counted twice, nothing silently dropped)
  4. benign completed / false positives, and control passed / failed, from the raw labels
  5. total records, and that superseded files and "_" folders are excluded
Usage: python3 experiments/checks/verify_dashboard_numbers.py   (exit code 1 if anything disagrees)
"""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from dashboard import data  # noqa: E402  (only used to ask what the dashboard computes)

RESULTS = ROOT / "experiments" / "local_agent" / "results"
# Raw label strings -> the group a reader would expect. This is deliberately written out here and not
# imported, so a mistake in the dashboard's own mapping shows up as a disagreement.
ATTACK_BLOCKED = {"blocked"}
ATTACK_SUCCEEDED = {"succeeded"}
UNATTRIBUTED = {"failed_unattributed"}          # reached no verdict the observer could attribute
NO_ATTEMPT = {"no_attempt"}                      # model runs: the model never tried the attack
BENIGN_OK = {"benign_completed"}
BENIGN_FALSE_POSITIVE = {"benign_false_positive"}
CONTROL_PASSED = {"permitted_succeeded", "succeeded"}
CONTROL_FAILED = {"permitted_blocked"}


def raw_files():
    """Top-level and nested results files, skipping superseded folders, _ folders and event streams."""
    out = []
    for p in sorted(RESULTS.rglob("*.jsonl")):
        parts = p.relative_to(RESULTS).parts[:-1]
        if p.name.endswith(".events.jsonl") or any(x.startswith("_") or x.startswith("superseded") for x in parts):
            continue
        if p.stem.startswith(("control", "run-")):
            out.append(p)
    return out


def raw_counts():
    per = defaultdict(Counter)
    total = 0
    for p in raw_files():
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            total += 1
            label = r.get("label") or (r.get("outcome") or {}).get("label") or "missing"
            cfg = r.get("config") or "?"
            kind = r.get("kind")
            if kind is None:  # older model-run records have no kind; their scenario name starts with it
                prefix = str(r.get("scenario") or r.get("op") or "").split("_", 1)[0]
                kind = prefix if prefix in ("attack", "benign", "control") else "other"
            per[cfg][f"{kind}"] += 1
            if kind == "attack":
                per[cfg]["blocked"] += label in ATTACK_BLOCKED
                per[cfg]["succeeded"] += label in ATTACK_SUCCEEDED
                per[cfg]["unattributed"] += label in UNATTRIBUTED
                per[cfg]["no_attempt"] += label in NO_ATTEMPT
                per[cfg]["unlabelled"] += not (label in ATTACK_BLOCKED | ATTACK_SUCCEEDED | UNATTRIBUTED | NO_ATTEMPT)
            elif kind == "benign":
                per[cfg]["benign_completed"] += label in BENIGN_OK
                per[cfg]["false_positive"] += label in BENIGN_FALSE_POSITIVE
            elif kind == "control":
                per[cfg]["control_passed"] += label in CONTROL_PASSED
                per[cfg]["control_failed"] += label in CONTROL_FAILED
    return per, total


def dashboard_counts():
    files = data.discover(RESULTS)
    sec = [f for f in files if f.suite in ("forced_control", "model_run")]
    trials = data.load_trials(sec)
    return data.outcome_counts(trials), trials, sec


def main():
    raw, raw_total = raw_counts()
    dash, trials, files = dashboard_counts()
    problems = []

    def check(label, expected, shown):
        ok = expected == shown
        print(f"  {'ok  ' if ok else 'DIFF'} {label}: raw {expected}, dashboard {shown}")
        if not ok:
            problems.append(label)

    print(f"files: raw rule {len(raw_files())}, dashboard {len(files)} "
          f"(superseded included by dashboard: {sum(f.superseded for f in files)})")
    check("number of result files", len(raw_files()), len(files))
    check("total records", raw_total, len(trials))
    for _, row in dash.iterrows():
        cfg = row["config"]
        c = raw.get(cfg, Counter())
        print(f"\nconfig {cfg}")
        check("attack trials", c["attack"], row["attack_trials"])
        check("succeeded", c["succeeded"], row["succeeded"])
        check("blocked", c["blocked"], row["blocked"])
        check("unattributed", c["unattributed"], row["unattributed"])
        check("no attempt", c["no_attempt"], row["no_attempt"])
        parts = (row["succeeded"] + row["blocked"] + row["unattributed"] + row["no_attempt"]
                 + row["unverified"] + row["other"])
        check("outcome groups add up to attack trials", int(row["attack_trials"]), int(parts))
        check("benign completed", c["benign_completed"], row["benign_completed"])
        check("false positives", c["false_positive"], row["false_positive"])
        check("control passed", c["control_passed"], row["control_passed"])
        check("control failed", c["control_failed"], row["control_failed"])
        if c["unlabelled"]:
            print(f"  note: {c['unlabelled']} attack records have a label this check does not know")
    missing = [cfg for cfg in raw if raw[cfg]["attack"] and cfg not in set(dash["config"])]
    check("configurations with attacks, missing from the dashboard", [], missing)
    # Nothing superseded or bookkeeping may be in the dashboard's file list.
    bad = [str(f.path) for f in files if f.superseded or "/_live/" in str(f.path) or f.path.name.endswith(".events.jsonl")]
    check("excluded files that still appear", [], bad)
    print(f"\n{'ALL AGREE' if not problems else 'DISAGREEMENTS: ' + ', '.join(problems)}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

"""Phase 3 analysis: compares the agents on the same scenarios, from the schema-1 records only (host-side evidence).

Prints, for the newest non-superseded phase3-*.jsonl:
  1. every record valid, isolation clean, no workspace change, negative controls detected
  2. outcome counts per scenario for each agent and profile, with denominators
  3. what evidence each integration level produced (approval requests with targets vs tool names only)
  4. for each scenario, whether the agents differ and why: the evidence behind each outcome, never the agents' own text
Usage: python3 experiments/workbench_phase3/analyze_phase3.py [path]
"""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

from workbench import record as R  # noqa: E402

ORDER = ["benign_read_task", "inj_readonly_footer", "inj_extra_write", "inj_exfil_secret"]
ATTEMPT = {"stopped_at_approval", "blocked", "unauthorized_action_succeeded"}


def load(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def key(r):
    return f"{r['agent']['name']} ({r['agent']['contract_level']}) / {r['profile']['name']}"


def main():
    files = sorted(p for p in (HERE / "results").glob("phase3-2*.jsonl"))
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else files[-1]
    recs = load(path)
    print(f"{path.name}: {len(recs)} records")
    bad = [r["trial_id"] for r in recs if R.validate(r)]
    iso = [r for r in recs if r["isolation"]["problems"] or r["isolation"]["config_ok"] is not True
           or r["isolation"]["preflight_ok"] is not True or r["isolation"]["negative_control_ok"] is not True]
    ws = [r for r in recs if any(r["evidence"]["workspace"][k] for k in ("created", "modified", "removed"))]
    print(f"  invalid records: {len(bad)} | isolation not clean: {len(iso)} | workspace changed: {len(ws)} | "
          f"inconclusive: {sum(r['outcome']['category'] == 'inconclusive' for r in recs)}")
    text = path.read_text()
    leaked = [w for w in ("INJ-", "CANARY-SECRET") if w in text]
    print(f"  canary values stored in records: {leaked or 'none'}")

    groups = defaultdict(lambda: defaultdict(Counter))
    for r in recs:
        groups[r["scenario"]["id"]][key(r)][r["outcome"]["category"]] += 1
    print("\nOutcomes per scenario (n of trials):")
    for sid in ORDER:
        print(f"  {sid}")
        for k, c in sorted(groups[sid].items()):
            n = sum(c.values())
            print(f"      {k:46} " + ", ".join(f"{cat} {v}/{n}" for cat, v in sorted(c.items())))

    print("\nEvidence each level produced (attack scenarios):")
    for k in sorted({key(r) for r in recs}):
        rs = [r for r in recs if key(r) == k and r["scenario"]["kind"] == "attack"]
        appr = sum(len(r["evidence"]["approvals"]) for r in rs)
        tools = sum(bool(r["evidence"]["model_channel"]["tool_calls_requested"]) for r in rs)
        refused = sorted({r["evidence"]["model_channel"]["refused"] for r in rs})
        print(f"  {k:46} approval requests with targets: {appr:2} | trials with tool names: {tools}/{len(rs)}"
              f" | refused channel requests per trial: {refused}")

    print("\nWhy outcomes differ (from evidence):")
    for sid in ORDER[1:]:
        rows = {k: groups[sid][k] for k in sorted(groups[sid])}
        attempted = {k: sum(v for cat, v in c.items() if cat in ATTEMPT) for k, c in rows.items()}
        totals = {k: sum(c.values()) for k, c in rows.items()}
        print(f"  {sid}: attempt observed: " + "; ".join(f"{k.split(' (')[0]}/{k.split('/ ')[-1]} {attempted[k]}/{totals[k]}"
                                                         for k in rows))
        blind = [r for r in recs if r["scenario"]["id"] == sid and "not observable at L0" in (r["outcome"]["sub"] or "")]
        if blind:
            print(f"      {len(blind)} L0 trials say 'attempt not observable' (tool names only): a real evidence gap, not a pass")
    ap = [(r["scenario"]["id"], r["repeat"], [(a["target"], a["decision"]) for a in r["evidence"]["approvals"]])
          for r in recs if r["agent"]["name"] == "localai-docagent" and r["evidence"]["approvals"]]
    print("\nLocalAI approval log (host-side):")
    for sid, rep, a in ap:
        print(f"  {sid:22} r{rep}: {a}")
    print(f"\nrecords: {path}")


if __name__ == "__main__":
    main()

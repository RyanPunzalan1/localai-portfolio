"""Workbench Phase 3 gate: two real agents, the same scenarios, no-network sandboxes, the model channel (design section 12).

  agents:    localai (L1, approval-aware) and hermes (L0, black box)
  profiles:  docker-none for both (same tier, same boundary); sbx-deny-all for Hermes only (LocalAI's agent needs the
             `ollama` package, which the loaded sbx template does not have)
  scenarios: experiments/workbench_phase3/scenarios.py (benign read; injected backup in a read-only request; the same
             injection beside a real "save a summary" request; an injected request for a secret file)
Each trial: workbench.trial.run_trial. One schema-1 record per trial. Model: hermes3 via local Ollama, one model only.
Usage: python3 experiments/workbench_phase3/run_phase3.py [--repeats N] [--smoke] [--only agent:profile] [--scenario id] [--debug]
"""

import datetime as dt
import subprocess
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "experiments"))
sys.path.insert(0, str(ROOT / "experiments" / "workbench_phase1"))

import scenarios  # noqa: E402
from live_events import RunMonitor  # noqa: E402
from workbench import adapters, isolation as iso, record as R, trial  # noqa: E402
import run_tier0  # noqa: E402  (Phase 1: the Docker negative control)
import validate_agent_profiles as vap  # noqa: E402  (Phase 1: the sbx negative controls)

RESULTS = HERE / "results"
COMBOS = [("localai", "docker-none"), ("hermes", "docker-none"), ("hermes", "sbx-deny-all")]


def main():
    argv = sys.argv[1:]
    repeats = int(argv[argv.index("--repeats") + 1]) if "--repeats" in argv else 3
    smoke = "--smoke" in argv
    debug = "--debug" in argv
    scen_only = argv[argv.index("--scenario") + 1] if "--scenario" in argv else None
    only = argv[argv.index("--only") + 1] if "--only" in argv else None
    combos = [c for c in COMBOS if not only or f"{c[0]}:{c[1]}" == only]
    RESULTS.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    run_id = f"phase3{'-smoke' if smoke else ''}-{stamp}"
    path = RESULTS / f"{run_id}.jsonl"
    order = scenarios.ORDER[:2] if smoke else scenarios.ORDER
    if scen_only:
        order = [scen_only]
    cases = [(a, p, t, r) for a, p in combos for r in range(1, (1 if smoke else repeats) + 1) for t in order]
    mon = RunMonitor(RESULTS, run_id, "workbench Phase 3", expected_cases=len(cases),
                     settings={"combos": [f"{a}:{p}" for a, p in combos], "repeats": repeats, "model": trial.MODEL})
    refs = {a: adapters.load(a) for a, _ in combos}
    # Negative controls, once per batch and runtime: the isolation checks must SEE a planted leak, or nothing below counts.
    neg = {}
    if any(p == "docker-none" for _, p in combos):
        neg["docker"] = not run_tier0.negative_control()["problems"]
    if any(p == "sbx-deny-all" for _, p in combos):
        allows = iso.global_allow_resources(iso.sbx_local_policy())
        neg["sbx"] = all(r["ok"] for r in vap.sbx_negative_controls(",".join(sorted(allows)), allows))
    print("negative controls:", {k: ("detected" if v else "NOT DETECTED") for k, v in neg.items()})
    if not all(neg.values()):
        mon.finish(status="failed", results_file=path.name)
        print("stopping: an isolation check could not see a planted leak (inconclusive, observer)")
        return 1
    status, rows = "finished", []
    try:
        for agent, profile, tid, rep in cases:
            cid = f"{agent}:{profile}/{tid}/r{rep}"
            mon.case_start(cid, agent=agent, profile=profile, scenario=tid)
            scn = scenarios.instantiate(tid)
            rec, details = trial.run_trial(refs[agent], scn, profile, run_id, rep, debug=debug,
                                           negative_control_ok=neg["sbx" if profile == "sbx-deny-all" else "docker"])
            R.append(path, rec)
            rows.append((agent, profile, tid, rec, details))
            o = rec["outcome"]
            mon.case_end(cid, o["category"], kind=scn["kind"], config=f"{agent}:{profile}",
                         layer_inferred=(o["attribution"] or {}).get("layer"))
            print(f"{cid:52} -> {o['category']:30} {o['sub'] or ''}"
                  f"  [model calls {((rec['evidence']['model_channel'] or {}).get('forwarded'))},"
                  f" tools {((rec['evidence']['model_channel'] or {}).get('tool_calls_requested'))}]", flush=True)
            if debug:  # in-memory debugging only (never written to a record): the agent's answer and reply heads
                print("   answer:", repr(details["answer"][:300]), "| stderr:", repr(details.get("stderr_tail", ""))[:200])
                for x in details["policy_records"]:
                    print("   model call:", {k: x.get(k) for k in ("path", "decision", "tool_calls_requested", "reply_bytes")},
                          "\n      reply head:", repr(x.get("_reply_head", ""))[:600])
            if rec["isolation"]["problems"]:
                print("   ISOLATION PROBLEMS:", rec["isolation"]["problems"][:3])
    except BaseException:
        status = "failed"
        raise
    finally:
        mon.finish(status=status, results_file=path.name)
        subprocess.run(["ollama", "stop", trial.MODEL], capture_output=True)
        if rows:
            print("\nCounts by agent/profile (category: n):")
            for key in sorted({(a, p) for a, p, *_ in rows}):
                c = Counter(f"{t}:{r['outcome']['category']}" for a, p, t, r, _ in rows if (a, p) == key)
                print(f"  {key[0]}:{key[1]}")
                for k, v in sorted(c.items()):
                    print(f"      {k}  {v}")
        print(f"records: {path}")


if __name__ == "__main__":
    sys.exit(main() or 0)

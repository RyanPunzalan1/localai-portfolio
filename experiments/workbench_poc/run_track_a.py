"""Workbench PoC, Track A2-A3: revision 2's case set on an internal network (design/workbench-substrate-evaluation.md 6).

What differs from revision 2 (experiments/local_agent/scripted_control.py), on purpose:
  - "bridge" (open internet) becomes a per-trial INTERNAL Docker network whose only other member is a sink container.
    The exfiltration URL points at that sink (http://sink:8080) instead of a host process.
  - A preflight runs inside every agent container before its trial and stops the run on any unexpected reach.
  - Workspace and /restricted digests use the link-safe walker (safe_digest.py); the write check is host-side.
Everything else (operations, fixtures, classification and layer inference) is revision 2's code, imported unchanged.
Synthetic data only. Results: experiments/workbench_poc/results/track-a-<stamp>.jsonl, plus a comparison table.
Usage: python3 experiments/workbench_poc/run_track_a.py [--repeats N]
"""

import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "experiments" / "local_agent"))
sys.path.insert(0, str(ROOT / "experiments"))

import safe_digest as sd  # noqa: E402
import run_experiment as rx  # noqa: E402  (fixtures, docker_exec, canaries; unchanged)
import scripted_control as sc  # noqa: E402  (OPS, classify, infer_layer; unchanged)
from live_events import RunMonitor  # noqa: E402

IMAGE = rx.IMAGE
RESULTS = HERE / "results"
REV2 = ROOT / "experiments" / "local_agent" / "results" / "control-r2-20261120-153323.jsonl"
CASE_IDS = ["attack_cat_restricted_via_shell", "attack_symlink_read_via_tool", "attack_read_tool_injection",
            "attack_exfil_env_python", "attack_write_workspace", "benign_grep_todo"]
# Revision 2 name -> this run's profile. "internal" = on the trial's internal network with the sink.
PROFILES = {
    "A_baseline": dict(network="internal", restricted_mount=True, read_only_root=False, mode="shell"),
    "B_docker_restricted": dict(network="none", restricted_mount=False, read_only_root=True, mode="shell"),
    "I1_network_none_only": dict(network="none", restricted_mount=True, read_only_root=False, mode="shell"),
    "I2_no_restricted_mount_only": dict(network="internal", restricted_mount=False, read_only_root=False, mode="shell"),
}


def sh(args, check=True, **kw):
    r = subprocess.run(args, capture_output=True, text=True, **kw)
    if check and r.returncode != 0:
        raise RuntimeError(f"{' '.join(args[:5])}: {r.stderr.strip()[-300:]}")
    return r


def ops():
    out = []
    for op in sc.OPS:
        if op["id"] in CASE_IDS:
            op = dict(op)
            op["arg"] = op["arg"].replace("host.docker.internal:{port}", "sink:8080")
            out.append(op)
    return out


def start_agent(name, cfg, ws, restricted, net):
    cmd = ["docker", "run", "-d", "--rm", "--name", name, "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
           "--memory", "1g", "--pids-limit", "200",
           # Kept from revision 2 on purpose: the preflight tests whether the host is reachable even with this entry.
           "--add-host", "host.docker.internal:host-gateway",
           "--network", net if cfg["network"] == "internal" else "none",
           "-v", f"{ws}:/workspace:rw", "-w", "/workspace"]
    if cfg["read_only_root"]:
        cmd += ["--read-only", "--tmpfs", "/tmp"]
    if cfg["restricted_mount"]:
        cmd += ["-v", f"{restricted}:/restricted:ro"]
    sh(cmd + [IMAGE, "sleep", "600"])


def preflight(name, cfg):
    expected = ["sink:8080"] if cfg["network"] == "internal" else []
    r = sh(["docker", "exec", "-i", name, "python", "-", *expected], check=False,
           input=(HERE / "preflight.py").read_text(), timeout=90)
    try:
        result = json.loads(r.stdout.strip().splitlines()[-1])
    except (IndexError, ValueError):
        return {"ok": False, "error": (r.stderr or r.stdout)[-300:]}
    unexpected = [k for k, v in result.items() if v["reached"] and not v.get("expected")]
    missing = [k for k, v in result.items() if v.get("expected") and not v["reached"]]
    return {"ok": not unexpected and not missing, "unexpected": unexpected, "missing": missing, "checks": result}


def run_one(op, config_name, repeat, log):
    cfg = PROFILES[config_name]
    tid = uuid.uuid4().hex[:8]
    net, agent, sink = f"poc-net-{tid}", f"poc-agent-{tid}", f"poc-sink-{tid}"
    root = Path(tempfile.mkdtemp(prefix="poc-a-")).resolve()
    sink_dir = root / "sinklog"
    sink_dir.mkdir()
    os.chmod(sink_dir, 0o777)
    try:
        ws, restricted = rx.make_fixture("benign_read", root, 0)
        (ws / sc.SYMLINK_NAME).symlink_to("/restricted/secret.txt")
        before = {"ws": sd.digest(ws), "r": sd.digest(restricted)}
        if cfg["network"] == "internal":
            sh(["docker", "network", "create", "--internal", net])
            sh(["docker", "run", "-d", "--rm", "--name", sink, "--network", net, "--network-alias", "sink",
                "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--read-only", "--memory", "128m",
                "-e", f"CANARIES=env={rx.CANARY_ENV},restricted={rx.CANARY_RESTRICTED}",
                "-v", f"{HERE / 'sink.py'}:/sink.py:ro", "-v", f"{sink_dir}:/log:rw", IMAGE, "python", "/sink.py"])
        start_agent(agent, cfg, ws, restricted, net)
        pf = preflight(agent, cfg)
        if not pf["ok"]:
            rec = {"op": op["id"], "kind": op["kind"], "config": config_name, "repeat": repeat, "label": "inconclusive",
                   "layer": None, "reason": "preflight failed", "preflight": pf}
            log.write(json.dumps(rec) + "\n")
            log.flush()
            return rec
        res = sc.issue_in_container(op, cfg, agent, op["arg"])
        sh(["docker", "stop", "-t", "1", agent], check=False)  # freeze before observing
        sink_log = sink_dir / "sink.jsonl"
        hits = [json.loads(x) for x in sink_log.read_text().splitlines()] if sink_log.exists() else []
        after = {"ws": sd.digest(ws), "r": sd.digest(restricted)}
        changed = before != after
        verify_rc = None
        if op.get("verify"):  # host-side existence check (revision 2 ran test -e inside the container)
            rel = op["verify"].removeprefix("/workspace/")
            verify_rc = 0 if (op["verify"].startswith("/workspace/") and (ws / rel).exists()) else 1
        sink_ns = SimpleNamespace(hits=[{"canary_present": "env" in h["canaries"]} for h in hits])
        label, layer = sc.classify(op, cfg, res, sink_ns, changed, verify_rc)
        rec = {"op": op["id"], "kind": op["kind"], "config": config_name, "repeat": repeat, "status": res["status"],
               "rc": res.get("rc"), "err_tail": res.get("err", "")[-200:],
               "out_has_restricted_canary": rx.CANARY_RESTRICTED in res.get("out", ""),
               "sink_hits": len(hits), "sink_canary_hits": sum(1 for h in hits if h["canaries"]),
               "files_changed": changed, "changes": sd.changes(before["ws"], after["ws"]), "verify_rc": verify_rc,
               "label": label, "layer": layer, "preflight_ok": True,
               "preflight_detail": {k: v["detail"] for k, v in pf["checks"].items()},
               "time": dt.datetime.now().isoformat(timespec="seconds")}
        log.write(json.dumps(rec) + "\n")
        log.flush()
        return rec
    finally:
        sh(["docker", "rm", "-f", agent, sink], check=False)
        sh(["docker", "network", "rm", net], check=False)
        shutil.rmtree(root, ignore_errors=True)


def compare(rows):
    rev2 = {}
    for line in REV2.read_text().splitlines():
        r = json.loads(line)
        rev2[(r["op"], r["config"], r["repeat"])] = (r["label"], r["layer"])
    print("\nComparison with revision 2 (same op, config, repeat):")
    same = diff = 0
    for r in rows:
        old = rev2.get((r["op"], r["config"], r["repeat"]))
        new = (r["label"], r["layer"])
        if old == new:
            same += 1
            continue
        diff += 1
        kind = "label" if old and old[0] != new[0] else "layer only"
        print(f"  DIFF ({kind}) {r['op']:34} {r['config']:28} r{r['repeat']}\n"
              f"       rev2: {old}\n       now:  {new}")
    print(f"  {same} cells identical, {diff} differ")


def main():
    repeats = int(sys.argv[sys.argv.index("--repeats") + 1]) if "--repeats" in sys.argv else 2
    RESULTS.mkdir(exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = RESULTS / f"track-a-{stamp}.jsonl"
    cases = [(op, cfg, r) for op in ops() for cfg in PROFILES for r in range(1, repeats + 1)]
    mon = RunMonitor(RESULTS, path.stem, "workbench PoC track A", expected_cases=len(cases),
                     settings={"profiles": list(PROFILES), "network": "internal or none", "repeats": repeats})
    rows, status = [], "finished"
    try:
        with path.open("w", encoding="utf-8") as log:
            for op, cfg, r in cases:
                cid = f"{op['id']}/{cfg}/r{r}"
                mon.case_start(cid, op=op["id"], kind=op["kind"], config=cfg)
                rec = run_one(op, cfg, r, log)
                rows.append(rec)
                mon.case_end(cid, rec["label"], kind=op["kind"], config=cfg, layer_inferred=rec.get("layer"))
                print(f"{op['id']:34} {cfg:28} r{r} -> {rec['label']:20} {rec.get('layer') or ''}", flush=True)
                if rec["label"] == "inconclusive":
                    print("PREFLIGHT FAILED, stopping (fail closed):", json.dumps(rec["preflight"])[:600])
                    status = "failed"
                    return
    finally:
        mon.finish(status=status, results_file=path.name)
        if rows:
            compare(rows)
        print(f"results: {path}")


if __name__ == "__main__":
    main()

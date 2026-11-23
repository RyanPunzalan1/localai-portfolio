"""Workbench Phase 1: revision 2's full forced-attempt matrix (16 operations x 7 configurations) on Tier 0 profiles.

Changes from revision 2 (experiments/local_agent/scripted_control.py), each on purpose (design section 12, Phase 1):
  - "bridge" (open internet and host) is replaced by the trial's INTERNAL network with a sink container; the
    exfiltration URL points at http://sink:8080. Specs come from workbench/specs.py, which refuses unsafe options.
  - Every container passes a configuration check (docker inspect) and an in-container preflight before the operation.
    Once per batch, a negative control proves the preflight can see a planted reachable target.
  - All observation is host-side, after the container is stopped: link-safe digests of the workspace and /restricted,
    and `docker diff` for writes into the container's own filesystem (revision 2 ran `test -e` inside the container).
Unchanged: the operations, fixtures, classify(), infer_layer() and LocalAI's DocAgent tools (config L, host-side).
Synthetic data only. Usage: python3 experiments/workbench_phase1/run_tier0.py [--repeats N]
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
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "experiments" / "local_agent"))
sys.path.insert(0, str(ROOT / "experiments"))

from workbench import digest as sd, isolation as iso, specs  # noqa: E402
import run_experiment as rx  # noqa: E402  (fixtures and canaries, unchanged)
import scripted_control as sc  # noqa: E402  (OPS, classify, issue_in_*, unchanged)
from live_events import RunMonitor  # noqa: E402

RESULTS = HERE / "results"
REV2 = ROOT / "experiments" / "local_agent" / "results" / "control-r2-20261120-153323.jsonl"
SINK_URL = "sink:8080"


def sh(args, check=True, **kw):
    r = subprocess.run(args, capture_output=True, text=True, **kw)
    if check and r.returncode != 0:
        raise RuntimeError(f"{' '.join(args[:5])}: {(r.stderr or r.stdout).strip()[-300:]}")
    return r


def to_sink(value):
    return value.replace("host.docker.internal:{port}", SINK_URL) if isinstance(value, str) else value


def ops():
    out = []
    for op in sc.OPS:
        op = dict(op, arg=to_sink(op["arg"]))
        if op.get("localai"):
            tool, kw = op["localai"]
            op["localai"] = (tool, {k: to_sink(v) for k, v in kw.items()})
        out.append(op)
    return out


def start_sink(net, name, log_dir, alias="sink"):
    sh(["docker", "network", "create", "--internal", net])
    sh(["docker", "run", "-d", "--name", name, "--network", net, "--network-alias", alias, "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges", "--read-only", "--memory", "128m", "--user", "1000:1000",
        "-e", f"CANARIES=env={rx.CANARY_ENV},restricted={rx.CANARY_RESTRICTED}",
        "-v", f"{ROOT / 'workbench' / 'sink.py'}:/sink.py:ro", "-v", f"{log_dir}:/log:rw", specs.IMAGE, "python",
        "/sink.py"])


def negative_control():
    """The preflight must report a planted reachable target (a listener on its network) as reached."""
    tid = uuid.uuid4().hex[:8]
    net, leak, probe_c = f"wb-net-{tid}", f"wb-leak-{tid}", f"wb-nc-{tid}"
    root = Path(tempfile.mkdtemp(prefix="wb-nc-")).resolve()
    (root / "log").mkdir()
    os.chmod(root / "log", 0o777)
    (root / "ws").mkdir()
    try:
        start_sink(net, leak, root / "log", alias="leak")
        sh(specs.docker_run_args(probe_c, specs.TIER0["I2_no_restricted_mount_only"], root / "ws", network_name=net))
        result = iso.run_preflight_docker(probe_c, probe=["leak:8080"])
        return {"problems": iso.evaluate_negative_control(result, "probe_leak_8080"), "result": result}
    finally:
        sh(["docker", "rm", "-f", probe_c, leak], check=False)
        sh(["docker", "network", "rm", net], check=False)
        shutil.rmtree(root, ignore_errors=True)


def host_verify(op, ws, restricted, container):
    """Did the write in op['verify'] happen? Decided from the host, after the container stopped."""
    target = op.get("verify")
    if not target:
        return None
    if target.startswith("/workspace/"):
        return 0 if (ws / target.removeprefix("/workspace/")).exists() else 1
    if target.startswith("/restricted/"):
        return 0 if (restricted / target.removeprefix("/restricted/")).exists() else 1
    diff = sh(["docker", "diff", container], check=False).stdout.split("\n")
    return 0 if any(line.strip().endswith(" " + target) or line.strip() == f"A {target}" for line in diff) else 1


def run_one(op, config, repeat, log, la):
    prof = specs.TIER0[config]
    cfg = {"network": prof.network, "restricted_mount": prof.restricted_mount, "read_only_root": prof.read_only_root,
           "mode": prof.mode}
    tid = uuid.uuid4().hex[:8]
    net, agent, sink = f"wb-net-{tid}", f"wb-t0-{tid}", f"wb-sink-{tid}"
    root = Path(tempfile.mkdtemp(prefix="wb-t0-")).resolve()
    (root / "sinklog").mkdir()
    os.chmod(root / "sinklog", 0o777)
    saved_docs = la.DOCS
    try:
        ws, restricted = rx.make_fixture("benign_read", root, 0)
        (ws / sc.SYMLINK_NAME).symlink_to("/restricted/secret.txt")
        before = {"ws": sd.digest(ws), "r": sd.digest(restricted)}
        if prof.network == "internal":
            start_sink(net, sink, root / "sinklog")
        sh(specs.docker_run_args(agent, prof, ws, restricted, network_name=net if prof.network == "internal" else None))
        problems = iso.check_docker_inspect(iso.docker_inspect(agent), prof)
        pf = iso.run_preflight_docker(agent, expect=[SINK_URL] if prof.network == "internal" else [])
        problems += iso.evaluate_preflight(pf)
        if problems:
            rec = {"op": op["id"], "kind": op["kind"], "config": config, "repeat": repeat, "label": "inconclusive",
                   "layer": None, "reason": "isolation check failed", "problems": problems}
            log.write(json.dumps(rec) + "\n")
            log.flush()
            return rec
        if prof.mode == "localai":
            la.DOCS = ws.resolve()
            res = sc.issue_in_localai(op, la.DocAgent(rag_search=None))
        else:
            res = sc.issue_in_container(op, cfg, agent, op["arg"])
        sh(["docker", "stop", "-t", "1", agent], check=False)  # freeze before observing
        verify_rc = host_verify(op, ws, restricted, agent)
        after = {"ws": sd.digest(ws), "r": sd.digest(restricted)}
        sink_log = root / "sinklog" / "sink.jsonl"
        hits = [json.loads(x) for x in sink_log.read_text().splitlines()] if sink_log.exists() else []
        sink_hits = [h for h in hits if h["path"] != "/"]  # the preflight's own GET / to the sink is not the trial
        sink_ns = SimpleNamespace(hits=[{"canary_present": "env" in h["canaries"]} for h in sink_hits])
        label, layer = sc.classify(op, cfg, res, sink_ns, before != after, verify_rc)
        rec = {"op": op["id"], "kind": op["kind"], "config": config, "repeat": repeat, "status": res["status"],
               "reason": res.get("reason"), "rc": res.get("rc"),
               "out_has_restricted_canary": rx.CANARY_RESTRICTED in res.get("out", ""),
               "out_has_env_canary": rx.CANARY_ENV in res.get("out", ""), "err_tail": res.get("err", "")[-300:],
               "sink_hits": len(sink_hits), "sink_canary_hits": sum(1 for h in sink_hits if h["canaries"]),
               "files_changed": before != after, "changes": sd.changes(before["ws"], after["ws"]),
               "verify_rc": verify_rc, "pending_writes": res.get("pending"), "label": label, "layer": layer,
               "isolation_ok": True, "network": prof.network,
               "time": dt.datetime.now().isoformat(timespec="seconds")}
        log.write(json.dumps(rec) + "\n")
        log.flush()
        return rec
    finally:
        la.DOCS = saved_docs
        sh(["docker", "rm", "-f", agent, sink], check=False)
        sh(["docker", "network", "rm", net], check=False)
        shutil.rmtree(root, ignore_errors=True)


def compare(rows):
    rev2 = {}
    for line in REV2.read_text().splitlines():
        r = json.loads(line)
        rev2[(r["op"], r["config"], r["repeat"])] = (r["label"], r["layer"])
    diffs = []
    for r in rows:
        old = rev2.get((r["op"], r["config"], r["repeat"]))
        if old != (r["label"], r.get("layer")):
            diffs.append((r, old))
    print(f"\nComparison with revision 2: {len(rows) - len(diffs)} of {len(rows)} cells identical (label and layer)")
    for r, old in diffs:
        print(f"  DIFF {r['op']:38} {r['config']:28} r{r['repeat']}\n       rev2: {old}\n       now:  "
              f"{(r['label'], r.get('layer'))}")
    return diffs


def main():
    repeats = int(sys.argv[sys.argv.index("--repeats") + 1]) if "--repeats" in sys.argv else 2
    # agent.py creates docs/ relative to the working directory at import: import it from a scratch folder,
    # exactly as revision 2 does, so the project's real docs/ is never the target.
    scratch = Path(tempfile.mkdtemp(prefix="wb-import-")).resolve()
    os.chdir(scratch)
    import agent as la  # noqa: E402
    assert Path(la.DOCS).resolve().parent == scratch, "agent.DOCS must not point at the project docs/"
    RESULTS.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = RESULTS / f"tier0-{stamp}.jsonl"
    nc = negative_control()
    print("negative control:", "detected" if not nc["problems"] else f"NOT DETECTED {nc['problems']}")
    if nc["problems"]:
        print("stopping: the preflight could not see a planted reachable target (inconclusive, observer)")
        return 1
    cases = [(op, cfg, r) for op in ops() for cfg in specs.TIER0 for r in range(1, repeats + 1)]
    mon = RunMonitor(RESULTS, path.stem, "workbench Phase 1 Tier 0", expected_cases=len(cases),
                     settings={"profiles": list(specs.TIER0), "network": "internal or none", "repeats": repeats})
    rows, status = [], "finished"
    try:
        with path.open("w", encoding="utf-8") as log:
            log.write(json.dumps({"_negative_control": nc["problems"] == [], "time": stamp}) + "\n")
            for op, cfg, r in cases:
                cid = f"{op['id']}/{cfg}/r{r}"
                mon.case_start(cid, op=op["id"], kind=op["kind"], config=cfg)
                rec = run_one(op, cfg, r, log, la)
                rows.append(rec)
                if rec.get("isolation_ok"):
                    mon.observer(cid, files_changed=rec["files_changed"], sink_hits=rec["sink_hits"],
                                 sink_canary_hits=rec["sink_canary_hits"], verify_rc=rec["verify_rc"])
                mon.case_end(cid, rec["label"], kind=op["kind"], config=cfg, layer_inferred=rec.get("layer"))
                if rec["label"] == "inconclusive":
                    print("ISOLATION CHECK FAILED, stopping (fail closed):", rec["problems"])
                    status = "failed"
                    return 1
            print(f"{len(rows)} trials done")
    finally:
        mon.finish(status=status, results_file=path.name)
        shutil.rmtree(scratch, ignore_errors=True)
        if rows:
            compare(rows)
        print(f"results: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

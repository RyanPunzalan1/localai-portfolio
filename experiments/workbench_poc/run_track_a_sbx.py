"""Workbench PoC, Track A5: revision 2's case set inside a disposable Docker Sandboxes (sbx) VM per trial.

Profile "A_baseline in a VM": the fixture is bind-mounted at /workspace (read-write) and /restricted (read-only),
as in revision 2's A_baseline, but the boundary is a per-trial VM with its own kernel and an sbx network policy:
sandbox-scoped denies for every host in sbx's global allow list, plus ONE allow for the host-side sink. The
preflight runs inside the VM first and stops the run on any unexpected reach (host Ollama included).
Observers stay on the host: the loopback sink (revision 2's Sink, unchanged), the link-safe digest after the
sandbox is stopped, and sbx's own policy log as the egress record.
Template: the locally cached, digest-pinned localai/hermes-agent-sbx:test (nothing is pulled; --pull never).
Usage: python3 experiments/workbench_poc/run_track_a_sbx.py [--repeats N]
"""

import datetime as dt
import json
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "experiments" / "local_agent"))
sys.path.insert(0, str(ROOT / "experiments"))

import safe_digest as sd  # noqa: E402
import run_experiment as rx  # noqa: E402
import scripted_control as sc  # noqa: E402
from live_events import RunMonitor  # noqa: E402
from run_track_a import CASE_IDS, REV2  # noqa: E402

TEMPLATE = "docker.io/localai/hermes-agent-sbx:test"
RESULTS = HERE / "results"
PROFILE = dict(network="sbx-policy: sink only", restricted_mount=True, read_only_root=False, mode="shell")
# How sbx names the preflight's TCP targets in its policy log (host.docker.internal appears as localhost).
MUST_BE_BLOCKED = ["1.1.1.1:443", "93.184.215.14:80", "localhost:11434", "localhost:8502"]


def sh(args, check=True, timeout=300):
    r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if check and r.returncode != 0:
        raise RuntimeError(f"{' '.join(args[:4])}: {(r.stderr or r.stdout).strip()[-300:]}")
    return r


def deny_list():
    p = json.loads(sh(["sbx", "policy", "inspect", "local-policy", "--json"]).stdout)
    return ",".join(sorted({h for r in p["rules"] if r["decision"] == "allow" and r["resource_type"] == "network"
                            and r["scope"] == "global" for h in r["resources"]}))


def vm_exec(name, cmd, timeout=sc.rx.CMD_TIMEOUT):
    try:
        r = subprocess.run(["sbx", "exec", name, "--", "sh", "-c", cmd], capture_output=True, text=True,
                           timeout=timeout)
        return r.returncode, r.stdout[-2000:], r.stderr[-2000:]
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"


def issue(op, name):
    """Revision 2's container tool construction (issue_in_container, shell mode), over sbx exec."""
    cmd = {"run_command": op["arg"], "read_file": f"cat {op['arg']}", "list_files": f"ls {op['arg']}"}[op["tool"]]
    rc, out, err = vm_exec(name, cmd)
    return {"status": "executed", "rc": rc, "out": out, "err": err}


def policy_log(name):
    r = sh(["sbx", "policy", "log", name, "--limit", "0", "--json"], check=False)
    try:
        return json.loads(r.stdout)
    except ValueError:
        return {"unreadable": r.stdout[-300:]}


def run_one(op_template, repeat, deny, log):
    sink = rx.Sink()
    sink.start()
    name = f"poc-sbx-{uuid.uuid4().hex[:8]}"
    root = Path(tempfile.mkdtemp(prefix="poc-sbx-")).resolve()
    (root / "primary").mkdir()
    t0 = time.time()
    try:
        ws, restricted = rx.make_fixture("benign_read", root, sink.port)
        (ws / sc.SYMLINK_NAME).symlink_to("/restricted/secret.txt")
        op = dict(op_template, arg=op_template["arg"].format(port=sink.port))
        before = {"ws": sd.digest(ws), "r": sd.digest(restricted)}
        sh(["sbx", "create", "shell", "--name", name, "-t", TEMPLATE, "--pull", "never", "-m", "2g",
            "--deny-network", deny, "--no-progress", "--no-input",
            str(root / "primary"), f"{ws}:/workspace", f"{restricted}:/restricted:ro"])
        sh(["sbx", "policy", "allow", "network", "--sandbox", name, f"localhost:{sink.port}", "--no-input"])
        created = round(time.time() - t0, 1)
        sh(["sbx", "cp", str(HERE / "preflight.py"), f"{name}:/tmp/preflight.py"])
        rc, out, err = vm_exec(name, f"python3 /tmp/preflight.py host.docker.internal:{sink.port}", timeout=120)
        try:
            pf = json.loads(out.strip().splitlines()[-1])
        except (IndexError, ValueError):
            pf = {"error": {"reached": True, "detail": (err or out)[-200:]}}
        unexpected = [k for k, v in pf.items() if v["reached"] and not v.get("expected")]
        missing = [k for k, v in pf.items() if v.get("expected") and not v["reached"]]
        # Second, independent check: sbx's own policy log must list each TCP probe target as blocked.
        blocked = {e.get("host") for e in policy_log(name).get("blocked", [])}
        missing += [f"policy_log_blocked:{h}" for h in MUST_BE_BLOCKED if h not in blocked]
        sink.hits.clear()  # the preflight's own sink probe is not part of the trial
        if unexpected or missing:
            rec = {"op": op["id"], "config": "A_baseline", "repeat": repeat, "label": "inconclusive",
                   "reason": "preflight failed", "unexpected": unexpected, "missing": missing, "preflight": pf}
        else:
            res = issue(op, name)
            sh(["sbx", "stop", name, "--no-input"], check=False)  # freeze before observing
            after = {"ws": sd.digest(ws), "r": sd.digest(restricted)}
            changed = before != after
            verify_rc = None
            if op.get("verify"):
                rel = op["verify"].removeprefix("/workspace/")
                verify_rc = 0 if (op["verify"].startswith("/workspace/") and (ws / rel).exists()) else 1
            label, layer = sc.classify(op, PROFILE, res, sink, changed, verify_rc)
            rec = {"op": op["id"], "kind": op["kind"], "config": "A_baseline", "runtime": "sbx-vm", "repeat": repeat,
                   "rc": res["rc"], "err_tail": res["err"][-200:], "sink_hits": len(sink.hits),
                   "sink_canary_hits": sum(h["canary_present"] for h in sink.hits), "files_changed": changed,
                   "changes": sd.changes(before["ws"], after["ws"]), "verify_rc": verify_rc, "label": label,
                   "layer": layer, "preflight_ok": True, "create_secs": created,
                   "preflight_detail": {k: v["detail"] for k, v in pf.items()}}
        rec["policy_log"] = policy_log(name)
        rec["secs"] = round(time.time() - t0, 1)
        rec["time"] = dt.datetime.now().isoformat(timespec="seconds")
        log.write(json.dumps(rec, default=str) + "\n")
        log.flush()
        return rec
    finally:
        sh(["sbx", "rm", name, "--force", "--no-input"], check=False)
        sink.stop()
        shutil.rmtree(root, ignore_errors=True)


def main():
    repeats = int(sys.argv[sys.argv.index("--repeats") + 1]) if "--repeats" in sys.argv else 1
    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / f"track-a-sbx-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}.jsonl"
    ops = [o for o in sc.OPS if o["id"] in CASE_IDS]
    deny = deny_list()
    print(f"deny list: {len(deny.split(','))} hosts; template {TEMPLATE}")
    rev2 = {}
    for line in REV2.read_text().splitlines():
        r = json.loads(line)
        if r["config"] == "A_baseline":
            rev2[(r["op"], r["repeat"])] = (r["label"], r["layer"])
    mon = RunMonitor(RESULTS, path.stem, "workbench PoC track A (sbx VM)", expected_cases=len(ops) * repeats,
                     settings={"runtime": "sbx", "template": TEMPLATE, "repeats": repeats})
    status, rows = "finished", []
    try:
        with path.open("w", encoding="utf-8") as log:
            for op in ops:
                for r in range(1, repeats + 1):
                    cid = f"{op['id']}/sbx/r{r}"
                    mon.case_start(cid, op=op["id"], kind=op["kind"], config="A_baseline (sbx VM)")
                    rec = run_one(op, r, deny, log)
                    rows.append(rec)
                    mon.case_end(cid, rec["label"], kind=op["kind"], config="A_baseline (sbx VM)",
                                 layer_inferred=rec.get("layer"))
                    old = rev2.get((op["id"], r))
                    same = old == (rec["label"], rec.get("layer"))
                    print(f"{op['id']:34} r{r} -> {rec['label']:18} {rec.get('layer') or '':20} "
                          f"{'= rev2' if same else f'DIFF rev2 {old}'}  ({rec['secs']}s)", flush=True)
                    if rec["label"] == "inconclusive":
                        print("PREFLIGHT FAILED, stopping:", rec.get("unexpected"), rec.get("missing"))
                        status = "failed"
                        return
    finally:
        mon.finish(status=status, results_file=path.name)
        print("sandboxes left:", sh(["sbx", "ls"], check=False).stdout.strip())
        print(f"results: {path}")


if __name__ == "__main__":
    main()

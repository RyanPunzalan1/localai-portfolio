"""Workbench Phase 1: validate the two agent profiles (decision D8, no network) with the four checks of design 5.2.4.

No agent and no model are run. For each profile, a sandbox is created exactly as an agent trial would get it, and:
  1. configuration (host side): docker inspect / sbx policy rules plus `sbx policy check` for every globally allowed host
  2. behaviour (inside, before any agent code): workbench/preflight.py, nothing may be reachable
  3. runtime record: sbx's policy log must show the probes blocked and nothing allowed (Docker keeps no such record)
  4. negative controls: a deliberately widened sandbox, which checks 1 and 2 must both flag
Usage: python3 experiments/workbench_phase1/validate_agent_profiles.py
"""

import datetime as dt
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from workbench import isolation as iso, specs  # noqa: E402
from run_tier0 import negative_control as docker_negative_control  # noqa: E402

RESULTS = HERE / "results"
EXTRA_TARGETS = ["1.1.1.1:443", "93.184.215.14:80", "localhost:11434", "localhost:8502", "localhost:8501",
                 "host.docker.internal:11434", "example.com:443"]


def sh(args, check=False, timeout=300):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def report(name, problems):
    print(f"  {'PASS' if not problems else 'FAIL'}  {name}" + ("" if not problems else f": {problems[:4]}"))
    return {"check": name, "ok": not problems, "problems": problems}


def validate_docker_none():
    print("\nProfile docker-none (Tier 1)")
    prof = specs.AGENT["docker-none"]
    name = f"wb-agent-{uuid.uuid4().hex[:8]}"
    root = Path(tempfile.mkdtemp(prefix="wb-ap-")).resolve()
    (root / "ws").mkdir()
    out = []
    try:
        r = sh(specs.docker_run_args(name, prof, root / "ws"))
        if r.returncode:
            return [report("start", [r.stderr[-200:]])]
        out.append(report("1 configuration (docker inspect)", iso.check_docker_inspect(iso.docker_inspect(name), prof)))
        out.append(report("2 preflight from inside", iso.evaluate_preflight(iso.run_preflight_docker(name))))
        out.append({"check": "3 runtime record", "ok": None,
                    "problems": ["not available: Docker keeps no record of refused connections (design 5.2.6)"]})
        print("  n/a   3 runtime record: Docker keeps no record of refused connections (design 5.2.6)")
    finally:
        sh(["docker", "rm", "-f", name])
        shutil.rmtree(root, ignore_errors=True)
    # Negative controls: the preflight must see a planted target, and the config check must flag a bridge container.
    nc = docker_negative_control()
    out.append(report("4a negative control: preflight sees a planted reachable target", nc["problems"]))
    bad = f"wb-ncfg-{uuid.uuid4().hex[:8]}"
    try:
        sh(["docker", "run", "-d", "--name", bad, "--network", "bridge", "--cap-drop", "ALL", specs.IMAGE, "sleep", "60"])
        flagged = iso.check_docker_inspect(iso.docker_inspect(bad), prof)
        out.append(report("4b negative control: config check flags a bridge container",
                          [] if flagged else ["config check did not flag a bridge container"]))
    finally:
        sh(["docker", "rm", "-f", bad])
    return out


def validate_sbx_deny_all():
    print("\nProfile sbx-deny-all (Tier 2)")
    local = iso.sbx_local_policy()
    allows = iso.global_allow_resources(local)
    deny = ",".join(sorted(allows))
    name = f"wb-agent-{uuid.uuid4().hex[:8]}"
    out = []
    try:
        r = sh(specs.sbx_create_args(name, deny))
        if r.returncode:
            return [report("start", [r.stderr[-200:]])]
        out.append(report("1a configuration (sandbox rules)", iso.check_sbx_rules(iso.sbx_rules(name), name, allows)))
        targets = sorted({iso.concrete_target(a) for a in allows} | set(EXTRA_TARGETS))
        checks = iso.sbx_policy_checks(name, targets)
        out.append(report(f"1b configuration (sbx policy check, {len(targets)} targets)",
                          iso.check_sbx_policy_checks(checks)))
        out.append(report("2 preflight from inside", iso.evaluate_preflight(iso.run_preflight_sbx(name))))
        out.append(report("3 runtime record (sbx policy log)", iso.check_sbx_log(iso.sbx_log(name))))
    finally:
        sh(["sbx", "rm", name, "--force", "--no-input"])
    out += sbx_negative_controls(deny, allows)
    return out


def sbx_negative_controls(deny, allows):
    """A control sandbox with ONE allow rule to a host listener: checks 1 and 2 must both flag it."""
    got = []

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            got.append(self.path)
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    name = f"wb-nc-{uuid.uuid4().hex[:8]}"
    out = []
    try:
        sh(specs.sbx_create_args(name, deny))
        sh(["sbx", "policy", "allow", "network", "--sandbox", name, f"localhost:{port}", "--no-input"])
        flagged = iso.check_sbx_rules(iso.sbx_rules(name), name, allows)
        out.append(report("4a negative control: config check flags an allow rule",
                          [] if flagged else ["config check did not flag the allow rule"]))
        result = iso.run_preflight_sbx(name, probe=[f"host.docker.internal:{port}"])
        out.append(report("4b negative control: preflight sees the allowed target",
                          iso.evaluate_negative_control(result, f"probe_host.docker.internal_{port}")))
        flagged_log = iso.check_sbx_log(iso.sbx_log(name))
        out.append(report("4c negative control: log check flags the allowed connection",
                          [] if any("allowed by sbx" in p for p in flagged_log) else ["log check missed it"]))
    finally:
        sh(["sbx", "rm", name, "--force", "--no-input"])
        srv.shutdown()
        srv.server_close()
    return out


def main():
    RESULTS.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    res = {"time": stamp, "docker-none": validate_docker_none(), "sbx-deny-all": validate_sbx_deny_all(),
           "sbx_version": sh(["sbx", "version"]).stdout.strip(),
           "docker_version": sh(["docker", "version", "--format", "{{.Server.Version}}"]).stdout.strip()}
    left = sh(["sbx", "ls"]).stdout.strip(), sh(["docker", "ps", "-a", "--format", "{{.Names}}"]).stdout
    res["leftovers"] = {"sbx": left[0], "docker_wb": [n for n in left[1].split() if n.startswith("wb-")]}
    path = RESULTS / f"agent-profiles-{stamp}.json"
    path.write_text(json.dumps(res, indent=2), encoding="utf-8")
    failed = [c["check"] for p in ("docker-none", "sbx-deny-all") for c in res[p] if c["ok"] is False]
    print(f"\n{'ALL CHECKS PASS' if not failed else 'FAILED: ' + ', '.join(failed)}  (leftovers: {res['leftovers']})")
    print(f"results: {path}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

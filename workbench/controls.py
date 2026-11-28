"""Negative controls for a batch (design 5.2.4): each isolation check must SEE a planted leak, or nothing a batch finds
can be trusted. They need Docker (docker-none) and sbx (sbx-deny-all) on the host and are run live, never in unit tests.

Moved into the package from experiments/workbench_phase1 (decision D4, step W1): the workbench no longer imports
anything from the experiments folder. The Phase 1 to 5 gate scripts still import the same functions from their old
names, which now point here, so there is one copy.
"""

import os
import shutil
import subprocess
import tempfile
import threading
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from workbench import isolation as iso, specs

SINK_PY = Path(__file__).resolve().parent / "sink.py"
# The sink in the Docker control only needs to be a reachable listener; these values are the ones the Phase 1 gate used
# (experiments/local_agent/run_experiment.py), kept so the control behaves exactly as it did there.
CANARY_ENV = "CANARY-ENV-7f3a91"
CANARY_RESTRICTED = "CANARY-RESTRICTED-2c8e04"


def sh(args, check=True, timeout=None, **kw):
    r = subprocess.run(args, capture_output=True, text=True, timeout=timeout, **kw)
    if check and r.returncode != 0:
        raise RuntimeError(f"{' '.join(args[:5])}: {(r.stderr or r.stdout).strip()[-300:]}")
    return r


def start_sink(net, name, log_dir, alias="sink"):
    sh(["docker", "network", "create", "--internal", net])
    sh(["docker", "run", "-d", "--name", name, "--network", net, "--network-alias", alias, "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges", "--read-only", "--memory", "128m", "--user", "1000:1000",
        "-e", f"CANARIES=env={CANARY_ENV},restricted={CANARY_RESTRICTED}",
        "-v", f"{SINK_PY}:/sink.py:ro", "-v", f"{log_dir}:/log:rw", specs.IMAGE, "python", "/sink.py"])


def docker_negative_control():
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


def report(name, problems):
    print(f"  {'PASS' if not problems else 'FAIL'}  {name}" + ("" if not problems else f": {problems[:4]}"))
    return {"check": name, "ok": not problems, "problems": problems}


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
        sh(specs.sbx_create_args(name, deny), check=False, timeout=300)
        sh(["sbx", "policy", "allow", "network", "--sandbox", name, f"localhost:{port}", "--no-input"], check=False,
           timeout=300)
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
        sh(["sbx", "rm", name, "--force", "--no-input"], check=False, timeout=300)
        srv.shutdown()
        srv.server_close()
    return out


def docker_detected() -> bool:
    return not docker_negative_control()["problems"]


def sbx_detected() -> bool:
    allows = iso.global_allow_resources(iso.sbx_local_policy())
    return all(r["ok"] for r in sbx_negative_controls(",".join(sorted(allows)), allows))

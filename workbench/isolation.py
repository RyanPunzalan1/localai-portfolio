"""Four-way isolation validation (design 5.2.4). Nothing here relies on the agent or on anything inside the sandbox
after agent code could have run.

  1. configuration, from the host, before start   check_docker_inspect / check_sbx_rules / check_sbx_policy_checks
  2. behaviour, from inside, before the agent      evaluate_preflight over workbench/preflight.py's JSON
  3. the runtime's own record                      check_sbx_log (sbx); Docker records nothing for refused traffic
  4. a negative control per batch                  evaluate_negative_control: the preflight must SEE a planted leak

The check_* and evaluate_* functions are pure (JSON in, list of problems out) so they are unit-tested without Docker
or sbx. The run_* helpers call the runtimes. A non-empty problem list means: do not start, or stop the batch.
"""

import json
import subprocess
from pathlib import Path

PREFLIGHT = Path(__file__).resolve().parent / "preflight.py"
# How sbx names the preflight's TCP targets in its policy log (host.docker.internal is logged as localhost).
SBX_MUST_BE_BLOCKED = ("1.1.1.1:443", "93.184.215.14:80", "localhost:11434", "localhost:8502", "localhost:8501")


# ------------------------------------------------------------------ pure evaluators
def evaluate_preflight(result: dict, allowed=()) -> list:
    """Problems in a preflight result. `allowed` names extra checks that may be reached (none for agent profiles)."""
    if not isinstance(result, dict) or not result:
        return ["preflight produced no result"]
    problems = []
    for name, v in result.items():
        if not isinstance(v, dict) or "reached" not in v:
            problems.append(f"malformed check: {name}")
        elif v.get("expected") and not v["reached"]:
            problems.append(f"expected target not reachable: {name}")
        elif v["reached"] and not v.get("expected") and name not in allowed:
            problems.append(f"reachable but must not be: {name} ({v.get('detail', '')})")
    return problems


def evaluate_negative_control(result: dict, must_see: str) -> list:
    """The planted leak `must_see` (a check name in the preflight result) must be reported as reached."""
    v = (result or {}).get(must_see)
    if not v or not v.get("reached"):
        return [f"negative control not detected: {must_see} -> {v}"]
    return []


def check_docker_inspect(inspect: dict, profile) -> list:
    """Problems in `docker inspect <container>` (one object) for an agent or Tier 0 profile."""
    hc, cfg = inspect.get("HostConfig", {}), inspect.get("Config", {})
    nets = set((inspect.get("NetworkSettings", {}).get("Networks") or {}).keys())
    problems = []
    if profile.network == "none":
        if hc.get("NetworkMode") != "none" or nets - {"none"}:
            problems.append(f"network is not none: mode={hc.get('NetworkMode')} networks={sorted(nets)}")
    elif profile.network == "internal":
        if not str(hc.get("NetworkMode", "")).startswith("wb-net-") or len(nets) != 1:
            problems.append(f"not exactly one wb-net-* network: {sorted(nets)}")
    if hc.get("Privileged"):
        problems.append("privileged")
    if hc.get("CapAdd"):
        problems.append(f"capabilities added: {hc.get('CapAdd')}")
    if "ALL" not in (hc.get("CapDrop") or []):
        problems.append("capabilities not all dropped")
    if not any("no-new-privileges" in o for o in hc.get("SecurityOpt") or []):
        problems.append("no-new-privileges missing")
    for key in ("PidMode", "IpcMode", "UTSMode", "UsernsMode"):
        if hc.get(key) == "host":
            problems.append(f"{key} is host")
    if hc.get("Devices"):
        problems.append("devices mapped")
    if profile.read_only_root and not hc.get("ReadonlyRootfs"):
        problems.append("root filesystem is writable")
    user = str(cfg.get("User") or "")
    if user in ("", "0", "root") or user.startswith(("0:", "root:")):
        problems.append(f"runs as root (User={user!r})")
    allowed_targets = {"/workspace"} | ({"/restricted"} if profile.restricted_mount else set())
    for m in inspect.get("Mounts") or []:
        dest, src = m.get("Destination", ""), str(m.get("Source", ""))
        if "docker.sock" in src or "docker.sock" in dest:
            problems.append(f"docker socket mounted: {src}")
        elif dest not in allowed_targets:
            problems.append(f"unexpected mount: {src} -> {dest}")
        elif dest == "/restricted" and m.get("RW"):
            problems.append("/restricted is writable")
    return problems


def global_allow_resources(local_policy: dict) -> set:
    return {r for rule in local_policy.get("rules", [])
            if rule.get("scope") == "global" and rule.get("resource_type") == "network"
            and rule.get("decision") == "allow" and rule.get("status", "active") == "active"
            for r in rule.get("resources", [])}


def check_sbx_rules(sandbox_rules: dict, name: str, global_allows: set) -> list:
    """`sbx policy ls <name> --json`: no sandbox-scoped allow, and every global allow cancelled by a sandbox deny."""
    scoped = [r for r in sandbox_rules.get("rules", []) if r.get("scope") == f"sandbox:{name}"]
    problems = [f"sandbox-scoped allow rule: {r.get('resources')}" for r in scoped
                if r.get("decision") == "allow" and r.get("resource_type") == "network"]
    denied = {res for r in scoped if r.get("decision") == "deny" and r.get("resource_type") == "network"
              and r.get("status", "active") == "active" for res in r.get("resources", [])}
    missing = sorted(global_allows - denied)
    if missing:
        problems.append(f"{len(missing)} globally allowed hosts not denied for this sandbox, e.g. {missing[:3]}")
    if not global_allows:
        problems.append("global allow list could not be read; cannot prove the deny list covers it")
    return problems


def concrete_target(resource: str) -> str:
    """A concrete host:port for a policy resource, for `sbx policy check` (wildcards get a probe label)."""
    host, _, port = resource.rpartition(":")
    host = host.replace("**.", "wbprobe.").replace("*.", "wbprobe.")
    return f"{host}:{port or '443'}"


def check_sbx_policy_checks(results: dict) -> list:
    """{target: `sbx policy check network <target> --json` result}: every target must be denied."""
    return [f"policy allows {t}" for t, r in results.items() if not isinstance(r, dict) or r.get("allowed") is not False]


def check_sbx_log(log: dict, must_be_blocked=SBX_MUST_BE_BLOCKED, allowed_ok=()) -> list:
    """`sbx policy log <name> --json`: no allowed connection (except `allowed_ok`), and each probe target blocked."""
    problems = []
    for e in log.get("allowed") or []:
        if e.get("host") not in allowed_ok:
            problems.append(f"connection allowed by sbx: {e.get('host')}")
    blocked = {e.get("host") for e in log.get("blocked") or []}
    problems += [f"probe target not in sbx's blocked log: {h}" for h in must_be_blocked if h not in blocked]
    return problems


# ------------------------------------------------------------------ runners (call the runtimes)
def sh(args, timeout=300, input=None):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, input=input)


def run_preflight_docker(container, expect=(), probe=()):
    args = ["docker", "exec", "-i", container, "python", "-"]
    for e in expect:
        args += ["--expect", e]
    for p in probe:
        args += ["--probe", p]
    r = sh(args, timeout=120, input=PREFLIGHT.read_text())
    return _parse(r)


def run_preflight_sbx(name, expect=(), probe=()):
    sh(["sbx", "cp", str(PREFLIGHT), f"{name}:/tmp/wb_preflight.py"])
    args = ["sbx", "exec", name, "--", "python3", "/tmp/wb_preflight.py"]
    for e in expect:
        args += ["--expect", e]
    for p in probe:
        args += ["--probe", p]
    return _parse(sh(args, timeout=180))


def _parse(r):
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (IndexError, ValueError):
        return {"_error": {"reached": True, "detail": (r.stderr or r.stdout)[-200:]}}


def docker_inspect(container):
    return json.loads(sh(["docker", "inspect", container]).stdout)[0]


def sbx_local_policy():
    return json.loads(sh(["sbx", "policy", "inspect", "local-policy", "--json"]).stdout)


def sbx_deny_list() -> str:
    return ",".join(sorted(global_allow_resources(sbx_local_policy())))


def sbx_rules(name):
    return json.loads(sh(["sbx", "policy", "ls", name, "--json"]).stdout)


def sbx_policy_checks(name, targets):
    out = {}
    for t in targets:
        r = sh(["sbx", "policy", "check", "network", t, "--sandbox", name, "--json"], timeout=60)
        try:
            out[t] = json.loads(r.stdout)
        except ValueError:
            out[t] = {"error": (r.stderr or r.stdout)[-200:]}
    return out


def sbx_log(name):
    r = sh(["sbx", "policy", "log", name, "--limit", "0", "--json"])
    try:
        return json.loads(r.stdout)
    except ValueError:
        return {"allowed": [{"host": "(policy log unreadable)"}]}

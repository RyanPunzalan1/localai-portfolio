"""`python -m workbench`: the one entry point the README documents (Phase 6, owner decision 2026-11-25).

  doctor                           check this machine: Python, Docker, Ollama and the model, sbx and its settings,
                                   the reference agent images. Says which tiers can run; changes nothing.
  pack PACK                        validate a scenario pack and list its scenarios (PACK: a built-in name or a folder)
  run PACK --agent A --profile P   run every scenario in PACK against each agent x profile as one fail-closed batch
                                   (Phase 4), then write the report and check its numbers
  report RESULTS... --out DIR      report.html and report.md from schema-1 results
  check DIR RESULTS...             recount every number in DIR's report from the raw results (exit 1 on a difference)
  reproduce REFERENCE_DIR          rebuild a shipped reference report byte for byte and check its numbers
  compare REFERENCE.jsonl NEW.jsonl   a live run against a reference: every benign outcome must match; each attack
                                   outcome that differs is listed with its evidence, for a person to explain

Rules it enforces (design D1, D6, Phase 4):
  - the Docker tier (docker-none) runs only code you trust: any agent other than this project's own `localai` needs
    --trusted-code. Third-party agents belong in the VM tier.
  - the VM tier (sbx-deny-all) runs only on macOS. Linux is untested (D6), so it is refused there.
  - a batch does not start unless each isolation check it relies on detects a planted leak (negative controls).
"""

import argparse
import datetime as dt
import importlib
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from workbench import adapters, batch, isolation as iso, report, scenario, specs, trial

ROOT = Path(__file__).resolve().parent.parent
AGENTS = ("localai", "hermes")
OWN_CODE = trial.OWN_CODE  # this project's own agent; everything else is third-party for D1
PROFILES = tuple(specs.AGENT)
DEFAULT_OUT = Path.home() / ".agent-workbench" / "runs"


def _checker():
    sys.path.insert(0, str(ROOT / "experiments" / "checks"))
    return importlib.import_module("verify_report_numbers")


def load_pack(ref: str) -> scenario.Pack:
    """A built-in pack by name ("core", "examples"), or a pack folder by path."""
    if "/" not in ref and (scenario.PACKS / ref).is_dir():
        return scenario.load_pack(scenario.PACKS / ref)
    return scenario.load_pack(Path(ref).expanduser())


# ------------------------------------------------------------------ rules (pure)
def select_scenarios(order, wanted):
    """The pack's scenario ids to run, in pack order. `wanted` empty means all. An unknown id is an error, never skipped."""
    if not wanted:
        return list(order)
    unknown = [w for w in wanted if w not in order]
    if unknown:
        raise ValueError(f"unknown scenario {', '.join(unknown)} (the pack has: {', '.join(order)})")
    return [sid for sid in order if sid in wanted]


def refuse_combo(agent: str, profile: str, trusted_code: bool, system: str, vm_image_ok: bool = True) -> str | None:
    """Why this agent x profile may not run here, or None. vm_image_ok: the agent's manifest image is the VM template."""
    if profile not in specs.AGENT:
        return f"unknown profile {profile!r} (choose from {', '.join(PROFILES)})"
    if agent not in AGENTS:
        return f"unknown agent {agent!r} (choose from {', '.join(AGENTS)})"
    if specs.AGENT[profile].tier == 1 and agent not in OWN_CODE and not trusted_code:
        return (f"{agent} is third-party code: the Docker tier shares the host's kernel, so it runs only code you trust. "
                f"Use --profile sbx-deny-all, or pass --trusted-code if you have reviewed it (design D1)")
    if specs.AGENT[profile].tier == 2 and system != "Darwin":
        return f"the VM tier is only tested on macOS; {system} is untested and refused (design D6)"
    if specs.AGENT[profile].tier == 2 and not vm_image_ok:
        return f"{agent} has no VM-tier image yet (its manifest image is not {specs.SBX_TEMPLATE})"
    return None


def doctor_report(checks: list) -> tuple:
    """checks: [(name, ok: bool|None, detail, tiers_needing_it)]. Returns (text, {tier: usable})."""
    usable = {1: True, 2: True}
    lines = []
    for name, ok, detail, tiers in checks:
        mark = "OK  " if ok else ("SKIP" if ok is None else "FAIL")
        lines.append(f"  {mark} {name}: {detail}")
        if ok is False:
            for t in tiers:
                usable[t] = False
    lines.append("")
    lines.append(f"  Docker tier (docker-none): {'ready' if usable[1] else 'NOT ready'}")
    lines.append(f"  VM tier (sbx-deny-all):    {'ready' if usable[2] else 'NOT ready'}")
    return "\n".join(lines), usable


def compare(reference: list, new: list) -> dict:
    """Gate rule (owner decision 2026-11-25): benign outcomes must match exactly; attack outcomes that differ are
    listed with their evidence so a person can explain each one. Keyed by (agent, profile, scenario, repeat)."""
    def key(r):
        return ((r.get("agent") or {}).get("name"), r["profile"]["name"], r["scenario"]["id"], r.get("repeat") or 1)

    def evidence(r):
        mc = r["evidence"].get("model_channel") or {}
        return {"category": r["outcome"]["category"], "sub": r["outcome"].get("sub"),
                "predicates": {k: v for k, v in (r["outcome"].get("predicates") or {}).items() if v},
                "tools_requested": mc.get("tool_calls_requested"), "canaries_in_prompt": mc.get("canaries_in_prompt"),
                "workspace": {k: v for k, v in (r["evidence"].get("workspace") or {}).items() if v}}

    ref, got = {key(r): r for r in reference}, {key(r): r for r in new}
    out = {"benign_mismatch": [], "attack_differs": [], "missing": sorted(map(str, set(ref) - set(got))),
           "extra": sorted(map(str, set(got) - set(ref))), "same": 0}
    for k in sorted(set(ref) & set(got), key=str):
        a, b = ref[k], got[k]
        if a["scenario"].get("hash") != b["scenario"].get("hash"):
            out["benign_mismatch" if a["scenario"]["kind"] == "benign" else "attack_differs"].append(
                {"case": k, "reason": "scenario hash differs: not the same scenario"})
            continue
        if a["outcome"]["category"] == b["outcome"]["category"]:
            out["same"] += 1
        elif a["scenario"]["kind"] == "benign":
            out["benign_mismatch"].append({"case": k, "reference": evidence(a), "new": evidence(b)})
        else:
            out["attack_differs"].append({"case": k, "reference": evidence(a), "new": evidence(b)})
    out["pass"] = not out["benign_mismatch"] and not out["missing"]
    return out


# ------------------------------------------------------------------ doctor (calls the runtimes)
def _cmd(args, timeout=30):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, "", e.__class__.__name__


def engine_ok(os_type) -> bool:
    """Docker must run Linux containers (Docker Desktop can be switched to Windows containers, which this cannot use)."""
    return (os_type or "").strip().lower() == "linux"


def platform_detail(system) -> str:
    if system == "Windows":
        return "Windows: the VM tier is refused; only the Docker tier (shared WSL2 kernel, owner-accepted) can run"
    return f"{system}: the VM tier is untested here and refused (D6)"


def doctor_checks() -> list:
    system = platform.system()
    checks = [("python", sys.version_info >= (3, 11), platform.python_version() + " (needs 3.11+ for tomllib)", (1, 2))]
    dv = iso.docker_version()
    checks.append(("docker", bool(dv), dv or "not reachable (is Docker Desktop running?)", (1, 2)))
    if dv:
        os_type = _cmd(["docker", "info", "--format", "{{.OSType}}"])[1]
        checks.append(("docker containers", engine_ok(os_type), f"{os_type or 'unknown'} containers (needs linux)", (1, 2)))
    from workbench import model_info
    model_problems = model_info.check_local(trial.MODEL)
    checks.append(("ollama model", not model_problems,
                   f"{trial.MODEL} present ({model_info.digest(trial.MODEL)})" if not model_problems
                   else "; ".join(model_problems), (1, 2)))
    for name in AGENTS:
        try:
            m = adapters.load(name).manifest
            iid = dv and _cmd(["docker", "image", "inspect", m.image, "--format", "{{.Id}}"])[1]
            ok = bool(iid) and (not m.image_id or iid == m.image_id)
            checks.append((f"agent image {name}", ok, m.image + (" ok" if ok else " missing or not the pinned build"),
                           (1, 2) if name in OWN_CODE else (2,)))
        except Exception as e:  # a broken manifest is a failed check, not a crash
            checks.append((f"agent image {name}", False, f"manifest problem: {e}", (1, 2)))
    if system != "Darwin":
        checks.append(("platform", False, platform_detail(system), (2,)))
        return checks
    if not shutil.which("sbx"):
        checks.append(("sbx", False, "not installed (Docker Sandboxes)", (2,)))
        return checks
    v = iso.sbx_version()
    checks.append(("sbx version", not iso.check_sbx_version(v), f"{v} (validated: {specs.SBX_VERSION})", (2,)))
    host = iso.check_sbx_host(iso.sbx_settings(), iso.sbx_mcp_servers())
    checks.append(("sbx host bridges", not host, "browser and SSH forwarding off, no MCP servers registered"
                   if not host else "; ".join(host), (2,)))
    tmpl = _cmd(["docker", "image", "inspect", specs.SBX_TEMPLATE, "--format", "{{.Id}}"])[1]
    checks.append(("sbx template", bool(tmpl), specs.SBX_TEMPLATE + (" present" if tmpl else " missing"), (2,)))
    return checks


# ------------------------------------------------------------------ commands
def cmd_doctor(a):
    text, usable = doctor_report(doctor_checks())
    print("Workbench doctor (changes nothing):\n" + text)
    return 0 if usable[1] or usable[2] else 1


def cmd_pack(a):
    p = load_pack(a.pack)
    print(f"pack {p.name} v{p.version} hash {p.hash}: {p.description}")
    for sid in p.order:
        d = p.scenarios[sid]
        print(f"  {sid:28} {d['kind']:7} needs {', '.join(d['requires'])}")
    return 0


def cmd_run(a):
    pack = load_pack(a.pack)
    combos = [(ag, pr) for ag in (a.agent or []) for pr in (a.profile or [])]
    for pair in a.pair or []:
        ag, _, pr = pair.partition(":")
        combos.append((ag, pr))
    if bool(a.agent) != bool(a.profile) or not combos:
        print("give --agent and --profile together (every combination), and/or --pair agent:profile")
        return 2
    combos = list(dict.fromkeys(combos))
    try:
        scenario_ids = select_scenarios(pack.order, a.scenario)
    except ValueError as e:
        print(f"refused: {e}")
        return 2
    for ag, pr in combos:
        vm_ok = ag not in AGENTS or adapters.load(ag).manifest.image.removeprefix("docker.io/") == \
            specs.SBX_TEMPLATE.removeprefix("docker.io/")
        why = refuse_combo(ag, pr, a.trusted_code, platform.system(), vm_ok)
        if why:
            print(f"refused: {ag} on {pr}: {why}")
            return 2
    from workbench import controls, model_info
    model_problems = model_info.check_local(a.model)
    if model_problems:
        print(f"refused: model {a.model}: " + "; ".join(model_problems))
        return 2
    model_digest = model_info.digest(a.model)
    print(f"model: {a.model} ({model_digest})")
    neg = {}
    if any(specs.AGENT[p].tier == 1 for _, p in combos):
        neg["docker"] = controls.docker_detected()
    if any(specs.AGENT[p].tier == 2 for _, p in combos):
        refused = iso.check_sbx_version(iso.sbx_version()) or iso.check_sbx_host(iso.sbx_settings(), iso.sbx_mcp_servers())
        if refused:
            print("refused: the VM tier is not ready:\n  - " + "\n  - ".join(refused) + "\nRun: python -m workbench doctor")
            return 2
        neg["sbx"] = controls.sbx_detected()
    print("negative controls:", {k: "detected" if v else "NOT DETECTED" for k, v in neg.items()})
    if not all(neg.values()):
        print("stopping: an isolation check could not see a planted leak, so nothing it reports could be trusted")
        return 1
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = Path(a.out).expanduser() / f"{pack.name}-{stamp}"
    out.mkdir(parents=True)
    refs = {ag: adapters.load(ag) for ag, _ in combos}
    cases = [(ag, pr, sid, rep) for ag, pr in combos for rep in range(1, a.repeats + 1) for sid in scenario_ids]
    run_id = f"{pack.name}-{stamp}"

    def run_one(case, guard):
        ag, pr, sid, rep = case
        rec, details = trial.run_trial(refs[ag], pack.instantiate(sid), pr, run_id, rep, model=a.model, guard=guard,
                                       negative_control_ok=neg["sbx" if specs.AGENT[pr].tier == 2 else "docker"],
                                       sampling=trial.sampling_for(), model_digest=model_digest)
        print(f"  {ag}:{pr}/{sid} r{rep} -> {rec['outcome']['category']} {rec['outcome']['sub'] or ''}", flush=True)
        return rec, details

    print(f"running {len(cases)} trials; results in {out}")
    s = batch.run_batch(cases, run_one, out / "results.jsonl", batch.Guard(), out / "batch-summary.json")
    subprocess.run(["ollama", "stop", a.model], capture_output=True)
    if not (out / "results.jsonl").exists():
        print("no trial produced a record")
        return 1
    res = report.write([out / "results.jsonl"], out / "report", f"Workbench run: pack {pack.name}")
    problems = _checker().check(out / "report", [out / "results.jsonl"])
    print(f"report: {res['html']}\nnumbers: {'agree' if not problems else 'DISAGREE: ' + '; '.join(problems[:5])}")
    return 1 if s["stopped"] or problems else 0


def cmd_report(a):
    res = report.write(a.results, a.out, a.title)
    print(json.dumps(res, indent=2))
    return 0


def cmd_comparisons(a):
    from workbench import comparison
    recs, skipped = report.load(a.results)
    files = comparison.write_all(recs, a.out)
    print(f"{len(recs)} trials ({len(skipped)} skipped); wrote {len(files)} files to {a.out}")
    return 0 if recs else 1


def cmd_check(a):
    problems = _checker().check(a.dir, a.results)
    print("OK: every number agrees" if not problems else "DISAGREE:\n  - " + "\n  - ".join(problems[:50]))
    return 1 if problems else 0


def reproduce(ref_dir: Path, work: Path) -> list:
    """Rebuild the reference report from its shipped results; both files must be byte-identical and the numbers agree."""
    meta = json.loads((ref_dir / "reference.json").read_text(encoding="utf-8"))
    results = [ref_dir / r for r in meta["results"]]
    report.write(results, work, meta["title"])
    problems = [f"{n} differs from the shipped report" for n in ("report.html", "report.md")
                if (work / n).read_bytes() != (ref_dir / "report" / n).read_bytes()]
    return problems + _checker().check(work, results)


def cmd_reproduce(a):
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        problems = reproduce(Path(a.reference), Path(d))
    print("OK: the shipped report rebuilds byte for byte and every number agrees" if not problems
          else "FAILED:\n  - " + "\n  - ".join(problems))
    return 1 if problems else 0


def cmd_compare(a):
    def read(p):
        recs, skipped = report.load([p])
        if skipped:
            print(f"note: {len(skipped)} invalid lines skipped in {p}")
        return recs
    c = compare(read(a.reference), read(a.new))
    print(f"same outcome: {c['same']}")
    for label in ("missing", "extra"):
        if c[label]:
            print(f"{label} cases: {c[label]}")
    for label, title in (("benign_mismatch", "BENIGN OUTCOMES DIFFER (gate fails)"),
                         ("attack_differs", "attack outcomes that differ (each needs an explanation from its evidence)")):
        if c[label]:
            print(f"\n{title}:")
            for d in c[label]:
                print("  ", json.dumps(d, default=str))
    print(f"\ngate: {'PASS' if c['pass'] else 'FAIL'}"
          + (f" ({len(c['attack_differs'])} attack difference(s) to explain)" if c["attack_differs"] else ""))
    return 0 if c["pass"] else 1


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m workbench", description="Agent security workbench.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor", help="check this machine; changes nothing").set_defaults(f=cmd_doctor)
    p = sub.add_parser("pack", help="validate a scenario pack and list it")
    p.add_argument("pack")
    p.set_defaults(f=cmd_pack)
    p = sub.add_parser("run", help="run a pack against agents and profiles")
    p.add_argument("pack")
    p.add_argument("--agent", action="append", choices=AGENTS, help="with --profile: every agent x profile")
    p.add_argument("--profile", action="append", choices=PROFILES)
    p.add_argument("--pair", action="append", metavar="AGENT:PROFILE", help="one agent on one profile")
    p.add_argument("--repeats", type=int, default=1, choices=range(1, 11), metavar="1-10")
    p.add_argument("--scenario", action="append", metavar="ID", help="only this scenario (repeatable); default: the whole pack")
    p.add_argument("--trusted-code", action="store_true", help="allow a third-party agent in the Docker tier (D1)")
    p.add_argument("--model", default=trial.MODEL,
                   help=f"a model already installed in the local Ollama (default {trial.MODEL}); never pulled, never a cloud model")
    p.add_argument("--out", default=str(DEFAULT_OUT))
    p.set_defaults(f=cmd_run)
    p = sub.add_parser("report", help="build report.html and report.md")
    p.add_argument("results", nargs="+")
    p.add_argument("--out", required=True)
    p.add_argument("--title", default="Agent security workbench report")
    p.set_defaults(f=cmd_report)
    p = sub.add_parser("comparisons", help="one comparison report per axis: agent, platform, sandbox, scenario, outcome")
    p.add_argument("results", nargs="+")
    p.add_argument("--out", required=True)
    p.set_defaults(f=cmd_comparisons)
    p = sub.add_parser("check", help="recount a report's numbers from raw results")
    p.add_argument("dir")
    p.add_argument("results", nargs="+")
    p.set_defaults(f=cmd_check)
    p = sub.add_parser("reproduce", help="rebuild a shipped reference report and check it")
    p.add_argument("reference")
    p.set_defaults(f=cmd_reproduce)
    p = sub.add_parser("compare", help="compare a live run with a reference run")
    p.add_argument("reference")
    p.add_argument("new")
    p.set_defaults(f=cmd_compare)
    a = ap.parse_args(argv)
    try:
        return a.f(a)
    except scenario.ScenarioError as e:
        print(f"pack refused: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())

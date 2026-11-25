"""One agent trial, start to finish (design 5.1). Trusted host-side code; the agent and everything it writes is hostile.

Steps: pin the image; build the fixture copy; digest it; create the no-network sandbox; validate isolation (configuration
check, then preflight) BEFORE any agent code is delivered; deliver the adapter and task; start the model channel; check
isolation again with the channel running; run the agent under a timeout; stop the sandbox and freeze it; collect host-side
evidence (workspace digest, channel log, approvals, runtime log); decide the outcome with workbench.verdict; write one
schema-1 record. Any isolation problem or channel violation makes the trial inconclusive; nothing is retried.
"""

import hashlib
import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path

from workbench import channel as ch, contract, digest, isolation as iso, memory as mem, model_policy as mp, record as R, \
    runtime, specs, verdict
from workbench import tripwire as tw_mod

MODEL = "gpt-oss-64k"  # the project's model (64K-window tag); hermes3 failed the benign control on the host too
MAX_REPLY_TOKENS = 4096
MAX_MODEL_CALLS = 60


def scenario_hash(scn) -> str:
    return hashlib.sha256(json.dumps(scn["template"], sort_keys=True).encode()).hexdigest()[:16]


def _fixture(root: Path, scn):
    ws = root / "ws"
    docs = ws / "docs"
    docs.mkdir(parents=True)
    for name, text in scn["files"].items():
        (docs / name).write_text(text, encoding="utf-8")
    if scn.get("secret_file"):
        (ws / "secret.txt").write_text(scn["secret_file"], encoding="utf-8")
    for p in [ws, docs]:
        os.chmod(p, 0o777)  # the sandbox user (uid 1000) may differ from the host user on Linux
    return ws


def run_trial(reference, scn, profile_name, run_id, repeat=1, model=MODEL, negative_control_ok=None, debug=False,
              guard=None):
    """Run one scenario against one agent in one agent profile. Returns (record, details).

    guard: an optional batch guard (workbench.batch.Guard) with tokens() -> {name: tripwire token} and
    check() -> (shared tripwire changes, inventory changes). Without one, only the trial's own tripwire is checked.
    Raises isolation.IsolationRefused before creating anything if the VM tier's runtime version is not the validated one,
    a host bridge setting is on, or an MCP server is registered with sbx.
    """
    m = reference.manifest
    prof = specs.AGENT[profile_name]
    rt = "sbx" if prof.network == "sbx-deny-all" else "docker"
    contract.require_pinned_for_tier(m, prof.tier)
    if rt == "sbx":
        refused = iso.check_sbx_version(iso.sbx_version()) or iso.check_sbx_host(iso.sbx_settings(),
                                                                                  iso.sbx_mcp_servers())
        if refused:
            raise iso.IsolationRefused("; ".join(refused))
    runtime_version = iso.sbx_version() if rt == "sbx" else iso.docker_version()
    pre, during, log_problems, cfg_before, cfg_after = [], [], [], [], []
    chan, name, tw, sampler = None, f"wb-ag-{uuid.uuid4().hex[:8]}", None, None
    root = Path(tempfile.mkdtemp(prefix="wb-trial-")).resolve()
    ev = {"workspace": {"created": [], "removed": [], "modified": []}, "model_channel": None, "approvals": [],
          "runtime": {"exit_code": None, "timed_out": False, "memory": None}, "answer": "", "isolation_problems": [],
          "channel_violation": None}
    details = {"answer": "", "events": [], "policy_records": []}
    iso_state = {"config_ok": None, "preflight_ok": None, "runtime_log_ok": None, "negative_control_ok": negative_control_ok}
    post = {"trial": [], "shared": [], "inventory": [], "other": [], "kept_at": None}
    tokens, rec = {}, None
    try:
        if m.image_id and runtime.image_id(m.image) != m.image_id:
            raise contract.ContractError(f"local image {m.image} does not match the manifest's image_id")
        if rt == "sbx" and m.image.removeprefix("docker.io/") != specs.SBX_TEMPLATE.removeprefix("docker.io/"):
            raise contract.ContractError("the VM tier can only run the loaded sbx template for this agent")
        missing = contract.applies(scn["requires"], m)
        if missing:
            rec = _record(run_id, repeat, scn, prof, m, rt, model, iso_state, ev, details,
                          {"category": "not_applicable", "sub": f"agent lacks: {', '.join(missing)}", "attribution": None,
                           "predicates": {}}, runtime_version=runtime_version)
            return rec, details
        # 0. host tripwires: one beside this trial's workspace (never inside a mount), plus the batch's shared one
        try:
            tw = tw_mod.Tripwire(root / "tripwire")
            tokens["tripwire_trial"] = tw.token
        except tw_mod.TripwireError as e:
            post["other"].append(f"trial tripwire not planted: {e}")
        if guard is not None:
            tokens.update(guard.tokens())
        ws = _fixture(root, scn)
        before = digest.digest(ws)
        # 1. create the sandbox and validate isolation before any agent code exists in it
        if rt == "docker":
            runtime.create_docker(name, prof, ws, m.image, reference.tmpfs)
            sampler = mem.Sampler(lambda: mem.docker_mem_mib(name)).start()
            cfg_before = iso.check_docker_inspect(iso.docker_inspect(name), prof)
            pre = iso.evaluate_preflight(iso.run_preflight_docker(name))
        else:
            allows = iso.global_allow_resources(iso.sbx_local_policy())
            (root / "primary").mkdir()
            baseline_pids = mem.docklet_pids()
            runtime.create_sbx(name, ",".join(sorted(allows)), ws, root / "primary")
            sampler = mem.Sampler(lambda: mem.sbx_rss_mib(baseline_pids)).start()
            cfg_before = (iso.check_sbx_rules(iso.sbx_rules(name), name, allows)
                          + iso.check_sbx_inspect(iso.sbx_inspect(name), name, ws, root / "primary"))
            pre = iso.evaluate_preflight(iso.run_preflight_sbx(name))
        if not (cfg_before or pre or post["other"]):
            # 2. deliver the adapter and task, start the channel, check isolation again with it running
            runtime.deliver(rt, name, {**reference.files, "/run/task.json": contract.task_file(scn["request"], name)})
            policy = mp.ModelPolicy(model, max_tokens=MAX_REPLY_TOKENS, max_calls=MAX_MODEL_CALLS,
                                    canaries={**scn["values"], **tokens}, keep_reply_heads=700 if debug else 0)
            chan = ch.Channel(ch.shim_command(rt, name), policy, approval="deny_all")
            if not chan.wait_ready(60):
                ev["channel_violation"] = chan.violation or "shim did not start"
            else:
                during = iso.evaluate_preflight(iso.run_preflight_sbx(name) if rt == "sbx"
                                                else iso.run_preflight_docker(name))
            if not during and not ev["channel_violation"]:
                # 3. run the agent under a timeout
                rc, out, err = runtime.exec_in(rt, name, list(m.entrypoint), env={**reference.env, "WORKBENCH_MODEL": model},
                                               cwd="/workspace",
                                               timeout=m.timeout_seconds + 30)
                ev["runtime"].update(exit_code=None if rc == -1 else rc, timed_out=rc == -1)
                details["stderr_tail"] = (err or "")[-300:]
                # 4. read the self-reported files while the sandbox is still frozen in place
                details["answer"] = contract.parse_answer(runtime.read_file(rt, name, contract.ANSWER_PATH,
                                                                            contract.MAX_ANSWER_BYTES))
                details["events"] = contract.parse_events(runtime.read_file(rt, name, contract.EVENTS_PATH,
                                                                            contract.MAX_EVENTS_BYTES))
            if chan.violation:
                ev["channel_violation"] = chan.violation
        # 5. runtime record and configuration after the run
        if sampler is not None:
            ev["runtime"]["memory"] = sampler.stop()
            sampler = None
        if rt == "sbx":
            log_problems = iso.check_sbx_log(iso.sbx_log(name))
            iso_state["runtime_log_ok"] = not log_problems
            cfg_after = (iso.check_sbx_rules(iso.sbx_rules(name), name, iso.global_allow_resources(iso.sbx_local_policy()))
                         + iso.check_sbx_inspect(iso.sbx_inspect(name), name, ws, root / "primary"))
        else:
            cfg_after = iso.check_docker_inspect(iso.docker_inspect(name), prof)
        runtime.stop(rt, name)  # freeze before observing
        after = digest.digest(ws)
        ev["workspace"] = digest.changes(before, after)
        ev["answer"] = details["answer"]
        if chan is not None:
            chan.close()
            ev["approvals"] = list(chan.approvals)
            recs = policy.records
            details["policy_records"] = recs
            fwd = [x for x in recs if x["decision"] == "forwarded"]
            ev["model_channel"] = {"requests": len(recs), "forwarded": len(fwd),
                                   "refused": sum(1 for x in recs if x["decision"] == "refused"),
                                   "canaries_in_prompt": sorted({c for x in fwd for c in x["canaries_in_prompt"]}),
                                   "tool_calls_requested": sorted({t for x in fwd for t in x.get("tool_calls_requested", [])})}
        iso_state["config_ok"] = not (cfg_before or cfg_after)
        iso_state["preflight_ok"] = not (pre or during)
        ev["isolation_problems"] = sorted(set(cfg_before + cfg_after + pre + during + log_problems))
        iso_state["problems"] = ev["isolation_problems"]
        outcome = verdict.decide(scn, m.level, ev)
        rec = _record(run_id, repeat, scn, prof, m, rt, model, iso_state, ev, details, outcome,
                      runtime_version=runtime_version, extra_redact=tokens)
    finally:
        if sampler is not None:
            sampler.stop()
        if chan is not None:
            chan.close()
            try:
                chan.proc.wait(timeout=10)
                for s in (chan.proc.stdin, chan.proc.stdout, chan.proc.stderr):
                    s.close()
            except Exception:
                pass
        runtime.remove(rt, name)
        # 6. after the sandbox is gone: tripwires and the host inventory (design 4.5)
        if tw is not None:
            post["trial"] = tw.check()
        if guard is not None and (rec is None or rec["outcome"]["category"] != "not_applicable"):
            try:
                post["shared"], post["inventory"] = guard.check()
            except Exception as e:  # an unreadable tripwire or inventory is an anomaly, never clean
                post["other"].append(f"guard check failed: {e}")
        if post["trial"] or post["shared"] or post["inventory"] or post["other"] or _leaked(rec, tokens):
            post["kept_at"] = str(root)  # design 4.5: keep the evidence (synthetic fixture and tripwire only)
        else:
            shutil.rmtree(root, ignore_errors=True)
    if rec["outcome"]["category"] != "not_applicable":
        apply_integrity(rec, post, tokens)
    return rec, details


def _leaked(rec, tokens) -> list:
    """Names of tripwire tokens the host-side channel saw in a prompt (only a sandbox that read a tripwire could send one)."""
    mc = ((rec or {}).get("evidence") or {}).get("model_channel") or {}
    return sorted(n for n in (mc.get("canaries_in_prompt") or []) if n in tokens)


def apply_integrity(rec, post, tokens):
    """Fill evidence.tripwires and, on any anomaly, make the trial inconclusive with the reason (design 4.5 step 2/3)."""
    leaked = _leaked(rec, tokens)
    anomaly, reasons = tw_mod.classify(post["trial"], post["shared"], leaked, post["inventory"],
                                       rec["isolation"].get("problems") or [], post["other"])
    rec["evidence"]["tripwires"] = {"planted": sorted(tokens), "trial": post["trial"], "shared": post["shared"],
                                    "in_model_channel": leaked, "inventory": post["inventory"],
                                    "anomaly": anomaly, "reasons": reasons, "kept_at": post.get("kept_at")}
    if anomaly:
        rec["outcome"] = verdict.integrity_outcome(anomaly, reasons, rec["outcome"])
    return rec


def _record(run_id, repeat, scn, prof, m, rt, model, iso_state, ev, details, outcome, runtime_version=None,
            extra_redact=None):
    values = {**scn["values"], **(extra_redact or {})}
    return R.new_record(
        run_id=run_id, repeat=repeat,
        scenario={"id": scn["id"], "version": scn.get("version", 1), "kind": scn["kind"],
                  "hash": scn.get("hash") or scenario_hash(scn), "pack": scn.get("pack")},
        profile={"name": prof.name, "tier": prof.tier, "network": prof.network},
        agent={"name": m.name, "image_digest": m.image_id or (m.image if m.pinned else None), "contract_level": m.level},
        versions={"runtime": rt, "runtime_version": runtime_version, "model": model},
        isolation={**iso_state, "problems": ev.get("isolation_problems", [])},
        evidence={"workspace": ev["workspace"], "model_channel": ev["model_channel"], "approvals": ev["approvals"],
                  "runtime": ev["runtime"]},
        self_reported={"answer_excerpt": contract.redact(details["answer"][:500], values),
                       "events": contract.redact(details["events"][:50], values)},
        outcome=outcome)

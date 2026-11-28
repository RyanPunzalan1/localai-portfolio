"""Evidence record, schema 1 (design 7.2 and 8.1). One JSON object per trial, one line each in a results JSONL file.

Shape (every key is always present; unknown evidence is null, never guessed):

  schema            1
  trial_id, run_id, time, repeat
  scenario          {id, version, kind: attack|benign|control, hash}
                    (Phase 5: also pack: {name, version, hash} for scenarios loaded from a pack, else null)
  agent             {name, image_digest, contract_level} or null for scripted operations
  profile           {name, tier: 0|1|2, network: internal|none|sbx-deny-all}
  versions          {workbench, runtime, model, model_digest}
  isolation         {config_ok, preflight_ok, runtime_log_ok (null where the runtime keeps no record),
                     negative_control_ok, problems: []}
  evidence          {workspace: {created, removed, modified},
                     sink: {hits, canary_hits} or null (Tier 0 only),
                     network_log: {blocked, allowed, names, rank: 3} or null,
                     model_channel: {requests, forwarded, refused, canaries_in_prompt, tool_calls_requested} or null,
                     approvals: [{action, target, decision}],
                     runtime: {exit_code, timed_out},
                     tripwires: {planted: [token names], trial: [changes], shared: [changes],
                                 in_model_channel: [token names], inventory: [changes],
                                 anomaly: suspected_escape|integrity|null, reasons: []}
                                or null (records before Phase 4, scripted operations, not_applicable)}
  (Phase 4: versions also has runtime_version; evidence.runtime may have memory: {unit, samples, missed, peak, mean})
  (macOS RC: evidence.kept_at = "~/.agent-workbench/evidence/<run>/<trial folder>" when the trial folder was kept:
   every crashed, inconclusive or failed trial and every successful attack; absent when it was removed)
  self_reported     agent-reported text or events, labelled, never used for the outcome; or null
  outcome           {category (below), sub (reason, e.g. "timeout"), attribution: {layer, basis: observed|inferred}
                     or null, predicates: {name: bool}}

Categories (exactly one per trial; design 8.1):
  attack   unauthorized_action_succeeded, blocked, stopped_at_approval, attempt_unattributed,
           no_attempt_not_reached, no_attempt_held, inconclusive, not_applicable
  benign   completed, false_positive, failed_not_control, inconclusive, not_applicable
  control  observer_control_passed, observer_control_failed, permitted_action_passed, permitted_action_failed,
           inconclusive
"""

import json
import re
import time
import uuid
from pathlib import Path

SCHEMA = 1


def _repo_version() -> str:
    """The repo's version, from the VERSION file at the repo root (design/versioned-data-and-releases.md).
    "unknown" if it can't be read or isn't a version, so a record never claims a version it didn't come from."""
    try:
        text = (Path(__file__).resolve().parent.parent / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"
    return text if re.fullmatch(r"\d+\.\d+\.\d+(-rc\d+)?", text) else "unknown"


WORKBENCH_VERSION = _repo_version()
CATEGORIES = {
    "attack": {"unauthorized_action_succeeded", "blocked", "stopped_at_approval", "attempt_unattributed",
               "no_attempt_not_reached", "no_attempt_held", "inconclusive", "not_applicable"},
    "benign": {"completed", "false_positive", "failed_not_control", "inconclusive", "not_applicable"},
    "control": {"observer_control_passed", "observer_control_failed", "permitted_action_passed",
                "permitted_action_failed", "inconclusive"},
}
# Legacy labels (revision 2, T8, model runs) -> (kind, category). Shared with the dashboard as the mapping table.
LEGACY = {
    "succeeded": ("attack", "unauthorized_action_succeeded"),
    "attack_succeeded": ("attack", "unauthorized_action_succeeded"),
    "blocked": ("attack", "blocked"),
    "stopped_at_approval": ("attack", "stopped_at_approval"),
    "failed_unattributed": ("attack", "attempt_unattributed"),
    "did_not_reach_model": ("attack", "no_attempt_not_reached"),
    "held_by_model": ("attack", "no_attempt_held"),
    "no_attempt": ("attack", "no_attempt_held"),
    "inconclusive": (None, "inconclusive"),
    "benign_completed": ("benign", "completed"),
    "benign_false_positive": ("benign", "false_positive"),
    "benign_failed": ("benign", "failed_not_control"),
    "permitted_succeeded": ("control", "permitted_action_passed"),
    "permitted_blocked": ("control", "permitted_action_failed"),
    "control_ok": ("control", "permitted_action_passed"),
    "control_failed": ("control", "permitted_action_failed"),
}
TOP = ("schema", "trial_id", "run_id", "time", "repeat", "scenario", "agent", "profile", "versions", "isolation",
       "evidence", "self_reported", "outcome")
EVIDENCE = ("workspace", "sink", "network_log", "model_channel", "approvals", "runtime", "tripwires")


def legacy_category(label, kind=None):
    """Map an old label to a schema-1 category. A 'succeeded' with kind control is a permitted action (2026-11-21)."""
    if label == "succeeded" and kind == "control":
        return "permitted_action_passed"
    return LEGACY.get(label, (None, None))[1]


def new_record(*, run_id, scenario, profile, repeat=1, agent=None, versions=None, isolation=None, evidence=None,
               self_reported=None, outcome=None, trial_id=None):
    ev = {"workspace": {"created": [], "removed": [], "modified": []}, "sink": None, "network_log": None,
          "model_channel": None, "approvals": [], "runtime": {"exit_code": None, "timed_out": False},
          "tripwires": None}
    ev.update(evidence or {})
    return {
        "schema": SCHEMA, "trial_id": trial_id or uuid.uuid4().hex[:12], "run_id": run_id,
        "time": time.strftime("%Y-%m-%dT%H:%M:%S"), "repeat": repeat, "scenario": scenario, "agent": agent,
        "profile": profile,
        "versions": {"workbench": WORKBENCH_VERSION, "runtime": None, "model": None, "model_digest": None,
                     **(versions or {})},
        "isolation": {"config_ok": None, "preflight_ok": None, "runtime_log_ok": None, "negative_control_ok": None,
                      "problems": [], **(isolation or {})},
        "evidence": ev, "self_reported": self_reported,
        "outcome": {"category": None, "sub": None, "attribution": None, "predicates": {}, **(outcome or {})},
    }


def validate(rec) -> list:
    """Problems with a record. An empty list means it is a well-formed schema-1 record."""
    if not isinstance(rec, dict):
        return ["not an object"]
    problems = [f"missing key: {k}" for k in TOP if k not in rec]
    if problems:
        return problems
    if rec["schema"] != SCHEMA:
        problems.append(f"schema is {rec['schema']!r}, not 1")
    kind = (rec.get("scenario") or {}).get("kind")
    if kind not in CATEGORIES:
        problems.append(f"bad scenario kind: {kind!r}")
    cat = (rec.get("outcome") or {}).get("category")
    if kind in CATEGORIES and cat not in CATEGORIES[kind]:
        problems.append(f"category {cat!r} is not valid for kind {kind!r}")
    prof = rec.get("profile") or {}
    if prof.get("tier") not in (0, 1, 2) or prof.get("network") not in ("internal", "none", "sbx-deny-all"):
        problems.append(f"bad profile: {prof}")
    if prof.get("tier") in (1, 2) and prof.get("network") == "internal":
        problems.append("agent profiles must have no network (D8)")
    ev = rec.get("evidence") or {}
    problems += [f"missing evidence key: {k}" for k in EVIDENCE if k not in ev]
    att = (rec.get("outcome") or {}).get("attribution")
    if att is not None and att.get("basis") not in ("observed", "inferred"):
        problems.append("attribution basis must be observed or inferred")
    if cat == "inconclusive" and not (rec.get("outcome") or {}).get("sub"):
        problems.append("inconclusive needs a sub-reason")
    return problems


def append(path, rec):
    problems = validate(rec)
    if problems:
        raise ValueError(f"refusing to write an invalid record: {problems}")
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(rec, sort_keys=True) + "\n")

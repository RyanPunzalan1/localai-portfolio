"""Read experiment result files and normalise them for the dashboard.

Read-only: nothing here writes, moves, or deletes a file. No Streamlit import, so it can be tested on its own.

Text fields copied from records (paths, error tails, answers) are untrusted. They are kept as plain strings here;
the views must render them escaped, never as markdown or HTML.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
# Overridable so tests and a dev preview can point the dashboard at a scratch folder instead of real results.
SECURITY_DIR = Path(os.environ.get("DASHBOARD_SECURITY_RESULTS") or ROOT / "experiments" / "local_agent" / "results")
WORKBENCH_DIR = Path(os.environ.get("DASHBOARD_WORKBENCH_RESULTS")
                     or ROOT / "experiments" / "workbench_phase2" / "results")
MODEL_TEST_DIR = Path(os.environ.get("DASHBOARD_MODEL_RESULTS") or ROOT / "experiments" / "hermes_agent" / "results")

# Record label -> display group. Labels not listed here map to "other" and are shown, never dropped.
LABEL_GROUPS = {
    "succeeded": "succeeded",
    "blocked": "blocked",
    "failed_unattributed": "unattributed",
    "no_attempt": "no_attempt",
    "benign_completed": "benign_completed",
    "benign_false_positive": "false_positive",
    "permitted_succeeded": "control_passed",
    "permitted_blocked": "control_failed",
}

# Workbench schema-1 category -> display group. Categories stay separate: a run that was never reached, one the
# model held back from, and one stopped at approval are three groups, none of them "blocked".
WORKBENCH_GROUPS = {
    "unauthorized_action_succeeded": "succeeded", "blocked": "blocked", "stopped_at_approval": "stopped_at_approval",
    "attempt_unattributed": "unattributed", "no_attempt_not_reached": "not_reached", "no_attempt_held": "no_attempt",
    "inconclusive": "inconclusive", "not_applicable": "other",
    "completed": "benign_completed", "false_positive": "false_positive", "failed_not_control": "other",
    "observer_control_passed": "control_passed", "permitted_action_passed": "control_passed",
    "observer_control_failed": "control_failed", "permitted_action_failed": "control_failed",
}
# Categories where an action was actually attempted or proposed. No-attempt and inconclusive are not counted here.
WORKBENCH_ATTEMPTED = {"unauthorized_action_succeeded", "blocked", "stopped_at_approval", "attempt_unattributed"}

# Fields the independent observer writes. A record missing any of them is "unverified".
OBSERVER_FIELDS = {
    "forced_control": ("sink_hits", "files_changed", "rc"),
    "model_run": ("sink_hits", "workspace_changed"),
}

TRIAL_COLUMNS = [
    "run_id", "source_file", "suite", "superseded", "item", "kind", "config", "model", "repeat",
    "label", "group", "layer", "attribution", "verified", "attempted", "sink_hits", "sink_canary_hits",
    "files_changed", "rc", "err_tail", "canary_in_output", "evidence", "tool_calls", "time", "raw",
]
WORKBENCH_SUITE = "workbench"


@dataclass(frozen=True)
class ResultFile:
    path: Path
    run_id: str
    suite: str          # forced_control | model_run | model_test:<tN> | unknown
    superseded: bool
    model_hint: str | None = None   # model name taken from the file name, when present


@dataclass
class LoadReport:
    """Lines that could not be parsed, so the UI can say so instead of hiding them."""
    bad_lines: list[tuple[str, int]]


def classify(path: Path) -> ResultFile:
    """Work out what kind of results a file holds from its name and folder."""
    name = path.stem
    superseded = any(p.name.startswith("superseded") for p in path.parents)
    model_hint = None
    if name.startswith("control"):
        suite = "forced_control"
    elif name.startswith("run-"):
        suite = "model_run"
    else:
        m = re.match(r"(t\d+)(?:-([a-z][\w.:-]*?))?-\d{8}-\d{6}", name)
        if m:
            suite = f"model_test:{m.group(1)}"
            variant = m.group(2)
            # Suffixes such as "ablate" or "localai-loop" are test variants, not model names.
            if variant and re.match(r"(hermes|gpt-oss|llama|qwen|mistral)", variant):
                model_hint = variant
        else:
            suite = WORKBENCH_SUITE if _is_workbench_file(path) else "unknown"
    return ResultFile(path, name, suite, superseded, model_hint)


def _is_workbench_file(path: Path) -> bool:
    """A JSONL whose first record has "schema": 1 holds workbench evidence records."""
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    rec = json.loads(line)
                    return isinstance(rec, dict) and rec.get("schema") == 1
    except (OSError, json.JSONDecodeError):
        pass
    return False


def discover(directory: Path, include_superseded: bool = False) -> list[ResultFile]:
    """All *.jsonl result files under a folder, newest name first.

    Folders starting with "_" (such as _live/, the runners' live status and event stream) and *.events.jsonl
    files hold bookkeeping, not trial records, so they are never read as results.
    """
    if not directory.is_dir():
        return []
    files = [classify(p) for p in directory.rglob("*.jsonl")
             if not p.name.endswith(".events.jsonl")
             and not any(part.startswith("_") for part in p.relative_to(directory).parts[:-1])]
    if not include_superseded:
        files = [f for f in files if not f.superseded]
    return sorted(files, key=lambda f: f.path.name, reverse=True)


def read_jsonl(path: Path, report: LoadReport | None = None) -> list[dict]:
    """Parse a JSONL file. Unreadable lines (for example a half-written last line) are skipped and reported."""
    records = []
    with path.open(encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                if report is not None:
                    report.bad_lines.append((path.name, n))
                continue
            if isinstance(rec, dict):
                records.append(rec)
            elif report is not None:
                report.bad_lines.append((path.name, n))
    return records


def attribution_of(layer: str | None) -> str | None:
    """'observed' or 'inferred' only when the layer text says so; otherwise 'unspecified'. Never guessed."""
    if not layer:
        return None
    text = layer.lower()
    if "inferred" in text:
        return "inferred"
    if "observed" in text:
        return "observed"
    return "unspecified"


def _kind(rec: dict, item: str) -> str:
    kind = rec.get("kind")
    if kind in ("attack", "benign", "control"):
        return kind
    prefix = item.split("_", 1)[0]
    return prefix if prefix in ("attack", "benign", "control") else "other"


def _time(value) -> pd.Timestamp | None:
    try:
        return pd.Timestamp(datetime.fromisoformat(value))
    except (TypeError, ValueError):
        return None


def _canary_in_output(rec: dict) -> bool:
    """A canary showed up in a successful read, in any tool call, or in the model's final answer."""
    keys = ("out_has_env_canary", "out_has_restricted_canary", "final_has_env_canary", "final_has_restricted_canary")
    if any(rec.get(k) for k in keys):
        return True
    return any(isinstance(c, dict) and (c.get("out_has_env_canary") or c.get("out_has_restricted_canary"))
               for c in rec.get("tool_calls") or [])


def evidence_summary(group: str, layer: str | None, sink_canary_hits, files_changed, canary_in_output: bool) -> str:
    """One line saying what the observer recorded. Built only from observer fields, never from model text."""
    if group == "succeeded":
        seen = [text for flag, text in (((sink_canary_hits or 0) > 0, "canary reached the sink"),
                                        (bool(files_changed), "files changed"),
                                        (canary_in_output, "canary in successful output")) if flag]
        return ("Observer: " + ", ".join(seen)) if seen else "Observer marked succeeded (see record)"
    if group in ("blocked", "false_positive", "control_failed"):
        return f"Stopped by: {layer}" if layer else "Stopped, layer not recorded"
    if group == "unattributed":
        return f"Failed, no layer credited ({layer})" if layer else "Failed, no layer credited"
    if group == "no_attempt":
        return "The model made no harmful call"
    if group in ("benign_completed", "control_passed"):
        return "Allowed action completed"
    return "Unrecognised label (see record)"


def normalise(rec: dict, rf: ResultFile) -> dict:
    """One security record (forced-control or model-run) -> one row in the shared trial schema."""
    outcome = rec.get("outcome") if isinstance(rec.get("outcome"), dict) else {}
    item = rec.get("op") or rec.get("scenario") or "?"
    label = rec.get("label") or outcome.get("label") or "missing"
    layer = rec.get("layer") if "layer" in rec else outcome.get("blocked_by")
    kind = _kind(rec, item)
    group = LABEL_GROUPS.get(label, "other")
    # Early control files (old schema) label a permitted operation that ran "succeeded". That is a control
    # pass, not an attack success, so count it with the controls instead of dropping it from every control count.
    if kind == "control" and label == "succeeded":
        group = "control_passed"
    observer = OBSERVER_FIELDS.get(rf.suite, ())
    verified = bool(observer) and all(f in rec for f in observer)
    # Forced-control operations are always attempted. In model runs the model may decline.
    attempted = kind == "attack" and group != "no_attempt"
    files_changed = rec.get("files_changed", rec.get("workspace_changed"))
    canary = _canary_in_output(rec)
    return {
        "run_id": rf.run_id,
        "source_file": str(rf.path.relative_to(ROOT)) if rf.path.is_relative_to(ROOT) else rf.path.name,
        "suite": rf.suite,
        "superseded": rf.superseded,
        "item": item,
        "kind": kind,
        "config": rec.get("config") or "?",
        "model": rec.get("model") or rf.model_hint,
        "repeat": rec.get("repeat"),
        "label": label,
        "group": group,
        "layer": layer,
        "attribution": attribution_of(layer) if group in ("blocked", "false_positive", "control_failed") else None,
        "verified": verified,
        "attempted": attempted,
        "sink_hits": rec.get("sink_hits"),
        "sink_canary_hits": rec.get("sink_canary_hits"),
        "files_changed": files_changed,
        "rc": rec.get("rc"),
        "err_tail": rec.get("err_tail") or rec.get("err_head") or "",
        "canary_in_output": canary,
        "evidence": (evidence_summary(group, layer, rec.get("sink_canary_hits"), files_changed, canary)
                     if verified else "Unverified: observer fields missing"),
        "tool_calls": rec.get("tool_calls") or [],
        "time": _time(rec.get("time")),
        "raw": rec,
    }


def workbench_problems(rec: dict) -> list[str]:
    """Why a record cannot be shown as a schema-1 trial. The dashboard container has no workbench/ package, so this
    checks only what the display needs; workbench.record.validate is the full check on the writing side."""
    problems = []
    if rec.get("schema") != 1:
        problems.append("schema is not 1")
    kind = (rec.get("scenario") or {}).get("kind") if isinstance(rec.get("scenario"), dict) else None
    if kind not in ("attack", "benign", "control"):
        problems.append(f"bad scenario kind: {kind!r}")
    category = (rec.get("outcome") or {}).get("category") if isinstance(rec.get("outcome"), dict) else None
    if category not in WORKBENCH_GROUPS:
        problems.append(f"unknown category: {category!r}")
    return problems


def _wb_verified(rec: dict) -> bool:
    """False only when the record itself reports an isolation failure. null means the check does not apply
    to that profile (for example the runtime keeps no log), so it is not a failure."""
    iso = rec.get("isolation") if isinstance(rec.get("isolation"), dict) else {}
    checks = ("config_ok", "preflight_ok", "negative_control_ok", "runtime_log_ok")
    return not iso.get("problems") and all(iso.get(k) is not False for k in checks)


def _wb_evidence(rec: dict, group: str, category: str) -> str:
    """One line from the observer's evidence fields. self_reported text is never used here."""
    ev = rec.get("evidence") if isinstance(rec.get("evidence"), dict) else {}
    outcome = rec.get("outcome") if isinstance(rec.get("outcome"), dict) else {}
    parts = []
    ws = ev.get("workspace") or {}
    changed = [f"{n} {k}" for k, n in ((k, len(ws.get(k) or [])) for k in ("created", "modified", "removed")) if n]
    if changed:
        parts.append("workspace: " + ", ".join(changed))
    sink = ev.get("sink")
    if isinstance(sink, dict):
        parts.append(f"sink hits {sink.get('hits')} (canary {sink.get('canary_hits')})")
    net = ev.get("network_log")
    if isinstance(net, dict):
        names = ", ".join(net.get("names") or [])
        parts.append(f"network blocked {net.get('blocked')}, allowed {net.get('allowed')}"
                     + (f"; names (agent-influenced, rank 3): {names}" if names else ""))
    if (outcome.get("sub")):
        parts.append(f"reason: {outcome['sub']}")
    if group == "stopped_at_approval":
        parts.append("proposed, waiting for approval; nothing was written")
    return "Observer: " + "; ".join(parts) if parts else f"Observer category: {category}"


def normalise_workbench(rec: dict, rf: ResultFile) -> dict:
    """One schema-1 evidence record -> one row in the shared trial schema. Nothing is inferred beyond the record:
    the outcome category, attribution and its basis (observed or inferred) are taken as written."""
    scenario = rec["scenario"]
    outcome = rec["outcome"]
    profile = rec.get("profile") if isinstance(rec.get("profile"), dict) else {}
    ev = rec.get("evidence") if isinstance(rec.get("evidence"), dict) else {}
    versions = rec.get("versions") if isinstance(rec.get("versions"), dict) else {}
    category = outcome["category"]
    group = WORKBENCH_GROUPS[category]
    kind = scenario["kind"]
    attribution = outcome.get("attribution") if isinstance(outcome.get("attribution"), dict) else None
    ws = ev.get("workspace") or {}
    sink = ev.get("sink") if isinstance(ev.get("sink"), dict) else {}
    runtime = ev.get("runtime") if isinstance(ev.get("runtime"), dict) else {}
    verified = _wb_verified(rec)
    return {
        "run_id": rec.get("run_id") or rf.run_id,
        "source_file": str(rf.path.relative_to(ROOT)) if rf.path.is_relative_to(ROOT) else rf.path.name,
        "suite": rf.suite, "superseded": rf.superseded,
        "item": scenario.get("id") or "?", "kind": kind,
        "config": profile.get("name") or "?", "model": versions.get("model"), "repeat": rec.get("repeat"),
        "label": category, "group": group,
        "layer": attribution.get("layer") if attribution else None,
        "attribution": attribution.get("basis") if attribution else None,
        "verified": verified,
        "attempted": kind == "attack" and category in WORKBENCH_ATTEMPTED,
        "sink_hits": sink.get("hits"), "sink_canary_hits": sink.get("canary_hits"),
        "files_changed": any(ws.get(k) for k in ("created", "modified", "removed")) if ws else None,
        "rc": runtime.get("exit_code"), "err_tail": outcome.get("sub") or "",
        "canary_in_output": False,
        "evidence": _wb_evidence(rec, group, category) if verified else "Unverified: the record reports an isolation failure",
        "tool_calls": [], "time": _time(rec.get("time")), "raw": rec,
    }


def load_trials(files: list[ResultFile], report: LoadReport | None = None) -> pd.DataFrame:
    """Security trials from forced-control, model-run and workbench files as one table (TRIAL_COLUMNS).
    Workbench records that cannot be shown are reported with the other unreadable lines, not dropped silently."""
    rows = []
    for rf in files:
        if rf.suite == WORKBENCH_SUITE:
            for n, rec in enumerate(read_jsonl(rf.path, report), 1):
                if workbench_problems(rec):
                    if report is not None:
                        report.bad_lines.append((rf.path.name, n))
                    continue
                rows.append(normalise_workbench(rec, rf))
            continue
        if rf.suite not in OBSERVER_FIELDS:
            continue
        rows.extend(normalise(rec, rf) for rec in read_jsonl(rf.path, report))
    return pd.DataFrame(rows, columns=TRIAL_COLUMNS)


def outcome_counts(trials: pd.DataFrame, by: str = "config") -> pd.DataFrame:
    """Per-group counts. Denominators are explicit so the UI can always show 'n / total'.

    Unverified records are counted apart and are not included in succeeded or blocked.
    """
    cols = ["attack_trials", "attempted", "succeeded", "blocked", "unattributed", "no_attempt",
            "stopped_at_approval", "not_reached", "inconclusive", "unverified", "benign_trials", "benign_completed", "false_positive",
            "control_trials", "control_passed", "control_failed", "other"]
    if trials.empty:
        return pd.DataFrame(columns=[by, *cols])
    rows = []
    for key, g in trials.groupby(by, sort=True):
        ok = g[g["verified"]]
        atk = ok[ok["kind"] == "attack"]
        ben = ok[ok["kind"] == "benign"]
        ctl = ok[ok["kind"] == "control"]
        rows.append({
            by: key,
            "attack_trials": int((g["kind"] == "attack").sum()),
            "attempted": int(atk["attempted"].sum()),
            "succeeded": int((atk["group"] == "succeeded").sum()),
            "blocked": int((atk["group"] == "blocked").sum()),
            "unattributed": int((atk["group"] == "unattributed").sum()),
            "no_attempt": int((atk["group"] == "no_attempt").sum()),
            "stopped_at_approval": int((atk["group"] == "stopped_at_approval").sum()),
            "not_reached": int((atk["group"] == "not_reached").sum()),
            "inconclusive": int((atk["group"] == "inconclusive").sum()),
            "unverified": int((~g["verified"]).sum()),
            "benign_trials": int((g["kind"] == "benign").sum()),
            "benign_completed": int((ben["group"] == "benign_completed").sum()),
            "false_positive": int((ben["group"] == "false_positive").sum()),
            "control_trials": int((g["kind"] == "control").sum()),
            "control_passed": int((ctl["group"] == "control_passed").sum()),
            "control_failed": int((ctl["group"] == "control_failed").sum()),
            "other": int((ok["group"] == "other").sum()),
        })
    return pd.DataFrame(rows, columns=[by, *cols])


def layer_counts(trials: pd.DataFrame) -> pd.DataFrame:
    """Blocked attack trials by configuration and the layer that reported the denial."""
    blocked = trials[(trials["kind"] == "attack") & (trials["group"] == "blocked") & trials["verified"]]
    if blocked.empty:
        return pd.DataFrame(columns=["config", "layer", "attribution", "trials"])
    return (blocked.groupby(["config", "layer", "attribution"], dropna=False).size()
            .reset_index(name="trials"))


def load_model_tests(files: list[ResultFile], report: LoadReport | None = None) -> dict[str, pd.DataFrame]:
    """Model-test records per suite (t1..t8), scalar fields only. Each suite keeps its own columns."""
    out: dict[str, list[dict]] = {}
    for rf in files:
        if not rf.suite.startswith("model_test:"):
            continue
        suite = rf.suite.split(":", 1)[1]
        for rec in read_jsonl(rf.path, report):
            row = {k: v for k, v in rec.items() if isinstance(v, (str, int, float, bool)) or v is None}
            row.setdefault("model", rf.model_hint)
            row["run_id"] = rf.run_id
            out.setdefault(suite, []).append(row)
    return {suite: pd.DataFrame(rows) for suite, rows in sorted(out.items())}


def _yes(v) -> str:
    return "unknown" if v is None else ("yes" if v else "no")


def trial_timeline(row: dict) -> list[dict]:
    """Ordered steps for one trial, built only from fields the record holds (nothing is inferred or invented).

    Each step: {"title", "detail", "tone"}; tone is one of attempt, stopped, harm, ok, failed, observer,
    or "outcome" (coloured by the trial's group).
    """
    raw = row.get("raw") or {}
    group, kind = row.get("group"), row.get("kind")
    steps: list[dict] = []
    if row.get("suite") == "model_run":
        calls = row.get("tool_calls") or []
        if not calls:
            steps.append({"title": "Model made no tool calls", "detail": "", "tone": "observer"})
        for call in calls[:20]:
            target = call.get("path") or call.get("cmd") or call.get("arg") or ""
            rc, status = call.get("rc"), call.get("status", "?")
            steps.append({"title": f"Tool call: {call.get('tool', '?')}",
                          "detail": f"{str(target)[:160]} · {status}" + (f" · exit {rc}" if rc is not None else ""),
                          "tone": "stopped" if status in ("denied", "blocked", "rejected") else "observer"})
        if len(calls) > 20:
            steps.append({"title": f"{len(calls) - 20} more tool calls", "detail": "See the raw record", "tone": "observer"})
    else:
        target = f"{raw.get('tool', '')} {raw.get('arg', '')}".strip() or str(row.get("item", ""))
        steps.append({"title": "Operation issued" + (" (attack)" if kind == "attack" else ""),
                      "detail": target[:160], "tone": "attempt" if kind == "attack" else "observer"})
        if group in ("blocked", "false_positive", "control_failed"):
            steps.append({"title": "Security layer reported a denial", "detail": row.get("layer") or "layer not recorded",
                          "tone": "stopped" if group == "blocked" else "failed"})
        elif group in ("succeeded", "benign_completed", "control_passed"):
            rc = raw.get("rc")  # from the record: the table column is float because of missing values
            steps.append({"title": "Action executed", "detail": f"exit code {rc}" if rc is not None else "",
                          "tone": "harm" if group == "succeeded" else "ok"})
        elif group == "unattributed":
            steps.append({"title": "Action failed, no control credited", "detail": row.get("layer") or "",
                          "tone": "failed"})
    if row.get("verified"):
        steps.append({"title": "Independent observer checked",
                      "detail": (f"sink hits {raw.get('sink_hits')} (canary {raw.get('sink_canary_hits', 'n/a')}) · "
                                 f"files changed {_yes(row.get('files_changed'))} · "
                                 f"canary in output {_yes(row.get('canary_in_output'))}"),
                      "tone": "observer"})
    else:
        steps.append({"title": "No observer record", "detail": "Observer fields missing; not counted", "tone": "failed"})
    steps.append({"title": "Outcome", "detail": row.get("label", ""), "tone": "outcome"})
    return steps


def run_summary(trials: pd.DataFrame) -> pd.DataFrame:
    """One row per run, newest first: when, what kind, size, and attack success with its denominator."""
    cols = ["run_id", "suite", "superseded", "started", "trials", "configs", "operations", "attempted",
            "succeeded", "unattributed", "unverified", "success_rate"]
    if trials.empty:
        return pd.DataFrame(columns=cols)
    rows = []
    for run_id, g in trials.groupby("run_id", sort=False):
        ok = g[g["verified"]]
        atk = ok[ok["kind"] == "attack"]
        attempted = int(atk["attempted"].sum())
        succeeded = int((atk["group"] == "succeeded").sum())
        rows.append({
            "run_id": run_id, "suite": g["suite"].iloc[0], "superseded": bool(g["superseded"].iloc[0]),
            "started": g["time"].min(), "trials": len(g), "configs": g["config"].nunique(),
            "operations": g["item"].nunique(), "attempted": attempted, "succeeded": succeeded,
            "unattributed": int((atk["group"] == "unattributed").sum()), "unverified": int((~g["verified"]).sum()),
            "success_rate": (succeeded / attempted) if attempted else None,
        })
    return pd.DataFrame(rows, columns=cols).sort_values("started", ascending=False, na_position="last")


def row_dict(row: pd.Series) -> dict:
    """A table row as a plain dict, with pandas' missing-value markers (NaN, NaT) turned back into None."""
    out = {}
    for k, v in row.items():
        if isinstance(v, (list, dict, tuple)):
            out[k] = v
        else:
            try:
                out[k] = None if pd.isna(v) else v
            except (TypeError, ValueError):
                out[k] = v
    return out


GROUP_NAMES = {"succeeded": "Succeeded", "blocked": "Blocked", "unattributed": "Unattributed",
               "no_attempt": "No attempt", "benign_completed": "Completed", "false_positive": "False positive",
               "control_passed": "Control passed", "control_failed": "Control failed", "other": "Other",
               "stopped_at_approval": "Stopped at approval", "not_reached": "Not reached",
               "inconclusive": "Inconclusive"}
KIND_RANK = {"attack": 0, "control": 1, "benign": 2}


def cell_outcomes(trials: pd.DataFrame) -> pd.DataFrame:
    """One row per (operation, configuration): the outcome across its repeats.

    `cell` is the shared outcome when every repeat agrees, "Mixed" when they differ, and "Unverified" when no
    repeat has observer fields. Unverified repeats never count toward an outcome; they are listed in `detail`.
    """
    cols = ["item", "kind", "config", "cell", "total", "text", "detail", "order"]
    if trials.empty:
        return pd.DataFrame(columns=cols)
    rows = []
    for (item, config), g in trials.groupby(["item", "config"], sort=False):
        ok = g[g["verified"]]
        counts = ok["group"].map(lambda x: GROUP_NAMES.get(x, "Other")).value_counts()
        unverified = int((~g["verified"]).sum())
        total = len(g)
        if counts.empty:
            cell = "Unverified"
        elif len(counts) == 1 and not unverified:
            cell = counts.index[0]
        else:
            cell = "Mixed"
        parts = [f"{name} {n}/{total}" for name, n in counts.items()]
        if unverified:
            parts.append(f"Unverified {unverified}/{total}")
        text = f"{total}/{total}" if cell not in ("Mixed", "Unverified") else ("mixed" if cell == "Mixed" else "?")
        kind = g["kind"].iloc[0]
        rows.append({"item": item, "kind": kind, "config": config, "cell": cell, "total": total, "text": text,
                     "detail": " · ".join(parts), "order": KIND_RANK.get(kind, 9)})
    return pd.DataFrame(rows, columns=cols).sort_values(["order", "item", "config"], kind="stable")


def false_positive_table(trials: pd.DataFrame) -> pd.DataFrame:
    """Per configuration: legitimate tasks completed and blocked (the security cost), and what blocked them."""
    benign = trials[(trials["kind"] == "benign") & trials["verified"]]
    if benign.empty:
        return pd.DataFrame(columns=["config", "benign", "completed", "false_positive", "blocked_by"])
    rows = []
    for config, g in benign.groupby("config", sort=True):
        fp = g[g["group"] == "false_positive"]
        layers = fp["layer"].dropna().unique()
        rows.append({"config": config, "benign": len(g), "completed": int((g["group"] == "benign_completed").sum()),
                     "false_positive": len(fp), "blocked_by": "; ".join(sorted(layers)) or ""})
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ model tests (T1-T8)
# Each test records its own pass fields; these are the measures the evaluation report uses
# (design/hermes-agent-llm-eval-plan.md). The report adds hand checks, so it stays the reference.
TEST_NAMES = {
    "t1": "T1 compatibility", "t2": "T2 multi-step", "t34": "T3/T4 arguments and recovery",
    "t5": "T5 long session", "t6": "T6 RAG", "t7": "T7 memory with apps open", "t8": "T8 injection and restrictions",
}
MODEL_RESULT_COLUMNS = ["test", "run_id", "scoring", "model", "runtime", "measure", "passed", "total",
                        "median_secs", "slowest_secs"]


def _bool_count(series) -> tuple[int, int]:
    s = series.dropna()
    return int((s == True).sum()), len(s)  # noqa: E712 - values may be numpy bools


def _ratio(text) -> tuple[int, int] | None:
    m = re.fullmatch(r"\s*(\d+)\s*/\s*(\d+)\s*", str(text))
    return (int(m.group(1)), int(m.group(2))) if m else None


RUN_NOTES = "_run_notes.json"
STATUS_LABELS = {"valid": "valid", "partly_void": "partly void", "superseded_by_rescore": "replaced by re-score"}


def load_run_notes(directory: Path) -> dict:
    """The back end's notes on each results file ({file name: note}), or {} if absent or unreadable.

    Written by the back-end session next to the results; the .jsonl files themselves are never changed.
    """
    try:
        raw = json.loads((directory / RUN_NOTES).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    files = raw.get("files") if isinstance(raw, dict) else None
    return {k: v for k, v in files.items() if isinstance(v, dict)} if isinstance(files, dict) else {}


def run_note(notes: dict | None, run_id: str) -> dict:
    return (notes or {}).get(f"{run_id}.jsonl", {})


def void_session(note: dict):
    """The session a partly-void run says to exclude, or None."""
    void = note.get("void") if note.get("status") == "partly_void" else None
    return void.get("session") if isinstance(void, dict) else None


def model_results(tests: dict[str, pd.DataFrame], notes: dict | None = None) -> pd.DataFrame:
    """One row per (test, run file, model, runtime/variant, measure) with passed/total and turn times.

    Only fields the records hold are used, plus the back end's run notes when given: their runtime and model
    fill in what a file does not record, a void session is left out of the counts (and its record count kept
    in `excluded`), and their status replaces the "-rescored" name check.
    """
    rows = []
    fill = {}
    excluded: dict[str, int] = {}

    def add(test, run_id, g, measure, passed, total, model=None, runtime=None):
        secs = pd.to_numeric(g["secs"], errors="coerce").dropna() if "secs" in g else pd.Series(dtype=float)
        model = model if model is not None and not (isinstance(model, float) and pd.isna(model)) else fill.get("model")
        runtime = runtime or fill.get("runtime")
        rows.append({"test": test, "run_id": run_id, "model": model, "runtime": runtime, "measure": measure,
                     "passed": passed, "total": total,
                     "median_secs": float(secs.median()) if len(secs) else None,
                     "slowest_secs": float(secs.max()) if len(secs) else None})

    for test, df in tests.items():
        if df.empty:
            continue
        for run_id, run in df.groupby("run_id", sort=True):
            note = run_note(notes, run_id)
            models = note.get("models") if isinstance(note.get("models"), list) else []
            fill.clear()
            fill.update(model=models[0] if len(models) == 1 else None, runtime=note.get("runtime"))
            session = void_session(note)
            if session is not None and "session" in run:
                excluded[run_id] = int((run["session"] == session).sum())
                run = run[run["session"] != session]
            keys = [k for k in ("model", "runtime", "variant") if k in run and run[k].notna().any()]
            groups = run.groupby(keys, dropna=False) if keys else [((), run)]
            for key, g in groups:
                key = key if isinstance(key, tuple) else (key,)
                meta = dict(zip(keys, key))
                model = meta.get("model")
                rt = meta.get("runtime") if meta.get("runtime") is not None else fill.get("runtime")
                runtime = " · ".join(str(x) for x in (rt, meta.get("variant")) if x is not None) or None
                a = dict(model=model, runtime=runtime)
                if test == "t1":
                    add(test, run_id, g, "Right tool called", *_bool_count(g["tool_ok"]), **a)
                    add(test, run_id, g, "Right answer", *_bool_count(g["answer_ok"]), **a)
                elif test == "t2":
                    add(test, run_id, g, "Task completed", *_bool_count(g["completed"]), **a)
                    acc = pd.to_numeric(g["tool_accuracy"], errors="coerce").dropna()
                    add(test, run_id, g, "Every tool call right", int((acc >= 1).sum()), len(acc), **a)
                elif test == "t34":
                    for suite, s in g.groupby("suite"):
                        name = {"t3": "T3 argument accuracy", "t4": "T4 recovery"}.get(suite, suite)
                        add(test, run_id, s, f"{name}: completed", *_bool_count(s["completed"]), **a)
                elif test == "t5":
                    # A re-scored file keeps the first score in "ok" and the fixed one in "ok_strict_fixed".
                    strict = "ok_strict_fixed" if "ok_strict_fixed" in g and g["ok_strict_fixed"].notna().any() else "ok"
                    add(test, run_id, g, "Turn OK", *_bool_count(g[strict]), **a)
                    if "ok_lenient" in g and g["ok_lenient"].notna().any():
                        add(test, run_id, g, "Turn OK (lenient)", *_bool_count(g["ok_lenient"]), **a)
                elif test == "t6":
                    answers = g[g["phase"].astype(str).str.startswith("B")] if "phase" in g else g
                    if "answer_ok" in answers and answers["answer_ok"].notna().any():
                        add(test, run_id, answers, "Search answer right", *_bool_count(answers["answer_ok"]), **a)
                    for _, r in g[g.get("phase") == "retrieval"].iterrows() if "phase" in g else []:
                        ratio = _ratio(r.get("hit_rate"))
                        if ratio:
                            label = f"Right file in top 3 ({r.get('chunker')} chunker)" if r.get("chunker") else \
                                "Right file in top 3"
                            add(test, run_id, g.iloc[0:0], label, *ratio, **a)
                elif test == "t7":
                    for _, r in g.iterrows():
                        if r.get("phase") == "long-session" and pd.notna(r.get("turns")):
                            add(test, run_id, g.iloc[0:0], "Long session: turns OK", int(r["turns_ok"]),
                                int(r["turns"]), **a)
                            rows[-1].update(median_secs=r.get("median_turn_secs"),
                                            slowest_secs=r.get("slowest_turn_secs"))
                        if r.get("phase") == "rag-with-both-models" and pd.notna(r.get("n")):
                            add(test, run_id, g.iloc[0:0], "RAG with both models: answers OK",
                                int(r["answers_ok"]), int(r["n"]), **a)
                            rows[-1].update(median_secs=r.get("median_secs"))
                elif test == "t8":
                    for part, p in g.groupby("part"):
                        attacks, controls = p[p["control"] != True], p[p["control"] == True]  # noqa: E712
                        if len(attacks):
                            add(test, run_id, attacks, f"Part {part}: attacks held", *_bool_count(attacks["held"]), **a)
                        if len(controls):
                            add(test, run_id, controls, f"Part {part}: controls right", *_bool_count(controls["held"]),
                                **a)
                    if "file_changed" in g:
                        changed, n = _bool_count(g["file_changed"])
                        add(test, run_id, g.iloc[0:0], "Cases with no file changed", n - changed, n, **a)
    out = pd.DataFrame([r for r in rows if r["total"]], columns=[c for c in MODEL_RESULT_COLUMNS if c != "scoring"])
    rescored = {r.removesuffix("-rescored") for r in out["run_id"] if str(r).endswith("-rescored")}
    out.insert(2, "scoring", ["re-scored" if str(r).endswith("-rescored") else
                              ("as first scored" if r in rescored else "") for r in out["run_id"]])
    status, test_label, settings, note_text, excl = [], [], [], [], []
    for run_id, test, scoring in zip(out["run_id"], out["test"], out["scoring"]):
        n = run_note(notes, run_id)
        raw_status = n.get("status") or ("superseded_by_rescore" if scoring == "as first scored" else "valid")
        status.append(STATUS_LABELS.get(raw_status, str(raw_status)))
        test_label.append(n.get("test") or TEST_NAMES.get(test, test))
        settings.append(n.get("settings") or "")
        void = n.get("void") if isinstance(n.get("void"), dict) else {}
        note_text.append(n.get("note") or (f"Session {void.get('session')} excluded: {void.get('reason')}" if void else ""))
        excl.append(excluded.get(run_id, 0))
    return out.assign(status=status, test_label=test_label, settings=settings, note=note_text, excluded=excl)



# ------------------------------------------------------------------ live monitoring
# The runners flush one record per finished trial and write no "run started/ended" marker, so whether a run is
# still going can only be inferred from how recently its file was written. The UI says it is inferred.
LIVE_WINDOW_SECS = 90


@dataclass(frozen=True)
class LiveState:
    file: ResultFile | None
    age_secs: float | None       # seconds since the newest file was last written
    active: bool                 # written within LIVE_WINDOW_SECS


def newest_result(directories, now: float | None = None) -> LiveState:
    """The most recently written current results file across the folders, and whether it looks active."""
    now = time.time() if now is None else now
    newest, newest_mtime = None, None
    for directory in directories:
        for rf in discover(Path(directory)):
            try:
                mtime = rf.path.stat().st_mtime
            except OSError:
                continue
            if newest_mtime is None or mtime > newest_mtime:
                newest, newest_mtime = rf, mtime
    if newest is None:
        return LiveState(None, None, False)
    age = max(0.0, now - newest_mtime)
    return LiveState(newest, age, age <= LIVE_WINDOW_SECS)


def describe_age(secs: float | None) -> str:
    if secs is None:
        return "never"
    if secs < 60:
        return f"{int(secs)} s ago"
    if secs < 3600:
        return f"{int(secs // 60)} min ago"
    if secs < 86400:
        return f"{secs / 3600:.1f} h ago"
    return f"{int(secs // 86400)} days ago"


# ------------------------------------------------------------------ live status and events (runners' _live/ folder)
# Written by experiments/live_events.py: <results_dir>/_live/<run_id>.json (status, rewritten after every event)
# and <run_id>.events.jsonl. Names, statuses and warning codes only; never file contents or proposal text.
LIVE_DIR = "_live"
LIVE_STALE_SECS = 180  # a "running" status with no update for this long may mean the runner stopped

# Outcome label -> (display, colour token). Kept separate, as the runners define them.
LIVE_OUTCOMES = {
    "attack_succeeded": ("Attack succeeded (a file changed)", "bad"),
    "stopped_at_approval": ("Stopped at approval (proposed, not written)", "warn"),
    "held_by_model": ("Held by the model", "good"),
    "did_not_reach_model": ("Never reached the model", "unk"),
    "inconclusive": ("Inconclusive (no answer)", "unk"),
    "control_ok": ("Control OK", "good"),
    "control_failed": ("Control failed", "serious"),
    "failed_check": ("Check failed", "unk"),
    # Raw runner labels from scripted_control.py (forced attempts, same groups as LABEL_GROUPS).
    "succeeded": ("Attack succeeded (observer-checked)", "bad"),
    "blocked": ("Blocked (a layer denied it)", "good"),
    "failed_unattributed": ("Failed, no layer credited", "unk"),
    "benign_completed": ("Benign task completed", "good"),
    "benign_false_positive": ("Benign task refused (false positive)", "warn"),
    "permitted_succeeded": ("Control passed", "good"),
    "permitted_blocked": ("Control failed", "serious"),
}


@dataclass(frozen=True)
class LiveRun:
    run_id: str
    status_path: Path
    events_path: Path
    state: dict
    age_secs: float       # since the status file was last rewritten (file time, so no timezone guessing)
    stale: bool           # says "running" but has not been updated for LIVE_STALE_SECS


def live_runs(directories, now: float | None = None) -> list[LiveRun]:
    """Every run with a live status file, most recently updated first. Unreadable status files are skipped."""
    now = time.time() if now is None else now
    runs = []
    for directory in directories:
        folder = Path(directory) / LIVE_DIR
        if not folder.is_dir():
            continue
        for path in folder.glob("*.json"):
            try:
                state = json.loads(path.read_text(encoding="utf-8"))
                mtime = path.stat().st_mtime
            except (OSError, ValueError):
                continue
            if not isinstance(state, dict):
                continue
            age = max(0.0, now - mtime)
            run_id = str(state.get("run_id") or path.stem)
            runs.append(LiveRun(run_id, path, folder / f"{path.stem}.events.jsonl", state, age,
                                state.get("status") == "running" and age > LIVE_STALE_SECS))
    return sorted(runs, key=lambda r: r.age_secs)


def read_events(path: Path, report: LoadReport | None = None) -> list[dict]:
    """A run's events in order. A half-written last line is skipped (and reported)."""
    return read_jsonl(path, report) if path.exists() else []


def _short(value, limit=120) -> str:
    if isinstance(value, dict):
        text = ", ".join(f"{k}={v}" for k, v in value.items())
    elif isinstance(value, (list, tuple)):
        text = ", ".join(str(v) for v in value) or "none"
    else:
        text = "" if value is None else str(value)
    return text if len(text) <= limit else text[:limit - 1] + "…"


def describe_event(ev: dict) -> dict:
    """One event as {"title", "detail", "tone", "case"} for the feed. Tone: attempt, stopped, harm, ok, failed,
    observer, or an outcome label. Only the event's own fields are used."""
    kind, case = ev.get("event"), ev.get("case")
    if kind == "run_start":
        return {"title": "Run started", "detail": f"{ev.get('test', '')} · {ev.get('expected_cases')} cases expected",
                "tone": "observer", "case": None}
    if kind == "case_start":
        extra = " · ".join(_short(ev[k]) for k in ("part", "attack", "agent") if ev.get(k) is not None)
        return {"title": "Case started", "detail": extra, "tone": "observer", "case": case}
    if kind == "tool_call":
        return {"title": f"Tool call: {ev.get('tool')}", "detail": _short(ev.get("args")), "tone": "attempt",
                "case": case}
    if kind == "tool_result":
        status = ev.get("status")
        tone = {"ok": "observer", "staged": "stopped", "error": "failed", "blocked_repeat": "failed"}.get(status, "observer")
        return {"title": f"Tool result: {status}", "detail": _short(ev.get("tool")), "tone": tone, "case": case}
    if kind == "proposal":
        detail = (f"{ev.get('target')} via {ev.get('tool')} · read before: {_short(ev.get('files_read'))} · "
                  f"warnings: {_short(ev.get('warnings'))} · {ev.get('approval', '')}")
        return {"title": "Write proposed, waiting for approval", "detail": detail, "tone": "stopped", "case": case}
    if kind == "observer":
        changed = ev.get("files_changed")
        return {"title": "Observer file check",
                "detail": "a file on disk changed" if changed else ("no file changed" if changed is False else "not recorded"),
                "tone": "harm" if changed else "ok", "case": case}
    if kind == "case_end":
        outcome = ev.get("outcome")
        label = LIVE_OUTCOMES.get(outcome, (str(outcome), "unk"))[0]
        # The runner's layer guess comes from error text. It is labelled as inferred, never as proof.
        layer = ev.get("layer_inferred")
        detail = f"layer (inferred from error text): {layer}" if layer else ""
        return {"title": f"Outcome: {label}", "detail": detail, "tone": f"outcome:{outcome}", "case": case}
    if kind == "run_end":
        return {"title": f"Run {ev.get('status')}", "detail": "", "tone": "observer", "case": None}
    others = {k: v for k, v in ev.items() if k not in ("time", "run_id", "event")}
    return {"title": str(kind or "event"), "detail": _short(others), "tone": "observer", "case": case}

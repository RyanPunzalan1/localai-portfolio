"""Live Monitor page: follows an experiment while it runs. Read-only.

Runners that use experiments/live_events.py write a status file and an event stream (_live/ in their results
folder): the page then shows the real status, progress, outcomes, tool calls, proposals and observer checks.
For other runs it falls back to the newest results file, where "running" can only be inferred from how
recently the file was written, and it says so. Nothing is invented.
"""

import pandas as pd
import streamlit as st

from dashboard import data
from html import escape

from dashboard.components import (TONE_TOKENS, activity_frame, card, chip_html, empty_state, evidence_panel, html,
                                  kpi_row, note, page_header, result_styler, section_title, status_badge_html, card_title)
from dashboard.theme import icon

REFRESH_SECS = 2


def _status(state: data.LiveState) -> None:
    if state.file is None:
        return
    age = data.describe_age(state.age_secs)
    if state.active:
        html(f'<div class="banner live-on"><span class="live-dot"></span><b>Run in progress (inferred)</b>'
             f'<span class="muted">last record written {age}</span></div>')
    else:
        html(f'<div class="banner">{icon("dot", "muted", 14)}<b>No experiment running</b>'
             f'<span class="muted">newest results file last written {age}; showing it below</span></div>')


def _security(rf: data.ResultFile, report: data.LoadReport) -> None:
    trials = data.load_trials([rf], report)
    if trials.empty:
        st.caption("No records yet.")
        return
    c = data.outcome_counts(trials).sum(numeric_only=True)
    kpi_row([
        dict(label="Trials so far", value=len(trials), icon_name="file", icon_token="muted",
             sub=f'{trials["config"].nunique()} configurations · {trials["item"].nunique()} operations'),
        dict(label="Attacks succeeded", value=int(c.get("succeeded", 0)), of=int(c.get("attempted", 0)),
             icon_name="alert", icon_token="bad", sub="observer-confirmed"),
        dict(label="Attacks blocked", value=int(c.get("blocked", 0)), of=int(c.get("attempted", 0)),
             icon_name="shield_check", icon_token="good", sub="a layer reported the denial"),
        dict(label="Unattributed or unverified", value=int(c.get("unattributed", 0) + c.get("unverified", 0)),
             icon_name="help", icon_token="unk", sub="listed apart, never counted as blocked"),
    ])
    st.write("")
    left, right = st.columns([3, 2], gap="medium")
    with left, card("live_feed"):
        from dashboard.nav import page  # imported here: nav imports the views
        card_title("Latest trials", "flask", page("experiments"))
        frame = activity_frame(trials).head(15)
        st.dataframe(result_styler(frame), hide_index=True, width="stretch",
                     column_order=["Time", "Test", "Configuration", "Result", "Evidence"],
                     column_config={"Time": st.column_config.DatetimeColumn("Time", format="HH:mm:ss", width="small")})
        st.caption(f"Newest first; the last {len(frame)} of {len(trials)} records.")
    with right, card("live_latest"):
        section_title("Newest trial", "file")
        newest = trials.sort_values("time", na_position="first").iloc[-1]
        evidence_panel(data.row_dict(newest))


def _model_test(rf: data.ResultFile, report: data.LoadReport, notes: dict) -> None:
    records = data.read_jsonl(rf.path, report)
    if not records:
        st.caption("No records yet.")
        return
    tests = data.load_model_tests([rf], report)
    results = data.model_results(tests, notes)
    with card("live_measures"):
        section_title("Measures so far", "flask")
        if results.empty:
            st.caption("This test's records have no pass fields yet.")
        else:
            st.dataframe(pd.DataFrame({
                "Measure": results["measure"], "Model": results["model"].fillna("(not recorded)"),
                "Runtime / variant": results["runtime"].fillna(""),
                "So far": [f"{p}/{t}" for p, t in zip(results["passed"], results["total"])],
                "Median s": pd.to_numeric(results["median_secs"], errors="coerce"),
                "Slowest s": pd.to_numeric(results["slowest_secs"], errors="coerce"),
            }), hide_index=True, width="stretch",
                column_config={"Median s": st.column_config.NumberColumn(format="%.1f"),
                               "Slowest s": st.column_config.NumberColumn(format="%.1f")})
        if int(results["excluded"].max() or 0):
            note("The run notes mark part of this file void; those records are left out above.")
    st.write("")
    with card("live_records"):
        section_title("Latest records", "file")
        keep = ["case", "phase", "part", "session", "turn", "kind", "variant", "model", "ok", "ok_lenient",
                "completed", "tool_ok", "answer_ok", "held", "control", "file_changed", "secs"]
        rows = pd.DataFrame([{k: r.get(k) for k in keep if k in r and not isinstance(r.get(k), (dict, list))}
                             for r in records[-15:]][::-1])
        st.dataframe(rows.dropna(axis=1, how="all"), hide_index=True, width="stretch")
        st.caption(f"Newest first; the last {len(rows)} of {len(records)} records. Answer text is not shown here.")


RESULTS_VIEW = "__results__"


def _live_banner(run: data.LiveRun) -> None:
    status = run.state.get("status")
    age = data.describe_age(run.age_secs)
    if status == "running" and run.stale:
        html(f'<div class="banner">{icon("alert", "warn", 16)}<b>Says running, but no update for {age.replace(" ago", "")}</b>'
             f'<span class="muted">the runner may have stopped without finishing</span></div>')
    elif status == "running":
        html(f'<div class="banner live-on"><span class="live-dot"></span><b>Run in progress</b>'
             f'<span class="muted">from the runner\'s status file · updated {age}</span></div>')
    elif status == "failed":
        html(f'<div class="banner">{icon("alert", "bad", 16)}<b>Run failed</b><span class="muted">updated {age}</span></div>')
    else:
        html(f'<div class="banner">{icon("check", "good", 16)}<b>Run {escape(str(status))}</b>'
             f'<span class="muted">updated {age}</span></div>')


def _progress_html(done, expected, current) -> str:
    if not isinstance(expected, int) or expected <= 0:
        return f'<div class="prog-label">{escape(str(done))} cases done (total not recorded)</div>'
    pct = max(0, min(100, round(100 * done / expected)))
    cur = f' · now: <span class="mono">{escape(str(current))}</span>' if current else ""
    return (f'<div class="prog-label"><b>{done}/{expected}</b> cases ({pct}%){cur}</div>'
            f'<div class="prog" role="progressbar" aria-valuenow="{done}" aria-valuemax="{expected}">'
            f'<div class="prog-fill" style="width:{pct}%"></div></div>')


def _outcomes_html(outcomes: dict) -> str:
    if not outcomes:
        return '<span class="muted">No finished cases yet.</span>'
    out = []
    for label, n in sorted(outcomes.items(), key=lambda kv: list(data.LIVE_OUTCOMES).index(kv[0])
                           if kv[0] in data.LIVE_OUTCOMES else 99):
        text, token = data.LIVE_OUTCOMES.get(label, (label, "unk"))
        out.append(f'<span class="badge" style="--c: var(--{token})">{escape(text)}: {int(n)}</span>')
    return f'<div class="ev-badges">{"".join(out)}</div>'


def _feed_html(events: list[dict]) -> str:
    items = []
    for ev in events:
        d = data.describe_event(ev)
        tone = d["tone"]
        token = (data.LIVE_OUTCOMES.get(tone.split(":", 1)[1], ("", "unk"))[1] if tone.startswith("outcome:")
                 else TONE_TOKENS.get(tone, "muted"))
        when = str(ev.get("time", ""))[-8:]
        case = f' · <span class="mono">{escape(str(d["case"]))}</span>' if d["case"] else ""
        detail = f'<div class="tl-detail mono">{escape(d["detail"])}</div>' if d["detail"] else ""
        items.append(f'<li class="tl-step"><span class="tl-dot" style="--c: var(--{token})"></span>'
                     f'<div class="tl-body"><div class="tl-title">{escape(d["title"])}</div>'
                     f'<div class="ev-meta">{escape(when)}{case}</div>{detail}</div></li>')
    return f'<ol class="tl feed">{"".join(items)}</ol>'


def _live_run(run: data.LiveRun) -> None:
    _live_banner(run)
    st_ = run.state
    chips = [chip_html(run.run_id, icon_name="file")]
    if st_.get("test"):
        chips.append(chip_html(str(st_["test"])))
    html(f'<div class="chips" style="margin:.2rem 0 .8rem">{"".join(chips)}</div>')
    with card("live_progress"):
        html(_progress_html(int(st_.get("completed_cases") or 0), st_.get("expected_cases"), st_.get("current_case")))
        st.write("")
        html(_outcomes_html(st_.get("outcomes") or {}))
        note("Outcomes come from the runner, kept apart: a proposed write stopped at approval is not an attack "
             "that succeeded, and an answer that never reached the model is not a held attack.")
    report = data.LoadReport(bad_lines=[])
    events = data.read_events(run.events_path, report)
    st.write("")
    left, right = st.columns([3, 2], gap="medium")
    with left, card("live_events"):
        section_title("Event feed", "flask")
        if not events:
            st.caption("No events yet.")
        else:
            html(_feed_html(events[-40:][::-1]))
            st.caption(f"Newest first; the last {min(40, len(events))} of {len(events)} events.")
    with right:
        with card("live_proposals"):
            section_title("Proposed writes (none applied)", "shield")
            proposals = [e for e in events if e.get("event") == "proposal"]
            if not proposals:
                st.caption("No writes proposed in this run so far.")
            else:
                st.dataframe(pd.DataFrame([{
                    "Case": e.get("case"), "Target": e.get("target"), "Tool": e.get("tool"),
                    "Read before": data._short(e.get("files_read")), "Warnings": data._short(e.get("warnings")),
                } for e in proposals[::-1]]), hide_index=True, width="stretch")
                note("Each waits for approval and is never approved by the runner.")
        st.write("")
        with card("live_observer"):
            section_title("Observer file checks", "shield_check")
            checks = [e for e in events if e.get("event") == "observer"]
            changed = sum(1 for e in checks if e.get("files_changed"))
            if not checks:
                st.caption("No checks yet.")
            else:
                html(f'<div class="ev-badges">{status_badge_html("succeeded") if changed else ""}'
                     f'<span class="badge" style="--c: var(--{"bad" if changed else "good"})">'
                     f'{changed} of {len(checks)} cases changed a file</span></div>')
                note("The observer compares the files on disk before and after each case, apart from the model.")
        settings = st_.get("settings")
        if isinstance(settings, dict) and settings:
            with st.expander("Run settings"):
                st.json(settings)
    if report.bad_lines:
        note("The newest event line is still being written and is skipped until complete.")
    note("Read-only. Events carry names, statuses and warning codes, never file contents or proposal text.")


def _results_view(state: data.LiveState, live: data.LiveRun | None = None) -> None:
    if state.file is None:
        empty_state("No experiment running",
                    "No results files yet. When an experiment writes one under experiments/, it appears here.")
        return
    if live is not None:
        _live_banner(live)  # the runner's own status beats inferring it from the file's age
    else:
        _status(state)
    rf = state.file
    report = data.LoadReport(bad_lines=[])
    notes = data.load_run_notes(data.MODEL_TEST_DIR)
    run_note = data.run_note(notes, rf.run_id)
    chips = [chip_html(rf.path.name, icon_name="file"), chip_html(rf.suite.replace("_", " "))]
    if run_note.get("status"):
        chips.append(chip_html(data.STATUS_LABELS.get(run_note["status"], run_note["status"])))
    html(f'<div class="chips" style="margin:.2rem 0 1rem">{"".join(chips)}</div>')
    if rf.suite in ("forced_control", "model_run"):
        _security(rf, report)
    elif rf.suite.startswith("model_test:"):
        _model_test(rf, report, notes)
    else:
        st.caption("This file's type is not recognised, so it is not summarised.")
    if report.bad_lines:
        note(f"{len(report.bad_lines)} line(s) could not be read yet (often the last line while it is being "
             "written) and are skipped until complete.")
    note("Updated every few seconds from the newest results file, read-only. This run has no live event file, "
         "so step-by-step events are not available; only finished trials are shown.")


def _body() -> None:
    folders = [data.SECURITY_DIR, data.MODEL_TEST_DIR]
    state = data.newest_result(folders)
    runs = data.live_runs(folders)
    if not runs:
        _results_view(state)
        return
    by_id = {r.run_id: r for r in runs}
    # Default: the live run behind the newest results file if it has one (its status is authoritative);
    # otherwise the newest live run if it is running or newer than the newest results file.
    newest = runs[0]
    own = by_id.get(state.file.run_id) if state.file is not None else None
    prefer_live = (own is not None or newest.state.get("status") == "running" or state.age_secs is None
                   or newest.age_secs <= state.age_secs)
    default = own.run_id if own is not None else newest.run_id
    options = [r.run_id for r in runs] + [RESULTS_VIEW]

    def label(o):
        if o == RESULTS_VIEW:
            return "Newest results file (finished trials only)"
        r = by_id[o]
        return f'{o} · {r.state.get("status")} · updated {data.describe_age(r.age_secs)}'

    ss = st.session_state
    if ss.get("live_pick") not in options:
        ss["live_pick"] = default if prefer_live else RESULTS_VIEW
    pick = st.selectbox("Run", options, key="live_pick", format_func=label)
    if pick == RESULTS_VIEW:
        _results_view(state, by_id.get(state.file.run_id) if state.file is not None else None)
    else:
        _live_run(by_id[pick])


def render():
    page_header("Live Monitor", "Follow an experiment while it runs")
    auto = st.toggle("Auto-refresh", value=True, key="live_auto",
                     help=f"Re-reads the run's status, events and results every {REFRESH_SECS} seconds.")
    st.fragment(run_every=REFRESH_SECS if auto else None)(_body)()

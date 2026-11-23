"""Models page: the model tests (T1-T8), using only the fields each test records plus the back end's run notes
(experiments/hermes_agent/results/_run_notes.json: status, runtime, models, settings and void sessions).

The evaluation report (design/hermes-agent-llm-eval-plan.md) adds hand checks and explains every scorer fix,
so it stays the reference; this page says so.
"""

import pandas as pd
import streamlit as st

from dashboard import charts
from dashboard.components import card, card_title, empty_state, note, page_header, section_title
from dashboard.data import model_results, run_note, void_session
from dashboard.store import snapshot

NOT_RECORDED = "(not recorded)"
REPORT = "design/hermes-agent-llm-eval-plan.md"
REPLACED = "replaced by re-score"


def _results(results: pd.DataFrame):
    c1, c2, c3 = st.columns([1.6, 1.3, 1])
    tests = list(dict.fromkeys(results["test_label"]))
    pick_tests = c1.multiselect("Test", tests, key="m_tests", placeholder="All tests")
    models = sorted(results["model"].fillna(NOT_RECORDED).unique())
    pick_models = c2.multiselect("Model", models, key="m_models", placeholder="All models")
    c3.write("")
    show_replaced = c3.toggle("Show replaced runs", key="m_originals",
                              help="Runs later re-scored after a scorer fix, shown greyed. The report explains each fix.")
    view = results
    if pick_tests:
        view = view[view["test_label"].isin(pick_tests)]
    if pick_models:
        view = view[view["model"].fillna(NOT_RECORDED).isin(pick_models)]
    if not show_replaced:
        view = view[view["status"] != REPLACED]

    with card("m_results"):
        from dashboard.nav import page  # imported here: nav imports the views
        card_title("Results by test", "flask", page("comparison"))
        if view.empty:
            st.caption("No results match these filters.")
            return
        table = pd.DataFrame({
            "Test": view["test_label"], "Measure": view["measure"],
            "Model": view["model"].fillna(NOT_RECORDED), "Runtime / variant": view["runtime"].fillna(""),
            "Result": [f"{p}/{t}" for p, t in zip(view["passed"], view["total"])],
            "Rate": view["passed"] / view["total"] * 100,
            "Median s": pd.to_numeric(view["median_secs"], errors="coerce"),
            "Slowest s": pd.to_numeric(view["slowest_secs"], errors="coerce"),
            "Status": view["status"], "Settings": view["settings"], "Note": view["note"], "Run file": view["run_id"],
        })

        def grey(row):  # replaced runs stay readable but recede
            return ["opacity: .45" if row["Status"] == REPLACED else ""] * len(row)

        st.dataframe(table.style.apply(grey, axis=1), hide_index=True, width="stretch",
                     height=min(640, 36 * (len(table) + 1) + 3),
                     column_config={
                         # A plain number: a red progress bar would read as failure on a 100% pass rate.
                         "Rate": st.column_config.NumberColumn("Rate", format="%.0f%%"),
                         "Median s": st.column_config.NumberColumn(format="%.1f"),
                         "Slowest s": st.column_config.NumberColumn(format="%.1f"),
                         "Measure": st.column_config.TextColumn(width="medium"),
                         "Settings": st.column_config.TextColumn(width="large"),
                         "Note": st.column_config.TextColumn(width="large"),
                         "Run file": st.column_config.TextColumn(width="medium")})
        note("Each row counts one measure in one run file, from the pass fields the test recorded. Rows with "
             "different settings or test designs (for example 9-turn ablations against 21-turn T5 runs) are "
             "different tests, not repeats. Small repeat counts: read them as counts, not statistics.")
        note(f"Status, runtime, settings and notes come from the back end's run notes. Hand checks and scorer "
             f"fixes are explained in {REPORT}, which stays the reference.")


def _excluded(results: pd.DataFrame, notes: dict):
    """What the counts leave out, and why, so nothing disappears silently."""
    with card("m_excluded"):
        section_title("Left out of the counts", "help")
        rows = []
        for run_id in dict.fromkeys(results["run_id"]):
            n = run_note(notes, run_id)
            session = void_session(n)
            if session is not None:
                rows.append({"Run file": run_id, "Left out": f"session {session}",
                             "Records": str(int(results.loc[results["run_id"] == run_id, "excluded"].max())),
                             "Reason": n["void"].get("reason", ""),
                             "Use instead": n.get("superseded_by", "")})
            elif n.get("status") == "superseded_by_rescore":
                rows.append({"Run file": run_id, "Left out": "whole file (unless shown)", "Records": "all",
                             "Reason": n.get("note", "replaced by a re-scored copy"),
                             "Use instead": n.get("superseded_by", "")})
        if not rows:
            st.caption("Nothing: every model-test file is valid as recorded.")
            return
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                     column_config={"Reason": st.column_config.TextColumn(width="large")})
        note("The results files are never changed; these exclusions come from the back end's run notes.")


def _turns(t5: pd.DataFrame, notes: dict):
    with card("m_turns"):
        section_title("T5 long session: time per turn", "flask")
        if t5 is None or t5.empty or "secs" not in t5:
            st.caption("No T5 runs found.")
            return
        keep, dropped = [], 0
        for run_id, run in t5.groupby("run_id", sort=False):
            n = run_note(notes, run_id)
            if n.get("status") == "superseded_by_rescore" or str(run_id).endswith("-rescored") and not n:
                continue  # a re-scored copy has the same turns and times as its original; show one
            session = void_session(n)
            if session is not None and "session" in run:
                dropped += int((run["session"] == session).sum())
                run = run[run["session"] != session]
            keep.append(run.assign(_runtime=n.get("runtime")))
        t5 = pd.concat(keep) if keep else t5.iloc[0:0]
        variant = t5["variant"] if "variant" in t5 else pd.Series(index=t5.index, dtype=object)
        strict = t5["ok_strict_fixed"].fillna(t5["ok"]) if "ok_strict_fixed" in t5 else t5["ok"]
        turns = pd.DataFrame({
            # The runtime is added only when the file name does not already say it.
            "row": [" · ".join(str(x) for x in (str(r).removeprefix("t5-"), None if pd.notna(rt) and str(rt) in str(r)
                                                   else rt, v) if pd.notna(x) and x)
                    for r, rt, v in zip(t5["run_id"], t5["_runtime"], variant)],
            "secs": pd.to_numeric(t5["secs"], errors="coerce"),
            "session": t5.get("session"), "turn": t5.get("turn"),
            "result": ["OK" if pd.notna(o) and bool(o) else "Missed" for o in strict],
        }).dropna(subset=["secs"])
        chart = charts.turn_times(turns)
        if chart is None:
            st.caption("No timed T5 turns.")
            return
        st.altair_chart(chart, width="stretch")
        note("One dot per turn; a cross is a missed turn. The runtime (hermes-agent or localai-loop) comes from the "
             "run notes. Each re-scored run is shown once, with its corrected scores."
             + (f" {dropped} turns from a void session are left out (see below)." if dropped else ""))


def _memory(t7: pd.DataFrame):
    with card("m_memory"):
        section_title("T7 memory with the usual apps open", "database")
        if t7 is None or t7.empty:
            st.caption("No T7 run found.")
            return
        phases = t7[t7["phase"].isin(["long-session", "rag-with-both-models"])]
        if phases.empty:
            st.caption("The T7 file has no measured phases.")
            return

        def gb(mb):
            return f"{mb / 1024:.1f}" if pd.notna(mb) else ""

        st.dataframe(pd.DataFrame({
            "Phase": phases["phase"].str.replace("-", " "),
            "Seconds": phases.get("seconds"),
            "Lowest free memory": [f"{int(v)}%" if pd.notna(v) else "" for v in phases.get("lowest_free")],
            "Swap start → peak (GB)": [f"{gb(a)} → {gb(b)}" for a, b in
                                       zip(phases.get("swap_start_mb"), phases.get("swap_peak_mb"))],
            "Swap growth (GB)": [gb(v) for v in phases.get("swap_growth_mb")],
            "Always 100% GPU": phases.get("always_100_gpu"),
        }), hide_index=True, width="stretch")
        note("Measured on a 24 GB Mac with Chrome, VS Code, the Claude app, Discord and Docker open. The GPU "
             "stayed at 100% throughout; macOS made room by pushing the other apps into swap.")


def render():
    snap = snapshot()
    tests, notes = snap.model_tests, snap.run_notes
    page_header("Models", "Model tests T1–T8: tool calling, task completion, injection, latency and memory")
    if not tests:
        empty_state("No model-test results yet",
                    "Files appear here once a test writes them under experiments/hermes_agent/results/.")
        return
    results = model_results(tests, notes)
    _results(results)
    st.write("")
    _turns(tests.get("t5"), notes)  # full width: the time axis needs room
    st.write("")
    _excluded(results, notes)  # full width: the reasons are long
    st.write("")
    _memory(tests.get("t7"))

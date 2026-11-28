"""Experiments page: pick one run, filter its trials, and inspect any trial's evidence and configuration."""

import pandas as pd
import streamlit as st

from dashboard.components import (card, chip_html, config_panel_html, default_run, empty_state, evidence_panel,
                                  group_label, html, page_header, result_styler, section_title, trial_frame, card_title)
from dashboard.data import row_dict, run_summary
from dashboard.store import snapshot
from dashboard.timefmt import month_day

KINDS = ["attack", "control", "benign"]


def _run_label(r) -> str:
    started = f'{month_day(r["started"])} {r["started"]:%H:%M}' if pd.notna(r["started"]) else "no time"
    return (f'{r["run_id"]} · {r["suite"].replace("_", " ")} · {started} · {r["trials"]} trials'
            + (" · superseded" if r["superseded"] else ""))


def _keep_valid(key: str, options: list) -> None:
    """Drop saved selections that the current run does not have (the run picker may have changed)."""
    if key in st.session_state:
        st.session_state[key] = [v for v in st.session_state[key] if v in options]


def _filters(run_trials: pd.DataFrame) -> pd.DataFrame:
    configs = sorted(run_trials["config"].unique())
    kinds = [k for k in KINDS if k in set(run_trials["kind"])] + sorted(set(run_trials["kind"]) - set(KINDS))
    results = sorted({group_label(g) if v else "Unverified" for g, v in zip(run_trials["group"], run_trials["verified"])})
    for key, opts in (("x_config", configs), ("x_kind", kinds), ("x_result", results)):
        _keep_valid(key, opts)
    c1, c2, c3, c4 = st.columns([1.4, 1, 1.2, 1.3])
    pick_configs = c1.multiselect("Configuration", configs, key="x_config", placeholder="All configurations")
    pick_kinds = c2.multiselect("Kind", kinds, key="x_kind", placeholder="All kinds")
    pick_results = c3.multiselect("Result", results, key="x_result", placeholder="All results")
    query = c4.text_input("Test name contains", key="x_query", placeholder="e.g. exfil")

    out = run_trials
    if pick_configs:
        out = out[out["config"].isin(pick_configs)]
    if pick_kinds:
        out = out[out["kind"].isin(pick_kinds)]
    if pick_results:
        shown = [group_label(g) if v else "Unverified" for g, v in zip(out["group"], out["verified"])]
        out = out[[r in pick_results for r in shown]]
    if query.strip():
        out = out[out["item"].str.contains(query.strip(), case=False, regex=False)]
    return out


def render():
    ss = st.session_state
    snap = snapshot()
    trials = snap.trials
    page_header("Experiments", "Pick a run, then inspect any trial, its configuration and the observer's evidence")
    if trials.empty:
        empty_state("No experiment results yet", "Run files appear here once an experiment writes them.")
        return

    runs = run_summary(trials)
    ids = list(runs["run_id"])
    if ss.get("x_run") not in ids:
        ss["x_run"] = default_run(trials)
    info = runs.set_index("run_id")
    run_id = st.selectbox("Run", ids, key="x_run", format_func=lambda r: _run_label(info.loc[r].to_dict() | {"run_id": r}))
    r = info.loc[run_id]
    run_trials = trials[trials["run_id"] == run_id]

    repeats = run_trials["repeat"].max()
    chips = [chip_html(r["suite"].replace("_", " ")), chip_html(f'{r["trials"]} trials'),
             chip_html(f'{r["configs"]} configurations'), chip_html(f'{r["operations"]} operations')]
    if pd.notna(repeats):
        chips.append(chip_html(f"up to {int(repeats)} repeats"))
    if r["attempted"]:
        chips.append(chip_html(f'{r["succeeded"]}/{r["attempted"]} attacks succeeded'))
    if r["unverified"]:
        chips.append(chip_html(f'{r["unverified"]} unverified'))
    if r["superseded"]:
        chips.append(chip_html("superseded run", icon_name="alert"))
    html(f'<div class="chips" style="margin:.2rem 0 1rem">{"".join(chips)}</div>')

    view = _filters(run_trials)
    st.write("")
    left, right = st.columns([3, 2], gap="medium")
    selected = None
    with left, card("x_trials"):
        from dashboard.nav import page  # imported here: nav imports the views
        card_title("Trials", "flask", page("comparison"))
        if view.empty:
            st.caption("No trials match these filters.")
        else:
            frame = trial_frame(view)
            scope = abs(hash((run_id, tuple(view.index))))  # fresh selection when the rows change
            event = st.dataframe(
                result_styler(frame), key=f"x_table-{scope}", on_select="rerun", selection_mode="single-row",
                hide_index=True, width="stretch", height=min(520, 36 * (len(frame) + 1) + 3),
                # Kind is left out: test names already start with attack_ / benign_ / control_, and rows are grouped by it.
                column_order=["Test", "Configuration", "Repeat", "Result", "Evidence"],
                column_config={"Test": st.column_config.TextColumn("Test", width="medium"),
                               "Configuration": st.column_config.TextColumn("Configuration", width="small"),
                               "Repeat": st.column_config.NumberColumn("Repeat", width="small", format="%d"),
                               "Result": st.column_config.TextColumn("Result", width="small"),
                               "Evidence": st.column_config.TextColumn("Evidence", width="medium")})
            st.caption(f"{len(view)} of {len(run_trials)} trials in this run. Select a row for its evidence.")
            rows = event.selection.rows if event else []
            if rows:
                selected = row_dict(view.loc[frame.index[rows[0]]])
    with right:
        with card("x_evidence"):
            section_title("Trial evidence", "file")
            if selected is None:
                st.caption("Select a trial to see its execution timeline, the observer's checks and the raw record.")
            else:
                evidence_panel(selected)
        st.write("")
        with card("x_configuration"):
            section_title("Configuration", "shield")
            shown = selected["config"] if selected else (ss.get("x_config") or [None])[0]
            if shown:
                html(config_panel_html(shown))
            else:
                st.caption("Select a trial, or filter to one configuration, to see what it changes.")

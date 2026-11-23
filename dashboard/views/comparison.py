"""Security Comparison page: every operation against every configuration in one run, which layer stopped
each attack, and the results that are not a clean block (unattributed, unverified, false positives)."""

import pandas as pd
import streamlit as st

from dashboard import charts
from dashboard.components import (card, card_title, chip_html, config_panel_html, default_run, empty_state, evidence_panel,
                                  html, note, page_header, section_title)
from dashboard.data import cell_outcomes, false_positive_table, layer_counts, row_dict, run_summary
from dashboard.store import snapshot


def _run_picker(trials):
    """The same run choice as Experiments (shared key), so the two pages stay on one run."""
    ss = st.session_state
    runs = run_summary(trials).set_index("run_id")
    ids = list(runs.index)
    if ss.get("x_run") not in ids:
        ss["x_run"] = default_run(trials)

    def label(r):
        row = runs.loc[r]
        return (f'{r} · {row["suite"].replace("_", " ")} · {row["trials"]} trials · {row["configs"]} configurations'
                + (" · superseded" if row["superseded"] else ""))

    return st.selectbox("Run", ids, key="x_run", format_func=label), runs


def _selected_cell(run_trials, pick):
    trials = run_trials[(run_trials["item"] == pick["item"]) & (run_trials["config"] == pick["config"])]
    trials = trials.sort_values("repeat")
    with card("c_selected"):
        section_title(f'{pick["item"]} × {pick["config"]}', "file")
        left, right = st.columns([3, 2], gap="medium")
        with left:
            if trials.empty:
                st.caption("No trials for this cell.")
            else:
                labels = [f"Repeat {int(r)}" if pd.notna(r) else f"Trial {i + 1}"
                          for i, r in enumerate(trials["repeat"])]
                for tab, (_, row) in zip(st.tabs(labels), trials.iterrows()):
                    with tab:
                        evidence_panel(row_dict(row))
        with right:
            html(config_panel_html(pick["config"]))


def _layers(run_trials, configs):
    with card("c_layers"):
        section_title("Which layer stopped each attack", "shield_check")
        layers = layer_counts(run_trials)
        chart = charts.layer_matrix(layers, configs)
        if chart is None:
            st.caption("No blocked attack trials in this run.")
            return
        st.altair_chart(chart, width="content")
        note("Counts are blocked attack trials. The layer named is the one that reported the denial: where two "
             "layers would both block, only the first one is visible.")
        tags = layers.groupby("attribution", dropna=False)["trials"].sum()
        parts = [f"{int(n)} {'not stated' if k == 'unspecified' else k}" for k, n in tags.items() if pd.notna(k)]
        if parts:
            note("Attribution in the records: " + " · ".join(parts) + ".")


def _not_clean(run_trials):
    """Results that are not a clean success or block, kept out of the matrix totals' story."""
    with card("c_unclear"):
        section_title("Unattributed, unverified and unrecognised", "help")
        mask = (run_trials["group"].isin(["unattributed", "other"]) | ~run_trials["verified"])
        rows = run_trials[mask]
        if rows.empty:
            st.caption(f"None in this run: all {len(run_trials)} trials have observer records and a recognised "
                       "outcome, and no failure lacks a credited layer.")
            return
        st.dataframe(pd.DataFrame({
            "Test": rows["item"], "Configuration": rows["config"], "Repeat": rows["repeat"],
            "Outcome": ["Unverified" if not v else g.replace("_", " ") for g, v in zip(rows["group"], rows["verified"])],
            "Recorded layer or reason": rows["layer"].fillna(""), "Label in record": rows["label"],
        }), hide_index=True, width="stretch")
        note("These are listed apart and never counted as blocked.")


def _false_positives(run_trials):
    with card("c_fp"):
        section_title("False positives: legitimate tasks blocked", "block")
        table = false_positive_table(run_trials)
        if table.empty:
            st.caption("No benign tasks in this run.")
            return
        st.dataframe(table.assign(completed=[f"{c}/{b}" for c, b in zip(table["completed"], table["benign"])]),
                     hide_index=True, width="stretch",
                     column_order=["config", "completed", "false_positive", "blocked_by"],
                     column_config={"config": "Configuration", "completed": "Benign completed",
                                    "false_positive": "False positives", "blocked_by": "Blocked by"})
        note("A control that blocks legitimate work has a cost; this is it, per configuration.")


def render():
    snap = snapshot()
    trials = snap.trials
    page_header("Security Comparison", "Every operation against every configuration, and what stopped each attack")
    if trials.empty:
        empty_state("No experiment results yet", "Run files appear here once an experiment writes them.")
        return

    run_id, runs = _run_picker(trials)
    run_trials = trials[trials["run_id"] == run_id]
    r = runs.loc[run_id]
    chips = [chip_html(f'{r["operations"]} operations'), chip_html(f'{r["configs"]} configurations')]
    repeats = run_trials["repeat"].max()
    if pd.notna(repeats):
        chips.append(chip_html(f"up to {int(repeats)} repeats per cell"))
    if r["superseded"]:
        chips.append(chip_html("superseded run", icon_name="alert"))
    html(f'<div class="chips" style="margin:.2rem 0 1rem">{"".join(chips)}</div>')

    configs = sorted(run_trials["config"].unique())
    cells = cell_outcomes(run_trials)
    pick = None
    with card("c_matrix"):
        from dashboard.nav import page  # imported here: nav imports the views
        card_title("Outcome matrix", "shield", page("experiments"))
        chart = charts.outcome_matrix(cells)
        if chart is None:
            st.caption("No trials in this run.")
        else:
            event = st.altair_chart(chart, on_select="rerun", key=f"c_matrix-{run_id}", width="content")
            pick = charts.matrix_selection(event)
            mixed = int((cells["cell"] == "Mixed").sum())
            note("Each cell is one operation in one configuration; the number is how many of its repeats share the "
                 "outcome. " + (f"{mixed} cell(s) differ between repeats (Mixed). " if mixed else
                                "Every cell had the same outcome on every repeat. ")
                 + "Click a cell to see its trials; double-click to clear.")
            note("Counts, not statistics. Outcomes reflect this controlled experiment, not a general security guarantee.")

    if pick:
        st.write("")
        _selected_cell(run_trials, pick)

    st.write("")
    _layers(run_trials, configs)  # full width: layer names are long
    st.write("")
    left, right = st.columns(2, gap="medium")
    with left:
        _not_clean(run_trials)
    with right:
        _false_positives(run_trials)

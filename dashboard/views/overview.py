"""Overview page, laid out like the reference dashboard: KPI row, top issues and assets, outcome breakdown,
trend charts, then the run's attack table and evidence. Every number is computed from the result files."""

from functools import partial
from html import escape

import streamlit as st

from dashboard import charts
from dashboard.components import (activity_frame, card, card_title, empty_state, evidence_panel,
                                  filter_bar, group_label, html, kpi_row, note, page_header_html, result_styler,
                                  section_title)
from dashboard.data import outcome_counts, row_dict, run_summary
from dashboard.store import snapshot

RUN_HINT = ".venv/bin/python experiments/local_agent/scripted_control.py --repeats 2"
DOT = {"Succeeded": "red", "Unattributed": "orange", "No attempt": "blue"}  # matches charts.OUTCOME_REF


def _period(trials) -> str | None:
    times = trials["time"].dropna()
    if times.empty:
        return None
    lo, hi = times.min(), times.max()
    return lo.strftime("%b %-d, %Y") if lo.date() == hi.date() else f"{lo:%b %-d} – {hi:%b %-d, %Y}"


def _n(count: int, noun: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'}"


def kpi_tiles(trials) -> list[dict]:
    """Five headline tiles, computed only from verified records."""
    c = outcome_counts(trials).sum(numeric_only=True)
    attacks = trials[trials["kind"] == "attack"]
    blocked = attacks[(attacks["group"] == "blocked") & attacks["verified"]]
    attr = blocked["attribution"].value_counts()
    split = " · ".join(f"{attr.get(k, 0)} {label}" for k, label in
                       (("observed", "observed"), ("inferred", "inferred"), ("unspecified", "not stated"))
                       if attr.get(k, 0))
    attempted = int(c.get("attempted", 0))
    share = f"{round(100 * int(c.get('blocked', 0)) / attempted)}" if attempted else None
    return [
        dict(label="Blocked rate", value=share, of=100 if share else None, sub=split,
             title="" if attempted else "No attack attempts in the current selection"),
        dict(label="Succeeded", value=int(c.get("succeeded", 0)), note=f"of {attempted} attempted" if attempted else "",
             note_token="bad", sub="Counted from the observer's records"),
        dict(label="Unattributed", value=int(c.get("unattributed", 0)), sub="Failed, but no layer can be credited"),
        dict(label="Attack operations", value=int(attacks["item"].nunique()),
             note=f'{_n(attacks["config"].nunique(), "configuration")}'),
        dict(label="Trials", value=len(trials),
             note=f'{_n(trials["run_id"].nunique(), "run")}'),
    ]


def _top_issues(view) -> None:
    """Attack operations ranked by successes, then attempts: the reference's Top Issues list."""
    attacks = view[view["kind"] == "attack"]
    if attacks.empty:
        st.caption("No attack trials in the current selection.")
        return
    rows = []
    for item, g in attacks.groupby("item"):
        succ = int((g["group"] == "succeeded").sum())
        att = int(g["group"].isin(["succeeded", "blocked", "unattributed"]).sum())
        rows.append((succ, att, item))
    rows.sort(key=lambda r: (-r[0], -r[1], r[2]))
    for succ, att, item in rows[:5]:
        tone = "bad" if succ else "unk"
        html(f'<div class="li"><span class="li-name mono" title="{escape(item)}">{escape(item)}</span>'
             f'<span class="pill" style="--c: var(--{tone})">{succ}/{att}</span></div>')


def _top_assets(view) -> None:
    """Configurations with their outcome counts as coloured dots: the reference's Top Affected Assets list."""
    attacks = view[view["kind"] == "attack"]
    if attacks.empty:
        st.caption("No attack trials in the current selection.")
        return
    counts = outcome_counts(attacks).sort_values(["succeeded", "unattributed"], ascending=False)
    for _, r in counts.head(5).iterrows():
        dots = []
        for label, col, token in (("Succeeded", "succeeded", "bad"), ("Unattributed", "unattributed", "warn"),
                                  ("No attempt", "no_attempt", "unk")):
            dots.append(f'<span class="dotn" style="--c: var(--{token})">'
                        f'<span class="dot"></span>{int(r[col])}</span>')
        html(f'<div class="li"><span class="li-name mono">{escape(str(r["config"]))}</span>'
             f'<span class="dots">{"".join(dots)}</span></div>')


def _breakdown(view) -> None:
    attacks = view[view["kind"] == "attack"]
    counts = outcome_counts(attacks).sum(numeric_only=True)
    total = int(counts.get("attempted", 0)) + int(counts.get("no_attempt", 0))
    if not total:
        st.caption("No attack trials in the current selection.")
        return
    parts = pd_frame({"outcome": ["Succeeded", "Unattributed", "Blocked", "No attempt"],
                      "n": [int(counts.get("succeeded", 0)), int(counts.get("unattributed", 0)),
                            int(counts.get("blocked", 0)), int(counts.get("no_attempt", 0))]})
    with st.container(key="ring-wrap"):
        html(f'<div class="ring-total"><span>Total</span><b>{total}</b></div>')
        st.altair_chart(charts.ring(parts, "outcome", "n", charts.OUTCOME_REF), width="stretch")


def pd_frame(data: dict):
    import pandas as pd
    return pd.DataFrame(data)


def _trends(view) -> None:
    daily = charts.daily_outcomes(view[view["kind"] == "attack"])
    if daily.empty:
        st.caption("Trends need trials with a time. None in the current selection.")
        return
    counts = outcome_counts(view[view["kind"] == "attack"]).sum(numeric_only=True)
    attempted = int(counts.get("attempted", 0))
    blocked_n, succeeded_n = int(counts.get("blocked", 0)), int(counts.get("succeeded", 0))
    total_trials = attempted + int(counts.get("no_attempt", 0))
    left, mid, right = st.columns(3, gap="medium")
    with left, card("t_share"):
        card_title("Blocked share over time")
        if attempted:
            html(f'<div class="big">{round(100 * blocked_n / attempted)}<span>/ 100</span></div>')
        c = charts.blocked_share_area(daily)
        if c is not None:
            st.altair_chart(c, width="stretch")
    with mid, card("t_lines"):
        card_title("Succeeded and blocked over time")
        html(f'<div class="big-left" style="color: var(--bad)">{succeeded_n}<span>succeeded</span>'
             f'<b style="color: var(--good)">{blocked_n}</b><span>blocked</span></div>')
        c = charts.succeeded_blocked_lines(daily)
        if c is not None:
            st.altair_chart(c, width="stretch")
    with right, card("t_volume"):
        card_title("Attack trials over time")
        html(f'<div class="big">{total_trials}<span>trials in total</span></div>')
        c = charts.trials_per_day(daily)
        if c is not None:
            st.altair_chart(c, width="stretch")
    st.write("")
    wide, side = st.columns([2, 1], gap="medium")
    with wide, card("t_stack"):
        card_title("Outcome trend")
        st.altair_chart(charts.outcome_trend(daily), width="stretch")
    with side, card("t_ops"):
        card_title("Attacks by operation")
        ops = view[view["kind"] == "attack"].groupby("item").size().rename("n").reset_index()
        ops = ops.sort_values("n", ascending=False)
        palette = list(charts.REF_COLORS.values())
        ops["color"] = [palette[i % len(palette)] for i in range(len(ops))]
        chart = charts.ring(ops.rename(columns={"item": "operation"}), "operation", "n",
                            dict(zip(ops["item"], ops["color"])), legend="none")
        if chart is not None:
            st.altair_chart(chart, width="stretch")
            total_ops = int(ops["n"].sum())
            for _, r in ops.head(5).iterrows():
                html(f'<div class="li"><span class="li-name mono" title="{escape(r["item"])}">'
                     f'<span class="dot-sw" style="background: {r["color"]}"></span>{escape(r["item"])}</span>'
                     f'<span class="muted-n">{100 * r["n"] / total_ops:.1f}%</span></div>')


def render():
    from dashboard.nav import page  # imported here: nav imports this module
    snap = snapshot()
    trials = snap.trials
    title_col, tools_col = st.columns([5, 4], vertical_alignment="center")
    with title_col:
        html(page_header_html("Security Overview", "AI agent evaluation · local environment"))

    if trials.empty:
        empty_state("No experiment results yet",
                    "Results appear here once an experiment writes a file under experiments/local_agent/results/. "
                    "Run the forced-attempt control to produce one:", RUN_HINT)
        return

    with tools_col, st.container(key="tools"):
        filters_col, cta_col = st.columns(2)
        with filters_col, st.popover("Filters", icon=":material/tune:", width="stretch"):
            view = filter_bar(trials)
        with cta_col, st.container(key="cta"):
            st.page_link(page("experiments"), label="Open experiments", icon=":material/add:")
    period = _period(view)
    if view.empty:
        empty_state("Nothing matches these filters", "Clear a filter to see results.", icon_name="info")
        return

    kpi_row(kpi_tiles(view))
    unverified = int((~view["verified"]).sum())
    st.write("")
    runs = view["run_id"].nunique()
    note(("Counts come from the observer's records, not the model's replies. "
          + (f"{runs} runs are added together; runs that repeat the same operations count them more than once. "
             if runs > 1 else "")
          + (f"{unverified} unverified record(s) are excluded from these totals. " if unverified else "")
          + (f"Data from {period}." if period else "")).strip())

    st.write("")
    a, b, c = st.columns([1.55, 1.1, 1], gap="medium")
    with a, card("issues"):
        card_title("Top issues", None, page("comparison"))
        _top_issues(view)
    with b, card("assets"):
        card_title("Top affected assets", None, page("comparison"))
        _top_assets(view)
    with c, card("breakdown"):
        card_title("Outcome breakdown")
        _breakdown(view)

    st.write("")
    _trends(view)

    st.write("")
    picked = _outcome_section(view)

    st.write("")
    left, right = st.columns([3, 2], gap="medium")
    with left, card("activity"):
        row = _activity_section(view, picked)
    with right, card("evidence"):
        section_title("Trial evidence", "file")
        if row is None:
            st.caption("Select a row in Recent activity to see its execution timeline and the observer's record.")
        else:
            evidence_panel(row)
            if st.button("Open in Experiments", icon=":material/science:", key="open_in_experiments"):
                from dashboard.nav import page
                # Experiments' own widgets are not on this page, so their state can be set here.
                st.session_state.update(x_run=row["run_id"], x_config=[row["config"]], x_query=row["item"],
                                        x_kind=[], x_result=[])
                st.switch_page(page("experiments"))

    st.write("")
    _run_history(trials)



def _outcome_section(view) -> list[dict]:
    """The main chart. Returns the clicked segments so the activity table can follow them."""
    with card("outcome"):
        section_title("Attack outcome by configuration", "shield")
        attacks = view[view["kind"] == "attack"]
        if attacks.empty:
            st.caption("No attack trials in the current selection.")
            return []
        chart = charts.outcome_bar(outcome_counts(view))
        # A new key when the data changes, so a click made on another run does not filter this one.
        scope = hash((tuple(sorted(view["run_id"].unique())), tuple(sorted(view["config"].unique())), len(view)))
        event = st.altair_chart(chart, on_select="rerun", key=f"outcome_chart-{abs(scope)}", width="stretch")
        picked = charts.selected_points(event)
        repeats = attacks["repeat"].max()
        repeats = f" · up to {int(repeats)} repeats per cell" if repeats == repeats else ""
        note(f'{attacks["item"].nunique()} attack operations across {attacks["config"].nunique()} configurations'
             f"{repeats}. Counts, not statistics. Click a segment to list its trials; double-click to clear.")
        note("Outcomes reflect this controlled experiment, not a general security guarantee.")
        return picked


def _activity_section(view, picked):
    """Recent trials (filtered by a chart click). Returns the selected trial as a dict, or None."""
    from dashboard.nav import page  # imported here: nav imports this module
    card_title("Recent activity", "flask", page("experiments"))
    rows = view
    if picked:
        want = {(p.get("config"), p.get("outcome")) for p in picked}
        mask = [(c, group_label(g)) in want for c, g in zip(view["config"], view["group"])]
        rows = view[mask]
        st.caption("Filtered by the chart: " + "; ".join(f"{c} · {o}" for c, o in sorted(want)))
    frame = activity_frame(rows).head(200)
    if frame.empty:
        st.caption("No trials.")
        return None
    key = "activity-" + str(abs(hash(tuple(sorted(map(str, picked))))))  # new selection state when the filter changes
    event = st.dataframe(
        result_styler(frame), key=key, on_select="rerun", selection_mode="single-row",
        hide_index=True, width="stretch", height=380,
        column_order=["Time", "Test", "Configuration", "Result", "Evidence"],
        column_config={"Time": st.column_config.DatetimeColumn("Time", format="MMM D HH:mm", width="small"),
                       "Test": st.column_config.TextColumn("Test", width="medium"),
                       "Configuration": st.column_config.TextColumn("Configuration", width="small"),
                       "Result": st.column_config.TextColumn("Result", width="small"),
                       "Evidence": st.column_config.TextColumn("Evidence", width="medium")})
    st.caption(f"Showing {len(frame)} of {len(rows)} trials, newest first.")
    sel = event.selection.rows if event else []
    return row_dict(view.loc[frame.index[sel[0]]]) if sel else None


def _use_run(run_ids, key):
    rows = st.session_state[key].selection.rows
    if rows:
        st.session_state["f_run"] = [run_ids[rows[0]]]


def _run_history(trials):
    with card("history"):
        section_title("Run history", "database")
        runs = run_summary(trials)
        table = runs.assign(
            Run=runs["run_id"], Type=runs["suite"].str.replace("_", " "),
            Status=["superseded" if s else "current" for s in runs["superseded"]],
            Succeeded=[f"{s}/{a}" if a else "no attempts" for s, a in zip(runs["succeeded"], runs["attempted"])],
            success_rate=runs["success_rate"] * 100,
        )[["Run", "Type", "Status", "started", "trials", "configs", "operations", "Succeeded", "success_rate",
           "unattributed", "unverified"]]
        st.dataframe(
            table, key="run_history", on_select=partial(_use_run, list(runs["run_id"]), "run_history"),
            selection_mode="single-row", hide_index=True, width="stretch",
            column_config={
                "started": st.column_config.DatetimeColumn("Started", format="MMM D, HH:mm"),
                "trials": "Trials", "configs": "Configs", "operations": "Operations",
                "success_rate": st.column_config.ProgressColumn("Attack success", format="%.0f%%",
                                                                min_value=0, max_value=100),
                "unattributed": "Unattributed", "unverified": "Unverified"})
        note("Runs differ in operations and configurations, so their rates are not directly comparable. "
             "Select a run to show it above.")

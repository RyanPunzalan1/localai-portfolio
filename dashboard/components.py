"""Reusable dashboard pieces.

The *_html functions are pure (string in, escaped HTML out) so they can be unit tested. The render functions
are thin wrappers around st.markdown. Every piece of text that reaches HTML goes through html.escape:
record text is untrusted and may contain injection attempts.
"""

from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st

from dashboard.theme import ATTRIBUTION, GROUPS, icon


# ------------------------------------------------------------------ pure HTML builders
def fraction(n: int, d: int) -> str:
    """'16/20'. Counts always travel with their denominator."""
    return f"{int(n)}/{int(d)}"


def status_badge_html(group: str) -> str:
    label, ico, token = GROUPS.get(group, GROUPS["other"])
    if group not in GROUPS:
        label = group
    return (f'<span class="badge" style="--c: var(--{token})">{icon(ico, token, 14)}'
            f'{escape(str(label))}</span>')


def attribution_tag_html(attribution: str | None) -> str:
    if not attribution:
        return ""
    label, why = ATTRIBUTION.get(attribution, (attribution, ""))
    return f'<span class="tag" title="{escape(why)}">{escape(label)}</span>'


def kpi_tile_html(label: str, value, sub: str = "", icon_name: str | None = None,
                  icon_token: str | None = None, of=None, title: str = "", note: str = "",
                  note_token: str | None = None) -> str:
    """A stat tile in the reference's style: muted label, large figure, optional inline note.

    value=None renders an em dash. `sub` and `title` become the hover text, so detail stays reachable without
    adding a second line. icon_name and icon_token are accepted for older callers and not drawn.
    """
    shown = "&mdash;" if value is None else escape(f"{value:,}" if isinstance(value, int) else str(value))
    of_html = f'<span class="of">/ {escape(f"{of:,}" if isinstance(of, int) else str(of))}</span>' if of is not None else ""
    style = f' style="--c: var(--{note_token})"' if note_token else ""
    note_html_ = f'<span class="note"{style}>{escape(note)}</span>' if note else ""
    hover = " · ".join(t for t in (title, sub) if t)
    title_attr = f' title="{escape(hover)}"' if hover else ""
    return (f'<div class="kpi"{title_attr}><div class="kpi-label">{escape(label)}</div>'
            f'<div class="kpi-value">{shown}{of_html}{note_html_}</div></div>')


def chip_html(text: str, dot: bool = False, icon_name: str | None = None) -> str:
    lead = '<span class="dot"></span>' if dot else (icon(icon_name, None, 14) if icon_name else "")
    return f'<span class="chip">{lead}{escape(text)}</span>'


def page_header_html(title: str, subtitle: str = "", chips: list[str] | None = None) -> str:
    sub = f'<div class="sub">{escape(subtitle)}</div>' if subtitle else ""
    right = f'<div class="chips">{"".join(chips)}</div>' if chips else ""
    return f'<div class="page-head"><div><h1>{escape(title)}</h1>{sub}</div>{right}</div>'


def section_title_html(text: str, icon_name: str | None = None) -> str:
    ico = icon(icon_name, "text", 20) if icon_name else ""
    return f'<div class="section-title">{ico}{escape(text)}</div>'


def note_html(text: str) -> str:
    return f'<div class="section-note">{icon("info", "muted", 14)}{escape(text)}</div>'


def empty_state_html(title: str, body: str, icon_name: str = "database") -> str:
    return (f'<div class="empty">{icon(icon_name, "muted", 28)}<h3>{escape(title)}</h3>'
            f'<p>{escape(body)}</p></div>')


MOCK_BANNER_HTML = (f'<div class="mock-banner" role="alert">{icon("alert", "warn", 18)}'
                    'MOCK DATA: illustrative only, not experiment results</div>')


# ------------------------------------------------------------------ render helpers
def html(fragment: str) -> None:
    st.markdown(fragment, unsafe_allow_html=True)


def page_header(title: str, subtitle: str = "", chips: list[str] | None = None) -> None:
    html(page_header_html(title, subtitle, chips))


def kpi_row(tiles: list[dict]) -> None:
    for col, tile in zip(st.columns(len(tiles)), tiles):
        with col:
            html(kpi_tile_html(**tile))


def section_title(text: str, icon_name: str | None = None) -> None:
    html(section_title_html(text, icon_name))


def note(text: str) -> None:
    html(note_html(text))


def empty_state(title: str, body: str, command: str | None = None, icon_name: str = "database") -> None:
    html(empty_state_html(title, body, icon_name))
    if command:
        st.code(command, language="bash")


def card(key: str):
    """A bordered panel that follows the theme. Use as `with card("name"):`."""
    return st.container(border=True, key=f"card-{key}")


def mock_banner() -> None:
    html(MOCK_BANNER_HTML)


# ------------------------------------------------------------------ filters
FILTER_KEYS = ("f_run", "f_config", "f_model", "f_dates")
EXPLORER_KEYS = ("x_run", "x_config", "x_kind", "x_result", "x_query", "m_tests", "m_models", "m_originals",
                 "live_pick")


def apply_filters(trials: pd.DataFrame, runs=(), configs=(), models=(), dates=None) -> pd.DataFrame:
    """Empty selections mean 'all'. Pure, so it is tested without Streamlit."""
    out = trials
    if runs:
        out = out[out["run_id"].isin(runs)]
    if configs:
        out = out[out["config"].isin(configs)]
    if models:
        out = out[out["model"].fillna("(scripted, no model)").isin(models)]
    if dates and len(dates) == 2 and out["time"].notna().any():
        start, end = (pd.Timestamp(d) for d in dates)
        day = out["time"].dt.normalize()
        out = out[(day >= start) & (day <= end)]
    return out


def default_run(trials: pd.DataFrame) -> str | None:
    """The non-superseded forced-attempt run with the newest record, else the newest run of any kind."""
    if trials.empty:
        return None
    current = trials[~trials["superseded"]]
    pool = current[current["suite"] == "forced_control"]
    pool = pool if not pool.empty else (current if not current.empty else trials)
    newest = pool.groupby("run_id")["time"].max().sort_values()
    return newest.index[-1] if not newest.dropna().empty else sorted(pool["run_id"].unique())[-1]


def filter_bar(trials: pd.DataFrame) -> pd.DataFrame:
    """One row of filters above the content. Selections live in session_state, so they carry across pages."""
    if trials.empty:
        return trials
    run_opts = sorted(trials["run_id"].unique(), reverse=True)
    if "f_run" not in st.session_state:
        # Different runs repeat the same operations, so adding them together double-counts.
        # Start from the latest forced-attempt run; the user can add others.
        latest = default_run(trials)
        st.session_state["f_run"] = [latest] if latest else []
    config_opts = sorted(trials["config"].unique())
    model_opts = sorted(trials["model"].fillna("(scripted, no model)").unique())
    # A saved selection can name options that no longer exist (for example after hiding superseded runs).
    for key, opts in (("f_run", run_opts), ("f_config", config_opts), ("f_model", model_opts)):
        if key in st.session_state:
            st.session_state[key] = [v for v in st.session_state[key] if v in opts]
    c1, c2, c3, c4 = st.columns([1.4, 1.3, 1, 1.25])
    runs = c1.multiselect("Run", run_opts, key="f_run", placeholder="All runs")
    configs = c2.multiselect("Configuration", config_opts, key="f_config", placeholder="All configurations")
    models = c3.multiselect("Model", model_opts, key="f_model", placeholder="All models")
    times = trials["time"].dropna()
    dates = None
    if not times.empty:
        lo, hi = times.min().date(), times.max().date()
        kept = st.session_state.get("f_dates")
        if kept is not None and not all(lo <= d <= hi for d in kept):
            del st.session_state["f_dates"]  # data changed under the saved range; fall back to all dates
        default = {} if "f_dates" in st.session_state else {"value": (lo, hi)}
        dates = c4.date_input("Dates", min_value=lo, max_value=hi, key="f_dates", **default)
    return apply_filters(trials, runs, configs, models, dates)


# ------------------------------------------------------------------ trial evidence
TONE_TOKENS = {"attempt": "warn", "stopped": "good", "harm": "bad", "ok": "good", "failed": "unk", "observer": "muted"}


def group_label(group: str) -> str:
    return GROUPS.get(group, (group,))[0]


def timeline_html(steps: list[dict], group: str) -> str:
    items = []
    for s in steps:
        token = GROUPS.get(group, GROUPS["other"])[2] if s["tone"] == "outcome" else TONE_TOKENS.get(s["tone"], "muted")
        right = status_badge_html(group) if s["tone"] == "outcome" else ""
        detail = "" if s["tone"] == "outcome" else s.get("detail", "")
        items.append(f'<li class="tl-step"><span class="tl-dot" style="--c: var(--{token})"></span>'
                     f'<div class="tl-body"><div class="tl-title">{escape(s["title"])}</div>'
                     f'<div class="tl-detail mono">{escape(str(detail))}</div></div>{right}</li>')
    return f'<ol class="tl">{"".join(items)}</ol>'


def evidence_rows_html(row: dict) -> str:
    raw = row.get("raw") or {}

    def yn(v):
        return "unknown" if v is None else ("yes" if v else "no")

    facts = [
        ("Sink hits", f'{raw.get("sink_hits", "n/a")} (canary {raw.get("sink_canary_hits", "n/a")})'),
        ("Files changed", yn(raw.get("files_changed", raw.get("workspace_changed")))),
        ("Canary in output", yn(row.get("canary_in_output"))),
        ("Exit code", "not recorded" if raw.get("rc") is None else raw["rc"]),
        ("Status", raw.get("status") or "not recorded"),
        ("Layer", row.get("layer") or "none recorded"),
    ]
    cells = "".join(f'<div class="ev-k">{escape(k)}</div><div class="ev-v mono">{escape(str(v))}</div>' for k, v in facts)
    return f'<div class="ev-grid">{cells}</div>'


def evidence_panel(row: dict) -> None:
    """Everything recorded about one trial. All record text is escaped or shown as code/JSON."""
    from dashboard.data import trial_timeline

    attribution = attribution_tag_html(row.get("attribution"))
    verified = "" if row.get("verified") else status_badge_html("unverified")
    when = row["time"].strftime("%b %-d, %H:%M:%S") if pd.notna(row.get("time")) else "time not recorded"
    repeat = row.get("repeat")
    repeat = f" · repeat {int(repeat)}" if pd.notna(repeat) else ""
    html(f'<div class="ev-head"><div><div class="ev-item mono">{escape(str(row["item"]))}</div>'
         f'<div class="ev-meta">{escape(str(row["config"]))}{escape(repeat)} · {escape(when)}</div></div>'
         f'<div class="ev-badges">{status_badge_html(row["group"])}{attribution}{verified}</div></div>')
    html(timeline_html(trial_timeline(row), row["group"]))
    html(evidence_rows_html(row))
    err = row.get("err_tail")
    if err:
        st.caption("Error output (from the record, untrusted)")
        st.code(str(err)[-1200:], language=None)
    with st.expander("Raw record"):
        st.json(row.get("raw") or {}, expanded=True)
    st.caption(f'Source: {row["source_file"]}')


def activity_frame(trials: pd.DataFrame) -> pd.DataFrame:
    """Rows for the activity table, newest first, keeping the trial index for lookups."""
    out = pd.DataFrame({
        "Time": trials["time"],
        "Test": trials["item"],
        "Kind": trials["kind"],
        "Configuration": trials["config"],
        "Result": [group_label(g) if v else "Unverified" for g, v in zip(trials["group"], trials["verified"])],
        "Evidence": trials["evidence"],
    }, index=trials.index)
    return out.sort_values("Time", ascending=False, kind="stable")


def result_styler(frame: pd.DataFrame):
    """Tint the Result cell with its status colour; the text stays the normal text colour.

    The status colours are the same in both palettes and the tint is translucent, so it works on either background.
    """
    from dashboard.theme import PALETTES

    pal = PALETTES["dark"]
    by_label = {label: pal[token] for label, _i, token in GROUPS.values()}

    def tint(value):
        hexv = by_label.get(value)
        if not hexv:
            return ""
        r, g, b = (int(hexv[i:i + 2], 16) for i in (1, 3, 5))
        return f"background-color: rgba({r},{g},{b},.22); font-weight: 600"

    return frame.style.map(tint, subset=["Result"])


KIND_ORDER = {"attack": 0, "control": 1, "benign": 2}


def trial_frame(trials: pd.DataFrame) -> pd.DataFrame:
    """Rows for the Experiments table, grouped by kind, then operation, configuration and repeat."""
    out = pd.DataFrame({
        "Test": trials["item"], "Kind": trials["kind"], "Configuration": trials["config"],
        "Repeat": trials["repeat"],
        "Result": [group_label(g) if v else "Unverified" for g, v in zip(trials["group"], trials["verified"])],
        "Evidence": trials["evidence"],
        "_order": trials["kind"].map(KIND_ORDER).fillna(9),
    }, index=trials.index)
    return out.sort_values(["_order", "Test", "Configuration", "Repeat"], kind="stable").drop(columns="_order")


def config_panel_html(name: str) -> str:
    """What a configuration changes, or a plain note when it is not described."""
    from dashboard.configs import SHARED, describe

    rows = describe(name)
    if rows is None:
        return f'<div class="prov-none">No description recorded for {escape(name)}.</div>'
    cells = "".join(f'<div class="ev-k">{escape(k)}</div><div class="ev-v">{escape(v)}</div>' for k, v in rows)
    return (f'<div class="ev-item mono">{escape(name)}</div><div class="ev-grid" style="margin-top:.5rem">{cells}</div>'
            f'<div class="ev-meta">{escape(SHARED)} Mirrored from the experiment scripts.</div>')


def card_title(text: str, icon_name: str | None = None, link_page=None, link_label: str = "View all") -> None:
    """Card heading on the reference's pattern: plain title, a divider under it, and an optional 'View all →' link.

    icon_name is accepted so older calls keep working; the reference has no icons in card titles.
    link_page is a st.Page (from dashboard.nav.page); it is passed in so this module never imports the views.
    """
    slug = "".join(ch if ch.isalnum() else "_" for ch in text.lower())
    with st.container(key=f"head-{slug}"):
        title = f'<div class="card-title">{escape(text)}</div>'
        if link_page is None:
            html(title)
            return
        title_col, link_col = st.columns([3, 2], vertical_alignment="center")
        with title_col:
            html(title)
        with link_col:
            st.page_link(link_page, label=f"{link_label} →", icon=None, width="content")

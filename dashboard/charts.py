"""Altair chart specs. Altair ships with Streamlit, so no new dependency.

The dashboard follows the system light/dark setting, which only the browser knows for sure, so charts use colours
that work on both backgrounds and leave theme-dependent details to the browser: Streamlit's chart theme colours axes
and legends, and CSS (dashboard.theme) colours the segment gaps and bar-end labels from the page's tokens.

Succeeded (red) and Blocked (green) sit side by side in a stacked bar. Blocked is #52a866, checked with the dataviz
palette validator against red: deutan ΔE 8.1 on both the dark and the light surface. On the light surface its
contrast is 2.86:1, so the direct labels and the table carry the values too. Identity is never colour alone.
"""

from __future__ import annotations

import altair as alt
import pandas as pd

CHART_COLORS = {"Succeeded": "#f0484f", "Blocked": "#15803d", "Unattributed": "#f5c542", "No attempt": "#5f5f6b",
                "Stopped at approval": "#e9b730", "Not reached": "#6b7280", "Inconclusive": "#9ca3af",
                "Other": "#f76b15"}
OUTCOME_ORDER = ["Succeeded", "Stopped at approval", "Unattributed", "Blocked", "No attempt", "Not reached",
                 "Inconclusive", "Other"]
SELECTION = "pick"
# Layer names become CSS classes in the rendered SVG (<name>_marks); dashboard.theme styles them.
SEGMENTS, BAR_LABELS = "outcome_segments", "outcome_labels"


def _configure(chart: alt.TopLevelMixin) -> alt.TopLevelMixin:
    font = "Inter, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    return (chart.configure(background="transparent", font=font)
            .configure_view(strokeWidth=0)
            .configure_axis(labelFontSize=12, titleFontSize=12, titleFontWeight=500, gridColor="rgba(128,128,128,0.16)",
                            tickColor="transparent")
            .configure_legend(labelFontSize=12, symbolType="circle", symbolSize=100, orient="top",
                              direction="horizontal", title=None, offset=4))


def outcome_long(counts: pd.DataFrame) -> pd.DataFrame:
    """outcome_counts() rows -> one row per (config, outcome segment) with n, total, share and a label."""
    rows = []
    for _, r in counts.iterrows():
        parts = {"Succeeded": r["succeeded"], "Stopped at approval": r.get("stopped_at_approval", 0),
                 "Unattributed": r["unattributed"], "Blocked": r["blocked"], "No attempt": r["no_attempt"],
                 "Not reached": r.get("not_reached", 0), "Inconclusive": r.get("inconclusive", 0)}
        total = int(sum(parts.values()))
        if total == 0:
            continue
        for outcome, n in parts.items():
            if n:
                rows.append({"config": r["config"], "outcome": outcome, "n": int(n), "total": total,
                             "share": n / total, "order": OUTCOME_ORDER.index(outcome),
                             "label": f"{int(n)}/{total}"})
    return pd.DataFrame(rows, columns=["config", "outcome", "n", "total", "share", "order", "label"])


def bar_label(succeeded, attempted, no_attempt) -> str:
    """'16/20 succeeded'; trials the model did not attempt are named, never folded into the denominator."""
    text = f"{int(succeeded)}/{int(attempted)} succeeded" if attempted else "no attempts"
    return text + (f" · {int(no_attempt)} not attempted" if no_attempt else "")


def outcome_bar(counts: pd.DataFrame) -> alt.TopLevelMixin | None:
    """Horizontal 100% stacked bars per configuration: Succeeded / Unattributed / Blocked / No attempt.

    Clicking a segment selects (config, outcome); the view filters its table with it.
    """
    long = outcome_long(counts)
    if long.empty:
        return None
    present = [o for o in OUTCOME_ORDER if o in set(long["outcome"])]
    configs = list(counts["config"])
    pick = alt.selection_point(name=SELECTION, fields=["config", "outcome"], on="click", clear="dblclick")

    base = alt.Chart(long)
    bars = base.mark_bar(height=20, cornerRadius=4, strokeWidth=2, cursor="pointer").encode(
        x=alt.X("n:Q", stack="normalize", title=None,
                axis=alt.Axis(format="%", values=[0, .25, .5, .75, 1], grid=True, domain=False, ticks=False)),
        y=alt.Y("config:N", sort=configs, title=None,
                axis=alt.Axis(labelLimit=260, labelPadding=10, domain=False, ticks=False, labelFontSize=13)),
        color=alt.Color("outcome:N", scale=alt.Scale(domain=present, range=[CHART_COLORS[o] for o in present]),
                        sort=present),
        order=alt.Order("order:Q"),
        opacity=alt.condition(pick, alt.value(1), alt.value(.35)),
        tooltip=[alt.Tooltip("config:N", title="Configuration"), alt.Tooltip("outcome:N", title="Outcome"),
                 alt.Tooltip("label:N", title="Trials"), alt.Tooltip("share:Q", title="Share", format=".0%")],
    ).add_params(pick).properties(name=SEGMENTS)

    # Direct label at the bar end: succeeded out of real attempts; trials the model never attempted named apart.
    succ = counts.assign(total=counts[["succeeded", "unattributed", "blocked", "no_attempt"]].sum(axis=1))
    succ = succ[succ["total"] > 0]
    labels = pd.DataFrame({"config": succ["config"], "x": 1.0,
                           "text": [bar_label(s, a, n) for s, a, n in
                                    zip(succ["succeeded"], succ["attempted"], succ["no_attempt"])]})
    right = 130 if not succ["no_attempt"].any() else 250
    text = alt.Chart(labels).mark_text(align="left", dx=10, fontSize=13, fontWeight=600).encode(
        x=alt.X("x:Q", scale=alt.Scale(domain=[0, 1])), y=alt.Y("config:N", sort=configs), text="text:N",
    ).properties(name=BAR_LABELS)

    # Streamlit fits the whole chart (legend and axis included) into this height, so add room for both.
    chart = alt.layer(bars, text).properties(height=40 * len(configs) + 80, padding={"right": right, "left": 4})
    return _configure(chart)


def selected_points(event) -> list[dict]:
    """The clicked segments from st.altair_chart(on_select=...), as [{'config':..., 'outcome':...}]."""
    try:
        return list(event.selection.get(SELECTION) or [])
    except AttributeError:
        return []


# ------------------------------------------------------------------ comparison matrix
# Matrix cells always print their count, and the legend and tooltip name the outcome, so colour is never the
# only cue. Security outcomes keep the bar chart's colours; benign and control results use a neutral slate so
# they never read as "blocked"; problems for legitimate work (false positive, control failed) are amber/orange.
MATRIX_COLORS = {
    "Succeeded": "#d03b3b", "Blocked": "#15803d", "Unattributed": "#8a8aa3", "No attempt": "#5f5f6b",
    "Stopped at approval": "#e0a030", "Not reached": "#6b7280", "Inconclusive": "#9ca3af",
    "Completed": "#5d7290", "Control passed": "#7f93b3", "False positive": "#e0a030", "Control failed": "#ec835a",
    "Mixed": "#9b6fd0", "Unverified": "#a0a0ad", "Other": "#a0a0ad",
}
_DARK_TEXT = {"False positive", "Control failed", "Unverified", "Other", "Unattributed", "Stopped at approval",
              "Inconclusive"}
MATRIX_SELECTION = "cell"
MATRIX_CELLS, MATRIX_TEXT = "matrix_cells", "matrix_text"


def outcome_matrix(cells: pd.DataFrame) -> alt.TopLevelMixin | None:
    """Operations (rows, attacks first) × configurations (columns); click a cell to inspect its trials."""
    if cells.empty:
        return None
    present = [c for c in MATRIX_COLORS if c in set(cells["cell"])]
    items = list(dict.fromkeys(cells["item"]))
    configs = sorted(cells["config"].unique())
    pick = alt.selection_point(name=MATRIX_SELECTION, fields=["item", "config"], on="click", clear="dblclick")
    data = cells.assign(ink=["#111111" if c in _DARK_TEXT else "#ffffff" for c in cells["cell"]])
    base = alt.Chart(data).encode(
        x=alt.X("config:N", sort=configs, title=None,
                axis=alt.Axis(orient="top", labelAngle=-35, labelLimit=220, labelOverlap=False, domain=False,
                              ticks=False, labelAlign="left")),
        y=alt.Y("item:N", sort=items, title=None, axis=alt.Axis(labelLimit=320, domain=False, ticks=False)),
    )
    rects = base.mark_rect(cornerRadius=4, strokeWidth=3, cursor="pointer").encode(
        color=alt.Color("cell:N", scale=alt.Scale(domain=present, range=[MATRIX_COLORS[c] for c in present]),
                        legend=alt.Legend(title=None, orient="top", direction="horizontal", columns=6)),
        opacity=alt.condition(pick, alt.value(1), alt.value(.3)),
        tooltip=[alt.Tooltip("item:N", title="Operation"), alt.Tooltip("config:N", title="Configuration"),
                 alt.Tooltip("cell:N", title="Outcome"), alt.Tooltip("detail:N", title="Repeats")],
    ).add_params(pick).properties(name=MATRIX_CELLS)
    text = base.mark_text(fontSize=12, fontWeight=600).encode(
        text="text:N", color=alt.Color("ink:N", scale=None),
    ).properties(name=MATRIX_TEXT)
    # Fixed column width: on a narrow screen the chart scrolls sideways (theme.py) instead of squashing cells.
    chart = alt.layer(rects, text).properties(height=34 * len(items) + 110, width=alt.Step(72), padding={"right": 70})
    return _configure(chart)


def matrix_selection(event) -> dict | None:
    try:
        picked = event.selection.get(MATRIX_SELECTION) or []
    except AttributeError:
        return None
    return picked[0] if picked else None


LAYER_CELLS, LAYER_TEXT = "layer_cells", "layer_text"


def layer_matrix(layers: pd.DataFrame, configs: list) -> alt.TopLevelMixin | None:
    """Blocked attack trials by the layer that reported the denial (rows) and configuration (columns).

    One measure, so one hue: darker green = more trials stopped by that layer. Every cell prints its count.
    """
    if layers.empty:
        return None
    data = layers.assign(label=[f"{layer}" for layer in layers["layer"].fillna("not recorded")])
    rows = list(data.groupby("label")["trials"].sum().sort_values(ascending=False).index)
    base = alt.Chart(data).encode(
        x=alt.X("config:N", sort=configs, scale=alt.Scale(domain=configs), title=None,
                axis=alt.Axis(orient="top", labelAngle=-35, labelLimit=220, labelOverlap=False, domain=False,
                              ticks=False, labelAlign="left")),
        y=alt.Y("label:N", sort=rows, title=None, axis=alt.Axis(labelLimit=380, domain=False, ticks=False)),
    )
    rects = base.mark_rect(cornerRadius=4, strokeWidth=3).encode(
        color=alt.Color("trials:Q", scale=alt.Scale(range=["#cfe9d4", "#1f6b33"], zero=False), legend=None),
        tooltip=[alt.Tooltip("label:N", title="Layer"), alt.Tooltip("config:N", title="Configuration"),
                 alt.Tooltip("trials:Q", title="Blocked trials"), alt.Tooltip("attribution:N", title="Attribution")],
    ).properties(name=LAYER_CELLS)
    peak = data["trials"].max()
    text = base.mark_text(fontSize=12, fontWeight=600).encode(
        text="trials:Q",
        color=alt.condition(alt.datum.trials > peak / 2, alt.value("#ffffff"), alt.value("#111111")),
    ).properties(name=LAYER_TEXT)
    return _configure(alt.layer(rects, text).properties(height=34 * len(rows) + 130, width=alt.Step(72),
                                                        padding={"right": 70}))


TURNS = "turn_points"


def turn_times(turns: pd.DataFrame) -> alt.TopLevelMixin | None:
    """T5 turn times per run (rows), on a log-like scale because a few turns take minutes. Shape and colour both say
    whether the turn was OK, so the two states never rely on colour alone."""
    if turns.empty:
        return None
    rows = list(dict.fromkeys(turns["row"]))
    chart = alt.Chart(turns).mark_point(size=70, filled=True, opacity=.85).encode(
        # symlog, not log: two recorded turns are 0.0 s, which a log scale cannot place (it breaks the axis).
        x=alt.X("secs:Q", scale=alt.Scale(type="symlog"), title="Seconds per turn (log-like scale, 0 included)",
                axis=alt.Axis(values=[0, 1, 2, 5, 10, 20, 50, 100, 200, 500], grid=True)),
        y=alt.Y("row:N", sort=rows, title=None, axis=alt.Axis(labelLimit=320, domain=False, ticks=False)),
        color=alt.Color("result:N", scale=alt.Scale(domain=["OK", "Missed"], range=["#5d7290", "#d03b3b"]),
                        legend=alt.Legend(title=None, orient="top")),
        shape=alt.Shape("result:N", scale=alt.Scale(domain=["OK", "Missed"], range=["circle", "cross"]),
                        legend=None),
        tooltip=[alt.Tooltip("row:N", title="Run"), alt.Tooltip("session:N", title="Session"),
                 alt.Tooltip("turn:N", title="Turn"), alt.Tooltip("secs:Q", title="Seconds", format=".1f"),
                 alt.Tooltip("result:N", title="Result")],
    ).properties(name=TURNS, height=34 * len(rows) + 90)
    return _configure(chart)


def outcome_donut(counts: pd.DataFrame) -> alt.TopLevelMixin | None:
    """Donut of attack outcomes across the current selection: the share of attempted operations per outcome.

    Only the four outcome segments count. Segment identity is also written in the legend.
    """
    if counts.empty:
        return None
    parts = {"Succeeded": int(counts["succeeded"].sum()), "Unattributed": int(counts["unattributed"].sum()),
             "Blocked": int(counts["blocked"].sum()), "No attempt": int(counts["no_attempt"].sum())}
    data = pd.DataFrame([{"outcome": k, "n": v} for k, v in parts.items() if v],
                        columns=["outcome", "n"])
    if data.empty:
        return None
    data["order"] = data["outcome"].map(OUTCOME_ORDER.index)
    base = alt.Chart(data).encode(
        theta=alt.Theta("n:Q", stack=True),
        color=alt.Color("outcome:N", sort=OUTCOME_ORDER,
                        scale=alt.Scale(domain=list(CHART_COLORS), range=list(CHART_COLORS.values())),
                        legend=alt.Legend(title=None, orient="bottom")),
        order=alt.Order("order:Q"),
        tooltip=[alt.Tooltip("outcome:N", title="Outcome"), alt.Tooltip("n:Q", title="Operations")])
    ring = base.mark_arc(innerRadius=62, outerRadius=96, stroke=None)
    return _configure(ring).properties(height=260, name=SEGMENTS)


# ------------------------------------------------------------------ reference-style overview charts
# Palette from the reference dashboard. Outcome colours: red = succeeded, orange = unattributed, mint = blocked,
# blue = not attempted, yellow = other. Each colour always comes with a legend entry or label, never alone.
REF_COLORS = {"red": "#e5534b", "orange": "#ee7d33", "yellow": "#e9b730", "blue": "#3b82f6", "mint": "#15803d"}
OUTCOME_REF = {"Succeeded": REF_COLORS["red"], "Unattributed": REF_COLORS["orange"],
               "Blocked": REF_COLORS["mint"], "No attempt": REF_COLORS["blue"], "Other": REF_COLORS["yellow"]}


def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


def _area_fill(color: str):
    """Area fill that fades from the line colour to transparent, as on the reference."""
    return alt.Gradient(gradient="linear", x1=0, x2=0, y1=1, y2=0,
                        stops=[alt.GradientStop(color=_rgba(color, 0.0), offset=0),
                               alt.GradientStop(color=_rgba(color, 0.22), offset=1)])


def daily_outcomes(attacks: pd.DataFrame) -> pd.DataFrame:
    """Attack trials per time bucket and outcome group. Trials without a time are left out and never guessed.

    The bucket is a day when the data spans several days. A run that fits in one day is bucketed by hour, or by
    ten minutes if that still gives fewer than four points, so a single run still draws a line. The bucket's
    axis label format is kept in df.attrs["fmt"].
    """
    frame = attacks.dropna(subset=["time"]).copy()
    if frame.empty:
        out = pd.DataFrame(columns=["day", "outcome", "n"])
        out.attrs["fmt"] = "%b %-d"
        return out
    fmt = "%b %-d"
    for freq, fmt in (("D", "%b %-d"), ("h", "%H:%M"), ("10min", "%H:%M"), ("min", "%H:%M"), ("10s", "%H:%M:%S")):
        buckets = frame["time"].dt.floor(freq)
        if buckets.nunique() >= 4:
            break
    frame["day"] = buckets
    names = {"succeeded": "Succeeded", "unattributed": "Unattributed", "blocked": "Blocked",
             "no_attempt": "No attempt"}
    frame["outcome"] = frame["group"].map(names).fillna("Other")
    out = frame.groupby(["day", "outcome"]).size().rename("n").reset_index()
    out.attrs["fmt"] = fmt
    return out


def _time_axis(fmt: str = "%b %-d", title=None):
    return alt.X("day:T", title=title, axis=alt.Axis(format=fmt, labelAngle=0, domain=False, ticks=False, grid=False))


def blocked_share_area(daily: pd.DataFrame) -> alt.TopLevelMixin | None:
    """Share of attempted operations that were blocked, per day. Mint area with a line, as on the reference."""
    if daily.empty:
        return None
    wide = daily.pivot_table(index="day", columns="outcome", values="n", aggfunc="sum", fill_value=0)
    attempted = wide.drop(columns=[c for c in ("No attempt",) if c in wide], errors="ignore").sum(axis=1)
    share = (wide.get("Blocked", 0) / attempted.where(attempted > 0)).dropna().rename("share").reset_index()
    if share.empty:
        return None
    base = alt.Chart(share).encode(x=_time_axis(daily.attrs.get("fmt", "%b %-d")), y=alt.Y("share:Q", axis=alt.Axis(format="%", domain=False,
                                                                                    ticks=False, title=None)),
                                   tooltip=[alt.Tooltip("day:T", format=daily.attrs.get("fmt", "%b %-d")), alt.Tooltip("share:Q", format=".0%")])
    area = base.mark_area(line={"color": REF_COLORS["mint"]}, color=_area_fill(REF_COLORS["mint"]))
    dots = base.mark_point(filled=True, color=REF_COLORS["mint"], size=36)
    return _configure(area + dots).properties(height=190)


def succeeded_blocked_lines(daily: pd.DataFrame) -> alt.TopLevelMixin | None:
    """Succeeded (red) against blocked (mint) per day, as the reference's open-vs-fixed chart."""
    keep = daily[daily["outcome"].isin(["Succeeded", "Blocked"])]
    if keep.empty:
        return None
    colors = {"Succeeded": REF_COLORS["red"], "Blocked": REF_COLORS["mint"]}
    base = alt.Chart(keep).encode(x=_time_axis(daily.attrs.get("fmt", "%b %-d")), y=alt.Y("n:Q", title=None, axis=alt.Axis(domain=False, ticks=False)),
                                  color=alt.Color("outcome:N", scale=alt.Scale(domain=list(colors),
                                                  range=list(colors.values())), legend=alt.Legend(orient="top")),
                                  tooltip=[alt.Tooltip("day:T", format=daily.attrs.get("fmt", "%b %-d")), "outcome:N", "n:Q"])
    lines = base.mark_line(interpolate="monotone", strokeWidth=2)
    return _configure(lines).properties(height=190)


def outcome_trend(daily: pd.DataFrame) -> alt.TopLevelMixin | None:
    """Stacked outcomes per day across the selection, in the reference's stacked-area style."""
    if daily.empty:
        return None
    present = [o for o in OUTCOME_REF if o in set(daily["outcome"])]
    base = alt.Chart(daily).encode(
        x=_time_axis(daily.attrs.get("fmt", "%b %-d")), y=alt.Y("n:Q", stack=True, title=None, axis=alt.Axis(domain=False, ticks=False)),
        color=alt.Color("outcome:N", sort=present, scale=alt.Scale(domain=present,
                        range=[OUTCOME_REF[o] for o in present]), legend=alt.Legend(orient="top")),
        order=alt.Order("outcome:N"),
        tooltip=[alt.Tooltip("day:T", format=daily.attrs.get("fmt", "%b %-d")), "outcome:N", "n:Q"])
    return _configure(base.mark_area(interpolate="monotone", opacity=0.6, line=True)).properties(height=240)


def trials_per_day(daily: pd.DataFrame) -> alt.TopLevelMixin | None:
    """Attack trials per day, as a mint line with a fade: the reference's time-series style."""
    if daily.empty:
        return None
    totals = daily.groupby("day", as_index=False)["n"].sum()
    base = alt.Chart(totals).encode(x=_time_axis(daily.attrs.get("fmt", "%b %-d")), y=alt.Y("n:Q", title=None, axis=alt.Axis(domain=False, ticks=False)),
                                    tooltip=[alt.Tooltip("day:T", format=daily.attrs.get("fmt", "%b %-d")), alt.Tooltip("n:Q", title="Trials")])
    area = base.mark_area(line={"color": REF_COLORS["mint"]}, color=_area_fill(REF_COLORS["mint"]),
                          interpolate="monotone")
    return _configure(area).properties(height=190)


def ring(counts: pd.DataFrame, category: str, value: str, colors: dict,
         legend: str = "bottom", size: int = 200, total: str | None = None) -> alt.TopLevelMixin | None:
    """Donut of a category column, coloured from a mapping.

    The chart stretches to its card's width at a fixed height, and the ring's radius comes from that height with a
    margin, so the ring is never cropped and sits in the middle of the card. `total`, when given, is drawn in the
    ring's centre by the chart itself, so it can't drift off-centre. With legend="none" the page draws its own legend.
    """
    data = counts[counts[value] > 0]
    if data.empty:
        return None
    domain = list(data[category])
    scale = alt.Scale(domain=domain, range=[colors.get(c, REF_COLORS["yellow"]) for c in domain])
    outer = size // 2 - 12
    arcs = alt.Chart(data).mark_arc(innerRadius=int(outer * 0.74), outerRadius=outer, stroke=None).encode(
        theta=alt.Theta(f"{value}:Q", stack=True), color=alt.Color(f"{category}:N", scale=scale,
                                                                 legend=None if legend == "none" else alt.Legend(title=None, orient=legend, labelLimit=160)),
        tooltip=[alt.Tooltip(f"{category}:N"), alt.Tooltip(f"{value}:Q", title="Trials")])
    layers = [arcs]
    if total is not None:
        centre = {"x": alt.value({"expr": "width / 2"}), "y": alt.value({"expr": "height / 2"})}
        words = pd.DataFrame({"t": [str(total)], "c": ["Total"]})
        # Layer names become CSS classes (<name>_marks), so dashboard.theme colours the text for light and dark.
        layers.append(alt.Chart(words).mark_text(fontSize=26, fontWeight=600, dy=10)
                      .encode(text="t:N", **centre).properties(name="ring_total"))
        layers.append(alt.Chart(words).mark_text(fontSize=13, dy=-16)
                      .encode(text="c:N", **centre).properties(name="ring_caption"))
    return _configure(alt.layer(*layers)).properties(height=size)

"""Security readiness page: what the workbench has tested, what it has only partly tested, and what it has not."""

from html import escape

import pandas as pd
import streamlit as st

from dashboard import readiness
from dashboard.components import card, card_title, html, note, page_header


def readiness_summary_html() -> str:
    """Four boxes: one per status, with its count. Shared with the Overview."""
    c = readiness.counts()
    boxes = "".join(f'<div class="ready-box" style="--c: var(--{token})"><b>{c[key]}</b><span>{escape(label)}</span></div>'
                    for key, (label, token) in readiness.STATUS.items())
    return f'<div class="ready-grid">{boxes}</div>'


def _table() -> pd.DataFrame:
    return pd.DataFrame([{"Status": readiness.STATUS[i["status"]][0], "Area": i["area"], "Capability": i["name"],
                          "Evidence": i["evidence"], "Source": i["source"]} for i in readiness.ITEMS])


def render():
    page_header("Security Readiness", "What has been tested, what has not, and where each claim comes from")
    with card("ready_summary"):
        card_title("Readiness summary")
        html(readiness_summary_html())
        note("Copied by hand from the workbench's threat model and phase results, which each row names. The dashboard "
             "does not measure these. Untested items are not claimed to work.")
    st.write("")
    order = list(readiness.STATUS)
    for key in order:
        label, token = readiness.STATUS[key]
        rows = _table()
        rows = rows[rows["Status"] == label]
        if rows.empty:
            continue
        with card(f"ready_{key}"):
            card_title(f"{label} ({len(rows)})")
            st.dataframe(rows.drop(columns=["Status"]), hide_index=True, width="stretch",
                         column_config={"Area": st.column_config.TextColumn(width="small"),
                                        "Capability": st.column_config.TextColumn(width="medium"),
                                        "Evidence": st.column_config.TextColumn(width="large"),
                                        "Source": st.column_config.TextColumn(width="medium")})
        st.write("")

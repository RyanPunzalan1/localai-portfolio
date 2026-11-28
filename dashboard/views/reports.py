"""Reports page: the workbench's static reports and the evidence behind them, offered for download as written.

Reports are never rendered inside the dashboard. The HTML report is built to be opened on its own (escaped text, no
scripts, a strict content-security policy); embedding it here would drop that protection. The Markdown is shown as
plain text only, so agent-written text in it can't turn into links or images.
"""

from datetime import datetime

import pandas as pd
import streamlit as st

from dashboard import data
from dashboard.components import card, card_title, empty_state, note, page_header
from dashboard.store import snapshot
from dashboard.timefmt import month_day

MIME = {".html": "text/html", ".md": "text/markdown", ".jsonl": "application/x-ndjson", ".json": "application/json"}


def selection_export(trials: pd.DataFrame) -> tuple[bytes, bytes]:
    """The current trials as CSV and as JSON lines (the original records). Shared with other pages."""
    flat = trials.drop(columns=["raw", "tool_calls"], errors="ignore")
    csv = flat.to_csv(index=False).encode("utf-8")
    import json
    lines = "\n".join(json.dumps(r, sort_keys=True, default=str) for r in trials["raw"]) + "\n" if len(trials) else ""
    return csv, lines.encode("utf-8")


def render():
    page_header("Reports", "Download assessment reports and the evidence they were built from")
    reports = data.find_reports()
    if not reports:
        empty_state("No reports found", "The workbench writes reports under experiments/workbench_phase*/ when a batch "
                    "finishes. In Docker, those folders are only visible if they are mounted.", icon_name="file")
    for i, rep in enumerate(reports):
        summary = rep["summary"]
        with card(f"report_{i}"):
            card_title(rep["name"])
            when = (lambda t: f"{month_day(t)}, {t:%Y %H:%M}")(datetime.fromtimestamp(rep["modified"]))
            facts = [f"Written {when}"]
            if "workbench_phase5" in rep["name"]:
                facts.append("Phase 5 gate test of the report's escaping and number check, not an evaluation")
            if summary:
                facts.append(f'{summary.get("completed", "?")} of {summary.get("planned", "?")} trials completed')
                if summary.get("anomaly"):
                    facts.append("anomaly: the batch stopped (see the report)")
            note(" · ".join(facts))
            cols = st.columns(len(rep["files"]))
            for col, path in zip(cols, rep["files"]):
                with col:
                    st.download_button(path.name, data=path.read_bytes(), file_name=f"{rep['folder'].name}-{path.name}",
                                       mime=MIME.get(path.suffix, "application/octet-stream"),
                                       key=f"dl_{i}_{path.name}", icon=":material/download:", width="stretch")
            md = next((p for p in rep["files"] if p.suffix == ".md"), None)
            if md is not None:
                with st.expander("Preview (plain text)"):
                    st.code(md.read_text(encoding="utf-8", errors="replace")[:20000], language=None)
        st.write("")

    snap = snapshot()
    with card("export"):
        card_title("Export the trial results")
        if snap.trials.empty:
            st.caption("No trials loaded.")
        else:
            csv, jsonl = selection_export(snap.trials)
            c1, c2 = st.columns(2)
            c1.download_button("All trials (CSV)", csv, "localai-trials.csv", "text/csv", key="dl_csv",
                               icon=":material/download:", width="stretch")
            c2.download_button("All trials (original records, JSONL)", jsonl, "localai-trials.jsonl",
                               "application/x-ndjson", key="dl_jsonl", icon=":material/download:", width="stretch")
            note(f"{len(snap.trials)} trials from {snap.trials['run_id'].nunique()} runs. The CSV is the dashboard's "
                 "table; the JSONL holds each record exactly as the run wrote it.")

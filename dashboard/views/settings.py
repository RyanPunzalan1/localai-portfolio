"""Settings page: display note, which runs to include, and the result files in use (read-only)."""

import pandas as pd
import streamlit as st

from dashboard import data
from dashboard.components import card, note, page_header, section_title
from dashboard.store import snapshot


def _files_table(files: list[data.ResultFile]) -> pd.DataFrame:
    rows = []
    for f in files:
        try:
            size = f.path.stat().st_size
        except OSError:
            size = None
        rows.append({"File": f.path.name, "Type": f.suite, "Superseded": f.superseded,
                     "Folder": str(f.path.parent.relative_to(data.ROOT)), "Size (KB)": round(size / 1024, 1) if size else None})
    return pd.DataFrame(rows)


def render():
    page_header("Settings", "Display options and data sources")

    with card("display"):
        section_title("Display")
        note("Light or dark follows your system setting, so charts, tables and controls always match.")

    with card("data"):
        section_title("Data")
        st.toggle("Include superseded runs", key="include_superseded",
                  help="Runs replaced after a bug was found. Shown with a 'superseded' marker when included.")
        st.toggle("Mock data", value=False, disabled=True,
                  help="No mock fixtures exist yet. When added, every page shows a MOCK DATA banner.")
        note("The dashboard only reads these files. It never writes, moves or deletes results.")

    snap = snapshot()
    with card("files"):
        section_title("Result files in use")
        files = snap.security_files + snap.model_files
        if files:
            st.dataframe(_files_table(files), hide_index=True, width="stretch")
        else:
            st.caption("No result files found.")
        if snap.bad_lines:
            st.warning(f"{len(snap.bad_lines)} line(s) could not be read and were skipped: "
                       + ", ".join(f"{name} line {n}" for name, n in snap.bad_lines[:10]))

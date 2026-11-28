"""Cached access to result files for the views. Read-only.

The cache key includes every file's size and modification time, so a new or growing results file
(an experiment still running) is picked up on the next rerun without a manual refresh.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd
import streamlit as st

from dashboard import data


@dataclass
class Snapshot:
    trials: pd.DataFrame
    model_tests: dict[str, pd.DataFrame]
    security_files: list[data.ResultFile]
    model_files: list[data.ResultFile]
    bad_lines: list[tuple[str, int]] = field(default_factory=list)
    run_notes: dict = field(default_factory=dict)  # the back end's notes on model-test files


def _signature(files: list[data.ResultFile]) -> tuple:
    sig = []
    for f in files:
        try:
            s = f.path.stat()
            sig.append((str(f.path), s.st_size, s.st_mtime_ns))
        except OSError:
            sig.append((str(f.path), -1, -1))
    return tuple(sig)


@st.cache_data(show_spinner=False, max_entries=8)
def _load(include_superseded: bool, _sec: list, _mod: list, signature: tuple) -> Snapshot:
    report = data.LoadReport(bad_lines=[])
    trials = data.load_trials(_sec, report)
    tests = data.load_model_tests(_mod, report)
    return Snapshot(trials, tests, _sec, _mod, report.bad_lines, data.load_run_notes(data.MODEL_TEST_DIR))


def snapshot() -> Snapshot:
    include = bool(st.session_state.get("include_superseded", False))
    sec = data.discover(data.SECURITY_DIR, include_superseded=include)
    for folder in data.WORKBENCH_DIRS:
        sec += data.discover(folder, include_superseded=include)
    mod = data.discover(data.MODEL_TEST_DIR, include_superseded=include)
    notes = data.ResultFile(data.MODEL_TEST_DIR / data.RUN_NOTES, "notes", "notes", False)
    return _load(include, sec, mod, _signature(sec) + _signature(mod) + _signature([notes]))

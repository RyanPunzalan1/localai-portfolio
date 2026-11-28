"""Evidence viewer for one trial: the observer's timeline and fields, plus every schema-1 evidence field.

All record text is escaped. Agent self-reported text is never shown, because it never decides an outcome.
"""

import json
from html import escape

import streamlit as st

from dashboard import data
from dashboard.components import evidence_panel, html
from dashboard.theme import icon  # noqa: F401  (kept for callers that build headers)


def _yes(v) -> str:
    return "unknown" if v is None else ("yes" if v else "no")


def workbench_evidence_html(rec: dict) -> str:
    """The schema-1 evidence fields, as plain rows. Agent-written text is escaped; self-reported text is not shown."""
    ev = rec.get("evidence") if isinstance(rec.get("evidence"), dict) else {}
    out = []
    preds = (rec.get("outcome") or {}).get("predicates") or {}
    if preds:
        out.append('<div class="ev-section">Predicates (decided from the evidence)</div>')
        out += [f'<div class="pred"><span class="mono">{escape(str(k))}</span><span>{_yes(v)}</span></div>'
                for k, v in preds.items()]
    mc = ev.get("model_channel")
    if isinstance(mc, dict):
        out.append('<div class="ev-section">Model channel (host side)</div>')
        for k in ("requests", "forwarded", "refused", "canaries_in_prompt", "tool_calls_requested"):
            v = mc.get(k)
            v = ", ".join(map(str, v)) if isinstance(v, list) else v
            out.append(f'<div class="pred"><span>{escape(k.replace("_", " "))}</span><span class="mono">{escape(str(v if v not in (None, "") else "none"))}</span></div>')
    approvals = ev.get("approvals") or []
    out.append('<div class="ev-section">Approvals requested</div>')
    if approvals:
        out += [f'<div class="pred"><span class="mono">{escape(str(a.get("action")))} {escape(str(a.get("target")))}</span>'
                f'<span>{escape(str(a.get("decision")))}</span></div>' for a in approvals if isinstance(a, dict)]
    else:
        out.append('<div class="pred"><span>none</span><span></span></div>')
    ws = ev.get("workspace") or {}
    out.append('<div class="ev-section">Workspace changes</div>')
    out += [f'<div class="pred"><span>{k}</span><span class="mono">{escape(", ".join(map(str, ws.get(k) or [])) or "none")}</span></div>'
            for k in ("created", "modified", "removed")]
    net = ev.get("network_log")
    if isinstance(net, dict):
        out.append('<div class="ev-section">Network log (names are agent-influenced, rank 3)</div>')
        out.append(f'<div class="pred"><span>blocked / allowed</span><span>{escape(str(net.get("blocked")))} / '
                   f'{escape(str(net.get("allowed")))}</span></div>')
    iso = rec.get("isolation") if isinstance(rec.get("isolation"), dict) else {}
    if iso:
        out.append('<div class="ev-section">Isolation checks</div>')
        out += [f'<div class="pred"><span>{escape(k.replace("_", " "))}</span><span>{_yes(iso.get(k))}</span></div>'
                for k in ("config_ok", "preflight_ok", "runtime_log_ok", "negative_control_ok")]
    return "".join(out)


def evidence_viewer(row: dict) -> None:
    left, right = st.columns([3, 2], gap="large")
    with left:
        evidence_panel(row)
    with right:
        raw = row.get("raw") or {}
        if row.get("suite") == data.WORKBENCH_SUITE:
            sub = (raw.get("outcome") or {}).get("sub")
            if sub:
                html(f'<div class="ev-section">Reason</div><div class="pred"><span>{escape(str(sub))}</span></div>')
            html(workbench_evidence_html(raw))
        else:
            html('<div class="ev-section">Record type</div>'
                 f'<div class="pred"><span>{escape(str(row.get("suite")))}</span><span>observer fields shown on the left</span></div>')
        st.download_button("Download this record (JSON)", json.dumps(raw, indent=2, sort_keys=True, default=str),
                           file_name=f"{row.get('run_id')}-{row.get('item')}.json", mime="application/json",
                           key="dl_record", icon=":material/download:")



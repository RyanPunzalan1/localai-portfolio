"""
approval_view.py - how the Approvals inbox shows a proposal's provenance and reviewer warnings (Phase 2).

Display only. Nothing here approves, rejects or changes a proposal, and app.py's Approve and Reject buttons
do not read these functions. Both fields are optional: older items and code-step proposals have neither.

Every value comes from a pending-write item and may include file names or text the model saw, so all of
it is HTML-escaped. The file lists are shown under separate labels with provenance.EVIDENCE_NOTE, so a
listed file is not read as the cause of the proposal.
"""

from html import escape

from provenance import EVIDENCE_NOTE, REQUEST_LABELS

# Strongest first, as the back end defines them. Unknown codes are still shown, after these.
WARNING_ORDER = ["request_no_change", "request_read_only", "target_not_in_request", "answer_claims_done",
                 "not_mentioned_in_answer"]

# (field, label) in display order. Labels match the field names: read / retrieved / named in answer.
FILE_LISTS = [
    ("files_read", "Files read"),
    ("files_retrieved", "Files retrieved (search)"),
    ("files_named_in_answer", "Files named in the answer"),
]


def warnings_of(item) -> list:
    """The item's warnings as [{'code', 'message'}], strongest first. Malformed entries are dropped."""
    raw = item.get("warnings") if isinstance(item, dict) else None
    if not isinstance(raw, list):
        return []
    found = [w for w in raw if isinstance(w, dict) and (w.get("message") or w.get("code"))]

    def rank(w):
        code = w.get("code")
        return WARNING_ORDER.index(code) if code in WARNING_ORDER else len(WARNING_ORDER)

    return sorted(found, key=rank)


def warnings_html(item) -> str:
    """A warning box for above Approve/Reject, or '' when there are none."""
    found = warnings_of(item)
    if not found:
        return ""
    lines = "".join(f"<li>{escape(str(w.get('message') or w.get('code')))}</li>" for w in found)
    return (f'<div class="prov-warn" role="alert"><b>Check before approving</b>'
            f'<ul>{lines}</ul></div>')


def _names(value) -> str:
    if not isinstance(value, (list, tuple)) or not value:
        return "none"
    return ", ".join(str(v) for v in value)


def provenance_rows(item) -> list:
    """[(label, value)] for the provenance section, or [] when the item has no provenance."""
    prov = item.get("provenance") if isinstance(item, dict) else None
    if not isinstance(prov, dict):
        return []
    intent = prov.get("request_intent")
    rows = [
        ("Proposed by tool", str(prov.get("tool") or "not recorded")),
        ("Request type", REQUEST_LABELS.get(intent, str(intent) if intent else "not recorded")),
    ]
    rows += [(label, _names(prov.get(field))) for field, label in FILE_LISTS[:2]]
    listed = prov.get("files_listed")
    rows.append(("File names listed", "not recorded" if listed is None else
                 ("yes (names only, no file text)" if listed else "no")))
    rows.append((FILE_LISTS[2][1], _names(prov.get(FILE_LISTS[2][0]))))
    return rows


def provenance_html(item) -> str:
    """The provenance section's body: labelled rows and the back end's note, or '' when absent."""
    rows = provenance_rows(item)
    if not rows:
        return ""
    prov = item["provenance"]
    note = prov.get("note") or EVIDENCE_NOTE
    cells = "".join(f'<div class="prov-k">{escape(k)}</div><div class="prov-v">{escape(v)}</div>' for k, v in rows)
    return f'<div class="prov-grid">{cells}</div><div class="prov-note">{escape(str(note))}</div>'

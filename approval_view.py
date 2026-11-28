"""
approval_view.py - how the Approvals inbox shows a proposal's provenance and reviewer warnings (Phase 2),
what Approve will do, and the Chat tab's "changes waiting" line (security fix 2).

Display only. Nothing here approves, rejects or changes a proposal, and app.py's Approve and Reject buttons
do not read these functions. Both fields are optional: older items and code-step proposals have neither.

Every value comes from a pending-write item and may include file names or text the model saw, so all of
it is HTML-escaped. The file lists are shown under separate labels with provenance.EVIDENCE_NOTE, so a
listed file is not read as the cause of the proposal.
"""

import re
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


# --------------------------------------------------------------- security fix 2: what Approve will do
def waiting_banner(count) -> str:
    """The Chat tab's line when writes are waiting, decided by the inbox count, never by the model's wording.
    Empty when nothing is waiting. Plain text (no HTML)."""
    if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
        return ""
    noun = "change is" if count == 1 else "changes are"
    return f"{count} {noun} waiting for your approval in the Approvals tab. Nothing is saved yet."


def target_html(plan) -> str:
    """One line on an inbox card saying exactly what Approve will do (agent.planned_target). HTML-escaped."""
    if not isinstance(plan, dict) or not plan.get("text"):
        return ""
    css = "target refused" if plan.get("action") == "refused" else "target"
    return f'<div class="{css}">{escape(str(plan["text"]))}</div>'


# --------------------------------------------------------------- versioned data: an inbox file that could not be used
_SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]{1,120}$")


def unreadable_notice(names) -> str:
    """The Approvals tab's warning when the saved inbox could not be used and was set aside (data_schema.py, D2).
    Plain text (no HTML); empty when nothing was set aside. A name that isn't a plain file name is not shown."""
    names = [n for n in (names or []) if isinstance(n, str)]
    if not names:
        return ""
    shown = ", ".join(f"logs/{n}" for n in names if _SAFE_NAME.match(n)) or "files in logs/"
    noun = "A saved approvals file" if len(names) == 1 else f"{len(names)} saved approvals files"
    return (f"{noun} could not be used (damaged, or written by a newer version of the app), so it was set aside, not "
            f"deleted: {shown}. Changes that were waiting in it are not shown here. "
            "Run `python -m data_schema check` to see more, and delete the copy when you no longer need it.")

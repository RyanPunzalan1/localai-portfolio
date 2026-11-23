"""
provenance.py - what the agent looked at before a proposal, and warnings for the human reviewer.

Phase 2 (approval visibility). Nothing here approves, blocks or changes a proposal: it only adds
information to the approvals inbox. The approval code (agent.approve_write) reads name, content and
mode, never these fields, so a warning (or its absence) can never approve anything.

Evidence is kept apart by how it was observed, and none of it claims a cause:
  files_read       files whose text a tool returned in this request before the proposal
                   (read_file, list_tasks)
  files_retrieved  files whose passages a search returned before the proposal (search_docs, find_lessons)
  files_listed     True if the agent listed file names before the proposal (names only, no text)
  target           the file the proposal would change
  files_named_in_answer  real file names that appear in the agent's final answer

Privacy: like the activity log, nothing here stores what the user typed. The request is classified
in memory and only the label (for example "read_only") is kept.
"""

import re

EVIDENCE_NOTE = ("Files the agent read or retrieved in this request before proposing the change. "
                 "This shows what it saw, not what caused the proposal.")

# Tools whose successful result is a file's text, and which file.
READ_TOOLS = {"read_file": lambda args: args.get("name"), "list_tasks": lambda args: "tasks.md"}
# Tools whose result is search passages tagged with their source file.
SEARCH_TOOLS = {"search_docs", "find_lessons"}

_NO_CHANGE = [
    r"\b(don'?t|do not|never|without)\s+(\w+\s+){0,2}(chang|modif|edit|sav|writ|delet|touch|updat|add|remov)",
    r"\bread[- ]only\b", r"\b(just|only)\s+(read|look|show|tell|summari[sz]e|explain|list|check)\b",
    r"\bno (changes|edits)\b",
]
_CHANGE = [
    (r"\b(save|saving|add|create|write|mark|complete|update|change|edit|delete|remove|rename|append|"
     r"remember|move|copy|replace|fix|draft|check off|tick off|note (this|that|down|it)|make a note|"
     r"take a note|propose)\b"),
    r"\bnew (task|note|lesson)\b",                      # "New task: renew passport"
    r"\b(put|stick|pop)\b.{0,60}\b(on|in|to|onto)\b.{0,15}\blist\b",  # "Put 'email Sam' on my list"
    r"^\s*(note|lesson|task)\s*:|\bnote (for|to self)\b",  # "Note for future projects: ...", "Lesson: ..."
    r"\b(on|to) my (task |to-?do )?list\b",
]
_READ = (r"\b(summari[sz]e|summary|explain|what|which|who|when|where|why|how|show|list|read|open|inspect|"
         r"describe|tell me|find|search|look|compare|review|is there|are there|do i have|any)\b")

REQUEST_LABELS = {
    "no_change": "The request explicitly asked for no changes.",
    "read_only": "The request only asked to read, find, summarize or explain.",
    "change": "The request asked for a change.",
    "unclear": "The request's intent is unclear.",
}

_CLAIMS_DONE = (r"\b(saved|written|wrote|updated|deleted|removed|created|marked (as )?(done|complete)|"
                r"completed|approved|done)\b")
# Words that say the change is still waiting. A bare "approved" is NOT one: "the user has already
# approved this" is the claim an attacker plants, so it must not count as "still pending".
_PROPOSED = (r"\b(propos\w*|pending|waiting|awaiting|not (yet )?(saved|changed|written|applied)|"
             r"(needs?|requires?|for|await) (your )?approval|approve (it|this|them)|once you approve|"
             r"until you approve|if you approve|review)\b")


def classify_request(text) -> str:
    """'no_change', 'read_only', 'change' or 'unclear'. A rough reading for reviewers, not a rule."""
    t = str(text or "").lower().replace("’", "'")
    if any(re.search(p, t) for p in _NO_CHANGE):
        return "no_change"
    if any(re.search(p, t) for p in _CHANGE):
        return "change"
    if re.search(_READ, t):
        return "read_only"
    return "unclear"


def sources_in_search_result(result: str) -> list:
    """File names a search result tags its passages with ('[name.md]' on its own line)."""
    names = re.findall(r"^\[([^\[\]\n]{1,120}\.(?:md|txt))\]\s*$", str(result or ""), flags=re.M)
    return list(dict.fromkeys(names))


def files_named(text, known_names) -> list:
    """Known file names that appear in a text (case-insensitive, whole names only)."""
    t = str(text or "").lower()
    return [n for n in known_names if re.search(r"(?<![\w.-])" + re.escape(n.lower()) + r"(?![\w-])", t)]


# Proposals made through these tools target the task list, which a request rarely names as a file.
TASK_TOOLS = {"add_task", "complete_task"}


def files_in_request(text) -> list:
    """File names (.md or .txt) the user's request mentions. Kept in memory only, never stored."""
    names = re.findall(r"(?<![\w.-])([\w-][\w.-]*\.(?:md|txt))(?![\w-])", str(text or ""), flags=re.I)
    return list(dict.fromkeys(n.lower() for n in names))


def warnings_for(request_intent: str, answer: str, item: dict, request_files=None) -> list:
    """Reviewer warnings for one proposal made during a request. Each is a hint, not proof."""
    out = []
    if request_intent == "no_change":
        out.append({"code": "request_no_change",
                    "message": "The request explicitly asked for no changes, but the agent proposed one."})
    elif request_intent == "read_only":
        out.append({"code": "request_read_only",
                    "message": "The request only asked to read or explain. This change was not requested."})
    tool = (item.get("provenance") or {}).get("tool")
    target = str(item.get("name") or "").lower()
    # A change request that names files, with a proposal to a different note: the proposal is extra.
    # Task proposals are exempt (the task list is not usually named), as are requests naming no file.
    if (request_intent == "change" and request_files and tool not in TASK_TOOLS
            and target and target not in request_files):
        out.append({"code": "target_not_in_request",
                    "message": f"The request named {', '.join(request_files)} but this proposal changes "
                               f"{item.get('name')}, which it did not name."})
    a = str(answer or "").lower().replace("’", "'")
    if re.search(_CLAIMS_DONE, a) and not re.search(_PROPOSED, a):
        out.append({"code": "answer_claims_done",
                    "message": "The agent's answer says a change was made or approved. Nothing is changed "
                               "until you approve it here."})
    # "Mentioned" means the answer names the file, or (for task proposals) talks about tasks at all.
    mentioned = bool(target and target in a) or (tool in TASK_TOOLS and "task" in a)
    if not re.search(_PROPOSED, a) and not mentioned:
        out.append({"code": "not_mentioned_in_answer",
                    "message": "The agent's answer does not mention this proposal."})
    return out

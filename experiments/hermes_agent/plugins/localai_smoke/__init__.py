"""LocalAI stand-in tools for testing models under Hermes Agent (design/hermes-agent-llm-eval-plan.md).

Read tools (T1) and staged-write tools (T2+) with the same names, descriptions and messages as
LocalAI's agent.py and tasks pack, over a folder of dummy notes inside the sandbox. Not LocalAI's own
code: the final test uses LocalAI's tools through an MCP server.

- Writes are never applied. save_note, add_task and complete_task only append a proposal to
  PENDING_LOG, like LocalAI's approvals inbox. No file in DOCS is ever changed.
- Every call is logged to CALL_LOG, so scoring does not depend on the model's text.
- A pre_tool_call hook blocks any tool that is not enabled here.
- Which tools are enabled comes from TOOLSET_FILE (one name per line; default: all). Hermes does not
  pass environment variables through to plugins, so a file is used.
- T4 planted failures come from FAULTS_FILE: {"<tool>|<name or text>": N} makes that call fail with a
  temporary error N times, then work. The count is kept in the file, since each case is a new process.
"""

import json
import time
from pathlib import Path

WORK = Path("/home/agent/workspace")
DOCS = (WORK / "docs").resolve()
CALL_LOG = WORK / "calls.jsonl"
PENDING_LOG = WORK / "pending.jsonl"
TOOLSET_FILE = WORK / "toolset.txt"
FAULTS_FILE = WORK / "faults.json"
TASKS_FILE = "tasks.md"
SUFFIXES = {".md", ".txt"}
MAX_READ_CHARS = 8000
MAX_TASK_CHARS = 200


def _log(path: Path, event: dict) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"time": round(time.time(), 3), **event}) + "\n")


def _clean_name(name) -> str:
    return Path(str(name or "").replace("\\", "/")).name  # drop folders and ../ tricks


def _wrap(label: str, text: str) -> str:
    return f'<document name="{label}">\n{text}\n</document>'


PLAIN_FLAG = WORK / "plain_results"  # present = return plain text like LocalAI's tools, not JSON (plan 3.6)


def _result(tool: str, args: dict, status: str, out: dict) -> str:
    _log(CALL_LOG, {"tool": tool, "args": args, "status": status})
    if PLAIN_FLAG.is_file():
        if "files" in out:
            return "\n".join(out["files"])
        return str(next(iter(out.values())))
    return json.dumps(out)


def _planted_fault(tool: str, args: dict):
    """A planted temporary error for this call, if FAULTS_FILE asks for one (T4). Else None."""
    if not FAULTS_FILE.is_file():
        return None
    faults = json.loads(FAULTS_FILE.read_text() or "{}")
    key = f"{tool}|{args.get('name') or args.get('text') or ''}"
    if faults.get(key, 0) > 0:
        faults[key] -= 1
        FAULTS_FILE.write_text(json.dumps(faults))
        return _result(tool, args, "error",
                       {"error": "Temporary error: the notes service did not respond. Try again."})
    return None


# ---------------------------------------------------------------- read tools
def _list_files(args: dict, **kwargs) -> str:
    fault = _planted_fault('list_files', args)
    if fault:
        return fault
    try:
        names = sorted(p.name for p in DOCS.iterdir()
                       if p.is_file() and not p.is_symlink() and p.suffix.lower() in SUFFIXES)
        return _result("list_files", args, "ok", {"files": names or ["(no files yet)"]})
    except Exception as e:  # never raise into Hermes
        return _result("list_files", args, "error", {"error": str(e)})


def _read_file(args: dict, **kwargs) -> str:
    fault = _planted_fault('read_file', args)
    if fault:
        return fault
    clean = _clean_name(args.get("name"))
    path = DOCS / clean
    try:
        if Path(clean).suffix.lower() not in SUFFIXES:
            return _result("read_file", args, "refused", {"error": "Only .txt and .md files are allowed."})
        if path.is_symlink() or not path.is_file():
            return _result("read_file", args, "missing",
                           {"error": f"'{clean}' does not exist. Use list_files first."})
        text = path.read_text(encoding="utf-8", errors="replace")[:MAX_READ_CHARS]
        return _result("read_file", args, "ok", {"content": _wrap(clean, text)})
    except Exception as e:
        return _result("read_file", args, "error", {"error": str(e)})


def _list_tasks(args: dict, **kwargs) -> str:
    fault = _planted_fault('list_tasks', args)
    if fault:
        return fault
    path = DOCS / TASKS_FILE
    if not path.is_file():
        return _result("list_tasks", args, "ok", {"content": "(no tasks yet)"})
    text = path.read_text(encoding="utf-8", errors="replace")[:MAX_READ_CHARS]
    return _result("list_tasks", args, "ok", {"content": _wrap("tasks", text)})


# ------------------------------------------------------ staged-write tools
def _save_note(args: dict, **kwargs) -> str:
    fault = _planted_fault('save_note', args)
    if fault:
        return fault
    clean = _clean_name(args.get("name"))
    content = str(args.get("content") or "")
    if Path(clean).suffix.lower() not in SUFFIXES:
        return _result("save_note", args, "refused", {"error": "Only .txt and .md files are allowed."})
    _log(PENDING_LOG, {"tool": "save_note", "name": clean, "content": content})
    return _result("save_note", args, "staged", {
        "result": f"Proposed saving '{clean}'. It is NOT saved yet; waiting for the user to approve."})


def _add_task(args: dict, **kwargs) -> str:
    fault = _planted_fault('add_task', args)
    if fault:
        return fault
    clean = " ".join(str(args.get("text") or "").split())[:MAX_TASK_CHARS]
    if not clean:
        return _result("add_task", args, "error", {"error": "Error: the task text is empty."})
    _log(PENDING_LOG, {"tool": "add_task", "text": clean})
    return _result("add_task", args, "staged", {
        "result": "Proposed a new task. It is NOT saved yet; waiting for the user to approve."})


def _complete_task(args: dict, **kwargs) -> str:
    fault = _planted_fault('complete_task', args)
    if fault:
        return fault
    clean = " ".join(str(args.get("text") or "").split())[:MAX_TASK_CHARS]
    if not clean:
        return _result("complete_task", args, "error", {"error": "Error: the task text is empty."})
    path = DOCS / TASKS_FILE
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    if f"- [ ] {clean}" not in [x.rstrip() for x in lines]:
        return _result("complete_task", args, "no_match",
                       {"error": "Error: no open task with that text. Call list_tasks to check."})
    _log(PENDING_LOG, {"tool": "complete_task", "text": clean})
    return _result("complete_task", args, "staged", {
        "result": "Proposed marking the task done. It is NOT changed yet; waiting for the user to approve."})


def _schema(name, description, props=None, required=()):
    return {"name": name, "description": description,
            "parameters": {"type": "object", "properties": props or {}, "required": list(required)}}


def _string(description):
    return {"type": "string", "description": description}


TOOLS = {
    "list_files": (_list_files, _schema("list_files", "List the note files available in the docs folder.")),
    "read_file": (_read_file, _schema("read_file", "Read the full text of one note from the docs folder.",
                                      {"name": _string("The file name, for example 'ideas.md'.")}, ["name"])),
    "save_note": (_save_note, _schema(
        "save_note", "Propose saving a note to the docs folder. The user must approve it.",
        {"name": _string("The file name to save, ending in .md or .txt."),
         "content": _string("The full text of the note.")}, ["name", "content"])),
    "list_tasks": (_list_tasks, _schema("list_tasks", "List the current tasks.")),
    "add_task": (_add_task, _schema(
        "add_task", "Propose adding a task. The user must approve it before it is saved.",
        {"text": _string("The task, in one short line.")}, ["text"])),
    "complete_task": (_complete_task, _schema(
        "complete_task", "Propose marking an open task as done. The user must approve it first.",
        {"text": _string("The task text, as it appears in the list.")}, ["text"])),
}


def _enabled() -> list:
    if TOOLSET_FILE.is_file():
        wanted = [x.strip() for x in TOOLSET_FILE.read_text().splitlines() if x.strip()]
        return [t for t in wanted if t in TOOLS]
    return list(TOOLS)


def _allowlist(tool_name=None, args=None, **kwargs):
    """Second allowlist: block any tool that is not enabled here, even if a toolset slipped through."""
    if tool_name not in _enabled():
        _log(CALL_LOG, {"tool": tool_name, "args": args, "status": "blocked_by_hook"})
        return {"action": "block", "message": f"Tool '{tool_name}' is not allowed in this test."}
    return None


API_LOG = WORK / "api.jsonl"


def _api_request(**kw):
    """Log the size of every model request (T5): prompt tokens, messages, finish reason, window."""
    usage = kw.get("usage") or {}
    _log(API_LOG, {"model": kw.get("model"), "messages": kw.get("message_count"),
                   "prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": usage.get("completion_tokens"),
                   "finish": kw.get("finish_reason"), "context_length": kw.get("context_length"),
                   "secs": round(kw.get("api_duration") or 0, 2)})


DUMP_FLAG = WORK / "dump_requests"  # present = write every full request to REQUEST_LOG (debugging)
REQUEST_LOG = WORK / "requests.jsonl"


def _dump_request(**kw):
    """Debugging only (plan 3.6): the exact payload Hermes sends to the model, when DUMP_FLAG exists."""
    if DUMP_FLAG.is_file():
        _log(REQUEST_LOG, {"request": kw.get("request"), "system_prompt": kw.get("system_prompt"),
                           "message_count": kw.get("message_count")})


def register(ctx):
    for name in _enabled():
        handler, schema = TOOLS[name]
        ctx.register_tool(name=name, toolset="localai_smoke", handler=handler, schema=schema, override=True)
    ctx.register_hook("pre_tool_call", _allowlist)
    ctx.register_hook("post_api_request", _api_request)
    ctx.register_hook("pre_api_request", _dump_request)

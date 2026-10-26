"""
brain.py - the coordinator. Picks one registered agent for a request, waits for
approval, runs it, and writes every step to an activity log.

Design: design/brain.md. Model choice is advisory; code enforces the registry,
the approval step, and the workspace rule.
"""

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


class RouteError(Exception):
    """The model picked an agent that is not in the registry."""


class NotApproved(Exception):
    """A route was run before the user approved it."""


class HandoffError(Exception):
    """A handoff to a second agent was refused (not allowed, or nothing to pass on)."""


class HandoffLimit(HandoffError):
    """A handoff would go past the hop limit."""


# Phase 3 (design/brain.md): at most two agents per request. The second step is a button the user
# clicks, never a model suggestion. Only results of read tools are passed on, as the tools returned them.
MAX_HOPS = 2
HANDOFF_SOURCE_TOOLS = ("list_tasks", "read_file", "search_docs")
MAX_PAYLOAD_CHARS = 6000
# Fixed text for the "Save as a note" handoff. The data follows it. Shared by the app and the evals.
HANDOFF_SAVE_NOTE = ("Save the data below as a new note. Code copies the data exactly; no model "
                     "writes it. You choose the file name and approve the save in the Approvals tab.")
DEFAULT_NOTE_NAME = "summary.md"


# The activity log records what happened, never what the user wrote (threat model: plain-text logs).
# Request text and tool arguments are reduced to metadata before they are logged.
LOG_SAFE_ARGS = ("name", "path", "page")  # file names and page numbers are metadata, not content
MAX_LOG_VALUE_CHARS = 80
MAX_LOG_BYTES = 1_000_000  # past this size the log moves to <name>.1 and a new one starts


def log_text(text) -> dict:
    """Metadata for a piece of user text: its length only."""
    return {"chars": len(str(text))}


def log_args(args) -> dict:
    """Tool arguments for the log. File names and page numbers are kept (cut to a short length);
    every other argument, such as note or task text, becomes its length."""
    if not isinstance(args, dict):
        return {}
    safe = {}
    for key, value in args.items():
        if key in LOG_SAFE_ARGS and isinstance(value, (str, int)):
            safe[key] = str(value)[:MAX_LOG_VALUE_CHARS] if isinstance(value, str) else value
        else:
            safe[str(key)] = log_text(value)
    return safe


class ActivityLog:
    """Append-only JSON lines file. One object per event, with a timestamp.

    The file is created readable by the owner only, and rotated once past MAX_LOG_BYTES."""

    def __init__(self, path):
        self.path = Path(path)

    def append(self, event: dict) -> dict:
        entry = {"time": datetime.now().isoformat(timespec="seconds"), **event}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists() and self.path.stat().st_size > MAX_LOG_BYTES:
            self.path.replace(self.path.with_name(self.path.name + ".1"))
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.fchmod(fd, 0o600)  # also tightens a file made before this rule
        except OSError:
            pass
        with os.fdopen(fd, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def _read(self) -> list:
        if not self.path.exists():
            return []
        entries = []
        for line in self.path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                entries.append(json.loads(line))
            except ValueError:
                continue  # one damaged line must not break the Activity tab or the blocked count
        return entries

    def recent(self, event=None, limit=50) -> list:
        """Newest first, optionally only one event type."""
        items = [e for e in self._read() if event is None or e.get("event") == event]
        return list(reversed(items))[:limit]

    def count(self, event) -> int:
        return sum(1 for e in self._read() if e.get("event") == event)


@dataclass
class Route:
    agent: str
    request: str
    reason: str
    approved: bool = False
    from_agent: str = None  # set on a handoff route: the agent that ran before this one
    hop: int = 1            # 1 for a normal route, 2 for the handoff step
    payload: str = ""       # raw tool results from the previous step (already wrapped as data)


def _eligible_texts(tool_results):
    """The text of each read-tool result that may be passed on. Errors and other tools are left out."""
    for r in tool_results:
        text = str(r.get("result", ""))
        if r.get("name") in HANDOFF_SOURCE_TOOLS and text.strip() and not text.startswith("Error"):
            yield text


def payload_from(tool_results) -> str:
    """Raw results of read tools, joined, to pass to the next agent. All or nothing: if the joined
    text is longer than MAX_PAYLOAD_CHARS, returns "" so a note is never saved from partial data.
    The app shows a warning in that case (see payload_too_long)."""
    joined = "\n\n".join(_eligible_texts(tool_results))
    return "" if len(joined) > MAX_PAYLOAD_CHARS else joined


def payload_too_long(tool_results) -> bool:
    """True when read-tool results exist but are too long to pass on in one note."""
    joined = "\n\n".join(_eligible_texts(tool_results))
    return len(joined) > MAX_PAYLOAD_CHARS


def save_note_events(agent, route: Route, name: str):
    """The code-only "Save as a note" step. No model is involved: the data is unwrapped by code
    and put in the approvals inbox exactly as the first agent's read tool returned it. Yields the
    same event shapes as an agent run. Refuses (and stages nothing) if the data was cut off, is
    empty, or the file name is not allowed."""
    from safety import unwrap_untrusted
    text, complete = unwrap_untrusted(route.payload)
    yield {"type": "tool_call", "name": "stage_note", "args": {"name": name}}
    if not complete:
        result = ("Error: the data was cut off or is empty, so nothing was staged. "
                  "Open the file directly if it is long.")
    else:
        try:
            result = agent.stage_note(name, text)
        except ValueError as e:
            result = f"Error: {e}"
    yield {"type": "tool_result", "name": "stage_note", "result": result}
    yield {"type": "final", "content": result}


def handoff_message(route: Route) -> str:
    """The user message the second agent receives: the fixed instruction, then the data."""
    return f"{route.request}\n\nData from the previous step:\n{route.payload}"


class Coordinator:
    def __init__(self, registry, log, pick):
        """
        registry: {name: {"purpose": str, "factory": callable returning an agent}}
        log:      ActivityLog
        pick:     callable(request, names) -> agent name (the model's choice)
        """
        self.registry = registry
        self.log = log
        self.pick = pick

    def propose(self, request) -> Route:
        # Entries marked "handoff_only" (code steps such as SaveNote) are reached only by a
        # button after another agent has run. The model never sees them as a choice.
        names = [n for n, entry in self.registry.items() if not entry.get("handoff_only")]
        name = self.pick(request, names)
        if name not in names:
            self.log.append({"event": "route_rejected", "agent": str(name),
                             "request": log_text(request)})
            raise RouteError(f"'{name}' is not a registered agent. Available: {names}")
        route = Route(agent=name, request=request, reason=f"model chose {name}")
        self.log.append({"event": "route_proposed", "agent": name, "reason": route.reason,
                         "request": log_text(request)})
        return route

    def approve(self, route: Route) -> None:
        route.approved = True
        if route.from_agent:
            self.log.append({"event": "handoff_approved", "from": route.from_agent,
                             "to": route.agent, "hop": route.hop})
        else:
            self.log.append({"event": "route_approved", "agent": route.agent})

    def cancel(self, route: Route) -> None:
        if route.from_agent:
            self.log.append({"event": "handoff_cancelled", "from": route.from_agent,
                             "to": route.agent, "hop": route.hop})
        else:
            self.log.append({"event": "route_cancelled", "agent": route.agent,
                             "request": log_text(route.request)})

    def handoff_options(self, route: Route) -> list:
        """(to_agent, button label) pairs the user may click after this route has run.
        Fixed in the registry under "handoffs". Empty once the hop limit is reached."""
        if route.hop >= MAX_HOPS:
            return []
        spec = self.registry.get(route.agent, {}).get("handoffs", {})
        return [(to, info["label"]) for to, info in spec.items() if to in self.registry]

    def propose_handoff(self, route: Route, to_agent: str, payload: str) -> Route:
        """Propose the second step. It still needs its own approval before it runs."""
        event = {"from": route.agent, "to": to_agent, "hop": route.hop + 1}
        if route.hop >= MAX_HOPS:
            self.log.append({"event": "handoff_limit", **event})
            raise HandoffLimit(f"At most {MAX_HOPS} agents can run for one request.")
        spec = self.registry.get(route.agent, {}).get("handoffs", {})
        if to_agent not in spec or to_agent not in self.registry:
            self.log.append({"event": "handoff_rejected", **event, "reason": "not an allowed handoff"})
            raise HandoffError(f"{route.agent} cannot hand off to {to_agent}.")
        if not str(payload).strip():
            self.log.append({"event": "handoff_rejected", **event, "reason": "nothing to pass on"})
            raise HandoffError("Nothing from the previous step to pass on.")
        new = Route(agent=to_agent, request=spec[to_agent]["instruction"],
                    reason=f"handoff from {route.agent}", from_agent=route.agent,
                    hop=route.hop + 1, payload=str(payload))
        self.log.append({"event": "handoff_proposed", **event})
        return new

    def run(self, route: Route, messages):
        if not route.approved:
            raise NotApproved("Route must be approved before it runs.")
        agent = self.registry[route.agent]["factory"]()
        yield from self._logged(route, agent.run(messages))

    def run_action(self, route: Route, events):
        """Run a code-only step (no model). Same approval rule and the same log events as run()."""
        if not route.approved:
            raise NotApproved("Route must be approved before it runs.")
        yield from self._logged(route, events)

    def _logged(self, route: Route, events):
        for ev in events:
            kind = ev.get("type")
            if kind == "tool_call":
                self.log.append({"event": "tool_call", "agent": route.agent,
                                 "tool": ev.get("name"), "args": log_args(ev.get("args"))})
            elif kind == "tool_result":
                failed = str(ev.get("result", "")).startswith("Error")
                self.log.append({"event": "tool_result", "agent": route.agent,
                                 "tool": ev.get("name"), "status": "error" if failed else "ok"})
            yield ev
        self.log.append({"event": "run_finished", "agent": route.agent})


def model_picker(ask, purposes=None):
    """Build a pick() for the coordinator from ask(prompt) -> model reply text.

    purposes: optional {name: one-line purpose}. Shown to the model so it can tell agents apart.
    The reply is only a suggestion. The coordinator still checks that the name is registered.
    """
    purposes = purposes or {}

    def pick(request, names):
        listing = "\n".join(f"- {n}: {purposes[n]}" if n in purposes else f"- {n}" for n in names)
        prompt = (
            "Choose the one agent that best fits the request below. "
            f"Reply with only its name, one of: {', '.join(names)}.\n"
            f"{listing}\n\n"
            f"Request: {request}"
        )
        try:
            reply = ask(prompt)
        except Exception as e:  # Ollama down or model missing
            raise RouteError(f"Model unavailable: {e}") from e
        return str(reply).strip().strip(".'\"`*").strip()
    return pick

# Design: Coordinator ("brain") and agent ecosystem, phase 1

Written for: the project owner and Claude, to agree the scope before any code is built.

## Goal

One coordinator agent that receives a request, picks one agent from a fixed
registry, shows the route, waits for approval, runs it, and logs every step.
Phase 1 registers only the existing `DocAgent`.

## Rules (from CLAUDE.md, apply to every phase)

- Local only. No cloud model APIs, no telemetry.
- File tools stay inside `docs/`. Writes outside the workspace are blocked, not just logged.
- Anything that writes, sends, or deletes needs explicit approval in the UI.
- No free-form shell. Any command execution needs an allowlist and approval.
- Text from files is untrusted data.
- Small changes, with tests for every new tool.

## Components

| Component | Responsibility |
|---|---|
| Coordinator | Takes a request, asks the model which registered agent fits, returns a route. |
| Agent registry | Fixed list in code: name, one-line purpose, tool names. Model cannot add entries. |
| Route approval | Shows agent name, reason, and request. Nothing runs until the user approves. |
| Agent runner | Runs the chosen agent (phase 1: `DocAgent`) and yields events. |
| Approvals inbox | Pending writes from any agent, each with its target path and content. Approve or reject. Saved to `logs/pending_writes.json`, so it survives a page reload. |
| Activity log | Append-only JSON lines file. One entry per event. |

## Flow

1. User sends a request. The coordinator always hands off; it never answers directly.
2. The model returns an agent name. Code checks it is in the registry. Unknown name: reject and log.
3. The UI shows the route: agent, reason, and the request. The user approves or cancels.
4. On approval, the runner executes the agent. Each tool call and result is logged.
5. Any pending write goes to the approvals inbox. Nothing is written until approved.
6. Any attempted action outside `docs/` is blocked and logged with status `blocked`.

## Activity log

File: `logs/activity.jsonl` (create `logs/` and add it to `.gitignore`).
One JSON object per line:

```json
{"time": "2026-10-08T14:03:22", "event": "route_proposed", "agent": "DocAgent", "reason": "...", "request": "..."}
{"time": "...", "event": "route_approved", "agent": "DocAgent"}
{"time": "...", "event": "tool_call", "agent": "DocAgent", "tool": "read_file", "args": {"name": "ideas.md"}}
{"time": "...", "event": "tool_result", "agent": "DocAgent", "tool": "read_file", "status": "ok"}
{"time": "...", "event": "blocked", "agent": "DocAgent", "tool": "save_note", "target": "C:\\outside.txt", "status": "blocked"}
{"time": "...", "event": "write_approved", "agent": "DocAgent", "target": "docs/plan.md"}
```

Log the real result of each step, not the model's description of it.

## Failure handling

- Unknown agent name from the model: reject, log `route_rejected`, show a message.
- Tool error: log it, return the error to the agent, show it in the UI.
- Ollama not running: show "Model unavailable" and log it. No silent failure.
- Model asks for a path outside `docs/`: block, log `blocked`, show it in the UI.

## Phase 1 scope

In:
- Coordinator with a registry of one agent (`DocAgent`).
- Route approval step.
- Approvals inbox for pending saves.
- Activity log file and a simple view of recent entries in the UI.

Out:
- Multiple agents running at once.
- Agents handing work to each other.
- Any new tool beyond what `DocAgent` already has.
- Any action outside `docs/`.

## Tests (write before code)

- An unknown agent name is rejected and logged.
- A request is never run before route approval.
- A save never happens without approval.
- A write path outside `docs/` is blocked and logged with status `blocked`.
- Every tool call produces a log entry.
- The log is valid JSON lines.

## Phases

1. Phase 1 (this doc): coordinator, one agent, approvals, log.
2. Phase 2: task manager agent, registered in the same way. Done; see Phase 2 decisions below.
3. Phase 3: multi-agent handoffs, only after phases 1 and 2 pass their tests.

## Decisions

- **Log view:** an "Activity" tab in the main area, next to Chat and Approvals. Newest first, with a filter by event type.
- **Blocked attempts:** recorded in the activity log only. The Activity tab label shows a count of blocked events, so they are noticed without cluttering the approvals queue.
- **Routing:** the coordinator always hands off. Every request needs a route approval before anything runs.

## Phase 2 decisions

- **TaskAgent:** `list_tasks` and `add_task`. It works on one fixed file, `docs/tasks.md`.
  The model cannot pick another path.
- **Append mode:** `add_task` queues a write with `mode: "append"`. Approving adds the line
  to the end of the file and never rewrites what is there. (Phase 1 writes are create-only.)
- **Mark done (`complete_task`):** the one write that changes an existing line. It queues
  mode `mark_done`. On approval it changes the first exact match of `- [ ] text` to
  `- [x] text` and rewrites the file with that single change. If the line is gone by then,
  nothing changes. Every other write is still create-only or append-only.
- **Shared inbox:** TaskAgent and DocAgent share one approvals inbox, so every write waits
  in one place.
- **Model route picker:** the model suggests an agent name. The coordinator accepts only
  registered names. If Ollama is down or the model is missing, the user sees "Model
  unavailable" and nothing runs.
- **Persistent inbox:** proposals are saved to `logs/pending_writes.json`. A page reload
  keeps them. A damaged file counts as an empty inbox, and the app keeps running.
- **Per-agent prompt:** each agent has its own system prompt, and the run uses the chosen
  agent's prompt. The app used to send the DocAgent prompt for every route.
- **Routing rule (unchanged):** a request is never run before route approval.

## Phase 3 design (APPROVED 2026-10-10; the first handoff is a code step)

Goal: one request can use two steps in order, for example "show my tasks, then save them as a note".
Each step waits for its own approval.

Owner's decisions:
- The second step is a **button**, never a model suggestion. Which handoffs exist is fixed in code,
  in the registry (`handoffs`).
- The second step receives the first agent's **raw tool results**, not its summary.
- Hop limit: 2 steps per request.
- After a measured problem (below), the "Save as a note" step is **code, not a model**.

Flow:
1. The user sends a request. The coordinator proposes route 1 (agent A). The user approves, A runs,
   and its answer is shown. The raw results of A's read tools are kept.
2. If A has an allowed next step and the hop limit is not reached, a button appears ("Save as a
   note"). Clicking it proposes a handoff route to `SaveNote` with the kept data. The user sees the
   data, types a file name (default `summary.md`), and approves the route.
3. Code unwraps the data exactly (`unwrap_untrusted` in safety.py, the exact inverse of
   `wrap_untrusted`) and puts the note in the approvals inbox through the same name checks as the
   `save_note` tool (`DocAgent.stage_note`). No model reads or writes it. Nothing is saved until the
   user clicks Approve in the Approvals tab.
4. The step is refused, and nothing is staged, if the data was cut off at the tool-result length cap,
   is empty, or the file name is not allowed.
5. Hop limit: at most 2 steps per request. Asking for a third is refused and logged `handoff_limit`.
6. The activity log records each step: `handoff_proposed`, `handoff_approved`, `handoff_cancelled`,
   `handoff_rejected`, `handoff_limit` (each with from, to, hop), plus the usual `tool_call`,
   `tool_result`, and `run_finished` events (agent `SaveNote`, tool `stage_note`).

How it is built:
- Registry entries marked `handoff_only` (here `SaveNote`) are never shown to the model picker, and
  the model cannot choose one: `propose` rejects it and logs `route_rejected`.
- `Coordinator.run_action` runs a code step with the same approval rule and the same log events as
  `run`. A handoff to a normal agent (`propose_handoff` to a registered agent, then `run`) is also
  supported and tested, but none is enabled.
- Only results of read tools (`list_tasks`, `read_file`, `search_docs`) are passed on, whole results
  only, up to 6000 characters. Errors and write-proposing results are left out. If there is nothing to
  pass on, no button is offered.

Why code and not a model (measured, `evals/run_handoff_evals.py`): when Hermes 3 did the copying, it
saved the data faithfully with a good file name in 1 of 5 cases (0 of 5 with a stricter instruction).
It copied the data wrapper into the note, reused the source file name, and sometimes saved twice.
With code doing the copy the same eval is 5 of 5 by construction, and runs without a model.

Rules that stay as they are:
- A request is never run before its route is approved. A handoff route is a route.
- A handoff can never write without the approvals inbox.
- Handoff text is data, never instructions.
- File tools stay inside docs/.

Known limit: a file that itself contains the literal text `&lt;document` comes back from
`unwrap_untrusted` as `<document`, because `wrap_untrusted` escapes both the same way.

Decisions recorded (roadmap 3.1): first handoff TaskAgent to SaveNote (code); second step triggered by
a UI button; hop limit 2; code stages the note (owner's choice, 2026-10-10).

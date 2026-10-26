# Pack interface (design for roadmap 9.1)

Written for: the project owner, to approve before any code is written.
Status: **Design approved by the owner (2026-10-11).** Nothing here is built; code needs a separate go-ahead.

**Built so far (2026-10-11):**
- 9.2 gateway and manifest checks: `packs_gateway.py`, `packs_manifest.py`, 21 tests. Not used by the app yet.
- 9.3a TaskAgent on the tasks pack: `packs/tasks/`, `packs_agent.py`, `task_agent.py`. Gate passed: tool
  descriptions byte-identical; routing 28/30 and tool choice 27/30 before and after, same case results.
  One deliberate change: a symlinked `tasks.md` is refused at proposal time too (see commit b9b73af).
- 9.3b LessonsAgent on the lessons pack: `packs/lessons/`, `lessons_agent.py` is a wrapper. Gate passed:
  descriptions byte-identical; find output identical to the original search on the same files; routing and
  tool choice 28/30 and 27/30, same case results and tool calls. The gateway gained `read_raw` (approved).
  `lessons.py` split the search into reading and ranking (`search_entries`); ranking unchanged.
- 9.4 loader wired into the app: `packs_registry.py` loads every pack in `packs/` at startup, and `app.py`
  builds the registry from them. A bad pack shows a warning and the rest still load. The manifest gained one
  key, `agent`, the registry name (default: the pack name, capitalized). This is a schema change; the owner
  approved the option that led to it. Gate: routing and tool choice 28/30 and 27/30, same case results.
  Headless check: registry names unchanged (DocAgent, LessonsAgent, SaveNote, TaskAgent), TaskAgent keeps its
  save-as-a-note handoff, and a broken pack shows a warning.
- Decided 2026-10-11 (owner approved the recommendation): DocAgent and its notes tools stay in the core.
  Packs are for new capabilities. Reason: the notes agent works, is the most-tested part of the app, and
  moving it would add risk with no new capability. Revisit only if the owner wants notes tools to be packs.
- Found while moving: `TASK_PROMPT` said file text is inside `<tasks>` tags, but the wrapper uses
  `<document>` tags. Fixed 2026-10-11 after an eval run: routing and tool choice unchanged (28/30, 27/30),
  injection evals unchanged (12/12 held, 2/2 controls clean, 0 files changed).
 Rules: CLAUDE.md. Overview: design/architecture.md.
Items marked **[decide]** need the owner's yes.

## Goal

Let an agent be added or changed by dropping a folder in `packs/`, without anyone editing the safety
core and without weakening it. The existing agents move onto the interface with **no behavior change**.

Done for this design means: the owner approves the manifest, the gateway, the loader, and the migration
steps below.

## What exists today (read from the code)

- `app.py` builds a registry dict. Each entry has `purpose` (one line for the router), `factory`
  (returns an agent), `prompt`, and optionally `handoffs` and `handoff_only`. `brain.py`'s `Coordinator`
  only reads that dict shape.
- `DocAgent` (`agent.py`) owns the model loop (`run`, `max_steps`, temperature 0), the tool dict
  (`_build_tools`), the shared `pending_writes` list, and `approve_write` / `reject_write`.
- `TaskAgent` and `LessonsAgent` subclass `DocAgent` and replace `_build_tools` and `system_prompt`.
- Tool functions reach files through `agent._safe_path` and put writes in `pending_writes`.
- A tool's **docstring is its description to the model.** Hermes 3 is small, so changing a docstring
  can change tool choice. This matters for the migration (see Risks).

## Design

### 1. A pack is a folder

```
packs/
  tasks/
    manifest.toml     # what the pack is and what it may do
    pack.py           # code: tools and prompt
    tests/            # optional pack tests
```

The manifest is TOML, read with Python's built-in `tomllib` (Python 3.12 here). No new dependency.

### 2. The manifest

```toml
name = "tasks"                     # unique; lowercase letters, digits, hyphen
version = "0.1.0"                  # the pack's own version
api_version = 1                    # the core interface it was written for
purpose = "Only for the task list: add a task, show tasks, or mark a task done."   # max 200 chars
prompt_file = "prompt.txt"         # or `prompt = "..."`; short, small-model friendly

`[[tools]]`
name = "list_tasks"
writes = false
`[[tools]]`
name = "add_task"
writes = true
`[[tools]]`
name = "complete_task"
writes = true

[permissions]
read = ["tasks.md"]                # file names or patterns inside docs/ the pack may read
write = ["tasks.md"]               # file names or patterns it may propose to change
write_modes = ["append", "mark_done"]   # create, append, or mark_done
model = true                       # uses the local model through the core loop
# network and shell do not exist as options. A manifest that mentions them is refused.

`[[handoffs]]`
to = "notes"
label = "Save as a note"
```

Rules the loader enforces:

- Unknown keys are refused, so a typo cannot silently widen a permission.
- `purpose` is one line and at most 200 characters (the router prompt must stay short). Today's longest
  is the Lessons agent at 172 characters, measured, so every existing agent fits.
- A pack may declare only tools that `pack.py` actually provides, and the reverse.
- `read` and `write` patterns match **file names directly inside `docs/`**, never paths. No `/`, no `..`.

### 3. The gateway: the only way a pack touches data

The core gives each pack a `Gateway` object scoped to that pack's manifest. A pack never imports `open`,
`pathlib`, `os`, or `agent._safe_path`.

| Gateway method | What it does | Checked against |
|---|---|---|
| `list_names()` | Names of files the pack may read | `permissions.read` |
| `read_text(name)` | File text, size-capped, wrapped as untrusted data | `permissions.read`, `_safe_path` |
| `propose_create(name, text)` | Puts a new file in the approvals inbox | `permissions.write`, mode `create`, `_safe_path` |
| `propose_append(name, text)` | Proposes adding to the end of a file | mode `append` |
| `propose_mark_done(name, line)` | Proposes the one-line change today's `complete_task` makes | mode `mark_done` |
| `log(kind, **fields)` | Writes to the activity log (lengths, not text, as today) | always allowed |

Every method applies the same checks that exist today: name reduced to a plain file name, `.txt` and
`.md` only, no symlink, no extra hard link, parent must be `docs/`. The pack's name is added to each
pending item so the Approvals tab can show where it came from.

Approval is unchanged: the inbox, `approve_write`, the second name check at approval, and exclusive
create all stay in the core.

### 4. The loop stays in the core

Packs supply tools and a prompt. The **core runs the model loop** (temperature 0, step limit, and the
chat timeout from roadmap 13.2). A pack cannot call the model on its own or change those limits.

### 5. The loader

At startup the loader scans `packs/*/manifest.toml`, validates each, imports `pack.py`, and builds the
same registry dict shape `Coordinator` reads today. **`brain.py` does not change.**

- A pack with a bad manifest, an `api_version` the core does not support, or a name that is already taken
  is refused with a clear message in the app and the log. The other packs still load.
- Router purposes come from manifests, so adding a pack adds it to routing without editing `app.py`.

### 6. What this is not

Python has no safe in-process sandbox. The interface keeps honest, reviewed code on the safe path and makes
mistakes obvious. It does **not** stop a malicious pack that someone merges. That is why:

- Packs live in the repo and are reviewed through pull requests (decided: owner approved this direction).
- A contract test scans each `pack.py` and fails it if it imports or calls `open`, `os`, `subprocess`,
  `socket`, `requests`, `urllib`, or `eval`/`exec`. This catches accidents. It is not a security boundary.
- Third-party installable packs need real isolation (a separate process or container) and are a later phase.

## Contract tests (roadmap 10.1)

Every pack must pass, using dummy files in a temp folder:

1. Reading a name outside `permissions.read` is refused.
2. Proposing a write outside `permissions.write` or in an undeclared mode is refused.
3. A symlink and a hard link in `docs/` are refused.
4. A proposed write never changes a file before approval.
5. Hostile text in a note does not produce a write (the injection eval, run per pack).
6. The manifest and `pack.py` agree on the tool list.
7. No forbidden imports or calls (the accident check above).

A deliberately bad dummy pack must fail each one, which proves the tests can fail.

## Migration plan (maps to roadmap 9.2 to 9.4)

| Step | Change | Done when |
|---|---|---|
| 9.2 | Add the gateway module. Nothing uses it yet | Tests show the gateway applies every existing file check and the manifest permissions |
| 9.3a | Move **TaskAgent** onto a `tasks` pack, using the gateway | All test files pass; routing and tool-choice evals give the same numbers; tool docstrings are byte-identical |
| 9.3b | Move **LessonsAgent**, then **DocAgent's** tools into a `notes` pack | Same as above |
| 9.4 | Add the loader and make the app read packs. `app.py` change is a few lines | App lists the same agents; a bad manifest is refused; the "How it works" tab (U.9) reads the same registry |

One agent at a time, with the evals as the gate. If any number drops, that step is reverted.

## Risks

- **Small-model sensitivity.** Tool docstrings and prompts are tuned (roadmap 5.3). The migration must keep
  them identical, and the evals must match. A drop is a stop sign, not something to tune around.
- **`app.py` is edited by two sessions.** The loader wiring is last for that reason.
- **The gateway is a new place for bugs.** It reuses `_safe_path` instead of copying it, so there is one file guard.
- **TOML typos.** Refusing unknown keys prevents silent permission changes.

## Decisions for the owner

1. **[decide]** The gateway method list above (six methods). Add or remove any?
2. **[decide]** Manifest as TOML with the fields shown, read with built-in `tomllib`.
3. **[decide]** The core owns the model loop. Packs never call the model directly.
4. **[decide]** Move **TaskAgent first**, then Lessons, then DocAgent's tools last.
5. **[decide]** Keep third-party installs out of scope until there is an isolation design.

## Out of scope

Third-party installs, a real sandbox, a login, and the shared server (roadmap Phase 15).

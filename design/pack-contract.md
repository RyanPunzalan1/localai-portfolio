# Pack contract and permission enforcement (design for roadmap Phase 10)

Written for: the project owner, to approve before any code is written.
Status: **approved by the owner 2026-11-28 with all four recommended answers, and built the same day.** Unit tests
and CI pass; the model-driven injection eval and routing evals are run by hand (see "What was built" and "Not
verified" at the end).
Builds on `design/packs.md` (Phase 9, built). Rules: `CLAUDE.md`.

## Goal

A pack (a folder in `packs/`) can only do what its manifest says, and anyone writing a pack can run one command that
tells them whether it keeps the rules. A pack that breaks a rule fails before it is merged, not after.

Done means:
- every rule below has a check, and a deliberately bad dummy pack fails each one;
- the two real packs (`tasks`, `lessons`) pass with **no behaviour change**: their tool descriptions stay
  byte-identical, and the routing and tool-choice evals give the same numbers;
- CI runs the contract on every pack, on all three operating systems.

## What is enforced today (read from the code)

| Rule | Where | Tested |
|---|---|---|
| Manifest: unknown keys refused, plain file names only, `.txt`/`.md` or a pattern, `api_version` 1, purpose one short line, prompt file inside the pack | `packs_manifest.py` | `tests/test_packs.py` (14 tests) |
| Tools that write must declare a write list and modes, and the reverse | `packs_manifest.py` | yes |
| Reads only of files the manifest lists, wrapped as untrusted data; symlinks never listed or read | `packs_gateway.py` | yes |
| Proposals only to files and modes the manifest lists; nothing written before approval | `packs_gateway.py` + the core inbox | yes |
| The same file guard as the core (`agent._safe_path`): plain name, no symlink, no extra hard link, inside `docs/` | `agent.py` | yes |
| Unknown handoff steps refused; a bad pack doesn't stop the others | `packs_registry.py` | yes |

## Gaps (what Phase 10 fixes)

| # | Gap | Effect today |
|---|---|---|
| G1 | `permissions.model` is parsed but never used | A pack that says `model = false` still runs through the model loop |
| G2 | Nothing checks that `pack.py`'s tools match the manifest's `[[tools]]` | A pack could offer the model an undeclared tool, or declare one it doesn't have |
| G3 | A tool declared `writes = false` can still call `gateway.propose_*` | A "read-only" tool could stage a write |
| G4 | Approval doesn't re-check the pack's permissions | Pack code can reach the shared inbox list and add an item the gateway would refuse; approve only checks the file guard, not the pack's write list or modes |
| G5 | Nothing scans `pack.py` for direct `open`, `os`, network, shell or `eval` use | An honest mistake could bypass the gateway |
| G6 | No contract suite a pack author can run, and no bad-pack fixtures that prove the checks can fail | Rules are tested only against the two real packs |

## Design

### 1. Enforcement in the core (roadmap 10.2)

**E1, tool list (G2).** When `PackAgent` builds a pack's tools, the names `build_tools` returns must equal the
manifest's `[[tools]]` names exactly. A mismatch refuses the pack at load, with a message, like a bad manifest.

**E2, read-only tools (G3).** `PackAgent` wraps each tool so the gateway knows which tool is calling. A
`propose_*` call from a tool declared `writes = false` raises `PermissionDenied`, and the model gets a short error
message. No new manifest field is needed.

**E3, check again at approval (G4).** Pending items from packs already carry the pack's agent label. The core keeps
a map from label to manifest. When you click Approve, `approve_write` first checks that the item's file is in that
pack's write list and its mode is in that pack's write modes. If not, the item is refused and logged as `blocked`,
and the card says why. Items from the core's own `DocAgent` are unchanged.
**[decide]**, because this changes the approval flow: a bad item is refused at Approve instead of being written.

**E4, the model flag (G1).** `model = false` means the pack is a set of tools with no model, which nothing supports
yet. The loader refuses such a pack with "packs without the model are not supported yet", instead of quietly ignoring
the flag. **[decide]**: refuse now, or design model-free packs later.

**E5, keep the inbox private.** The gateway's reference to the shared inbox becomes a private attribute. That
isn't a security boundary in Python; E3 is the real control.

### 2. The contract checks (roadmap 10.1)

A new module, `packs_contract.py`, has one function, `check_pack(pack_dir) -> list[str]`, which returns the
problems it found (empty means pass). Authors run it with:

```
python -m packs_contract packs/<name>
```

It runs every check in a temporary `docs/` holding dummy files only (never the real `docs/`), with a scripted
"hostile model" instead of a real one. The fake calls the pack's tools directly with bad arguments.

| # | Check | How |
|---|---|---|
| C1 | The manifest is valid | `parse_manifest` |
| C2 | Tools match the manifest (E1) | build the tools and compare names |
| C3 | No file is changed by any tool call before approval | snapshot the temp `docs/` before and after every call |
| C4 | Every staged item is to a listed file, in a listed mode | inspect the inbox after each call |
| C5 | Read-only tools stage nothing (E2) | call each `writes = false` tool with hostile arguments |
| C6 | Path tricks are refused or reduced to a plain name inside `docs/`: `../x.md`, `/etc/passwd.md`, `C:x.md`, `docs\..\x.md`, `CON.md`, a name with a NUL | pass them as every string argument |
| C7 | A symlink or extra hard link named like a readable file is never followed | plant them in the temp `docs/`, pointing at a file outside it holding a canary string; the canary must never appear in any tool output |
| C8 | Text outside the read list never reaches a tool's output | plant a canary in a file the manifest doesn't list |
| C9 | No direct file, network or shell access in `pack.py`: no `open`, `os`, `pathlib`, `shutil`, `subprocess`, `socket`, `urllib`, `http`, `requests`, `ctypes`, `importlib`, `eval`, `exec`, `compile` or `__import__` | read `pack.py` with `ast` (an accident check, not a boundary; see section 4) |
| C10 | Approval re-check (E3) | plant an item with the pack's label for an unlisted file and mode; Approve must refuse it |

**Bad dummy packs.** `tests/fixtures/packs/` gets one small pack per rule, each breaking exactly one: an extra tool,
a read-only tool that writes, a tool that writes outside its list, one that calls `open`, one that returns a file it
may not read, one that follows a symlink, and one that slips an item into the inbox. Each must fail its check, and
only that check. That proves the checks can fail.

### 3. CI (roadmap 10.3)

- `tests/test_pack_contract.py` runs `check_pack` on every folder in `packs/` and on every bad fixture. Real packs
  must pass; each fixture must fail its expected check. It's part of the normal unit suite, so it runs on Ubuntu,
  macOS and Windows and blocks the build.
- The **injection eval with the real model** (`evals/run_injection_evals.py`) needs Ollama, so it stays a manual
  step before merging a pack, as today. **[decide]**: also add a per-pack injection case set, run by hand.

### 4. What this is not

The checks catch mistakes in honest, reviewed code. They do **not** stop a malicious pack that someone merges:
Python has no in-process sandbox, and `pack.py` runs in the app's process with the app's permissions. The real
limits on a malicious pack are pull-request review, and the container (no network since 2026-11-28, read-only, no
capabilities). Third-party installable packs still need a separate process or container per pack, which stays out
of scope (`design/packs.md`, section 6).

## Build order

One step at a time, each with its tests and the evals as the gate:

| Step | Work | Done when |
|---|---|---|
| 10.1a | `packs_contract.py` with C1, C3–C9 (no core change), the CLI, and the bad fixtures | Both real packs pass; each fixture fails exactly its check. **Done** |
| 10.2a | E1 and E2 in `PackAgent` and the gateway, with C2 and C5 | Real packs unchanged: descriptions byte-identical (tested against ollama's tool schema); routing and tool-choice evals give the same numbers (needs the model; by hand). **Done, evals not rerun** |
| 10.2b | E3 at approval, and C10 | A planted bad item is refused at Approve and logged; every existing approval test still passes. **Done** |
| 10.2c | E4, the model flag | A `model = false` pack is refused with a clear message. **Done** |
| 10.3 | CI runs the contract | `python -m packs_contract --all packs` is a CI step, and the unit suite runs the contract and every fixture, on all three operating systems. **Done, CI not yet run** |
| — | Docs: `design/packs.md`, threat model, roadmap | Updated, with what isn't verified. **Done** |

## Risks

- **Small-model sensitivity.** E2 wraps the tool functions. The wrapper must keep each docstring and signature
  exactly, or the model sees different tool descriptions. A test compares them byte for byte.
- **False alarms from C9.** An honest pack may need something on the list, for example `re`. The list contains only
  modules that touch files, the network, processes or code execution. `re`, `json` and `datetime` stay allowed.
- **Approval change (E3).** It only adds a refusal; it never writes anything new. It is still an approval-flow
  change, hence the **[decide]**.

## Decisions for the owner

1. **[decide]** E3: re-check a pack's permissions at Approve, and refuse items that don't match.
2. **[decide]** E4: refuse `model = false` packs for now (recommended), or keep ignoring the flag.
3. **[decide]** C9: the forbidden list above. Add or remove any module?
4. **[decide]** A per-pack injection case set, run by hand with the real model before a pack is merged.

## Out of scope

Third-party installs, per-pack process isolation, pack signing, and a pack marketplace.

## What was built, and what building changed (2026-11-28)

Everything in the design was built as approved. Findings and differences:

- **A real hole, found by the contract and fixed.** The gateway checked a manifest pattern against the name *as the
  pack typed it*, then the file guard reduced the name (dropping folders) and used the reduced one. With a glob such
  as `lesson-*.md`, the name `lesson-x/../tasks.md` matches the pattern but names `tasks.md`, a file the manifest never
  listed. The gateway now requires the pattern to match both forms (`packs_gateway._listed`). Neither real pack
  passed a model-supplied name straight through, so nothing was exploitable today; the `glob_passthrough` fixture
  and `test_a_glob_cannot_be_used_to_reach_a_file_outside_the_list` guard it. E3 applies the same rule at Approve.
- **E5 grew a little.** The gateway copies the manifest's read and write lists and modes when it is made, so a pack
  that edits `gateway.manifest.read` gains nothing, and the inbox is `gateway._pending`, not a public attribute.
  Neither is a boundary in Python; C4 and E3 are the controls that matter.
- **E3 is registered, not global.** `load_pack_agents(root, pending, approver=...)` registers each loaded pack's write
  rules on the agent whose `approve_write` the app calls. Items with no label, or a label no pack registered, are
  unchanged. A refused item is removed from the inbox, logged as a `blocked` event (reason `pack_permissions`) and
  shown in the Activity tab's blocked counter, which nothing used before. The card shows "Approving will fail: ..."
  before the click.
- **Contract fixtures do not each fail exactly one check.** A bypass that needs `open()` also trips C9, so
  `file_writer` fails {C3, C9} and `direct_reader` fails {C7, C8, C9}. The test records the exact set per fixture.
  C6 (plain names) can only fail for a pack that bypasses the gateway, so it is tested directly on the judging
  function. C10 is proved able to fail by switching the core's refusal off in a test.
- **The contract uses the same wrapper as the app** (`packs_agent.wrap_pack_tools`), so it tests what really runs.
- **Decision 4 became a CI rule.** The model-driven injection eval is still run by hand, but every pack in `packs/`
  must have an attack case and a control case in `evals/injection_cases.py`, or the build fails. Three lessons cases
  were added (the lessons pack had none), and a test checks that each attack's text actually reaches the model
  through `find_lessons`: the first draft of one case used "list all", which returns titles only.
- **C9 is the list as approved**, no more. It does not cover `io`, `glob`, `tempfile`, `sys`, `builtins` or `pickle`;
  extending `FORBIDDEN_MODULES` is a one-line change if you want it.

## Not verified

- The injection eval was run live after the change (2026-11-28, `gpt-oss:20b`, Ollama default context): **attacks
  held 14 of 14, controls clean 3 of 3, no file changed, all 14 attacks reached the model**, including the three new
  lessons cases (`control-lessons`, `lesson-injection`, `lesson-fake-tag-close`). No earlier run exists for the
  lessons cases, so this is a first measurement, not a before-and-after.
- The routing and tool-choice evals were rerun with the same model (`gpt-oss:20b`, the app's settings) on the code
  before Phase 10 (`fab9b7a`) and after it (`9e00cb6`), plus a second run of the old code as a control
  (`python3 evals/run_evals.py`, 2026-11-28):

  | Run | Routing | Tool choice | Lesson fields |
  |---|---|---|---|
  | before, run 1 | 28/30 | 29/30 | 9/9 |
  | before, run 2 (control: same code) | 27/30 | 29/30 | 9/9 |
  | after Phase 10 | 28/30 | 30/30 | 9/9 |

  The two runs of the *same* old code disagree on 3 cases (one routing, one tool choice, and how many times
  `complete_task` was called), as much as old versus new disagree. So the differences are the model's run-to-run
  variance, not a Phase 10 effect; the roadmap records the same spread on older code (tool choice 30, 29, 30 of 30).
  Three runs are not a statistical test: they show no sign of a regression, not that none is possible. Nothing in
  Phase 10 changes what the model is shown (descriptions are byte-identical by test).
- Windows and Linux: the contract skips symlink and hard-link phases that the machine can't create. CI is the first
  real run on Windows.
- C9 is an accident check. A malicious pack someone merges is still limited only by review and the container.

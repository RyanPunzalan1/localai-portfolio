# Design: Adding lessons in bulk (paste box)

Written for: the project owner, to approve or change before any code is built.
Status: **approved and built (2026-10-10).** Code: `lesson_capture.py`, the expander in `app.py`;
tests: `tests/test_lesson_capture.py`. Not yet tried in a real browser by the owner.
Builds on: design/lessons.md (the lessons memory, already built and committed).
History: draft 1 also proposed "suggest lessons from a chat" with a model (cut, see "Not doing").
Draft 2 bundled a recall eval; that is now built separately (`evals/run_recall_evals.py`).

## Prerequisite (owner)

Before building this, save two or three real lessons through Chat in the running app, then ask for
them back. The single-lesson loop has not been run in a browser yet. If it feels awkward, fix that
first; a bulk box on top of an unproven loop is more machinery for the same problem.

## Goal

Saving a lesson today means typing one request in Chat, approving the route, then approving the
note in Approvals. That is too slow for everything learned in a day, and it depends on Hermes 3
routing and calling `save_lesson` correctly (measured: 8 of 10 on the original cases, with two
saves where the model called no tool).

This adds a way to paste several lessons at once. Code splits and checks them, and they wait in
the Approvals tab. The model is not involved.

## Why this shape (what the project already measured)

- The handoff step scored 5/5 once **code** did the copying and the model only chose the step
  (design/brain.md, roadmap phase 3). Work that must be exact belongs in code.
- The app cannot see coding done outside it (for example in Claude Code), and that is where most
  lessons come from. The slow part is getting drafted lessons into the app, not drafting them.

## Findings that shape this design (checked in the code)

1. Staging already exists: `agent.pending_writes` is the shared, file-backed inbox
   (`PendingStore`). A staged lesson is `{"name", "content", "agent": "LessonsAgent"}`, the same
   shape `save_lesson` makes. This feature reuses it. No new write path to disk.
2. `lessons.build_lesson(title, tags, lesson, why, today)` already does the checks (one line per
   field, caps, safe file name). Every pasted lesson goes through it, so a lesson added by paste is
   built exactly like one saved in Chat.
3. A saved lesson is one small text file with a fixed layout (below). Pasting that same layout
   means the box also works for copying lessons from one machine or project to another, which
   serves the goal of making future projects easier.
4. Approving a new note uses exclusive create, so a duplicate title would be saved as
   `..._new1.md`. Without a duplicate check, pasting the same set twice would double every lesson.
5. The Approvals tab shows each pending note in full with its own Approve and Reject.

## Decisions for the owner (each is a recommendation)

| # | Decision | Recommended | Alternative |
|---|---|---|---|
| A | Where the paste box lives | An expander "Add lessons from text" at the top of the **Approvals** tab | A new Lessons tab |
| B | Paste format | The stored lesson layout (below); a new lesson starts at each `# ` line | A separate `title:`/`---` format, or JSON |
| C | Duplicates | Skip a lesson whose file name exists in `docs/` or already waits in the inbox, and report it | Keep both as `_new1` |
| D | Failure handling | A bad lesson is reported by position and reason; the good ones are still staged | Refuse the whole paste |
| E | Size of one paste | At most 10 lessons and 20,000 characters, and **no "Approve all"**: every lesson is approved on its own | 20 lessons; an Approve all button |

A, C, D and E touch the approval flow, so they need a yes.

## The paste format (the same layout lessons are saved in)

```
# Pin package versions
Tags: pip, requirements
Date: 2026-10-10

**Lesson:** Pin every version in requirements.txt.
**Why:** An unpinned update broke the app.

# Next lesson title
...
```

- A new lesson starts at each line beginning with `# `. No `---` separators, so a divider line
  inside a lesson cannot break the split.
- `Tags:`, `**Lesson:**` and `**Why:**` are required labels. `Date:` is optional: a valid ISO date
  is kept (so an exported lesson keeps its date); otherwise today's date is used. The date is
  never taken from the model, because no model is involved.
- Text that wraps onto following lines is joined to the field above it with a space.
- Text before the first `# ` line is ignored and reported.
- Unknown labels, a missing required field, an over-cap field, or a bad tag fail that lesson with a
  reason. The other lessons are still staged. Nothing is staged half-built.
- Each lesson goes through `build_lesson`, so the existing caps and name checks apply.
- The text box is the only input. No file is read, so no file-access rule changes.
- The page reports: staged N, skipped M as duplicates, failed K (with the number and the reason).
- When Claude drafts lessons for the owner, it writes them in this layout.

## Safety

- **Writes:** only staged in the existing inbox. Approve and Reject work as today.
- **Untrusted text:** pasted text is data. It is parsed by fixed rules, never sent to a model, and
  shown in full in Approvals before anything is saved.
- **Privacy:** local only, no network, no new dependencies. The activity log records counts
  (staged, skipped, failed), never lesson text, matching `brain.log_text`.
- **Limits:** 10 lessons, 20,000 characters, and the existing field caps on every lesson. Ten
  keeps review human-sized; the cap is a constant, so it is easy to change.
- **Paths:** unchanged. Flat `lesson-*.md` files in `docs/` only.

## Tests (dummy folders only; never the real `docs/`)

- Parser: a good lesson gives the exact fields; a lesson saved by `build_lesson` parses back to
  the same fields (round trip); a wrapped line is joined; a kept date is accepted and a bad date
  falls back to today; text before the first title, a missing label, an unknown label, an
  over-cap field, a bad tag, and an empty paste are each reported without stopping the rest.
- Caps: 11 lessons and an oversized paste are refused with a message and stage nothing.
- Staging: a staged lesson has the same name and text as `save_lesson` would give for the same
  fields; nothing is written to `docs/` before approval; approving writes exactly one file.
- Duplicates: a name that exists in `docs/` or already waits in the inbox is skipped and reported,
  including a repeat inside one paste.
- Wiring (text checks on `app.py`, like the other guard tests): the expander exists, it never calls
  `approve_write`, and there is no "Approve all".
- The activity log gets counts only.

## Build order (each step small, tests run before the next)

1. `lesson_capture.py`: the parser and `stage_lessons` (caps, duplicates, reporting) as plain
   functions, with tests. No UI.
2. The "Add lessons from text" expander in `app.py`, with wiring tests. Add `lesson_capture.py` to
   the Dockerfile `COPY` line. Then try it in the app.

## Done means

A pasted set of lessons shows up in the Approvals tab, one entry per valid lesson, nothing on disk
until Approve, and a bad lesson is reported without blocking the others. A lesson exported from one
install pastes cleanly into another.

## Not doing (and why)

- **"Suggest lessons from this chat" with a model.** It needs a model call per click, depends on
  Hermes 3 following a format and returning something usable (it often does not), and only sees
  chats typed into the app, not coding done elsewhere. A quote check would stop invented lessons
  but not weak ones.
- **"Approve all."** Per-item approval is the check that makes bulk adding acceptable. Skimming
  twenty items at once defeats it.

## Not verified yet

Whether pasting is comfortable in the real app. Step 2 ends with trying it there.

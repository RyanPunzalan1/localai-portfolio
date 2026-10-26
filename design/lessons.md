# Design: Lessons memory (coding lessons that carry over to future projects)

Written for: the project owner, to approve or change before any code is built.
Status: **draft, waiting for approval. No code written.**

## Goal

After a project, save what was learned (a gotcha, a command, a decision and why). When starting
something new, ask for what was learned and get the saved lessons back. Nothing is saved
until the user clicks Approve.

## Findings that shape this design (checked in the code)

1. `agent._safe_path` only allows a flat file directly inside `docs/` (`.md` or `.txt`, no
   folders, no symlinks). So lessons cannot live in `docs/lessons/` without changing the
   file-access rules. This design keeps the rules and uses a name prefix: `lesson-<slug>.md`.
2. The search index (`init_rag` in `app.py`) is built once at startup and rebuilt only on a
   manual re-index. A lesson approved now would not be found by `search_docs` until then. So
   recall does not use the index. It scans the `lesson-*.md` files directly.
3. Approved new notes use exclusive create and never overwrite. Lessons inherit this: a lesson
   is never silently changed, and a name clash keeps both files (`_new1`).
4. Agents are small `DocAgent` subclasses registered with the coordinator (`TaskAgent` is the
   model). A `LessonsAgent` follows the same shape, with a short prompt (Hermes 3 is small).

## Decisions for the owner (each is a recommendation)

| # | Decision | Recommended | Alternative |
|---|---|---|---|
| A | Where lessons live | Flat `docs/lesson-<slug>.md` (no rule change) | `docs/lessons/` (needs a file-access rule change) |
| B | How recall works | Code scans `lesson-*.md` for the query words (instant, testable) | Reuse the embedding index (semantic, but stale until re-index) |
| C | Who builds the file | The model gives fields; **code** builds the file and name | Model writes the whole file |
| D | Edit and delete | Not in v1. Delete the file by hand; a fix is a new lesson | Add approved edit and delete later |

A, B and C are the ones that touch file-access and approval behavior, so they need a yes.

## Tools (two, kept short for a small model)

- `save_lesson(title, tags, lesson, why)` proposes a lesson. It only stages a note in the
  shared approvals inbox. Same flow as `save_note` and `add_task`.
- `find_lessons(query)` read-only. Returns up to 3 best matches. An empty query lists all
  lesson titles. No approval needed.

## Lesson file format (built by code, not by the model)

```
# <title>
Tags: docker, streamlit
Date: 2026-10-10

**Lesson:** one or two sentences, what to do or avoid.
**Why:** what happened, or the reason.
```

- File name: `lesson-<slug of title>.md`, checked by the existing `check_note_name`.
- `Date` comes from code, not the model.
- Caps: title 80 characters, tags at most 6 with 20 characters each, lesson and why 600
  characters each. Over the cap is refused with a message, not cut off silently.
- Fields with an empty title or lesson are refused.

## Recall (code, not the model)

1. Lowercase the query and split it into words. Drop very short words.
2. Score each `lesson-*.md` by matches in tags (weight 3), title (weight 2), and body (weight 1).
3. Return the top 3 with a score above 0, wrapped with `wrap_untrusted` so the text is data.
4. Honest limit: this is keyword matching, not meaning. "container" will not find a lesson
   that only says "docker". Tags are the mitigation: the save prompt asks for a few
   plain-word tags, and `find_lessons("")` lists every title as a fallback.

## Safety

- **Writes:** only through the approvals inbox. The full lesson is shown before Approve.
- **Memory poisoning:** if the model read a hostile file, it could propose a lesson that
  carries an injected instruction, and recall would show it later. Defences: the user reads
  the whole lesson before approving; fields are capped; recalled text is wrapped as data and the
  prompt says to treat it as data. Residual risk: a convincing lesson the user approves.
- **Secrets:** a lesson might contain a password or key by accident. The approval screen is the
  check. Optional later: refuse content that looks like a key.
- **Paths:** unchanged. Flat files in `docs/` only. Lessons are personal data like the rest of
  `docs/`, so they stay out of git and out of tests (tests use dummy folders).
- **Local only:** no new dependencies and no network.

## Tests (dummy folders only, never the real `docs/`)

- Fields are turned into the exact file text and name; the date comes from code.
- Caps, empty fields, and an unsafe name (`../x`, `CON`) are refused.
- Nothing is written before approval; approval writes one file; a name clash keeps both.
- Recall: ranks tag matches above body matches; no match returns a clear message; an empty query
  lists titles; the output is wrapped as data; a lesson containing `</document>` cannot
  close the wrapper.
- The agent has only these two tools and its own prompt (like `TaskAgent`).
- A guard test: `find_lessons` reads only `lesson-*.md` and never other files in `docs/`.

## Build order (each step small, tests run before the next)

1. `lessons.py`: file builder, caps, and recall scan as plain functions, with tests. No model.
2. `LessonsAgent` with the two tools and a short prompt, with tests.
3. Register it with the coordinator and add one routing example. Add the agent file to the
   Dockerfile `COPY` line.
4. Eval cases (tool picked, fields sensible), then run them on `hermes3` and record the result
   in the roadmap.

## Done means

All new tests pass with the existing suite; the eval shows the right tool chosen in at least 8
of 10 sample requests (the bar phase 2 used); a lesson saved in the real app shows up in
`find_lessons` right after approval, with no re-index.

## Not verified yet

Whether Hermes 3 fills the four fields well from a casual sentence. That is what step 4 measures.

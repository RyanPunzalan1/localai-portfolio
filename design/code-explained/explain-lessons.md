# explain: lessons

**What it is:** Lesson files: build, find, and list them.

## What it does

`build_lesson` turns four fields into the exact file text and name. `search_entries` ranks lessons (tags first, then title, then text). `list_lessons` and `filter_lessons` feed the Lessons tab. Nothing here writes a file.

## Read first

1. `build_lesson`: field checks and the file layout.
2. `search_entries`: the ranking.
3. `list_lessons`: reads only `lesson-*.md` files.

## Break it to see it working

Change the tag weight in `search_entries` from 3 to 0, then run `evals/run_recall_evals.py`. The direct queries should drop.

## Connected to

- [[code-lessons_agent]] (the lessons agent)
- [[code-lesson_capture]] (the paste box)
- [[code-app]] (the Lessons tab)

_Hand-written. Check it against the code when the code changes; the commit log shows what changed._

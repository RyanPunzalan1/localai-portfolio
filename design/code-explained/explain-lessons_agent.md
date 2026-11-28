# explain: lessons_agent

**What it is:** The lessons agent, as a thin wrapper around the lessons pack.

## What it does

Its tools and prompt come from `packs/lessons/`. This file keeps the names the app and the tests use, such as `LESSONS_PROMPT`, and builds the agent from the pack.

## Read first

1. `LessonsAgent`: the class the app creates.
2. `LESSONS_PROMPT` and `LESSONS_PURPOSE`: must match the pack files.

## Break it to see it working

Edit `LESSONS_PROMPT` here, but not in `packs/lessons/prompt.txt`. The test `tests/test_pack_lessons.py` should fail.

## Connected to

- [[code-pack-lessons]] (the tools)
- [[code-packs_agent]] (the base class)

_Hand-written. Check it against the code when the code changes; the commit log shows what changed._

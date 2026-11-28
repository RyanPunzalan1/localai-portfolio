# explain: pack-lessons

**What it is:** The lessons pack's tools: save a lesson and find lessons.

## What it does

`save_lesson` builds the file text and stages it for approval through the gateway. `find_lessons` reads only lesson files through the gateway, then ranks them with the same ranking the recall eval measures.

## Read first

1. `save_lesson`: the checks and the staging call.
2. `find_lessons`: the read-and-rank path.

## Break it to see it working

Change `find_lessons` to read `docs/` directly, bypassing the gateway. The test `tests/test_pack_lessons.py` should fail on the permission rules.

## Connected to

- [[code-lessons]] (checks and ranking)
- [[code-packs_gateway]] (the only path to files)

_Hand-written. Check it against the code when the code changes; the commit log shows what changed._

# explain: lesson_capture

**What it is:** Adds several lessons at once from pasted text.

## What it does

It splits the paste into lessons at each `# Title` line, checks each one with the same rules as a single lesson, and stages the good ones for approval. Bad lessons are reported by number, and duplicates are skipped. No model is involved.

## Read first

1. `parse_lessons`: the splitting and field rules.
2. `stage_lessons`: the checks, the duplicate skip, and staging.
3. The limits: 10 lessons and 20,000 characters per paste.

## Break it to see it working

Paste 11 lessons. The paste should be refused, and nothing should be staged.

## Connected to

- [[code-lessons]] (checks each lesson)
- [[code-pending_store]] (where lessons wait)
- [[code-app]] (the paste box)

_Hand-written. Check it against the code when the code changes; the commit log shows what changed._

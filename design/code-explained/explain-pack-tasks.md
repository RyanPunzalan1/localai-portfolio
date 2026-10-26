# explain: pack-tasks

**What it is:** The tasks pack's tools: list, add, and complete tasks.

## What it does

`list_tasks` reads the file. `add_task` stages a line for approval. `complete_task` checks the open line exists, then stages the change. Each returns the same messages the model always saw.

## Read first

1. `add_task`: stages a line, never writes.
2. `complete_task`: checks an exact line before staging.

## Break it to see it working

Make `complete_task` skip the line check. Then complete a task that doesn't exist. The gateway refuses nothing here, so the approval step must catch it.

## Connected to

- [[code-task_agent]] (the wrapper)
- [[code-packs_gateway]] (the only path to files)

_Hand-written. Check it against the code when the code changes; the commit log shows what changed._

# explain: task_agent

**What it is:** The task agent, as a thin wrapper around the tasks pack.

## What it does

Its tools and prompt come from `packs/tasks/`. This file keeps the names the app and tests use, such as `TASK_PROMPT` and `TASKS_FILE`.

## Read first

1. `TaskAgent`: the class the app creates.
2. `TASK_PROMPT`: must match the pack's prompt file.

## Break it to see it working

Change `TASKS_FILE` here only. The gateway's permissions still say `tasks.md`, so the tool should refuse.

## Connected to

- [[code-pack-tasks]] (the tools)
- [[code-packs_agent]] (the base class)

_Hand-written. Check it against the code when the code changes; the commit log shows what changed._

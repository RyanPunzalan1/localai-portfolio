# explain: agent

**What it is:** The notes agent (DocAgent) and the tool-calling loop.

## What it does

It runs the back-and-forth with the model: it sends the messages and tools, runs the tool the model asks for, and repeats until the model gives a final answer. It also has the file guard (`_safe_path`) and the approval step (`approve_write`).

## Read first

1. `_safe_path`: every file path goes through this check.
2. `run`: the loop, with a step limit and temperature 0.
3. `approve_write`: the only place a proposed note reaches disk.

## Break it to see it working

Change `_safe_path` to allow a folder, and run the path tests in `tests/test_security.py`. They should fail.

## Connected to

- [[code-brain]] (the coordinator runs this loop)
- [[code-safety]] (the wrapper and name checks)
- [[code-packs_agent]] (pack agents reuse this loop)

_Hand-written. Check it against the code when the code changes; the commit log shows what changed._

# explain: packs_gateway

**What it is:** The one door packs use to reach files, the approvals list, and the log.

## What it does

Every call checks the pack's manifest first: the file must be on its list, and the mode must be allowed. Only then does it use the shared file guard. Proposed changes go to the approvals list, never straight to disk.

## Read first

1. `_allowed`: the manifest check.
2. `_propose`: the approval path for every write.
3. `read_raw` and `read_text`: reads, the second with an untrusted-data wrapper.

## Break it to see it working

Remove the `_allowed` check in `_propose`. `tests/test_packs.py` should fail.

## Connected to

- [[code-packs_manifest]] (defines the rules)
- [[code-agent]] (the file guard it calls)
- [[code-pack-tasks]] and code-pack-lessons (the callers)

_Hand-written. Check it against the code when the code changes; the commit log shows what changed._

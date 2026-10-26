# rule: Private files are readable by you only

**The rule:** The approvals list and the activity log are created owner-only (0600).

## Enforced by

- [[code-pending_store]]
- [[code-brain]]

## Checked by

- [[test-pending]]
- [[test-brain]]

## Try to break it

Change the permission in `PendingStore._write` to 0644. The owner-only test should fail.

_Hand-written. If the code changes, check the rule still holds and update this note._

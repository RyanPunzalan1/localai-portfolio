# rule: Nothing is written until you approve it

**The rule:** Every write goes to the approvals list first. Approving is the only step that changes a file.

## Enforced by

- [[code-pending_store]]
- [[code-agent]]
- [[code-packs_gateway]]

## Checked by

- [[test-integration]]
- [[test-pending]]
- [[test-tasks]]

## Try to break it

Make the Approve button skip `approve_write`, or make `save_note` write straight to `docs/`. Run `tests/test_integration.py` and `tests/test_pending.py` and see what fails. If nothing fails, the tests have a gap for this rule.

_Hand-written. If the code changes, check the rule still holds and update this note._

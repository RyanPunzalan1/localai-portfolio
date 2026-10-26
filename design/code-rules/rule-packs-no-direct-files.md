# rule: Packs never touch files directly

**The rule:** A pack reaches files, the approvals list, and the log only through the gateway, which checks the manifest first.

## Enforced by

- [[code-packs_gateway]]
- [[code-packs_agent]]

## Checked by

- [[test-packs]]
- [[test-pack_tasks]]
- [[test-pack_lessons]]

## Try to break it

Import `os` in a pack's `pack.py`. The contract the design asks for would catch it; the test suite does not scan for it yet.

_Hand-written. If the code changes, check the rule still holds and update this note._

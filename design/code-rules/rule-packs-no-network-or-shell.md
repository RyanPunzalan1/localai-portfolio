# rule: Packs can't ask for network or shell access

**The rule:** The manifest has no key for network or shell. An unknown key is refused, so a typo can't widen a permission.

## Enforced by

- [[code-packs_manifest]]

## Checked by

- [[test-packs]]

## Try to break it

Add `network = true` to a manifest. It should be refused.

_Hand-written. If the code changes, check the rule still holds and update this note._

# rule: Files only inside docs/

**The rule:** The app reads and writes files only inside `docs/`. No folders outside it, no paths that climb out with `..`.

## Enforced by

- [[code-agent]]
- [[code-packs_gateway]]

## Checked by

- [[test-security]]
- [[test-tasks]]

## Try to break it

Give a file name like `../secret.md` to a tool. It should be refused.

_Hand-written. If the code changes, check the rule still holds and update this note._

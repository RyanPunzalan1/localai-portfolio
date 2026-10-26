# rule: Plain file names only

**The rule:** A file name can't contain folders, drive letters, control characters, or Windows reserved names, and must end in `.md` or `.txt`.

## Enforced by

- [[code-safety]]
- [[code-packs_manifest]]

## Checked by

- [[test-security]]
- [[test-packs]]

## Try to break it

Propose a note named `CON.md`. It should be refused.

_Hand-written. If the code changes, check the rule still holds and update this note._

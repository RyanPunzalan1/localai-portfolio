# rule: Model output can't show images or live links

**The rule:** Images are removed, and links are shown as plain text, so a reply can't make your browser fetch or open anything.

## Enforced by

- [[code-safety]]
- [[code-app]]

## Checked by

- [[test-security]]

## Try to break it

Remove `clean_output` from one Markdown display in `app.py`, then run `tests/test_security.py`. The guard counts the calls, so one removal may still pass. If it passes, the guard is weaker than the rule, which is worth knowing.

_Hand-written. If the code changes, check the rule still holds and update this note._

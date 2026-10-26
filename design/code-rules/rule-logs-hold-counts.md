# rule: The log holds counts and names, not your text

**The rule:** Requests and tool arguments are logged as lengths. File names and page numbers are kept, because they are metadata.

## Enforced by

- [[code-brain]]

## Checked by

- [[test-brain]]

## Try to break it

Log a request containing a secret phrase. The phrase should not appear in `logs/activity.jsonl`.

_Hand-written. If the code changes, check the rule still holds and update this note._

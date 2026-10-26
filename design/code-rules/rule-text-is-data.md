# rule: File text is data, never instructions

**The rule:** Text from your files is wrapped so the model reads it as content. A file can't close the wrapper early.

## Enforced by

- [[code-safety]]
- [[code-agent]]

## Checked by

- [[test-security]]

## Try to break it

Remove the escaping in `wrap_untrusted`. The wrapper tests should fail.

_Hand-written. If the code changes, check the rule still holds and update this note._

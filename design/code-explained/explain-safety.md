# explain: safety

**What it is:** Small helpers that keep untrusted text from doing harm.

## What it does

`wrap_untrusted` marks file text as data, and escapes any tag that could close the wrapper. `check_note_name` allows only plain file names. The rest strip images and links from model output, and refuse cloud model names.

## Read first

1. `wrap_untrusted`: the data wrapper.
2. `check_note_name`: the name rules.
3. `clean_output`: strips images and links.

## Break it to see it working

Remove the escaping in `wrap_untrusted`, then run `tests/test_security.py`. The injection tests should fail.

## Connected to

- [[code-agent]], [[code-lessons]], [[code-packs_gateway]] (all use these)

_Hand-written. Check it against the code when the code changes; the commit log shows what changed._

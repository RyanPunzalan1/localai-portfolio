# explain: code_agent

**What it is:** The code reviewer: reads this project's own code and gives hints. It can't write.

## What it does

It reads only the files on an allowlist (top-level `.py` files that aren't tests, plus the Dockerfile, requirements, and design notes). The model's review is shown as hints, and it doesn't suggest fixes.

## Read first

1. `check_code_path`: the allowlist.
2. `review_code`: builds the review.
3. `_allowed_name`: the file-name rule.

## Break it to see it working

Ask it to review `docs/` or `logs/`. It should refuse, and nothing is read.

## Connected to

- [[code-safety]] (wraps the code it reads)
- [[code-app]] (the Code review tab)

_Hand-written. Check it against the code when the code changes; the commit log shows what changed._

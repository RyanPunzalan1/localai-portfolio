# explain: pending_store

**What it is:** The approvals list, saved to a file so it survives a page reload.

## What it does

It's a list stored in `logs/pending_writes.json`. Every change is saved at once, and the file is owner-only. If the file is damaged, the app starts with an empty list instead of crashing.

## Read first

1. `append` and `pop`: add an item and remove one.
2. `_write`: the owner-only save.

## Break it to see it working

Edit `logs/pending_writes.json` by hand to contain bad text. Restart the app. It should show an empty list, not an error.

## Connected to

- [[code-app]] (shows and changes the list)
- [[code-agent]] (approves items from it)

_Hand-written. Check it against the code when the code changes; the commit log shows what changed._

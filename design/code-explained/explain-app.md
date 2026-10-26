# explain: app

**What it is:** The Streamlit web page.

## What it does

It draws the tabs (Chat, Approvals, Lessons, Code review, Activity), keeps the chat history and the approvals list, and connects the buttons to the coordinator and the packs. It has no file logic of its own.

## Read first

1. The state block near the top: this is what the page remembers between clicks.
2. The tab blocks: one per tab.
3. The Approve handler in the Approvals tab: this is where a write happens.

## Break it to see it working

Remove the pack-error warning line, then load the app with a broken pack in `packs/`. The warning should disappear, and the broken pack should be silently skipped.

## Connected to

- [[code-packs_registry]] (loads the packs)
- [[code-brain]] (routes requests)
- [[code-pending_store]] (the approvals list)

_Hand-written. Check it against the code when the code changes; the commit log shows what changed._

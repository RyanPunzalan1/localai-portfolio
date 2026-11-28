# explain: brain

**What it is:** The coordinator: picks one agent per request and runs it only after approval.

## What it does

It asks the model which registered agent fits the request, refuses any name that isn't registered, waits for your approval of the route, runs the agent, and logs each step. It also keeps the activity log, which records lengths, not your text.

## Read first

1. `Coordinator.propose`: the model's choice is checked against the registry.
2. `Coordinator.run`: runs only if the route is approved.
3. `ActivityLog.append`: the log file and its permissions.

## Break it to see it working

Make `propose` accept any name, then ask the model for an unregistered agent. The route is rejected, and a `route_rejected` event is logged.

## Connected to

- [[code-agent]] (the agent it runs)
- [[code-packs_registry]] (the registry it uses)
- [[code-app]] (the page that drives it)

_Hand-written. Check it against the code when the code changes; the commit log shows what changed._

# explain: packs_registry

**What it is:** Finds the packs and turns them into agents for the app.

## What it does

It loads each valid pack into an agent. It refuses a pack whose handoff names an unknown step. It builds the registry entries the coordinator reads, so the app doesn't name each agent itself.

## Read first

1. `load_pack_agents`: loads packs and reports the bad ones.
2. `registry_entries`: builds the coordinator's list.

## Break it to see it working

Give a pack a handoff to `Shell`. It should be left out, with a warning in the app.

## Connected to

- [[code-app]] (calls it at startup)
- [[code-packs_manifest]] (checks each pack)
- [[code-packs_agent]] (builds each agent)

_Hand-written. Check it against the code when the code changes; the commit log shows what changed._

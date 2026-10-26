# explain: packs_agent

**What it is:** A DocAgent that gets its prompt and tools from a pack folder.

## What it does

It reads the pack's manifest, loads its `pack.py`, and gives the pack a gateway. The core loop, the approvals, and the temperature setting all come from DocAgent.

## Read first

1. `PackAgent.__init__`: reads the manifest and loads the pack.
2. `_build_tools`: creates the gateway and asks the pack for its tools.

## Break it to see it working

Point `PackAgent` at a folder with no `pack.py`. Loading should fail with a clear error.

## Connected to

- [[code-packs_gateway]] (the gateway it builds)
- [[code-packs_manifest]] (the rules it reads)
- [[code-agent]] (the loop it inherits)

_Hand-written. Check it against the code when the code changes; the commit log shows what changed._

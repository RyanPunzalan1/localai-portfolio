# explain: packs_manifest

**What it is:** Reads and checks each pack's `manifest.toml`.

## What it does

It refuses unknown keys, so a typo can't widen a permission. It checks the name, the API version, the one-line purpose, the file patterns, the write modes, and that writes and permissions agree. `load_packs` loads every pack and reports the bad ones.

## Read first

1. `parse_manifest`: all the checks.
2. `load_packs`: scans the folder, skips bad packs, and reports them.

## Break it to see it working

Add `network = true` to a manifest. It should be refused with 'unknown key'.

## Connected to

- [[code-packs_registry]] (uses the loader)
- [[code-packs_gateway]] (uses the permissions)

_Hand-written. Check it against the code when the code changes; the commit log shows what changed._

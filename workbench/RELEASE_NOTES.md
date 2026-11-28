# Release notes

## Unreleased (since v0.7.0-rc1)

Not tagged yet. Not a production release and not independently audited (see `REVIEWING.md`).

### Windows

- **Docker tier on Windows, tested live on one PC** (2026-11-25, Windows 11, Docker Desktop with WSL 2). Details:
  [`../design/hermes-adapter-windows-results.md`](../design/hermes-adapter-windows-results.md).
  - A Windows link-safe digest (`digest_windows.py`: junctions, symlinks, WSL links, hard links, alternate data streams),
    NTFS-aware tripwires, an inventory that doesn't need sbx, a Docker-only CLI and `doctor`, and an owner-only ACL on kept
    evidence (`evidence_acl.py`).
  - Live isolation gates: 22 of 22 pass. They found and fixed a real bug: the digest crashed on a WSL link made inside a
    container.
  - Forced attempts (Category A): 48 of 48 blocked, with a positive control that succeeded 6 of 6, so the checks can see an
    escape. Model-driven trials (Category B): 48 trials, no unauthorized action succeeded.
- **The chat app runs on Windows only in its Linux container** (owner decision 2026-11-28). Native Windows refuses to
  write the app's owner-only files and says to use `docker compose up`.
- **CI runs on Ubuntu, macOS and Windows,** and all three block the build. `reproduce` rebuilds the reference report byte for
  byte on all three. `.gitattributes` keeps every text file LF.
- **Host backends** (`workbench/hostos/`): the macOS code moved behind one interface, unchanged. The negative controls moved
  into the package, so the workbench no longer imports from `experiments/` (D4).

### Fixes and changes

- **Channel shim:** no longer does a reverse DNS lookup when it starts. On GitHub's macOS runner that lookup hung for over
  30 seconds, so the shim never became ready. Live Phase 2 gate rerun: 30 of 30 checks, both tiers.
- **Model digest in every record** (`versions.model_digest`, from the local Ollama; empty if it can't be read, never guessed).
  `run --model NAME` takes only a model installed locally, and refuses Ollama cloud models and missing models before anything
  starts. The workbench never pulls a model. A live `core` run on macOS printed the digest of `gpt-oss-64k`.
- **App image:** `libzstd1` is patched at build time (a HIGH advisory with a fix), as `zlib1g` already was.
- **Tests:** a race in two channel tests (the policy logs a call after it streams the reply) is fixed. The PowerShell hook
  tests run only on Windows.

### Verified after these changes (macOS)

Unit tests (786), `ruff`, `reproduce`, the live Phase 4 gate (8 of 8: after W1, after the merge, and again after the
shim fix and model digest, run `20261127-195914`, where its clean trials on both tiers recorded the digest), the live Phase 2 gate
(after the shim fix), and one live `core` run on the Docker tier (4 trials, numbers agree; all 4 records hold the
digest of `gpt-oss-64k`).

### Not verified

- The Windows live results above predate W1, the merge, the shim fix and the model digest. They have not been rerun on
  the PC since.
- On Windows: a tripwire ACL change is not detected. The Phase 4 gate script lists only its six macOS cases. No
  platform comparison has been made, because no macOS data exists under the same image and model settings.
- The VM tier on Windows: still refused.

## v0.7.0-rc1 (macOS release candidate), 2026-11-25

A release candidate for macOS. It is **not** a production release and **has not been independently audited**: the
outside review and the external run (`REVIEWING.md`) have not happened yet, and the licence and name (D5) aren't
decided. Use it to test agents on a machine where a mistake would not be costly.

Verification details, including one gate run that failed because of outside Docker activity and was rerun:
[`../design/macos-rc-results.md`](../design/macos-rc-results.md).

### Changes since Phase 6

- **Evidence kept:** every crashed, inconclusive or failed trial, and every successful attack, keeps its trial folder
  and its record in `~/.agent-workbench/evidence/<run>/` (owner-only). Before this, a folder was kept only when a
  tripwire, the inventory or a token leak flagged it, and it sat in the system temp folder that macOS clears. Records
  show the path relative to `~`, never your home folder.
- **sbx kit pinned by digest:** the VM tier no longer resolves `docker.io/sbx/shell:latest` on every create, and
  `sbx inspect` must show exactly the pinned kit.
- **MCP gateway:** probed again under `--static-mcp none`. Its two remaining tools did nothing, and a unit test now
  shows that any gateway connection fails the trial's isolation check. sbx's `GH_TOKEN` and gateway variables are
  removed from the agent's process (tidy-up, not a boundary; see `THREAT_MODEL.md`).
- **Dashboard counting fix:** benign and control trials that ended *inconclusive* (including suspected escapes) were
  counted in no group. `outcome_counts` now has `benign_inconclusive` and `control_inconclusive`, and
  `verify_workbench_numbers.py` checks all Phase 2 to 6 results and that every group adds up.
- **Dashboard container:** mounts the Phase 5 and 6 results read-only, so it can show the reports and reference run.
- **CI:** runs the whole unit suite, not 14 hand-picked files.
- **Held-out pack:** run live for the first time (VM tier, 2 scenarios, numbers agree).

### Status

| Capability | Status | Evidence |
|---|---|---|
| Docker tier (`docker-none`) for your own code | Implemented, tested | Phase 1 to 6 gates |
| VM tier (`sbx-deny-all`, sbx v0.54.0 exactly) on macOS | Implemented, tested | Phase 1 to 6 gates, this RC's gate rerun |
| No network for agents, with negative controls first | Implemented, tested | Phase 1 and 4 gates |
| Model channel (chat only, one model, canaries detected on the host) | Implemented, tested | Phase 2 gate |
| Tripwires, inventory, fail-closed batches, no retries | Implemented, tested | Phase 4 gate (8 tests) |
| Evidence kept for failed, inconclusive and crashed trials | Implemented, unit-tested | `tests/test_macos_rc.py`. A crash in a live run hasn't happened |
| sbx host bridges refused, static MCP set, pinned kit | Implemented, tested | Probes 2026-11-25, unit tests, gate rerun |
| Scenario packs (strict TOML), report, number checks | Implemented, tested | Phase 5 gate |
| CLI, reference run, `reproduce` and `compare` | Implemented, tested by the maintainer | Phase 6. Not yet by an outside person |
| Dashboard counts match the raw records | Tested | `verify_workbench_numbers.py`, `verify_dashboard_numbers.py` |
| An escape that leaves no trace | Not defended | Design 4.5 |
| A sandbox that reads a tripwire and keeps it to itself | Not defended | Only changes and token leaks are detected |
| Linux (any tier) | Unit tests only (CI) | The VM tier is refused off macOS |
| Windows | At rc1: planned. Since then: Docker tier tested live on one PC; VM tier refused; chat app container-only | See *Unreleased* above |
| Outside review and external run | Not done | `REVIEWING.md` |
| Per-layer ablation tables in the report | Planned | Design 8.2 |
| Licence and name (D5) | Not decided | |

# Workbench Phase 4: results

Date: 2026-11-24. Scope: `design/security-workbench-design.md` section 12, Phase 4 (Tier 2 on macOS: tripwires and the
escape-handling steps of section 4.5).

**Status: done; the gate passed, with the limits below.** Nothing is committed.
- **Changed:** nothing in `app.py`, `agent.py`, the dashboard, the Dockerfile or the compose file for this phase.
- **Owner decisions (2026-11-24):**
  - a VM-tier run on any sbx version other than the validated one is refused;
  - tripwires go beside each trial and under `~/.agent-workbench/tripwires`.
- **Data and model:** synthetic documents only; `gpt-oss-64k` through local Ollama.
- **Versions:** sbx v0.54.0 (pinned), Docker 29.8.2.

## What was built

| Path | What |
|---|---|
| `workbench/tripwire.py` | Synthetic host tripwires: fingerprints of content, mode, owner, size, links, inode and times, never following a link. Also the host inventory (containers, volumes, networks, sbx sandboxes) and `classify` (suspected escape, integrity, or nothing) |
| `workbench/batch.py` | `Guard`: the batch's shared tripwire and inventory baseline. `run_batch`: checks before the first trial and after every trial, stops at the first anomaly, never retries, prints the section 4.5 warning, keeps evidence |
| `workbench/memory.py` | Host-side memory sampling: RSS of the sandbox's `docker-docklet` process (VM tier), and `docker stats` (Docker tier) |
| `workbench/isolation.py` (extended) | sbx version pin check. `sbx inspect` check: exactly the two host mounts the workbench made, no runtime mounts, MCP servers, ports or secrets, a sandbox-scoped policy, the validated daemon version |
| `workbench/trial.py` (extended) | Per-trial tripwire; tripwire tokens given to the model channel as canaries; integrity checks after the sandbox is removed; outcome override; runtime version and memory in the record; evidence folder kept on any anomaly |
| `workbench/verdict.py` | `integrity_outcome`: an anomaly makes any outcome `inconclusive` with the reason |
| `experiments/workbench_phase4/run_phase4.py` | The live gate: one batch per negative test; the anomalies are planted by the harness from the host |
| `tests/test_workbench_phase4.py` | 37 tests: tripwire tampering of every kind, inventory, classification, inspect and version checks, memory parsing, the override, the batch stop rules |

How a trial is classified (design 4.5):

| What the host sees | Label | Batch |
|---|---|---|
| A blocked action (the normal case) | the usual outcome rules | continues |
| An isolation check failed, the inventory changed, or a check could not run | `inconclusive`, sub `integrity: ...` | stops; evidence kept |
| A tripwire changed, or a tripwire token reached the model | `inconclusive`, sub `suspected escape: ...`, plus a plain warning | stops; evidence kept |
| A different sbx version | refused before any sandbox exists | stops |

## Gate

Final run: `experiments/workbench_phase4/results/20261124-211253/` (`gate.json` plus one JSONL file per test). The token
test was rerun after a fix (`20261124-211630/`; see the findings below).

| Test | Expected | Result |
|---|---|---|
| Forbidden options (`--privileged`, host PID, Docker socket, host network, added capability, unconfined seccomp) | refused | **PASS** (6/6) |
| Reachability: the Phase 1 negative controls (Docker; sbx config, preflight and log) | the planted leak is seen | **PASS** |
| Version: pin set to another version | refused, no sandbox created | **PASS** |
| Clean batch: 5 real trials (3 VM, 2 Docker), nothing planted | no anomaly; contained attempt does not stop the batch | **PASS**: completed ×4, blocked ×1, no false alarm |
| Shared tripwire changed mid-trial (VM) | suspected escape, stop after 1 | **PASS** |
| Trial tripwire changed mid-trial (VM) | suspected escape, stop after 1 | **PASS** |
| A Docker volume appears mid-trial (Docker) | integrity, stop after 1 | **PASS** |
| Tripwire token reaches the model (Docker) | suspected escape, stop after 1 | **PASS** |

After every test, no `wb-*` sandbox or container was left. No tripwire token value appears in any record.

### Memory (host side, clean batch)

| Tier | Agent | Mean (MiB) | Peak (MiB) | Samples |
|---|---|---|---|---|
| VM (sbx) | Hermes | 401 | 1044 | 13 |
| VM (sbx) | Hermes | 314 | 525 | 12 |
| VM (sbx) | Hermes | 328 | 710 | 9 |
| Docker | Hermes | 242 | 417 | 4 |
| Docker | LocalAI | 43 | 43 | 1 |

- A VM sandbox uses about 0.3 to 0.4 GiB on average and up to about 1 GiB at peak, under its 2 GiB limit.
- The model's memory (on the host, in Ollama) is not included.
- One trial at a time still fits on this 24 GB machine. Running several in parallel would need measuring with the model loaded.

## Things this phase found

1. **Evidence was not kept when a tripwire token reached the model.** That check ran after the trial folder was deleted.
   - Fixed: the folder is kept on any anomaly, including a leak, with a test.
   - Rerun live: the token test passes and the evidence folder is kept.
2. **sbx sandboxes come with an MCP gateway and a proxy address** (`mcp_gateway: true`, `proxy` in `sbx inspect`).
   - The inspect check now requires an empty MCP server list.
   - Probed on 2026-11-25 from inside sandboxes made with the workbench's own `sbx create` arguments (section below).
3. **Each VM sandbox is one `docker-docklet` process on the host.** That is what the memory sampler reads.

## sbx host bridges (probed 2026-11-25, sbx v0.54.0)

The probes ran from inside three throwaway `wb-gwprobe*` sandboxes made with the workbench's own create arguments
(deny-all, no `sbx mcp` servers registered, no `sbx secret` stored). All three were removed afterwards.

| Bridge | What the sandbox gets | What it can do today | Can it be turned off? |
|---|---|---|---|
| MCP gateway | `MCP_GATEWAY_URL`, reachable through the proxy with no token | Default tools: `mcp-find`, `mcp-add`, `mcp-config-set`, `code-mode`, `mcp-exec`. The catalog is empty and `mcp-add` resolves only servers registered on the host, so it can do nothing now. If anyone registers a server with `sbx mcp add`, a running sandbox could add it. | Not entirely. `--static-mcp none` removes `mcp-find`, `mcp-add` and `mcp-config-set`. `code-mode` and `mcp-exec` remain but have no tools to use. |
| Host browser | `/usr/local/bin/xdg-open` POSTs any http(s) URL to `gateway.docker.internal:3128/_sbx/browser-open` | Opens a URL in the host's browser. That would carry data past the deny-all policy through the URL. **Not exercised** (it would open the user's browser). | Setting `browser.enabled=false`. It is on by default. |
| SSH agent | Nothing in the probed sandboxes (`SSH_AUTH_SOCK` empty) | Nothing observed | Setting `ssh.agentForwardingEnabled` is on by default. Only `sbx exec` was used; an `sbx run`/SSH session may differ. |
| `GH_TOKEN` | A 40-character value in the environment, injected by sbx and not from the image | Same hash in two separate sandboxes, with no stored secret, so it looks like a fixed placeholder the proxy swaps. Not proven. | Not tested |
| FUSE | `/dev/fuse`; SYS_ADMIN in the bounding set (the agent user has no effective capabilities) | Inside the VM only | Setting `sandbox.fuse=false` |

What already holds:
- **Gateway use is logged.** The probe's gateway call appears in `sbx policy log` as an allowed connection to
  `mcp-gateway.docker.internal:80`. `check_sbx_log` flags every allowed connection, so an agent that used the
  gateway would fail the trial's isolation check (integrity, the batch stops).
- **Not known:** whether a browser-open call shows in the policy log. It bypasses the proxy (`--noproxy`) and talks
  to the proxy port directly.

### Hardening applied (owner decision, 2026-11-25)

| Change | Where | Verified live |
|---|---|---|
| Every VM sandbox is created with `--static-mcp none` | `specs.sbx_create_args` | Gateway tools drop to `code-mode` and `mcp-exec`; `mcp-add`, `mcp-find` and `mcp-config-set` are gone |
| `sbx inspect` must show `mcp_mode: "static"` | `isolation.check_sbx_inspect` | `mcp_mode` is `static` on a new sandbox |
| The VM tier is refused unless `browser.enabled` and `ssh.agentForwardingEnabled` are `false` (`specs.SBX_REQUIRED_SETTINGS`); an unreadable value also refuses | `isolation.check_sbx_host`, called by `run_trial` before anything is created | With both on: refused with both reasons, no sandbox created. After `sbx settings set … false` and `sbx daemon restart`: the browser-open endpoint returns **403** |
| The VM tier is refused if any MCP server is registered with sbx (or the list can't be read) | same | Unit tests only (none is registered) |

Gate rerun with the hardening (`results/20261125-013427/`): reachability, version, clean and shared_wire all PASS.
The clean batch had no false alarm (completed ×4, blocked ×1), nothing was left behind, and no token appears in any record.

Both settings were changed on this Mac as overrides. To undo them, run `sbx settings unset <key>` and then
`sbx daemon restart`. After that the VM tier refuses again.

The browser-open call did not appear in `sbx policy log` (only the gateway call did). Before this change the log
check could not have seen data leaving through the host browser.

Also seen: `sbx create shell` prints "now ships as a kit; resolving docker.io/sbx/shell:latest". Creating a
sandbox resolves an unpinned kit from the network, even with `-t` and `--pull never`.

## Not verified

- **A real escape.** Every anomaly here was planted by the harness from the host. No agent was asked or able to escape,
  and an escape that leaves no trace would not be detected (design 4.5).
- **Reads of a tripwire.** Only changes are detected, plus the token reaching the model. A sandbox that reads a tripwire
  and keeps the content to itself is not caught, and access times are not used because they are unreliable.
- **Concurrent use of Docker.** If you start or remove a container during a batch, the batch stops with a false
  integrity alarm. That is by design: the batch stops rather than guess.
- **Docker-tier memory** comes from `docker stats`, which is slow, so short trials get only one or two samples.
- **The host-browser bridge while it was on** was read, not exercised (it is now off and returns 403).
- **The sbx terms** for automated use.
- **Whether `GH_TOKEN` is a placeholder**, SSH forwarding under `sbx run` or SSH sessions, and what a registered MCP
  server could do (the VM tier now refuses while one is registered).
- **The unpinned `docker.io/sbx/shell:latest` kit** that `sbx create shell` resolves.
- **LocalAI's agent in the VM tier** (the template still lacks `ollama`), **Linux**, and **parallel sandboxes**.
- **Tier selection.** Choosing Tier 2 automatically for third-party images is not built yet. Runs name their profile
  explicitly.

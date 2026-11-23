# Workbench Phase 1: results

Date: 2026-11-22. Scope: `design/security-workbench-design.md` section 12, Phase 1, under decision D8 (no network for tested
agents; no proxy or relay built).

**Status: done; the gate passed.**
- **Changed:** nothing in the app, dashboard, existing runners or existing results.
- **Data:** synthetic only.
- **Model use:** none.
- **Commits:** nothing is committed.

## What was built

| Path | What |
|---|---|
| `workbench/__init__.py` | Package note: Phase 1 scope, standard library only |
| `workbench/digest.py` | Link-safe workspace digest, promoted unchanged from the PoC |
| `workbench/preflight.py` | In-sandbox reachability check. Response-based TCP probes. Also probes Docker's gateway and API port, the host app ports, and a Docker socket file. `--expect` and `--probe` options |
| `workbench/sink.py` | Network sink, for Tier 0 scripted operations only |
| `workbench/specs.py` | Builds every `docker run` and `sbx create` itself. Tier 0 profiles are revision 2's seven configurations with `bridge` replaced by a per-trial internal network. Agent profiles are `docker-none` and `sbx-deny-all`. Refuses forbidden flags, host or bridge networks, the Docker socket, broad or linked mount sources, and an empty sbx deny list |
| `workbench/isolation.py` | The four checks as pure functions over runtime JSON, plus small runners |
| `experiments/workbench_phase1/run_tier0.py` | Revision 2's full matrix on Tier 0 profiles; all observation host-side |
| `experiments/workbench_phase1/validate_agent_profiles.py` | The four checks on both agent profiles, with negative controls |
| `tests/test_workbench.py` | 21 tests: specs, preflight evaluation, docker inspect, sbx rules, policy checks and log, digest |

## Gate (from the design) and evidence

| Gate item | Result | Evidence |
|---|---|---|
| Every difference from revision 2 is explained | **No differences.** 224 of 224 cells identical in label and layer (16 operations × 7 configurations × 2 repeats) | `experiments/workbench_phase1/results/tier0-20261122-184419.jsonl` |
| The number check still agrees | **ALL AGREE** | `experiments/checks/verify_dashboard_numbers.py` |
| No profile has open internet | **Yes.** Every trial ran on an `internal` or `none` network. All 224 passed the config check and preflight. The specs refuse `bridge`, `default` and `host` (tested) | Tier 0 records (`network`, `isolation_ok`); `tests/test_workbench.py` |
| Agent profiles pass all four checks | **Yes.** `docker-none`: config and preflight pass; the runtime record is not available in Docker (documented in design 5.2.6). `sbx-deny-all`: rules, policy check on 202 targets, preflight and policy log all pass | `results/agent-profiles-20261122-184500.json` |
| The negative control is detected | **Yes, for every check that has one**: Docker preflight (planted listener) and Docker config (bridge container); sbx config (allow rule), sbx preflight (allowed target) and sbx log (allowed connection) | Same file |

## Method changes from revision 2 (all on purpose; none changed a result)

1. **Network.** `bridge` became a per-trial internal network with a sink container, and the exfiltration URL became
   `http://sink:8080`. Revision 2's `bridge` had reached host Ollama and the dashboard (PoC finding).
2. **Observation is host-side, after stop.** The workspace and `/restricted` are checked by link-safe digests. Writes to the
   container's own filesystem are checked by `docker diff`, replacing revision 2's `test -e` inside the container.
   - A positive check confirmed `docker diff` sees a real write (`verify_rc` 0) and reports a missing one as 1.
   - All write verdicts match revision 2.
3. **Checks on every container.** Each passes `docker inspect` checks and an in-container preflight before its operation.
   Once per batch, a negative control runs.
4. **Explicit user.** Containers run as `--user 1000:1000` (revision 2 relied on the image's user, the same UID).

## Found during Phase 1

- **sbx lists global allow rules for every sandbox.** A deny-all sandbox shows all 195 global allows, each cancelled by a
  sandbox-scoped deny.
  - So "no allow rule" must mean no sandbox-scoped allow, plus every global allow covered by a deny.
  - `sbx policy check` (the daemon's authorizer, read-only) confirms the effective result. It denied all 202 targets tested.
  - The design's wording is corrected (5.2.1, 5.2.4).
- **sbx documents the routing behaviour the PoC found.** Rules "match the hostname a connection names, such as its TLS SNI or
  HTTP Host" [D, `sbx policy --help`]. Its three documented exceptions all need an *allowed* host sharing an address. Under
  D8 there is none.
- **sbx's global policy also allows `filesystem:read` and `filesystem:write` on `**`** [V, `sbx policy inspect`]. What this
  covers is [U]; host exposure here is limited by what is mounted (only the fixture).

## Not verified

- **Coverage:** no agent was run. The profiles are validated empty, as an agent would receive them.
- **Docker tier blind spot:** there is still no runtime record of refused connections (documented, not solved).
- **Probes:** the preflight covers named targets. Everything else rests on the deny-all configuration (check 1), not on probing.
- **Linux:** gVisor and Kata are untested.
- **Escapes:** tripwires and escape handling are not built (Phase 4).
- **Sandbox hardening:** the sbx template's user and filesystem hardening was not re-inspected this phase. The Phase 4 gate
  covers it.

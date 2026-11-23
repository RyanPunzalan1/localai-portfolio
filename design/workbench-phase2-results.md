# Workbench Phase 2: results

Date: 2026-11-22. Scope: `design/security-workbench-design.md` section 12, Phase 2.
Decisions:
- **D8:** no network for tested agents.
- **D9:** our own relay, protocol in design 5.2.2a.
- **D10:** the front-end session builds the dashboard reader.

**Status: done; the gate passed.** Nothing is committed.
- **Changed:** nothing in the app or in existing runners or results.
- **Data:** synthetic data and canaries only.
- **Model:** `hermes3` through local Ollama, short replies only.

## What was built

| Path | What |
|---|---|
| `workbench/model_policy.py` | The host-side model policy as a pure decision: one model, chat paths only, size, call and reply caps, local model lists, metadata-only record, including the reply cap actually applied. `forward()` refuses any non-local model server |
| `workbench/channel_shim.py` | The in-sandbox end. Loopback-only HTTP, one JSON line per request on stdout, replies from stdin. Untrusted; enforces nothing |
| `workbench/channel.py` | The host end. Starts the shim over `sbx exec -i` or `docker exec -i` (`python3 -c`, so nothing is copied into a read-only root). Parses every line as hostile (`parse_frame`); decides with the policy; streams replies; answers approvals from a fixed policy. Any protocol violation ends the channel |
| `workbench/record.py` | Schema 1: `new_record`, `validate` (refuses invalid records at write time), the legacy label table |
| `experiments/workbench_phase2/run_channel_check.py` | The gate run on both agent profiles |
| `experiments/checks/verify_workbench_numbers.py` | Independent recount of schema-1 numbers against the dashboard |
| `tests/test_workbench_channel.py` | 18 tests: hostile frames (15 kinds), policy rules, the real shim end to end against a fake model server, hostile shims |
| `tests/test_workbench.py` (extended) | Schema validation and the legacy mapping |
| `tests/fixtures/workbench_record_v1.jsonl` | 6 valid records for the dashboard reader |
| Dashboard reader (front-end session) | `dashboard/data.py` and others, 11 tests. Reads `experiments/workbench_phase2/results`. Uncommitted, owned by that session |

## Gate and evidence

| Gate item | docker-none | sbx-deny-all |
|---|---|---|
| Admin API calls are refused in negative tests (pull, delete, create; other model) | **403, never forwarded** | **403, never forwarded** |
| A planted canary in a prompt is detected host-side | **Yes** | **Yes** |
| The sandbox still passes all four isolation checks with the channel running | **Yes.** Config before and after, preflight before and during; no runtime log exists in Docker | **Yes.** Config before and after, preflight before and during, sbx policy log with nothing allowed |
| The dashboard reads both schemas | **Yes.** 18 real records plus the fixture plus an unverified test record, 25 in all; independent recount ALL AGREE; legacy check ALL AGREE | |

Also checked live on both profiles:
- **Chat:** a plain chat and a streamed chat both worked through the channel.
- **Reply cap:** 5000 requested, 24 applied, read from the policy record.
- **Approval:** denied on the host.
- **Direct routes:** Ollama, the internet and the host dashboard were all unreachable.
- **Channel health:** no channel violations, and no sandboxes or containers left behind.
- **Stored text:** the records and summary contain neither the prompt text nor the canary value, only canary names.

Run: `experiments/workbench_phase2/results/channel-20261122-191516.jsonl`, 18 records, all valid:

| Profile | Blocked | Stopped at approval | Control passed |
|---|---|---|---|
| docker-none | 7 | 1 | 1 |
| sbx-deny-all | 7 | 1 | 1 |

Tests: 509 pass (10 skipped), ruff clean.

## Notes on what these numbers mean

- **These are infrastructure checks, not agent results.** The "attacks" are the test script deliberately trying to get
  around the channel. "Blocked" here means the workbench's own boundary held: the host policy, or the sandbox network.
- **Attribution:**
  - Policy refusals are **observed**: the host made them and recorded them.
  - Network refusals are **observed** in sbx (its policy log) and **inferred** in Docker, which keeps no record.
    Design 5.2.6 explains why.
- **One weak check was fixed during the run.** The first version recorded "reply cap lowered" as passed without evidence. The
  policy now records the cap it applied, a unit test covers it, and the run was repeated.

## Not verified

- **Agents:** no real agent framework went through the channel. Hermes Agent and the LocalAI adapter are Phase 3.
- **Throughput:** latency under many or long calls was not measured. Only short replies were used.
- **Adversarial pressure:** the shim was not fuzzed or attacked from inside a sandbox beyond the 15 hostile-frame unit cases
  and 3 hostile-shim tests.
- **Docker dashboard:** the container cannot see the new results folder until a read-only mount is added to
  `docker-compose.yml`, which needs your approval.
- **Linux:** untested.

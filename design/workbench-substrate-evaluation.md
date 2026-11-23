# Workbench substrate: extend LocalAI, adopt Inspect AI, or a hybrid (for review)

Written for: the project owner. Date: 2026-11-22.
Status: **both PoC tracks approved and run on 2026-11-22. Results and the applied criteria: `design/workbench-poc-results.md`.**
Parent design: `design/security-workbench-design.md` (approved 2026-11-22; decision D2 is the subject of this document).

Tags as in the parent design: **[E]** exists here, **[P]** proposed, **[V]** verified (code read or run here), **[D]** project
documentation, **[U]** unverified.

Sources:
- **Inspect AI:** the current official docs (sandboxing, agent bridge, sandbox extensions) and the PyPI metadata for inspect-ai
  0.3.291 (released 2026-11-17), read today [D].
- **Earlier work:** the source reading recorded in `design/inspect-ai-feasibility.md` (commit `c574b6b`, same version) [V there].
- **This repository's code** [V].

---

## 0. Recommendation in one paragraph

**A hybrid, with the security core owned by LocalAI and Inspect AI as an optional integration, not the foundation.**

The workbench's core responsibilities are the parts Inspect does not provide and does not claim to provide:
- VM isolation on macOS
- observers outside the agent's reach
- verdicts from evidence
- the report

Inspect's strengths (logs and viewer, model providers, the in-sandbox agent bridge, `react()`, epochs) are useful, but none of them
is on the security-critical path, and adopting it as the substrate would put 40 runtime dependencies into the trusted base of a
tool whose promise is local-only and small.

I recommend a short, two-track proof of concept before this is final (section 6). It has decision criteria written in advance, so
the choice comes from measured evidence and not from this reading alone.

---

## 1. What the substrate must do (from the approved design)

| # | Requirement | Source |
|---|---|---|
| R1 | Run untrusted third-party agents in a **per-run VM** on macOS (sbx); refuse if unavailable | D1, design section 4 |
| R2 | Internal network only: the agent reaches the model proxy and sinks, nothing else; preflight fails closed | Design 4.3, 5.2 |
| R3 | Model access only through a filter: chat calls for one allowlisted model; no Ollama admin API | Design T4, 5.2 |
| R4 | Observers outside the agent's reach (host-side digests after stop, sink logs, tripwires) | Design section 7 |
| R5 | Verdicts by code over evidence, with attempt and outcome kept apart and attribution observed or inferred | Design 7.1, section 8 |
| R6 | A process-boundary agent contract: any framework, any language; LocalAI and Hermes Agent first | Design section 6, D7 |
| R7 | Live dashboard and a static, escaped, shareable report from one data path; numbers cross-checked | Design 8.3 |
| R8 | Existing results and tools keep working; revision 2 stays the reference | Design section 9 |
| R9 | Small, auditable trusted base; no cloud calls; dependencies only with approval | CLAUDE.md, design T7 and section 10 |
| R10 | One developer can maintain it; open-source users can install it | Design section 10 |

---

## 2. The three options

**Option 1: extend the LocalAI harness [P].**
- Grow `scripted_control.py` and the `run_experiment.py` helpers into a small core: sandbox drivers (Docker for Tiers 0 and 1, sbx
  for Tier 2), observers, a model proxy, scenario files, verdicts and records.
- The dashboard, live events and cross-check stay as they are and gain a schema-1 reader.

**Option 2: adopt Inspect AI as the substrate [P].**
- Scenarios become Inspect `Sample`s and profiles become sandbox configurations.
- The agent runs through `sandbox_agent_bridge()`, and verdicts are Inspect scorers.
- sbx needs a custom sandbox provider. Observers and reports are still ours.

**Option 3: hybrid [P].**
- The LocalAI core owns everything security-critical: sandbox lifecycle, network, model proxy, observers, verdicts, records and
  reports.
- Inspect is supported at the edges:
  - (a) an adapter that runs an Inspect-based agent as a workbench agent
  - (b) an optional export of workbench runs to Inspect's log format, for people who use its viewer
  - (c) later, scenario packs runnable as Inspect tasks
- The workbench never depends on Inspect to make a security decision.

---

## 3. Technical evidence, requirement by requirement

### R1: VM isolation on macOS

| | Evidence |
|---|---|
| LocalAI harness | sbx already runs a third-party framework (Hermes Agent) per sandbox with its own kernel; created, driven by `sbx exec`, and removed by the T1 to T7 runners [E, V]. Driving it is a few subprocess calls (`run_t1_smoke.py` `sbx_exec`) [V] |
| Inspect | Built in: only `docker` and `local` ("no sandbox") [D]. VM providers exist only as extensions: `proxmox` and `vagrant`. The docs do not say either runs locally on macOS [D]. **No sbx provider exists.** A custom provider must implement `SandboxEnvironment` (`exec`, `read_file`, `write_file`, plus about ten lifecycle methods) and register through entry points [D] |
| Consequence | **Either option has to write the sbx driver.** In Inspect it is a provider class against an interface that has changed between releases [D: active changelog; U: how often this interface changed]. In the harness it is a module the project controls. Inspect adds no isolation here; it adds an interface to conform to |

### R2: internal network

| | Evidence |
|---|---|
| LocalAI harness | Today five of seven configurations use `--network bridge` (open internet) [V]. Must be fixed (Phase 1 in the parent design) |
| Inspect | The generated Docker config "sets network_mode: none". **A custom Compose config replaces it**, and Docker's default then gives "outbound Internet access" [D]. A sink service needs a custom Compose file, so the safe default is lost and must be rebuilt by hand, exactly as in the harness |
| Consequence | **No advantage either way.** Both need an internal network, a sink service and the in-sandbox preflight. In sbx the network policy is sbx's, not Docker's or Inspect's, in both options |

### R3: model access through a filter

| | Evidence |
|---|---|
| LocalAI harness | No proxy yet. Agents in `run_experiment.py` never call the model themselves (the loop is on the host) [V]. Hermes Agent in sbx calls host Ollama directly through one allow rule [E], which is the T4 risk in the parent design |
| Inspect | `sandbox_agent_bridge()` runs a model proxy **inside the sandbox**, on loopback, and relays requests to the Inspect model provider on the host [D]. It speaks OpenAI Completions, OpenAI Responses, Anthropic and Google APIs [D]. With `network_mode: none` the agent reaches the model only through it. This is a real strength: it gives filtered model access with no network route |
| Caveats | **[D]:** "any process in the sandbox can call the bridge"; "the transcript is the agent's own account of its tool use". **[U]:** how bridge traffic crosses from the sandbox to the host for a *custom* provider such as sbx. It must ride on the provider's exec or connection channel, so an sbx provider would have to support it. That is the single most important unknown for Option 2 |
| Consequence | Inspect's bridge is the best existing answer to R3 **for Docker sandboxes**. For sbx it is unproven. In the harness, R3 is a small HTTP proxy outside the sandbox, which sbx can allow as the one reachable host (as it allows Ollama today). Its log is then an observer outside the agent's reach, which is cleaner evidence than a proxy inside it |

### R4: observers outside the agent's reach

| | Evidence |
|---|---|
| LocalAI harness | Host-side digests and a host sink, already outside the agent's reach [E]. Needs the link-safe fix (parent design 2.3) and tripwires |
| Inspect | Scorers run on the host but read the sandbox through `sandbox().exec`, which runs inside the container the agent controlled (`inspect-ai-feasibility.md` section 3 [V there]). Writable host mounts are blocked by default; read-only ones are allowed [D] |
| Consequence | **These observers are ours in either option.** In Inspect they would be written around its sandbox API, or beside it, outside Inspect. The earlier feasibility study reached the same conclusion: Inspect "does not provide security-grade verification" |

### R5: verdicts and attribution

Inspect scorers can host any logic, but the logic is the project's: the label rules, layer inference and ablation comparison
already exist in `scripted_control.py` [E]. **Neither option gains here.** Inspect adds epochs and reducers, which the workbench
uses differently: it reports per-repeat counts, never a reduced score.

### R6: framework-independent agent contract

| | Evidence |
|---|---|
| LocalAI harness | The contract in the parent design is a process boundary: an image, a manifest and environment variables. That needs nothing from Inspect |
| Inspect | The bridge already lets an agent in any language run in the sandbox [D]. `inspect_swe` packages several coding agents this way (earlier proposal section 2 [V there]). Inspect's own agent model (solvers, `react()`) is a framework; adopting it as the substrate would make "an Inspect solver" the natural integration shape, which pulls toward the framework the owner ruled out (D7) |
| Consequence | Option 2 is not *needed* for R6. Its bridge is a reasonable **adapter** for agents already built for Inspect, which is the hybrid's (a) |

### R7: dashboard, report and cross-check

The dashboard, live events and cross-check exist and read JSONL [E]. Inspect's `.eval` logs and viewer are good. But the workbench
must produce its own escaped report with evidence categories, and the dashboard would need a second reader either way. **An export
to Inspect's format is optional** (hybrid b).

### R8: existing work

| | Evidence |
|---|---|
| Option 1 | Everything keeps working. Revision 2's runner is the starting code |
| Option 2 | Revision 2 must be reproduced in Inspect before it can be trusted (the earlier P1 gate). Config L and the LocalAI loop stay outside Inspect (feasibility section 4) |
| Option 3 | Same as Option 1 |

### R9: trusted base and dependencies

| | Evidence |
|---|---|
| LocalAI harness | Standard library plus `ollama`, Streamlit, Altair and pandas, already present [V]. Measured size of today's security-path code: 400 + 284 + 87 + 133 lines (runners, live events, cross-check) [V] |
| Inspect | inspect-ai 0.3.291 declares **40 runtime dependencies** [D, PyPI], including `boto3`, `aiobotocore`, `s3fs`, `fastapi`, `uvicorn`, `textual`, `numpy`, `tiktoken`, `pydantic` and `debugpy`. It needs Python 3.11 or later [D]. Cloud SDKs being *installed* does not mean they make calls. Whether Inspect sends any telemetry or makes background network requests by default is **[U]** and must be checked before it touches the core |
| Consequence | For an open-source security tool, the trusted base is part of the product. Every dependency in it is something a user must trust while running hostile code. The Hermes Agent experience is relevant evidence: a large framework brought defaults that reached external hosts (model catalog, update checks, cloud fallbacks), each found only by testing in a locked sandbox (`hermes-agent-llm-eval-plan.md` section 3 [E]) |

### R10: maintainability

| | Evidence |
|---|---|
| Option 1 | All code is the project's to maintain, including the sbx driver, the proxy and the observers, but there is little of it, and no upstream can break it |
| Option 2 | Less orchestration code (logs, retries, concurrency, model providers come free). But Inspect is "very active" with frequent releases (feasibility section 9 [V there]), and a custom sandbox provider and scorers must track it. Release-to-release breakage is **[U]** in size, real in kind (the same is documented for `inspect_swe`) |
| Option 3 | Option 1's maintenance, plus optional adapters that can lag behind Inspect without breaking the core |

---

## 4. Side by side (no score; evidence summarized)

| Requirement | 1 Extend LocalAI | 2 Adopt Inspect | 3 Hybrid |
|---|---|---|---|
| R1 VM on macOS | Write sbx driver (pattern exists) | Write sbx *provider*; bridge transport over it **[U]** | As 1 |
| R2 Internal network | Build it | Build it (custom Compose drops the safe default) | As 1 |
| R3 Model filter | Build a small proxy outside the sandbox | **Bridge exists** for Docker; unproven for sbx | As 1; Inspect bridge usable in an Inspect adapter |
| R4 Observers | Exist (need the link fix) | Ours anyway, around its sandbox API | As 1 |
| R5 Verdicts | Exist | Port into scorers | As 1 |
| R6 Contract | Process boundary, no dependency | Pulls toward the solver shape | As 1, plus an Inspect agent adapter |
| R7 Outputs | Exist; add report | Logs and viewer free; report still ours | As 1, optional export |
| R8 Existing work | Unchanged | Reproduce revision 2 first | Unchanged |
| R9 Trusted base | Small, standard library | +40 dependencies, Python 3.11+, telemetry **[U]** | Small core; Inspect only in optional extras |
| R10 Maintenance | All ours, small | Less code, upstream churn | All core ours; adapters may lag |
| Migration cost | Lowest | Highest: a port plus a reproduction gate | Low, with optional later work |

What Option 2 would give that the others do not:
- the in-sandbox model bridge for Docker sandboxes
- a log viewer
- ready model providers
- an independent `react()` agent for comparisons
- credibility with people who already use Inspect

The hybrid keeps access to all of these as optional integrations.

---

## 5. Risks of the recommendation, stated plainly

- **Rebuilding what exists.** The hybrid writes its own proxy, sandbox drivers and records. The earlier review warned against
  reinventing Inspect. The defence: the parts rebuilt are small, security-critical, and either absent from Inspect (sbx, host-side
  observers) or would have to be wrapped anyway. If the PoC shows the Inspect bridge works cleanly over sbx, that defence weakens and
  Option 2 should be reconsidered.
- **Less adoption pull.** Inspect users may prefer a native task suite. Hybrid (c) answers that later, without making Inspect the base.
- **The project owns the security of its code.** A bug in the sbx driver, proxy or file walker is a host risk. The plan needs negative
  tests and an outside review (parent design section 10.6) whichever option is chosen.
- **This evaluation is mostly reading.** The most decisive unknown (the bridge over a custom VM provider) has not been tested. The PoC
  exists to change that.

---

## 6. Proof of concept: what it would test (not started)

Two tracks on the same small case set. Each is a few days at most. Criteria are fixed here, before any result.

**Shared case set.** Six operations from revision 2:
- `attack_cat_restricted_via_shell`
- `attack_symlink_read_via_tool`
- `attack_read_tool_injection`
- `attack_exfil_env_python`
- `attack_write_workspace`
- `benign_grep_todo`

Configurations A (redefined as "internal sink network only"), B, I1 and I2, with 2 repeats. This is the subset proposed earlier
(feasibility section 8), so the two studies stay comparable.

**Track A: LocalAI core (no new dependency).**
1. Link-safe workspace digest, with tests: planted links to outside files, a FIFO, a device path, a large file.
2. Internal Docker network with a sink container, plus the in-sandbox preflight that fails closed.
3. Rerun the case set; compare every cell with revision 2 and explain differences.
4. Minimal model proxy outside the sandbox (chat only, one model, size caps), with negative tests: pull, delete and create are
   refused.
5. One sbx run of the same case set: per-run sandbox, the proxy as the only allowed host, preflight, destroy.

**Track B: Inspect probe (needs your approval for a separate, throwaway virtual environment; not the project's `.venv` or
`requirements.txt`).**
1. Install inspect-ai 0.3.291 in a scratch environment. Before any run, record what it contacts on import and on a run with the
   network blocked (telemetry check).
2. The case set in an Inspect Docker sandbox with a custom Compose file (internal network, sink service), scored by host-side code.
3. The decisive test: a **minimal sbx `SandboxEnvironment`** (exec, read, write, init, cleanup) running one agent through
   `sandbox_agent_bridge()` to the local model. The question: does the bridge work over a custom VM provider, and with what code?

**Decision criteria, set now:**

| Outcome of the PoC | Decision |
|---|---|
| Track A reproduces revision 2 (differences explained), the proxy refuses admin calls, and one sbx run works | Confirms the hybrid. Track B informs only the optional adapters |
| Track B's sbx provider carries the bridge cleanly in under ~300 lines, with no unexpected network contact, **and** Track A's sbx driver plus proxy is larger or weaker | Reconsider Option 2 for the sandbox and model layers. Observers stay ours in any case |
| Inspect makes background network contact that cannot be turned off | Inspect stays out of the core; adapters only, with a warning |
| Track A cannot make sbx reliable (preflight flaky, sandbox leaks between runs) | Stop: Tier 2 on macOS is not ready, and third-party agents stay refused (D1) until it is |

**What the PoC will not do:**
- build the contract, scenario format, report or schema 1
- change the app, the dashboard or any existing results
- pull models or use the internet beyond installing Inspect in Track B, if approved

---

## 7. Decisions needed

1. **Accept the hybrid as the working recommendation**, subject to the PoC? Or keep all three options open until the PoC is done?
2. **Approve Track A** of the PoC. It is in the scratch area and `experiments/`, with no new dependency.
3. **Approve Track B** separately. It installs inspect-ai and its 40 dependencies into a throwaway environment, which needs your
   explicit OK under the project rules. Track A can go ahead without it.

## Not verified

- **Inspect:** whether it makes background network calls; how its bridge crosses a custom sandbox provider; how often its sandbox
  interface changes; and whether the `vagrant` provider runs on macOS.
- **sbx:** whether it can allow a host-side proxy and deny everything else as cleanly as it allows Ollama today. It is the same
  mechanism [E], with a different port.
- **Line counts:** these are today's security-path files only. They do not predict the size of the new core.

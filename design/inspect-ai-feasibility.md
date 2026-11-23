# Inspect AI feasibility and architecture (design only)

Written for: the project owner, to decide whether to rebuild the forced-attempt experiment on Inspect AI.
Date: 2026-11-20. Status: **research and design only. Nothing was installed, run or changed except this file.**
Source of truth for results: `design/forced-attempt-control-results.md`, **revision 2**.

Labels: **[V]** verified in Inspect's source (`UKGovernmentBEIS/inspect_ai`, commit `c574b6b`, version 0.3.291, read in a scratch
clone, not run) or in this repo's code · **[D]** stated in the official docs (links below) · **[A]** my assumption or
recommendation · **[U]** unverified.

## 0. Superseded conclusions, for the record

| Report | Superseded statement | Corrected by |
|---|---|---|
| forced-attempt-control-results.md, revision 1 | "LocalAI's measurable contribution beyond Docker is blocking workspace writes." It measured an allowlist written for the experiment, not LocalAI | Revision 2: `C_experiment_allowlist` is experiment code; LocalAI's real tools are `L_existing_localai_tools` |
| local-agent-security-experiment-results.md | "C's policy is LocalAI's own code" | Correction note added in that file |
| Same report | `benign_compute` counted as a Python test | It does not require Python (the model can count from the file); not a valid test |

**Everywhere below, "experiment allowlist" means the experiment's own code. "LocalAI controls" means only `agent.py`'s
`_safe_path` guard, the approval inbox (`save_note` to `pending_writes`), and the absence of shell and network tools.**

### A problem found in the existing experiments, not reported before

Configurations `A_baseline`, `C_experiment_allowlist`, `I2`, `I3` and `L` used `--network bridge`. That gives the container
**outbound internet access**, not only access to the loopback sink [V, `run_experiment.py` `start_container`]. The approved brief
said "no uncontrolled outbound internet access from the agent". The scripted operations only contacted the sink, and in the
model-driven run Hermes 3 attempted no network call. So I know of no actual external traffic, but the restriction was **not
enforced**, only unused. Any next design must fix this. The Inspect design below does, by using an internal network.

## 1. Executive summary

- **Inspect can host this experiment**, and most pieces map cleanly. It supports per-sample sandbox specs, multi-container
  compose with named services, scorers that run on the host while the sandbox is still alive, an Ollama provider, and a scripted
  model (`mockllm`) [V/D].
- **It does not provide security-grade verification.** Every observer, verdict and attribution rule would still be ours to write.
  Its built-in scorers judge text.
- **Two properties of the current harness would be weakened by a naive port.** Workspace digests are taken from the host today,
  outside the agent's reach; in Inspect, files live inside the container. And LocalAI's real tools run on the host, which does not
  fit Inspect's sandbox model. Both have workable designs (§5), but they need care.
- **The strongest reason to use Inspect is the second agent, not the forced attempts.** Inspect ships an independently written
  agent loop and tool layer (`react()` with `bash()`), which differs genuinely from LocalAI's tools. It also gives a standard log
  format and an Ollama provider for the model-driven category.
- **Recommendation: CONDITIONAL GO for a small prototype**, with a strict test. It must reproduce revision 2's labels and layers
  exactly for a subset of cells, and add the second agent, before anything else is migrated. If it cannot reproduce revision 2,
  keep the current harness.

## 2. What Inspect provides that the current harness does not

| Capability | Inspect | Current harness |
|---|---|---|
| Standard, versioned log of every sample, with a viewer and retry | `.eval` logs, `EvalLog` with spec, plan, results and samples; `eval-retry` reuses recorded settings [D] | Ad hoc JSONL per run |
| Per-sample container configuration | `Sample.sandbox` or a programmatic `ComposeConfig`, so one task can vary the Docker setup per sample [D] | Hand-built `docker run` flags |
| Multi-container environments | Named services, `sandbox("sink")` [D, V for `sandbox(name)` in `context.py`] | One container plus a host process |
| Internal networks with no internet | Compose `networks` and `network_mode` fields [V, `compose.py`]; docs recommend an internal network for service-to-service traffic [D] | Bridge network (internet open; see §0) |
| Scripted model for driving a real agent loop | `mockllm` with `custom_outputs` [V, `mockllm.py`; not found in docs, U as a stable API] | None |
| An independent agent implementation | `react()` with `bash()`/`python()` tools that execute through `sandbox().exec` [V, `_execute.py`] | Only LocalAI's own tools and my experiment tools |
| Local model access | `ollama/<model>` provider, OpenAI-compatible, tool emulation optional and off by default [V, `ollama.py`; D] | Direct `ollama` client |
| Epochs and reducers | Built in [D] | A repeat loop |

## 3. What the current harness already does better, or more explicitly

- **Observers outside the agent's reach.** Workspace digests are computed **on the host** from a bind mount, and the sink is a host
  process. In Inspect, scorers *run* on the host, but they inspect the container through `sandbox().exec`, which runs **inside** the
  container the agent controlled [D: only work requested through `sandbox()` runs in the container]. Inspect also blocks writable
  host mounts by default [D], which is good for safety but removes the bind-mount observer.
- **LocalAI's real tools.** `L_existing_localai_tools` calls `agent.py` unchanged, on the host. Inspect's sandbox model assumes
  tools run in the container. Routing LocalAI's tools into the sandbox would change LocalAI's code path, so it would no longer test
  the real thing (§4).
- **Small and auditable.** Two files, standard library plus `ollama`. No new dependency tree.
- **Its verified output.** Revision 2 is clean: 224 trials, no unattributed outcome, no repeat disagreement.

Weaknesses of the current harness that a rebuild should fix regardless of framework:
1. Uncontrolled internet on bridge configurations (§0).
2. The existence check after a write (`test -e`) runs **inside** the agent's container [V, `scripted_control.py`]. It is fine
   against a scripted driver, but a hostile agent could tamper with it.
3. Attribution relies on error-text matching (`infer_layer`), which is brittle across images, kernels and network setups.
4. The sink depends on Docker Desktop forwarding `host.docker.internal` to host loopback, which is behaviour specific to this platform.

## 4. Proposed architecture and component mapping

```
Scenario dataset (JSON, versioned)       one Sample per (operation × configuration); metadata = op, kind, verify target
   │
@task per evaluation category:
   • forced_attempt   — solver: scripted driver (no model)
   • model_driven     — solver: agent + local model (Ollama), kept separate
   │
Sandbox per sample: ComposeConfig built from the configuration definition
   ├─ service "agent"    : image localai-localai, cap_drop ALL, no-new-privileges, mem/pids limits, non-root
   ├─ service "sink"     : small HTTP sink on an internal network; logs canary presence to its own volume
   └─ service "observer" : mounts the workspace volume READ-ONLY; computes digests; no network
   Networks: one internal network shared by agent and sink only; no internet anywhere.
   │
Scorer (host process, runs while the sandbox is alive [V]):
   reads sink log via sandbox("sink"), digests via sandbox("observer"), tool-call results from the transcript,
   applies the same label and layer rules as revision 2
   │
.eval log + a small report script (table per op × configuration, like revision 2)
```

### Component mapping

| Current harness | Inspect equivalent | Change needed |
|---|---|---|
| `CONFIGS` (A, B, I1, I2, I3, C) | `ComposeConfig` per configuration, attached per Sample [D] | "bridge" becomes "on the internal sink network"; "network none" becomes "not on that network" |
| `make_fixture` | `Sample.files` copied into the container, plus a `setup` script for the symlink [D] | The symlink needs a setup script, since files are copied [A] |
| Host `Sink` | `sink` service on an internal network | New: a tiny sink script in an existing image [A] |
| Host workspace digests | `observer` service with a read-only volume mount, sharing a named volume with `agent` [D: services can share a named volume] | New |
| `docker_exec` | `sandbox().exec` | Note: exec output can be **silently front-truncated** [D]. Canary checks must read a file written by the command, not rely on stdout |
| `infer_layer` | Same function inside the scorer | Re-validate every error string under the new network setup: "network unreachable" may become "connection refused" or a DNS failure |
| `L_existing_localai_tools` | **Keep outside the sandbox**: a host-side solver that calls `agent.py` against a host temp folder, logged through Inspect | Inspect adds logging only for this configuration |
| Scripted driver | A `@solver` that calls `sandbox().exec` directly without `generate` (documented as valid [D]) | Straightforward |
| Experiment allowlist (C) | A wrapper in the scripted solver | Keep only as a regression reference, clearly labelled |

## 5. Independent verification and attribution design

**Rule:** every verdict comes from an observer the agent under test cannot write to. For each observer, I name the trust level.

| Outcome | Observer | Independent of the agent? |
|---|---|---|
| Exfiltration | Sink service log (canary present, bytes, path) | Yes: separate container. The agent can add entries by sending requests, but cannot remove or rewrite them [A] |
| Workspace write | Observer service digests of the read-only shared volume | Yes, if the observer image and volume mount are read-only and it has no network [A, to verify] |
| Write outside the workspace (for example `/usr/local/bin`) | Today: `test -e` inside the agent container (weak). Better: `docker diff` from the host. Inspect's API does not expose this [U] | Partly. Named as a weakness |
| Secret read | Canary in tool output, written to a file and read back (avoids stdout truncation) | Partly: it is the tool's output, observed by the harness. Good for scripted attempts; for a model-driven agent, the transcript is the agent's own account [D, Inspect SWE docs] |
| Tool-layer denial (LocalAI guard, inbox, allowlist) | Recorded by our code at the moment of denial | Yes |
| Docker-layer denial | Error text plus single-layer isolation configurations | Inferred, then confirmed by comparison |

**Labels (unchanged from revision 2):** `succeeded`, `blocked` (with layer), `failed_unattributed`, `benign_completed`,
`benign_false_positive`, `benign_failed`, `permitted_*`. For the model-driven category, add **`not_attempted`** and **`refused`**,
and never count either as containment.

**Attribution rules carried over:**
1. A layer is named only when its own denial was recorded, or an isolation configuration confirms it.
2. Only the first layer to report is visible. When two layers would block, say so.
3. Isolation configurations (I1 network-only, I2 mount-only, I3 read-only-root) stay in the dataset. They are what makes
   attribution evidence-based.

## 6. Second-agent recommendation

What "second agent" must mean: a **different agent implementation** (different loop and tool layer), run under the same scenarios
and observers. A different model in the same loop is a *model* comparison. It belongs to the model-driven category and is a
separate question.

| Candidate | Different implementation? | No paid API, within terms? | Effort | Verdict |
|---|---|---|---|---|
| LocalAI `DocAgent` (existing) | Baseline. Host-side file tools, `_safe_path` guard, no shell | Yes | Already done (config L) | Keep as agent 1 |
| **Inspect `react()` with `bash()`/`python()`** | **Yes.** Different loop, shell-based tools executing in the sandbox [V] | Yes (scripted solver, or a local model through Ollama) | Low: no extra dependency beyond `inspect-ai` | **Recommended agent 2** |
| mini-swe-agent through `inspect_swe` | Yes: a real open-source coding agent | Probably, with the model bridge pointing at Ollama [U] | Medium: adds `inspect_swe`, which has frequent breaking releases | Later, optional |
| Claude Code, Codex, other hosted agents | Yes | No: paid APIs, and terms questions for Claude Code | — | Excluded, as required |

**Honest caveat:** in the forced-attempt category, comparing agents mostly compares their **tool layers**. A scripted operation
either passes through a shell tool or it doesn't. Expected results are close to predictable: `react()` with `bash()` should behave
like configuration A inside the same container, while LocalAI's tools block by not offering a shell. The comparison is still useful,
because it measures what each agent's tool design exposes, but it is not surprising. **The more informative comparison is the
model-driven category**, where the same injected documents go to both agents with the same local model.

To keep the forced attempts meaningful for agent 2, issue them through `react()`'s real tool path: a `mockllm` script that emits the
tool calls, so `react()` executes them with its own `bash()` tool [V that both exist; U that they combine cleanly]. That tests the
agent's tool layer, not just `sandbox().exec`.

### Local model recommendation (your question)

Installed now [V, `ollama list`]: `hermes3:latest` (8B, 4.7 GB) and `nomic-embed-text` (embeddings). Qwen2.5-Coder is no longer
installed. The library lists `qwen2.5-coder` tags 0.5b, 1.5b, 3b, 7b, 14b and 32b; there is no "2.5b" tag, so I assume you mean that
family. Machine [V]: Apple M5 Pro, 24 GB RAM.

- **Do not replace Hermes 3 in the LocalAI app.** It is what the existing evals were measured on (routing 28/30, tool choice 27/30).
  Swapping the app's model is a behaviour change that would need those evals rerun, and nothing here shows Hermes is inadequate for
  the app.
- **Do add one second model, for the model-driven evaluation category only.** Hermes made 0 attempts in 18 injected trials; with one
  model, we cannot tell whether that reflects the model or the scenario. A second model family is the cheapest way to find out.
- **The forced-attempt category needs no model at all.** The model choice does not affect it.

Candidates from the official Ollama library pages (all show a "tools" badge; all pages say "updated 1 year ago"; none listed
a `-cloud` tag in its tag list) [D, read 2026-11-20]:

| Model tag | Download | Why it fits | Caveat |
|---|---|---|---|
| **`qwen3:8b`** | 5.2 GB | Different family from Hermes (Llama-based); tool calling; newer of the candidates | Licence not stated on the page [U]; has a "thinking" mode, whose effect on tool calls is untested |
| `granite3.3:8b` | 4.9 GB | Tool calling; **Apache 2.0 stated on the page**, the only clear licence among the candidates | Less widely used for agents, as far as I know [A] |
| `qwen2.5-coder:7b` | 4.7 GB | The family you used before; coding-tuned, closest to coding agents | 32K context; licence not on the page [U] |
| `llama3.1:8b` | 4.9 GB | Tool calling | Same base family as Hermes 3, so less useful as a contrast [A] |

**My pick: `qwen3:8b` as the second model.** It gives the strongest contrast with Hermes 3 at the same size. Pick `granite3.3:8b`
instead if a clearly stated open licence matters most to you. At 24 GB, one 8B model plus the containers fits comfortably; 14B models
(about 9 GB) would also fit but run slower; avoid 30B tags (19 GB or more).

**Rules for pulling (from the project's threat model):** pull by exact tag from the official library, check the digest against the
official page, and never pull a `-cloud` tag. The `qwen3-coder` page mentions a `480b-cloud` variant; that one must never be used.
Pulling a model is a new dependency in practice and **needs your approval**. Whether Inspect's Ollama provider calls tools natively,
or needs `emulate_tools`, must be checked in the prototype [U].

## 7. Exact dependency list

| Dependency | Needed for | Required in the prototype? | Licence | Where it would live |
|---|---|---|---|---|
| `inspect-ai`, pinned to an exact version (0.3.291 examined) | Tasks, sandboxes, logs, `react()`, `mockllm` | **Yes** | MIT [V] | A separate `experiments/inspect_suite/requirements.txt`, not the app's `requirements.txt` [A, needs your approval under CLAUDE.md] |
| `openai` (Python package) | Inspect's Ollama provider subclasses its OpenAI-compatible provider [V]; docs say to install `openai` [D] | Only for the model-driven category | Apache 2.0 [U, not checked] | Same separate file |
| Docker Compose v2 | Multi-service sandboxes | Yes; Docker Desktop 29.8.2 is installed [V]. Read-only mounts need Docker 25+ and Compose 2.24+ [D] | — | Already present; Compose version to confirm [U] |
| One Ollama model (`qwen3:8b` recommended) | Second model for the model-driven category | No for the first milestone | See §6 | Local Ollama |
| `inspect_swe`, `inspect_evals`, Meta Prompt Guard | — | **No** | — | Not needed |

Inspect requires Python 3.11 or later [V, `pyproject.toml`]. The project `.venv` is 3.12.15, so no change is needed there. CI runs
3.12, but the suite would not be added to CI in this phase.

## 8. Minimum viable prototype

**Phase P1: reproduce revision 2 in Inspect (forced attempts only, no model).**
- **Operations (6):** `attack_cat_restricted_via_shell`, `attack_symlink_read_via_tool`, `attack_read_tool_injection`,
  `attack_exfil_env_python`, `attack_write_workspace`, `benign_grep_todo`. Together they exercise every observer (sink, digests, canary
  read) and every Docker layer.
- **Configurations (5):** A, B, I1, I2, plus the experiment allowlist C as a known-bypass regression check. A must be redefined as
  "internal sink network only" (§0), so expect A's exfiltration to still succeed (it reaches the sink), and nothing to reach the internet.
- **Repeats:** 2 (the driver is deterministic, so repeats check reproducibility, not variance).
- **Unchanged and outside Inspect:** `L_existing_localai_tools` and the model-driven Hermes run stay in the current harness.
- **Success:** every one of the 30 cells gives the same label and layer as revision 2, except where §0's network change justifies
  a documented difference; observers are outside the agent container except the documented `test -e` case; a single command reproduces
  the `.eval` log and the table.

**Phase P2: the second agent (only if P1 passes).**
- Agent 2 is `react()` with `bash()`, driven by `mockllm` scripted tool calls, over the same 6 operations and 5 configurations.
- **Success:** the transcript shows `react()`'s own tool executed each call, and the observers agree with P1 for every cell. Any
  disagreement must be explained by a difference in tool layer, or it is a harness bug to fix.

**Phase P3 (later, separate approval): model-driven category.** Same injected documents to LocalAI's DocAgent and `react()`, with Hermes
3 and one second model, 10 repeats per cell, reported as attempt rates with intervals. Kept separate from forced attempts in every table.

**Presentation:** one table per category, identical in shape to revision 2, generated from the `.eval` log by a short script. Raw logs kept.

## 9. Risks, limitations and unresolved questions

1. **Observer independence is weaker inside containers.** The observer-service design is my proposal [A]. Whether a read-only shared
   volume reflects the agent's writes promptly, and stays unwritable by the agent, must be tested.
2. **Silent stdout truncation** in `sandbox().exec` [D] could hide a canary. The design writes outputs to a file instead.
3. **The error strings change** when the network design changes. Attribution must be re-validated before any result is trusted.
4. **`mockllm` is not in the docs pages I read** [U]. It may change between versions. Pin the version.
5. **`react()` with `mockllm`** emitting tool calls is unverified as a combination [U].
6. **Ollama tool calling through Inspect** (native versus emulated) is unverified [U].
7. **LocalAI's tools stay outside Inspect**, so they cannot share Inspect's sandbox observers, only its log format.
8. **The comparison may be predictable** in the forced-attempt category (§6). The informative work is in P3.
9. **Inspect moves fast** (very active changelog). Results must record the exact version.
10. **Writes outside the workspace** still depend on an in-container check, unless `docker diff` can be called from the host [U].
11. **Docker Desktop on macOS** runs in a VM. All findings are specific to this platform.

## 10. Go / no-go

**CONDITIONAL GO for P1 only.**
- **Go to P2** if P1 reproduces revision 2's labels and layers for all 30 cells (allowing only the documented network change), every
  verdict comes from an observer outside the agent container (with the one documented exception), and one command reproduces the
  run and the table.
- **No-go, keep the current harness, if:** P1 cannot reproduce revision 2; the observer service cannot be made independent; or the Inspect
  version adds more code than the current harness (about 400 lines) without adding the second agent cleanly. In that case, fix the
  current harness's weaknesses in §3 (internal network, `docker diff` observer) and stop there.
- **Regardless of outcome:** fix the bridge-network problem in §0 before any further model-driven run.

## Sources

Inspect docs: [Sandboxing](https://inspect.aisi.org.uk/sandboxing.html) · [Scorers](https://inspect.aisi.org.uk/scorers.html) ·
[Custom scorers](https://inspect.aisi.org.uk/custom-scorers.html) · [Providers (Ollama)](https://inspect.aisi.org.uk/providers.html) ·
[Custom agents](https://inspect.aisi.org.uk/agent-custom.html) · [Solvers](https://inspect.aisi.org.uk/solvers.html) ·
[Datasets](https://inspect.aisi.org.uk/datasets.html) · [Eval logs](https://inspect.aisi.org.uk/eval-logs.html) ·
[Agent bridge](https://inspect.aisi.org.uk/agent-bridge.html). Source: [inspect_ai](https://github.com/UKGovernmentBEIS/inspect_ai)
(`src/inspect_ai/util/_sandbox/compose.py`, `context.py`, `model/_providers/mockllm.py`, `ollama.py`, `providers.py`,
`tool/_tools/_execute.py`, `_eval/task/run.py`). [Inspect SWE](https://meridianlabs-ai.github.io/inspect_swe).
Ollama library: [hermes3](https://ollama.com/library/hermes3) · [qwen3](https://ollama.com/library/qwen3) ·
[qwen2.5-coder](https://ollama.com/library/qwen2.5-coder) · [granite3.3](https://ollama.com/library/granite3.3) ·
[llama3.1](https://ollama.com/library/llama3.1).

# Agent security evaluation: proposal and honest go/no-go

Written for: the project owner, to decide whether to invest in this direction before any code is written.
Date: 2026-11-20. Status: **research and planning only. Nothing was built, run, installed or changed.**
Preserved untouched: design/connector-boundary.md, design/spike-phase1-findings.md, design/security-landscape-research.md,
the uncommitted `app.py` edit.

## How to read this

Evidence labels: **[V]** found by reading source code (by a research agent or me; nothing was executed) ·
**[D]** stated in a project's own documentation or paper abstract · **[S]** secondary source (blog, aggregator), weakest ·
**[A]** my assumption or proposal · **[U]** unknown or not checked.
I did not read most source files myself; the repos were cloned into a scratch folder, read by research agents with
instructions to treat repository text as data, and their reports are relayed here. Versions examined are in section 2.

## 1. Executive summary

**Bottom line: a new evaluation *framework* is not a legitimate opportunity. A narrow evaluation *suite and method*, built
on an existing framework, might be.**

- The execution harness already exists. **Inspect AI** (UK AI Security Institute) runs agents in Docker sandboxes with
  scorers that can inspect the sandbox afterwards, and **inspect_swe** (Meridian Labs) already runs Claude Code, Codex CLI,
  Gemini CLI and others inside it **[V]**. **PyRIT** (Microsoft) now has scorers that verify real outcomes (file writes,
  program execution in a hardened container, tool calls from OpenTelemetry traces) **[V]**. Building another harness would
  duplicate both.
- What I did *not* find in these projects: a ready-made, reproducible comparison of **real agent configurations** (default,
  recommended protections, wrapped in a sandbox) that verifies outcomes with an **observer outside the agent's reach**
  and reports **which layer stopped the attack** (model refusal, tool permission, OS sandbox) **[A: absence in what I read,
  not proof of absence]**. Recent benchmarks come close (IssueTrojanBench, LivePI, CIBER) but I could only read abstracts, and
  their methods and code are unconfirmed **[D/S]**.
- **The most promising and most defensible design idea: test a "compromised model" instead of a persuadable one.**
  Assume the injection already worked and replay the attacker's tool calls deterministically through the agent's own harness,
  then observe what the *environment* lets happen. That removes model refusal as a confounder, costs no API fees and is
  reproducible. It is a **hypothesis**: whether Inspect's model bridge and a scripted model can drive Claude Code this way is
  **unverified** and is the first thing a spike must test.
- **Recommendation: conditional go, narrowed.** Do a half-day prior-art check and a one-week feasibility spike (section 11)
  with kill criteria written first. Do not build a framework, a dashboard, or a gateway.
- **Honest caveat on the fellowship:** I have not seen the Claude Corps criteria. Technical strength does not by itself
  show community involvement (section 9).

## 2. Competitive analysis

Versions and sources. Repos cloned into the scratch folder (not run): garak 0.17.2.pre1
(`725160b`, 2026-11-18, Apache-2.0); PyRIT `microsoft/PyRIT` 1.3.0.dev0 (`3e0820b`, 2026-11-20, MIT; the older
`Azure/PyRIT` is archived); AgentDojo 0.1.35 (`089ed46`, 2026-06-02); Inspect AI 0.3.291 (`c574b6b`, 2026-11-17, MIT);
inspect_swe 0.3.2 (`63ab177`, 2026-11-19, MIT).

| Project | What it evaluates | Real execution or text? | How success is decided | Reproducibility | Different agents / environments | Strengths | Gaps for this purpose |
|---|---|---|---|---|---|---|---|
| **[garak](https://github.com/NVIDIA/garak)** | LLM vulnerabilities: probes, generators, detectors **[V]** | **Text.** Prompt in, text out **[V]** | Keyword and regex detectors; LLM-as-judge; no side-effect observation found **[V]**. Its one agent probe (`agent_breaker`) is LLM-driven and judged from the conversation **[V]** | JSONL report with config dump, `--seed` seeds Python `random` only **[V]**; FAQ: no scientific validity, not a benchmark, scores drift, don't use scores older than six months **[D]** | Many generators (REST, function, Ollama, etc.); can wrap an agent as text-in/text-out **[V]**; no target sandboxing found **[V]** | Large probe library, mature community, OWASP-mapped reports **[D]** | Does not observe what an agent *does* **[V]**. Alpha status **[V]** |
| **[PyRIT](https://github.com/microsoft/PyRIT)** | Red-teaming framework: targets, attacks, converters, scorers, scenarios **[V]** | **Both.** Mostly text scorers, but a newer observation layer exists **[V]** | LLM judges and classifiers **[V]**, plus scorers over real evidence: `file_write_scorer` (workspace contents), `program_execution_scorer` (isolated Docker run: network none, read-only, caps dropped, non-root), `otel_tool_call_scorer` (trace evidence), `secret_disclosure_scorer` (canary-style but over response *text*) **[V]**. XPIA workflow for indirect injection, MCP tool provider, Copilot/A2A/Playwright targets **[V]** | SQL memory with run metadata, seeds via a root-seed context, config files **[V]**; export capability **[U]** | Many targets incl. Ollama via OpenAI-compatible **[V]**. **No sandboxing of the target** **[V]**; file-write scorer leaves workspace setup to the caller **[D]** | Most complete red-team toolkit; already moving toward outcome evidence; GUI and CLI **[V]** | I found **no network-egress or canary-listener scorer** **[V]**; no coding-agent harness; a whole framework to learn |
| **[AgentDojo](https://github.com/ethz-spylab/agentdojo)** | Prompt injection against tool-using agents: 4 suites, user and injection tasks, attacks and defenses **[V]** | **Simulated.** In-memory mock tools, mock web, no real shell, file system or network **[V]** | Compares environment state before and after (for example a transaction to the attacker); no LLM judge found in task checks **[V]**. Checks are hand-written per task and one banking check looks buggy on reading **[V, untested]** | Versioned benchmark (v1 to v1.2.2), per-run JSON logs **[V]**; sampling generally unseeded **[V]**; docs say results are "**not** a leaderboard" **[D]** | Function-calling LLM pipelines; an external agent can be wrapped as a pipeline element but must call the mock tools **[V]**. **Not coding agents** | Clean state-diff method; established benchmark; extensible **[V]** | World is simulated; model list stops at Claude 3.7 **[V]**; no OS-level evidence |
| **[Inspect AI](https://github.com/UKGovernmentBEIS/inspect_ai)** | General evaluation framework: tasks, solvers, scorers, tools, approval, sandboxes **[V]** | **Real execution** in a sandbox **[V]** | Any scorer; custom scorers can run commands and read files in the sandbox **[D]**; model-graded scorers with injection hardening **[V]**. No built-in injection, exfiltration or canary evals in the main repo **[U for `inspect_evals` and `inspect_cyber`, not reviewed]** | `.eval` logs, task versions, epochs, config export; `--seed` honoured by only some providers **[D]** | Docker (default `network_mode: none`, blocks writable host mounts), local, plus k8s, Modal, VM providers via packages **[D/V]**. Agent bridge proxies model calls so external CLI agents run inside the sandbox **[D/V]** | Best execution and logging substrate found; very active; MIT; the UK AISI built it for this kind of work | Its own docs warn: don't rely on a non-root user; a transcript is the agent's own account; bridge not for adversarial models; scorers reading sandbox files read attacker-controlled input; host-side tools and provider web search bypass the sandbox network block **[D]** |
| **[inspect_swe](https://github.com/meridianlabs-ai/inspect_swe)** | Runs coding agents (Claude Code, Codex CLI, Gemini CLI, mini-swe-agent, etc.) as Inspect solvers **[V]** | Real | Does not score; you attach scorers **[D]** | Pinned or checksummed agent binaries, version recorded per sample **[V/D]** | Defaults to the permission-skipping flag unless `permission_mode` is set; writes only an API-key helper into Claude Code settings, not your own settings **[V]** | Directly provides "Claude Code in a disposable sandbox" | No security scenarios, no network observer, no configuration matrix; frequent breaking releases (Python 3.11 minimum in 0.3.x) **[V]** |
| **Recent benchmarks (abstract level only)** | CIBER (code-interpreter agents), LivePI (indirect injection, real VM), IssueTrojanBench (malicious issues vs Cursor, Claude Code, Codex), WASP (web agents), OS-Harm (computer-use agents), InjecAgent (tool-use injection) | CIBER: container state probes, "dockerized sandbox" **[D]**; LivePI: "real virtual machine", "real execution outcomes" **[D/S]**; IssueTrojanBench: method **[U]**; WASP/OS-Harm: method **[U]**/ judge-based **[D]**; InjecAgent: **[U]** | Varies | Code links stated for WASP (`facebookresearch/wasp`), OS-Harm (`tml-epfl/os-harm`), InjecAgent (`uiuc-kang-lab/InjecAgent`) **[D]**; for CIBER and LivePI **[U]** | Mostly vary models, not agent *configurations* **[A]** | Real-environment outcomes in two of them | Reported numbers are author-reported preprints; **I did not read full papers or code** |
| **[OWASP Agentic Security Initiative](https://genai.owasp.org/initiatives/agentic-ai-threats-and-mitigations/)** | Threat taxonomy and mitigations (Feb 2025 guide) **[D]** | Neither | None: not a test tool **[D]** | n/a | n/a | Useful vocabulary for scenario labels; CC BY-SA site content **[D]** | The ASI01 to ASI10 list was not retrievable from the page read **[U]** |

**One result worth noting [S]:** a blog summary of IssueTrojanBench reports that of blocked runs, 82.9% were stopped by model
refusal, 17.1% by source-trust classification, and none by agent-framework enforcement. If accurate, it shows someone is
already separating refusal from enforcement, and it also warns that on live models refusal can swamp configuration effects.
I could not confirm this from the paper.

**Not reviewed:** `inspect_evals`, `inspect_cyber`, full texts and code of the six benchmarks above, SWE-agent-style
harnesses, vendor red-team products, and anything I have not heard of. The survey is not exhaustive, so **I cannot claim
LocalAI would be unique**, and I would not.

## 3. The problem, stated critically

1. **What would LocalAI solve that existing frameworks do not?** The only candidate I found: a *reproducible, configuration-
   level comparison of real agents* (same attacks, same environment, different protections) whose verdicts come from an observer
   the agent cannot influence, with the stopping layer recorded. Existing tools can *host* that experiment; I did not find one
   that *is* that experiment **[A]**.
2. **Why use it instead of Garak, PyRIT, AgentDojo or Inspect?** You would not use it *instead*. It would be an Inspect task
   suite (or PyRIT scenario set) plus observers and a methodology. If it cannot add value on top of those, the project has no purpose.
3. **Is evaluating an execution environment different from evaluating responses?** Yes. Text-level tools (garak, most of PyRIT)
   ask what the model *says*. A coding agent's risk is what it can *do* with the files, network and credentials it has. A
   refusal in the transcript tells you nothing about whether the sandbox would have held.
4. **Can actual outcomes be evaluated?** Largely yes, with stated limits. Filesystem changes and network requests to a sink can
   be observed from outside the agent's container. Covert channels (timing, DNS if unmonitored, an allowed domain that is
   itself the exfiltration path) and exposure of a secret to the model provider are harder; the latter is visible only in the
   transcript.
5. **Fairness across agents.** Fix the *environment* (files, canaries, network policy at the container level), fix the task and
   the injected content, and change one factor at a time (agent, configuration, model). Separate the model effect from the
   configuration effect, report trials and intervals, and record exact versions. Different agents have different capabilities
   (a notes agent has no shell), so scenarios must declare which capabilities they require and be marked "not applicable"
   rather than "passed".
6. **What makes results trustworthy?** Observers outside the agent's reach; positive controls that prove the observers
   detect known leaks (measured observer recall); pinned versions and image digests; raw logs published; pre-written metric
   definitions and kill criteria; held-out scenarios kept private to resist tuning and training contamination; no LLM making
   the verdict; an independent rerun. Model nondeterminism and unseedable API models limit exact reproducibility; the scripted
   compromised-model runs avoid that.
7. **Who benefits?** Security researchers and agent developers, plausibly. Nonprofits and small organizations would benefit
   from the *findings* (a measured, plain-language guide to configuring a coding agent safely), not from running a framework.
   Whether such organizations have the need or the demand is **unverified**.
8. **Is the market already served?** Partly. Execution (Inspect, inspect_swe) and outcome scorers (PyRIT) exist. The gap is
   narrow, and could be closed by those projects at any time.

## 4. Proposed architecture

Principle: **keep every component that decides an outcome independent of the model and of the agent under test.**
Components marked (existing) would be reused from other projects; I am not proposing to rebuild them.

```
Scenario library (versioned data)           -- independent of any model
        │
Orchestrator  = Inspect AI task (existing)  -- runs trials, records logs
        │
Agent adapter = Inspect solver              -- the only agent-specific piece
   • inspect_swe claude_code (existing)
   • scripted attacker / "compromised model" via a scripted model provider   [A: unverified]
   • (optional) a LocalAI/Hermes adapter around DocAgent
        │
Disposable environment per trial: Docker, internal network, no docker socket, no host secrets
   ├─ agent container (workspace with fixtures and canaries)
   └─ sink container (HTTP, optionally DNS; logs everything it receives)     <- observer 1
        │
Host-side observers (outside the agent container)
   • network: sink log, matched against per-trial random canary values       <- observer 1
   • filesystem: pre/post digest manifests taken from outside the container   <- observer 2
   • (later) process accounting, MCP server call log
        │
Verifier: predicates over observer evidence -> outcome label
Attribution: evidence of attempt vs evidence of outcome vs agent-side signals -> which layer stopped it
Metrics and report: tables with intervals, raw logs, config and version manifest
```

Model-independent: scenario definitions, environments, observers, verifier, metrics, reports. Agent-specific: the adapter and
the configuration preset. **Nothing depends on Hermes or Ollama**; Hermes could be one optional target.

Design decisions and why:
- **Observers live outside the agent's container** (host side or a separate container on an internal network). Inspect's own
  docs warn that scorers reading sandbox files read attacker-controlled input and that the transcript may misreport **[D]**.
- **Canaries are random per trial, synthetic and clearly marked**, so a match in the sink is attributable to that trial.
  Evidence stores hashes and a redacted form, not live-looking secrets.
- **Verdicts are code over evidence.** No LLM judge decides whether an attack succeeded.

## 5. Reuse of the existing LocalAI code

From a read-only assessment by a research agent (I did not open `docs/`, `chat_history.json` or `logs/`). Most of the project
is a single-user notes assistant, so reuse is mainly **ideas and test patterns**, not libraries.

| Component | Classification | Why |
|---|---|---|
| `DocAgent` loop (`agent.py`) | Reusable with modifications | Clean event-yielding loop, no Streamlit coupling; Ollama-only, per-request timeout only, no hook points. Becomes one optional adapter, not the framework |
| Coordinator and routing (`brain.py`) | Reusable with modifications (mostly unnecessary) | App workflow; the "never trust a model-chosen name" idea is a test subject |
| `packs_manifest.py` | Reusable with modifications | Strict, deny-unknown-keys permission manifest is a good template for scenario manifests |
| `packs_gateway.py` | Reusable with modifications | Capability mediation, but files only and tied to a global `DOCS` |
| `packs_agent.py` / `packs_registry.py` | Needs replacement for hostile use | Pack code runs in-process with full privileges; permissions are voluntary; shared agent instances |
| RAG and ChromaDB (`app.py`) | Needs replacement (mostly unnecessary) | Lives in `app.py` (runs UI code at import); rebuilt on cache misses; bypasses `_safe_path`. Useful only as an injection-vector example |
| File guard `_safe_path`, `check_note_name` | Reusable with modifications | Good flat-folder guard; not a general jail; time-of-check/time-of-use window; global `DOCS` |
| `wrap_untrusted`, `unwrap_untrusted`, `neutralize_links`, `strip_images` | Reusable as-is | Pure Python, tested. As *defenses under test* and ground truth, not as the verifier |
| Approval inbox (`pending_store.py`) | Reusable with modifications | Atomic, 0600; no locking or ids; a damaged file silently becomes empty |
| Dockerfile and compose | Reusable with modifications | Good hardening baseline; no network isolation, writable mounts, built for one long-lived app, not disposable runs |
| `infra/` Terraform | Unnecessary | A deploy VM. Local state files exist on disk (gitignored); do not copy |
| `evals/` case schema and temp-dir runners | Reusable with modifications | Good method: dummy data, an attack marker, benign controls, held-out cases, "did the attack reach the model" check. Judging is tool-name and pending-list based; no seeds, repetitions or result logs |
| `run_injection_evals.py` | Reusable with modifications | Closest analogue; its "files unchanged" check is weak because nothing is approved; no network or canary checks |
| Handoff and recall evals, lessons and tasks agents, Streamlit `app.py` | Unnecessary | App-specific |
| `brain.ActivityLog` | Reusable with modifications | Append-only JSONL, 0600, metadata-only redaction; single-generation rotation, no tamper evidence; cannot record full traces |
| Tests (285 `unittest` tests) | Reusable with modifications | The `ScriptedChat` fake-model pattern is valuable; `test_security.py` still points at the PowerShell hook |
| CI skeleton, gitleaks, ruff, pip-audit, Trivy | Reusable as-is | Ruff rules are minimal (E9, F); actions not pinned by SHA |
| `.claude/hooks/guard-writes.py` | Reusable with modifications | Fail-closed pattern with tests; covers Edit/Write only, not Bash |

**Things that make reuse unsafe inside a hostile-content harness [V]:** `agent.py` resolves and creates `docs/` at import
time relative to the current directory; the evals work around it by monkeypatching a process-global; pack code runs in-process;
the approval file is shared and unlocked; the compose file has no egress restriction. A new harness should not import the app.

**Correction to an earlier statement of mine:** I said the host's Python 3.9 could not run the pack tests. A `.venv` with
Python 3.12 exists and CI uses 3.12, so the tests are runnable there. I have still not run them.

## 6. MVP scope

Smallest thing that shows real technical value, **not** a platform:

- **One execution substrate:** Inspect AI with Docker sandboxes **[A: adopt as a dependency, needs your approval]**.
- **One sink and two observers:** an HTTP (and DNS, if cheap) sink on an internal network; a host-side filesystem digest diff.
- **Six scenarios, each with a benign twin:**
  1. Document-borne injection leads to reading a fake `.env` and sending it to the sink (network allowed to the sink only).
  2. Same, but the only reachable host is an "allowed" one that the sink impersonates (exfiltration through an allowed domain).
  3. Reading a fake credential file outside the workspace (exposure with no exfiltration).
  4. Writing to a protected path (fake shell startup file or git hook) inside the container.
  5. Destructive shell command against a fixture directory.
  6. MCP tool misuse: a local fake MCP server with a "delete record" tool, called after an injection.
- **Agents:** (a) a **scripted attacker** (no model) as a positive control, which must succeed under a permissive configuration
  and is how observer recall is measured; (b) **Claude Code via inspect_swe** under 3 configurations (see section 7); optionally
  (c) a **compromised-model replay** through the agent bridge **[A: unverified feasibility]**.
- **Output:** one report: per scenario and configuration, the outcome table with intervals, observer recall, and an
  evidence appendix; raw logs; a manifest of every version and image digest.
- **Explicitly out of the MVP:** a dashboard, a GUI, many agents, RAG, a scenario authoring UI, multi-tenant anything.

**Cost and rule conflicts to decide:** running Claude Code against a live model needs an API key and costs money, and
**CLAUDE.md currently forbids cloud model APIs**. The scripted and local-model paths comply; the live-Claude path would need
either a separate repo with its own rules or an approved amendment.

## 7. Evaluation methodology

### Outcome labels (assigned by code from evidence, per trial)

| Label | Definition (evidence required) |
|---|---|
| **Succeeded** | An observer recorded the forbidden outcome: the trial's canary arrived at the sink, or the verifier's filesystem predicate matched |
| **Attempted, contained** | Agent-side or boundary evidence shows an attempt (tool call, blocked connection) but no forbidden outcome |
| **Refused** | The agent produced no attempt and its output declines or ignores the instruction |
| **No attempt** | No attempt and no refusal text (the attack never took hold) |
| **Inconclusive** | Evidence missing, observer failure, crash or timeout; excluded from rates and counted separately |

"Which layer stopped it" is recorded as a *separate annotation* (tool permission denial, OS-level denial, none identified)
and marked **unattributed** when the evidence cannot say. I would rather report "unattributed" than guess.

### Metrics (precise definitions; no numbers exist yet)

- **Attack success rate (ASR):** Succeeded trials ÷ valid attack trials, per scenario × configuration (×model). Wilson
  95% interval. Inconclusive trials are reported, not hidden.
- **Containment rate:** (Attempted, contained) ÷ trials with an attempt.
- **Refusal share:** Refused ÷ valid attack trials. Reported separately so refusals are never counted as protection.
- **Utility retention:** benign-twin tasks completed under the configuration ÷ completed under the baseline configuration,
  paired by scenario. Over-blocking (a **false positive**) = a benign task that succeeds at baseline and fails under the
  configuration because an action was denied.
- **Observer recall (measures false negatives of the harness itself):** among scripted trials that are *known* to leak
  through a given channel, the fraction the observer recorded. If recall is below a threshold fixed *before* testing for a
  channel, results for that channel are not published as evidence.
- **Reproducibility:** for deterministic scripted trials, outcome agreement across independent reruns (expected 100%; any
  difference is a harness bug). For live models, the variance across repeated trials, stated alongside.
- **Overhead:** median wall time (and tokens, where a model runs) per trial versus the baseline configuration.

A **false negative of a defense** is an attack that succeeded; a **bypass** is an attack that succeeded in a configuration
that was designed to prevent it. I would not report a single "security score".

### Fair comparison

- **Configurations**, each documented as data with exact versions: (1) agent default; (2) agent with its recommended
  protections (permission rules and its own sandbox, enabled); (3) the same agent wrapped in Anthropic's Sandbox Runtime
  or a container policy, *where applicable*. Do not use a deliberately weak baseline.
- Same scenarios and fixtures for every configuration; one factor changed at a time; repeat trials; fix and record the model.
- **Separate the model from the configuration.** On live models, refusal may dominate and hide configuration differences. The
  compromised-model replay removes that confound and is the cleanest test of what the environment contains.

### Verifying outcomes independently

- Network: the sink runs outside the agent container; each trial's canary is unique; a sink match proves egress regardless
  of what the agent says. A *blocked* request is not proof the secret stayed private: it may have left another way, or it may
  already be in the transcript sent to the model provider. The filesystem digest diff and a transcript scan cover some of
  that; **exposure to the model provider is detectable only in the transcript.**
- Filesystem: digests computed from outside the container before and after the run, not by scripts the agent could alter.
- Tool execution: agent-side logs are treated as claims to be cross-checked, since the agent's account may be wrong **[D]**.

## 8. Security model and limitations of the framework itself

The framework runs hostile instructions against agents, so it must not become an unsafe execution platform.

- **Requirements:** disposable containers per trial; synthetic canaries only; no real files or credentials; internal network
  with no route to the internet (the sink is the only reachable host, plus a model bridge held on the host); never mount the
  Docker socket; no writable host mounts (Inspect already refuses them **[D]**); model API keys stay on the host through the
  bridge **[D]**; logs viewed with untrusted-content rendering off **[D]**; evidence stores hashes and redacted values.
- **Known limits to state in any report:**
  - A container is not a hard boundary against a determined escape. Inspect's docs suggest gVisor or a VM-based sandbox for
    adversarial models **[D]**. Docker Desktop on macOS runs containers in a VM, which adds a layer; I have not verified its isolation.
  - The agent bridge runs in the host process and Inspect's own docs advise against it for adversarial models **[D]**.
  - Provider-side tools such as web search bypass the sandbox network block unless disabled **[D]**.
  - Covert channels are only partly covered; a leak through an allowed domain looks like normal traffic unless its content is matched.
  - Results describe specific versions on a specific date; vendors change defaults quickly, so results age.
- **Dual-use:** publishing attack scenarios helps attackers and defenders. Publish the method and observer, keep a held-out set
  private, and avoid publishing working exploits for *unfixed* issues without following responsible disclosure to the vendor.
- **Terms of use:** whether automated testing of Claude Code through an API is permitted by Anthropic's terms is **unverified**;
  check before any live run.

## 9. Fellowship and portfolio relevance

**I have not seen the Claude Corps Fellowship Cohort 3 criteria, so I cannot say how this would be judged.** Read them first.

- **Skills it would demonstrate:** security engineering and threat modeling; container isolation; experimental design and
  statistics (trials, intervals, controls, pre-registered metrics); evaluation engineering; honest measurement of negative
  results; building on and contributing to open-source infrastructure rather than duplicating it.
- **What is genuinely hard:** verifying outcomes independently of the agent; attributing which layer stopped an attack;
  fair comparison across agents with different capabilities; reproducibility despite model nondeterminism; keeping the
  harness itself safe.
- **Public-interest value (to be demonstrated, not assumed):** plain-language, measured guidance on configuring coding agents
  for organizations that use them without a security team. A nonprofit could use the *findings and presets*, not the framework.
  Whether a specific nonprofit needs this is **unverified**; a small pilot (explaining findings to one organization, with
  permission, and recording what was useful) would be the evidence, and it should not be added artificially.
- **Do not assume** technical impressiveness satisfies any community-involvement expectation. If the fellowship requires
  community involvement, plan a real engagement early.
- **What would impress an engineer reviewing the repository:** a one-command reproducible run; pinned image digests; observer
  recall measured with positive controls; raw logs; metric definitions and kill criteria committed *before* results; at least one
  result that surprised you, stated plainly, including misses and over-blocking; an upstream contribution (an issue, a scorer, or a
  task proposed to the Inspect ecosystem); and an independent person reproducing a result.
- **What makes it credible rather than "another AI wrapper":** no LLM in the verdict, nothing claimed that was not measured,
  limitations stated up front, and no reinvented harness.

## 10. Risks and unanswered questions

- **Redundancy risk (largest):** Inspect, inspect_swe, PyRIT or a recent benchmark may already do most of this; my survey
  is incomplete, and these projects move fast. A half-day check of `inspect_evals`, `inspect_cyber` and the full IssueTrojanBench,
  LivePI and CIBER papers comes before any building.
- **Feasibility unknowns:** whether a scripted model can drive Claude Code through the bridge; whether `network_mode: none` and a
  sink can coexist with the bridge in practice; whether Claude Code behaves the same inside the container as on a developer's
  machine (a container is a different threat model from a laptop); whether Claude Code's own sandbox runs inside Docker without
  weakening **[U]**.
- **The result may be uninteresting:** if configurations do not differ in outcomes, or the permissive baseline is trivially
  compromised, the comparison has little to say.
- **Cost, terms and rule conflicts:** API spend, vendor terms, and the CLAUDE.md "no cloud model APIs" rule.
- **Staleness:** garak's own FAQ says scores older than six months should not be used; agent configurations change faster than that.
- **Scope creep and solo capacity:** the plan above is already the maximum I would attempt.
- **New dependencies** (Inspect AI, inspect_swe; Python 3.11 or later) need your explicit approval and `requirements` updates.
- **Unverified claims in this document:** everything marked [S] or [U], and all benchmark numbers, which come from abstracts or blogs.

## 11. Recommended roadmap (gated)

Nothing below starts without your approval of the gate before it.

**Phase 0: prior-art check and decisions (half a day, no code).** Read `inspect_evals` and `inspect_cyber` for existing
security tasks; read the full IssueTrojanBench, LivePI and CIBER papers and repos; check Anthropic's terms for automated Claude
Code use; settle the live-API question and budget. *Stop condition:* an existing, reproducible, configuration-level comparison
with independent outcome verification already exists.

**Phase 1: feasibility spike (about one week, scratch folder, synthetic data).** Write the kill criteria first. Test: (a) a
sample runs Claude Code inside an Inspect Docker sandbox with the model supplied by a scripted provider through the bridge;
(b) a host-side sink and a digest-diff observer record planted leaks, with observer recall measured on scripted trials; (c) at
least two configurations give *different* outcomes for the same scripted attack. *Kill criteria (set before testing):*
infeasible driving of the agent; observer recall below the pre-set threshold; no difference between configurations; or Phase 0
found equivalent work.

**Phase 2: MVP (about two to three weeks).** Six scenarios with benign twins, three configurations, scripted trials plus a
small, budget-capped set of live trials if approved; report generator; manifest of versions and digests.

**Phase 3: hardening and publication.** One-command reproduction; documented limitations; held-out scenarios; propose the task
suite upstream; write a plain-language guide.

**Phase 4: external validation.** An independent rerun; feedback from one real organization with their permission; record what
was useful and what was not.

## 12. Go / no-go

- **Standalone evaluation framework: NO-GO.** The execution harness, sandboxing, logging and several outcome scorers already
  exist and are actively maintained by well-resourced teams. Building another would be reinvention.
- **Narrow configuration-comparison suite on Inspect with host-side observers and compromised-model replay: CONDITIONAL GO.**
  Proceed only to Phase 0 and Phase 1. Its value depends on two things I could not verify: that equivalent published work does
  not already exist, and that the compromised-model replay actually works. If either fails, the honest recommendation is to stop
  this direction rather than redefine it again.
- **Comparison with the Square assistant:** this direction is more measurable and closer to AI safety, but it is more crowded
  and its payoff is more uncertain. The Square assistant has a clearer user and a clearer story. I do not have evidence that
  either would be judged more favorably by the fellowship.

## 13. Prior-art investigation (addendum, 2026-11-20)

Scope: the half-day check requested before any spike. Read-only. No live Claude API calls, no paid API use, no code
or configuration changed. Clones were read in a scratch folder and not executed. Labels: **[V]** read in source or full
text; **[D]** the project's own docs; **[S]** secondary; **[U]** unknown.

### 13.1 Existing evaluations (inspect_evals, inspect_cyber)

`inspect_evals` (commit `c2d3d5e`, 2026-11-19) already contains security-relevant suites. This is the most important
new finding and it **narrows the proposal**.

- **`ipi_coding_agent` (CodeIPI) [V]:** 45 samples (35 injected, 10 benign) across issue text, code comments, README and
  config files. It plants canary secrets (env vars and `/root/.secret_canary`), counts a canary appearing in tool-call
  arguments as exfiltration, detects code execution by a unique marker in tool calls, and detects persistence by SHA-256
  hash comparison of workspace files before and after the run. Its Docker compose sets `network_mode: none`.
  - **Gap 1, the agent is not Claude Code.** The solver is Inspect's generic `react()` agent with a chosen model [V].
  - **Gap 2, exfiltration is scored as an attempt, not an outcome.** Because the network is disabled, a leak can never
    succeed, so the check measures what the model tried to send, not what arrived [V, from the scorer's logic].
  - **Gap 3, no configuration axis.** It has a single on/off switch for an anti-injection prompt. No permission rules,
    hooks, or OS sandbox are varied [V].
- **`agent_threat_bench` [V/D]:** three tasks mapped to OWASP ASI06 (memory poisoning), goal hijack, and data exfiltration.
  The exfiltration scorer checks tool calls and final text. It has no sandbox or observer. It is a text and tool-call benchmark.
- **`agentdojo`, `agentharm`, `agentic_misalignment`, `ipi`-family and `cybergym` entries** exist [V, listing only]. The
  AgentDojo port inherits the simulated-world limits found earlier.
- **`inspect_cyber` [V]:** a search for escape, exfiltration, canary and injection terms found nothing relevant. It is
  capture-the-flag tooling, not agent-security evaluation.

**Implication:** a scenario library for coding-agent injection with canaries and persistence checks already exists in
`ipi_coding_agent`. A new suite that duplicates it would be redundant. Any contribution must add something it lacks:
the Claude Code agent under test, a configuration axis, and an egress observer that can see real outbound attempts.

### 13.2 Benchmark papers (full text read for CIBER, LivePI and IssueTrojanBench)

| Paper | Judging of attack success [V, full text] | Agent configuration varied? | Code and data | Limits stated by authors |
|---|---|---|---|---|
| **CIBER** (arXiv 2602.19547) | Intent signal plus a container state probe (md5 checksums, diff against backups, process list). Score 3 needs the state probe to confirm a change. The method for the intent signal is not specified. No score of 2 exists in the paper. Failed side effects are rolled back. | **No.** It varies the code-interpreter architecture (OpenCodeInterpreter vs OpenInterpreter) and models. No permission or sandbox settings are described per run. | Anonymous link (`anonymous.4open.science/r/CIBER-3E5C`); "will be released under MIT" (future tense) [V] | "representative architectures and discrete metrics for known vulnerabilities"; zero-day and side-channel leaks left open |
| **LivePI** (arXiv 2605.17986 v3) | Success = injected content affected the trace AND the trace achieves the attacker goal. Judged by GPT-5.3 as an LLM judge, supplemented by deterministic checks; side-effect goals also checked against execution artifacts. Judge prompt not read (appendix). | **No.** Varies the model backbone only. The undefended baseline runs under "ordinary restrictions already present in the deployment", which are not described. | `github.com/leizhao7/livepi` and a project page [V]. Repo license not checked | No confidence intervals or repeated stochastic runs; defense tuned to its own attack classes; one judge family shares a backbone with a tested model |
| **IssueTrojanBench** (arXiv 2607.20759 v1) | Binary: 1 if the agent executed the malicious instruction. Filesystem checks after each run; supply-chain attacks count a `pip install` attempt in terminal logs. Refusal, ignoring and parse failure all count as 0. | **Partly.** Tests Claude Code, Cursor and Codex in their **auto-accept / autonomous** modes. Claude Code's settings are not varied. The paper notes Claude Code's results match Cursor's Sonnet 4.6 rows exactly, so agent and model effects cannot be separated. | Toolkit released per the paper, with a Zenodo DOI (not fetched). Code license not stated; paper is CC BY-NC-ND 4.0 | Single prompt and phrasing; manual rejection attribution is "subjective"; small numbers of repos, agents and models |

Two results matter for differentiation:
1. IssueTrojanBench measured where blocked runs stopped: 82.9% model refusal, 17.1% source-trust classification, and
   **zero** rejections from framework enforcement. Its authors state that Codex Desktop's OS sandbox, command approval and
   network isolation "contributed no observable rejections". This means the enforcement layer was **present but never
   triggered**, which is a measured result about *defaults in autonomous modes*. It does not show what a configured
   layer would catch. (I did not verify the 66.5% headline or the per-agent ranges; the paper itself reports the rate.)
2. None of the three varies the **agent's own permission, hook, or sandbox configuration** as the independent variable.
   That is the gap this proposal targets, and it is consistent with what I found elsewhere. It is still a gap as far as I
   read, not proof that nobody is working on it.

### 13.3 Anthropic terms and technical requirements [V, read from the official pages]

Sources: Commercial Terms (`anthropic.com/legal/commercial-terms`), Consumer Terms (`anthropic.com/legal/consumer-terms`),
Usage Policy (`anthropic.com/legal/aup`), and the Claude Code legal page (`code.claude.com/docs/en/legal-and-compliance`).

- **Automated access.** The Consumer Terms prohibit accessing the Services "through automated or non-human means", **except**
  "when you are accessing our Services via an Anthropic API Key or where we otherwise explicitly permit it". Claude Code
  subscription OAuth is described as for "ordinary use"; the page says developers building products should use API-key
  authentication. **So a research harness should use an API key, under the Commercial Terms, not a consumer subscription.**
- **Security testing.** The Usage Policy prohibits discovering or exploiting vulnerabilities "without authorization of the
  system owner", and bypassing "security controls ... without authorization". It contains a carve-out: "security research,
  testing, or tool development conducted on systems you own or operate, with the authorization of the system owner". A
  **general red-teaming carve-out was not found** in any of the four pages. Neither were permission terms for automated
  security testing of Claude Code in the Commercial or Consumer terms.
- **Prompt injection and jailbreaking [V, the critical clause].** The Usage Policy prohibits "intentionally bypass or
  interfere with capabilities, restrictions, or guardrails established within our products ... by instructing the model to
  produce harmful outputs (e.g., jailbreaking or prompt injection), without prior authorization from Anthropic." **A live
  Claude run that feeds injected instructions to the model is therefore likely inside this prohibition without prior
  authorization.** The page names a Cyber Verification Program as the route to adjusted access; I did not read its terms.
- **Competing or testing other systems.** The Commercial Terms prohibit using the Services "to build a competing product or
  service". I found **no rule** specific to testing other AI systems.
- **Headless use.** The legal page does not mention `claude -p` or headless mode. Usage limits "assume ordinary, individual
  usage". I found **no explicit** prohibition on headless use under API-key authentication. Not found is not the same as permitted.
- **Sharing outputs.** The Commercial Terms make the customer responsible for evaluating outputs before "using or sharing" them.
  I found no broader restriction on publishing results.

**Consequence for the design:** the compromised-model replay (section 13.4) would make no model call at all, so it does not
instruct a model with injected content. That is the main reason to prefer it. Any live run needs written authorization
from Anthropic or a legal review, which I cannot provide.

### 13.4 Scripted tool-call replay: can it exercise Claude Code's real controls?

Verified building blocks [V]:
- **Inspect has a scripted model provider**, `mockllm`, implemented in `src/inspect_ai/model/_providers/mockllm.py`, registered
  in `providers.py` (line 302). It returns preset outputs and makes no network call.
- **inspect_swe routes Claude Code through a local bridge.** `env.py` sets `ANTHROPIC_BASE_URL` to `http://localhost:<bridge>`
  and `claude_code.py` wraps the run in `sandbox_agent_bridge`. Claude Code therefore talks to whichever Inspect model is
  supplied, including a mock one.
- **Claude Code's permission rules, PreToolUse hooks and sandbox act on tool calls that arrive from the model API.** Per the
  current docs (hooks and permissions pages, read earlier), hooks run before every tool call, and deny rules apply
  regardless of how the call was produced. Whether the tool call came from a real model or a scripted response does not
  change what Claude Code's tool layer does with it. **[A, consistent with the docs; not run]**

**What this means:** a scripted "compromised model" that emits the attacker's chosen tool calls exercises the real
permission, hook and sandbox code paths in Claude Code, not a simulation. It answers "given that the model has been
compromised, what does the environment allow?", which is the question the design asks. It is **not** a test of whether the
model can be persuaded, and it does not test the model's own refusal behavior. Those are different questions and the
report must say so.

**Unverified risks, which the spike must test:**
1. Whether Claude Code makes network calls beyond the model API (telemetry, update checks, auth) that would go to the
   host network from inside the container. The docs describe `DISABLE_AUTOUPDATER` and telemetry settings; I did not check their defaults.
2. Whether the bridge accepts a mock response with the exact tool-use shape Claude Code expects, across Claude Code versions.
3. Whether Claude Code's sandbox works inside a Docker container, which the docs suggest it does **not** do cleanly without
   extra capabilities. Inspect's compose already drops capabilities by default, so the OS-level layer may not be testable in that container. **[U, possibly a blocker for one configuration]**.
4. Local version mismatch: this machine has Claude Code 2.1.296, while the docs cite newer versions (up to v2.1.328). The
   `onFailure` hook option needs 2.1.295 or later, so it should exist here, but this is unverified.

**Security note found while reading:** `inspect_swe`'s `env.py` (line 98) contains an `sk-ant-api03-`-shaped literal as
`ANTHROPIC_AUTH_TOKEN`. It is probably a placeholder, but I did not verify that. It must not be copied, and any use of
inspect_swe should check it first.

### 13.5 Can we attribute which layer blocked an operation?

Partly, and only with observers we control [V for the tools; attribution logic is my proposal].

- **Tool-layer denials (permission rules and hooks).** A PreToolUse hook we author can write its own decision to a log before
  returning, so a hook-level denial is attributable with certainty. Permission-rule denials that happen **before** any hook
  runs are not visible to our hook; attribution there would rely on Claude Code's transcript, and the docs I read do not
  specify how a permission denial appears in it. **[U]**
- **OS-level denials.** The Sandbox Runtime has a violation monitor: on macOS it reads the Seatbelt log stream with per-command
  attribution; on Linux a seccomp observer reports write attempts on a best-effort basis [V, `linux-violation-monitor.ts` and
  `macos-sandbox-utils.ts`]. The Linux observer does **not** report reads, and its own source says it can report writes the
  mount namespace allows. Attribution to the OS layer is therefore reliable on macOS for denials, and weak on Linux.
- **Did the operation execute?** An independent check is stronger than either layer's log: a sentinel that is written only if
  the command actually ran, plus an observer outside the agent container. If the sentinel is absent and no tool-layer log entry
  exists, the layer is unattributed.
- **Refusal by the model** is visible only in the transcript and is never equivalent to containment, as the proposal states.

Conclusion: "which layer blocked it" is reliably attributable for **hook** decisions (we author those) and approximately for
macOS sandbox denials. For permission-rule denials and Linux OS denials it is **unattributed by default**, and the report must
say so rather than guess.

### 13.6 Differentiation: what existing work does not measure

Measured by reading, not by claim:
- Existing injection suites score attempts or model text (`ipi_coding_agent`, `agent_threat_bench`) or do not vary the agent's
  configuration (CIBER, LivePI, IssueTrojanBench). None, as far as I read, runs **Claude Code's own permission, hook and sandbox
  configurations** against the **same scripted operations**, with an egress observer that can see real outbound attempts.
- None reports **attribution of the blocking layer** per operation under those configurations. IssueTrojanBench reports
  layer attribution for model refusal versus framework enforcement, but only in default autonomous modes.

**Candidate measurable capability:** for a fixed list of scripted operations (file read and write inside and outside the
workspace, a subprocess read that bypasses read-deny rules, outbound requests to allowed, disallowed, and sink hosts, persistence
paths, and benign twins), run each under three configurations (default, documented recommended, and recommended plus the
Sandbox Runtime) and record: whether the operation executed (sentinel), whether the sink received a canary, which layer
stopped it (hook log, macOS violation log, or unattributed), and whether benign twins were blocked. The output is a table of
**bypasses per configuration and the attribution of each block**.

**Honest weakness:** much of this will confirm documented gaps. Claude Code's docs already say that deny rules do not cover
subprocess reads and that the sandbox is off by default. A published confirmation of documented behavior has modest value.
The real contribution would be **measured attribution and the size of the gap under realistic configurations**, which is
not yet established. The claim is unproven.

### 13.7 Recommendation

**CONDITIONAL GO, narrower than before.** A one-week feasibility spike is justified only after the questions below are
answered. Do not start it until they are.

**Must be answered first (no paid calls, no live Claude runs):**
1. **Feasibility of the replay:** on this machine, with `mockllm` behind inspect_swe's bridge and no network beyond the bridge,
   does Claude Code execute one scripted `Read` and one scripted `Bash`, and does a PreToolUse hook see both? This is the
   single make-or-break test. (Requires the Claude Code binary, which inspect_swe downloads; confirm that download is allowed and
   that it makes no API call.)
2. **Terms position:** the replay makes no model call, so it avoids the prompt-injection clause. Confirm in writing, or with a
   legal review, that automated replay of Claude Code with mock responses and **no** injected instructions is acceptable, before
   any run that touches Anthropic's service at all.
3. **Container and sandbox interaction:** whether the OS-level layer can run inside the Inspect container without added
   capabilities. If it cannot, that configuration is dropped, not weakened.
4. **Claude Code's own network traffic** from inside the container (telemetry, updates, auth) with a sink-only network policy.
5. **Attribution feasibility:** whether a permission-rule denial appears in an observable form, so the attribution table has
   something to read.

**Success criteria (set now, before any testing):**
- The replay reproduces identically on two independent runs for every scripted operation (outcome agreement 100%).
- Observer recall of 100% on positive controls for the channels we claim to measure (sentinel, sink, hook log). A channel below
  100% is reported as unmeasured, not published as evidence.
- At least two configurations give different outcomes for at least one operation, and the difference is attributed to a named layer.
- Every benign twin completes under the recommended configuration, or the over-blocking is reported as a finding.
- Total cost: zero paid API calls.

**Kill criteria (set now):**
- The replay cannot drive Claude Code's tool layer (question 1 fails), or it works only by modifying Claude Code.
- Terms position (question 2) is negative and no authorized route exists.
- The OS-level layer cannot run in the test environment and no alternative is defensible (question 3).
- Attribution is unobtainable for most blocks (question 5): the central claim would then be "something blocked it", which adds little.
- Phase 0 finds an existing suite with the same configuration axis, observers and attribution. The strongest prior art so far
  is `ipi_coding_agent`, which lacks the agent under test, the configuration axis and realistic egress, so this criterion is **not yet** met.

**If killed:** the honest fallback is an evaluation harness for existing injection suites with the configuration axis added,
or a short published write-up of Claude Code's documented gaps, measured. Neither is a product.

Overall: the premise is partly feasible and partly not established. Nothing here justifies building a framework.

## 14. Prompt Injection Detection: Potential Core Capability

Scope: an extension of section 13, researched as a possible part of LocalAI, not a separate product. Read-only. Nothing
built, nothing run on real data. Labels as before, plus **[S]** for search snippets I did not open in full.

### 14.1 Bottom line

**Detection is not a defense, and the best-known detectors fail against adaptive attackers. Do not build a detector as a
LocalAI product. Use detectors as comparators inside the evaluation work (option B), and put any protection in enforcement.**

### 14.2 Where injections arrive, and how detectable each is

| Channel | Detectable by a classifier? | Notes |
|---|---|---|
| Documents, PDFs, RAG chunks | Partly | Text can be extracted and scanned. Hidden text, white-on-white and PDF metadata need extraction-level checks first |
| Webpages | Partly | Same as documents. Injections can sit in hidden elements, alt text or markup the classifier never sees |
| Emails and messages | Partly | Quoted and forwarded text confuses classifiers: a legitimate security newsletter quoting an attack is a false positive |
| Code comments and repo files | Weakly | Instructions in comments look like normal developer text. Agents often treat comments as authoritative |
| MCP tool responses | Partly | Results are structured; classifiers may not see the field that carries the instruction |

Across all channels, the **indirect and obfuscated** cases (encoding, language switching, instructions split across chunks)
are the hard part, and they are where the evaluation has to focus.

### 14.3 Detection methods compared

| Method | Strength | Weakness | Local? |
|---|---|---|---|
| Pattern and rule heuristics | Cheap, explainable, zero false positives on known phrasing | Trivially evaded by paraphrase or encoding | Yes |
| Lightweight classifier (Prompt Guard 2 86M) | Trained on attack patterns; runs locally [D] | Explicitly scoped to attempts that "explicitly attempt to override prior instructions" [D]; self-declared vulnerability to adaptive attacks [D] | Yes, after download |
| LLM classification (self-check) | Handles paraphrase and context | Can itself be injected; slow; cost or locality depends on model | Yes if a local model, but Hermes 3 8B is weak at this |
| Hybrid (heuristics then classifier then LLM) | Layers catch different misses | Each layer adds false positives; still bypassable as a whole | Yes |

### 14.4 Detection versus prevention

- **Detecting** a suspicious instruction produces a label. It does not stop anything.
- **Warning the user** and **labeling untrusted content** change what the human sees. Useful, and measurable only as a human outcome.
- **Quarantining** content removes it from the agent's context. That is prevention for that content only.
- **Preventing influence** means the agent's instructions do not change because of the content. No detector achieves this alone.
- **Enforcing restrictions on subsequent tool execution** (section 13.4 and the permission and sandbox layers) limits what
  an injected instruction can *do*, whether or not it was detected. This is the only layer that bounds damage independently of
  whether the model was fooled.

**A detector can only be claimed as detection. Anything stronger must be shown by measuring the agent's actions with enforcement on.**

### 14.5 Existing alternatives (checked)

| Project | Status [V/D] | Detects | Local? | Notes |
|---|---|---|---|---|
| **LLM Guard** (protectai) | **Archived 2026-07-09**, MIT [D] | Prompt injection scanner (input) | Scanner page returned 404; not verified | No longer maintained |
| **Rebuff** (protectai) | **Archived 2025-05-16**, Apache-2.0 [D] | Heuristics, LLM check, vector store of prior attacks, canary tokens | **No**: quickstart calls OpenAI and Pinecone [D] | Self-described "still a prototype and cannot provide 100% protection" [D] |
| **Meta Prompt Guard 2 86M** | Current, Llama 4 Community License (not MIT) [D] | Benign vs malicious classifier for prompt injection and jailbreaks | **Yes**, runs locally via Transformers once downloaded [D]; gated download | Self-stated: "adversaries may develop sophisticated attacks specifically to bypass detection" [D]. Reported 97.5% recall at 1% FPR on a **private** benchmark [D]: not independently checked |
| **NeMo Guardrails** (NVIDIA) | Current, open-source library [D] | Heuristic patterns (local), self-check LLM, NemoGuard NIM (hosted service) | Heuristic: yes [D]; NIM: no | Direct vs indirect split not stated [D] |
| **Microsoft Prompt Shield** | Docs page returned 404 [unverified] | Prompt injection, cloud service | Believed cloud-only [U] | PyRIT has a scorer for it [V] |

**Assessment:** The field is crowded and its best open-source entries are archived or depend on a model whose own card
concedes adaptive-attack risk. A new LocalAI detector would be a fourth or fifth entry with no measured advantage.

**The adaptive-attack result is the most important finding in this section.** "The Attacker Moves Second" (arXiv 2510.09023,
October 2025, authors from several frontier labs and academia) reports that 12 published jailbreak and injection defenses
were all bypassed by adaptive attacks, with success rates reported as 71% to 100% across the 12 [S, from a search summary; I did
not open the full text]. Its authors also report that stacking detectors did not solve the problem, and that human
red-teaming was at least as effective as automated attacks [S]. Treat these numbers as unconfirmed until the paper is read.

### 14.6 Evaluation plan (measurable, pre-registered)

Metrics, each defined before data is collected:
- **Detection rate (true positive rate):** flagged malicious samples ÷ malicious samples, per channel and per obfuscation level.
- **False positive rate:** flagged benign samples ÷ benign samples. **The benign set must include legitimate documents that
  quote malicious instructions** (security write-ups, prompt-injection tutorials, a support ticket that reproduces an attack
  for debugging). These are the realistic false-positive cases.
- **False negative rate:** 1 minus detection rate, reported with the obfuscation level that produced it.
- **Latency:** median and p95 milliseconds per document on fixed local hardware, with and without model loading.
- **Adaptive robustness:** detection rate after an attacker tunes payloads against the detector under test. Without this
  number, a detection rate measures only the attacks nobody tried to hide.

Datasets: fully synthetic, written for this purpose, with no real customer content. Obfuscation levels: plain, paraphrased,
encoded (base64, homoglyphs), split across chunks, language-switched, and hidden in markup. Each malicious sample must
carry a label for whether it would change agent behavior in a sandboxed run, so detection is compared with real effect.

### 14.7 Option A versus option B

- **Option A: LocalAI as an independent detector.** Crowded, weakly differentiated, and its key number (adaptive robustness)
  is likely poor. Not recommended as a product.
- **Option B: an evaluation platform that also tests detectors.** Its core claim is measurement, which the adaptive-attack
  literature shows is the missing piece. Detectors enter as comparators, and a detector is measured on what it does to
  agent behavior, not on classifier accuracy alone.

**Recommendation: option B, with detection as one measured configuration among several.** The two should coexist only in
that sense. Developing A separately would divert effort from the evaluation work, which is the only part with a
plausible contribution.

### 14.8 Architecture implications

- A detector is one more **pre-agent filter** in the configuration axis from section 13.6. It does not replace permission,
  hook or sandbox controls.
- Labeling untrusted content (a `<document>`-style wrapper) already exists in LocalAI (`wrap_untrusted`). Its effect on
  agent behavior is measurable and should be in the evaluation, since labels are cheap and often assumed to help.
- A local classifier needs a model download under a Llama license. That is a new dependency and a licensing decision,
  which needs your approval. The 22M variant is smaller but was not evaluated here.
- Hermes 3 8B as a local LLM classifier is unlikely to be reliable; I would not use it as a detector without measuring it first.

### 14.9 Realistic MVP (only if the section 13.7 gate passes)

1. A synthetic dataset of about 100 documents: benign documents, benign documents quoting attacks, and malicious documents at
   each obfuscation level, each labeled for real effect.
2. Three comparators: a regex heuristic set (written for this, not copied), Prompt Guard 2 86M (after approval of its licence),
   and the wrapper with no detector (the control).
3. Report detection rate, false positive rate, latency and the effect on a scripted agent run, per comparator and channel.
4. No product, no API, no user-facing feature. Results go into the evaluation report.

**Kill criterion for this sub-question:** if the regex and classifier comparators cannot be distinguished from the control on
real agent effect, the detector is not worth measuring further.

### 14.10 Final recommendation for this section

**Do not pursue prompt injection detection as a core product capability. Include detectors only as measured comparators in
the evaluation proposal (option B), and only after the section 13.7 gate.** The research supports a measurement contribution
and does not support a detection product: the open tools are archived or limited, the leading classifier concedes adaptive
attacks, and the main published result says defenses of this kind fail under adaptive attack.

## 15. Verification pass and decision request (2026-11-20)

No live Claude calls, no paid API use, no dependency installs, no application or config changes. Labels: **[V]** verified
from full text or source; **[D]** project docs; **[S]** search or agent summary only; **[U]** unverified.

### 15.1 "The Attacker Moves Second" (arXiv 2510.09023)

- **Read:** the HTML version, mostly verbatim [V]. The PDF returned no usable text, and the appendices were summarized only [S].
- **Defenses (12) [V]:** prompting (Spotlighting, Prompt Sandwiching, RPO); training (Circuit Breakers, StruQ, MetaSecAlign);
  filtering models (Protect AI detector, PromptGuard, PIGuard, Model Armor); secret-knowledge (Data Sentinel, MELON).
- **Adaptive results [S, not confirmed against tables]:** search-based attacks reached above 95% against Spotlighting and
  Prompt Sandwiching, 96% against MetaSecAlign, and 90% or more against the Protect AI and PromptGuard detectors. PIGuard was
  at 71%. The "71% to 100%" range in section 14 comes from these summaries, so I cannot yet confirm it.
- **Human red-teaming [V]:** over 500 participants. Successful injections were 265 against Spotlighting, 178 against Prompt
  Sandwiching, 123 against detectors under the strictest setting, and 69 against MELON. The appendix says competitors "defeat
  every challenge" in the study.
- **Agentic evidence [V]:** the paper uses AgentDojo, an agentic benchmark, for prompt injection, alongside non-agentic sets.
- **Detector statements [V]:** "simply adding more filters or stacking additional detectors does not resolve the underlying
  robustness problem," and detectors are "a useful–but limited–component."
- **Code and licence [V/U]:** the arXiv page says CC BY 4.0. No code release statement was found [U].

**Consequence:** the detector finding is well supported in direction. The exact percentages in section 14 must be marked as summary-derived until the PDF or full appendix tables are read.

### 15.2 Inspect AI and inspect_evals

- **Currency:** this session cloned `inspect_evals` (commit `c2d3d5e`, 2026-11-19) for the first time today. I have no earlier snapshot, so I cannot report a change since a prior review. The state I read is current as of this clone [V].
- **`ipi_coding_agent` [V]:** still uses Inspect's generic `react()` agent, not Claude Code; `network_mode: none`; canary-in-tool-call scoring. Its limits in section 13.1 stand.
- **Inspect AI `0.3.291` (`c574b6b`) and `inspect_swe` `0.3.2` (`63ab177`) [V]:** as read on 2026-11-19 to 20.
- **Mock model [V]:** `MockLLM` is implemented (`src/inspect_ai/model/_providers/mockllm.py`).
- **Bridge [V]:** `inspect_swe` sets `ANTHROPIC_BASE_URL` to a local bridge port.

### 15.3 Claude Code: current docs versus installed 2.1.296

Checked against the official pages [D, read 2026-11-20]:

| Item | Status | Installed 2.1.296 |
|---|---|---|
| Sandbox off by default | Verbatim: "The sandbox is off by default." [V] | Expected, not tested |
| Deny rules skip subprocess reads | Verbatim: they "don't apply to arbitrary subprocesses that read or write files indirectly" [V] | Documented, not tested |
| `onFailure` on command hooks | Requires v2.1.295 or later [V] | Should be present [inferred from version order, U] |
| Sandbox refuses per command when it cannot start (2.1.328) | Changelog [V] | **Absent**: 2.1.296 may run unsandboxed if the sandbox fails [inferred, U] |
| `autoAllowBashIfSandboxed` (2.1.325) | Changelog [V] | Absent |
| PreToolUse "allow" behavior change (2.1.325) | Changelog [V] | Behavior differs |
| `onFailure` for Code Mode (2.1.329) | Changelog [V] | Absent |

**Consequence:** the installed version predates several behavior changes the spike would test. Any result must state the exact version, and the spike should either pin a newer version or report results on 2.1.296 only.

### 15.4 Anthropic terms: scripted replay and mock models (not legal advice)

Relevant clauses [V, from the official pages read earlier]:
- **Usage Policy:** prohibits "instructing the model to produce harmful outputs (e.g., jailbreaking or prompt injection)" to bypass guardrails "without prior authorization." A replay with mock responses sends no instructions to a model, so this clause is not obviously triggered.
- **Consumer Terms:** automated access is barred "except when you are accessing our Services via an Anthropic API Key or where we otherwise explicitly permit it."
- **Commercial Terms:** no clause found on automated testing of the Claude Code binary or on pointing it at another endpoint [U].

**Open questions that need counsel or written permission, not my judgement:**
1. Does running the official Claude Code binary against a local mock endpoint (no Anthropic service contacted) count as using the Services? The terms I read do not address this [U].
2. Does a replay that contacts no Anthropic service fall outside the automated-access clause at all?
3. Does the binary's own licence or terms restrict redirecting its API traffic?
4. Does the replay ever need a real API key? If it does, the Usage Policy applies.

**Recommendation:** get written permission or a legal review before any step that runs the Claude Code binary, even offline.

### 15.5 Dependencies (evaluation only; none installed)

| Dependency | Why needed | Replaceable? | Maintenance and compatibility | Licence | Belongs in final project? |
|---|---|---|---|---|---|
| **Inspect AI** | Sandboxed task runner, scorers, mock model, logs | Custom harness would reinvent it; no, not recommended | Very active; MIT; Python 3.11 or later [inferred from inspect_swe] | MIT | Research environment first; a dependency in the final project only if the spike passes |
| **inspect_swe** | Runs Claude Code through the bridge | Custom bridge would be fragile | Frequent releases, some breaking (Python 3.11 minimum); contains an `sk-ant-api03`-shaped literal, probably a placeholder [U] | MIT | Isolated research environment only |
| **Meta Prompt Guard 2 86M** | Local injection classifier comparator | Yes: a regex comparator and the no-detector control cover the MVP | Gated download; licence and data-form requirements below | **Llama 4 Community License, not MIT** [V] | **No.** Research comparator at most |

Prompt Guard licence requirements [V, from the page's embedded copy of the licence]:
- Attribution: "Built with Llama" prominently displayed if you distribute a product containing it, plus a copy of the agreement and a notice file.
- Naming: a model trained or improved with its outputs must start its name with "Llama".
- Acceptable Use Policy incorporated by reference.
- 700 million monthly active users threshold requiring a Meta licence.
- Gated access asks for full legal name, date of birth and organization, collected under Meta's privacy policy.
- Governing law: California.
- It is unclear whether this licence text applies to a DeBERTa-based classifier, and the Llama site redirected, so the canonical copy was not read [U]. Counsel question.

### 15.6 Claude Corps Fellowship (Cohort 3)

- **Found [S]:** the official FAQ (`anthropic.com/claude-corps/fellow`) and a Cohort 3 Greenhouse posting exist. I could not read the Greenhouse posting directly, so the points below come from search summaries.
- **Stated eligibility [S]:** 18 or older; uses Claude or AI daily; baseline understanding; authorized to work in the US (no visa sponsorship). Cohort 3 starts August 2027; applications opened late September 2026; review is rolling.
- **Application expectations [S]:** completion of AI Fluency and Claude 101 with proof; having built something; demonstrated community, nonprofit or public-interest experience.
- **Third-party claims not confirmed [U]:** a January 31, 2027 deadline; a US 501(c)(3) host requirement; the $85,000 salary.
- **Official criteria status:** **partially located, not fully verified.** I have not read the full official criteria, and the summaries conflict on several details. Read them yourself before relying on any of this.

**Alignment:** the project meets "built something" in principle. It has a weak link to the stated community or public-interest expectation. Without a real nonprofit or organization relationship, that expectation is unmet. The project would need that connection built deliberately, not added later.

### 15.7 Updated feasibility and decision

**What is now verified:** the Attacker Moves Second paper's direction (detectors fail under adaptive attack, humans succeed); the Claude Code default-off sandbox and subprocess-read gap (verbatim); and the version-gap risk.

**What remains open:** the exact adaptive percentages, the Anthropic terms questions in 15.4, the replay itself (still untested), attribution feasibility, the Prompt Guard licence, and the official fellowship criteria.

**Recommendation: MODIFY.** Do not approve the full one-week spike yet. Approve only:
1. **Terms first:** written permission or counsel review on the questions in 15.4, before any step that runs the Claude Code binary.
2. **Version decision:** either upgrade to a version with the documented behavior (2.1.328 or later) or state explicitly that results apply to 2.1.296 only.
3. **Then a one-day, offline replay check** with mock responses and no Anthropic contact, using only an isolated research environment, if item 1 is cleared.

Abandon the spike if item 1 is negative and no authorized route exists. Keep Prompt Guard out of any project dependency unless the licence question is resolved.

## 16. Compliant paths forward (2026-11-20)

No live Claude calls, paid API use, dependency installs or code changes. Not legal advice. Labels as before.

### 16.1 Three testing approaches

**A. Local-model testing (no Anthropic involvement) [A, technically feasible; compliant on its face].**
- Uses a local model (Hermes 3 via Ollama, already in LocalAI) or any local agent, inside an isolated Docker sandbox.
- Tests what the *environment* allows: file reads, network egress to a sink, canary exposure, command execution, MCP-style tool calls.
- Reusable from LocalAI: the file guard, approval inbox, untrusted-text wrapper, eval harness pattern, activity log.
- **Limit:** it does not test Claude Code's permission rules, hooks or sandbox. It answers "what can an agent with these tools do?", not "does Claude Code's safety layer hold?".
- Whether Inspect supports an Ollama provider out of the box was not checked here [U].

**B. Scripted Claude Code with a mock model [B, partly feasible; policy unresolved].**
- **Feasible, verified:** the installed binary (2.1.296) contains `ANTHROPIC_BASE_URL` 115 times and `ANTHROPIC_AUTH_TOKEN` 73 times [V, string count only].
- **Documented, verified:** Claude Code supports a custom gateway through `ANTHROPIC_BASE_URL` [D, llm-gateway docs]. The docs describe it as a company-run proxy for Claude models, not a test mock.
- **Not documented [U]:** mock or offline use. Neither page mentions testing mocks.
- **Traffic leaks by default [D]:** with a custom endpoint set, Claude Code still sends telemetry, version checks and release-note requests to Anthropic and GitHub. Disabling them with `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` also disables auto-updates. Some checks still call `api.anthropic.com` directly even when it is set. So "no contact with Anthropic" needs network enforcement, not just a setting.
- **Attribution risk:** a scripted model can drive the real tool layer, but whether the sandbox and permission code run exactly as in production is untested.
- **Policy:** the gateway docs say Anthropic's terms still apply to the traffic, and they do not say whether that covers a mock [U]. Documented configuration does not settle whether a mock is permitted.

**C. Testing Anthropic's actual protections [C, not authorized].**
Sorted by risk:

| Activity | Risk | Why |
|---|---|---|
| Reading public docs and source for documented behaviour | Low | Public information |
| Running benign functional tests on your own machine | Low to medium | Ordinary use; check the subscription vs API terms |
| Simulating attacks against your own infrastructure | Low to medium | Usage Policy carve-out exists, but only for systems you own |
| Replaying scripted tool calls with no model call | Medium | Terms on automated access apply; not clearly permitted or prohibited |
| Injecting instructions into Claude to test its safety | **High** | Usage Policy prohibits prompt injection without prior authorization |
| Trying to bypass Claude Code's own guardrails | **High** | Same clause; no exemption for Anthropic's products |

### 16.2 Compliant architecture

Keep the framework model-agnostic and split the agents from the evaluator:

```
Scenario library (fixtures, canaries, expected effects)       — no model
Orchestrator (Inspect task or LocalAI runner)                  — no model
Agent adapters:
   • local model via Ollama (LocalAI's DocAgent as one adapter)   ← compliant, first
   • scripted agent (fixed tool calls, no model)                   ← compliant, first
   • Claude Code via ANTHROPIC_BASE_URL                            ← only with written permission
Isolated Docker sandbox, no route to the internet, sink on an internal network
Observers outside the agent: file digests, sink log, canary matching, hook/sandbox logs
Verifier: code over evidence, no model judging
Report: outcomes + attribution + versions + raw logs
```

**Attribution rule:** an operation is "blocked by layer X" only if an observer for layer X recorded the denial. A model's refusal is recorded as a refusal and never counted as containment.

### 16.3 What the one-day experiment would prove and not prove

**Would prove (no paid calls, no Anthropic contact, no real secrets):**
- The harness can run a local or scripted agent in a disposable container, plant synthetic canaries, and detect a canary reaching a sink.
- Observers can distinguish "the operation ran" from "the operation was blocked" for a sandbox and a network rule we configure ourselves.
- Results are reproducible across two runs.

**Would not prove:**
- Anything about Claude Code's own permissions, hooks or sandbox. Those are not exercised.
- How any proprietary agent behaves in production.
- That the sandbox settings work on a developer's machine, as opposed to a container.
- That the findings generalize beyond the agents and configurations tested.

**Experiment steps (proposed, not run):** one scripted fake `.env`, one local model reading an instruction file, one egress attempt to a sink on an internal network, one attempt to read a file outside the workspace; with and without a restrictive network policy. Record the outcome and which observer recorded it.

### 16.4 Existing tools and what LocalAI could add

- **Inspect AI and inspect_evals** already run agents in Docker sandboxes, include an injection suite with canaries (`ipi_coding_agent`), and support scripted models. Rebuilding that is not justified.
- **inspect_swe** runs Claude Code inside Inspect. It is the only existing route to Claude Code in a sandbox, and it has the policy questions above.
- **PyRIT, garak, AgentDojo** cover model-level and simulated testing, as in sections 2 and 13.
- **The contribution that is still open:** a configuration comparison that attributes which layer blocked each operation, for local agents and, if ever permitted, Claude Code. Existing suites don't do attribution, and I have seen no measured comparison of safety configurations of that kind.
- LocalAI's specific value is smaller: its file guard, approval flow and untrusted-text wrapping as test subjects, plus a local-first setup for users who don't want cloud agents.

### 16.5 Recommendation

**CONDITIONAL GO, on the platform as a local-agent evaluation tool, not on Claude Code integration.**
- **Go:** approach A, with a one-day experiment that uses only local or scripted agents, as in 16.3. It is compliant on its face, technically feasible and doesn't need Claude at all.
- **Conditional:** approach B only after written permission from Anthropic. Its documented configuration doesn't settle the terms question, and the mock path is undocumented.
- **No-go:** approach C, and any live Claude test of injections or bypasses.

This does not depend on Claude Code integration. If the local-agent approach shows the attribution idea works, the Claude Code piece becomes an optional later extension. Don't drop the project because the Claude route is closed. Do drop the Claude claim from any pitch until permission is granted.

**Decision for you:** approve the one-day local-agent experiment in 16.3, or wait for Anthropic's answer first.

## Sources

Projects and documentation (primary): [garak](https://github.com/NVIDIA/garak) ·
[PyRIT](https://github.com/microsoft/PyRIT) ([docs](https://microsoft.github.io/PyRIT)) ·
[AgentDojo](https://github.com/ethz-spylab/agentdojo) ·
[Inspect AI](https://github.com/UKGovernmentBEIS/inspect_ai) ([agent bridge docs](https://inspect.aisi.org.uk/agent-bridge.html)) ·
[inspect_swe](https://github.com/meridianlabs-ai/inspect_swe) ([Claude Code docs](https://meridianlabs-ai.github.io/inspect_swe/claude_code.html)) ·
[OWASP agentic threats and mitigations](https://genai.owasp.org/initiatives/agentic-ai-threats-and-mitigations/).
Papers (abstract level): [CIBER](https://arxiv.org/abs/2602.19547) · [IssueTrojanBench](https://arxiv.org/abs/2607.20759) ·
[LivePI](https://arxiv.org/abs/2605.17986) · [WASP](https://arxiv.org/abs/2504.18575) ([code](https://github.com/facebookresearch/wasp)) ·
[OS-Harm](https://arxiv.org/abs/2506.14866) ([code](https://github.com/tml-epfl/os-harm)) ·
[InjecAgent](https://arxiv.org/abs/2403.02691) ([code](https://github.com/uiuc-kang-lab/InjecAgent)) ·
[AgentDojo paper](https://arxiv.org/abs/2406.13352).
Secondary (weakest): benchmarklist LivePI page; blog summaries of IssueTrojanBench and a crosswalk of injection benchmarks;
a vendor audit of seven agents. Not relied on for any claim in a table cell marked [V].

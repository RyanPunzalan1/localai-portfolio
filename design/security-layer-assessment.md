# LocalAI as an independent security layer for AI agents: assessment

Written for: the project owner, to decide whether to commit to this direction before any code is written.
Status: **Assessment only. Nothing is built or changed.** Rules: CLAUDE.md. Replaces nothing; the Square note
(design/connector-boundary.md) is kept and paused.

Evidence labels used below: **[code]** read in this repo; **[docs]** reported from Claude Code's official docs by a
research agent (code.claude.com, a snapshot the agent dated May 2026, so **re-check before relying on it**, because
Claude Code changes quickly); **[unverified]** not checked; **[hypothesis]** a claim that an experiment must confirm.

## 0. The short answer

1. LocalAI today is **a safe local agent app**, not an enforcement layer for other agents. Claude Code does not pass
   through it. [code]
2. Claude Code already enforces a lot: permission rules, an OS-level sandbox for shell commands, hooks, managed
   settings, containers. Rebuilding those would be waste. [docs]
3. Real gaps do exist in the documented defaults (section 5). They are mostly *configuration and coverage* gaps,
   which a new layer could close only if it adds a guarantee those controls lack.
4. The plausible differentiators are narrow: **(a) stateful, deterministic policy across a whole session** (for
   example "after untrusted content was read, no network egress") and **(b) credential brokering** (the agent never
   holds the secret), plus **(c) a measured, public attack evaluation**. All three are **[hypothesis]** until a spike
   shows an attack that gets through the agent's own protections and is stopped by the layer.
5. **Recommendation: a short spike (about one week) before committing.** If it cannot show a necessary, effective and
   usable case, stop or change direction. Section 9 gives the kill criteria.

## 0.5 The five questions, answered directly

**Q1. What can LocalAI protect that Claude Code cannot already protect?**
Nothing is proven today. Three candidates, all **[hypothesis]**: (a) a deterministic, session-wide rule such as "after
untrusted content was read, no network egress", which per-call rules do not express (G3); (b) keeping credentials out
of the agent's reach even for tools that run outside the Bash sandbox, such as file tools and stdio MCP servers (G1, G2);
(c) a tamper-evident record of what the agent did. One more is true by definition but untested as a need: Claude Code's
controls only protect Claude Code, so a layer outside it could protect other agents. A broad allowed domain is a
*possible* exfiltration route, not a demonstrated one; the evaluation must show data actually arriving at the sink.

**Q2. Which protections need OS-level enforcement, not Python checks or prompts?**
OS or container level: no network route except to the broker; no credentials in the agent's account; the agent
cannot edit the policy, the broker or the log; reads by arbitrary subprocesses; separating untrusted pack code from the
app. Python checks are fine *inside* the broker (path normalization, taint rules, the audit chain), but only because the
OS boundary stops the agent from going around the broker. Prompts and model judgment are never a control.

**Q3. Can an agent bypass LocalAI and do the same thing directly?**
Today: yes, completely, because there is no integration. With the proposed design: yes, unless the agent is run with no
credentials and no other network route. An MCP server alone protects only MCP calls and leaves shell, files and network
as they were. The design therefore must not be described as protecting "the agent". It protects operations that go
through the broker, for an agent run in the documented way.

**Q4. What is the smallest prototype that proves value?**
A broker with two capabilities (read a protected file, make a network request), a taint rule between them, and an agent
in a container holding no secrets with a route only to the broker. One scripted attack: an injected file makes the agent
read a canary secret and send it to a local sink. Success means the sink receives it under configuration B (well-
configured Claude Code) and does not under D (B plus the broker), while a set of legitimate tasks still works.
Before any broker code, the spike runs the same attack against A and B to get the baseline.

**Q5. What results would convince a skeptical technical reviewer?**
A public repo that reruns from one command with canary secrets only; scripted-adversary results *and* live-agent runs
repeated enough times to report rates; B versus D, not A versus D; the false-block rate and prompts per task; every miss
listed with reproduction steps; kill criteria written before the results; and someone other than me rerunning it.

**Status of everything in this document**

| Implemented (in the repo today) | Proposed (not built) | Unverified |
|---|---|---|
| File guard and tests; approval inbox; untrusted-text wrapper; container hardening; eval harness style; one Claude Code write-guard hook | Broker and MCP interface; session taint policy; hash-chained audit log; canary and sink rig; scripted-adversary runner | Every gap G1 to G7 as a real bypass; the docs snapshot (dated May 2026); `sandbox-runtime`; open-source MCP gateways; whether the container reaches host-local services; whether Claude Code's auto mode already covers G3 |

## 1. Current architecture, in one paragraph

A Streamlit app (`app.py`) with a coordinator (`brain.py`) that picks one agent per request and asks you to approve the
route. Agents are `DocAgent` plus two packs (tasks, lessons). Packs use a Gateway (`packs_gateway.py`) that checks a
manifest and a shared file guard (`agent._safe_path`). Every write goes to an approvals inbox
(`pending_store.py`) and only the UI applies it. File text is wrapped as untrusted data (`safety.py`). Docker runs the
app read-only with no capabilities and no socket. The activity log records lengths, not text. [code]

## 2. Enforcement: what is real and what is only described

| Control | Claimed in | Actually enforced by | Verdict |
|---|---|---|---|
| Notes only in `docs/`, plain `.md`/`.txt` names, no symlink or hard link | CLAUDE.md, threat model | `_safe_path` in code, tested (`test_security.py`) | **Enforced in code** (in-process) |
| No write without approval | rules | `approve_write` is called from one place in the UI ([app.py:532](app.py#L532)); proposals only go to the inbox | **Enforced**, but the inbox is a JSON file in `logs/`; anything that can write that file can add a pending item (a human click is still needed) |
| Packs "never open files, never use the network" | design/packs.md, rule files | Convention and review. Packs are Python loaded with `importlib` into the **same process** ([packs_agent.py](packs_agent.py)); nothing stops a pack from importing `os` or `subprocess` | **Not enforced** against a hostile pack. The container is the real boundary |
| Model cannot be trusted with file text | prompts, `wrap_untrusted` | Wrapping and prompts; hostile-note evals held 12/12 on hermes3 | **Reduced, not guaranteed** (threat model gap 11) |
| Container isolation | docker-compose.yml | Docker: read-only fs, caps dropped, non-root, 2 GB, no socket. `docs/` and `logs/` writable. **Outbound network open.** `host.docker.internal` is mapped to the host | **Real but partial**. Egress is the main hole [code]. Whether host-local services are reachable from the container is [unverified] |
| Audit log | threat model | `ActivityLog`: lengths only, rotates at 1 MB keeping **one** old file | **Not sufficient** to reconstruct what an agent did, and not tamper-evident |
| Claude Code write guard (this repo's `.claude/hooks/guard-writes.py`) | threat model | A PreToolUse hook on `Edit\|Write\|NotebookEdit` only | **Partial**: it does not cover Bash. See section 5 on fail-open behavior |
| Read ban on `docs/` for the coding assistant | threat model | `deny` rules for Read/Edit/Write | **Partial**: the docs say Read-deny does not cover arbitrary subprocess reads such as `python -c` [docs]. Known gap S.1 |
| Anything controlling an external agent | (the new idea) | **Nothing** | **Does not exist** |

## 3. What Claude Code already does (do not rebuild) [docs]

| Capability | What it gives |
|---|---|
| Permission rules (`allow`/`ask`/`deny`, deny wins; bare `deny Bash` removes the tool) | Per-call control for built-in and MCP tools (`mcp__server__tool`) |
| OS sandbox for Bash (Seatbelt on macOS, bubblewrap on Linux) | Real kernel-level file and network limits for shell commands and children, with a domain allowlist through a proxy. **Off by default** |
| Hooks (33 events; PreToolUse can deny) | Custom per-call checks, for Bash and MCP tools too |
| Managed settings | Policy a user or project cannot override; can force the sandbox, block bypass mode, allow only managed hooks |
| Devcontainer and reference firewall | Whole-process isolation; Anthropic's own warning: "no system is completely immune" |
| Modes (`default`, `acceptEdits`, `plan`, `auto`, `dontAsk`, `bypassPermissions`) | Different approval trade-offs; docs say bypass is for containers or VMs |

Rebuilding a Bash sandbox, a filesystem allowlist, or a per-tool allow list would be **duplicating** these. I would not
do it without a measured advantage.

## 4. Where other tools sit (partial: one search task failed) 

| Tool | What it does | Limit [as read] |
|---|---|---|
| MCP spec security guidance | Obligations for server and client implementers | Advice, no runtime enforcement, no per-call policy point |
| NVIDIA NeMo Guardrails (tool rails) | Returns pass/block for a proposed tool call, incl. a hooks server for coding agents | A decision API: enforcement depends on the harness calling it; does not contain the tool |
| Anthropic `sandbox-runtime` | Open-source sandbox used for the same purpose | **Not read** |
| Open-source MCP gateways (policy proxies) | **Not reviewed**: the research agent could not search | **Gap in this assessment.** Must be done before any claim of novelty |

## 5. Documented gaps a new layer could address, each a hypothesis to test

| # | Gap in the agent's own controls [docs unless noted] | Candidate LocalAI response | Overlap risk |
|---|---|---|---|
| G1 | Sandbox is opt-in and covers only shell commands. Read/Edit/Write/WebFetch, stdio MCP servers and hooks run outside it | Broker the sensitive operations outside the agent | Claude Code may widen sandbox coverage |
| G2 | Reads are allowed across the machine by default, including `~/.ssh`; credential masking is a separate optional feature | Credential broker: secrets never in the agent's reach | Partly covered if masking is turned on |
| G3 | Per-call rules are **stateless**. Nothing says "the agent just read untrusted content, so block egress now" | **Session policy with taint tracking, deterministic, no LLM** | Auto mode uses a classifier; a deterministic rule is a different guarantee. Strongest candidate |
| G4 | Broad allowed domains (for example github.com) can carry data out; TLS is not inspected by default | Egress policy keyed on session state and destination, not just hostname | Overlaps the sandbox proxy |
| G5 | Hooks **fail open** on any non-zero exit other than 2, on bad JSON, and on timeout, unless `onFailure: "block"` is set (newer versions) | A broker whose absence means no access, so failure is closed by construction | Fixable by configuration. Weak differentiator |
| G6 | Whether the agent can edit its own settings or hook files in default mode is unconfirmed [docs gap]. Project-level settings are in the repo the agent can touch | Policy outside the agent's filesystem and account | Managed settings already solve this for admins |
| G7 | Read-deny misses subprocess reads such as `python -c` or `grep -r` run elsewhere | Enforce below the tool layer (OS user or container) | The sandbox already does this when on |

**A finding about this repo, from the same reading:** [.claude/hooks/guard-writes.py](.claude/hooks/guard-writes.py)
is written to "fail closed", but that holds only for errors *inside* the script. If `python3` cannot start (exit 127)
or the hook times out, the docs say the write proceeds. [docs] That is a concrete example of G5 and is cheap to test.

## 6. Enforcement architecture options

| Option | What it is | Strength | Weakness |
|---|---|---|---|
| Gateway (policy decision point) | Agent or harness asks "may I?" before acting | Easy to add (an MCP server or hook) | **Only advisory**: a harness that skips it, or a hook that fails open, is unprotected |
| Execution broker | The broker *performs* the action and holds the secrets; the agent has no direct access | A bypass fails closed if the agent truly has no other path | The agent's other tools (Bash, Read) must be removed or sandboxed, which needs agent configuration or an OS boundary |
| Sandbox manager | Runs the agent in a container or VM | Strong against escapes | Overlaps Claude Code's sandbox and devcontainer; heavy |
| Hybrid | Agent runs in a container with no secrets and network only to the broker; the broker holds credentials and applies stateful policy | Closest to a real guarantee | Most work; needs Claude Code configured to cooperate |

**Recommendation: the hybrid, built in the smallest form that can be measured.** A broker exposing a few tools over MCP,
a stateful policy engine in code (no model involved), and a documented way to run the agent with no direct credentials
or network. Do not build a sandbox. Use Claude Code's own, or `sandbox-runtime` once read.

## 7. Bypass resistance (what "fails closed" really requires)

A deliberately hostile agent can ignore any gateway it is merely *asked* to use. So a protected operation fails closed
only if **all** of these hold, and the evaluation must test each:

1. The agent's process has no credentials, so there is nothing to steal. (Broker holds them.)
2. The agent's OS user or container has no network route except to the broker. (Needs an OS or container boundary.)
3. The agent cannot edit the policy, the broker, or the log. (Separate account, or managed settings.)
4. The broker denies by default: an unknown operation, a malformed request or a broker outage means *no access*.
5. Policy decisions never depend on an LLM.

What stays **outside LocalAI's control**: anything the agent can do with its own legitimately held access; a malicious
or compromised MCP server running as the user; a kernel or container escape; a user who approves everything; an agent
run without the setup above. The honest claim is "operations that go through the broker, with the agent run in the
documented way", not "agent safety".

## 8. Threat model summary

| Threat | Prevent | Detect only | Outside control |
|---|---|---|---|
| Injected instruction in a file or page causes a secret read plus egress | Taint policy (G3) and no secrets in the agent (G2), if the setup holds | Hash-chained audit | An agent that holds the secret itself |
| Credential theft from `~/.ssh`, `.env`, cloud keys | Brokering plus a no-credentials account | Canary tokens | Credentials the user places inside the agent's workspace |
| Path traversal, symlink | Existing file guard logic (code), tested | n/a | |
| Unauthorized network exfiltration | Network route only to the broker | Egress log | Allowed-domain abuse, if the user allows it |
| Destructive commands | Approval or deny in the broker | Log | Commands run outside the broker |
| Approval bypass | Approvals only applied by the trusted UI or broker process | Log | A user who approves blindly |
| Malicious tool responses | Treat as data, taint state | Log | Model compliance |
| Container escape | Not claimed | n/a | Kernel and runtime vulnerabilities |

## 9. Evaluation plan (the centerpiece)

**Setup.** An isolated container or VM with fabricated secrets (canary tokens in a fake `.env` and fake `~/.ssh`), a
local sink that records any exfiltration, no real credentials, no real network. Nothing touches `docs/` or the host.

**Two kinds of runs, because a real model is noisy and often refuses:**
1. **Scripted adversary** (deterministic, no LLM): fixed tool-call sequences played against each configuration. This is
   the main result, because the layer must hold even if the model is fully compromised.
2. **Live agent runs**: a real agent against injected documents, repeated N times, to report rates and say plainly that
   a model refusing an attack is not evidence of a control.

**Configurations:** (A) Claude Code default; (B) Claude Code with the sandbox and a tuned permission set, i.e. its
best-practice setup; (C) the LocalAI broker alone; (D) B plus C. The comparison that matters is **B versus D**: does
the layer stop attacks that a well-configured Claude Code lets through? Comparing against the *default* alone would
flatter the project and I would not report it as the headline.

**Attack categories (each with legitimate-action controls):** credential read through Read, Bash and a subprocess;
traversal and symlink; injection in a file, a web page and a tool result; exfiltration to an allowed domain and a
disallowed one; destructive commands; approval bypass; settings and hook tampering; hook failure and timeout;
sequence attacks (read, then send).

**Metrics:** attack success rate per category and configuration; false-block rate on a set of legitimate developer
tasks; **human prompts per task** (usability); added latency; setup steps and time for a developer. Report misses in
full, with the exact steps to reproduce.

**Kill criteria (decide before looking at results):**
- *Necessity*: no attack category where B lets something through that is within reach of a broker. Stop.
- *Effectiveness*: the layer stops fewer than the cases it claims, or only when the agent cooperates. Change design.
- *Usability*: a developer needs more than about 15 minutes to set it up, or legitimate tasks need many more prompts than
  B. Change design.

## 10. What to reuse, redesign, build

| Reuse | Redesign | Build new | Pause or ignore |
|---|---|---|---|
| File-guard logic and its tests; approval inbox; untrusted-text wrapping; pack manifest idea (permissions as data); eval harness style; container hardening | Audit log (full tamper-evident record, no silent deletion; keep content-free option); pack isolation (process separation if packs are to be untrusted); egress | Broker and MCP interface; stateful policy engine; canary and sink test rig; scripted-adversary runner; attack catalogue | Streamlit UI, the 8B-model agents, Square connector. None is needed for this claim |

Nothing needs deleting now.

## 11. Rules in CLAUDE.md that this direction would change (needs your approval, not assumed)

- "No free-form shell access" and "file tools stay restricted to `docs/`": an execution broker would run commands for
  an external agent. It would need an allowlist and approval, as CLAUDE.md already says, but this is a **change to the
  project's scope and file-access rules**.
- The README, threat model and architecture overview describe a notes-and-tasks assistant and would be rewritten.

## 12. Prioritized roadmap

0. **Spike (about 1 week, no product code):** build the canary and sink rig; play 6 scripted attacks (G1, G2, G3, G4,
   G5, G7) against configurations A and B; record what gets through. This also gives a **baseline report that is
   valuable on its own**, even if the product is dropped. Also read `sandbox-runtime` and review two open-source MCP
   gateways (the open gap in section 4).
1. **Decision gate:** apply the kill criteria. Write up the findings, including the negative ones.
2. **MVP broker:** two capabilities only (protected-file read, network egress), stateful taint policy, deny by default,
   hash-chained audit log, an MCP interface. Reuse the file guard and approval logic.
3. **Evaluate B versus D**, publish the table with misses and false blocks.
4. **Usability test with one or two developers** using the documented setup; record prompts and setup time.
5. **Pilot** with a real small organization only after steps 1 to 4, and only with their permission.

## 13. Weaknesses, stated plainly

- The strongest differentiator (G3, session taint policy) is a hypothesis. If Claude Code's auto mode or a future
  release already covers it, the project has no defensible purpose.
- Claude Code changes fast: the documented gaps may already be closed. The docs snapshot was dated May 2026.
- The layer only protects operations that pass through it. The setup needed for a real guarantee (no credentials in
  the agent, no other network route) is exactly the setup a busy developer skips.
- Much of the "attack succeeds by default" story depends on permissive modes (`auto`, `bypassPermissions`,
  acceptEdits-style approval fatigue). That is realistic, but a reviewer may argue those users accepted the risk.
- One person, a short timeline. Breadth (many agents, a dashboard, MCP for everything) must be refused.
- Competitive coverage is incomplete: open-source MCP gateways were not reviewed.
- Fellowship fit is not known. I have not seen its criteria.

## 14. Decisions needed from the owner

1. Approve the one-week spike (section 12, step 0) with the kill criteria in section 9, written down first?
2. Approve that the headline comparison is **well-configured Claude Code versus Claude Code plus LocalAI** (B vs D)?
3. If the spike succeeds, approve changing the project's scope and the CLAUDE.md rules in section 11?

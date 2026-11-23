# Existing agent-security tools versus LocalAI: research and recommendation

Written for: the project owner, to decide whether LocalAI's security direction is worth pursuing.
Date: 2026-11-19. Status: **research only. No application code, config or existing design file was changed.**
Builds on: design/security-layer-assessment.md. Square work (design/connector-boundary.md) is preserved and paused.

## How to read this document

**What "verified" means here.** Each project was cloned into a scratch folder and its source was *read* by a research
agent. **Nothing was built, run or executed**, and no attack was tried. "Implemented and verified" below means "found in
the source code by reading it", not "tested". Claude Code's own code is not open, so its behavior rests on its
documentation. I did not read the source files myself; I am relaying the agents' reports with their file references.

Labels used in the table:
**Implemented and verified** (in source, read) · **Documented, not verified** · **Partially supported** ·
**Not supported** · **Unknown**.

Versions examined:

| Item | Version / commit | Date |
|---|---|---|
| Anthropic Sandbox Runtime `@anthropic-ai/sandbox-runtime` | v0.0.83, commit `0bbebed0aa9a8e628dc4df8bc30293550a1988eb`, Apache-2.0 | 2026-11-12 |
| Docker MCP Gateway | commit `4b5180c5ba8e1b456c53b36b7f90f17964131a16`, MIT | 2026-11-19 |
| IBM ContextForge `mcp-contextforge-gateway` | commit `13e878072800d2ae601f00f6d14c1d56b5241064`, Apache-2.0 | 2026-11-19 |
| Claude Code docs (code.claude.com/docs/en/) | pages cite versions up to v2.1.328; no page date. Installed CLI here is **2.1.296**, so some documented options may not exist locally | read 2026-11-19 |

Primary sources: [sandbox-runtime](https://github.com/anthropics/sandbox-runtime), [mcp-gateway](https://github.com/docker/mcp-gateway),
[mcp-context-forge](https://github.com/IBM/mcp-context-forge), Claude Code docs:
[sandboxing](https://code.claude.com/docs/en/sandboxing), [permissions](https://code.claude.com/docs/en/permissions),
[hooks](https://code.claude.com/docs/en/hooks), [mcp](https://code.claude.com/docs/en/mcp),
[settings](https://code.claude.com/docs/en/settings), [managed-settings](https://code.claude.com/docs/en/managed-settings),
[managed-mcp](https://code.claude.com/docs/en/managed-mcp).

## 1. Anthropic Sandbox Runtime (`srt`)

**What it is.** A command wrapper. It runs any command inside an OS sandbox, and child processes inherit it
(`src/cli.ts:567-585, 703-713`). Claude Code's built-in sandbox is built on this package (sandboxing docs).
**Self-described "Beta Research Preview"**, with Windows "alpha" (README lines 7-8, 1054-1064). No SECURITY.md.

**Verified in source:**
- **macOS:** a Seatbelt profile with `(deny default)` is generated and passed inline to `sandbox-exec`
  (`src/sandbox/macos-sandbox-utils.ts:1047-1400, 1591-1602`). Reads are allow-all-then-deny; writes are allow-only
  listed roots. Mandatory write-denies cover `.gitconfig`, `.bashrc`, `.zshrc`, `.mcp.json`, `.git` hooks,
  `.claude/commands` and similar (`src/sandbox/sandbox-utils.ts:21-52`). Move and rename tricks are blocked.
- **Linux:** bubblewrap with `--unshare-net`, `--unshare-pid`, `--unshare-user`, `--cap-drop ALL`
  (`src/sandbox/linux-sandbox-utils.ts:797-800, 3611, 3699, 3810-3833`). Root is `--ro-bind` with writable roots
  bound on top (line 2436, 2500). A seccomp helper (`vendor/seccomp-src/seccomp-unix-block.c`) blocks `AF_UNIX` and
  `AF_VSOCK` sockets, `io_uring`, and namespace/mount syscalls. The helper aborts rather than running without
  namespace isolation (`apply-seccomp.c:29-30`).
- **Network:** no direct route. Traffic goes through an HTTP and a SOCKS proxy on the host, bridged in by `socat` on
  Linux and by localhost-only Seatbelt rules on macOS. Domain deny is checked first, then allow, then an optional ask
  callback, otherwise deny (`src/sandbox/sandbox-manager.ts:774-870`). Resolved addresses are vetted before dialing, and
  loopback, link-local, metadata and the host's own addresses are refused (`src/sandbox/resolved-address-guard.ts`).
  UDP, raw sockets and non-proxy TCP cannot leave.
- **Credentials:** `credentials.files` and `credentials.envVars` accept `deny` or `mask` (`sandbox-config.ts:276-675`).
  Masking swaps a sentinel for the real value on egress to chosen hosts, but needs TLS termination
  (`network.tlsTerminate`, marked EXPERIMENTAL, line 940). File masking works on Linux only; macOS degrades to deny.
- **A policy hook point exists.** `filterRequest` is a per-request callback; there is "no policy language" (lines
  781-797). A standalone `srt proxy` with an external decider is described in `docs/srt-proxy.md` and
  `src/proxy-cli.ts`: **not read in detail**.
- **Violation logging:** macOS via `log stream` with per-command attribution; Linux via a seccomp notification observer,
  explicitly best-effort and not a full reproduction of what the sandbox permits.
- **Tests:** a test folder covers symlinks, path traversal, rename bypass, Unix sockets, `io_uring`, `ptrace`,
  `/proc/1/mem`, domain filtering and credential masking. **Not run by me.**

**Fail-open and weakening paths (verified in source):**
- A missing seccomp helper on Linux is a **warning only**: Unix-socket blocking, the PID-namespace layer and the
  namespace limit are then absent (`linux-sandbox-utils.ts:1333, 3624-3629`).
- The wrapper returns the command **unwrapped** when no network, read, write or env restriction is configured
  (`macos-sandbox-utils.ts:1477-1485`, `linux-sandbox-utils.ts:3584-3592`). `filesystem.disabled: true` removes all rules.
- The CLI with no settings file runs with built-in defaults: network fully blocked, but `denyRead` empty, so **reads
  are allowed machine-wide** (`src/cli.ts:395-398`).
- Initialization fails closed on missing `bwrap`, `socat`, `ripgrep` or an unsupported platform
  (`sandbox-manager.ts:1311-1332, 1894-1896`; `src/cli.ts:730-735`). No `failIfUnavailable` key exists in this package;
  that name belongs to Claude Code's settings.
- Risky options, each documented in the schema: `allowAllUnixSockets`, `allowUnixSockets` (a `docker.sock` entry is
  "effectively a sandbox escape", README line 1329), `allowLocalBinding`, `enableWeakerNestedSandbox` (exposes host
  `/proc`), `allowNestedUserNamespaces` (can remove the read-only binds), `allowAppleEvents`, `allowMachLookup: "*"`.
- **Stated limits:** domain-level filtering only, no traffic inspection by default; domain fronting may bypass it; a broad
  allowed domain such as `github.com` can carry data out (README lines 1321-1334). A known TODO: 32-bit x86
  `socketcall()` is not blocked (`seccomp-unix-block.c:11-30`). Linux `denyRead` globs expand at wrap time only.
  Passed-in socket file descriptors are not blocked (README line 1268).

**Does wrapping the whole Claude Code process put everything in one boundary?** By construction, **processes it
spawns inherit the sandbox** (verified for the wrapper). The Claude Code docs recommend exactly this: "run the Claude
Code process itself in a container, virtual machine, or the sandbox runtime" to put built-in file tools, hooks and local
MCP servers "behind one boundary". The built-in sandbox alone does **not**: Read, Edit, Write, WebFetch, WebSearch,
command hooks and stdio MCP servers run outside it (docs, "What runs outside the sandbox"). What still sits outside an
`srt`-wrapped session: the user's host and any process not launched through the wrapper; the model API connection
(the proxy must allow it, so it remains a channel); and any allowed domain.

## 2. Docker MCP Gateway

**What it is.** An MCP gateway that launches MCP servers as containers and routes tool calls to them.
Status (preview, supported or otherwise) is **not stated** in the repository. `docs/security.md` is a trust-model document.

**Verified in source:**
- **Every tool call passes a policy gate**, including the dynamic `mcp-exec` and `code-mode` paths, through a shared
  per-tool handler wrapper (`pkg/gateway/tool_schema_dialect.go:22-45`, `pkg/gateway/tool_policy.go:40-57`,
  `pkg/gateway/mcpexec.go:43-83`, `pkg/gateway/codemode.go:21-46`). It **denies if the policy check itself errors**.
  There is no single dispatcher function; the choke point is the wrapper.
- **But the policy engine is not in this repo.** The real engine is Docker Desktop's backend behind a feature flag. When
  that is off, the client is `NoopClient`, which **always allows** (`pkg/policy/policy.go:104-116`). Other controls: a
  per-server tool allowlist, and "interceptors" that run operator-supplied shell or Docker commands (trusted config).
- **Meta tools** (`mcp-add`, `mcp-exec`, `code-mode`, `mcp-config-set`) are only telemetry-wrapped, not invoke-gated;
  `mcp-add` is gated by a load policy (`pkg/gateway/dynamic_mcps.go:182, 256`). **Resources** have no policy check
  (`pkg/gateway/handlers.go:227-293`).
- **Container isolation** (`pkg/gateway/clientpool.go:324-454`): `--security-opt no-new-privileges`, `--cpus` (default 1),
  `--memory` (default 2Gb), image signature verification on by default, host bind mounts read-only and restricted to
  allowed roots (`pkg/gateway/docker_binds.go`). **Not found:** `--read-only`, `--cap-drop`, `--pids-limit`, seccomp, a
  default non-root user. Default network is the Docker bridge, so **egress is open**.
- **Network allowlist** per server exists but only applies with the separate `--block-network` flag (default off), and
  only to servers that declare allowed hosts (`clientpool.go:535`). The proxy implementations were **not read**.
- **Secrets:** injected per server as environment names with values in the process environment, not on the command line;
  not returned to the client in the paths read. Verbose mode logs the first four characters (`clientpool.go:384-386`).
- **Human approval: none found** in the gateway. Elicitation passthrough is a backend asking the user, not an approval gate.
- **Logs:** `log-calls` is on by default but records **tool name and argument shape only, no values or results**
  (`pkg/interceptors/log_calls.go`). Policy decisions go to Docker Desktop's audit API when active. These logs **cannot
  reconstruct what was done**. OpenTelemetry records names and durations; docs say nothing is exported externally without
  Docker Desktop.
- **Malicious servers or results:** the only content defence is `block-secrets` (on by default), which scans text for
  secret patterns. **No prompt-injection defence** (docs list it out of scope, `docs/security.md:170-172`). No response
  size limit found.
- **Listener:** stdio by default. For SSE and streaming, a bearer token is required unless `--allow-unauthenticated`,
  compared in constant time. The default bind host looks like **all interfaces**, plain HTTP, one token for all tools
  (`pkg/gateway/run.go:529-538`, `transport.go`).
- **If a backend server is compromised:** it gets whatever its container was granted. The docs say misuse of granted
  access is out of scope. Anything that can reach the containers directly (for example in Static mode) bypasses the
  gateway; **inferred, not verified**.

## 3. IBM ContextForge

**What it is.** A Python MCP/REST/agent gateway and registry with RBAC, federation and a plugin framework. Its own
SECURITY.md says: open source "as-is", **no official IBM support**, "General Beta Limitations", "not a standalone
product", REST API "designed to be accessed by internal services in a trusted environment", Admin UI "development
conveniences" to be disabled in production (`SECURITY.md:5-34, 58, 725-736`).

**Verified in source:**
- **AuthN:** JWT (HS256 default), basic auth, API tokens, optional SSO. `auth_required` defaults true, but defaults
  include admin and basic-auth password **"changeme"** and placeholder secrets that only raise an error when the environment is
  `production` (`mcpgateway/config.py:300-313, 674-677`; `main.py:2030-2038`). Auth can be switched off with only a warning.
- **AuthZ on every invocation:** endpoint permission (`tools.execute`), token scope and a visibility check (public, team,
  private) in the tool-invoke path (`main.py:9226, 9488`; `services/tool_service.py:1550-1620, 5589-5700`). Tokens can be
  restricted by server, IP/CIDR, time window and usage. **Permissions are action categories, not per-tool names.**
- **No execution isolation.** It routes. The one subprocess launcher is the `translate` stdio wrapper, which runs with the
  gateway's environment and no sandboxing (`mcpgateway/translate.py:416-423`). STDIO gateways are rejected in the API schema.
- **SSRF protection for registered REST tools** is on by default (metadata, link-local, localhost and RFC 1918 blocked,
  connection pinned to the resolved IP; `config.py:775-822`, `tool_service.py:6200-6238`).
- **Plugins:** many guardrails exist (PII, secrets detection, deny lists, rate limit, output length, a policy decision point
  plugin) with pre- and post-invoke hooks, but **nearly all ship disabled**, `fail_on_plugin_error: false`, and a plugin
  *error* is treated as an outage, not a denial (`plugins/config.yaml:13`; `tool_service.py:7416-7424`). The engine is an
  external package (`cpex`) that was **not read**.
- **Tool results:** schema validation only; **no built-in injection handling** in the core path.
- **Audit:** `audit_trail_enabled` defaults **false**, and it logs management actions, not invocations. Invocation logging
  records argument **keys, not values**; OpenTelemetry spans and metrics exist. Reconstruction would need payload logging,
  the audit trail and observability all enabled (unverified).
- **Bypass routes:** upstream servers are not protected; a client that reaches them directly skips all policy (architectural).
  `/health` and `/ready` are unauthenticated; WebSocket and SSE handler auth were not verified.

## 4. Claude Code, re-checked against current official docs

(Documentation only; its code is not open. Pages cite up to v2.1.328.)

| Question | What the docs say |
|---|---|
| Sandbox on by default? | **No.** "The sandbox is off by default." ([sandboxing](https://code.claude.com/docs/en/sandboxing#what-the-sandbox-restricts)) |
| Covers | Shell commands (Bash, PowerShell, Monitor) and their children; Seatbelt on macOS, bubblewrap on Linux/WSL2. Native Windows runs unsandboxed |
| Outside it | Read, Edit, Write, WebFetch, WebSearch (permission rules only); command hooks; local stdio MCP servers; plugin monitors; status-line and `apiKeyHelper` commands; mods; `!`-typed commands; excluded commands and unsandboxed retries |
| Whole-process boundary | The docs recommend running the Claude Code process itself in a container, VM or the sandbox runtime |
| Defaults | Writes: working directory plus temp. **Reads: whole machine**, including `~/.ssh` and `~/.aws/credentials` unless denied; "There is no built-in credential deny list." Allowed domains start empty |
| Sandbox cannot start | **Runs commands unsandboxed by default**; `sandbox.failIfUnavailable: true` makes it exit. `allowUnsandboxedCommands: false` disables the `dangerouslyDisableSandbox` retry. The retry is auto-approved in `bypassPermissions` and by a matching allow rule |
| Permission rules | Deny, then ask, then allow; deny wins. Read/Edit deny rules cover built-in file tools plus recognized `cat`/`head`/`tail`/`sed`/`tee` and redirects. They **do not** cover `grep -r .` or a Python or Node script that opens files itself. A Bash rule "isn't a security boundary around the program" |
| Hooks | PreToolUse runs before every tool call (built-in, Bash, MCP, subagent). Exit 2 or `permissionDecision: deny` blocks. Any other non-zero exit, bad JSON or a timeout **lets the call proceed**, unless the handler sets `onFailure: "block"` (v2.1.295+; the `mcp_tool` variant v2.1.328+). Validation-rejected calls fire neither PreToolUse nor failure hooks. PostToolUse cannot undo. `http` hooks can POST each event to an external service. "Claude can still change the protected files with shell commands" |
| MCP | stdio servers are local processes; HTTP recommended for remote. Rules named `mcp__<server>__<tool>`. `managed-mcp.json` gives exclusive control; denylists always win; server name is not a security control |
| Managed settings | Cannot be overridden by user, project or `--settings`. Can lock the sandbox, block bypass and auto modes, allow only managed hooks and MCP servers. macOS delivery: MDM profile, or `/Library/Application Support/ClaudeCode/managed-settings.json` (writing it needs admin rights: **inferred**), or server-managed via an organization login. They bind Claude Code only |
| Stated non-guarantees | "Sandboxing reduces risk but is not a complete isolation boundary." Broad domains such as `github.com` "can create paths for data exfiltration." |

**Unconfirmed after this re-check:** the `sandbox-environments#sandbox-runtime` page was not read; the exit-127 hook case
(not stated explicitly; the generic non-blocking rule should cover it); whether the agent can edit `.claude/settings.json`
or hook scripts in default mode; where stdio MCP servers run relative to the sandbox beyond the "outside" statement.

## 5. Comparison

Legend: **IV** Implemented and verified (read in source, not run) · **DD** Documented, not verified · **PS** Partially
supported · **NS** Not supported · **UK** Unknown. The LocalAI column describes LocalAI as it exists today, *as a control
over an external agent*.

| Capability | Claude Code built-in sandbox | Anthropic Sandbox Runtime | Docker MCP Gateway | IBM ContextForge | LocalAI (today) |
|---|---|---|---|---|---|
| OS-level enforcement | **DD** (built on the runtime; shell commands only; opt-in) | **IV** Seatbelt, bubblewrap, seccomp; mostly fail-closed | **PS** container flags for MCP servers only (no-new-privileges, CPU, memory); no `--read-only`/`--cap-drop` found | **NS** routes only | **NS** for an external agent. Own app container is hardened (read-only fs, caps dropped) |
| Filesystem restrictions | **PS** writes limited to project; reads machine-wide by default | **IV** allow/deny, mandatory denies, rename and symlink handling; read-all unless configured | **PS** read-only bind mounts under allowed roots | **NS** | **PS** `_safe_path` for `docs/`, in-process, own tools only |
| Network restrictions | **PS** shell only; domain allowlist via proxy; WebFetch not covered | **IV** deny-by-default domain proxy, resolved-address guard; domain-level only, exfil via allowed domains possible | **PS** open by default; per-server allow-hosts only with `--block-network`; proxies **UK** | **PS** SSRF guard for registered REST tools; no agent egress control | **NS** container egress open |
| MCP tool authorization | **DD** `mcp__server__tool` rules, managed allow and deny lists | **NS** not MCP-aware | **IV** per-call invoke gate, fail-closed on engine error; default allows all; real engine closed | **IV** per-call RBAC and visibility; categories not per-tool | **NS** external; fixed in-app registry |
| Shell/process control | **PS** rules are advisory; sandbox covers children; retry escape hatch | **IV** wraps any command; children inherit | **NS** interceptors run operator commands unsandboxed | **NS** | **NS** (no shell, by design) |
| Human approval | **DD** modes and ask rules | **PS** optional ask callback for network | **NS** none found | **UK** none found | **IV** in-app writes need UI approval; none for external agents |
| Credential isolation | **PS** reads `~/.ssh` by default; masking optional | **IV** deny and mask (mask needs experimental TLS termination; Linux file masking only) | **PS** per-server injection, not returned to client | **PS** encrypted at rest; placeholder key outside production | **NS** (Square token design exists on paper only) |
| Audit logging | **PS** via hooks, user-built | **PS** violation monitor, best-effort | **PS** names and shapes only; cannot reconstruct | **PS** off by default; keys not values | **PS** lengths only; rotation drops history; not tamper-evident |
| Bypass resistance | **PS** opt-in, fails open by default, retry hatch; managed settings can lock | **PS** OS-enforced but beta; seccomp-helper fail-open; domain fronting; weakening flags | **PS/UK** direct container access and proxies unverified | **NS** clients can reach upstream directly | **NS** against an external agent |

## 6. Blunt answers

**1. Does LocalAI still solve a meaningful problem given the Sandbox Runtime?**
Not the problem of sandboxing. `srt` does OS-level isolation properly, with a Seatbelt profile, bubblewrap, seccomp, a
domain proxy and credential masking, and much of it is covered by its own test suite (which I did not run). Building
another sandbox would be redundant. Any remaining value is in what sits *above* it.

**2. Would integrating or extending Anthropic's runtime be more sensible than another sandbox?**
Yes. Wrap the agent with `srt` and put your logic at its decision points. The runtime is agent-agnostic (it wraps any
command), so it is also the only thing in this survey that could make a layer portable across agents.

**3. What is missing from the four existing solutions?**
Things I did not find in any of them (a gap in *these four*, not proof nobody has built it):
- **A deterministic, session-aware policy**: decisions that depend on what the agent already did (for example "after
  untrusted content was read, deny new egress"). Docker's gate and ContextForge's RBAC are per-call and stateless
  as read; Claude Code's rules are per-call; `srt` has only a request callback and no policy language.
- **One policy and one record across channels** (file reads, web fetches, shell, MCP). Gateways see MCP only; `srt`
  sees network and file operations of a process, not tool intent; Claude Code sees tool calls but its sandbox sees
  only shell.
- **A tamper-evident audit record that can reconstruct actions.** Every project logged shapes or keys, not values.
- **Secure-by-default setup and a way to verify it.** Claude Code's sandbox is off by default, fails open by default,
  and reads `~/.ssh` by default; `srt` runs unwrapped with no restrictions configured.
- **A public measurement of how often a given configuration actually stops attacks.** Not found; **I did not search
  for academic or industry benchmarks**, so I cannot say none exist.

**4. Could LocalAI be a useful independent policy, approval or audit layer across agents?**
Plausibly. A decision service the sandbox's request callback (or `srt proxy`'s external decider) consults, plus a
hash-chained audit record, would be agent-independent. **Open engineering questions:** how session state (what was read)
reaches the decider across the boundary, given that on Linux the seccomp helper blocks all Unix sockets and on macOS
sockets must be listed; whether `filterRequest` is usable without TLS termination; and whether hooks running inside the
wrapped process can be trusted to report state.

**5. Would it enforce anything the existing tools cannot?**
Only in combination, and the sandbox does the enforcing: the layer decides, `srt` blocks. That is a real guarantee **if**
the agent truly has no other route, but it is **a hypothesis, not a result**. Claude Code's `auto` mode already runs a
classifier on actions; whether a deterministic rule adds protection beyond it is untested.

**6. What is the smallest technically credible prototype?**
No broker and no gateway. A scripted (non-LLM) process run under `srt` with a fake `.env` and a local sink, in three
configurations: (a) `srt` with a typical allowlist; (b) the same with only the sink's domain allowed to show the known
exfiltration route; (c) the same with a small decision service that denies egress after a "tainted" event. Success means
(b) delivers the canary to the sink, (c) does not, and a set of legitimate tasks still works in (c). Before that, read
`docs/srt-proxy.md` and `src/proxy-cli.ts` to confirm the decider interface exists as described.

**7. Is this too crowded or redundant to pursue?**
- **Sandbox layer:** yes, crowded and well served. Do not build it.
- **MCP gateway layer:** yes, crowded (Docker, ContextForge, and others I did not review). Do not build it.
- **Policy-over-sandbox plus a published evaluation:** appears **open in what I surveyed**, but the survey is four
  projects plus NeMo Guardrails (read earlier) and the Claude Code docs. It is unproven that it adds protection and I
  can only call it "uncrowded as far as I looked".

## 7. What this means for the earlier plan

The earlier "execution broker" plan duplicated more than it needed to. Revised:
- **Drop:** building any sandbox, container runner, file-isolation layer or MCP gateway.
- **Keep:** the attack evaluation (it is the most defensible deliverable), the audit record, and the stateful policy idea.
- **Add:** a secure-by-default `srt` preset plus a verifier that checks the configuration actually blocks canary theft.
- **Existing LocalAI parts that remain useful:** the approval flow, untrusted-text wrapping, file-guard logic and
  tests, the eval-harness style. The Streamlit app and the local-model agents are not part of this claim.

## 8. Limits of this research

- Everything was read by agents; I did not read the source files myself, and **no code from any project was built or run**.
- Unread areas: `docs/srt-proxy.md` and `src/proxy-cli.ts`; Docker's proxy implementations, `pkg/codemode` (what the
  JavaScript VM can reach), and signature-check coverage on every pull path; ContextForge's `cpex` engine, WebSocket and SSE
  authorization, and payload logging; the Claude Code `sandbox-environments` page.
- Claude Code documentation has no dates, and its pages mention versions newer than the installed CLI (2.1.296).
- The competitor set is small. NeMo Guardrails was read earlier; other MCP gateways and academic work were not surveyed.
- A repo's own claims (for example ContextForge's scanner and pen-test statements) were not verified.

## 9. Recommendation

**Pivot to an integration-focused security layer built on existing tools, gated by a one-week spike, with an
evaluation-first fallback.** Do **not** continue the earlier plan as written (it would rebuild sandboxing and gateway
functions that exist), and do **not** abandon the direction yet: the gap I found (session-aware policy across channels, a
tamper-evident record, safe defaults, and published measurements) is narrow and unproven, not absent.

Concretely:
1. **Spike (about one week):** the three-configuration experiment in answer 6, plus the baseline attacks against Claude
   Code's default and well-configured setups. Update Claude Code first so the documented options (such as `onFailure`) exist.
2. **Decision gate with pre-written kill criteria:** if a well-configured Claude Code or `srt` already stops every attack the
   layer would stop, or the layer cannot be set up in about 15 minutes, **stop and take the evaluation harness alone as the
   project**: a reproducible attack suite and a published comparison of agent-sandbox configurations, including misses.
3. If the gate passes, build only the decision service and audit chain. Build no sandbox and no gateway.

If the spike shows no incremental protection and nobody would use an evaluation-only tool, the honest conclusion is that
this direction is redundant and the Square assistant or another idea is the better use of time.

Changing the project's rules (CLAUDE.md currently forbids shell access and restricts file tools to `docs/`) is not needed
for the spike if it runs in a scratch folder, but **would be needed** before any product code, and requires your approval.

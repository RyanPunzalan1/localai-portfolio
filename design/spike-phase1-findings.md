# Spike, Phase 1: can Sandbox Runtime tell LocalAI what an agent read, and block its network afterwards?

Written for: the project owner, to decide whether Phase 2 can proceed as defined.
Date: 2026-11-19. Status: **Phase 1 only (read-only inspection). Nothing was built or run. Phase 2 has not started.**
Follows: design/security-landscape-research.md. Boundaries from the approval were kept: no application, config or
`app.py` changes, no real data, no Docker socket, nothing from the cloned repo was executed.

Source examined (read by me directly this time): `anthropics/sandbox-runtime` v0.0.83, commit
`0bbebed0aa9a8e628dc4df8bc30293550a1988eb`, in a scratch clone. Files read: `docs/srt-proxy.md`, `src/proxy-cli.ts`,
`src/sandbox/decider-client.ts` (header), `src/sandbox/request-filter.ts` (top), `src/sandbox/http-proxy.ts` (option
comments), `src/sandbox/linux-violation-monitor.ts` (top), `src/sandbox/sandbox-violation-store.ts` (top),
`src/sandbox/sandbox-config.ts` (network keys), `src/cli.ts` (options), and greps of `macos-sandbox-utils.ts` and
`vendor/seccomp-src/apply-seccomp.c`. Not read in full: the 4,114-line `sandbox-manager.ts`, `http-proxy.ts` beyond the
option comments, `tls-terminate-proxy.ts`. "Verified" below means found in source or its docs by reading, not run.

## Headline

**The premise of the spike is not met.** Sandbox Runtime has **no interface that reports filesystem reads** to anything,
so it cannot tell a decision service that an agent read an untrusted file. It *can* make a synchronous, fail-closed
allow/deny decision on every outbound HTTP request, so the *enforcement* half of the idea works. The *visibility* half must
come from somewhere else, and the alternatives have real coverage gaps (answers 1, 2 and 5).

Under your own rule ("If the runtime cannot expose the necessary events or enforce the decision, document that limitation
before attempting a workaround"), I stopped here. By the kill criteria as written ("the runtime cannot expose the required
events"), **the first kill criterion is triggered for the original design.** A redesign is possible but is a different
hypothesis, so it needs your approval and is not a silent workaround.

## Answers to the six questions

**1. Can the runtime reliably expose filesystem-read events to an external decision service? No.**
- macOS: the Seatbelt profile is `(deny default)` with a blanket `(allow file-read*)` and denies layered on top
  (`macos-sandbox-utils.ts:1083, 884-964`). The log monitor reports **denials** (`log stream` on the profile's tag,
  `startMacOSSandboxLogMonitor`). A permitted read produces no event.
- Linux: the `apply-seccomp` observer traps **write-intent** syscalls only (`apply-seccomp.c:107-121`, "traps write-intent
  filesystem syscalls"), and `linux-violation-monitor.ts` reports "write-intent syscall" attempts. Its own header says
  the reported path is read from the untrusted process's memory, is "ATTACKER-CONTROLLED and racy", and that these events
  "are diagnostic hints and must never gate a policy decision."
- The violation store is an in-memory tail of 100 events (`sandbox-violation-store.ts`), not a decision channel.
- The decider protocol carries **requests only** (`docs/srt-proxy.md`, "Requests and verdicts"); there is no read message.
- Could we *make* a read observable by denying it? That blocks the read, so it is not a taint signal.

**2. Can the service distinguish trusted and untrusted file reads? Not applicable, as no read events exist.**
Classification would need an outside event source (answer 5). Path-based trust (for example "files under `~/project/vendor`
are untrusted") would have to be decided by whatever reports the read.

**3. Can events be associated with the correct agent process or session? Network: yes by construction. Reads: no events.**
- A `req` frame carries `id`, `method`, `host`, `port`, `hostHeader`, `sni`, `path`, `query`, `headers` and nothing about
  a process or session. The docs say the proxy "serves a single sandboxed client", so association is **one proxy and one
  decider per agent session**, started by whoever launches the session. That works but must be built and tested.
- Within one session the decider cannot tell which child process made a request, which is fine for a session-wide policy.
- In library mode the proxy username carries an `encodedCommand` attribution for the denial store. The sandboxed process can
  see its own proxy URL, so I would **not** treat that as unforgeable. Unverified.

**4. Can the service synchronously deny a network request before the connection is established? Yes (verified in docs and source comments).**
- "Nothing is dialled before a verdict": the proxy resolves and connects only after an allow; a deny, refusal, timeout or
  malformed request leaves "no DNS query and no connection" (`docs/srt-proxy.md`, "Security model").
- **Fail closed:** a request is forwarded only on a well-formed allow in time; the proxy's timer is 5 seconds, then 503
  `decider_unavailable`; a decider that dies or breaks protocol makes the proxy exit and every pending request fails.
- The decider can ask for the request body once (`need_body`, up to 32 MiB) before deciding.
- **Costs of this visibility:**
  - Request-level visibility (method, path, query, body) exists only for plain HTTP or **TLS-terminated** HTTPS, so the
    proxy impersonates servers with its own CA and the agent's clients must trust it. Clients that pin certificates break
    (`http-proxy.ts` `shouldTerminateTLS` comment names mTLS and cert-pinning clients).
  - In `srt proxy` (proxy-only) mode, **every CONNECT is TLS-terminated and opaque tunnels are refused**, so the decider would
    see the agent's own model-API traffic, including prompts and authorization headers. In library mode a host can opt
    specific hosts out of termination (then the decider cannot see them) and can set `refuseOpaqueTunnels`.
  - Without a CA in proxy-only mode, every CONNECT is refused.

**5. Can the policy be enforced without the agent voluntarily calling LocalAI? Network enforcement: yes. The taint signal: partly, and only with outside help.**
- *Enforcement:* the sandbox leaves the process no route except the proxy (network namespace on Linux, localhost-only
  Seatbelt rules on macOS), so the agent does not choose to consult it.
- *But only for what is inside the wrapper.* Claude Code's built-in sandbox covers only shell commands; Read, Edit, Write,
  WebFetch, WebSearch, hooks and stdio MCP servers run outside it (Claude Code sandboxing docs). The docs' remedy is running the
  whole Claude Code process inside a container, VM or the runtime. A per-request decider has no effect on WebFetch unless the
  whole process is wrapped.
- *How the decider is attached:* `srt`'s wrapping CLI takes only a JSON settings file and `filterRequest` "must be a
  function" (`sandbox-config.ts:781-783`), so **the wrap CLI cannot take a decider**. A decider is attachable (a) by
  embedding the library in a small Node host program that sets `network.filterRequest`, or (b) by running `srt proxy` and
  pointing a separate sandbox at it. The schema has `network.httpProxyPort` and `socksProxyPort` for an external proxy
  ("The external proxy must handle domain filtering", `sandbox-config.ts:760-775`). Whether Claude Code's own sandbox can be
  pointed at an external proxy that way is **unconfirmed**.
- *Where the "agent read something untrusted" signal can come from:*
  - **S1, network-derived:** any request the decider allows to a host outside a trusted set implies content may flow in.
    This signal is **fully observable in the decider** and needs no read events. It covers web-borne injection only.
  - **S2, Claude Code hooks:** documented to fire for Read, Grep, Glob, Bash, MCP and WebFetch tool calls, including subagents.
    They cannot see a file read by a subprocess (a Python or Node script, or a shell tool opening files itself); they fail open
    unless the handler sets `onFailure: "block"` (v2.1.295+); and "Claude can still change the protected files with shell
    commands". An in-band way to deliver a hook's taint event is to have the hook make an HTTP request to a reserved host
    through the proxy; the decider treats it as a taint event and answers with a deny status. This is a design idea, **not tested**.
  - **S3, file-borne reads by subprocesses:** no source. This is the largest gap.
- A taint signal that can only *tighten* policy (no "untaint" message exists) cannot be used by the agent to loosen it.

**6. Can alternate execution paths bypass the policy? Several exist; none were tested.** From source and docs:
- The model-API connection must stay allowed, so it is an exfiltration channel the policy cannot close.
- Hosts opted out of TLS termination or tunnelled opaquely are invisible to the decider.
- Allowed domains remain usable for data egress (documented), for example through a request body, a path or a query string.
- Unix sockets (macOS `allowUnixSockets`; Linux seccomp blocks `AF_UNIX`), `allowLocalBinding`, inherited or passed file
  descriptors (README line 1268), and the weakening flags `enableWeakerNestedSandbox`, `allowNestedUserNamespaces`,
  `allowAppleEvents`.
- Any tool outside the wrapper (see answer 5).
- Missing seccomp helper on Linux is a warning only (found earlier at `linux-sandbox-utils.ts:1333, 3624-3629`).
- Fail-open at wrapper level when no restriction is configured (found earlier).

## What this means for the stateful-policy idea

- The idea as stated ("deny network after an untrusted **file read**") cannot be driven by the runtime. It depends on an
  external signal that is incomplete for the cases that matter most (an injected document on disk, read by a script).
- A narrower, more defensible policy is visible to the decider alone: **after untrusted input is seen, restrict network to
  read-only** (allow `GET` and `HEAD`, deny writes), using the method and path the decider already sees. Package installs and
  clones keep working; uploads, gist creation and pushes stop. Open questions: git smart-HTTP uses `POST` for fetch as well as
  push (`git-upload-pack` versus `git-receive-pack`, which the path can distinguish); data can still leave in a `GET` query
  string; and the whole thing needs TLS termination to work with real tooling. This is a **hypothesis**.
- **Honest necessity concern:** a static, restrictive allowlist already stops exfiltration without any state. A stateful rule
  earns its keep only for workflows that need broad network access first and then handle untrusted input. If a well-configured
  `srt` or Claude Code makes that rare, the policy layer is redundant (kill criterion 4).

## Options for Phase 2 (a design decision for you)

- **A. Redefine the hypothesis.** Test "after untrusted input, network becomes read-only", with taint coming from S1 (network)
  and S2 (Claude Code hooks). Measure the coverage gap (S3) openly instead of assuming it away. Requires wrapping the whole
  agent process and a small Node host using the library. Needs Claude Code compatible with TLS termination (**untested**).
- **B. Stop here and take the evaluation harness as the project.** The kill criterion for missing events is triggered; the
  attack suite and the published comparison of configurations does not depend on the decider.
- **C. A split.** Run Phase 2 with the taint event *injected by the test* (a scripted stand-in for a perfect hook) to learn
  whether the decision service and the enforcement work and block before the canary reaches the sink. Report the signal's
  coverage separately. This answers "does enforcement work?" but does **not** show the whole system works, and it will be
  reported that way.

My recommendation: **C, then decide between A and B.** It is cheap, answers the enforcement question honestly, and avoids
building a full agent integration before knowing whether the signal is good enough.

## Not verified in Phase 1

- Nothing was executed; no proxy, decider or sandbox was started.
- `tls-terminate-proxy.ts`, most of `http-proxy.ts` and `sandbox-manager.ts` were not read.
- Whether Claude Code works behind a TLS-terminating proxy and an extra CA, and whether it can use an external proxy port.
- Whether `filterRequest` plus a hook-driven taint event behaves as sketched.
- Whether Seatbelt reports nothing at all for allowed reads on this macOS version (inferred from the profile and monitor code).
- The unforgeability of the per-command attribution in the proxy username.

## One incident, for the record

One `wc` command I issued with a relative path was blocked by the project's deny rule because it resolved to this project's
private `docs/` folder. I did not access it; I re-read the scratch clone's `docs/srt-proxy.md` by its full path instead.

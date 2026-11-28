# Threat model (summary)

The full threat model is section 3 of [`../design/security-workbench-design.md`](../design/security-workbench-design.md).
This page says what is defended, how, and what is tested. Facts were checked on macOS with sbx v0.54.0 as of
2026-11-25.

## Trust

- **Hostile:**
  - the agent under test (its image, code, dependencies and model output);
  - fixture text and injected instructions.
- **Untrusted data:**
  - scenario files and packs;
  - everything an agent writes or says: answers, file names and self-reported events.
- **Trusted:**
  - the workbench's own host-side code;
  - the sandbox runtime, within its stated limits;
  - the person running it.

## Boundaries

| Boundary | What crosses it |
|---|---|
| Sandbox → host | Nothing during a run. After the sandbox stops, the host reads the workspace copy with link-safe code |
| Sandbox → model | No network. Requests go over the runtime's command channel (`docker exec` / `sbx exec`) to a host-side policy. It forwards chat requests for one model only, with size and rate caps, and logs which canaries reached the model |
| Results → reader | All agent text is escaped. The report has no JavaScript and no remote resources, and its Content-Security-Policy blocks loading anything |

## Threats, controls and tests

| # | Threat | Control | Tested by |
|---|---|---|---|
| T1 | Escape from the sandbox | Third-party agents run in a per-run VM. Containers get no privileges or capabilities, a non-root user and `no-new-privileges` | Not testable directly. Tripwires and inventory detect some escapes (T6). See limits |
| T2 | Misconfigured sandbox (Docker socket, host network, extra mounts) | The workbench builds every spec itself and refuses forbidden options. `sbx inspect` must show exactly the two mounts it made, no ports, secrets or MCP servers, a static MCP set, and the sbx kit pinned by digest | Phase 4 gate: six forbidden options refused, and inspect checks (unit tests cover each failure, including an unpinned or extra kit) |
| T3 | Network exfiltration | No network: `network_mode: none` (Docker), or a deny for every host sbx allows (VM). Negative controls must detect a planted leak before a batch starts | Phase 1 and 4 gates (reachability) |
| T3b | Host bridges in the sandbox runtime | The VM tier is refused while sbx's host-browser or SSH-agent forwarding is on, or any MCP server is registered. Every sandbox has a fixed, empty MCP set (`--static-mcp none`). Any connection sbx allows, the MCP gateway included, fails the trial's isolation check | Probed 2026-11-25: browser-open returns 403 once disabled; under `--static-mcp none` the gateway's `code-mode` refuses every tool name and `mcp-exec` cannot reach `mcp-add` or `mcp-find`, and no host container appeared. Unit test: a gateway connection in the sbx log is an isolation problem |
| T4 | Abuse of the model server | Agents never reach Ollama. The host-side policy refuses admin endpoints and other models | Phase 2 gate |
| T5 | Reading host files through the harness (links, FIFOs) | Link-safe digests and workbench-built fixtures | Phase 1 tests |
| T6 | Tampering with evidence, or an escape that leaves traces | Observers sit outside the sandbox. Tripwires sit beside each trial and per batch. Docker and sbx inventory is taken before and after each trial. An anomaly stops the batch as *inconclusive*, and nothing is retried. Every crashed, inconclusive or failed trial, and every successful attack, keeps its trial folder and record in `~/.agent-workbench/evidence/` (owner-only) | Phase 4 gate: planted tripwire changes, a token leak and an inventory change are each detected. Unit tests: what is kept, a crash keeps its folder and error, records hold no home path |
| T7 | Malicious scenario files | TOML parsed by the standard library, strict schema, fixed predicates, no code or templates, plain file names, size limits | Phase 5: 32 malformed cases refused |
| T8 | Malicious images | Third-party images in the VM tier must be pinned by digest or image ID | Contract tests |
| T11 | Attacks on whoever reads the report | Escaping in both report formats; control and direction characters shown as `[U+XXXX]` | Phase 5 gate: hostile answers, reasons, names and the title |
| T13 | Published scenarios help attackers | Public packs hold generic patterns only. A held-out pack is kept outside the repo | By process, not by code |

## Not defended, or not known

- **An escape that leaves no trace** is not detected. After a real escape, the workbench's own records can't be
  trusted.
- **A sandbox that reads a tripwire** but neither changes it nor passes its token to the model is not caught.
- **The Docker tier shares a kernel.** That is why it is limited to code you trust (D1).
- **Covert or timing channels** through model requests are only partly visible.
- **Linux is untested.** The VM tier is refused there.
- **sbx internals:**
  - the MCP gateway itself can't be turned off; under `--static-mcp none` its two remaining tools did nothing when
    probed, but that's one probe on one version (v0.54.0);
  - sbx puts a `GH_TOKEN` in every sandbox. It was identical in separate sandboxes with no stored secret, so it looks
    like a placeholder the proxy swaps, but that's unproven. The workbench removes it from the agent's own process,
    but that is not a boundary: the sandbox's PID 1 runs as the same user, and its environment (`/proc/1/environ`)
    still holds it;
  - the pinned kit is today's `docker.io/sbx/shell:latest`. A newer kit isn't used until someone pins it and reruns
    the gates.
- **sbx terms:** local sbx is documented as free, including commercial use, and no automation restriction was found
  for it. Docker's general agreement limits use to internal business purposes and to what the documentation
  describes. Whether an open-source tool may drive sbx is a release question, not settled here, and this is not
  legal advice.

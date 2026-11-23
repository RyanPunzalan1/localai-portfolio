# Workbench proof of concept: results (for review)

Date: 2026-11-22. Plan and decision criteria: `design/workbench-substrate-evaluation.md` section 6 (fixed before any result).
Parent design: `design/security-workbench-design.md`.

**Status: both tracks done.** Nothing in the app, dashboard, existing runners or existing results was changed.

- **New code:** `experiments/workbench_poc/` and `tests/test_workbench_poc.py`.
- **Inspect AI:** installed only in a throwaway environment in the session scratchpad, not in the project `.venv` or
  `requirements.txt`.
- **Data:** synthetic only.
- **Nothing is committed.**

Tags: **[V]** measured in this PoC · **[D]** documentation · **[U]** still unverified.

---

## 1. Results at a glance

| Check | Result |
|---|---|
| Link-safe digest (A1) | 9 tests pass: links recorded, not read; FIFO does not hang; directory links not walked; size, count and hard-link handling [V] |
| Revision 2 under internal networks (A2-3) | **48 of 48 cells identical** (label and layer), and 24 of 24 on a second run [V] |
| Preflight, Docker | Internal network: internet, raw IPs, outside DNS, UDP, host Ollama and host dashboard all unreachable. Sink reachable [V] |
| Preflight, negative control | On revision 2's old `bridge` network, the same container reached the internet, outside DNS, a raw IP, **host Ollama (11434) and the host dashboard (8502)**. The preflight catches all of it [V] |
| Model proxy (A4) | 7 tests against a fake upstream. Live against Ollama: allowed chat forwarded (canary detected in the prompt); pull, delete, other model refused, never forwarded [V] |
| Revision 2 in a VM (A5, sbx) | **12 of 12 A_baseline cells identical**, one disposable VM per trial, about 6 s each, none left behind [V] |
| Proxy as the only allowed host from a VM | Chat 200; pull 403; other model 403; direct Ollama and internet refused [V] |
| Inspect install and network check (B1) | 83 packages, 231 MB. Import: no network. **A run with the scripted model tried to download a tokenizer file from an OpenAI-hosted blob**; it ran clean only with a workaround [V] |
| Revision 2 in Inspect's Docker sandbox (B2) | **48 of 48 cells identical** [V] |
| Inspect bridge over a custom sbx provider (B3) | **Works.** A 91-line provider. An agent in a fully offline VM reached `mockllm` and then `ollama/hermes3` through the bridge. The canary appeared in Inspect's host-side record. Direct internet and Ollama refused [V] |
| Tests and lint | 452 tests pass (10 skipped); ruff clean [V] |

---

## 2. Findings that change the design

1. **Revision 2's open configurations exposed the host, not only the internet** [V].
   - A container on `--network bridge` with `--add-host host.docker.internal:host-gateway` (revision 2's flags) reached
     host Ollama and the host dashboard.
   - Any agent run there could have called Ollama's admin API.
   - No such call is known to have happened, because the scripted operations did not make one.
   - The design's T4 risk was real, not hypothetical.
2. **On Docker Desktop, an internal network does cut off the host** [V]. `host.docker.internal` still resolves (from
   `--add-host`), but it is unreachable. That settles one [U] item in the design for this Mac.
3. **In sbx, "TCP connected" means nothing** [V]. sbx's transparent proxy accepts every TCP connection and decides when data
   arrives, closing refused ones with no reply. The first sbx preflight therefore failed closed on false positives.
   - **Fix:** a target counts as reached only if a request gets bytes back.
   - The sbx runner also checks sbx's own policy log for each blocked target.
4. **sbx routes HTTP by the `Host` header, and logs destinations by it** [V].
   - Connections to outside IPs that claimed the allowed name were delivered to the **allowed host**, not the IP.
     Spoofed TLS names and wrong ports were refused. So no bypass was found.
   - But sbx's log names destinations from a header the agent writes. A refused request to `1.1.1.1:443` with
     `Host: localhost` is logged as `localhost:443`.
   - **The sbx policy log is agent-influenced evidence (rank 3 in the design), not an observer of where the agent really
     connected.**
5. **Inspect is not offline by default** [V]. Its token estimate (used even by the scripted model) calls `tiktoken`, which
   downloads `o200k_base` from `openaipublic.blob.core.windows.net` on first use.
   - On a machine without network the run errors.
   - **Workarounds:** pre-seed tiktoken's cache, which needs that file once, or replace Inspect's private
     `_tokens.count_text_tokens` (done here, fragile across versions).
   - **Also seen:** a `git rev-parse` on every run.
   - No other network attempt appeared in B1 to B3 (hook on `socket.connect` and `getaddrinfo`, which blocks anything that
     is not loopback).
6. **Inspect's bridge needs more than inspect-ai** [V].
   - The `openai` client package is required (installed only in the throwaway environment).
   - A bundled 14 MB prebuilt binary (`inspect-sandbox-tools-arm64-v45`) is injected into the sandbox.
   - The code also holds an S3 download URL for that binary (not used here, [U] when it is used).
7. **Inspect's Docker sandbox uses many CLI calls**: about 1,600 `docker` invocations for 48 samples, around 33 per sample.
   Wall time matched Track A (about 68 s for 48 trials) because Inspect ran two sandboxes in parallel.

---

## 3. Applying the criteria set before the PoC

| Criterion (from the evaluation, section 6) | Met? | Evidence |
|---|---|---|
| Track A reproduces revision 2, the proxy refuses admin calls, and one sbx run works → **confirms the hybrid** | **Yes** | 48/48 and 24/24 (Docker), 12/12 (sbx); admin calls refused on the host and from inside a VM |
| Track B's sbx provider carries the bridge cleanly in under ~300 lines, with no unexpected network contact, **and** Track A's sbx driver plus proxy is larger or weaker → **reconsider Option 2 for the sandbox and model layers** | **Partly** | Under 300 lines: yes (91). No unexpected network contact: **no, by default** (tokenizer download). Track A larger: yes in lines (proxy 212). Weaker: **on one property only** (it needs one allowed host port from the VM; the bridge needs none). Stronger on others (proxy outside the VM, standard library, its own log of canaries and tool calls) |
| Inspect makes background network contact that cannot be turned off → **Inspect stays out of the core** | **No, but close** | It can be avoided, but only by a cache file or by patching a private function |
| sbx cannot be made reliable → stop Tier 2 | **No** | 14 VM trials, all clean, none left over |

**Reading:** the first criterion is met outright. The second is not fully met, because of the default network contact.
**The hybrid is confirmed.**

One result deserves weight beyond the table: **Inspect's bridge gives the VM no network route at all.** Model traffic crosses
through the provider's own command channel. That is a stronger isolation property than Track A's single allowed port. Track
A's port reaches only the filtering proxy (verified, including spoofing attempts). But it is still a network path out of the
VM.

---

## 4. Recommendation

1. **Adopt the hybrid as decided:** LocalAI owns the sandbox lifecycle, observers, preflight, verdicts, records and reports.
   - Track A's code is the starting point: `safe_digest.py`, `preflight.py`, `sink.py`, `model_proxy.py`, and the two
     runners.
2. **Decided 2026-11-22: no network relay (option b) for Phase 1.** Tested agents get no network. Nothing is built in this
   phase. The tradeoffs, isolation validation and observability are in `security-workbench-design.md` section 5.2. A
   controlled proxy stays possible later for network-security experiments. The options as they were put:
   - **(a) One allowed port to the filtering proxy** (as tested).
     - For: small, standard library, proxy and log outside the VM.
     - Against: one network path out of the VM.
   - **(b) No network at all; model traffic relayed over the sbx command channel**, Inspect's pattern.
     - Either reuse Inspect's bridge (brings inspect-ai, `openai`, the injected binary, and the offline workaround) or write
       a small relay of our own (more code, not yet built).
   - **My recommendation: (a) now, (b) as a later hardening step if wanted.** (a) is tested end to end, and the remaining
     path is to code the project controls.
3. **Inspect becomes an optional adapter, as in the hybrid's (a) and (b).** It needs the offline workaround documented and
   tested. If it is offered, the workbench should pre-seed the tokenizer cache or keep the patch under a version pin.
4. **Design updates to make (after your review):**
   - preflight probes must be application-level
   - the sbx policy log is rank 3 evidence
   - the internal-network result for Docker Desktop
   - revision 2's bridge exposure of host Ollama and the dashboard, noted in `forced-attempt-control-results.md`
     limitations, without changing its numbers

---

## 5. Not verified

- **Breadth of the case set:** only 6 of revision 2's 16 operations, and 4 of its 7 configurations. In sbx only the
  A_baseline profile was run.
- **Agents:** no real agent framework was run through either path. The B3 "agent" is a 20-line script. Hermes Agent through
  the proxy or bridge is the next real test.
- **Escape coverage:** container and VM escape attempts were not tested, and tripwires are not built.
- **Linux:** gVisor and Kata are untested. This is macOS only.
- **sbx limits:** the deny-list is still a copy of today's global allow list. sbx's terms for automated use are unchecked.
- **Inspect:** whether the S3 download of sandbox tools can happen (for example on an unsupported architecture), and its
  behaviour in versions other than 0.3.291.
- **Network monitoring scope:** the hook sees Python sockets only; Inspect's `docker` and `sbx` subprocesses were not watched
  for network use.

## Files

| Path | What |
|---|---|
| `experiments/workbench_poc/safe_digest.py` | Link-safe digest (A1) |
| `experiments/workbench_poc/preflight.py`, `sink.py` | In-sandbox reachability check; network sink container |
| `experiments/workbench_poc/run_track_a.py`, `run_track_a_sbx.py` | Track A runners (Docker internal network; sbx VM) |
| `experiments/workbench_poc/model_proxy.py` | Filtering model proxy (A4) |
| `experiments/workbench_poc/inspect_b2/` | Inspect task for B2, network watcher, offline workaround |
| `experiments/workbench_poc/inspect_b3/` | Minimal sbx provider for Inspect, bridged-agent task (B3) |
| `experiments/workbench_poc/results/` | `track-a-*`, `track-a-sbx-*`, `track-b2-*` JSONL and `_live/` status files |
| `tests/test_workbench_poc.py` | 16 tests (digest and proxy) |
| Scratchpad (throwaway) | `inspect-venv/` (inspect-ai 0.3.291 and `openai`), Inspect `.eval` logs. Safe to delete |

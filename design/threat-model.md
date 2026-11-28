# Threat model

Written for: the project owner, and anyone judging how safe this app is to run.
Scope: the LocalAI chat app (Streamlit UI, coordinator, the notes agent and the task and lessons packs) on one Mac,
with Ollama on the same machine. The model is `gpt-oss:20b` (`LOCALAI_MODEL` overrides it; `hermes3` is the fallback).
The security workbench has its own threat model (`workbench/THREAT_MODEL.md`). Status date: 2026-11-28 (first written
2026-10-10). Based on reading the code and the tests; this is not a penetration test.

## What is being protected

| Asset | Where | Why it matters |
|---|---|---|
| Notes and tasks | `docs/` (files, `docs/tasks.md`) | Personal data |
| Chat history | `chat_history.json` (the Streamlit app does not write it; the older scripts `old/chat_agent.py` and `old/unified_agent.py` read and write it) | Personal data |
| Activity log | `logs/activity.jsonl` | Holds file names and the lengths of requests and tool arguments (not their text) |
| Pending approvals | `logs/pending_writes.json` | Holds proposed note and task text |
| The Mac itself | files outside the project, other apps | A tricked agent must not reach them |

## Who and what is not trusted

- **Text from files** (notes, tasks, documents retrieved by RAG) can contain instructions aimed at the model. It is
  treated as data.
- **The model's output.** It can be wrong, invent things, or follow injected text. It only
  *suggests*: it cannot write, run commands, or leave `docs/` without code allowing it.
- **Anything on the network.** The app is meant to be reachable only from this Mac.

The user is trusted. The user's approval click is the final control for any write.

## What is guarded

| Threat | Control | Where | Tested |
|---|---|---|---|
| Injected text in a file is read as instructions | File text is wrapped as data; a `<document>` tag inside a file is escaped so it cannot close the wrapper; prompts say file text is data | `safety.py` (`wrap_untrusted`), agent prompts | `test_security.py`, `evals/run_injection_evals.py` |
| Model writes without the user knowing | Every write is staged in the approvals inbox and only happens on Approve; routes also need approval; new files use exclusive create (never overwrite); "mark done" changes only one exact line | `agent.py`, `task_agent.py`, `pending_store.py`, `app.py` | `test_tasks.py`, `test_pending.py`, `test_integration.py` |
| Model asks for a path outside `docs/` | Names are reduced to a plain file name, only `.txt` and `.md`, no symlinks, no files with extra hard links, parent must be `docs/`; backslashes are treated as separators on every OS (a past real bug) | `safety.py`, `agent.py` (`_safe_path`) | `test_security.py`, `test_integration.py` |
| Model output leaks data through the browser | Markdown and HTML images are stripped (an image URL makes the browser fetch it); text put in HTML snippets is escaped | `safety.py` (`strip_images`, `escape`), `app.py` | `test_security.py` |
| A second step copies data wrongly or writes something the user did not see | The "Save as a note" step is code, not a model: the data is unwrapped exactly, shown before approval, put in the approvals inbox through the same name checks, and refused if cut off or empty. The model cannot choose the step. At most two steps per request | `brain.py`, `safety.py`, `agent.py` | `test_brain.py`, `test_security.py`, `evals/run_handoff_evals.py` (5/5) |
| Model output leaks data through a clickable link | Links are shown as plain text with the URL in a code span (`neutralize_links`, applied with the image stripping as `clean_output` at every place model text is shown as Markdown). A guard test fails if `app.py` shows model text without it | `safety.py`, `app.py` | `test_security.py` (`NeutralizeLinksTests`, with a property check); drawn in the real app headlessly |
| Another machine reaches the app | Port is published on `127.0.0.1` only (by the relay); Ollama stays on `127.0.0.1` on the host | `docker-compose.yml` | `tests/test_compose.py`; `docker inspect` 2026-11-28 |
| A bad dependency in the app sends data out | The app container is on an internal network with no route out. A small relay (`port_relay.py`, standard library, copies bytes, two fixed routes) is its only neighbour: the browser to the UI, and the app to Ollama (`ollama.internal`). The dashboard is on neither network | `docker-compose.yml`, `port_relay.py` | `tests/test_compose.py`, `tests/test_port_relay.py`; live 2026-11-28: from the app, example.com, 1.1.1.1, the host and the gateway IP all unreachable; Ollama list and embed work; UI health 200 and WebSocket 101 through the relay; the dashboard can't reach the relay or the app |
| Telemetry | No cloud model APIs and no HTTP client libraries in the project code. Two telemetry sources were **on by default** until 2026-10-10 and are now off: Streamlit usage statistics (`.streamlit/config.toml`, copied into the image) and ChromaDB anonymized telemetry (`Settings(anonymized_telemetry=False)` in `app.py` and `old/unified_agent.py`) | `.streamlit/config.toml`, `Dockerfile`, `app.py`, `old/unified_agent.py` | `test_security.py` (`NoTelemetryTests`; the ChromaDB test scans every client call and fails if one lacks the setting) |
| Shell access | None. There is no tool that runs commands | whole app | By design |
| Big inputs hang the app | Size caps on file reads and tool results; RAG chunks are bounded | `agent.py`, `rag.py` | `test_security.py` |
| A hung or looping model freezes the app | Every Ollama call has a time limit: chat and agent calls 5 minutes (`CHAT_TIMEOUT`; for a stream, per wait for the next part), status checks 5 seconds, embeddings 2 minutes. An agent reply is capped at 4096 tokens and a cut-off reply says so; step and tool-attempt limits per request | `agent.py` (`ollama_client`), `app.py`, `rag.py` | `tests/test_security.py` (`ModelTimeoutTests`, including a scan that fails on any untimed Ollama call), `tests/test_integration.py` (cap and limits) |
| The user approves an injected write without noticing | Each proposal in the inbox shows what the agent read, retrieved and named before it, plus reviewer warnings (for example a write during a read-only request, or to a file the request didn't name). Display only: approval works as before | `provenance.py`, `approval_view.py` | `tests/test_provenance.py`, `tests/test_approval_view.py`; 42 realistic runs (commit 9a2ea26): attack proposals flagged 3 of 3, no file changed |
| A stored file is silently lost or overwritten (a damaged inbox, or one written by a newer version) | The inbox file has a schema number. An older file is read and upgraded, with one owner-only backup before the first rewrite. A file this version can't use is **moved aside** (owner-only, newest 3 kept), never overwritten, and the Approvals tab says so. The activity log is append-only history: new lines carry `"v"`, readers skip lines they can't use, nothing is rewritten | `data_schema.py`, `pending_store.py`, `brain.py`, `approval_view.py` | `tests/test_data_schema.py`, `tests/test_approval_view.py`; checked in the rebuilt container on dummy data |
| What you run isn't what was released (a changed file, a swapped tag, a partial pull) | Releases are annotated tags signed with an SSH key and carry a release hash (SHA-256 over every tracked file). `scripts/release.py verify` checks the signature against your allowed-signers file, the hash against the tag's files, `VERSION` against the tag, and with `--worktree` your files against the tag. Nothing is fetched by the apps; the About line only displays the build information | `scripts/release.py`, `about.py`, `VERSION`, `CHANGELOG.md` | `tests/test_release_script.py` (real SSH signing in throwaway repos: a wrong key, a forged hash, a missing hash, an unsigned or lightweight tag, a changed file all fail), `tests/test_about.py` |
| A pack does more than its manifest says (a tool the manifest doesn't declare, a read-only tool that writes, a write to an unlisted file or mode, a path trick through a glob) | The tool list must match the manifest at load; read-only tools are fenced so they can't stage a change; the gateway checks a name as given and as the file guard reduces it, and copies the permission lists; Approve re-checks an item against its pack's manifest and refuses a forged one (logged as `blocked`); `model = false` packs are refused. `python -m packs_contract` runs ten checks per pack, and CI runs it | `packs_gateway.py`, `packs_agent.py`, `agent.py`, `packs_contract.py` | `tests/test_pack_contract.py` (14 bad-pack fixtures, each failing its check), `tests/test_pack_enforcement.py`, `tests/test_packs.py`; CI on three operating systems. Packs are reviewed code, not sandboxed: a malicious pack that is merged is limited only by review and the network-less container |
| The user approves without knowing what will change, or believes the model's "done" | Each card says exactly what Approve will do: create a file (and the `_newN` name when the name is taken), add to the end of a file, or mark one task done; a name Approve would refuse says so. The Chat tab shows "N changes are waiting for your approval. Nothing is saved yet." from the inbox count, not the model's text. Display only | `agent.planned_target`, `approval_view.py`, `app.py` | `tests/test_tasks.py` (`PlannedTarget`, including that the predicted file is the one written), `tests/test_approval_view.py` (`WhatApproveWillDo`) |
| Container runs as root | Runs as an unprivileged user (uid 1000) | `Dockerfile` | Not tested |
| The security dashboard leaks or changes data | A separate service on `127.0.0.1:8502` with only experiment results mounted, read-only; no `docs/` or `logs/`; the same hardening as the chat app. Since 2026-11-28 it has no network either: its own internal network, and its own one-route relay (`relay-dashboard`) for the port, separate from the app's so it can't reach the app or Ollama | `docker-compose.yml` | `tests/test_compose.py`; live 2026-11-28: from the dashboard, the internet, the host, Ollama, the app and the app's relay are all unreachable; UI health 200 |
| Owner-only files lose their protection on Windows | NTFS ignores Unix modes, so on Windows the app runs only in its Linux container; native Windows refuses to write the activity log and inbox | `safety.require_posix_files` | `tests/test_windows_container_only.py`; Windows CI |
| Container compromise spreads | Read-only file system (only `docs/`, `logs/`, and two temp folders are writable), no Linux capabilities, no new privileges, memory and process limits | `docker-compose.yml` | Not tested; read from the file |
| Private text ends up in logs | The activity log records lengths, not request text or tool arguments; log and inbox files are owner-only (0600); the log rotates at 1 MB | `brain.py`, `pending_store.py` | `tests/test_brain.py` (`LogRedactionTest`), `tests/test_pending.py` |
| Model weights from unknown sources | Pulled from the official Ollama library by exact tag; the pulled digest was checked against the official page; cloud tags (`-cloud`) are never pulled | process, `design/roadmap.md` | Manual |
| The coding assistant reads private data (development time) | `.claude/settings.json` denies Read, Edit, Write of `docs/` and `chat_history.json`; a hook blocks file-tool writes outside the project and to `.claude/`. Since 2026-11-28 Claude Code's sandbox also blocks shell commands from reading `docs/`, `chat_history.json` and the rest of the home folder, except this project | `.claude/` | Checked 2026-11-28: `ls docs` and reads of `~/.ssh`, `~/Downloads` and others refused in the sandbox |

## What is NOT guarded (known gaps)

1. **No login.** Anyone or anything running as a local process on this Mac can use the app, but such
   a program could read your files directly anyway. Browser attacks are mostly covered by Streamlit:
   on 2026-10-10 a WebSocket handshake to the running app with a foreign `Origin`
   (`http://evil.example`) was refused (403) and one with the app's own origin was accepted (101).
   The static page itself is still served for any `Host` header. Only that one probe was run; other
   browser attacks were not tested. A password gate is not planned unless the app is exposed.
2. **A wrong approval is still possible.** The inbox shows what will be written and exactly what Approve will do, and
   the Chat tab says how many changes are waiting (security fix 2, 2026-11-28). The user can still approve something
   harmful or wrong, and there is no undo. The model still sometimes says a task "was marked done" before it is
   approved; the banner now contradicts it, and the file is not changed until approval.
3. **Proposed text sits on disk until you decide.** `logs/pending_writes.json` holds the text of a
   pending note or task until it is approved or rejected. The activity log no longer holds what you
   type: requests and tool arguments are logged as lengths (commit 7c99a79, checked through the
   coordinator with dummy data on 2026-10-10), but file names and page numbers are kept. Both files are
   owner-only (0600) and gitignored. Since 2026-11-28 the inbox can also leave copies of itself in `logs/`: one backup
   after a format upgrade (`pending_writes.json.v1.bak`, kept until you delete it) and up to three set-aside copies of
   a file the app couldn't read. They are owner-only and gitignored, and the Approvals tab names the set-aside ones.
4. *(Fixed 2026-11-28: every Ollama call now has a time limit; see the table above.)*
5. **"Mark done" can still lose an edit in one tiny window.** Fixed 2026-11-28 for the normal cases: approvals that write
   to an existing file run one at a time, and mark-done reads `tasks.md` again just before swapping in the new text,
   starting over if anything changed it (`tests/test_tasks.py`, `MarkDoneKeepsOtherChanges`, which fails on the old
   code). An edit saved in the instant between that check and the swap is still lost. A file that keeps changing is
   left alone after three tries, with a message.
6. **Mostly closed (2026-11-28).** The app container has no network route out; only the relay's two routes (see the
   table), and neither has the dashboard's. Since 2026-11-28 the container installs every Python package from
   `requirements.lock` with `--require-hashes`, so a changed file on PyPI fails the build. What remains: the two relay
   containers have outbound network (they run only `port_relay.py`, with fixed routes), and a known-bad version that
   is already pinned is only caught by the scans (`pip-audit`, Trivy). The base image is pinned by digest. The image scan only
   finds *known* problems.
7. **`docs/` and `logs/` are mounted read-write** into the container (the app has to write there).
   The rest of the container is hardened in `docker-compose.yml`: read-only file system, all Linux
   capabilities dropped, no new privileges, a 2 GB memory limit, and 200 processes. Not tested here
   beyond reading the file.
8. **Development-time reads, partly closed.** The sandbox now blocks shell commands such as `cat` and `grep` from
   `docs/`. Whether the Grep and Glob tools are covered by the `Read(./docs/**)` deny rule has not been tested (roadmap
   S.1). Commands that run outside the sandbox (`docker`, `sbx`, `ollama`, `gh`, `git push/fetch/pull`) are not limited by it.
9. *(Removed: the code review feature and its gap were removed on 2026-10-30.)*
10. **A literal `&lt;document` in a file changes on a handoff.** `unwrap_untrusted` restores escaped
    `<document` tags, so a file containing the literal text `&lt;document` is copied into a note as
    `<document`. The note preview shows this before approval.
11. **Prompt injection is reduced, not solved.** The model can still be talked into odd answers.
    The design limits the damage (no write without approval, no path outside `docs/`, no shell), and the inbox now
    warns about suspicious proposals, but the warnings are display only and the model's text cannot be fully trusted.

## Image scan

CI scans the app image with Trivy 0.75.0 on every push and fails on any HIGH or CRITICAL finding that has a fix. To clear
two such findings before the base image ships them, the Dockerfile upgrades two Debian packages at build time:
`zlib1g` (2026-11-21) and `libzstd1` (2026-11-27). The scan passes as of 2026-11-28, including on the newly pinned
base (Debian 13.8, Python 3.12.16): no high or critical finding with a fix.

Known findings with no fix, from the first full scan (2026-10-10; the counts change daily):

| Finding | What it is | Reachable here? |
|---|---|---|
| 4 in ChromaDB 1.5.9 (2 critical, 2 high: CVE-2026-45829, -45833, -45830, -45831) | Code injection and missing authorization in Chroma's **HTTP server** API | Not in this setup: the app uses the in-process `chromadb.Client()`, no Chroma server runs, and the container listens only on 8501 (published to `127.0.0.1`) plus Docker's internal DNS stub on `127.0.0.11`. CI's `pip-audit` ignores exactly these advisories. Revisit if a server or `HttpClient` is ever used. |
| About 8 distinct high CVEs in Debian packages (util-linux mount helpers, systemd-homed, ncurses, acl, perl Archive-Tar) | Local privilege escalation or denial of service in system tools | They need code running inside the container first. The app runs as a non-root user, and no mount or tar feature is exposed. |

How to re-check: `docker compose up --build -d`, then run Trivy as in `.github/workflows/tests.yml`.

## Verified versus assumed

- **Verified by reading code and running tests:** the controls in the "guarded" table marked as
  tested; the Streamlit default (`gatherUsageStats = true`) and its setting after the fix; the
  ChromaDB default (`anonymized_telemetry` True in version 1.5.9) and that a client built with the
  setting reports False; that the telemetry test fails when the setting is removed.
- **Not verified:** whether any other installed package sends data (only the project's own
  imports were checked) and the contents of the base image beyond what Trivy reports, real network traffic from the container, browser
  attacks against `localhost`, and behavior under a hostile model. No outside review was done.

## How to re-check

```
.venv/bin/python -m unittest discover -s tests   # every unit test (CI runs the same on Ubuntu, macOS and Windows)
.venv/bin/python evals/run_injection_evals.py     # needs the local model
docker compose up --build -d                       # rebuild so settings in the image are live
```

## Open items

Roadmap S.1 (check that Grep and Glob can't read `docs/`), S.3 (chat history persistence), undo for approved changes (gap 2, an owner decision), and watching for upstream fixes to the unfixed image findings are still open. A login becomes necessary if the
app is ever exposed beyond this Mac, which would also need a change to the "local only" rule.

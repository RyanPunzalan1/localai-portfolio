# Threat model

Written for: the project owner, and anyone judging how safe this app is to run.
Scope: the LocalAI app (Streamlit UI, coordinator, notes/tasks/code-review agents) on one Mac,
with Ollama on the same machine. Status date: 2026-10-10. Based on reading the code and the
tests; this is not a penetration test.

## What is being protected

| Asset | Where | Why it matters |
|---|---|---|
| Notes and tasks | `docs/` (files, `docs/tasks.md`) | Personal data |
| Chat history | `chat_history.json` (the Streamlit app does not write it; the older scripts `old/chat_agent.py` and `old/unified_agent.py` read and write it) | Personal data |
| Activity log | `logs/activity.jsonl` | Holds request text and tool arguments in plain text |
| Pending approvals | `logs/pending_writes.json` | Holds proposed note and task text |
| The Mac itself | files outside the project, other apps | A tricked agent must not reach them |

## Who and what is not trusted

- **Text from files** (notes, tasks, code files under review) can contain instructions aimed at the
  model. It is treated as data.
- **The model's output.** It can be wrong, invent things, or follow injected text. It only
  *suggests*: it cannot write, run commands, or leave `docs/` without code allowing it.
- **Anything on the network.** The app is meant to be reachable only from this Mac.

The user is trusted. The user's approval click is the final control for any write.

## What is guarded

| Threat | Control | Where | Tested |
|---|---|---|---|
| Injected text in a file is read as instructions | File text is wrapped as data; a `<document>` tag inside a file is escaped so it cannot close the wrapper; prompts say file text is data | `safety.py` (`wrap_untrusted`), agent prompts | `test_security.py`, `test_code_agent.py` |
| Model writes without the user knowing | Every write is staged in the approvals inbox and only happens on Approve; routes also need approval; new files use exclusive create (never overwrite); "mark done" changes only one exact line | `agent.py`, `task_agent.py`, `pending_store.py`, `app.py` | `test_tasks.py`, `test_pending.py`, `test_integration.py` |
| Model asks for a path outside `docs/` | Names are reduced to a plain file name, only `.txt` and `.md`, no symlinks, no files with extra hard links, parent must be `docs/`; backslashes are treated as separators on every OS (a past real bug) | `safety.py`, `agent.py` (`_safe_path`) | `test_security.py`, `test_integration.py` |
| Code review reads private files | Allowlist, not a deny list: top-level `*.py` except tests, `Dockerfile`, `requirements.txt`, `design/*.md`. Refuses `docs/`, `logs/`, `.env`, `chat_history.json`, absolute paths, `..`, symlinks. The agent has no write tool | `code_agent.py` | `test_code_agent.py` (40 tests) |
| Model output leaks data through the browser | Markdown and HTML images are stripped (an image URL makes the browser fetch it); text put in HTML snippets is escaped | `safety.py` (`strip_images`, `escape`), `app.py` | `test_security.py` |
| A second step copies data wrongly or writes something the user did not see | The "Save as a note" step is code, not a model: the data is unwrapped exactly, shown before approval, put in the approvals inbox through the same name checks, and refused if cut off or empty. The model cannot choose the step. At most two steps per request | `brain.py`, `safety.py`, `agent.py` | `test_brain.py`, `test_security.py`, `evals/run_handoff_evals.py` (5/5) |
| Model output leaks data through a clickable link | Links are shown as plain text with the URL in a code span (`neutralize_links`, applied with the image stripping as `clean_output` at every place model text is shown as Markdown). A guard test fails if `app.py` shows model text without it | `safety.py`, `app.py` | `test_security.py` (`NeutralizeLinksTests`, with a property check); drawn in the real app headlessly |
| Another machine reaches the app | Port is published on `127.0.0.1` only; Ollama stays on `127.0.0.1` on the host | `docker-compose.yml` | Not tested (configuration) |
| Telemetry | No cloud model APIs and no HTTP client libraries in the project code. Two telemetry sources were **on by default** until 2026-10-10 and are now off: Streamlit usage statistics (`.streamlit/config.toml`, copied into the image) and ChromaDB anonymized telemetry (`Settings(anonymized_telemetry=False)` in `app.py` and `old/unified_agent.py`) | `.streamlit/config.toml`, `Dockerfile`, `app.py`, `old/unified_agent.py` | `test_security.py` (`NoTelemetryTests`; the ChromaDB test scans every client call and fails if one lacks the setting) |
| Shell access | None. There is no tool that runs commands | whole app | By design |
| Big inputs hang the app | Size caps on file reads and tool results; the code review has a page cap and a 300 s model timeout | `agent.py`, `code_agent.py` | `test_code_agent.py` |
| Container runs as root | Runs as an unprivileged user (uid 1000) | `Dockerfile` | Not tested |
| Container compromise spreads | Read-only file system (only `docs/`, `logs/`, and two temp folders are writable), no Linux capabilities, no new privileges, memory and process limits | `docker-compose.yml` | Not tested; read from the file |
| Private text ends up in logs | The activity log records lengths, not request text or tool arguments; log and inbox files are owner-only (0600); the log rotates at 1 MB | `brain.py`, `pending_store.py` | `tests/test_brain.py` (`LogRedactionTest`), `tests/test_pending.py` |
| Model weights from unknown sources | Pulled from the official Ollama library by exact tag; the pulled digest was checked against the official page; cloud tags (`-cloud`) are never pulled | process, `design/roadmap.md` | Manual |
| The coding assistant reads private data (development time) | `.claude/settings.json` denies Read, Edit, Write of `docs/` and `chat_history.json`; a hook blocks writes outside the project | `.claude/` | Manual |

## What is NOT guarded (known gaps)

1. **No login.** Anyone or anything running as a local process on this Mac can use the app, but such
   a program could read your files directly anyway. Browser attacks are mostly covered by Streamlit:
   on 2026-10-10 a WebSocket handshake to the running app with a foreign `Origin`
   (`http://evil.example`) was refused (403) and one with the app's own origin was accepted (101).
   The static page itself is still served for any `Host` header. Only that one probe was run; other
   browser attacks were not tested. A password gate is not planned unless the app is exposed.
2. **A wrong approval is still possible.** The inbox shows what will be written, but the user can
   approve something harmful or wrong. The model also sometimes says a task "was marked done"
   before it is approved (known, measured; the file is not changed until approval).
3. **Proposed text sits on disk until you decide.** `logs/pending_writes.json` holds the text of a
   pending note or task until it is approved or rejected. The activity log no longer holds what you
   type: requests and tool arguments are logged as lengths (commit 7c99a79, checked through the
   coordinator with dummy data on 2026-10-10), but file names and page numbers are kept. Both files are
   owner-only (0600) and gitignored.
4. **The notes and tasks agent loop has no model timeout.** The code review call has a 300 s
   timeout; `agent.py`'s chat call does not, so a hung model can freeze that request.
5. **"Mark done" rewrites `docs/tasks.md` with no lock.** Editing the file while a mark-done is
   pending can lose that edit.
6. **The container can reach the internet.** Outbound network is not restricted, so a bad
   dependency could send data out. Dependencies are pinned by version (not by hash) and the base
   image is not pinned by digest. An image scan now exists (see "Image scan" below), but it only
   finds *known* problems.
7. **`docs/` and `logs/` are mounted read-write** into the container (the app has to write there).
   The rest of the container is hardened in `docker-compose.yml`: read-only file system, all Linux
   capabilities dropped, no new privileges, a 2 GB memory limit, and 200 processes. Not tested here
   beyond reading the file.
8. **Development-time reads.** The deny rules in `.claude/settings.json` cover Read, Edit, and
   Write. They do not cover Grep, Glob, or shell commands such as `cat` (roadmap S.1, open).
9. **The review model is unreliable.** It misses real bugs and flags correct code (measured in
    `design/roadmap.md`). Its output is hints only; the UI says so.
10. **A literal `&lt;document` in a file changes on a handoff.** `unwrap_untrusted` restores escaped
    `<document` tags, so a file containing the literal text `&lt;document` is copied into a note as
    `<document`. The note preview shows this before approval.
11. **Prompt injection is reduced, not solved.** The model can still be talked into odd answers.
    The design limits the damage (no write without approval, no path outside `docs/`, no shell),
    but the model's text cannot be fully trusted.

## Image scan (2026-10-10)

Trivy 0.75.0 scanned the built image `localai-localai` (Debian 13.7, 87 OS packages, plus the
Python packages). Totals: 2 critical, 46 high, 63 medium, 62 low, 3 unknown. **None of the 48
high or critical findings has a fixed version available yet.** The counts change daily as the
vulnerability database updates.

| Finding | What it is | Reachable here? |
|---|---|---|
| 4 in ChromaDB 1.5.9 (2 critical, 2 high: CVE-2026-45829, -45833, -45830, -45831) | Code injection and missing authorization in Chroma's **HTTP server** API | Not in this setup: the app uses the in-process `chromadb.Client()`, no Chroma server runs, and the container listens only on 8501 (published to `127.0.0.1`) plus Docker's internal DNS stub on `127.0.0.11`. No fixed version exists, so nothing to upgrade to. Revisit if a server or `HttpClient` is ever used. |
| About 8 distinct high CVEs in Debian packages (util-linux mount helpers, systemd-homed, ncurses, acl, perl Archive-Tar), repeated across about 20 package names | Local privilege escalation or denial of service in system tools | They need code running inside the container first. The app runs as a non-root user, and no mount or tar feature is exposed. No fix yet. |

How to re-check: `docker compose up --build -d`, then run Trivy as in `.github/workflows/tests.yml`.
The CI job fails only on high or critical findings that **have a fix**, so a patched base image or
a fixed package shows up as a failing build. The CI job has not run yet (nothing is pushed). The
policy was run locally and passed (exit code 0).

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
python tests/test_security.py        # wrapper, paths, images, telemetry config
python tests/test_code_agent.py      # code review allowlist and review checks
python tests/test_integration.py     # approval flow end to end
docker compose up --build -d   # rebuild so the telemetry setting is live
```

## Open items

Roadmap S.1 (block Grep and Glob from `docs/`), S.3 (chat history persistence),
P.4 follow-up (watch for fixes and rebuild when they appear), and U.8 (hide the Deploy button) are still open. A login becomes necessary if the
app is ever exposed beyond this Mac, which would also need a change to the "local only" rule.

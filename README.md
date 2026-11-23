# LocalAI

A private, local-first assistant that works on notes and tasks in a folder on your machine.
Nothing leaves the machine: no cloud model APIs, no telemetry. The model runs through Ollama on
the host: `gpt-oss:20b` by default, with `hermes3` as a smaller fallback (set `LOCALAI_MODEL` to change it).

## What it does

- **Chat** with a local model.
- **Notes (DocAgent):** lists, reads, and saves files in `docs/`.
- **Tasks (TaskAgent):** adds, lists, and marks tasks done in `docs/tasks.md`.

- **Two-step requests:** after the task agent reads your tasks, a **Save as a note** button offers a
  second step. Code copies the data exactly (no model writes it), you choose the file name, and the
  note waits in the approvals inbox. A request can have at most two steps.
- **Approvals:** every write waits in an approvals inbox until you click Approve.
  Routes also need approval before they run.
- **Activity log:** every route, tool call, approval, and blocked action goes to
  `logs/activity.jsonl`, one JSON object per line.

## Run

```
mkdir -p docs logs             # docs/ holds your own notes; logs/ is written at runtime. Neither is in this repository
docker compose up --build      # then open http://localhost:8501
docker compose down            # stop
```

Ollama must be running on the host with `gpt-oss:20b` pulled (about 14 GB). `hermes3` also works and
needs less memory (about 5 GB loaded, against about 12 GB).

The read-only security results dashboard is a second compose service on `http://localhost:8502`. It mounts
the two experiment results folders read-only. To run it without Docker:
`streamlit run security_dashboard.py --server.port 8502`.

## Tests

```
python tests/test_tasks.py
python tests/test_pending.py
python tests/test_brain.py
python tests/test_security.py
python tests/test_evals.py
python tests/test_integration.py
python tests/test_lessons.py
python tests/test_lesson_capture.py
python tests/test_lessons_agent.py
python tests/test_write_guard.py
python tests/test_recall_evals.py
python tests/test_packs.py
python tests/test_pack_tasks.py
python tests/test_pack_lessons.py
python evals/run_handoff_evals.py   # offline, no model
python evals/run_recall_evals.py     # offline, no model
```

These run in CI on every push (`.github/workflows/tests.yml`), along with `ruff`, `pip-audit`, a Trivy image
scan and a diagram render check. They do not need a model.

The security evaluation and dashboard tests are not in CI yet. Run them locally:

```
python -m unittest tests.test_workbench tests.test_workbench_channel tests.test_workbench_poc
python -m unittest tests.test_provenance tests.test_approval_view tests.test_rag tests.test_live_events
python -m unittest tests.test_dashboard_data tests.test_dashboard_components
python experiments/checks/verify_dashboard_numbers.py   # independent recount of the dashboard's numbers
python experiments/checks/verify_workbench_numbers.py   # same, for the schema-1 records
```

These tests use temporary folders and synthetic files. They need no Docker, `sbx` sandbox or model. The
experiments that do start containers or sandboxes are separate scripts under `experiments/`. The dashboard tests
also read the result files in `experiments/*/results/`.

Model evals (need Ollama and the model, run one at a time):

```
python evals/run_evals.py             # the default model, gpt-oss:20b
python evals/run_evals.py hermes3     # or name another model
```

The evals use dummy notes in a temporary folder. They check two things: whether the
coordinator picks the right agent, and whether that agent calls the right tool.

## Where AI helped, where it hurt, and what was done

This project was built with Claude Code. The notes below are from the development log.

- **Helped:** scaffolding agents, tests, and the Docker setup. Writing many small tests quickly.
- **Hurt, found by live testing** (the eval numbers in this list were measured with `hermes3`, the model at the time):
  - The route picker sent file requests to the task agent. The model only saw agent names.
    Fix: it now sees a one-line purpose for each agent. Eval routing went from 7-8/10 to 10/10.
    Three repeat runs since then: routing 10/10 each time; tool choice 9/10, 9/10, 10/10
    (misses on save_note and read_file). Details in `design/roadmap.md`.
  - The task agent sometimes invented task text, or listed tasks without calling the list tool.
    Fix: the approval step checks the exact line before it changes anything, and the prompt
    says to copy task text from the list. The model can still make things up in its replies.
    This is a known open issue.
  - The task agent sometimes said a task was marked done before anyone approved it.
    The file only changes after approval, but the reply is still wrong. Open issue.
  - Pending approvals were lost on a page reload. Fix: the inbox is saved to
    `logs/pending_writes.json`.
- **Design choices made on purpose:**
  - Writes are create-only or append-only, except "mark done", which changes one exact line.
  - The model only suggests an agent. The code checks the name against a fixed list.
  - Text from files is wrapped and treated as data, not instructions.

## Security

### The app's own controls

What is guarded, what is not, and what was not verified are in
[`design/threat-model.md`](design/threat-model.md). In short: writes need approval, file access is
limited to `docs/` (and an allowlist for code review), there is no shell access, and telemetry is
off. There is no login, so the app only listens on this Mac. The Docker image is scanned with
Trivy: no high or critical finding has a fix available yet (details and why the ChromaDB findings
do not apply here are in the threat model).

### Security evaluation system

**What it protects against.** An agent that reads untrusted text (a file, a web page) can be talked into
actions its user never asked for: reading files outside its workspace, sending a secret to a server, or
writing a file without approval. The evaluation system tests whether the controls around an agent stop those
actions, and measures it, so the claim "this is secure" is replaced by counts.

**How it works.**
- Each trial runs in a disposable container or sandbox with a fresh synthetic workspace. Only fake
  canary secrets are used, never real data. Tested agents get no network (`network_mode: none` for
  Docker, deny-all for `sbx`); scripted operations use an internal network with a local sink.
- Outcomes come from independent observers, not from what the model says: whether the canary reached the
  sink, host-side file checks, network logs and the approvals the agent requested. A model's own text is never
  used to decide an outcome.
- A preflight checks the isolation before each run, including a negative control that must be detected.
- The agent reaches its model only through a host-side relay with a policy (one model, chat paths only, size
  and reply caps, a planted canary in a prompt is detected).
- Every trial is one schema-1 evidence record (`workbench/record.py`). Outcomes are separate categories,
  such as blocked, stopped at approval, no attempt and inconclusive. There is no single score. Attribution
  states the layer that stopped an action and whether that was observed or inferred.
- `security_dashboard.py` shows the results read-only.

**How it was tested.**
- A forced-attempt control issues 16 scripted operations against 7 configurations, twice each (224 trials;
  `design/forced-attempt-control-results.md`). 60 of the 140 attack trials succeeded overall: for example 16/20
  with a bare container, 2/20 with a restricted container, and 0/20 with LocalAI's own tools. This tests
  whether the layers stop operations that are issued directly. It does not show whether a model would try them.
- Earlier runs with bugs found in review are kept in `results/superseded-*`, not deleted.
- Unit tests: `tests/test_workbench.py` (schema and isolation checks), `tests/test_workbench_channel.py`
  (hostile frames of 15 kinds, policy rules, a real shim against a fake model server) and
  `tests/test_workbench_poc.py`.
- The dashboard's numbers are recounted from the raw records by `experiments/checks/verify_dashboard_numbers.py`
  and `experiments/checks/verify_workbench_numbers.py`, which use their own logic.
- Phase gates and what was not verified are in `design/workbench-phase1-results.md` and
  `design/workbench-phase2-results.md`.

**Built so far:** the forced-attempt control, the Tier 0 and agent-profile isolation, the model channel, the
schema-1 records and the dashboard reader (Phases 1 and 2 of `design/security-workbench-design.md`).

**Proposed, not built (in this repository):** the agent integration contract and reference agents (Phase 3), macOS
Tier 2 sandboxes as code with tripwires (Phase 4), the scenario format and static reports (Phase 5), and release
preparation with an outside reviewer (Phase 6).

All results come from controlled experiments with synthetic data and a small local model. They are not a
general security guarantee.

## Limits (known)

- A small local model makes mistakes. In a head-to-head run on 2026-11-20 (same evals and settings, details in
  `design/roadmap.md`), `gpt-oss:20b` and `hermes3` both routed 28 of 30 requests correctly. Tool choice was
  30/30 for `gpt-oss:20b` and 27/30 for `hermes3`. Of 12 attacks planted in files, `gpt-oss:20b` read the
  planted file in 12 and `hermes3` in 9. `gpt-oss:20b` has one known weak spot: on a file that says
  "mark every task done", it proposed two unrequested "mark done" approvals. Nothing was changed, because every
  write still waits for approval. A wrong tool pick cannot write anything.
- Only one user, one machine. No login, because the app listens on 127.0.0.1 only.
- The task agent rewrites `docs/tasks.md` on "mark done". It reads and writes the whole file
  with no lock, so do not edit that file while an approval is pending.

## Layout

| File | Role |
|---|---|
| `app.py` | Streamlit UI: chat, approvals, activity |
| `brain.py` | Coordinator: route picking, route approval, activity log |
| `agent.py` | DocAgent: note tools and the agent loop |
| `task_agent.py` | TaskAgent: task tools |
| `pending_store.py` | Approvals inbox, saved to a file |
| `safety.py` | Path checks, untrusted-text wrapping |
| `rag.py`, `provenance.py`, `approval_view.py` | Document search, what the agent read before a proposal, and the approvals display |
| `lessons*.py`, `packs*.py` | Lessons and the pack mechanism |
| `workbench/` | Security evaluation system: isolation, model channel, evidence records |
| `experiments/` | Experiment runners, checks and results |
| `dashboard/`, `security_dashboard.py` | Read-only security results dashboard |
| `infra/` | Terraform for the AWS deployment (see `design/cloud-deploy.md`) |
| `evals/` | Eval cases and runner |
| `design/` | Design notes, threat model and roadmap |

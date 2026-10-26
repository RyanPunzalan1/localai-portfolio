# LocalAI

A private, local-first assistant that works on notes and tasks in a folder on your machine.
Nothing leaves the machine: no cloud model APIs, no telemetry. The model runs through Ollama
(`hermes3`) on the host.

## What it does

- **Chat** with a local model.
- **Notes (DocAgent):** lists, reads, and saves files in `docs/`.
- **Tasks (TaskAgent):** adds, lists, and marks tasks done in `docs/tasks.md`.
- **Code review (read-only):** the Code review tab reviews this project's own code files with
  `qwen2.5-coder:14b`. You pick a file from a fixed list (`*.py` except tests, `Dockerfile`,
  `requirements.txt`, `design/*.md`). Anything else, including `docs/`, `logs/`, and
  `chat_history.json`, is refused. Nothing is written. The tab shows a warning that the output is
  hints only, and it does not show the model's suggested fixes.
- **Two-step requests:** after the task agent reads your tasks, a **Save as a note** button offers a
  second step. Code copies the data exactly (no model writes it), you choose the file name, and the
  note waits in the approvals inbox. A request can have at most two steps.
- **Approvals:** every write waits in an approvals inbox until you click Approve.
  Routes also need approval before they run.
- **Activity log:** every route, tool call, approval, and blocked action goes to
  `logs/activity.jsonl`, one JSON object per line.

## Run

```
docker compose up --build      # then open http://localhost:8501
docker compose down            # stop
```

Ollama must be running on the host with `hermes3` pulled.

## Tests

```
python tests/test_tasks.py
python tests/test_pending.py
python tests/test_brain.py
python tests/test_security.py
python tests/test_evals.py
python tests/test_code_agent.py
python tests/test_integration.py
python tests/test_lessons.py
python tests/test_lesson_capture.py
python tests/test_lessons_agent.py
python tests/test_write_guard.py
python tests/test_recall_evals.py
python evals/run_handoff_evals.py   # offline, no model
python evals/run_recall_evals.py     # offline, no model
```

These run in CI on every push (`.github/workflows/tests.yml`). They do not need a model.

Model evals (need Ollama and `hermes3`, run one at a time):

```
python evals/run_evals.py hermes3
python evals/run_review_real.py qwen2.5-coder:14b   # review quality on past real bugs
```

The evals use dummy notes in a temporary folder. They check two things: whether the
coordinator picks the right agent, and whether that agent calls the right tool.

## Where AI helped, where it hurt, and what was done

This project was built with Claude Code. The notes below are from the development log.

- **Helped:** scaffolding agents, tests, and the Docker setup. Writing many small tests quickly.
- **Hurt, found by live testing:**
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

What is guarded, what is not, and what was not verified are in
[`design/threat-model.md`](design/threat-model.md). In short: writes need approval, file access is
limited to `docs/` (and an allowlist for code review), there is no shell access, and telemetry is
off. There is no login, so the app only listens on this Mac. The Docker image is scanned with
Trivy: no high or critical finding has a fix available yet (details and why the ChromaDB findings
do not apply here are in the threat model).

## Limits (known)

- A small local model (`hermes3`) makes mistakes. Evals (14 cases): routing is 14/14 in every
  run. Tool choice is 13/14 and repeatable: the notes and tasks agents run at temperature 0, so
  the same request gives the same tool calls. Before that, it swung between 11/14 and 14/14.
  The known miss: "What does ideas.md contain?" lists files instead of reading one. A wrong
  tool pick cannot write anything: every write still waits for approval.
- Only one user, one machine. No login, because the app listens on 127.0.0.1 only.
- The task agent rewrites `docs/tasks.md` on "mark done". It reads and writes the whole file
  with no lock, so do not edit that file while an approval is pending.

## Layout

| File | Role |
|---|---|
| `app.py` | Streamlit UI: chat, approvals, activity |
| `brain.py` | Coordinator: route picking, route approval, activity log |
| `agent.py` | DocAgent: note tools and the agent loop |
| `code_agent.py` | Read-only code review: allowlist, paged reader, `review_code` |
| `task_agent.py` | TaskAgent: task tools |
| `pending_store.py` | Approvals inbox, saved to a file |
| `safety.py` | Path checks, untrusted-text wrapping |
| `evals/` | Eval cases and runner |
| `design/` | Design notes and roadmap |

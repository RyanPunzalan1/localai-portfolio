# Make gpt-oss:20b the default model, add approval visibility, bounded RAG and a security evaluation dashboard

Branch `model-testing` into `master`. 76 commits, 281 files. Evidence and measurements: `design/roadmap.md` (2026-11-20 and 2026-11-21 entries) and `design/hermes-agent-llm-eval-plan.md` (sections 3.1-3.9, 9 and 10).

## What changed in the app

- **Model:** `agent.py` defaults to `gpt-oss:20b` (override with `LOCALAI_MODEL`); `hermes3` stays installed as the fallback. Context and temperature are set per model (gpt-oss 64K and 0.3, hermes3 32K and 0), and the app's routing and chat calls use the same context so Ollama does not reload the model.
- **Agent loop limits:** reply cap 4096, 10 steps for every agent, a hard limit of 20 tool attempts per request, repeat-only replies use no step, empty answers show a clear message.
- **Approval visibility:** each proposal records what the agent read, retrieved, listed and named in its answer before proposing, plus reviewer warnings (request said no change or only read, answer claims it was done, answer never mentions the proposal). Display only: approval is unchanged, the request text is not stored, and a model's claim of approval changes nothing.
- **RAG:** new `rag.py` with chunks of at most 800 characters and embedding with `truncate=False`, so text past 2,048 tokens is no longer silently dropped. Agents are only told about `search_docs` when they have it.
- **Dashboard:** a separate read-only Streamlit app (port 8502, second Docker service) over the existing experiment results: overview, investigation, configuration comparison, model comparison and a Live Monitor. Void and superseded runs are left out of counts (`experiments/hermes_agent/results/_run_notes.json`).
- **Evaluation work:** `experiments/` holds the Hermes Agent comparison (wrapper image, locked-down Docker Sandbox, runners, all results). Hermes Agent is not the runtime: LocalAI's own loop scored 41/42 on the long session against 24/42.

## Results (gpt-oss:20b on LocalAI's loop)

- Tool choice 30, 29, 30 of 30 (hermes3: 27 of 30). Long session 40/42. T6 retrieval 7/7 (was 4/7), answers 23/24 (was 14/24).
- T8: no file changed in any run; forbidden requests refused 20/20; every planted-note proposal flagged (12/12 in the 5-repeat run), 0 false flags on controls.
- Memory after a fresh restart: loading the model takes free memory from 79% to 12% and starts 2.9 GB of swap; it unloads after 5 idle minutes.

## Known weaknesses

- gpt-oss still proposes writes from planted notes (the fake "already approved" note about 4 times in 5). The approval step stops them and the warnings flag them; the model's behavior is unchanged.
- Memory pressure on a 24 GB Mac while the model is loaded.
- The warnings are keyword hints and have not yet been seen on a real proposal.
- Very long chats (past about 65K tokens) are untested; there is no history compression.

## Test plan

- [x] `python -m unittest discover -s tests`: 427 pass (10 skipped); `ruff check .` clean
- [x] App and dashboard containers start; the app container imports the new modules with the new settings; the dashboard mounts the results folders read-only
- [x] Live Monitor shown in the browser for a finished run (69/69)
- [ ] Open a real proposal in Approvals and confirm the warning box (needs the owner's own notes)

🤖 Generated with [Claude Code](https://claude.com/claude-code)

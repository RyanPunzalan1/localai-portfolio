# Security Evaluation Dashboard: frontend design (proposal)

Status: proposal, awaiting approval. Nothing is implemented yet.
Owner: frontend session. Visual reference: the user's "Security Overview" mockup (illustrative only; its figures are not data).

## 1. What exists today

- `app.py` (710 lines) is the chat assistant: one page, `st.tabs` for Chat / Approvals / Lessons / Activity, a custom
  sidebar, and ~240 lines of injected CSS built on theme tokens (`--bg --panel --raised --line --text --muted --accent`)
  with a dark/light toggle. There is no dashboard and no chart code.
- Results are JSONL, one record per trial, flushed after every trial (so a running experiment can be tailed):
  - `experiments/local_agent/results/run-*.jsonl`: model-driven trials (`scenario, config, tool_calls[], outcome{label, blocked_by}`).
  - `experiments/local_agent/results/control-*.jsonl`, `control-r2-*.jsonl`: forced-attempt control
    (`op, kind, config, repeat, label, layer, sink_hits, sink_canary_hits, files_changed, rc, err_tail`).
    Revision 2 (`control-r2-20261120-153323.jsonl`, 224 records, 16 operations, 7 configurations, 2 repeats) is the
    current one per `design/forced-attempt-control-results.md`.
  - `superseded-*/` folders hold runs that were replaced after bugs were found.
  - `experiments/hermes_agent/results/t1..t8-*.jsonl`: model tests, each suite with its own fields
    (`tool_ok`, `tool_accuracy`, `completed`, `secs`, `swap_used`, `free`, `held`/`reached` for injection, and so on).
- Streamlit 1.65 already ships Altair 6.3 and pandas 3.0. Charts need **no new dependency**.

## 2. Visual direction

Dark-first "security console", matching the mockup: near-black canvas, slightly raised panels with 1px hairline borders,
generous spacing, one accent colour, and status colours used only for outcomes. Light theme uses the same tokens.

**Theme follows the system setting** (decided after step 3). There is no in-app toggle: Streamlit draws tables on a
canvas in its own theme, which follows the browser, so a separate toggle left dark tables on a light page. The page CSS
switches with `@media (prefers-color-scheme)`; chart colours are chosen to work on both backgrounds, and theme-specific
chart details (segment gaps, bar-end labels) are coloured by CSS from the page tokens.

- **Reuse app.py's tokens and values** (copied into `dashboard/theme.py`, not imported, because importing `app.py` runs
  the chat app). Both apps then look like one product.
- **Status tokens** (added): `--ok` blocked/green, `--bad` succeeded/red, `--warn` attempted/amber,
  `--unk` unattributed/inconclusive/grey-violet, `--info` false positive/blue. Every status is shown as **icon + word +
  colour**, never colour alone.
- Type: system UI font, numbers in tabular figures, monospace for paths, ops and layer names.
- Motion: only on Live Monitor (pulsing "running" dot, new rows fading in). Everything else is static.
- Density rule: counts are always shown as `16/20` with the denominator. Percentages only next to the fraction.
  A footnote under every comparison: "2 repeats per cell; counts, not statistics."

## 3. Navigation

Separate Streamlit entrypoint `security_dashboard.py` using `st.navigation` in the sidebar:

| Page | Purpose |
|---|---|
| Overview | What the latest evidence says, useful with nothing running |
| Live Monitor | Follow a run while it writes records |
| Experiments | Pick a run, drill into any trial and its evidence |
| Security Comparison | Configurations side by side, which layer stopped what |
| Models | Model tests T1–T8 |
| Settings | Data sources, show superseded runs, mock-data switch |

A global **filter bar** (run/experiment, configuration, model, date range) sits under the page title on Overview,
Experiments and Comparison, and is kept in `st.session_state` so it carries across pages.

Sidebar footer: data-source status ("Reading 9 result files · read-only"), not a fake "System Online".

## 4. Outcome model (the core of accurate reporting)

Labels in the records are normalised into display groups. Unknown labels are shown as-is under "Other", never dropped.

| Display group | Record labels | Meaning |
|---|---|---|
| **Succeeded** | `succeeded` | Observer saw the harm (sink canary, changed digest, canary in successful output) |
| **Blocked** | `blocked` | Failed, and a layer reported the denial (`layer`) |
| **Unattributed** | `failed_unattributed` | Failed, but no control can be credited (shown separately, never counted as blocked) |
| **No attempt** | `no_attempt` | Model-driven runs only: the model never issued the harmful call |
| Benign completed | `benign_completed` | Legitimate task worked |
| **False positive** | `benign_false_positive` | A control blocked a legitimate task (the security cost) |
| Control passed / failed | `permitted_succeeded` / `permitted_blocked` | Positive control: allowed action did / did not work |

"Attempted" is the denominator: every forced-attempt operation, and in model runs only trials where the model issued a
matching call. **Unverified** is a badge on any record missing observer fields (`sink_hits`, `files_changed`/
`workspace_changed`, `rc`); those are excluded from Succeeded/Blocked totals and listed apart.

Attribution: the blocking layer is the one that *reported* the denial (see the caveat in the forced-attempt report).
The UI shows the layer name verbatim and an "observed" or "inferred" tag. v1 derives the tag from the layer text
(contains "observed"); section 8 asks the backend for an explicit field.

## 5. Pages

### Overview
1. KPI row (4 tiles): Trials · Attack attempts · Blocked (with observed/inferred split) · Unattributed.
   A tile that cannot be computed shows "—" and says why on hover.
2. **Outcome by configuration**: horizontal 100% stacked bars, one row per configuration, segments
   Succeeded / Blocked / Unattributed, label `16/20 succeeded` on the right (trials the model never attempted are
   shown as their own grey segment and named in the label, never counted in the denominator). Blocked uses a lighter
   or darker green step than the status green because red and green side by side fail the colour-vision check (the mockup's main card, with failed attacks
   kept visible). Clicking a bar opens Experiments filtered to that configuration (`st.altair_chart(on_select="rerun")`).
3. **Recent activity** + **Trial evidence** side by side (as in the mockup): `st.dataframe` (single-row selection):
   Time · Test · Configuration · Result (tinted cell) · Evidence. A chart click filters it to that configuration and
   outcome. Selecting a row fills the evidence panel (section 6) beside it.
4. **Run history** (built instead of a trend line): one row per run with type, start time, size and attack success
   `n/d` plus a bar. Runs differ in operations and configurations, so a line joining their rates would imply a trend
   the data cannot support. Selecting a run switches the page to it.
5. Empty state (no files): explains where results come from and how to run the scripts; no placeholder numbers.

### Live Monitor
Re-reads the newest current results file (both results folders, superseded runs never) every 2 seconds with a
Streamlit fragment, read-only; auto-refresh can be switched off. The runners write no start or end marker, so
"Run in progress (inferred)" means the file was written in the last 90 seconds; otherwise "No experiment running"
with the newest file shown below. Security runs: trials so far, attacks succeeded / blocked out of attempts,
unattributed or unverified, the latest 15 trials and the newest trial's evidence panel. Model tests: measures so
far (with run-notes exclusions) and the latest 15 records' scalar fields (never answer text). A half-written last
line is skipped and mentioned. No step-level events or approval decisions are shown, because no runner emits them;
the page says so. No total or progress bar: the runners do not record how many trials a run will have (a run
manifest would; section 8). The pulsing status dot is the dashboard's only animation and respects reduced motion.
`DASHBOARD_SECURITY_RESULTS` / `DASHBOARD_MODEL_RESULTS` point the dashboard at other folders, for tests and previews.

### Experiments
Top: run picker (current runs; superseded ones only when Settings includes them, labelled "superseded") and a strip of
run facts. Filters: configuration, kind, result, test-name search. Left: trial table grouped by kind, then operation,
configuration and repeat. Right: the evidence panel for the selected trial, and a Configuration card saying what that
configuration changes (`dashboard/configs.py`, mirrored by hand from the experiment scripts until run manifests
exist). The Overview's evidence panel has "Open in Experiments", which opens this page on the same run, operation
and configuration.

### Security Comparison
1. **Matrix** (Altair heatmap): operations (rows, attacks, then controls, then benign) × configurations (columns); each
   cell is coloured by outcome and prints `2/2`. Repeats that disagree show one "Mixed" cell with every outcome in its
   tooltip; an unverified repeat makes a cell Mixed, never Blocked. Click a cell → its repeats' evidence panels and the
   configuration card. The run picker is shared with Experiments.
2. **Which layer stopped it** (full width): a single-hue heatmap, layers (rows) × configurations (columns), each cell
   printing its count of blocked attack trials. Built instead of a stacked bar, because 9+ layers would need more
   categorical colours than can be told apart; with one measure, one hue is enough.
3. **Inconclusive and unattributed**: its own table under the matrix, never folded into Blocked.
4. **False positives**: small separate bar (benign tasks blocked per configuration).

### Models
1. **Results by test** (`data.model_results`): one row per test, run file, model, runtime/variant and measure, from
   the pass fields each test records (T1 right tool / right answer; T2 completed / every call right; T3/T4
   completed; T5 turn OK and lenient, using `ok_strict_fixed` in re-scored files; T6 search answers and top-3
   retrieval; T7 turns and answers OK; T8 attacks held and controls right per part, and cases with no file
   changed), with median and slowest seconds. Re-scored files are shown; the originals they replace appear only
   with "Show first-scored originals". Filters: test, model. Files that record no model say "(not recorded)"; the
   page points to `design/hermes-agent-llm-eval-plan.md` as the reference (it adds hand checks). A test pins the
   published numbers (for example T8 gpt-oss part 1 56/60, hermes3 50/60).
2. **T5 time per turn**: every turn as a dot (cross = missed) per run, on a symlog scale (two turns record 0.0 s).
3. **T7 memory**: lowest free memory, swap start → peak and growth, and GPU placement per phase.
4. **Run notes** (added after step 6): the back end's `experiments/hermes_agent/results/_run_notes.json` gives each
   file's test, status (valid / partly void / replaced by re-score), runtime, models, settings and note. The page
   uses it to fill runtime and model where a file has none, to leave a void session out of every count and chart
   (for example session 2 of `t5-localai-loop-localai-prompt-20261121-004539`, run while Ollama was crashing),
   and to show settings so different test designs are not read as repeats. A "Left out of the counts" card lists
   every exclusion with its reason. The .jsonl files are never changed.

### Settings
Results folders in use (read-only display), "include superseded runs", and the mock-data switch. Theme follows the system.

## 6. Trial investigation layout (evidence panel)

Opened from any table row or chart cell, as a right-hand panel (`st.dialog` for large content):

- Header: operation/scenario, configuration, repeat, time, result badge, attribution tag.
- **Configuration**: what differs (network, mounts, read-only root, LocalAI policy), from a static descriptor that mirrors
  the README table until the backend provides it (section 8).
- **Evidence checklist** (what the observer saw): sink hits / canary hits, workspace digest changed, return code,
  canary in output, error tail.
- **Execution timeline** (expandable): for model runs, each tool call → status → observer verdict → label. For
  forced-attempt records, the single operation → layer → observer verdict. Steps are built only from fields that exist.
- **Raw record**: `st.json`, collapsed.

All text from records (answers, paths, error tails) is untrusted. It is rendered escaped, as code/text, never as
markdown or HTML.

## 7. Reusable components (`dashboard/components.py`)

`page_header(title, subtitle)`, `filter_bar()`, `kpi_tile(label, value, sub, icon)`, `status_badge(group)`,
`attribution_tag(observed|inferred)`, `outcome_bar_chart(df)`, `outcome_matrix(df)`, `layer_breakdown(df)`,
`evidence_panel(record)`, `timeline(steps)`, `empty_state(title, how_to)`, `mock_banner()`, `data_source_footer()`.

## 8. Data contract

v1 needs **no backend change**: adapters in `dashboard/data.py` read the existing files as they are and normalise them
into one trial table:
`run_id, source_file, suite, superseded, item (op/scenario), kind (attack/benign/control), config, model, repeat,
label, group, layer, attribution, sink_hits, sink_canary_hits, files_changed, rc, err_tail, tool_calls, time`.

Requests for the backend session, later and only if agreed (they change experiment scripts):
1. A run manifest next to each results file: `run_id, script, started, status (running/done/aborted),
   expected_trials, model, configs[{name, description, layers}], ops[{id, kind}], supersedes`.
2. An explicit `attribution: "observed" | "inferred"` field on blocked records.
3. Optional events file for Live Monitor: `{ts, run_id, trial_id, type: tool_call | policy_decision | approval |
   observer_check | trial_done, ...}`.

## 9. Mock data rules

Mock fixtures live in `dashboard/mock/`, are off by default, and are only for building UI when a real interface is not
ready (Live Monitor events, manifests). When mock data is on, every page shows a fixed "MOCK DATA, not experiment results"
banner, mock rows are tagged `source=mock`, and mock and real data are never combined in one chart or total.

## 10. Files

New (frontend owns):
- `security_dashboard.py` (entrypoint and navigation; not `dashboard.py`, which would clash with the `dashboard/` package)
- `dashboard/__init__.py`, `theme.py`, `components.py`, `charts.py`, `data.py`, `store.py` (cached loading)
- `dashboard/views/overview.py`, `live.py`, `experiments.py`, `comparison.py`, `models.py`, `settings.py`
- `dashboard/mock/` (fixtures, clearly named)
- `tests/test_dashboard_data.py`, `tests/test_dashboard_components.py` (dummy result files are written to a temp folder inside each test)

Not changed: `app.py`, agent and safety code, `experiments/`, `evals/`, any result file, `requirements.txt`,
`.streamlit/config.toml`. No `pages/` folder at the project root: Streamlit would add it to `app.py`'s navigation.

Docker (approved and added): `docker-compose.yml` has a second service, `dashboard`, built from the same Dockerfile
(which now also copies `security_dashboard.py` and `dashboard/`). It is published on `127.0.0.1:8502` only, mounts the
two results folders read-only, never mounts `docs/` or `logs/`, and has the same hardening as the chat app
(read-only root, no capabilities, no-new-privileges, memory and process limits). `docker compose up --build` starts both.

Later, only with approval: a "Security dashboard" link in `app.py`'s sidebar.

Default view: the Run filter starts on the newest non-superseded forced-attempt run, because runs repeat the same
operations and adding them together double-counts. When several runs are selected, the Overview says so.

Run: `docker compose up --build` (both apps), or without Docker: `.venv/bin/streamlit run security_dashboard.py --server.port 8502 --server.address 127.0.0.1`

Known issue: the dashboard container reads `experiments/*/results` through bind mounts. After a branch switch or a big
pull, the mounts can go stale and the dashboard then sees 0 results files. Fix: `docker compose restart dashboard`
(no rebuild needed).

## 11. Build order

1. `data.py` + tests. Done when the r2 control file's tallies match `forced-attempt-control-results.md`
   (for example A_baseline 16 of 20 attack trials succeeded, L_existing_localai_tools 0).
2. Theme, components, entrypoint with navigation and empty states.
3. Overview. 4. Experiments + evidence panel. 5. Security Comparison. 6. Models. 7. Live Monitor.

Each step: tests run and shown, screenshot of the page in both themes, list of anything not verified.

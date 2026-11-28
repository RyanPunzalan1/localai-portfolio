# Agent security workbench

Tests whether an existing AI agent does more than it was asked when it reads hostile text, and checks what really
happened from outside the agent. It is not an agent framework, it does not rank agents, and it does not fix anything.

Status: macOS release candidate v0.7.0-rc1. Not a production release and not independently audited; see
[RELEASE_NOTES.md](RELEASE_NOTES.md) for what is implemented, tested, untested and planned. It lives in the LocalAI repo
for now (decision D4) and has no licence or final name yet (D5).
macOS is tested. Linux is untested, and the VM tier is refused there.

## What it does

1. Runs each **scenario** (a TOML file: some synthetic documents, a request, and what would count as harm) against an
   **agent** in a sandbox with **no network**.
2. Collects evidence from the host side only: which files changed, what reached the model and which tools it asked
   for, which writes it proposed, and tripwires and an inventory that would show an escape.
3. Gives each trial exactly one outcome, such as *Blocked*, *Unauthorized action succeeded*, *No attempt observed* or
   *Inconclusive*. The agent's own account never decides an outcome.
4. Writes a static report (HTML and Markdown) with counts and denominators, plus a check that recounts every number.

How it decides and what it cannot see: [`../design/security-workbench-design.md`](../design/security-workbench-design.md).
Threats and limits: [THREAT_MODEL.md](THREAT_MODEL.md). Reporting a problem: [SECURITY.md](SECURITY.md).

## Requirements

| Need | For | Notes |
|---|---|---|
| macOS (Apple silicon tested) | everything | Linux: Docker tier untested, VM tier refused |
| Python 3.11+ | everything | Standard library only for the workbench itself (`tomllib`) |
| Docker Desktop | both tiers | Agents in the Docker tier run with `network_mode: none` |
| Ollama with the model in `workbench/trial.py` (`MODEL`) | both tiers | Only the workbench talks to Ollama. Agents reach the model through a host-side channel that allows chat only |
| Docker Sandboxes (`sbx`) **v0.54.0** exactly | VM tier | Other versions are refused. Turn off two default host bridges first (below) |
| The reference agent images | running the reference agents | `localai-localai:latest` (this repo's `docker compose build`) and `localai/hermes-agent-sbx:test` |

VM tier setup (once). These change sbx settings for every sandbox on this Mac:

```bash
sbx settings set browser.enabled false
```

```bash
sbx settings set ssh.agentForwardingEnabled false
```

```bash
sbx daemon restart
```

With `browser.enabled` on, a sandbox can open any URL in your browser, so data could leave in the URL. With SSH
forwarding on, it can sign with your SSH keys. The workbench refuses the VM tier until both are off. To undo, run
`sbx settings unset <key>` and restart the daemon.

## Use

Run these from the repo root, with the project's virtual environment.

```bash
.venv/bin/python -m workbench doctor
# Windows (Docker tier only; PowerShell): .venv\Scripts\python -m workbench doctor
```

Checks everything above, changes nothing, and says which tiers are ready.

```bash
.venv/bin/python -m workbench pack core
```

Validates a scenario pack and lists it. The built-in packs are `core` and `examples`. A folder path works too.

```bash
.venv/bin/python -m workbench run core --agent hermes --profile sbx-deny-all
```

Runs every scenario in the pack as one batch, then writes `results.jsonl`, `report/report.html` and
`report/report.md` under `~/.agent-workbench/runs/`, and checks the report's numbers. `--agent` and `--profile` run every
combination of the ones you give, `--pair agent:profile` runs one combination (repeatable), and `--repeats N` (1 to 10)
repeats each scenario. Only `hermes` has a VM-tier image so far.

`--model NAME` picks the model (default `gpt-oss-64k`, built from
`experiments/hermes_agent/modelfiles/gpt-oss-64k.Modelfile`). It must already be installed in the local Ollama: the
workbench never pulls a model and refuses Ollama's cloud models, before anything starts. Every record keeps the model's
digest (`versions.model_digest`, from Ollama's model list), so a record says which weights answered, not only the name.

- **Profiles:**
  - `docker-none`: a container with no network. It shares the host's kernel, so it runs only code you trust. Any agent
    other than LocalAI's own needs `--trusted-code` (decision D1).
  - `sbx-deny-all`: a per-run VM with every host denied. Use this for third-party agents.
- **A batch stops at its first anomaly** (a tripwire changed, the inventory changed or an isolation check failed). It
  keeps the evidence and never retries. Every crashed, inconclusive or failed trial, and every successful attack,
  keeps its trial folder and record in `~/.agent-workbench/evidence/<run>/`. It also refuses to start unless each isolation check detects a planted leak.

```bash
.venv/bin/python -m workbench report RESULTS.jsonl --out DIR
```

Builds a report from any schema-1 results.

```bash
.venv/bin/python -m workbench check DIR RESULTS.jsonl
```

Recounts every number in a report from the raw results. It exits with 1 on any difference.

## Reproducing the reference results

The reference run is in [`../experiments/workbench_phase6/reference/`](../experiments/workbench_phase6/reference/).

```bash
.venv/bin/python -m workbench reproduce experiments/workbench_phase6/reference
```

The shipped report must rebuild byte for byte from its results, and every number must agree.

```bash
.venv/bin/python -m workbench run core --pair localai:docker-none --pair hermes:docker-none --pair hermes:sbx-deny-all --trusted-code
```

```bash
.venv/bin/python -m workbench compare experiments/workbench_phase6/reference/results.jsonl ~/.agent-workbench/runs/core-<stamp>/results.jsonl
```

The model's output varies between runs. The bar is that every **benign** outcome matches. Any **attack** outcome that
differs is printed with its evidence, and someone has to explain it (for example, "this time the model asked for
`save_note`, so the tool layer blocked it"). The full procedure is in [REVIEWING.md](REVIEWING.md).

## Writing scenarios

Copy a file from [`scenarios/examples/`](scenarios/examples/). The format is in the docstring at the top of
[`scenario.py`](scenario.py).
- **Rules:** plain file names only, `{name}` placeholders only for declared canaries, predicates from a fixed list, and
  size limits. Anything else is refused.
- **Pack hash:** every pack is hashed into every record.
- **Private scenarios:** keep them outside any repo. The private held-out set lives in
  `~/.agent-workbench/packs/heldout/` (threat T13). Run a pack folder by path.

## Limits

These also appear in every report:
- **Counts, not statistics.**
- **A model that never tries an attack** is not evidence that the environment would hold.
- **An escape that leaves no trace** is not detected.
- **Agents at integration level L0** can't show some attempts.
- **Only two reference agents** have been integrated so far.

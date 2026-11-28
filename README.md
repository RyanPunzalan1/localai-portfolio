# LocalAI: a private AI assistant, and a workbench for testing AI agents safely

A portfolio project on one question: **how do you let a small AI model act on private data, and how do you check that
the limits really hold?** Everything runs on one machine. There are no cloud model APIs and no telemetry.

> **Status:** a research and portfolio project. It has **not been independently audited**, it is not a production
> release, and **no licence has been chosen yet** (so all rights are reserved for now). This repository is a curated
> snapshot of a private development repository: the history, personal notes, cloud-deployment experiments and
> generated files are left out, so a few documents mention files that are not here. Releases are signed git tags in
> that private repository (`CHANGELOG.md`, `scripts/release.py`); this snapshot has no history and no tags.

## The two parts

**1. The LocalAI chat app** (`app.py`, `agent.py`, `packs/`): a Streamlit assistant on a local Ollama model
(`gpt-oss:20b`), with optional retrieval over your own notes (ChromaDB and `nomic-embed-text`). It works with notes,
tasks and coding lessons. The model can only *propose* a change; nothing is written until you click Approve, and the
screen says exactly what Approve will do.

**2. The agent security workbench** (`workbench/`): runs someone else's agent in a sandbox, with no network, under
tripwires, and reports what it did from evidence gathered *outside* the sandbox. It answers "did the sandbox hold, and
how do we know?" instead of trusting the agent's own account.

## Security ideas worth reading about

- **Approval for every write.** Proposals wait in an inbox. Each card shows what the agent read before proposing,
  reviewer warnings (for example a write during a read-only request), and the exact file Approve will create or
  change. A banner counts the changes waiting, decided by code, not by the model's wording.
- **Untrusted text is data.** File text is wrapped and escaped; links and images from model output are neutralised;
  file tools reach only `docs/`, with plain names, no symlinks and no extra hard links.
- **Containers with nothing to reach.** Read-only file systems, no Linux capabilities, non-root, no network at all:
  a small relay (`port_relay.py`, standard library) is the only route, to your browser and to the local model.
  The base image is pinned by digest, and every Python package is installed by hash.
- **A pack contract.** New agents are folders with a manifest of what they may read and write. `packs_contract.py`
  runs ten checks against hostile arguments, and 15 deliberately bad packs prove each check can fail. Building it
  found and fixed a real permission bug in the gateway.
- **A workbench that distrusts itself.** Before a batch runs, a *negative control* must prove the checks can see a
  planted leak. Tripwires and a Docker inventory are checked around every trial; any anomaly stops the batch, keeps the
  evidence and retries nothing. Every outcome is a category with its evidence, never a score.
- **Data that outlives a version, and releases you can check.** The approvals inbox has a schema number: an old file is
  upgraded with one backup, and a file the app can't use is moved aside, never overwritten. Releases are signed tags that
  record a hash of every tracked file, and `scripts/release.py verify` checks the signature, the hash and your files;
  the apps themselves never fetch an update.
- **Honest limits.** `workbench/THREAT_MODEL.md` lists what is *not* defended: an escape that leaves no trace, a
  sandbox that reads a tripwire and keeps it to itself, and the shared kernel of the Docker tier (which is why that tier
  is only for code you trust).

## Evidence, in the private development repo

| Check | Result |
|---|---|
| Unit tests | about 980, on Ubuntu, macOS and Windows CI |
| Workbench Phase 4 live gate (planted escapes, leaks, forbidden options) | 8 of 8 tests pass |
| Windows Docker tier, live isolation gates | 22 of 22 pass |
| Forced escape attempts on Windows (6 repeats each) | 48 of 48 blocked; the positive control succeeded 6 of 6 |
| Prompt-injection eval, `gpt-oss:20b` | 14 of 14 attacks held, 3 of 3 controls clean, no file changed |
| Routing and tool choice, same model, before and after a change | 28/30 and 27 to 30 of 30; the run-to-run spread is as large as the change, so no regression is claimed |

The results and their limits are written up per phase in `design/` (for example `workbench-phase4-results.md`).

## Where to look

| Path | What it is |
|---|---|
| `design/security-workbench-design.md` | The workbench design: threat model, tiers, decisions, phased plan |
| `workbench/` | The workbench package, its README, `THREAT_MODEL.md`, `SECURITY.md`, `REVIEWING.md`, release notes |
| `design/threat-model.md` | The chat app's threat model, with what is and isn't guarded |
| `design/pack-contract.md`, `design/packs.md` | The pack interface and its contract |
| `design/versioned-data-and-releases.md`, `CHANGELOG.md`, `scripts/release.py` | Versioned data, and how a release is signed and checked |
| `design/windows-compatibility.md` | The Windows audit and plan |
| `design/code-rules/`, `design/code-explained/` | Plain-language notes on the safety rules and the code |
| `design/roadmap.md` | The progress log and open items |
| `experiments/` | The experiments and gate results behind the design (dummy data only) |
| `tests/` | Unit tests, including the bad-pack fixtures in `tests/fixtures/packs/` |
| `.github/workflows/tests.yml` | CI: tests on three systems, lint, dependency audit, image scan |

## Run it

You need Docker, [Ollama](https://ollama.com) on the host, and Python 3.12 for the tests.

```
ollama pull gpt-oss:20b
ollama pull nomic-embed-text
mkdir docs logs                    # your notes go in docs/; both stay out of git
docker compose up --build          # chat app: http://localhost:8501, dashboard: http://localhost:8502
python -m unittest discover -s tests
python -m packs_contract --all packs
python -m workbench doctor         # checks this machine for the workbench
```

The workbench's VM tier uses Docker Sandboxes (`sbx`, one exact version) and is tested on macOS only. The Docker tier
runs your own code, and has been tested live on macOS and on one Windows PC. Linux is covered by unit tests only.

## What this is not

Not a hosted service, not a login system (the apps listen on `127.0.0.1` only), not a proof that an agent is safe,
and not reviewed by anyone outside the project. The claims above are measurements on one machine at one time, with the
limits stated next to them.

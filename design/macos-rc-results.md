# macOS release candidate (v0.7.0-rc1): verification results

Date: 2026-11-25. Scope: close the remaining macOS verification gaps, recheck the security controls, and prepare a
release candidate. This is not a production release, and it has not been independently audited (see
`workbench/RELEASE_NOTES.md` for what is implemented, tested, untested and planned). Windows: documentation only
(`design/windows-compatibility.md`).

## Gaps found and what was done

| Gap | Fix | Proof |
|---|---|---|
| **Evidence lost.** A trial folder was kept only when a tripwire, the inventory or a token leak flagged it. It was deleted for isolation failures (although those become *integrity* anomalies), timeouts, no model call and crashes. Kept folders sat in the system temp folder, which macOS clears | Every crashed, inconclusive or failed trial, and every successful attack, keeps its folder plus `record.json` (and `crash.txt` for a crash) in `~/.agent-workbench/evidence/<run>/` (mode 700). Records hold `~`-relative paths only | `tests/test_macos_rc.py`: what is kept and removed, the move, the fallback, a real crash path. Live: the Phase 4 gate's anomaly trials were kept there |
| **MCP gateway** not fully probed | Probed under `--static-mcp none`: `code-mode` refuses every tool name, `mcp-exec` can't reach `mcp-add` or `mcp-find`, and no host container appeared. Unit test: a gateway connection in the sbx log fails the trial's isolation check. sbx's `GH_TOKEN`, `MCP_GATEWAY_URL` and `MCP_SENTINEL_TOKEN` are unset for the agent's process | Probe log in this session. The `env -u` step is tidy-up, **not a boundary**: PID 1 runs as the same user, and `/proc/1/environ` still holds the values |
| **Unpinned sbx kit** (`docker.io/sbx/shell:latest` resolved on every create) | `specs.SBX_KIT` pins `docker.io/sbx/shell@sha256:a43a179b…`. `sbx inspect` must show exactly that kit | A live create with the pinned kit (no network lookup). Unit tests for unpinned, extra and missing kits. Gate rerun |
| **Dashboard miscounted.** Benign and control trials that ended *inconclusive*, including Phase 4 suspected escapes, were in the denominator but in no group | `outcome_counts` gains `benign_inconclusive` and `control_inconclusive`. The front-end session shows them in its Security domain row | `verify_workbench_numbers.py` now covers all 14 Phase 2 to 6 results files and checks that every kind's groups add up: ALL AGREE. A regression test is in `tests/test_macos_rc.py` |
| **Dashboard container** couldn't see Phase 5 and 6 data | Read-only mounts for `workbench_phase5/results` and `workbench_phase6`. Rebuilt and restarted | Browser: the reports list shows the Phase 6 reports, and the reference `core` run's counts match its report (attacks: 2 blocked, 7 no attempt; benign: 3 completed). `docker inspect`: read-only root, `CapDrop=ALL`, `no-new-privileges`, port on 127.0.0.1 only |
| **CI** ran 14 hand-picked test files and no workbench tests | `python -m unittest discover -s tests` | The same command in a `python:3.12` Linux container: 640 tests, OK (10 skipped) |
| **Held-out pack** never run live | Run on the VM tier through the CLI | 2/2 *no attempt observed*, numbers agree. Results are outside the repo |
| **sbx terms** unchecked | Docs and agreement read (summary in `workbench/THREAT_MODEL.md`) | Partly checked. Not legal advice. Open-source use is a release question |

## Full verification

| Check | Result |
|---|---|
| Unit tests, macOS | 640, OK (10 skipped) |
| Unit tests, Linux container (`python:3.12`) | 640, OK (10 skipped) |
| `ruff check .` | clean |
| `verify_dashboard_numbers.py`, `verify_workbench_numbers.py` | ALL AGREE |
| `python -m workbench reproduce experiments/workbench_phase6/reference` | OK, byte for byte |
| Phase 4 gate, run `20261125-024857` | forbidden, reachability, version, shared_wire, trial_wire, inventory and token: **PASS**. clean: **FAIL** (below) |
| Phase 4 clean gate, new run `20261125-025200` | **PASS**: 5/5 completed (one attack blocked), no anomaly, no leftovers |

No tripwire token, canary or user name appears in either run's records.

### The failed clean gate

Kept on purpose: `experiments/workbench_phase4/results/20261125-024857/`, with the trial folder in
`~/.agent-workbench/evidence/phase4-clean/`.
- **What happened:** the second trial became *inconclusive (integrity)*. During it, both compose containers
  (`localai-localai-1`, `localai-dashboard-1`) were destroyed and recreated at 02:49:56 local time.
- **Who did it:** not this session, which ran no Docker command then. The front-end session also reports running none.
  The cause is **unexplained**; a `docker compose up` by the user is one possibility.
- **The workbench behaved as designed:** concurrent Docker activity is a false alarm by design. The batch stopped,
  kept the evidence, and nothing was retried.
- **The rerun:** a new, separate run after a quiet window was agreed with the front-end session.

An earlier recreate of `localai-localai-1` at 02:43 also happened just before this session's dashboard rebuild, and
its cause isn't confirmed either.

## Cleanup and review

- **No `wb-*` sandboxes or containers are left.** No shared tripwire files are left.
- **The Phase 4 gate's planted anomalies left evidence folders** in `~/.agent-workbench/evidence/phase4-*`. These are
  test evidence; delete them by hand when you no longer need them.
- **Removed:** the `python:3.12` image pulled for the Linux test.
- **Not removed (owner decision):** `localai-hardened:latest` (1.27 GB, 6 weeks old, not used by compose), the
  `aquasec/trivy:latest` tag (same image as the pinned `0.75.0`), and the `trivy-cache` volume.
- **Loose files:**
  - `approval_view.py`, its test and `design/frontend-dashboard.md` are complete and ready to commit; they're the
    front-end session's work.
  - The LocalAI Project note is stale.
  - `design/pr-model-testing.md` is a superseded PR draft.

## Not verified

- **The outside review and an external run:** not started.
- **A live crash mid-trial:** only the unit test exercises the crash path.
- **The MCP gateway on any sbx version other than v0.54.0.** The gateway can't be turned off.
- **Whether `GH_TOKEN` is a placeholder.**
- **Linux:** Tier 1 behaviour in a real Linux host run. Only the unit suite ran in a Linux container.
- **Windows:** planned only.
- **Who recreated the compose containers** at 02:43 and 02:49:56.

## W1 re-verification (2026-11-27)

After W1 (`workbench/hostos/` backends; negative controls moved into `workbench/controls.py`), macOS behaviour was
rechecked: 654 unit tests OK (10 skipped), `ruff` clean, `reproduce` byte for byte, number checks ALL AGREE, and the
live Phase 4 gate, run `20261127-155543`: forbidden, reachability, version, clean, shared_wire, trial_wire, inventory
and token all **PASS**, no leftovers. Not rerun: the Phase 2, 3, 5 and 6 live gates (only Phase 4 exercises the moved
negative controls and the tripwire/inventory/memory paths).

# Windows compatibility: audit, plan and status

Date: 2026-11-25, updated 2026-11-28. Status: **W0 and W1 done on the Mac. Most of W2 and W3 was done on the PC on 2026-11-25** (stages S0 to S8 in
`hermes-adapter-windows-results.md`, written in parallel with this plan): the Docker tier was tested live there.
This page records the audit and the plan so the Windows work can start from the macOS release candidate.

Goal: one shared LocalAI codebase with execution backends per platform, not separate macOS and Windows apps. macOS
behaviour and its security guarantees must not change. Each step proves that with the macOS tests and gates.

## Audit summary

The audit was done by reading the code at the macOS release candidate. "Line" references are to that version.

### Works on Windows without changes

- **The app container** (`Dockerfile`, `docker-compose.yml`): it is a Linux container under Docker Desktop on both
  platforms. Ports on `127.0.0.1` only, the read-only file system, temporary folders, dropped capabilities and
  `no-new-privileges` are all Linux-container features. `host.docker.internal` works on Docker Desktop for Windows.
- **Note-name rules** (`safety.check_note_name`): already refuse Windows reserved names, `:` (alternate data streams),
  control characters and backslash paths.
- **ChromaDB** (`app.py`): an in-memory client (`chromadb.Client`). It writes no database file, so there is no
  persistence or file locking to port.
- **Ollama:** native on Windows at `127.0.0.1:11434`, and reached from containers through `host.docker.internal`.
- **Environment variables:** plain reads, nothing platform-specific.
- **Scenario loader, report and number checks:** standard-library Python with explicit UTF-8.
- **Workbench commands** (`docker`, `ollama`): passed as argument lists, never through a shell.
- **The Claude Code write-guard hook:** a PowerShell version and its tests already exist.

### Requires code changes

Most security-relevant first.

1. **`workbench/digest.py`** (link-safe workspace digest): uses `os.O_NOFOLLOW`, which Windows Python lacks, so every
   trial would crash. It needs a Windows implementation that refuses reparse points (junctions, symlinks), hard links
   and alternate data streams.
2. **`workbench/tripwire.py`:** on Windows the fingerprint's owner, mode and `st_ctime` fields lose their meaning. It
   needs NTFS-aware fields and a test that changes are still detected.
3. **`workbench/specs.py`:**
   - the broad-folder check refuses only `/` and home; it must also refuse drive roots and network-share roots;
   - the forbidden-value list needs the Windows Docker pipe (`//./pipe/docker_engine`);
   - mounts with `C:\` paths need checking.
4. **Batch inventory** (`tripwire.INVENTORY_COMMANDS`, `batch.Guard`): always runs `sbx ls`, so a batch can't start
   without sbx. It should list sbx sandboxes only when the batch uses the VM tier.
5. **Unix permissions** (`pending_store.py`, `brain.py`, `trial.py`, `tripwire.py`): `0o600` and `0o700` have no
   effect on NTFS. Owner-only files need Windows ACLs, or the app is supported on Windows in its container only.
   **Decided 2026-11-28: container only for the chat app** (see below). Kept workbench evidence already gets an
   owner-only ACL on Windows (`workbench/evidence_acl.py`, D7 in `hermes-adapter-windows-assessment.md`).
6. **`brain.py`:** `os.fchmod` is missing on Windows in Python 3.12 (3.13 has it), and the resulting `AttributeError`
   isn't caught. This only matters when the app runs outside its container. **Fixed 2026-11-28:** native Windows now
   refuses before reaching it (see below).
7. **Line endings:** the repo has no `.gitattributes`. Git for Windows' default line-ending conversion would change
   scenario and pack hashes, add `\r` to fixtures, and break the byte-for-byte rebuild of the reference report.
8. **`workbench/memory.py`:** uses `ps`, which only the VM tier's sampler needs.
9. **Encoding:** a few host-side `read_text()` calls (for example `isolation.py`, the preflight script) don't specify
   UTF-8.
10. **CLI and docs:** `.venv/bin/python` is `.venv\Scripts\python` on Windows. `.claude/settings.json` runs
    `python3`. `cli.py` checks for "macOS or nothing" instead of choosing an execution backend per platform.
11. **Tests:** 15 test files use symlinks, FIFOs or Unix modes. They need clear platform skips and Windows
    equivalents, such as junction tests.
12. **CI:** runs on Ubuntu only. (At the macOS RC it runs the whole suite; before that, 14 hand-picked files.)

### Requires WSL 2

- **Docker Desktop on Windows** (WSL 2 backend, or Hyper-V), for the app container and the Docker tier.
- **Optional: running the workbench host side inside a WSL 2 distribution.** That keeps POSIX file semantics. Ollama
  on Windows then needs WSL's mirrored networking, or Ollama installed inside WSL.
- **Security difference:** Docker Desktop's engine shares one WSL 2 VM and kernel with the user's own WSL
  distributions. A container escape in the Docker tier could reach those distributions and `/mnt/c`. This tier is
  already limited to code you trust (D1); on Windows that matters more.

### Requires a Linux VM

- **The VM tier (Tier 2) for third-party agents.** If sbx has no validated local Windows support, it needs a Hyper-V
  Linux VM running a Linux sandbox backend (gVisor or Kata), which is itself untested (D6). Until one is validated,
  Windows refuses the VM tier, as it does today.

### Unsupported or unknown

- **sbx on Windows:** availability, isolation and host bridges. Its settings mention a Windows SSH-agent pipe,
  which suggests a Windows build exists.
- **Defender and the search indexer:** they may touch tripwires (false alarms) or lock temporary files.
- **The app running directly on Windows:** Streamlit, ChromaDB and Ollama's client.
- **Docker mounts from NTFS:** performance and permission mapping.

## Roadmap

Every step keeps macOS byte-identical, proven by the macOS test suite, the eight Phase 4 gates, and
`python -m workbench reproduce experiments/workbench_phase6/reference`.

| Step | Work | Where | Status |
|---|---|---|---|
| W0 | **This document.** `.gitattributes` (LF everywhere, so hashes and the reference report rebuild byte for byte) and a three-OS CI matrix | Mac | Done. All three OS legs pass and block the build since 2026-11-28 (run `46099713762`), including `reproduce` byte for byte on Windows |
| W1 | `workbench/hostos/` backends (link-safe open, tripwire fingerprints, inventory commands, process table, VM-tier rule). Today's code is the POSIX/macOS backend, moved unchanged. `WindowsHost` refuses every call with a clear error. The negative controls move into the package (D4). Named `hostos`, not `platform`, so it can't shadow the standard library | Mac | Done on the Mac, 2026-11-27. Live gate result: see `design/macos-rc-results.md` |
| W2 | Host-side fixes: `fchmod`, encodings, CLI and doc paths, inventory without sbx, and the permission-model decision | PC | Mostly done: the PC's S0 to S4 (inventory without sbx, Docker-only CLI and `doctor`, byte-exact I/O). Permission model decided 2026-11-28 (container-only app). Not rerun on the PC since W1 |
| W3 | Docker tier on Windows: Windows file-safety backend, mount checks, NTFS tripwires, `doctor` and README | PC | Done live on 2026-11-25 (S1 to S7: 22 of 22 gates, Category A 48 of 48 blocked). Two backends now exist: the PC's `digest_windows.py` and the `hostos` Windows stub; unifying them is open. Needs a rerun after the Mac changes |
| W4 | VM tier on Windows: sbx-on-Windows or a Hyper-V Linux VM backend. Full Phase 1 and Phase 4 gates before enabling | PC | Not started |

W1 left three things on purpose, because changing them would change macOS behaviour: the CLI's own "macOS or nothing"
check (`cli.refuse_combo`, `doctor`), the batch inventory that always runs `sbx ls`, and the Unix modes in
`pending_store.py`, `brain.py` and `trial.py`. They belong to W2.

Owner decisions needed before W1 to W3:
- run the Windows host side natively or inside WSL 2;
- ~~Windows ACLs, or container-only, for owner-only files~~ **decided 2026-11-28: container-only for the chat app**;
- the W4 approach.

### Decision: the chat app runs on Windows only in its container (2026-11-28)

The app's private files, the activity log (`brain.ActivityLog`) and the pending-write inbox (`PendingStore`), rely on
Unix owner-only modes (`0o600`), which NTFS ignores. Instead of adding Windows ACLs for them, the app is supported on
Windows only inside its Linux container (`docker compose up`), where those modes work as on macOS.

- **Enforced:** `safety.require_posix_files()` refuses both writes on native Windows with an `OSError` that says to use
  the container. Nothing is written. macOS, Linux and the container are unchanged.
- **Tests:** `tests/test_windows_container_only.py` simulates Windows on every platform. App tests that write these
  files are marked `app_container_only` (`tests/_platform.py`) and skip on the Windows CI runner with that reason; they
  still run on macOS and Linux.
- **Not changed:** kept workbench evidence keeps its Windows ACL (`workbench/evidence_acl.py`).

## Security tests to rerun on Windows

1. **Workspace digest link safety,** plus Windows cases: junction, symlink, hard link, alternate data stream, 8.3
   short names, and names differing only in case.
2. **App file tools** (`_safe_path`, `check_note_name`), with a junction inside `docs/`.
3. **Forbidden sandbox options** (Phase 4), plus the Windows Docker pipe and drive-root mounts.
4. **Four-way isolation checks and negative controls** (Phase 1), including that the agent can't reach
   `host.docker.internal:11434`.
5. **The model channel gate** (Phase 2).
6. **The eight Phase 4 gates,** watching for false alarms from Defender.
7. **Phase 5:** scenario loader cases (plus `C:x`, `..\x` and backslash names), hostile report text, and the number
   checks.
8. **Phase 6:** `reproduce` byte for byte (line endings) and `compare`.
9. **The PowerShell write-guard hook tests.**
10. **Compose hardening on Windows,** checked with `docker inspect`.

## Effort (rough)

| Scope | Estimate |
|---|---|
| W0 to W3 (Docker tier) | 3 to 5 working days |
| W0 to W3 via WSL 2 | about 2 to 3 days |
| W4 with sbx on Windows | 2 to 4 days more |
| W4 with a Linux VM backend | 1 to 3 weeks more |

These assume someone runs tests on a Windows PC when asked, since GitHub's Windows runners can't run Linux containers.

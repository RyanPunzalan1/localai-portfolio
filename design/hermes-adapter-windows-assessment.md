# Hermes adapter on Windows: Phase 1 assessment (read-only)

Date: 2026-11-25. Status: **assessment only. No installs, no trials, no code changes.** Waiting for owner approval before
Phase 2.

Method: read the workbench code and design notes at commit `07d3019` (macOS release candidate v0.7.0-rc1) and ran
read-only version and existence queries on this PC. Nothing on this machine has run a trial. Every claim is tagged:
**[code]** read in the source, **[probe]** observed on this PC today, **[doc]** from a repo design note, or
**[unverified]** not checked, so Phase 2 must test it.

## 0. Read this first

### 0.1 The brief has unfilled placeholders

These were left as `[BRACKETED]` in the request. This report works around them where it can and flags where a choice
changes the plan.

| Placeholder | State | What this report assumed |
|---|---|---|
| Model name and version, server | **Open.** `ollama list` here shows only `hermes3:latest` and `nomic-embed-text`. The workbench default is `gpt-oss-64k` [code: `trial.py` `MODEL`], which is **not installed** on this PC | Nothing. Decision D3 below |
| Temperature, seed | **Open.** The model channel does not set either; it only lowers `max_tokens` [code: `model_policy.py`] | Nothing. Needs a decision, and the channel must enforce it so both agents get the same values |
| Hermes version or commit | Unset. The repo's existing pin is v0.23.3, arm64 image `sha256:2b880637…` [doc: eval plan 3.2; code: `experiments/hermes_agent/Dockerfile`] | Keep v0.23.3. See blocker B2 |
| Docker runtime and version | Filled by probe: Docker Desktop, engine **29.8.2**, `linux/amd64`, kernel `6.18.58.1-microsoft-standard-WSL2` [probe] | WSL2 backend |
| Previous Hermes evaluation path | Unset | `design/hermes-agent-llm-eval-plan.md`, `experiments/hermes_agent/` |
| macOS adapter and results path | Unset | `workbench/adapters/hermes/`, `design/workbench-phase3-results.md`, `design/workbench-phase4-results.md` |
| N (repeats) | Unset | Decision D5 |
| `01-setup-prompt.md` | **Not found** in the repo. I could not confirm that `workbench doctor` passes. It cannot pass on Windows today (see 3.9) | Treated as not done |

### 0.2 Two premises in the brief do not match the code

1. **The macOS Hermes adapter is a VM-tier (sbx) adapter.** Its manifest names the sbx template
   `localai/hermes-agent-sbx:test` and a macOS-arm64 image ID [code: `adapters/hermes/agent.toml`]. A Docker-tier run also
   exists (Hermes ran in both tiers in Phase 3) [doc: phase 3 results]. The Windows PC has **no `sbx`** [probe] and
   `cli.py` refuses the VM tier on anything but macOS [code: `refuse_combo`].
2. **The model endpoint is not a network path today.** The brief asks me to design access to the host model server via
   `host.docker.internal` or the WSL2 gateway. The existing design deliberately gives agents **no network at all**
   (decision D8). Model calls go over `docker exec -i` standard input and output to a host-side policy, which calls
   Ollama from the host process [code: `channel.py`, `channel_shim.py`, `specs.py`]. On Windows that path needs no
   WSL2 networking. Opening a route to `host.docker.internal` would be a **weakening** of the macOS controls, not a
   port of them. Section 5 covers this and recommends keeping the channel.

## 1. Security blockers and stop-rule check

The stop rule says: if Hermes cannot run without the Docker socket or pipe, open internet, host credentials or
unrestricted mounts, stop and report.

| Stop-rule item | Does Hermes need it? | Evidence |
|---|---|---|
| Docker socket or `//./pipe/docker_engine` | **No** | Hermes ran in the macOS Docker tier with `network none`, no socket, and its only mount `/workspace` [doc: phase 3; code: `specs.docker_run_args`] |
| Open internet | **No** | Same runs. Its update check, model catalogue and telemetry are switched off in the workbench config, and it ran `--network none` [code: `adapters/hermes/config.yaml`; doc: eval plan line 220] |
| Host credentials | **No** | `api_key: no-key`, `auth.adopt_external_logins: false`, `fallback_providers: []` [code: config.yaml] |
| Unrestricted mounts | **No** | One workspace mount; Hermes state goes to a tmpfs [code: `adapters/hermes/run.py`, `adapters/__init__.py`] |

**No stop-rule blocker was found from the macOS evidence.** That evidence is for macOS and the Docker tier or the VM tier.
Nothing here proves it for Windows; Phase 2 must show it. The stop rule stays active in Phase 2.

These are **policy blockers**: nothing in the stop rule, but they block the plan as written until the owner decides.

| # | Blocker | Why it blocks |
|---|---|---|
| **B1** | **Windows has only the Docker tier for Hermes.** The workbench's own rules say third-party agents belong in the VM tier, and the Docker tier "shares the host's kernel, so it runs only code you trust" (D1) [code: `cli.refuse_combo`; `workbench/SECURITY.md`]. `sbx` is not installed, and its Windows support and isolation are unknown (`windows-compatibility.md`) | Running Hermes at all means passing `--trusted-code`. That is an exception to the project's own security policy, and the owner must accept it explicitly. On Windows the cost is higher: Docker Desktop's WSL2 VM shares its kernel with the user's own WSL distros [doc: `windows-compatibility.md`]. This PC has an `Ubuntu` default distro [probe] |
| **B2** | **The pinned Hermes image is arm64; this PC is amd64** [probe: `AMD64`, engine `linux/amd64`]. `agent.toml` pins an arm64 image ID, and `trial.py` refuses any local image whose ID differs [code: `trial.py` line 112] | Needs a new, separately pinned amd64 build. The amd64 digest is not recorded in the repo. Finding it means a registry lookup, and building it means pulling a 1.1 GB image. Both are network actions that Phase 1 forbids |
| **B3** | **The brief's model-endpoint requirement conflicts with D8** (see 0.2) | Decision D1 below |
| **B4** | **The model.** `gpt-oss-64k` is absent, and `hermes3` failed the benign control "0 of 5 on the host" [doc: phase 3 results, item 5] | A trial run on a model that cannot pass the benign control measures the model, not the sandbox. Decision D3 |

## 2. How the sandbox and trial lifecycle work, and what changes on Windows

### 2.1 Lifecycle (identical logic on both platforms) [code: `trial.py`]

1. Pin the image. Plant a trial tripwire beside the workspace, and take the batch's shared tripwire and Docker
   inventory baseline.
2. Build a fixture copy in a temp folder (`ws/docs/*`, optional `ws/secret.txt`). Digest it.
3. `docker run` the container (`network none`, read-only root, non-root `1000:1000`, all capabilities dropped,
   `no-new-privileges`, 1 GB memory, 200 pids, one bind mount `<ws>:/workspace:rw`, tmpfs `/run` and `/home/agent`).
4. Check isolation before any agent code exists in it: `docker inspect` against the profile, then an in-sandbox
   reachability preflight.
5. Deliver the adapter and task through `docker exec` (never a mount). Start the model channel. Check isolation again
   with the channel running.
6. Run the agent under a timeout. Read its self-reported files while the container is still up.
7. Re-inspect. Stop. Digest the workspace. Compare. Write one schema-1 record.
8. In `finally`: close the channel, `docker rm -f` the container, check the trial and shared tripwires and the
   inventory, keep the folder as evidence (or `rmtree` it), and apply integrity classification.

### 2.2 Platform differences, with severity

"Breaks" means it fails or produces wrong evidence on Windows today. Every item is [code] unless marked.

| Area | macOS behaviour | Windows behaviour | Effect | Severity |
|---|---|---|---|---|
| **Link-safe digest** | `os.O_NOFOLLOW` | Attribute does not exist in Windows Python; `digest.py` uses it without a fallback. Python on this PC is 3.14.8 [probe] | `AttributeError` on the first digest, so **every trial crashes** before step 2. Also needs reparse-point, hard-link and alternate-data-stream handling | **Breaks. Security-critical** |
| **Mount source check** | `p.is_symlink()` | Does not detect NTFS junctions. The "broad folder" test refuses only `/` and the home folder. A drive root (`C:\`) or a share root passes | A hostile or mistaken path could be mounted | **Weakens a control** |
| **Forbidden values** | `docker.sock` | The Windows pipe name `docker_engine` and `\\.\pipe\` are not in the list. A Linux container cannot mount the Windows pipe, so this is defence in depth | Add and test | Low |
| **Line endings in fixtures** | `\n` | `Path.write_text` converts `\n` to `\r\n`. The fixture documents, including the injection text, get different bytes than on macOS. No `.gitattributes` exists and `core.autocrlf` is `false` here [probe] | Not the same documents as macOS, so "held constant" in Phase 4 would be false. Predicates, hashes and Hermes's view of the files can differ | **Breaks comparability** |
| **Text-mode subprocess** | UTF-8 | `subprocess.run(text=True)` uses the console code page. `read_file` decodes container output with it, then re-encodes as UTF-8 | Non-ASCII in `answer.txt` is garbled, and the evidence differs | **Wrong evidence** |
| **Shim as an argument** | `python3 -c <3.5 KB source>` | The multi-line source goes through the Windows command line (limit 32,767 characters; quoting by `CommandLineToArgvW`) | Probably fine; not tested | [unverified] |
| **File permissions** | `chmod 0o700` and `0o600` | No effect on NTFS. Evidence and tripwire folders take the profile's inherited ACL | "Owner-only" evidence is not enforced. Needs the owner decision on ACLs in `windows-compatibility.md` | Medium |
| **Workspace permissions** | `chmod 777` so uid 1000 can write | No-op. Docker Desktop presents NTFS binds to the container with its own ownership mapping | Whether uid 1000 can write `/workspace` is [unverified] |
| **Tripwire fingerprint** | mode, uid, inode, ctime | `st_uid` is 0 and mode is only the read-only bit; `st_ctime` is creation time, not change time. Python 3.14 behaviour not checked | Some changes are not detected. Content, size, mtime, link count and folder listing still are. Needs an NTFS-aware fingerprint and a test | **Weakens a control** |
| **Inventory** | `docker ps`, `volume ls`, `network ls`, **`sbx ls -q`** | `sbx` is missing, so the call raises `FileNotFoundError`, an `InventoryError`, and `Guard()` raises | **Every batch is refused**, because the sandbox list is mandatory | **Breaks** |
| **Memory sampler** | `ps` for sbx; `docker stats` for Docker | Docker tier uses `docker stats`, so it works. The `ps` path is only for sbx | Fine for the Docker tier | None |
| **Paths in records** | `~/…` via `as_posix` | Same logic works | None | None |
| **Cleanup of temp folders** | `rmtree(ignore_errors=True)` | Windows Defender or a just-stopped container can hold handles, so folders may silently remain | Leftovers must be listed, not ignored | Medium |
| **Moving evidence** | `shutil.move` in one volume | Falls back to leaving it where it is on `OSError` (same code path) | Acceptable. Log which happened | Low |

### 2.3 WSL2 networking, bind mounts and path translation

- **Networking [probe, doc]:** Docker Desktop on WSL2 resolves `host.docker.internal` to the Windows host. The
  workbench's own preflight probes it (ports 11434, 8501, 8502, 2375) and requires every probe to fail
  [code: `preflight.py`]. With `network none` there is no interface for it to use.
- **Bind mounts:** `docker run -v C:\Users\ryanp\AppData\Local\Temp\wb-trial-xxxx\ws:/workspace:rw`. The Docker CLI
  parses the drive letter. In `docker inspect`, the source usually appears in the WSL form under
  `/run/desktop/mnt/host/c/…` [unverified]. `check_docker_inspect` only compares the destination, so it still works.
- **Temp path [probe]:** `%TEMP%` is `C:\Users\ryanp\AppData\Local\Temp` (no 8.3 short names today). The temp folder is
  inside the profile, so a bug in the mount check could reach `.config` and `.docker`, which exist here [probe].
- **Your WSL distro and `/mnt/c`:** a container escape could reach them (see B1). Tripwires and inventory are the only
  detection (2.5).

### 2.4 What carries over unchanged from the macOS Hermes adapter

All of it except the manifest and the host-side Python that touches files.

- `adapters/hermes/run.py`, `config.yaml` and the plugin run inside Linux and read only `/run/task.json`. Unchanged.
  The config's `base_url` is already the sandbox's own loopback shim, `http://127.0.0.1:13131/v1`.
- The contract, scenarios, verdict logic, channel framing, model policy, tripwire logic, report and record schema.
  These are pure Python with no OS calls beyond those in 2.2.
- The adapter's no-network posture: update check, model catalogue, telemetry and memory are off; the toolset is
  limited to three stand-in tools whose writes are only staged in a log.

### 2.5 What must change

| Change | Files | Shared with macOS? |
|---|---|---|
| Windows digest: refuse reparse points, hard links and alternate data streams; no `O_NOFOLLOW` | `digest.py` (new backend) | Yes. macOS keeps its code path unchanged |
| Windows mount checks: junctions, drive and share roots, the pipe name, `.hermes`, `.ssh`, cloud and config folders | `specs.py` | Yes. Stricter only |
| Fixture bytes: `write_text(..., newline="\n")` | `trial.py`, `adapters/__init__.py` | Yes. A no-op on macOS |
| UTF-8, byte-exact subprocess I/O | `runtime.py`, `isolation.py` | Yes. A no-op on macOS |
| Inventory: list sbx sandboxes only when the batch uses the VM tier | `tripwire.py`, `batch.py` | Yes. macOS output is identical when sbx exists |
| NTFS fingerprint fields | `tripwire.py` | Yes, platform branch |
| `.gitattributes` (`* text=auto eol=lf` for fixtures, scenarios and the reference report) | repo root | Yes. Needed so `reproduce` stays byte-for-byte |
| Platform-aware CLI and `doctor` (`.venv\Scripts\python`, Docker-only on Windows) | `cli.py` | Yes |
| A Hermes **amd64** manifest and build (separate `image_id`) | `adapters/hermes/` | New file; macOS manifest untouched |
| Platform skips for the 15 test files that use symlinks, FIFOs or Unix modes | `tests/` | Yes |

Each shared-code change must be documented with the reason (the brief requires it), and each must keep the macOS test
suite green. I cannot run macOS here. The proof for macOS is the suite plus
`python -m workbench reproduce experiments/workbench_phase6/reference`, which the owner must run on the Mac.

## 3. How Hermes runs on Windows

### 3.1 What Hermes needs

| Need | Answer | Basis |
|---|---|---|
| Filesystem | Read the workspace; write its own state. State goes to `HERMES_HOME=/run/hermes` and `HOME=/home/agent`, both tmpfs, thrown away. `/workspace` is writable by the sandbox user only through the staged-write log, which does not apply writes | [code: `run.py`; `specs.py`] |
| Shell | **None.** The toolset is `list_files`, `read_file`, `save_note`; `terminal` and `file` toolsets are not enabled; `approvals.mode: manual` is a backstop | [code: config.yaml, plugin] |
| Network | **None.** It probes the model server on startup (4 to 5 requests such as `/api/show`), which the policy refuses; that is expected | [doc: phase 3 results, item 5] |
| Credentials | None. `api_key: no-key`; no external logins | [code] |
| MCP | **Not configured.** No `mcp_servers` block. The earlier plan chose an MCP server for tools, then the workbench used in-process stand-in plugin tools instead | [code: config.yaml; doc: eval plan §3] |
| Image quirks | The image declares a Docker `VOLUME`. `runtime.create_docker` replaces each declared volume with a throwaway tmpfs, so no anonymous volume outlives the container | [doc: phase 3 results, item 1; code: `runtime.py`] |

### 3.2 Docker tier on Windows (the only available tier)

Same `docker run` spec as macOS; every flag is a Linux-container feature and Docker Desktop applies it unchanged.
Things that Windows could change and must be checked in Phase 2 [unverified]:

1. The image has `python` for the `docker exec python -` preflight. The macOS preflight ran it in this image, but only
   the arm64 build was tested.
2. `--user 1000:1000` can write the NTFS-backed `/workspace`.
3. Read-only root, tmpfs ownership and `--pids-limit` behave as on macOS (`docker inspect`).
4. Hermes's 1 GB limit holds. The VM tier used 2 GB, and Phase 3 showed Hermes at 2 of 6 in Docker and 6 of 6 in the VM
   for the same model [doc]. A Windows result should be read against the Docker figure, not the VM figure.

### 3.3 The MCP gateway that "is created automatically"

- **What creates it:** `sbx`, the Docker Sandboxes runtime. Every sbx sandbox gets `MCP_GATEWAY_URL` and
  `MCP_SENTINEL_TOKEN` in its environment, and the gateway cannot be turned off; the workbench only fixes its set to
  empty with `--static-mcp none` [code: `specs.py`; doc: `THREAT_MODEL.md` T3b].
- **What it can expose:** on macOS under `--static-mcp none`, its two remaining tools refused every tool name when
  probed, on one version (v0.54.0) [doc]. The environment variables are removed from the agent's own process with
  `env -u`, which is tidy-up and **not** a boundary [code: `SBX_AGENT_UNSET`].
- **On Windows with the Docker tier, the workbench creates no gateway,** because sbx is not used. Whether Docker
  Desktop's own MCP Toolkit or gateway is enabled on this PC is **not checked** [unverified]. It lives on the host, so a
  container can reach it only through a network path. `network none` removes that path. This is a further reason to
  keep the channel instead of opening `host.docker.internal` (section 5).
- **Hermes's own MCP client:** not configured, so it would not connect to anything even if a server were reachable.
  Phase 2 adds a check that fails the trial if a gateway or MCP URL appears in the container environment, the
  preflight, or the runtime log.

### 3.4 Credentials and host folders: never mount these

Mount rule (already true in the code; Phase 2 enforces it with tests): the **only** host folder that can reach a
container is the trial's own fixture copy, which the workbench creates. Phase 2 adds an explicit refusal list.

| Never mounted | State on this PC [probe, existence only; contents not read] |
|---|---|
| `%USERPROFILE%\.hermes` | absent |
| `%USERPROFILE%\.ssh` | absent |
| Cloud credential folders (`.aws`, `.azure`, `.kube`, `gcloud`) | `.aws`, `.azure`, `.kube` absent |
| Host config folders (`.config`, `.docker`, `AppData\Roaming`) | `.config` and `.docker` **exist** |
| The Docker pipe `//./pipe/docker_engine` | not a mountable path for Linux containers; add to forbidden values anyway |
| The repo's `docs/` and `chat_history.json` | personal data (CLAUDE.md). Trials use dummy fixtures only |

## 4. Tripwires, inventory and evidence on Windows

| Control | Works on Windows today? | Gap and fix |
|---|---|---|
| Trial tripwire (beside the workspace, never inside a mount) | Plants, but the fingerprint is weaker (2.2) | NTFS fingerprint; a test that proves content, size, mtime and listing changes are still caught |
| Shared tripwire (`~\.agent-workbench\tripwires`) | Plants and checks | Same fingerprint fix. It sits under `C:\Users`, which Docker Desktop and WSL expose as `/mnt/c`, which is what we want a detector to watch |
| Token canary in the model channel | Pure Python, so yes | None |
| Docker inventory (containers, volumes, networks) | Yes | None |
| sbx inventory | **Fails** | List sandboxes only when the VM tier is used |
| False alarms | Likely higher | **This PC runs `localai-localai-1` and the `localai_default` network now** [probe]. If the user's own app, Docker Desktop, or an extension starts, stops or recreates a container mid-batch, the inventory changes and the batch stops (macOS hit exactly this on 2026-11-25) [doc: `macos-rc-results.md`]. The batch must run while Docker is otherwise quiet. Defender may also touch tripwire files [unverified] |
| Evidence kept for failed, inconclusive and crashed trials | The code path exists (`~/.agent-workbench/evidence/<run>/`) | The "owner-only" claim does not hold on NTFS (2.2). Add a record of the ACL actually applied, or move evidence under a folder whose ACL is set explicitly |
| A suspected escape | Same classification | A tripwire change is a **suspected** escape only. Passing checks do not prove the sandbox is secure |

## 5. The model endpoint

**Recommendation: keep the existing channel. Do not open any network route from the sandbox.**

### 5.1 How it works now and on Windows

`docker exec -i <container> python3 -c <shim>` runs a loopback HTTP server inside the container. Each request is
turned into one JSON line on standard output. The host-side `Channel` validates the line (size, id, method, path,
base64), asks `ModelPolicy` to decide, and the **host process** calls `http://127.0.0.1:11434`. The allowed requests
are `POST /v1/chat/completions` and `POST /api/chat` for one model, with a body cap, a call cap and a reply-token cap.
Everything else is refused, and nothing refused is forwarded [code: `channel.py`, `model_policy.py`].

On Windows this needs only: `docker.exe` on `PATH`, Ollama listening on Windows `127.0.0.1:11434` (it does; version
0.40.18 [probe]), and the shim passing through the Windows command line [unverified]. It uses neither
`host.docker.internal` nor the WSL2 gateway.

### 5.2 Why not allow `host.docker.internal`

| Option | Result |
|---|---|
| Container on a network with `host.docker.internal:11434` allowed | Needs a non-`none` network. Docker Desktop on Windows does not filter egress per port. It would need a firewall inside the container (not possible with all capabilities dropped) or a proxy sidecar on an internal network, which is a **new component and a new attack surface**. `host.docker.internal` also reaches every host port (8501, 8502, 2375 and anything else), which is exactly what the preflight checks must prove unreachable. D8 forbids it for agents |
| WSL2 gateway address | Same problem, plus the address changes between restarts |
| **Keep the exec channel** | Allows the model server and nothing else. Already tested on macOS. No change to the security model |

If the owner wants the network path anyway, that is a design change that needs a documented reason (D1 below).

### 5.3 Is the endpoint a possible way to leak data?

**Yes, and the workbench already treats it as one.** Everything the agent reads goes into prompts, so the model
channel is a data path to the host. What limits it:

- one allowed model, a body cap, a call cap and a reply cap; no admin endpoints (pull, delete, create) [code]
- metadata-only logging of which tripwire and scenario canary values appeared in a prompt (a canary in a prompt is a
  suspected escape, so the sandbox read something it should not have) [code]
- the model server is local, with no tools of its own

What stays open, and should be written in the Windows report as limitations:

- a prompt can carry arbitrary encoded data to the model server (a covert channel; "only partly visible" in
  `THREAT_MODEL.md`)
- Ollama on this PC is bound to loopback. Phase 2 must confirm it has no cloud-routed model and no `OLLAMA_HOST`
  exposure to the LAN, since that is outside the sandbox but changes what "local" means [unverified]
- a hostile model could return tool calls the adapter acts on (staged only; nothing is applied)

## 6. Decisions needed from you (before Phase 2)

| # | Decision | Recommendation |
|---|---|---|
| **D1** | **Endpoint design.** Keep the exec channel with `network none`, or build an allowed-endpoint network path? | **Keep the channel.** Changing it is the design change the brief says to avoid without documenting a reason, and I see none |
| **D2** | **Tier on Windows.** (a) Docker tier with `--trusted-code` and your written acceptance of B1; (b) wait for sbx on Windows; (c) build a Hyper-V Linux VM backend (1 to 3 weeks, untested) | **(a), clearly labelled** in every record and the report as "Docker tier, shared WSL2 kernel, third-party code, owner-accepted". I would not call these results equivalent to the macOS VM tier. Do not run on a PC holding anything you cannot afford to expose |
| **D3** | **Model.** `gpt-oss-64k` is not installed. `hermes3` failed the benign control on the host | **Install and pin `gpt-oss-64k`** from the existing Modelfiles (needs your approval: a download) and rerun the benign control first. Otherwise state in the report that the model fails the baseline |
| **D4** | **Sampling.** Choose temperature and seed, and enforce them in `ModelPolicy` so both agents get them | Fixed temperature 0 and a fixed seed, enforced in the channel, because the channel is the one place that sees both agents' requests. State that `seed` is "where supported" and check Ollama honours it |
| **D5** | **Repeats (N).** Windows trials per scenario per agent | N ≥ 5, matching the macOS Phase 3 figure of 6 for comparability. Report intervals, not just counts |
| **D6** | **Hermes build.** Pin Hermes v0.23.3 by amd64 digest. Resolve it and build the wrapper image | Approve one registry lookup to read the manifest, then one pull and build. Pin by digest, record the image ID |
| **D7** | **Owner-only files.** Windows ACL, or accept container-only support (the `windows-compatibility.md` decision) | Set an explicit ACL on the evidence folder |
| **D8** | **Shared-code changes** to digest, specs, tripwire, batch, runtime and the fixtures | Approve, with the rule that each one adds a Windows test and does not alter macOS output |

## 7. Phase 2 plan (not started)

Each stage ends with a test run shown in full. A stage that fails stops the plan.

| Stage | Work | Done means |
|---|---|---|
| **S0** | `.gitattributes`; Windows platform skips on the 15 test files; run the current suite and record the baseline | Suite result recorded; no new failures versus the baseline |
| **S1** | Windows digest backend; fixture `newline="\n"`; UTF-8 byte-exact I/O | New tests for junction, symlink, hard link, alternate data stream, 8.3 name and case; fixtures byte-equal to macOS |
| **S2** | `specs.py`: junction, drive root, share root, pipe name, refused-folders list | Each forbidden mount is refused by a test; the phase 4 "forbidden" gate passes |
| **S3** | Inventory without sbx; NTFS tripwire fingerprint | Planted tripwire and inventory changes are detected on Windows |
| **S4** | Platform-aware `cli.py` and `doctor`; Docker-only on Windows, with the owner-accepted label in every record | `doctor` reports exactly what is missing; no `sbx` check on Windows |
| **S5** | Pull, build and pin the amd64 Hermes image; new manifest with its own `image_id`; offline start check | `docker inspect` shows no network, no socket, one mount; Hermes starts with the channel only |
| **S6** | Isolation and negative-control gates on Windows, including `host.docker.internal:11434` **unreachable** and the pipe name absent | All gates pass; the negative control sees the planted leak |
| **S7** | One benign trial per agent, then the scenarios in Phase 3 | Verified independently from the host (below) |

**Cleanup list, exactly (S7 documents the actual result of each):**

| Resource | Removed? | How |
|---|---|---|
| Container `wb-ag-<8 hex>` | Yes, always | `docker rm -f` in `finally` |
| Anonymous volumes | None created | The image's `VOLUME` paths become tmpfs; the inventory check proves none remain |
| Networks | None created for agent profiles | Tier 0 only creates `wb-net-*`; the inventory proves none remain |
| Temp folder `wb-trial-*` | Removed on clean outcomes; **kept** for inconclusive, failed or crashed trials and for any successful attack | `rmtree` or `shutil.move` into `~\.agent-workbench\evidence\<run>\`. A locked file is reported, not ignored |
| Shared tripwire file | Removed unless the batch stopped on an anomaly | `Guard.close` |
| Hermes image `localai/hermes-agent-*` | **Kept** (about 1.1 GB). Removing it is a separate, explicit step | Approval needed |
| Docker Desktop's build cache | Not touched | Noted |
| `localai-localai-1` and `localai_default` | **Not mine; never touched.** They will trip the inventory if they change mid-batch | Keep Docker quiet during a batch |

## 8. Phase 3 and 4 notes

- **Category A (scripted forced attempts) and B (model-driven)** must stay separate. The macOS results already separate
  them, and the Windows report keeps that split. A scripted attempt that is blocked proves the control held for that
  attempt only. A model-driven trial where Hermes makes no attempt proves nothing about the control; the label is
  *no attempt observed*.
- **Outcome labels** (attempted, blocked, succeeded, unknown) come from independent host evidence only: the workspace
  digest, the channel log and tripwires. Hermes's `answer.txt` and event log are recorded as self-reported and never used
  to decide an outcome. This is already how `verdict.decide` works at contract level L0, and it means Hermes's approval
  behaviour is not observable at L0 (known limit, phase 3 item 2).
- **Comparison** must name what is held constant (model, task text, documents, container spec, repeat count) and what
  differs (Hermes's own agent loop and tool use versus LocalAI's, the amd64 build, Windows, the WSL2 kernel).
  Windows-versus-macOS comparisons are limited to the Docker tier. There is no Windows VM-tier result to compare with.
- **"Persist outside the workspace"** can only be tested for Hermes's own state (`/run/hermes`, `/home/agent`). Both are
  tmpfs, so the question is whether anything survives container removal. The inventory and a post-run `docker volume ls`
  answer it.
- **No escape exploits.** Sandbox-integrity scenarios only plant and detect tripwire and inventory changes.

## 9. Not verified (Phase 1)

- That anything in `workbench` runs on Windows. It cannot: the digest crashes (2.2).
- The amd64 Hermes digest, and that the pinned v0.23.3 behaves the same on amd64.
- That Hermes passes the stop-rule checks **on Windows**. Only macOS evidence was read.
- uid 1000 write access to the NTFS bind mount; the form of `docker inspect` mount sources.
- The Python 3.14 behaviour of `st_ctime`, `st_ino`, and `st_nlink` on NTFS.
- Whether Docker Desktop's MCP Toolkit or gateway is enabled, and whether the Docker Desktop "expose daemon on
  tcp://localhost:2375" setting is on.
- Defender interference with tripwires and temp folders.
- That the shim and the preflight survive the Windows command line and console encoding.
- Ollama's bind address and its model configuration.
- Anything on macOS. I cannot run it from here.
- The setup prompt `01-setup-prompt.md`, which is not in the repo; `workbench doctor` has not been run.
- The earlier Hermes evaluation's numbers: I read its design plan and the Phase 3 and 4 summaries, not the raw records.

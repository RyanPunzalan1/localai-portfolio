# Changelog

All notable changes to this repository: the LocalAI chat app and the agent security workbench ship together under one
version (the `VERSION` file). Format after [Keep a Changelog](https://keepachangelog.com); versions are semantic, with
pre-releases as `-rcN`. Every release also says what changed in the **stored data** and what to do when **upgrading**.

How to check a release and update: see "Updating" in `README.md` and `design/versioned-data-and-releases.md`.

## [Unreleased] (since v0.7.0-rc1)

### Added
- **Pack contract:** `python -m packs_contract packs/<name>` runs ten checks per pack in a throwaway folder; 15 bad-pack
  fixtures prove each can fail; CI runs it. Every pack needs injection eval cases (`design/pack-contract.md`).
- **Versioned data:** the approvals inbox has a schema number and is upgraded automatically; a file the app can't use
  is set aside, never overwritten; `python -m data_schema check` reports versions. Activity log lines carry `"v"`.
- **Release tooling:** `VERSION`, this changelog, `scripts/release.py` (`hash`, `verify`, `tag`, `data-check`,
  `build-info`) and an "About" line in the app, so a checkout and a build can be compared with a signed tag.
- **Approval clarity:** a line in Chat saying how many changes are waiting, and on each card exactly what Approve will
  do (new file, the `_newN` name, append, mark done).
- **Workbench:** the model's digest in every record (`versions.model_digest`) and a local-only `run --model` option.
- **Windows:** the Docker tier tested live on one PC; CI on Ubuntu, macOS and Windows (all blocking); host backends
  (`workbench/hostos/`); the chat app runs on Windows only in its container.

### Changed
- **Containers:** the app and the dashboard have no network of their own; a small relay (`port_relay.py`) gives the app
  its two routes (browser, Ollama). The base image is pinned by digest and every Python package is installed by hash
  (`requirements.lock`). The Deploy button is hidden.
- **Approve** re-checks an item against the manifest of the pack it claims to come from, and refuses a forged one.
- **Every Ollama call** has a time limit (chat 5 minutes, status checks 5 seconds, embeddings 2 minutes).
- **Packs:** the gateway checks a permission pattern against a name both as typed and as the file guard reduces it;
  read-only tools can't stage a change; a pack's tool list must match its manifest; `model = false` is refused.

### Fixed
- A damaged or newer approvals file was silently emptied and then overwritten by the next change.
- "Mark done" could lose an edit made to `tasks.md` at the same time.
- The workbench's channel listener hung for over 30 seconds on a reverse DNS lookup on GitHub's macOS runner.
- `libzstd1` patched in the app image (a HIGH advisory with a fix).

### Security
- Container, dependency and approval hardening above; the Claude Code sandbox and a repo-limited GitHub token for
  development. Known gaps are listed in `design/threat-model.md` and `workbench/THREAT_MODEL.md`.

### Data changes
- **Approvals inbox** (`logs/pending_writes.json`): schema 1 (a bare list) becomes schema 2
  (`{"schema": 2, "items": [...]}`). The file is read in either format and is rewritten in the new one at the first change
  after the update; one backup of the old file is kept as `pending_writes.json.v1.bak` (owner-only).
- **Activity log** (`logs/activity.jsonl`): new lines carry `"v": 1`. Old lines are not changed.

### Upgrade notes
- Run `python -m data_schema check` before and after updating.
- **Going back to an older version:** older code can't read schema 2: it would start with an empty inbox and overwrite
  the file. Approve or reject what is waiting before you go back.
- Rebuild the containers (`docker compose up --build -d`); the image includes `VERSION` and, if you ran
  `python scripts/release.py build-info`, the build information the "About" line shows.

## [0.7.0-rc1] - 2026-11-25

A macOS release candidate of the workbench; not a production release and not independently audited. What was
implemented, tested and left open is in `workbench/RELEASE_NOTES.md` and `design/macos-rc-results.md`.
Data: the approvals inbox is schema 1 and the activity log has no version field.

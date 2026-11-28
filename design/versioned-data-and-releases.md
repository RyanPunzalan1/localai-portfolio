# Versioned data and releases (design for roadmap Phase 11)

Written for: the project owner, to approve before any code is written.
Status: **approved by the owner 2026-11-28 with all six recommended answers (D1 to D6), and built the same day.** Items
marked **[decide]** below were decided that way. What building found or changed is at the end.
Rules: `CLAUDE.md`. Roadmap items 11.1 (versioned data), 11.2 (changelog, versions, tags), 11.3 (manual update check).

## Goal

1. A change to the app's stored data never silently loses or overwrites what you have: an old file is upgraded, a file
   the code can't understand is kept aside and reported.
2. Every release has a version, a changelog, and a tag you can check, so "am I running what was released?" has an
   answer that doesn't depend on trusting a network.
3. Updating stays manual and local. The app never fetches or installs anything.

Done means: an old-format inbox file loads, is upgraded, and its pending items survive (a test shows it); a damaged or
newer file is never overwritten; and a dummy release in a temporary git repo is verified end to end by the release
script.

## What exists today (read from the code)

| Data | Format | Versioned? | Where |
|---|---|---|---|
| Approvals inbox | One JSON file holding a bare list of items (`name`, `content`, `mode`, `agent`, `provenance`, `warnings`; later fields are optional) | No | `logs/pending_writes.json`, `pending_store.py` |
| Activity log | JSON lines, each `time` plus the event's fields; rotated at 1 MB to one `.1` file (replaced each time) | No | `logs/activity.jsonl`, `brain.py` |
| Notes, tasks, lessons | Plain Markdown the user owns; `tasks.md` and `lesson-*.md` follow a layout by convention | No, and not meant to be | `docs/` |
| Evidence records | JSON lines, `schema` 1, checked by `record.validate` | **Yes** (the precedent to follow) | workbench |
| Chat history | Only the old scripts in `old/` use it; the app doesn't | n/a | |

Problems found:

| # | Problem |
|---|---|
| P1 | The inbox file has no version. Any change to its shape can't be told apart from a damaged file. |
| P2 | `PendingStore._read` returns an empty list for a damaged file, a non-list, or a format it doesn't know. The next `append` then **overwrites** that file. A newer or damaged inbox is lost without a word. |
| P3 | The activity log has no version either, so a field's meaning can't change safely. |
| P4 | The repo has no app version, no `CHANGELOG`, and one annotated tag (`v0.7.0-rc1`) that carries **no signature**. No signing key is configured (`gpg.format` and `user.signingkey` are unset). The workbench has its own `WORKBENCH_VERSION = "0.7.0-rc1"`. |
| P5 | Nothing checks that a checkout, or the image built from it, equals a release. |

## Design

### 1. Data versions (roadmap 11.1)

**The inbox.** Schema 1 is today's bare list, which is every existing file. Schema 2 is an envelope:

```json
{"schema": 2, "items": [ ... ]}
```

Items keep their shape. Fields are **added, never reinterpreted**: older items without `agent`, `provenance` or
`warnings` already work, and `PendingStore.update` already preserves fields it doesn't know.

**Migrations** are small pure functions, one per step (`1 -> 2`), chained, in a new `data_schema.py`, with the current
version per file kind in one table. They are tested against saved fixtures of each old format.

**Read rules** (one function, used by `PendingStore`):

| File says | What happens |
|---|---|
| The current schema | Used as it is |
| An older schema (or a bare list) | Upgraded in memory; written back in the new format at the next change, after one backup copy (**[decide]** D3) |
| A newer schema, damaged JSON, or an unexpected shape | **Never overwritten.** Moved aside to `pending_writes.json.unreadable-<UTC time>` (owner-only), the inbox starts empty, and the Approvals tab shows a warning with the file name (**[decide]** D2) |

**The activity log** is append-only history, so it is never rewritten. New lines get `"v": 1`. Readers already skip
damaged lines; they will also ignore unknown fields and treat a missing `v` as version 0. The rule for changing it:
add fields freely; to change a meaning, use a new event name.

**Not versioned on purpose:** `docs/` (your private files; nothing migrates them, readers stay tolerant), ChromaDB
(in memory, nothing stored), and workbench records (their own `schema` and `validate`).

### 2. Migration mechanics

- Migration happens on read and is written back on the next change, with the same atomic write (temporary file, then
  replace, owner-only) the store already uses. Two browser sessions migrating at once write the same result.
- `python -m data_schema check [logs folder]` reports each file's kind, version and any problem. It never prints item
  contents.
- Tests (all with dummy data): an old-format file with old-shape items loads, upgrades and survives approve and
  reject; a newer-schema file and a damaged file are moved aside, not overwritten, and the warning shows; the backup
  is owner-only; a second migration of an already-current file changes nothing.

### 3. Versions, changelog and tags (roadmap 11.2)

- **One version for the repo for now** (the app and the workbench ship together; the workbench's own split is
  decision D4 of the workbench design). Semantic versions as tags, `vMAJOR.MINOR.PATCH` with a pre-release suffix as
  today (`v0.7.0-rc1`). A `VERSION` file at the root is the single source; the app and `record.py` read it.
- **`CHANGELOG.md` at the root**, Keep-a-Changelog style: Added, Changed, Fixed, Security, plus a **Data changes**
  line stating each schema version and an **Upgrade notes** line. It starts at `v0.7.0-rc1` with an Unreleased
  section seeded from `workbench/RELEASE_NOTES.md` and the commits since; it doesn't try to rebuild earlier history.
  `workbench/RELEASE_NOTES.md` keeps the workbench status table.
- **Tags are annotated and signed**, and the tag message carries the release hash (next section). The first release
  under this process would be `v0.7.0-rc2`, after the PC reruns.

### 4. A manual update check (roadmap 11.3)

The app container has no network and no code that fetches anything, and that doesn't change. An update is something
you do, in this order:

```
git fetch --tags
python scripts/release.py verify v0.7.0-rc2     # checks, changes nothing
git checkout v0.7.0-rc2
python scripts/release.py data-check             # the schema versions your logs/ files have
python scripts/release.py build-info             # writes build_info.json
docker compose up --build -d
```

**The release hash** is a SHA-256 over sorted lines `mode path sha256(content)` of every tracked file. It is computed
two ways that must agree: from a tag's git objects, and from the files in a working tree. Untracked files (`docs/`,
`logs/`, `.venv`) are deliberately not part of it. `.gitattributes` already pins LF line endings, so it is the same on
every platform.

**`verify TAG`** runs `git verify-tag` against your allowed-signers file, then checks that the hash in the tag's
message equals the hash of the tag's tree, and prints PASS or FAIL. With `--worktree` it also compares the files on
disk, which catches a local edit or a partial pull.

**The app's "About" line** shows the version, commit and release hash from `build_info.json`, which is copied into the
image at build time. The app only displays it; it can't verify anything offline. The comparison is the script's job.

What this proves, and what it doesn't:

| Proves | Doesn't prove |
|---|---|
| The tag was made by the holder of the signing key | That the code is safe (that is review and the contract) |
| The files you have are exactly what was tagged | Anything if the signing key is stolen |
| A changed file or a swapped tag is detected | Anything about an **unsigned** tag, which says nothing about who made it; `v0.7.0-rc1` is such a tag |

The signing key is yours to create and keep, and it adds a step to each release. The command to make one, with
`ssh-keygen`, will be given in the build step; I can't create or handle your key.

## Build order

One step at a time, each with tests, and a full-suite run between steps:

| Step | Work | Done when |
|---|---|---|
| 11.1a | `data_schema.py`, the inbox envelope, migration 1 to 2, and fixtures | An old file upgrades and its items survive (a test shows it) |
| 11.1b | The unreadable-file policy, the warning in the Approvals tab, and `data_schema check` | A newer or damaged file is moved aside, never overwritten |
| 11.1c | `"v": 1` on new activity lines, and tolerant-reader tests | Old and new lines read together |
| 11.2a | `VERSION`, `CHANGELOG.md`, the app and `record.py` read the version | One source of truth; reference results unchanged |
| 11.2b | `scripts/release.py` (`hash`, `verify`, `data-check`, `build-info`) | A dummy release in a temporary git repo verifies; a changed file and a wrong hash both fail |
| 11.3 | The "About" line, an "Updating" section in the README, the threat model and roadmap | Docs match the code, with what isn't verified |

## Risks

- **Downgrades.** After migration the inbox is the envelope; older code would read a dict as "not a list", start empty
  and overwrite it. Mitigation: `data-check` warns, and the docs say to empty the inbox before going back a version.
  The inbox only holds proposals waiting for a click, so the loss is small. A two-release rollout (readers first,
  writers a release later) avoids it entirely, at the cost of a release cycle. **[decide]** D1 covers this.
- **A migration bug** could drop pending proposals. Mitigation: the backup, the fixtures, and the move-aside rule.
- **`VERSION` feeds `record.py`.** Records carry the workbench version, so the reference results and tests that
  mention `0.7.0-rc1` must stay unchanged until a release is cut. A test will check this.
- **Signing adds a step and a secret.** The hash alone detects corruption but not forgery; the signature is what makes
  a tag trustworthy.
- **Moved-aside and backup files hold your private text.** Same class as threat-model gap 3: owner-only, gitignored in
  `logs/`, limited to a few copies.

## Decisions for the owner

1. **[decide] D1.** The inbox becomes `{"schema": 2, "items": [...]}` with migrations, and the activity log gets `"v"`
   with an additive-only rule. Ship writers and readers together (recommended; accept the downgrade note), or
   readers first?
2. **[decide] D2.** A newer, damaged or unrecognised data file is moved aside (owner-only, at most 3 kept) with a
   warning, never overwritten. Alternatives: refuse to start, or keep today's silent reset. Recommended: move aside.
3. **[decide] D3.** One backup copy before a migration rewrites a file (`*.v1.bak`, owner-only; you delete it).
   Recommended yes.
4. **[decide] D4.** One version for the whole repo, a root `VERSION` file, and `v0.7.0-rc2` as the first release under
   this process.
5. **[decide] D5.** Tags are signed with an SSH key and carry the release hash; `scripts/release.py verify` checks
   both. This is the update channel, so it needs your yes. Alternative: unsigned tags plus the hash only, which
   detects corruption but not forgery. Recommended: signed.
6. **[decide] D6.** An "About" line in the app showing version, commit and hash from `build_info.json`.
   Recommended yes.

## Out of scope

Auto-update or any network call from the app, a release server, migrating files in `docs/`, signed container images,
and an SBOM. The last two are reasonable later additions.

## What was built, and what building changed (2026-11-28)

Everything in the design was built as approved: `data_schema.py` and the inbox envelope with migration 1 to 2 and one
backup; the set-aside policy and the Approvals warning; `python -m data_schema check`; `"v": 1` on new log lines;
`VERSION`, `CHANGELOG.md`; `scripts/release.py` with `hash`, `verify`, `tag`, `build-info` and `data-check`; and the
About line. Findings and differences:

- **A bug the tests found in my own set-aside code.** Copies were named with a timestamp to the second. Pruning freed an
  old name, a newer copy in the same second reused it, and pruning then deleted the *newest* copy. Names now use a
  fixed-width timestamp to the microsecond, so sorting by name is sorting by time.
- **A latent crash fixed.** The activity log reader skipped lines that weren't valid JSON but not lines that were valid
  JSON and not objects (`5`, `null`); one such line would have broken the Activity tab. Both are skipped now.
- **Two modules the image would have lacked.** The Dockerfile copies files by name, and `data_schema.py` and `about.py`
  are now imported by the app. A new test follows the imports from `app.py`, the dashboard, the relay and the packs and
  fails if any root module isn't copied; I checked it fails when `data_schema.py` is removed.
- **The build information is optional.** `COPY VERSION build_info.jso[n] ./` copies `build_info.json` only if it exists,
  so a fresh clone or CI still builds. Built both ways: with it the About line shows commit, hash and schema; without it
  the line says to run `build-info`. `build_info.json` is gitignored and has no timestamp, so the same checkout gives the
  same file.
- **Modes in the hash are the tracked ones.** `hash` uses git's index modes and the files' content from disk. A changed
  executable bit shows in `build-info`'s `clean` flag (and in `git status`), not in the hash.
- **`verify` has an exit code for "integrity only".** 0 is every check including the signature; 1 a failed check; 2 a
  setup error; 3 the signature was skipped with `--no-signature`, so the tag is not authenticated and never reads as a
  pass.
- **`VERSION` stays `0.7.0-rc1`** until a release is cut, so records and the reference results are unchanged. A test
  checks `VERSION`, the workbench's record version and the changelog agree.
- **Your real `logs/` inbox is still schema 1** (empty). It is upgraded, with a backup, the first time a proposal is
  added. `data-check` was run once against it and printed counts only.
- **The signing key is yours to create.** Nothing here creates, reads or stores one. `release.py tag` prints the
  one-time setup if signing isn't configured, and the existing `v0.7.0-rc1` stays unsigned.

## Not verified

- **Windows and Linux CI** for the new tests. The signing tests run only where `ssh-keygen` exists and are skipped on
  Windows; the hash, About and inbox tests run everywhere. The first push is the first real run on those systems.
- **Signing with your own key and a real remote.** The tests use throwaway keys in temporary repos. A `verify` against a
  tag fetched from GitHub, with your allowed-signers file, has not been run.
- **Downgrading.** The upgrade note says older code would start with an empty inbox and overwrite the file; that is read
  from the old code, not run against it.
- **The Approvals-tab warning and the About expander in a browser.** The text, the data and the container behaviour are
  tested; I haven't looked at the rendered page.

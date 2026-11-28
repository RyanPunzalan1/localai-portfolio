"""
data_schema.py - versions and migrations for the app's stored data (design/versioned-data-and-releases.md).

Standard library only. Two kinds of file are versioned:

  pending   logs/pending_writes.json, the approvals inbox.
            schema 1: a bare JSON list of items (every file written before 2026-11-28).
            schema 2: {"schema": 2, "items": [...]}.
  activity  logs/activity.jsonl, an append-only history. Never rewritten and never migrated. New lines carry "v": 1;
            a line without "v" is version 0. The rule for changing it: add fields freely; to change what a field
            means, use a new event name.

Not versioned on purpose: docs/ (the user's own files), ChromaDB (in memory) and the workbench's records (their own
schema and validate()).

    python -m data_schema check [logs folder]     reports versions and problems; changes nothing, prints no contents
"""

import json
import sys
from pathlib import Path

CURRENT = {"pending": 2}
LOG_VERSION = 1

PENDING_FILE = "pending_writes.json"
ACTIVITY_FILE = "activity.jsonl"
KEEP_SET_ASIDE = 3  # how many ".unreadable-*" copies of one file are kept


class Unreadable(Exception):
    """The file can't be used by this version of the app. `reason` is one of: damaged, shape, newer."""

    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


# ----------------------------------------------------------------------------------------------- migrations
def _pending_1_to_2(document):
    """Schema 1 was a bare list of items; schema 2 wraps it so the file can say which schema it is."""
    return {"schema": 2, "items": document}


MIGRATIONS = {("pending", 1): _pending_1_to_2}


def pending_version_of(document) -> int:
    """The schema a decoded inbox document claims. Raises Unreadable for anything that isn't one."""
    if isinstance(document, list):
        return 1
    if isinstance(document, dict) and "schema" in document:
        version = document["schema"]
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise Unreadable("shape", "the schema number is not a positive whole number")
        if version > CURRENT["pending"]:
            raise Unreadable("newer", f"written by a newer version of the app (schema {version})")
        return version
    raise Unreadable("shape", "not an approvals inbox file")


def migrate(kind: str, document, version: int):
    """Apply each step from `version` up to the current one. Pure: returns the new document."""
    while version < CURRENT[kind]:
        document = MIGRATIONS[(kind, version)](document)
        version += 1
    return document


def parse_pending(text: str):
    """(items, version found) for the text of an inbox file, upgraded to the current shape.
    Raises Unreadable if the text is damaged, newer than this code, or not an inbox."""
    try:
        document = json.loads(text)
    except ValueError:
        raise Unreadable("damaged", "not valid JSON") from None
    version = pending_version_of(document)
    current = migrate("pending", document, version)
    items = current.get("items") if isinstance(current, dict) else None
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise Unreadable("shape", "the items are not a list of objects")
    return items, version


def dump_pending(items: list) -> str:
    return json.dumps({"schema": CURRENT["pending"], "items": items}, ensure_ascii=False, indent=2)


# ----------------------------------------------------------------------------------------------- the check command
def inspect_pending(path) -> dict:
    """Read-only report on an inbox file: {'status', 'version', 'items', 'problem'}.
    status: missing, current, older (will be upgraded and backed up at the next change), or unusable."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"status": "missing", "version": 0, "items": 0, "problem": None}
    except (OSError, UnicodeDecodeError) as e:
        return {"status": "unusable", "version": None, "items": 0, "problem": f"cannot be read ({e.__class__.__name__})"}
    try:
        items, version = parse_pending(text)
    except Unreadable as e:
        return {"status": "unusable", "version": None, "items": 0, "problem": f"{e.reason}: {e}"}
    status = "current" if version == CURRENT["pending"] else "older"
    return {"status": status, "version": version, "items": len(items), "problem": None}


def inspect_activity(path) -> dict:
    """Counts only: lines by version, and lines that are damaged or not objects."""
    path = Path(path)
    out = {"exists": path.exists(), "lines": 0, "by_version": {}, "damaged": 0}
    if not out["exists"]:
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        out["lines"] += 1
        try:
            entry = json.loads(line)
        except ValueError:
            out["damaged"] += 1
            continue
        if not isinstance(entry, dict):
            out["damaged"] += 1
            continue
        version = entry.get("v", 0)
        key = version if isinstance(version, int) and not isinstance(version, bool) else "?"
        out["by_version"][key] = out["by_version"].get(key, 0) + 1
    return out


def check(logs_dir) -> tuple:
    """(exit code, report lines) for a logs folder. 0 = every file is usable, 1 = one can't be used by this version."""
    logs = Path(logs_dir)
    lines, code = [], 0
    pending = inspect_pending(logs / PENDING_FILE)
    name = f"{logs.name}/{PENDING_FILE}"
    if pending["status"] == "missing":
        lines.append(f"{name}: no file (an empty inbox)")
    elif pending["status"] == "unusable":
        lines.append(f"{name}: CANNOT BE USED by this version: {pending['problem']}")
        code = 1
    else:
        note = "current" if pending["status"] == "current" else (
            f"older; it is upgraded to schema {CURRENT['pending']} (with one backup) at the next change")
        lines.append(f"{name}: schema {pending['version']} ({note}), {pending['items']} item(s)")
    for extra in sorted(logs.glob(PENDING_FILE + ".*")) if logs.is_dir() else []:
        kind = "backup from a migration" if ".bak" in extra.name else "set aside because it could not be read"
        lines.append(f"{logs.name}/{extra.name}: {kind} (delete it when you no longer need it)")
    activity = inspect_activity(logs / ACTIVITY_FILE)
    if activity["exists"]:
        by = ", ".join(f"v{k}: {n}" for k, n in sorted(activity["by_version"].items(), key=lambda kv: str(kv[0])))
        lines.append(f"{logs.name}/{ACTIVITY_FILE}: {activity['lines']} line(s) ({by or 'none'}), "
                     f"{activity['damaged']} damaged (skipped when reading)")
    else:
        lines.append(f"{logs.name}/{ACTIVITY_FILE}: no file")
    return code, lines


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] != "check" or len(args) > 2:
        print("usage: python -m data_schema check [logs folder]   (default: logs)")
        return 2
    code, lines = check(args[1] if len(args) == 2 else "logs")
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    sys.exit(main())

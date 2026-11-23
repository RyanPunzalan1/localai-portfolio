#!/usr/bin/env python3
"""PreToolUse guard: block Edit/Write/NotebookEdit outside the workspace and log the attempt.

Fails closed: any unexpected input or error denies the write.
Port of guard-writes.ps1 for macOS and Linux.
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

MAX_LOG_BYTES = 1024 * 1024


def decide(decision, reason):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


def safe_text(value):
    # One line per log entry: replace control characters from model-supplied values.
    return "".join("?" if ord(c) < 32 or ord(c) == 127 else c for c in str(value))


def write_log(root, line):
    log_dir = root / ".claude" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "outside-workspace.log"
    if log_file.exists() and log_file.stat().st_size > MAX_LOG_BYTES:
        log_file.replace(log_file.with_name(log_file.name + ".1"))
    if not log_file.exists():
        log_file.write_text(f"# Blocked writes outside {root} (newest at bottom)\n", encoding="utf-8")
    with log_file.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def has_link_below_root(full, root):
    """True if any existing part of the path below the root is a symlink."""
    current = full
    while len(str(current)) > len(str(root)):
        if current.is_symlink():
            return True
        current = current.parent
    return False


def main():
    root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).resolve()

    raw = sys.stdin.read()
    if not raw.strip():
        decide("deny", "Blocked: write guard received no input.")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        decide("deny", "Blocked: write guard could not parse its input.")

    tool = str(data.get("tool_name", ""))
    tool_input = data.get("tool_input") or {}
    target = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not target:
        decide("deny", f"Blocked: {tool} call has no file path, so the write guard cannot verify it.")
    target = str(target)

    # Combine handles both relative and absolute targets; resolve() collapses any ../ segments.
    full = (root / target).resolve()

    reason = None
    try:
        rel = full.relative_to(root)
    except ValueError:
        rel = None

    if rel is None:
        reason = f"is outside the workspace {root}"
    elif ":" in str(rel):
        reason = "uses an alternate data stream (a colon in the name)"
    elif rel.parts and rel.parts[0] == ".claude":
        reason = "is inside .claude/ (hooks, settings and logs are protected)"
    elif has_link_below_root(full, root):
        reason = "passes through a symlink"

    if reason is None:
        sys.exit(0)  # allowed: no output means no decision from this hook

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{stamp} | BLOCKED | {safe_text(tool)} | {safe_text(full)} | session {safe_text(data.get('session_id', ''))}"
    write_log(root, line)
    decide("deny", f"Blocked: {full} {reason}. Attempt logged.")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:  # fail closed on anything unexpected
        decide("deny", f"Blocked: write guard could not verify the path ({e}).")

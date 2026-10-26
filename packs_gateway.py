"""
packs_gateway.py - the only way a pack touches files, the approvals inbox, or the activity log.

Design: design/packs.md, section 3 (roadmap 9.2). Nothing uses this module yet. Every method
checks the pack's manifest permissions first, then uses the same file guard the core uses
(agent._safe_path), so there is one file guard, not a copy.
"""

import fnmatch

import agent as agent_mod
from brain import log_text
from safety import wrap_untrusted

MAX_READ_CHARS = agent_mod.MAX_READ_CHARS


class PermissionDenied(Exception):
    """A pack asked for a file or a mode its manifest does not allow."""


def _allowed(patterns, name: str) -> bool:
    """True if the file name matches one of the manifest patterns (exact or a glob)."""
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in patterns)


class Gateway:
    def __init__(self, manifest, pending_writes, log=None, label=None):
        """
        manifest:       a packs_manifest.Manifest (its permissions are the only rules used here)
        pending_writes: the shared approvals inbox (the same list every agent uses)
        log:            optional ActivityLog; events carry lengths, never text
        label:          the agent name shown in Approvals (defaults to the pack name)
        """
        self.manifest = manifest
        self.pending = pending_writes
        self.log = log
        self.label = label or manifest.name

    # -------------------------------------------------------------- reading
    def read_raw(self, name: str) -> str:
        """Plain file text, size-capped, NOT wrapped. Only for code that ranks or parses the text
        (the pack then returns its own wrapped output). Same permission and file checks."""
        if not _allowed(self.manifest.read, name):
            raise PermissionDenied(f"'{name}' is not in this pack's read list.")
        path = agent_mod._safe_path(name)
        if not path.exists():
            raise FileNotFoundError(f"'{path.name}' does not exist.")
        return path.read_text(encoding="utf-8", errors="replace")[:MAX_READ_CHARS]

    def list_names(self) -> list:
        """Names of files in docs/ that the manifest allows the pack to read."""
        docs = agent_mod.DOCS
        if not docs.is_dir():
            return []
        return sorted(
            p.name for p in docs.iterdir()
            if p.is_file() and not p.is_symlink() and _allowed(self.manifest.read, p.name)
        )

    def read_text(self, name: str) -> str:
        """File text, size-capped and wrapped as untrusted data."""
        if not _allowed(self.manifest.read, name):
            raise PermissionDenied(f"'{name}' is not in this pack's read list.")
        path = agent_mod._safe_path(name)
        if not path.exists():
            raise FileNotFoundError(f"'{path.name}' does not exist.")
        text = path.read_text(encoding="utf-8", errors="replace")[:MAX_READ_CHARS]
        return wrap_untrusted(path.stem, text)  # the label the task tools have always used

    def has_line(self, name: str, line: str) -> bool:
        """True if the file has this exact line. Returns no file content, only the answer."""
        if not _allowed(self.manifest.read, name):
            raise PermissionDenied(f"'{name}' is not in this pack's read list.")
        path = agent_mod._safe_path(name)
        if not path.exists():
            return False
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        return any(item.rstrip("\r\n") == line for item in lines)

    # -------------------------------------------------------------- proposing
    def _propose(self, name: str, mode: str, content: str) -> str:
        if not _allowed(self.manifest.write, name):
            raise PermissionDenied(f"'{name}' is not in this pack's write list.")
        if mode not in self.manifest.write_modes:
            raise PermissionDenied(f"This pack may not use mode '{mode}'.")
        path = agent_mod._safe_path(name)
        item = {"name": path.name, "content": content, "agent": self.label}
        if mode != "create":
            item["mode"] = mode  # create is the default in approve_write, as today
        self.pending.append(item)
        return f"Proposed a change to {path.name}. It is NOT changed yet; waiting for the user to approve."

    def propose_create(self, name: str, text: str) -> str:
        return self._propose(name, "create", text)

    def propose_append(self, name: str, text: str) -> str:
        return self._propose(name, "append", text)

    def propose_mark_done(self, name: str, line: str) -> str:
        """Propose changing one exact open-task line to done (the same change complete_task makes)."""
        return self._propose(name, "mark_done", line + "\n")

    # -------------------------------------------------------------- logging
    def log_event(self, kind: str, **fields) -> None:
        """Record an event for this pack. Text values become their length, as in the core log."""
        if self.log is None:
            return
        safe = {k: log_text(v) if isinstance(v, str) else v for k, v in fields.items()}
        self.log.append({"event": kind, "pack": self.manifest.name, **safe})

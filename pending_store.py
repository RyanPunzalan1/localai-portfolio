"""
pending_store.py - approvals inbox that survives a page reload.

A list-like store backed by one JSON file. Every change is saved at once, and every
read goes to the file, so a new browser session sees the same proposals.
The file lives in logs/, which is gitignored.

The file has a schema version (data_schema.py, design/versioned-data-and-releases.md):
  - an older file (schema 1, a bare list) is read and upgraded; the first change after that writes the new format
    and keeps ONE backup of the old file next to it (pending_writes.json.v1.bak, owner-only);
  - a file this version can't use (damaged, written by a newer version, or not an inbox) is NEVER overwritten: it is
    moved aside to pending_writes.json.unreadable-<UTC time> (owner-only, the newest 3 kept) and the inbox starts
    empty. unreadable_files() lists those copies so the app can warn about them.
"""

import os
from datetime import datetime, timezone
from pathlib import Path

import data_schema as ds
from safety import require_posix_files


class PendingStore:
    def __init__(self, path):
        self.path = Path(path)

    # ------------------------------------------------------------------------------------------- reading
    def _load(self):
        """(items, version found on disk). Version 0 means there is no usable file."""
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return [], 0
        except UnicodeDecodeError:
            self._set_aside()
            return [], 0
        except OSError:
            return [], 0
        try:
            return ds.parse_pending(text)
        except ds.Unreadable:
            self._set_aside()
            return [], 0

    def _read(self) -> list:
        return self._load()[0]

    def unreadable_files(self) -> list:
        """Names of the copies set aside because they could not be read, oldest first."""
        folder = self.path.parent
        if not folder.is_dir():
            return []
        return sorted(p.name for p in folder.glob(f"{self.path.name}.unreadable-*"))

    # ------------------------------------------------------------------------------------------- protecting files
    def _set_aside(self) -> None:
        """Move a file this version can't use out of the way, so the next write can't overwrite it."""
        try:
            require_posix_files()
            # Fixed width, to the microsecond, so sorting the names sorts them by time, and a name freed by pruning is
            # never reused out of order.
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            target = self.path.with_name(f"{self.path.name}.unreadable-{stamp}")
            n = 0
            while target.exists():
                n += 1
                target = self.path.with_name(f"{self.path.name}.unreadable-{stamp}-{n}")
            self.path.replace(target)
            os.chmod(target, 0o600)
            for old in self.unreadable_files()[: -ds.KEEP_SET_ASIDE]:
                (self.path.parent / old).unlink(missing_ok=True)
        except OSError:
            # Nothing more can be done here (a read-only folder, another session got there first, or native
            # Windows). The caller still gets an empty inbox.
            pass

    def _backup(self, version: int) -> None:
        """Keep one copy of the old-format file before the first write replaces it. An existing backup is kept."""
        backup = self.path.with_name(f"{self.path.name}.v{version}.bak")
        if backup.exists():
            return
        data = self.path.read_bytes()
        fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)  # owner-only: it holds proposed text
        with os.fdopen(fd, "wb") as f:
            f.write(data)

    # ------------------------------------------------------------------------------------------- writing
    def _write(self, items: list, previous_version: int = 0) -> None:
        require_posix_files()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if 0 < previous_version < ds.CURRENT["pending"]:
            self._backup(previous_version)
        tmp = self.path.with_suffix(".tmp")
        # Owner-only: the file holds proposed note text until the user approves or rejects it.
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(ds.dump_pending(items))
        os.chmod(tmp, 0o600)
        tmp.replace(self.path)

    def append(self, item: dict) -> None:
        items, version = self._load()
        items.append(item)
        self._write(items, version)

    def update(self, index: int, fields: dict) -> None:
        """Add or replace extra fields on one proposal (for example provenance and reviewer warnings).
        The fields that decide what gets written (name, content, mode) cannot be changed this way."""
        protected = {"name", "content", "mode"} & set(fields)
        if protected:
            raise ValueError(f"update() may not change {sorted(protected)}")
        items, version = self._load()
        items[index].update(fields)  # IndexError if out of range, same as a list
        self._write(items, version)

    def pop(self, index: int = -1) -> dict:
        items, version = self._load()
        item = items.pop(index)  # IndexError if out of range, same as a list
        self._write(items, version)
        return item

    def __len__(self) -> int:
        return len(self._read())

    def __iter__(self):
        return iter(self._read())

    def __getitem__(self, index):
        return self._read()[index]

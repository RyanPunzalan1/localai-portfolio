"""
pending_store.py - approvals inbox that survives a page reload.

A list-like store backed by one JSON file. Every change is saved at once, and every
read goes to the file, so a new browser session sees the same proposals.
The file lives in logs/, which is gitignored.
"""

import json
import os
from pathlib import Path


class PendingStore:
    def __init__(self, path):
        self.path = Path(path)

    def _read(self) -> list:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # A damaged file should not crash the app. Start with an empty inbox.
            return []
        return data if isinstance(data, list) else []

    def _write(self, items: list) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        # Owner-only: the file holds proposed note text until the user approves or rejects it.
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(items, ensure_ascii=False, indent=2))
        os.chmod(tmp, 0o600)
        tmp.replace(self.path)

    def append(self, item: dict) -> None:
        items = self._read()
        items.append(item)
        self._write(items)

    def update(self, index: int, fields: dict) -> None:
        """Add or replace extra fields on one proposal (for example provenance and reviewer warnings).
        The fields that decide what gets written (name, content, mode) cannot be changed this way."""
        protected = {"name", "content", "mode"} & set(fields)
        if protected:
            raise ValueError(f"update() may not change {sorted(protected)}")
        items = self._read()
        items[index].update(fields)  # IndexError if out of range, same as a list
        self._write(items)

    def pop(self, index: int = -1) -> dict:
        items = self._read()
        item = items.pop(index)  # IndexError if out of range, same as a list
        self._write(items)
        return item

    def __len__(self) -> int:
        return len(self._read())

    def __iter__(self):
        return iter(self._read())

    def __getitem__(self, index):
        return self._read()[index]

"""Link-safe workspace digest (workbench Phase 1; promoted from experiments/workbench_poc/safe_digest.py, unchanged in behaviour).

The current harness's digest_tree follows symbolic links: rglob, is_file() and read_bytes() all resolve them, so a
link planted in the workspace makes the host read a file outside it (verified 2026-11-22). This walker never follows
a link and never opens anything that is not a regular file:

  regular file      -> "file:<sha256>"   (opened with O_NOFOLLOW; size capped)
  symbolic link     -> "link:<target>"   (os.readlink only; the target is never opened or stat'ed)
  directory         -> walked, unless it is a link (then recorded as a link)
  FIFO, socket, device, other -> "special:<kind>" (never opened, so a FIFO cannot hang the walker)

Hard links to files outside the workspace are recorded with their hash, but flagged ("nlink>1"), because their
content is shared with a file elsewhere. Limits stop a hostile workspace from exhausting the host.
"""

import hashlib
import os
import stat

from workbench import hostos

MAX_ENTRIES = 5000
MAX_FILE_BYTES = 8 * 1024 * 1024   # bytes hashed per file; longer files are marked "truncated"
CHUNK = 64 * 1024


class DigestLimit(Exception):
    """The workspace has more entries than the limit; the caller should mark the trial inconclusive."""


def _kind(mode):
    if stat.S_ISFIFO(mode):
        return "fifo"
    if stat.S_ISSOCK(mode):
        return "socket"
    if stat.S_ISCHR(mode):
        return "char-device"
    if stat.S_ISBLK(mode):
        return "block-device"
    return "other"


def _hash_file(path, size):
    fd = hostos.current().open_regular_nofollow(path)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):  # swapped for something else between lstat and open
            return f"special:{_kind(st.st_mode)}"
        h, left = hashlib.sha256(), MAX_FILE_BYTES
        while left > 0:
            block = os.read(fd, min(CHUNK, left))
            if not block:
                break
            h.update(block)
            left -= len(block)
        out = f"file:{h.hexdigest()}"
        if size > MAX_FILE_BYTES:
            out += f":truncated:{size}"
        if st.st_nlink > 1:
            out += ":nlink>1"
        return out
    finally:
        os.close(fd)


def digest(root) -> dict:
    """{relative path: entry} for everything under root, without following links. root itself must be a directory."""
    root = os.fspath(root)
    if os.name == "nt":  # no O_NOFOLLOW on Windows: its own backend, same output format
        from workbench import digest_windows
        return digest_windows.digest(root, MAX_ENTRIES, (MAX_FILE_BYTES, CHUNK), DigestLimit)
    st = os.lstat(root)
    if not stat.S_ISDIR(st.st_mode):
        raise ValueError("digest root must be a real directory, not a link or file")
    out, stack = {}, [""]
    while stack:
        rel_dir = stack.pop()
        with os.scandir(os.path.join(root, rel_dir) if rel_dir else root) as it:
            for entry in it:
                rel = os.path.join(rel_dir, entry.name) if rel_dir else entry.name
                if len(out) >= MAX_ENTRIES:
                    raise DigestLimit(f"more than {MAX_ENTRIES} entries")
                est = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(est.st_mode):
                    out[rel] = f"link:{os.readlink(entry.path)}"
                elif stat.S_ISDIR(est.st_mode):
                    out[rel] = "dir"
                    stack.append(rel)
                elif stat.S_ISREG(est.st_mode):
                    out[rel] = _hash_file(entry.path, est.st_size)
                else:
                    out[rel] = f"special:{_kind(est.st_mode)}"
    return dict(sorted(out.items()))


def changes(before: dict, after: dict) -> dict:
    """Paths created, removed and modified between two digests."""
    return {"created": sorted(set(after) - set(before)),
            "removed": sorted(set(before) - set(after)),
            "modified": sorted(p for p in set(before) & set(after) if before[p] != after[p])}

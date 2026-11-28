"""Owner-only access for kept evidence on Windows (D7). NTFS has no Unix mode bits, so `mkdir(mode=0o700)` does nothing there.
The folder gets an explicit ACL: inheritance removed, full control for the current user only. Windows only; trusted host code."""

import csv
import io
import os
import subprocess
from pathlib import Path


class AclError(OSError):
    """The evidence ACL could not be set."""


def current_sid() -> str:
    r = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"], capture_output=True, text=True, timeout=30)
    rows = list(csv.reader(io.StringIO(r.stdout.strip())))
    if r.returncode != 0 or not rows or len(rows[0]) < 2 or not rows[0][1].startswith("S-1-"):
        raise AclError("could not read the current user's SID")
    return rows[0][1]


def _icacls(args):
    r = subprocess.run(["icacls", *args], capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise AclError(f"icacls failed: {(r.stdout + r.stderr).strip()[-200:]}")


def restrict(path, recursive=True) -> None:
    """Make `path` owner-only: inheritance removed, full control for the current user. With `recursive`, everything below
    it is reset to inherit that (the grant's folder flags do not apply to files, so setting it with /T would leave a file
    with an empty ACL)."""
    p = Path(path)
    if not p.exists():
        raise AclError(f"cannot restrict a missing path: {p.name}")
    # /reset first: Python 3.13+ turns mkdir(mode=0o700) into an explicit ACL (user, SYSTEM, Administrators), and
    # /inheritance:r alone would leave those entries in place.
    _icacls([str(p), "/reset"])
    _icacls([str(p), "/inheritance:r", "/grant:r", f"*{current_sid()}:(OI)(CI)F"])
    if recursive and p.is_dir() and any(p.iterdir()):
        _icacls([str(p) + os.sep + "*", "/reset", "/T", "/C", "/Q"])

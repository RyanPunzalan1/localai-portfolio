"""Platform skips shared by the tests. A skip here means "this machine cannot run the check", never "the check passed".

Each skip names the stage of the Windows work (design/hermes-adapter-windows-assessment.md) that replaces it with a
Windows equivalent, so nothing is silently dropped.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

WINDOWS = sys.platform == "win32"


def _can_symlink() -> bool:
    with tempfile.TemporaryDirectory() as d:
        try:
            os.symlink(Path(d) / "target", Path(d) / "link")
            return True
        except (OSError, NotImplementedError):
            return False


CAN_SYMLINK = _can_symlink()

# Creating a symbolic link on Windows needs Developer Mode or an elevated account. Where it is missing the test cannot
# build its fixture. Windows junction, hard-link and alternate-data-stream versions are added in stage S1.
needs_symlink = unittest.skipUnless(CAN_SYMLINK, "this account cannot create symbolic links (Windows: Developer Mode); "
                                                 "Windows link cases are added in stage S1")
# NTFS has no Unix permission bits. Owner-only files on Windows are an ACL question (decision D7, stages S3 and S7).
needs_unix_modes = unittest.skipIf(WINDOWS, "NTFS has no Unix mode bits; the Windows check is an ACL test (D7)")
# On Windows the chat app is supported only in its Linux container (decision 2026-11-28): its activity log and pending-write
# inbox need Unix owner-only modes, so native Windows refuses to write them (safety.require_posix_files). Tests that write
# them run on macOS and Linux, and in the container. Not a stage to be replaced: this is the decision itself.
app_container_only = unittest.skipIf(WINDOWS, "on Windows the app runs only in its Linux container (decision 2026-11-28)")

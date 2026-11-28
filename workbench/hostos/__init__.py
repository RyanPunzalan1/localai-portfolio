"""Host operating-system backends (design/windows-compatibility.md, step W1).

The workbench's host-side code (link-safe digest, tripwire fingerprints, host inventory, memory sampling, the VM-tier
rule) asks `current()` for a backend instead of calling POSIX functions directly. Today there is one working backend,
`PosixHost` (macOS; Linux is untested), whose code is the code that used to sit in those modules, moved and not
changed. `WindowsHost` is a stub that refuses every call, so a Windows run fails with a clear message instead of an
AttributeError. Named `hostos`, not `platform`, so it can never shadow the standard library's `platform` module.
"""

import functools
import sys

from .base import Host, HostNotSupported
from .posix import PosixHost
from .windows import WindowsHost

__all__ = ["Host", "HostNotSupported", "PosixHost", "WindowsHost", "current", "for_platform"]


def for_platform(platform: str) -> Host:
    """The backend for a sys.platform value. Anything that is not Windows gets the POSIX backend."""
    return WindowsHost() if platform.startswith("win") else PosixHost(platform)


@functools.lru_cache(maxsize=1)
def current() -> Host:
    return for_platform(sys.platform)

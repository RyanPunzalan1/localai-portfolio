"""Windows backend: a stub. Windows is planned, not implemented (design/windows-compatibility.md, steps W2 to W4).

Every call refuses with a clear message. Nothing here pretends to work: a half-working file-safety or fingerprint
backend would be worse than none, because the security checks depend on it.
"""

from .base import Host, HostNotSupported

_MSG = "Windows is not supported yet ({what}); see design/windows-compatibility.md"


def _no(what):
    raise HostNotSupported(_MSG.format(what=what))


class WindowsHost(Host):
    name = "windows"

    def open_regular_nofollow(self, path) -> int:
        _no("link-safe file open")

    def open_read_nofollow(self, path) -> int:
        _no("link-safe file open")

    def create_private_file(self, path, mode: int = 0o600) -> int:
        _no("owner-only file creation")

    def file_meta(self, st) -> str:
        _no("tripwire fingerprints")

    def inventory_commands(self) -> dict:
        _no("host inventory")

    def process_table(self) -> list:
        _no("process table")

    def vm_tier(self) -> tuple:
        return False, "the VM tier is not available on Windows yet (design/windows-compatibility.md, W4)"

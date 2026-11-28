"""The interface every host backend implements. Methods are the OS-specific operations the workbench needs."""


class HostNotSupported(RuntimeError):
    """This host operating system has no backend for the operation yet (see design/windows-compatibility.md)."""


class Host:
    name = "base"

    def open_regular_nofollow(self, path) -> int:
        """File descriptor for reading `path` that never follows a final link and never blocks on a FIFO (digest)."""
        raise NotImplementedError

    def open_read_nofollow(self, path) -> int:
        """File descriptor for reading `path`, refusing a final link where the OS can (tripwire fingerprint)."""
        raise NotImplementedError

    def create_private_file(self, path, mode: int = 0o600) -> int:
        """Create `path` exclusively, never through a link, owner-only where the OS has modes. Returns a descriptor."""
        raise NotImplementedError

    def file_meta(self, st) -> str:
        """The metadata part of a tripwire fingerprint, from an os.stat_result. Any change must change this string."""
        raise NotImplementedError

    def inventory_commands(self) -> dict:
        """{name: argument list} for the host inventory taken before and after each trial."""
        raise NotImplementedError

    def process_table(self) -> list:
        """[(pid, rss_kib, command)] for every process on the host (VM-tier memory sampling)."""
        raise NotImplementedError

    def vm_tier(self) -> tuple:
        """(supported, reason). The VM tier is refused wherever it has not been tested."""
        raise NotImplementedError

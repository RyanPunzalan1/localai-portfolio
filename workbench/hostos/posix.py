"""POSIX backend: the code that used to sit in digest.py, tripwire.py and memory.py, moved here unchanged."""

import os
import stat
import subprocess

from .base import Host


class PosixHost(Host):
    def __init__(self, platform="darwin"):
        self.platform = platform
        self.name = "macos" if platform == "darwin" else "posix"

    def open_regular_nofollow(self, path) -> int:
        return os.open(path, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0))

    def open_read_nofollow(self, path) -> int:
        return os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))

    def create_private_file(self, path, mode: int = 0o600) -> int:
        return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), mode)

    def file_meta(self, st) -> str:
        return (f"{stat.S_IMODE(st.st_mode):o}:{st.st_uid}:{st.st_size}:{st.st_nlink}:{st.st_ino}:{st.st_mtime_ns}"
                f":{st.st_ctime_ns}")

    def inventory_commands(self) -> dict:
        return {
            "containers": ["docker", "ps", "-a", "--no-trunc", "--format", "{{.ID}} {{.Names}}"],
            "volumes": ["docker", "volume", "ls", "-q"],
            "networks": ["docker", "network", "ls", "--no-trunc", "--format", "{{.ID}} {{.Name}}"],
            "sandboxes": ["sbx", "ls", "-q"],
        }

    def process_table(self) -> list:
        r = subprocess.run(["ps", "-axo", "pid=,rss=,comm="], capture_output=True, text=True, timeout=30)
        rows = []
        for line in r.stdout.splitlines():
            parts = line.split(None, 2)
            if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
                rows.append((int(parts[0]), int(parts[1]), parts[2]))
        return rows

    def vm_tier(self) -> tuple:
        if self.platform == "darwin":
            return True, ""
        return False, "the VM tier is only tested on macOS; Linux is untested and refused (design D6)"

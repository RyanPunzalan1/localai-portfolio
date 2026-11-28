"""Host-side memory sampling for one sandbox during a trial (Phase 4 gate: "memory use is measured").

VM tier (sbx): each sandbox runs as one `docker-docklet` process on the host (measured 2026-11-24, sbx v0.54.0). The
sampler finds the docklet processes that appeared after a baseline taken just before `sbx create` and sums their
resident size (RSS). RSS is what macOS reports for the process; guest pages the hypervisor has not touched are not in
it, so this is memory in use, not the 2 GiB limit.
Docker tier: `docker stats` for the container (memory charged to its cgroup inside Docker Desktop's VM).

Readings are measurements, never evidence for an outcome. A failed sample is recorded as missing, never guessed.
"""

import re
import subprocess
import threading

from workbench import hostos

DOCKLET = "docker-docklet"
_UNITS = {"B": 1 / 2**20, "KiB": 1 / 1024, "KB": 1 / 1024, "MiB": 1, "MB": 1, "GiB": 1024, "GB": 1024}


def _ps():
    return hostos.current().process_table()


def docklet_pids(ps=_ps) -> set:
    return {pid for pid, _, comm in ps() if comm.endswith(DOCKLET)}


def sbx_rss_mib(baseline_pids: set, ps=_ps):
    """Summed RSS (MiB) of docklet processes that are not in the baseline, or None if there are none."""
    rows = [rss for pid, rss, comm in ps() if comm.endswith(DOCKLET) and pid not in baseline_pids]
    return round(sum(rows) / 1024, 1) if rows else None


def parse_docker_mem(text: str):
    """'12.5MiB / 2GiB' -> 12.5 (MiB used), or None."""
    m = re.match(r"\s*([\d.]+)\s*([KMG]i?B|B)\b", text or "")
    return round(float(m.group(1)) * _UNITS[m.group(2)], 1) if m else None


def docker_mem_mib(name):
    r = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", name],
                       capture_output=True, text=True, timeout=30)
    return parse_docker_mem(r.stdout) if r.returncode == 0 else None


class Sampler:
    """Samples one sandbox's memory every `interval` seconds on a background thread until stop()."""

    def __init__(self, read, interval=2.0):
        self.read, self.interval = read, interval
        self.samples, self.missed = [], 0
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._loop, daemon=True)

    def start(self):
        self._t.start()
        return self

    def _loop(self):
        while not self._stop.is_set():
            try:
                v = self.read()
            except Exception:  # a failed reading is missing data, never a guess
                v = None
            if v is None:
                self.missed += 1
            else:
                self.samples.append(v)
            self._stop.wait(self.interval)

    def stop(self) -> dict:
        self._stop.set()
        self._t.join(timeout=self.interval + 35)
        s = self.samples
        return {"unit": "MiB", "samples": len(s), "missed": self.missed,
                "peak": max(s) if s else None, "mean": round(sum(s) / len(s), 1) if s else None}

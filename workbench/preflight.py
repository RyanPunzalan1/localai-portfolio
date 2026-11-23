"""Reachability preflight. Runs INSIDE a sandbox before any agent code (design 5.2.4, check 2). Standard library only.

Prints one JSON object: {check name: {"reached": bool, "detail": str, ...}}. The evaluator on the host decides what
the result means (workbench.isolation.evaluate_preflight); this script only reports.

Arguments:
  --expect HOST:PORT     a target that MUST be reachable (Tier 0: the sink). Repeatable.
  --probe HOST:PORT      an extra target to probe and report (used by the negative control). Repeatable.

A TCP target counts as reached only when a request gets bytes back: sbx's transparent proxy accepts every connection
and drops refused ones without a reply, so "connected" alone is not proof (found in the PoC, 2026-11-22).
"""

import json
import os
import socket
import sys

TIMEOUT = 3
TARGETS = {
    "dns_example_com": ("dns", "example.com", None),
    "tcp_example_com_80": ("tcp", "example.com", 80),
    "tcp_raw_ip_1_1_1_1_443": ("tcp", "1.1.1.1", 443),
    "tcp_raw_ip_93_184_215_14_80": ("tcp", "93.184.215.14", 80),
    "tcp_host_ollama_11434": ("tcp", "host.docker.internal", 11434),
    "tcp_host_dashboard_8502": ("tcp", "host.docker.internal", 8502),
    "tcp_host_app_8501": ("tcp", "host.docker.internal", 8501),
    "tcp_docker_gateway_80": ("tcp", "gateway.docker.internal", 80),
    "tcp_docker_api_2375": ("tcp", "host.docker.internal", 2375),
    "udp_dns_8_8_8_8": ("udp", "8.8.8.8", 53),
    "docker_socket_present": ("file", "/var/run/docker.sock", None),
}


def probe(kind, host, port):
    try:
        if kind == "dns":
            return True, ",".join(sorted({a[4][0] for a in socket.getaddrinfo(host, 80)}))[:80]
        if kind == "file":
            return os.path.exists(host), "exists" if os.path.exists(host) else "absent"
        if kind == "tcp":
            with socket.create_connection((host, port), timeout=TIMEOUT) as s:
                s.settimeout(TIMEOUT)
                s.sendall(b"GET / HTTP/1.1\r\nHost: " + host.encode() + b"\r\nConnection: close\r\n\r\n")
                data = s.recv(200)
                if data:
                    return True, "response: " + data.split(b"\r\n", 1)[0][:60].decode("latin-1")
                return False, "connected, but closed with no response (proxy refusal)"
        if kind == "udp":  # a DNS query for example.com; reached only if an answer comes back
            q = b"\x12\x34\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00\x07example\x03com\x00\x00\x01\x00\x01"
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.settimeout(TIMEOUT)
                s.sendto(q, (host, port))
                s.recvfrom(512)
                return True, "answer received"
    except OSError as e:
        return False, f"{type(e).__name__}: {e}"[:120]
    return False, "unknown kind"


def _pairs(flag):
    out, args = [], sys.argv[1:]
    for i, a in enumerate(args):
        if a == flag and i + 1 < len(args):
            host, port = args[i + 1].rsplit(":", 1)
            out.append((host, int(port)))
    return out


def main():
    out = {}
    for name, (kind, host, port) in TARGETS.items():
        reached, detail = probe(kind, host, port)
        out[name] = {"reached": reached, "detail": detail}
    for host, port in _pairs("--expect"):
        reached, detail = probe("tcp", host, port)
        out[f"expected_{host}_{port}"] = {"reached": reached, "detail": detail, "expected": True}
    for host, port in _pairs("--probe"):
        reached, detail = probe("tcp", host, port)
        out[f"probe_{host}_{port}"] = {"reached": reached, "detail": detail}
    print(json.dumps(out))


if __name__ == "__main__":
    main()

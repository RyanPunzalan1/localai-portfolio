"""Reachability preflight, run INSIDE a sandbox before any trial (design section 4.3). Standard library only.

Prints one JSON object: {check name: {"reached": bool, "detail": str}}. The runner compares it with what the
profile allows and stops the batch on any unexpected success (fail closed). Expected-reachable targets are passed
as argv: host:port pairs that must be reachable (for example the sink). Everything in TARGETS must NOT be.
"""

import json
import socket
import sys

TIMEOUT = 3
TARGETS = {
    "dns_example_com": ("dns", "example.com"),
    "tcp_example_com_80": ("tcp", "example.com", 80),
    "tcp_raw_ip_1_1_1_1_443": ("tcp", "1.1.1.1", 443),
    "tcp_raw_ip_93_184_215_14_80": ("tcp", "93.184.215.14", 80),
    "tcp_host_ollama_11434": ("tcp", "host.docker.internal", 11434),
    "tcp_host_gateway_dashboard_8502": ("tcp", "host.docker.internal", 8502),
    "udp_dns_8_8_8_8": ("udp", "8.8.8.8", 53),
}


def probe(kind, host, port=None):
    try:
        if kind == "dns":
            return True, ",".join(sorted({a[4][0] for a in socket.getaddrinfo(host, 80)}))[:80]
        if kind == "tcp":
            # A connect alone is not proof: sbx's transparent proxy accepts every TCP connection and decides only
            # when data arrives (found 2026-11-22). Reached = a request got any bytes back.
            with socket.create_connection((host, port), timeout=TIMEOUT) as s:
                s.settimeout(TIMEOUT)
                s.sendall(b"GET / HTTP/1.1\r\nHost: " + host.encode() + b"\r\nConnection: close\r\n\r\n")
                data = s.recv(200)
                if data:
                    return True, "response: " + data.split(b"\r\n", 1)[0][:60].decode("latin-1")
                return False, "connected, but closed with no response (proxy refusal)"
        if kind == "udp":  # a DNS query for example.com; reached only if an answer comes back
            q = b"\x12\x34\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00\x07example\x03com\x00\x00\x01\x00\x01"
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(TIMEOUT)
            s.sendto(q, (host, port))
            s.recvfrom(512)
            return True, "answer received"
    except OSError as e:
        return False, f"{type(e).__name__}: {e}"[:120]
    return False, "unknown kind"


def main():
    out = {name: dict(zip(("reached", "detail"), probe(*spec))) for name, spec in TARGETS.items()}
    for pair in sys.argv[1:]:
        host, port = pair.rsplit(":", 1)
        reached, detail = probe("tcp", host, int(port))
        out[f"expected_{host}_{port}"] = {"reached": reached, "detail": detail, "expected": True}
    print(json.dumps(out))


if __name__ == "__main__":
    main()

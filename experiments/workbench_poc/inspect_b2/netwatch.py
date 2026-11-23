"""Audit hook: log every socket connect/DNS lookup and subprocess start; block connections that leave this machine."""
import json, os, sys, ipaddress
LOG = os.environ.get("NETWATCH_LOG", "netwatch.jsonl")
def _local(host):
    if host in ("localhost", None) or (isinstance(host, str) and host.endswith(".sock")):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False
def hook(event, args):
    if event not in ("socket.connect", "socket.getaddrinfo", "subprocess.Popen", "urllib.Request"):
        return
    if event == "socket.connect":
        addr = args[1]
        host = addr[0] if isinstance(addr, tuple) else str(addr)
        rec = {"event": event, "host": host, "port": addr[1] if isinstance(addr, tuple) else None}
    elif event == "socket.getaddrinfo":
        host = args[0]; rec = {"event": event, "host": str(host), "port": args[1]}
    elif event == "subprocess.Popen":
        rec = {"event": event, "exe": str(args[0]), "argv": [str(a) for a in (args[1] or [])][:6]}; host = None
    else:
        host = None; rec = {"event": event, "url": str(args[0])[:120]}
    with open(LOG, "a") as f:
        f.write(json.dumps(rec) + "\n")
    if event in ("socket.connect", "socket.getaddrinfo") and not _local(host if isinstance(host, str) else None):
        raise PermissionError(f"netwatch blocked {event} to {host}")
sys.addaudithook(hook)

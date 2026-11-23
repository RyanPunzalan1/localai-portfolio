"""Network sink for Tier 0 scripted operations only (design 5.2.1). Runs in its own container on the trial's internal network.

Accepts any HTTP request on port 8080 and appends one JSON line per request to /log/sink.jsonl:
method, path, byte count, and which synthetic canaries (names from the CANARIES env var, NAME=VALUE pairs
separated by commas) appear in the body. The body itself is never stored. Standard library only.
"""

import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOG = "/log/sink.jsonl"
MAX_BODY = 1024 * 1024
CANARIES = dict(p.split("=", 1) for p in os.environ.get("CANARIES", "").split(",") if "=" in p)


class Handler(BaseHTTPRequestHandler):
    def _record(self):
        n = min(int(self.headers.get("Content-Length", 0) or 0), MAX_BODY)
        body = self.rfile.read(n) if n else b""
        hits = sorted(name for name, value in CANARIES.items() if value.encode() in body)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"time": time.time(), "method": self.command, "path": self.path[:200],
                                "bytes": len(body), "canaries": hits}) + "\n")
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_GET = do_POST = do_PUT = _record

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    open(LOG, "a").close()
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()

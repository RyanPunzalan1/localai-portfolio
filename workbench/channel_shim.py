"""In-sandbox end of the model and approval channel (design 5.2.2a). Runs INSIDE the sandbox; it is not trusted.

Listens on 127.0.0.1 only. Each HTTP request becomes one JSON line on stdout; replies arrive as JSON lines on stdin and
are streamed back to the HTTP client. It enforces nothing: every decision is made on the host, which treats this
process and everything it sends as hostile. Standard library only; started by the host as `python3 -c <source>`.
"""

import base64
import itertools
import json
import queue
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MAX_BODY = 1024 * 1024
_out_lock = threading.Lock()
_waiting = {}
_ids = itertools.count(1)


def _send(obj):
    line = json.dumps(obj, separators=(",", ":")) + "\n"
    with _out_lock:
        sys.stdout.write(line)
        sys.stdout.flush()


def _reader():
    for line in sys.stdin:
        try:
            msg = json.loads(line)
            q = _waiting.get(msg.get("id"))
        except (ValueError, AttributeError):
            continue
        if q is not None:
            q.put(msg)
    for q in list(_waiting.values()):  # host went away
        q.put({"type": "end", "error": "channel closed"})


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _relay(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        if n > MAX_BODY:
            self.send_error(413)
            return
        body = self.rfile.read(n) if n else b""
        rid = next(_ids)
        q = _waiting[rid] = queue.Queue()
        _send({"id": rid, "type": "request", "method": self.command, "path": self.path[:512],
               "body": base64.b64encode(body).decode()})
        try:
            start = q.get(timeout=600)
            if start.get("type") != "start":
                self.send_error(502)
                return
            self.send_response(int(start.get("status", 502)))
            self.send_header("Content-Type", str(start.get("content_type", "application/json"))[:100])
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            while True:
                msg = q.get(timeout=600)
                if msg.get("type") != "chunk":
                    break
                data = base64.b64decode(msg.get("data", ""))
                self.wfile.write(b"%x\r\n%s\r\n" % (len(data), data))
                self.wfile.flush()
            self.wfile.write(b"0\r\n\r\n")
        except queue.Empty:
            self.send_error(504)
        finally:
            _waiting.pop(rid, None)

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = _relay

    def log_message(self, *a):
        pass


def main():
    port = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 13131
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    srv.daemon_threads = True
    threading.Thread(target=_reader, daemon=True).start()
    _send({"id": 0, "type": "ready", "port": srv.server_address[1]})
    srv.serve_forever()


if __name__ == "__main__":
    main()

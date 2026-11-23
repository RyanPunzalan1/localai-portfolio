"""Filtering model proxy for the workbench PoC, Track A4 (design/security-workbench-design.md T4 and 5.2).

The agent's only route to the model. It never reaches Ollama directly, because Ollama has no authentication and its
API can pull (an outbound request from the host to a name the caller chooses), create, copy, push and delete models.

Allowed:  POST /v1/chat/completions and POST /api/chat, for the allowlisted model only, forwarded upstream.
          GET /v1/models and /api/tags, answered here with the one allowed model (no upstream call).
Refused:  everything else (403), never forwarded. Bodies over the size cap (413). Calls over the per-run cap (429).
Caps:     reply tokens (max_tokens / options.num_predict lowered to the cap; never raised).
Log:      one JSON line per request with metadata only: path, decision, model, message count, prompt characters,
          which synthetic canaries appear in the prompt (proof that injected text reached the model), and the tool
          names the model asked for. No prompt or reply text is stored.
Standard library only. Usage (host):
  python3 model_proxy.py --listen 127.0.0.1:18080 --upstream http://127.0.0.1:11434 --model hermes3 --log proxy.jsonl
"""

import argparse
import http.client
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

CHAT_PATHS = {"/v1/chat/completions": "openai", "/api/chat": "ollama"}
LIST_PATHS = {"/v1/models", "/api/tags"}
TOOL_NAME = re.compile(rb'"name"\s*:\s*"([A-Za-z0-9_.\-]{1,64})"')


class Policy:
    def __init__(self, model, upstream, log_path=None, max_body=256 * 1024, max_tokens=1024, max_calls=200,
                 canaries=None, timeout=300):
        self.models = {model, model.split(":")[0], model if ":" in model else model + ":latest"}
        self.model = model
        self.upstream = urlsplit(upstream)
        self.log_path = log_path
        self.max_body, self.max_tokens, self.max_calls = max_body, max_tokens, max_calls
        self.canaries = canaries or {}
        self.timeout = timeout
        self.calls = 0
        self.lock = threading.Lock()
        self.records = []

    def log(self, rec):
        rec = {"time": round(time.time(), 3), **rec}
        with self.lock:
            self.records.append(rec)
            if self.log_path:
                with open(self.log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(rec) + "\n")


def _prompt_text(body):
    parts = []
    for m in body.get("messages") or []:
        c = m.get("content") if isinstance(m, dict) else None
        if isinstance(c, str):
            parts.append(c)
        elif isinstance(c, list):
            parts += [p.get("text", "") for p in c if isinstance(p, dict)]
    return "\n".join(parts)


def make_handler(policy: Policy):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _reply(self, code, obj):
            data = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _refuse(self, code, reason, **fields):
            policy.log({"method": self.command, "path": self.path[:200], "decision": "refused", "reason": reason,
                        **fields})
            self._reply(code, {"error": f"refused by workbench proxy: {reason}"})

        def _drain(self):
            n = int(self.headers.get("Content-Length", 0) or 0)
            if n > policy.max_body:
                return None
            return self.rfile.read(n) if n else b""

        def do_GET(self):
            path = urlsplit(self.path).path
            if path in LIST_PATHS:
                policy.log({"method": "GET", "path": path, "decision": "answered_locally"})
                if path == "/api/tags":
                    return self._reply(200, {"models": [{"name": policy.model, "model": policy.model}]})
                return self._reply(200, {"object": "list", "data": [{"id": policy.model, "object": "model"}]})
            return self._refuse(403, "path not allowed")

        def _other_method(self):
            self._drain()
            return self._refuse(403, "method not allowed")

        do_DELETE = do_PUT = do_PATCH = do_HEAD = do_OPTIONS = _other_method

        def do_POST(self):
            path = urlsplit(self.path).path
            if path not in CHAT_PATHS:
                self._drain()
                return self._refuse(403, "path not allowed")
            raw = self._drain()
            if raw is None:
                self.close_connection = True
                return self._refuse(413, "body too large")
            try:
                body = json.loads(raw or b"{}")
                assert isinstance(body, dict)
            except (ValueError, AssertionError):
                return self._refuse(400, "not a JSON object")
            model = str(body.get("model", ""))
            if model not in policy.models:
                return self._refuse(403, "model not allowed", model=model[:80])
            with policy.lock:
                if policy.calls >= policy.max_calls:
                    over = True
                else:
                    policy.calls += 1
                    over = False
            if over:
                return self._refuse(429, "call limit reached", model=model)
            # Lower the reply cap, never raise it.
            if CHAT_PATHS[path] == "openai":
                for key in ("max_tokens", "max_completion_tokens"):
                    if key in body:
                        body[key] = min(int(body[key] or policy.max_tokens), policy.max_tokens)
                body.setdefault("max_tokens", policy.max_tokens)
            else:
                opts = body.setdefault("options", {}) if isinstance(body.get("options", {}), dict) else {}
                body["options"] = opts
                opts["num_predict"] = min(int(opts.get("num_predict") or policy.max_tokens), policy.max_tokens)
            prompt = _prompt_text(body)
            meta = {"method": "POST", "path": path, "decision": "forwarded", "model": model,
                    "messages": len(body.get("messages") or []), "prompt_chars": len(prompt),
                    "canaries_in_prompt": sorted(n for n, v in policy.canaries.items() if v in prompt),
                    "tools_offered": len(body.get("tools") or []), "stream": bool(body.get("stream"))}
            self._forward(path, json.dumps(body).encode(), meta)

        def _forward(self, path, data, meta):
            u = policy.upstream
            conn = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=policy.timeout)
            seen, total = b"", 0
            try:
                conn.request("POST", path, body=data, headers={"Content-Type": "application/json"})
                resp = conn.getresponse()
                self.send_response(resp.status)
                self.send_header("Content-Type", resp.getheader("Content-Type", "application/json"))
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                while True:
                    chunk = resp.read1(65536)
                    if not chunk:
                        break
                    total += len(chunk)
                    if len(seen) < 512 * 1024:
                        seen += chunk
                    self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
                    self.wfile.flush()
                self.wfile.write(b"0\r\n\r\n")
                meta["upstream_status"] = resp.status
            except OSError as e:
                meta["upstream_error"] = type(e).__name__
                if total == 0:
                    try:
                        self._reply(502, {"error": "upstream unavailable"})
                    except OSError:
                        pass
            finally:
                conn.close()
            meta["reply_bytes"] = total
            meta["tool_calls_requested"] = (sorted(set(n.decode() for n in TOOL_NAME.findall(seen)))
                                            if b"tool_calls" in seen else [])
            policy.log(meta)

        def log_message(self, *args):
            pass

    return Handler


def serve(policy, host, port):
    srv = ThreadingHTTPServer((host, port), make_handler(policy))
    srv.daemon_threads = True
    return srv


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--listen", default="127.0.0.1:18080")
    ap.add_argument("--upstream", default="http://127.0.0.1:11434")
    ap.add_argument("--model", required=True)
    ap.add_argument("--log", default=None)
    ap.add_argument("--max-tokens", type=int, default=1024)
    ap.add_argument("--max-calls", type=int, default=200)
    ap.add_argument("--canary", action="append", default=[], help="NAME=VALUE, repeatable")
    a = ap.parse_args()
    host, port = a.listen.rsplit(":", 1)
    pol = Policy(a.model, a.upstream, a.log, max_tokens=a.max_tokens, max_calls=a.max_calls,
                 canaries=dict(c.split("=", 1) for c in a.canary))
    srv = serve(pol, host, int(port))
    print(f"proxy on {host}:{srv.server_address[1]} -> {a.upstream}, model {a.model}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()

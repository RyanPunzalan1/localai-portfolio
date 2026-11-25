"""Host-side model policy (design T4 and 5.2.2). Decides every model request from a sandbox; transport-independent.

The rules are the ones tested in the PoC proxy (experiments/workbench_poc/model_proxy.py), now as a pure decision:
  allowed   POST /v1/chat/completions and POST /api/chat, for the one allowlisted model, forwarded upstream
  local     GET /v1/models and /api/tags, answered here with only that model (no upstream call)
  refused   every other method or path (403), bodies over the cap (413), bad JSON (400), other models (403),
            calls over the per-trial cap (429). Refused requests are never forwarded.
  caps      reply tokens lowered to the cap, never raised
  record    metadata only: path, decision, model, message count, prompt size, which synthetic canaries appear in the
            prompt, tool names the model asked for. No prompt or reply text.
"""

import http.client
import json
import re
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit

CHAT_PATHS = {"/v1/chat/completions": "openai", "/api/chat": "ollama"}
LIST_PATHS = {"/v1/models", "/api/tags"}
TOOL_NAME = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")


@dataclass
class Decision:
    status: int                 # 200 when forwarded or answered locally
    forward: bool = False
    body: bytes = b""           # request body to forward, or the local/refusal response body
    meta: dict = field(default_factory=dict)


def _prompt_text(body):
    parts = []
    for m in body.get("messages") or []:
        c = m.get("content") if isinstance(m, dict) else None
        if isinstance(c, str):
            parts.append(c)
        elif isinstance(c, list):
            parts += [p.get("text", "") for p in c if isinstance(p, dict) and isinstance(p.get("text"), str)]
    return "\n".join(parts)


def tool_names(reply: bytes) -> list:
    """Names of the tools a model reply asks for, read ONLY from the reply's tool-call fields:
    Ollama  message.tool_calls[].function.name         (one object, or one object per line when streamed)
    OpenAI  choices[].message|delta.tool_calls[].function.name   (one object, or SSE "data:" lines)
    Argument values are never searched, so text a model puts inside an argument cannot fake a tool name."""
    text = reply.decode("utf-8", "replace")
    docs = []
    try:
        docs.append(json.loads(text))
    except ValueError:
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                line = line[5:].strip()
            if line and line != "[DONE]":
                try:
                    docs.append(json.loads(line))
                except ValueError:
                    continue
    names = set()

    def take(holder):
        calls = holder.get("tool_calls") if isinstance(holder, dict) else None
        for c in calls if isinstance(calls, list) else []:
            fn = c.get("function") if isinstance(c, dict) else None
            n = fn.get("name") if isinstance(fn, dict) else None
            if isinstance(n, str) and TOOL_NAME.match(n):
                names.add(n)

    for d in docs:
        if not isinstance(d, dict):
            continue
        take(d.get("message"))
        for ch in d.get("choices") if isinstance(d.get("choices"), list) else []:
            if isinstance(ch, dict):
                take(ch.get("message"))
                take(ch.get("delta"))
    return sorted(names)


class ModelPolicy:
    def __init__(self, model, max_body=256 * 1024, max_tokens=1024, max_calls=200, canaries=None,
                 keep_reply_heads=0):
        self.model = model
        self.names = {model, model.split(":")[0], model if ":" in model else model + ":latest"}
        self.max_body, self.max_tokens, self.max_calls = max_body, max_tokens, max_calls
        self.canaries = dict(canaries or {})
        self.keep_reply_heads = keep_reply_heads  # debugging only: reply text kept IN MEMORY, never in a record file
        self.calls = 0
        self.records = []
        self._lock = threading.Lock()

    def _refuse(self, status, reason, method, path, **fields):
        meta = {"method": method, "path": path[:200], "decision": "refused", "reason": reason, **fields}
        return Decision(status, False, json.dumps({"error": f"refused by workbench: {reason}"}).encode(), meta)

    def decide(self, method: str, path: str, body: bytes) -> Decision:
        path = urlsplit(path).path
        if method == "GET" and path in LIST_PATHS:
            meta = {"method": method, "path": path, "decision": "answered_locally"}
            if path == "/api/tags":
                out = {"models": [{"name": self.model, "model": self.model}]}
            else:
                out = {"object": "list", "data": [{"id": self.model, "object": "model"}]}
            return Decision(200, False, json.dumps(out).encode(), meta)
        if method != "POST":
            return self._refuse(403, "method not allowed", method, path)
        if path not in CHAT_PATHS:
            return self._refuse(403, "path not allowed", method, path)
        if len(body) > self.max_body:
            return self._refuse(413, "body too large", method, path)
        try:
            req = json.loads(body or b"{}")
            assert isinstance(req, dict)
        except (ValueError, AssertionError):
            return self._refuse(400, "not a JSON object", method, path)
        model = str(req.get("model", ""))
        if model not in self.names:
            return self._refuse(403, "model not allowed", method, path, model=model[:80])
        with self._lock:
            if self.calls >= self.max_calls:
                return self._refuse(429, "call limit reached", method, path, model=model)
            self.calls += 1
        try:
            if CHAT_PATHS[path] == "openai":
                for key in ("max_tokens", "max_completion_tokens"):
                    if key in req:
                        req[key] = min(int(req[key] or self.max_tokens), self.max_tokens)
                req.setdefault("max_tokens", self.max_tokens)
            else:
                opts = req.get("options") if isinstance(req.get("options"), dict) else {}
                opts["num_predict"] = min(int(opts.get("num_predict") or self.max_tokens), self.max_tokens)
                req["options"] = opts
        except (TypeError, ValueError):
            return self._refuse(400, "bad token limit", method, path, model=model)
        prompt = _prompt_text(req)
        meta = {"method": method, "path": path, "decision": "forwarded", "model": model,
                "messages": len(req.get("messages") or []) if isinstance(req.get("messages"), list) else 0,
                "prompt_chars": len(prompt),
                "canaries_in_prompt": sorted(n for n, v in self.canaries.items() if v and v in prompt),
                "tools_offered": len(req.get("tools") or []) if isinstance(req.get("tools"), list) else 0,
                "stream": bool(req.get("stream")),
                "reply_cap": req.get("max_tokens") if CHAT_PATHS[path] == "openai" else req["options"]["num_predict"]}
        return Decision(200, True, json.dumps(req).encode(), meta)

    def record(self, meta, reply_head=b"", reply_bytes=0, upstream_status=None, error=None):
        rec = {"time": round(time.time(), 3), **meta}
        if meta.get("decision") == "forwarded":
            rec.update(upstream_status=upstream_status, reply_bytes=reply_bytes,
                       tool_calls_requested=tool_names(reply_head))
            if self.keep_reply_heads:
                rec["_reply_head"] = reply_head[: self.keep_reply_heads].decode("utf-8", "replace")
        if error:
            rec["error"] = error
        with self._lock:
            self.records.append(rec)
        return rec


def forward(upstream: str, path: str, body: bytes, timeout=300):
    """Send an allowed request to the model server. Yields (status, content_type) first, then reply chunks."""
    u = urlsplit(upstream)
    if u.hostname not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("the model server must be on this machine (no cloud models)")
    conn = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=timeout)
    try:
        conn.request("POST", path, body=body, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        yield resp.status, resp.getheader("Content-Type", "application/json")
        while True:
            chunk = resp.read1(65536)
            if not chunk:
                break
            yield chunk
    finally:
        conn.close()

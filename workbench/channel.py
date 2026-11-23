"""Host end of the model and approval channel (design 5.2.2a; decision D9). Trusted; runs outside the sandbox.

Starts the shim inside the sandbox over the runtime's command channel (`sbx exec -i` / `docker exec -i`), reads one
JSON line per request from its stdout, decides each request with ModelPolicy (or the fixed approval policy), forwards
allowed chat calls to the local model server, and writes the reply back as frames. There is no socket on the host
side and no network route from the sandbox.

Every line from the sandbox is hostile input. Any violation of the protocol ends the channel for the trial
(`violation` is set; the trial is inconclusive), rather than being guessed around.
"""

import base64
import binascii
import json
import subprocess
import threading
from pathlib import Path

from workbench import model_policy as mp

SHIM_SOURCE = (Path(__file__).resolve().parent / "channel_shim.py").read_text(encoding="utf-8")
SHIM_PORT = 13131
MAX_LINE = 1536 * 1024          # a 1 MiB body, base64-encoded, plus the frame
MAX_OPEN = 4                    # requests in flight at once
MAX_REQUESTS = 500              # per trial, of any kind
METHODS = {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}
APPROVAL_PATH = "/approval"


class ChannelViolation(Exception):
    """The sandbox broke the protocol. The channel is closed and the trial is inconclusive."""


def parse_frame(line: bytes, open_ids: set) -> dict:
    """Validate one line from the sandbox. Returns {id, method, path, body} or raises ChannelViolation."""
    if len(line) > MAX_LINE:
        raise ChannelViolation("line too long")
    if not line.endswith(b"\n"):
        raise ChannelViolation("line not terminated (too long or truncated)")
    try:
        msg = json.loads(line)
    except ValueError:
        raise ChannelViolation("not JSON") from None
    if not isinstance(msg, dict) or set(msg) - {"id", "type", "method", "path", "body", "port"}:
        raise ChannelViolation("unknown fields")
    if msg.get("type") == "ready":
        if msg.get("id") != 0 or not isinstance(msg.get("port"), int):
            raise ChannelViolation("bad ready frame")
        return {"ready": True, "port": msg["port"]}
    if msg.get("type") != "request":
        raise ChannelViolation("unexpected frame type")
    rid, method, path, body = msg.get("id"), msg.get("method"), msg.get("path"), msg.get("body", "")
    if not isinstance(rid, int) or isinstance(rid, bool) or rid <= 0 or rid in open_ids:
        raise ChannelViolation("bad or reused id")
    if method not in METHODS:
        raise ChannelViolation("bad method")
    if not isinstance(path, str) or not path.startswith("/") or len(path) > 512 or any(ord(c) < 32 for c in path):
        raise ChannelViolation("bad path")
    if not isinstance(body, str):
        raise ChannelViolation("bad body")
    try:
        raw = base64.b64decode(body, validate=True)
    except (binascii.Error, ValueError):
        raise ChannelViolation("body is not base64") from None
    return {"id": rid, "method": method, "path": path, "body": raw}


def shim_command(runtime: str, name: str) -> list:
    if runtime == "sbx":
        return ["sbx", "exec", "-i", name, "--", "python3", "-c", SHIM_SOURCE, "--port", str(SHIM_PORT)]
    if runtime == "docker":
        return ["docker", "exec", "-i", name, "python3", "-c", SHIM_SOURCE, "--port", str(SHIM_PORT)]
    raise ValueError(runtime)


class Channel:
    def __init__(self, command, policy: mp.ModelPolicy, upstream="http://127.0.0.1:11434", approval="deny_all"):
        if approval not in ("deny_all", "approve_all"):
            raise ValueError("approval policy must be deny_all or approve_all")
        self.policy, self.upstream, self.approval = policy, upstream, approval
        self.approvals = []
        self.violation = None
        self.requests = 0
        self.port = None
        self._open = set()
        self._wlock = threading.Lock()
        self._slots = threading.Semaphore(MAX_OPEN)
        self._ready = threading.Event()
        self.proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()

    def wait_ready(self, timeout=60) -> bool:
        return self._ready.wait(timeout) and self.violation is None

    # ---------------------------------------------------------------- reading (hostile input)
    def _read_loop(self):
        try:
            while True:
                line = self.proc.stdout.readline(MAX_LINE + 1)
                if not line:
                    break
                frame = parse_frame(line, self._open)
                if frame.get("ready"):
                    if self._ready.is_set():
                        raise ChannelViolation("second ready frame")
                    self.port = frame["port"]
                    self._ready.set()
                    continue
                if not self._ready.is_set():
                    raise ChannelViolation("request before ready")
                self.requests += 1
                if self.requests > MAX_REQUESTS:
                    raise ChannelViolation("request limit reached")
                if not self._slots.acquire(blocking=False):
                    raise ChannelViolation("too many requests in flight")
                self._open.add(frame["id"])
                threading.Thread(target=self._handle, args=(frame,), daemon=True).start()
        except ChannelViolation as e:
            self.violation = str(e)
            self.close()
        finally:
            self._ready.set()

    # ---------------------------------------------------------------- answering
    def _write(self, obj):
        data = (json.dumps(obj, separators=(",", ":")) + "\n").encode()
        with self._wlock:
            try:
                self.proc.stdin.write(data)
                self.proc.stdin.flush()
            except (BrokenPipeError, ValueError, OSError):
                pass

    def _reply(self, rid, status, body, content_type="application/json"):
        self._write({"id": rid, "type": "start", "status": status, "content_type": content_type})
        if body:
            self._write({"id": rid, "type": "chunk", "data": base64.b64encode(body).decode()})
        self._write({"id": rid, "type": "end"})

    def _handle(self, frame):
        rid = frame["id"]
        try:
            if frame["path"].split("?", 1)[0] == APPROVAL_PATH:
                return self._approval(rid, frame)
            d = self.policy.decide(frame["method"], frame["path"], frame["body"])
            if not d.forward:
                self.policy.record(d.meta)
                return self._reply(rid, d.status, d.body)
            head, total, status = b"", 0, None
            try:
                gen = mp.forward(self.upstream, d.meta["path"], d.body)
                status, ctype = next(gen)
                self._write({"id": rid, "type": "start", "status": status, "content_type": ctype})
                for chunk in gen:
                    total += len(chunk)
                    if len(head) < 512 * 1024:
                        head += chunk
                    self._write({"id": rid, "type": "chunk", "data": base64.b64encode(chunk).decode()})
                self._write({"id": rid, "type": "end"})
                self.policy.record(d.meta, head, total, status)
            except OSError as e:
                self.policy.record(d.meta, error=type(e).__name__)
                if status is None:
                    self._reply(rid, 502, b'{"error": "model server unavailable"}')
                else:
                    self._write({"id": rid, "type": "end"})
        finally:
            self._open.discard(rid)
            self._slots.release()

    def _approval(self, rid, frame):
        try:
            req = json.loads(frame["body"] or b"{}")
            assert isinstance(req, dict) and frame["method"] == "POST"
        except (ValueError, AssertionError):
            return self._reply(rid, 400, b'{"error": "approval request must be a JSON object, POST"}')
        decision = "approve" if self.approval == "approve_all" else "deny"
        self.approvals.append({"action": str(req.get("action", ""))[:40], "target": str(req.get("target", ""))[:200],
                               "decision": decision})
        self._reply(rid, 200, json.dumps({"decision": decision}).encode())

    def close(self):
        try:
            self.proc.kill()
        except OSError:
            pass

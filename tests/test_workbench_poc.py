"""Tests for the workbench proof of concept (design/workbench-substrate-evaluation.md section 6).

Temporary folders and synthetic files only. No Docker, sandbox or model is needed here.
"""

import hashlib
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "experiments" / "workbench_poc"))

import safe_digest as sd  # noqa: E402


@unittest.skipIf(sys.platform == "win32", "PoC copy of the digest (uses O_NOFOLLOW); superseded by workbench.digest, tested in tests/test_digest.py")
class SafeDigestTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp()).resolve()
        self.ws = self.base / "ws"
        self.ws.mkdir()
        self.outside = self.base / "outside_secret.txt"
        self.outside.write_text("HOST-ONLY-CONTENT", encoding="utf-8")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.base, ignore_errors=True)

    def test_regular_files_are_hashed(self):
        (self.ws / "a.md").write_text("hello", encoding="utf-8")
        (self.ws / "sub").mkdir()
        (self.ws / "sub" / "b.txt").write_text("x", encoding="utf-8")
        d = sd.digest(self.ws)
        self.assertEqual(d["a.md"], "file:" + hashlib.sha256(b"hello").hexdigest())
        self.assertEqual(d["sub"], "dir")
        self.assertIn("sub/b.txt", d)

    def test_a_link_to_an_outside_file_is_recorded_not_read(self):
        os.symlink(self.outside, self.ws / "link.md")
        d = sd.digest(self.ws)
        self.assertEqual(d["link.md"], f"link:{self.outside}")
        outside_hash = hashlib.sha256(b"HOST-ONLY-CONTENT").hexdigest()
        self.assertNotIn(outside_hash, " ".join(d.values()))  # the old digest_tree put exactly this hash here

    def test_a_directory_link_is_not_walked(self):
        (self.base / "outdir").mkdir()
        (self.base / "outdir" / "inner.txt").write_text("secret", encoding="utf-8")
        os.symlink(self.base / "outdir", self.ws / "dirlink")
        d = sd.digest(self.ws)
        self.assertTrue(d["dirlink"].startswith("link:"))
        self.assertFalse(any(k.startswith("dirlink/") for k in d))

    def test_a_fifo_is_not_opened_and_does_not_hang(self):
        os.mkfifo(self.ws / "pipe")
        result = {}
        t = threading.Thread(target=lambda: result.setdefault("d", sd.digest(self.ws)), daemon=True)
        t.start()
        t.join(timeout=5)
        self.assertFalse(t.is_alive(), "digest hung on a FIFO")
        self.assertEqual(result["d"]["pipe"], "special:fifo")

    def test_large_files_are_capped(self):
        old = sd.MAX_FILE_BYTES
        sd.MAX_FILE_BYTES = 1000
        try:
            (self.ws / "big.bin").write_bytes(b"x" * 5000)
            self.assertIn(":truncated:5000", sd.digest(self.ws)["big.bin"])
        finally:
            sd.MAX_FILE_BYTES = old

    def test_hard_link_to_an_outside_file_is_flagged(self):
        os.link(self.outside, self.ws / "hard.md")
        self.assertTrue(sd.digest(self.ws)["hard.md"].endswith(":nlink>1"))

    def test_entry_limit_raises(self):
        old = sd.MAX_ENTRIES
        sd.MAX_ENTRIES = 3
        try:
            for i in range(5):
                (self.ws / f"f{i}.txt").write_text("x", encoding="utf-8")
            with self.assertRaises(sd.DigestLimit):
                sd.digest(self.ws)
        finally:
            sd.MAX_ENTRIES = old

    def test_root_must_be_a_real_directory(self):
        os.symlink(self.ws, self.base / "wslink")
        with self.assertRaises(ValueError):
            sd.digest(self.base / "wslink")

    def test_changes(self):
        before = {"a": "file:1", "b": "file:2"}
        after = {"a": "file:1", "b": "file:3", "c": "link:/x"}
        self.assertEqual(sd.changes(before, after), {"created": ["c"], "removed": [], "modified": ["b"]})



import json  # noqa: E402
import http.client  # noqa: E402
import time  # noqa: E402
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: E402

import model_proxy as mp  # noqa: E402


class FakeUpstream:
    """Records every request that reaches it, and answers chat calls with one tool call."""

    def __init__(self):
        self.seen = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0) or 0)
                outer.seen.append((self.command, self.path, json.loads(self.rfile.read(n) or b"{}")))
                data = json.dumps({"choices": [{"message": {"tool_calls": [
                    {"function": {"name": "read_file", "arguments": "{}"}}]}}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_DELETE(self):
                outer.seen.append((self.command, self.path, None))
                self.send_response(200)
                self.end_headers()

            def log_message(self, *a):
                pass

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"


def wait_for_record(policy, timeout=5.0):
    """The policy records a forwarded call after it has streamed the reply, so the client can see the reply first."""
    end = time.time() + timeout
    while time.time() < end:
        found = [r for r in list(policy.records) if r["decision"] == "forwarded"]
        if found:
            return found
        time.sleep(0.02)
    return []


class ModelProxyTests(unittest.TestCase):
    def setUp(self):
        self.up = FakeUpstream()
        self.policy = mp.Policy("hermes3", self.up.url, max_tokens=100, max_calls=3, max_body=2000,
                                canaries={"env": "CANARY-ENV-TEST"})
        self.srv = mp.serve(self.policy, "127.0.0.1", 0)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.port = self.srv.server_address[1]

    def tearDown(self):
        for srv in (self.srv, self.up.srv):
            srv.shutdown()
            srv.server_close()

    def req(self, method, path, body=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        data = json.dumps(body).encode() if isinstance(body, dict) else body
        c.request(method, path, body=data, headers={"Content-Type": "application/json"})
        r = c.getresponse()
        out = r.status, r.read()
        c.close()
        return out

    def chat(self, **extra):
        return {"model": "hermes3", "messages": [{"role": "user", "content": "hi"}], **extra}

    def test_admin_calls_are_refused_and_never_forwarded(self):
        for method, path in [("POST", "/api/pull"), ("POST", "/api/push"), ("POST", "/api/create"),
                             ("POST", "/api/copy"), ("DELETE", "/api/delete"), ("POST", "/api/generate"),
                             ("POST", "/api/embed"), ("GET", "/api/ps"), ("GET", "/api/version")]:
            status, _ = self.req(method, path, {"model": "hermes3", "name": "evil.example/x"})
            self.assertEqual(status, 403, (method, path))
        self.assertEqual(self.up.seen, [])

    def test_other_models_are_refused(self):
        status, _ = self.req("POST", "/v1/chat/completions", {"model": "llama3:70b", "messages": []})
        self.assertEqual(status, 403)
        self.assertEqual(self.up.seen, [])

    def test_allowed_chat_is_forwarded_with_the_reply_cap_lowered(self):
        status, body = self.req("POST", "/v1/chat/completions", self.chat(max_tokens=99999))
        self.assertEqual(status, 200)
        self.assertEqual(self.up.seen[0][2]["max_tokens"], 100)
        status, _ = self.req("POST", "/api/chat", self.chat(options={"num_predict": 50}))
        self.assertEqual(self.up.seen[1][2]["options"]["num_predict"], 50)  # lower requests are kept

    def test_tags_and_models_list_only_the_allowed_model_without_upstream(self):
        status, body = self.req("GET", "/api/tags")
        self.assertEqual([m["name"] for m in json.loads(body)["models"]], ["hermes3"])
        self.assertEqual(self.up.seen, [])

    def test_body_size_and_call_limits(self):
        status, _ = self.req("POST", "/v1/chat/completions", b"x" * 5000)
        self.assertEqual(status, 413)
        for _ in range(3):
            self.assertEqual(self.req("POST", "/v1/chat/completions", self.chat())[0], 200)
        self.assertEqual(self.req("POST", "/v1/chat/completions", self.chat())[0], 429)
        self.assertEqual(len(self.up.seen), 3)

    def test_log_records_canaries_and_tool_calls_but_no_text(self):
        body = self.chat()
        body["messages"] = [{"role": "user", "content": "note text CANARY-ENV-TEST more"}]
        self.req("POST", "/v1/chat/completions", body)
        rec = wait_for_record(self.policy)[-1]
        self.assertEqual(rec["canaries_in_prompt"], ["env"])
        self.assertEqual(rec["tool_calls_requested"], ["read_file"])
        self.assertNotIn("note text", json.dumps(self.policy.records))

    def test_bad_json_is_refused(self):
        self.assertEqual(self.req("POST", "/v1/chat/completions", b"[1,2]")[0], 400)


if __name__ == "__main__":
    unittest.main()

"""Tests for the Phase 2 model channel: host-side policy, hostile-frame parsing, and the shim end to end.

The "sandbox" here is a local subprocess running the real shim, and the model server is a fake on 127.0.0.1, so no
Docker, sbx or model is needed. Synthetic data only.
"""

import base64
import http.client
import json
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from workbench import channel as ch, model_policy as mp  # noqa: E402

CANARY = "CANARY-CHANNEL-TEST"


class FakeModel:
    """Records every request that reaches it; answers chat with one tool call, streamed in two chunks."""

    def __init__(self):
        self.seen = []
        outer = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0) or 0)
                outer.seen.append((self.path, json.loads(self.rfile.read(n) or b"{}")))
                parts = [b'{"choices":[{"message":{"tool_calls":[{"function":',
                         b'{"name":"read_file","arguments":"{}"}}]}}]}']
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(sum(map(len, parts))))
                self.end_headers()
                for p in parts:
                    self.wfile.write(p)
                    self.wfile.flush()

            def log_message(self, *a):
                pass

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def stop(self):
        self.srv.shutdown()
        self.srv.server_close()


def frame(**kw):
    base = {"id": 1, "type": "request", "method": "POST", "path": "/v1/chat/completions", "body": ""}
    base.update(kw)
    return (json.dumps(base) + "\n").encode()


class ParseFrameTests(unittest.TestCase):
    def test_a_valid_request(self):
        f = ch.parse_frame(frame(body=base64.b64encode(b"{}").decode()), set())
        self.assertEqual((f["id"], f["method"], f["body"]), (1, "POST", b"{}"))

    def test_hostile_frames_are_rejected(self):
        bad = {
            "not json": b"{oops\n",
            "unterminated": frame()[:-1],
            "too long": b'{"x":"' + b"a" * (ch.MAX_LINE + 10) + b'"}\n',
            "list": b"[1,2]\n",
            "unknown field": frame(extra=1),
            "bad type": frame(type="response"),
            "id zero": frame(id=0),
            "id string": frame(id="1"),
            "id bool": frame(id=True),
            "bad method": frame(method="CONNECT"),
            "relative path": frame(path="v1/chat"),
            "control char in path": frame(path="/a\r\nHost: x"),
            "long path": frame(path="/" + "a" * 600),
            "body not base64": frame(body="***"),
            "body not string": frame(body=123),
        }
        for label, line in bad.items():
            with self.assertRaises(ch.ChannelViolation, msg=label):
                ch.parse_frame(line, set())

    def test_reused_id_is_rejected(self):
        with self.assertRaises(ch.ChannelViolation):
            ch.parse_frame(frame(id=7), {7})

    def test_ready_frame(self):
        self.assertEqual(ch.parse_frame(b'{"id":0,"type":"ready","port":13131}\n', set()), {"ready": True, "port": 13131})
        with self.assertRaises(ch.ChannelViolation):
            ch.parse_frame(b'{"id":3,"type":"ready","port":1}\n', set())


class ModelPolicyTests(unittest.TestCase):
    def setUp(self):
        self.p = mp.ModelPolicy("hermes3", max_tokens=100, max_calls=2, max_body=2000, canaries={"c": CANARY})

    def chat(self, **kw):
        return json.dumps({"model": "hermes3", "messages": [{"role": "user", "content": "hi"}], **kw}).encode()

    def test_admin_and_other_paths_are_refused(self):
        for method, path in [("POST", "/api/pull"), ("POST", "/api/push"), ("POST", "/api/create"),
                             ("POST", "/api/copy"), ("DELETE", "/api/delete"), ("POST", "/api/generate"),
                             ("POST", "/api/embed"), ("GET", "/api/ps"), ("GET", "/api/version"), ("PUT", "/x")]:
            d = self.p.decide(method, path, b'{"model":"hermes3"}')
            self.assertEqual((d.forward, d.status), (False, 403), (method, path))

    def test_model_size_json_and_call_limits(self):
        self.assertEqual(self.p.decide("POST", "/api/chat", b'{"model":"llama3:70b"}').status, 403)
        self.assertEqual(self.p.decide("POST", "/api/chat", b"x" * 3000).status, 413)
        self.assertEqual(self.p.decide("POST", "/api/chat", b"[1]").status, 400)
        self.assertTrue(self.p.decide("POST", "/v1/chat/completions", self.chat()).forward)
        self.assertTrue(self.p.decide("POST", "/v1/chat/completions", self.chat()).forward)
        self.assertEqual(self.p.decide("POST", "/v1/chat/completions", self.chat()).status, 429)

    def test_reply_cap_is_lowered_never_raised(self):
        d = self.p.decide("POST", "/v1/chat/completions", self.chat(max_tokens=99999))
        self.assertEqual(json.loads(d.body)["max_tokens"], 100)
        self.assertEqual(d.meta["reply_cap"], 100)
        d = self.p.decide("POST", "/api/chat", self.chat(options={"num_predict": 40}))
        self.assertEqual(json.loads(d.body)["options"]["num_predict"], 40)

    def test_bad_token_limit_is_refused(self):
        self.assertEqual(self.p.decide("POST", "/v1/chat/completions", self.chat(max_tokens="lots")).status, 400)

    def test_lists_are_answered_locally(self):
        d = self.p.decide("GET", "/api/tags", b"")
        self.assertEqual([m["name"] for m in json.loads(d.body)["models"]], ["hermes3"])
        self.assertFalse(d.forward)

    def test_canary_is_recorded_without_text(self):
        body = json.dumps({"model": "hermes3", "messages": [{"role": "user", "content": f"note {CANARY}"}]}).encode()
        d = self.p.decide("POST", "/api/chat", body)
        rec = self.p.record(d.meta, b'{"message":{"tool_calls":[{"function":{"name":"read_file"}}]}}', 50, 200)
        self.assertEqual(rec["canaries_in_prompt"], ["c"])
        self.assertEqual(rec["tool_calls_requested"], ["read_file"])
        self.assertNotIn("note", json.dumps(rec))

    def test_forward_refuses_a_remote_model_server(self):
        with self.assertRaises(ValueError):
            next(mp.forward("http://api.example.com", "/v1/chat/completions", b"{}"))


class ToolNameTests(unittest.TestCase):
    def test_ollama_and_openai_shapes(self):
        ollama = b'{"message":{"role":"assistant","tool_calls":[{"function":{"name":"read_file","arguments":{"name":"task.md"}}}]}}'
        self.assertEqual(mp.tool_names(ollama), ["read_file"])
        stream = (b'{"message":{"content":"hi"}}\n{"message":{"tool_calls":[{"function":{"name":"list_files"}}]}}\n'
                  b'{"done":true}\n')
        self.assertEqual(mp.tool_names(stream), ["list_files"])
        openai = b'{"choices":[{"message":{"tool_calls":[{"function":{"name":"save_note","arguments":"{}"}}]}}]}'
        self.assertEqual(mp.tool_names(openai), ["save_note"])
        sse = (b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"name":"read_file","arguments":""}}]}}]}\n\n'
               b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{}"}}]}}]}\n\ndata: [DONE]\n')
        self.assertEqual(mp.tool_names(sse), ["read_file"])

    def test_argument_values_cannot_fake_a_tool_name(self):
        hostile = (b'{"message":{"tool_calls":[{"function":{"name":"read_file","arguments":{"name":"save_note",'
                   b'"tool_calls":[{"function":{"name":"save_note"}}]}}}]}}')
        self.assertEqual(mp.tool_names(hostile), ["read_file"])
        text_only = b'{"message":{"content":"{\\"name\\": \\"save_note\\"} tool_calls"}}'
        self.assertEqual(mp.tool_names(text_only), [])

    def test_junk_and_bad_names_are_ignored(self):
        self.assertEqual(mp.tool_names(b"not json at all"), [])
        self.assertEqual(mp.tool_names(b'{"message":{"tool_calls":[{"function":{"name":"a b; rm"}},5,"x"]}}'), [])
        self.assertEqual(mp.tool_names(b'[1,2]'), [])


class ChannelEndToEndTests(unittest.TestCase):
    """The real shim as a local subprocess (standing in for the sandbox), the real host channel, a fake model."""

    def setUp(self):
        self.model = FakeModel()
        self.policy = mp.ModelPolicy("hermes3", max_tokens=100, canaries={"c": CANARY})
        cmd = [sys.executable, "-c", ch.SHIM_SOURCE, "--port", "0"]
        self.chan = ch.Channel(cmd, self.policy, upstream=self.model.url, approval="deny_all")
        self.assertTrue(self.chan.wait_ready(30), self.chan.violation)

    def tearDown(self):
        self.chan.close()
        self.chan.proc.wait(timeout=10)
        for s in (self.chan.proc.stdin, self.chan.proc.stdout, self.chan.proc.stderr):
            s.close()
        self.model.stop()

    def req(self, method, path, body=None):
        c = http.client.HTTPConnection("127.0.0.1", self.chan.port, timeout=30)
        data = json.dumps(body).encode() if isinstance(body, dict) else body
        c.request(method, path, body=data, headers={"Content-Type": "application/json"})
        r = c.getresponse()
        out = r.status, r.read()
        c.close()
        return out

    def test_allowed_chat_goes_through_with_cap_and_canary_record(self):
        status, body = self.req("POST", "/v1/chat/completions",
                                {"model": "hermes3", "max_tokens": 5000,
                                 "messages": [{"role": "user", "content": f"x {CANARY}"}]})
        self.assertEqual(status, 200)
        self.assertIn(b"read_file", body)                       # streamed chunks reassembled
        self.assertEqual(self.model.seen[0][1]["max_tokens"], 100)
        rec = [r for r in self.policy.records if r["decision"] == "forwarded"][0]
        self.assertEqual((rec["canaries_in_prompt"], rec["tool_calls_requested"]), (["c"], ["read_file"]))

    def test_admin_calls_never_reach_the_model_server(self):
        for method, path in [("POST", "/api/pull"), ("DELETE", "/api/delete"), ("POST", "/api/create")]:
            self.assertEqual(self.req(method, path, {"name": "registry.example.test/x"})[0], 403)
        self.assertEqual(self.model.seen, [])

    def test_approval_is_decided_on_the_host(self):
        status, body = self.req("POST", "/approval", {"action": "write", "target": "notes.md", "summary": "s"})
        self.assertEqual((status, json.loads(body)), (200, {"decision": "deny"}))
        self.assertEqual(self.chan.approvals, [{"action": "write", "target": "notes.md", "decision": "deny"}])

    def test_concurrent_requests(self):
        results = []
        ts = [threading.Thread(target=lambda: results.append(self.req("GET", "/api/tags")[0])) for _ in range(3)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(30)
        self.assertEqual(results, [200, 200, 200])
        self.assertIsNone(self.chan.violation)


class HostileShimTests(unittest.TestCase):
    """A sandbox that ignores the protocol: the host must stop the channel, not guess."""

    def run_fake(self, script):
        chan = ch.Channel([sys.executable, "-c", script], mp.ModelPolicy("hermes3"), upstream="http://127.0.0.1:9")
        deadline = time.time() + 20
        while chan.violation is None and time.time() < deadline and chan.proc.poll() is None:
            time.sleep(0.05)
        chan._thread.join(5)
        chan.close()
        chan.proc.wait(timeout=10)
        for s in (chan.proc.stdin, chan.proc.stdout, chan.proc.stderr):
            s.close()
        return chan

    def test_garbage_output_ends_the_channel(self):
        chan = self.run_fake("print('{\"id\":0,\"type\":\"ready\",\"port\":1}'); print('hello, not a frame', flush=True); "
                             "import time; time.sleep(30)")
        self.assertEqual(chan.violation, "not JSON")

    def test_request_before_ready_ends_the_channel(self):
        line = json.dumps({"id": 1, "type": "request", "method": "GET", "path": "/api/tags", "body": ""})
        chan = self.run_fake(f"print({line!r}, flush=True); import time; time.sleep(30)")
        self.assertEqual(chan.violation, "request before ready")

    def test_flood_of_requests_is_limited(self):
        """Requests stay open because the model server never answers, so the in-flight limit is reached for certain."""
        import socket
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(16)
        held = []
        threading.Thread(target=lambda: [held.append(srv.accept()[0]) for _ in range(16)], daemon=True).start()
        body = base64.b64encode(json.dumps({"model": "hermes3", "messages": [{"role": "user", "content": "x"}]}).encode())
        script = ("import json,sys,time\nprint(json.dumps({'id':0,'type':'ready','port':1}), flush=True)\n"
                  "for i in range(1, 9): print(json.dumps({'id':i,'type':'request','method':'POST',"
                  f"'path':'/v1/chat/completions','body':'{body.decode()}'}}), flush=True)\ntime.sleep(30)")
        try:
            chan = ch.Channel([sys.executable, "-c", script], mp.ModelPolicy("hermes3"),
                              upstream=f"http://127.0.0.1:{srv.getsockname()[1]}")
            deadline = time.time() + 20
            while chan.violation is None and time.time() < deadline:
                time.sleep(0.05)
            chan._thread.join(5)
            chan.close()
            chan.proc.wait(timeout=10)
            for s_ in (chan.proc.stdin, chan.proc.stdout, chan.proc.stderr):
                s_.close()
            self.assertEqual(chan.violation, "too many requests in flight")
        finally:
            for c in held:
                c.close()
            srv.close()


if __name__ == "__main__":
    unittest.main()

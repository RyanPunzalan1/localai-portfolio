"""The model a run used: its digest is recorded, and only a locally installed, non-cloud model can be used.

No real Ollama is needed: the model list is passed in, or served by a fake on 127.0.0.1.
"""

import contextlib
import io
import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from workbench import cli, model_info as mi  # noqa: E402

HEX = "b702e8c26d5c" + "0" * 52
LOCAL = [{"name": "gpt-oss-64k:latest", "model": "gpt-oss-64k:latest", "digest": HEX},
         {"name": "hermes3:latest", "model": "hermes3:latest", "digest": "sha256:" + "1" * 64},
         {"name": "nodigest:latest", "model": "nodigest:latest", "digest": "?"},
         {"name": "big:latest", "model": "big:latest", "digest": "2" * 64, "remote_host": "https://ollama.com:443"}]


class CheckLocal(unittest.TestCase):
    def test_installed_model_is_allowed_with_or_without_tag(self):
        self.assertEqual(mi.check_local("gpt-oss-64k", LOCAL), [])
        self.assertEqual(mi.check_local("gpt-oss-64k:latest", LOCAL), [])

    def test_missing_model_is_refused_and_never_pulled(self):
        problems = mi.check_local("llama3:70b", LOCAL)
        self.assertEqual(len(problems), 1)
        self.assertIn("never pulls", problems[0])

    def test_cloud_models_are_refused(self):
        for name in ("gpt-oss:120b-cloud", "qwen3:cloud", "big"):
            with self.subTest(name=name):
                self.assertIn("cloud model", mi.check_local(name, LOCAL)[0])

    def test_model_without_a_digest_is_refused(self):
        self.assertIn("no digest", mi.check_local("nodigest", LOCAL)[0])

    def test_unreachable_ollama_is_a_problem_not_a_pass(self):
        with mock.patch.object(mi, "tags", side_effect=mi.ModelUnavailable("Ollama is not reachable")):
            self.assertEqual(mi.check_local("gpt-oss-64k"), ["Ollama is not reachable"])


class Digest(unittest.TestCase):
    def test_digest_is_normalised(self):
        self.assertEqual(mi.digest("gpt-oss-64k", LOCAL), "sha256:" + HEX)
        self.assertEqual(mi.digest("hermes3", LOCAL), "sha256:" + "1" * 64)

    def test_unknown_or_cloud_or_unreachable_is_none_never_a_guess(self):
        self.assertIsNone(mi.digest("missing", LOCAL))
        self.assertIsNone(mi.digest("big", LOCAL))
        self.assertIsNone(mi.digest("nodigest", LOCAL))
        with mock.patch.object(mi, "tags", side_effect=mi.ModelUnavailable("down")):
            self.assertIsNone(mi.digest("gpt-oss-64k"))


class TagsFromOllama(unittest.TestCase):
    def setUp(self):
        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                body = json.dumps({"models": LOCAL}).encode() if self.path == "/api/tags" else b"{}"
                self.send_response(200 if self.path == "/api/tags" else 404)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()

    def test_reads_the_local_list_and_ignores_proxy_settings(self):
        with mock.patch.dict(os.environ, {"HTTP_PROXY": "http://127.0.0.1:9", "http_proxy": "http://127.0.0.1:9"}):
            entries = mi.tags(self.url)
        self.assertEqual(mi.digest("gpt-oss-64k", entries), "sha256:" + HEX)

    def test_nothing_listening_raises(self):
        import socket
        s = socket.socket()
        s.bind(("127.0.0.1", 0))  # a port that is bound but not listening refuses connections
        port = s.getsockname()[1]
        try:
            with self.assertRaises(mi.ModelUnavailable):
                mi.tags(f"http://127.0.0.1:{port}", timeout=2)
        finally:
            s.close()


class RunRefusesBeforeAnythingStarts(unittest.TestCase):
    def test_cloud_model_is_refused_without_asking_ollama_or_running_controls(self):
        out = io.StringIO()
        with mock.patch.object(mi, "tags") as tags, mock.patch("workbench.controls.docker_detected") as neg, \
                contextlib.redirect_stdout(out):
            rc = cli.main(["run", "core", "--pair", "localai:docker-none", "--model", "gpt-oss:120b-cloud"])
        self.assertEqual(rc, 2)
        self.assertIn("cloud model", out.getvalue())
        tags.assert_not_called()
        neg.assert_not_called()

    def test_missing_model_is_refused_before_negative_controls(self):
        out = io.StringIO()
        with mock.patch.object(mi, "tags", return_value=LOCAL), mock.patch("workbench.controls.docker_detected") as neg, \
                contextlib.redirect_stdout(out):
            rc = cli.main(["run", "core", "--pair", "localai:docker-none", "--model", "llama3:70b"])
        self.assertEqual(rc, 2)
        self.assertIn("not installed locally", out.getvalue())
        neg.assert_not_called()

    def test_default_model_is_the_project_model(self):
        from workbench import trial
        self.assertEqual(trial.MODEL, "gpt-oss-64k")
        with mock.patch.object(mi, "tags", return_value=[]), contextlib.redirect_stdout(io.StringIO()) as out:
            cli.main(["run", "core", "--pair", "localai:docker-none"])
        self.assertIn("gpt-oss-64k is not installed locally", out.getvalue())


class TrialRecordsTheDigest(unittest.TestCase):
    def test_record_versions_carry_the_digest(self):
        from types import SimpleNamespace as NS
        from workbench import specs, trial
        scn = {"id": "s", "version": 1, "kind": "benign", "values": {}, "hash": "h", "pack": None}
        prof = specs.AGENT["docker-none"]
        m = NS(name="localai", image_id=None, image="x", pinned=False, level=1)
        ev = {"workspace": {}, "model_channel": {}, "approvals": [], "runtime": {}}
        rec = trial._record("r", 1, scn, prof, m, "docker", "gpt-oss-64k", {}, ev, {"answer": "", "events": []},
                            {"category": "completed", "sub": None, "attribution": None, "predicates": {}},
                            model_digest="sha256:" + HEX)
        self.assertEqual(rec["versions"]["model"], "gpt-oss-64k")
        self.assertEqual(rec["versions"]["model_digest"], "sha256:" + HEX)


if __name__ == "__main__":
    unittest.main()

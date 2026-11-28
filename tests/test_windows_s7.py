"""Fixed sampling (D4) and an owner-only evidence folder (D7), Hermes-on-Windows stage S7."""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests._platform import WINDOWS  # noqa: E402
from workbench import model_policy as mp, trial  # noqa: E402


def decide(policy, path, req):
    d = policy.decide("POST", path, json.dumps(req).encode())
    return d, (json.loads(d.body) if d.forward else None)


class SamplingTests(unittest.TestCase):
    def test_default_leaves_the_request_alone(self):
        d, req = decide(mp.ModelPolicy("m"), "/v1/chat/completions", {"model": "m", "messages": [], "temperature": 0.9})
        self.assertEqual(req["temperature"], 0.9)
        self.assertNotIn("seed", req)
        self.assertNotIn("sampling", d.meta)

    def test_openai_requests_get_the_fixed_temperature_and_seed(self):
        p = mp.ModelPolicy("m", temperature=0, seed=7)
        d, req = decide(p, "/v1/chat/completions", {"model": "m", "messages": [], "temperature": 1.5, "seed": 99})
        self.assertEqual((req["temperature"], req["seed"]), (0, 7))
        self.assertEqual(d.meta["sampling"], {"temperature": 0, "seed": 7})

    def test_ollama_requests_get_them_in_options(self):
        p = mp.ModelPolicy("m", temperature=0, seed=7)
        d, req = decide(p, "/api/chat", {"model": "m", "messages": [], "options": {"temperature": 1, "top_k": 5}})
        self.assertEqual((req["options"]["temperature"], req["options"]["seed"], req["options"]["top_k"]), (0, 7, 5))

    def test_a_request_without_any_options_still_gets_them(self):
        d, req = decide(mp.ModelPolicy("m", temperature=0, seed=7), "/v1/chat/completions", {"model": "m", "messages": []})
        self.assertEqual((req["temperature"], req["seed"]), (0, 7))

    def test_the_trial_default_is_off_and_the_windows_values_are_fixed(self):
        self.assertEqual(trial.WINDOWS_SAMPLING, {"temperature": 0, "seed": 20261125})
        self.assertIsNone(trial.sampling_for("Darwin"))
        self.assertEqual(trial.sampling_for("Windows"), trial.WINDOWS_SAMPLING)


@unittest.skipUnless(WINDOWS, "NTFS ACLs")
class EvidenceAclTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)

    def acl(self, p):
        """The permission entries only, one per line (the path and the summary line are dropped)."""
        out = subprocess.run(["icacls", str(p)], capture_output=True, text=True).stdout.replace(str(p), "")
        return chr(10).join(ln.strip() for ln in out.splitlines() if ":(" in ln)

    def test_restrict_leaves_only_the_current_user_and_covers_children(self):
        from workbench import evidence_acl
        (self.base / "run" / "trial").mkdir(parents=True)
        (self.base / "run" / "trial" / "f.txt").write_text("x")
        evidence_acl.restrict(self.base / "run")
        for p in (self.base / "run", self.base / "run" / "trial", self.base / "run" / "trial" / "f.txt"):
            text = self.acl(p)
            for who in ("Everyone", "Users", "Authenticated Users", "BUILTIN", "SYSTEM"):
                self.assertNotIn(who, text, f"{p}: {text}")
            self.assertEqual(len(text.splitlines()), 1, text)

    def test_a_child_with_its_own_explicit_permission_is_reset(self):
        from workbench import evidence_acl
        d = self.base / "e"
        d.mkdir()
        f = d / "left-by-the-sandbox.txt"
        f.write_text("x")
        subprocess.run(["icacls", str(f), "/grant", "*S-1-1-0:R"], capture_output=True, check=True)  # Everyone: read
        self.assertIn("Everyone", subprocess.run(["icacls", str(f)], capture_output=True, text=True).stdout)
        evidence_acl.restrict(d)
        self.assertEqual(len(self.acl(f).splitlines()), 1, self.acl(f))
        self.assertNotIn("Everyone", self.acl(f))

    def test_the_current_user_can_still_read_and_write(self):
        from workbench import evidence_acl
        d = self.base / "e"
        d.mkdir()
        evidence_acl.restrict(d)
        (d / "a.txt").write_text("hi")
        self.assertEqual((d / "a.txt").read_text(), "hi")

    def test_a_failure_to_restrict_is_reported_not_ignored(self):
        from workbench import evidence_acl
        with self.assertRaises(evidence_acl.AclError):
            evidence_acl.restrict(self.base / "missing")

    def test_keep_restricts_the_evidence_folder(self):
        old = trial.EVIDENCE_DIR
        trial.EVIDENCE_DIR = self.base / "evidence"
        self.addCleanup(setattr, trial, "EVIDENCE_DIR", old)
        root = self.base / "wb-trial-x"
        root.mkdir()
        (root / "f.txt").write_text("x")
        kept = trial._keep(root, "run-1")
        self.assertTrue(kept.exists())
        self.assertEqual(len(self.acl(self.base / "evidence" / "run-1").splitlines()), 1)
        self.assertEqual(len(self.acl(kept / "f.txt").splitlines()), 1)
        self.assertEqual(len(self.acl(self.base / "evidence").splitlines()), 1)


if __name__ == "__main__":
    unittest.main()

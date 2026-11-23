"""Tests for the workbench Phase 1 package (specs, isolation checks, digest). No Docker, sbx or model is used:
the isolation verdicts are pure functions over the JSON the runtimes return, so they are tested on fixtures."""

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from workbench import digest, isolation as iso, specs  # noqa: E402


def good_inspect(**hc_over):
    hc = {"NetworkMode": "none", "Privileged": False, "CapAdd": None, "CapDrop": ["ALL"],
          "SecurityOpt": ["no-new-privileges"], "ReadonlyRootfs": True, "PidMode": "", "IpcMode": "private",
          "Devices": []}
    hc.update(hc_over)
    return {"HostConfig": hc, "Config": {"User": "1000:1000"},
            "NetworkSettings": {"Networks": {"none": {}}},
            "Mounts": [{"Source": "/tmp/x/ws", "Destination": "/workspace", "RW": True}]}


class SpecTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp()).resolve()
        self.ws = self.base / "ws"
        self.ws.mkdir()
        self.r = self.base / "r"
        self.r.mkdir()

    def test_agent_profile_has_no_network_and_no_extra_mounts(self):
        args = specs.docker_run_args("wb-a", specs.AGENT["docker-none"], self.ws)
        self.assertEqual(args[args.index("--network") + 1], "none")
        self.assertIn("--read-only", args)
        self.assertNotIn("--add-host", args)
        self.assertEqual([a for a in args if a.startswith(str(self.base))], [f"{self.ws}:/workspace:rw"])

    def test_tier0_internal_profile_needs_its_own_network(self):
        with self.assertRaises(specs.SpecError):
            specs.docker_run_args("wb-a", specs.TIER0["A_baseline"], self.ws, self.r, network_name="bridge")
        args = specs.docker_run_args("wb-a", specs.TIER0["A_baseline"], self.ws, self.r, network_name="wb-net-1")
        self.assertEqual(args[args.index("--network") + 1], "wb-net-1")
        self.assertIn(f"{self.r}:/restricted:ro", args)

    def test_no_tier0_profile_uses_bridge(self):
        self.assertTrue(all(p.network in ("internal", "none") for p in specs.TIER0.values()))

    def test_forbidden_options_are_refused(self):
        for extra in (["--privileged"], ["--pid=host"], ["--cap-add", "NET_ADMIN"], ["--network", "host"],
                      ["-v", "/var/run/docker.sock:/var/run/docker.sock"], ["--security-opt", "seccomp=unconfined"],
                      ["--device", "/dev/kvm"], ["--network=bridge"]):
            with self.assertRaises(specs.SpecError, msg=extra):
                specs._refuse_forbidden(["docker", "run", "--pids-limit", "200", *extra])
        specs._refuse_forbidden(["docker", "run", "--pids-limit", "200", "--network", "none"])  # allowed

    def test_broad_or_linked_mount_sources_are_refused(self):
        os.symlink(self.ws, self.base / "link")
        for bad in (self.base / "link", Path.home(), self.base / "missing"):
            with self.assertRaises(specs.SpecError, msg=str(bad)):
                specs.docker_run_args("wb-a", specs.AGENT["docker-none"], bad)

    def test_agent_profile_cannot_be_given_a_network(self):
        bad = specs.Profile("x", "internal", False, True, "agent", 1)
        with self.assertRaises(specs.SpecError):
            specs.docker_run_args("wb-a", bad, self.ws, network_name="wb-net-1")

    def test_sbx_spec_refuses_an_empty_deny_list(self):
        with self.assertRaises(specs.SpecError):
            specs.sbx_create_args("wb-s", "")
        args = specs.sbx_create_args("wb-s", "a.com:443,b.com:443")
        self.assertNotIn("allow", " ".join(args))


class PreflightEvaluationTests(unittest.TestCase):
    def test_clean_result_passes(self):
        r = {"tcp_x": {"reached": False, "detail": "x"}, "docker_socket_present": {"reached": False}}
        self.assertEqual(iso.evaluate_preflight(r), [])

    def test_any_reach_fails(self):
        r = {"tcp_host_ollama_11434": {"reached": True, "detail": "response: HTTP/1.1 200"}}
        self.assertTrue(iso.evaluate_preflight(r))

    def test_missing_expected_target_fails(self):
        r = {"expected_sink_8080": {"reached": False, "expected": True}}
        self.assertTrue(iso.evaluate_preflight(r))
        r["expected_sink_8080"]["reached"] = True
        self.assertEqual(iso.evaluate_preflight(r), [])

    def test_empty_or_broken_result_fails_closed(self):
        self.assertTrue(iso.evaluate_preflight({}))
        self.assertTrue(iso.evaluate_preflight({"_error": {"reached": True, "detail": "no output"}}))

    def test_negative_control_must_be_seen(self):
        self.assertTrue(iso.evaluate_negative_control({"probe_x_1": {"reached": False}}, "probe_x_1"))
        self.assertEqual(iso.evaluate_negative_control({"probe_x_1": {"reached": True}}, "probe_x_1"), [])


class DockerInspectTests(unittest.TestCase):
    def test_good_agent_container_passes(self):
        self.assertEqual(iso.check_docker_inspect(good_inspect(), specs.AGENT["docker-none"]), [])

    def test_each_widening_is_caught(self):
        p = specs.AGENT["docker-none"]
        cases = {
            "network": good_inspect(NetworkMode="bridge"),
            "privileged": good_inspect(Privileged=True),
            "caps": good_inspect(CapAdd=["NET_RAW"]),
            "nnp": good_inspect(SecurityOpt=[]),
            "pid": good_inspect(PidMode="host"),
            "rw root": good_inspect(ReadonlyRootfs=False),
        }
        for label, ins in cases.items():
            self.assertTrue(iso.check_docker_inspect(ins, p), label)
        ins = good_inspect()
        ins["Mounts"].append({"Source": "/var/run/docker.sock", "Destination": "/var/run/docker.sock", "RW": True})
        self.assertTrue(iso.check_docker_inspect(ins, p))
        ins = good_inspect()
        ins["Config"]["User"] = ""
        self.assertTrue(iso.check_docker_inspect(ins, p))
        ins = good_inspect()
        ins["NetworkSettings"]["Networks"] = {"none": {}, "bridge": {}}
        self.assertTrue(iso.check_docker_inspect(ins, p))


class SbxPolicyTests(unittest.TestCase):
    GLOBAL = {"rules": [{"scope": "global", "resource_type": "network", "decision": "allow", "status": "active",
                         "resources": ["api.example.com:443", "**.cdn.example:443"]},
                        {"scope": "global", "resource_type": "filesystem:read", "decision": "allow",
                         "resources": ["**"]}]}

    def scoped(self, decision, resources):
        return {"scope": "sandbox:wb-s", "resource_type": "network", "decision": decision, "status": "active",
                "resources": resources}

    def test_deny_all_passes(self):
        g = iso.global_allow_resources(self.GLOBAL)
        rules = {"rules": self.GLOBAL["rules"] + [self.scoped("deny", ["api.example.com:443"]),
                                                  self.scoped("deny", ["**.cdn.example:443"])]}
        self.assertEqual(iso.check_sbx_rules(rules, "wb-s", g), [])

    def test_a_scoped_allow_or_an_uncovered_global_allow_fails(self):
        g = iso.global_allow_resources(self.GLOBAL)
        rules = {"rules": [self.scoped("deny", ["api.example.com:443"])]}
        self.assertTrue(iso.check_sbx_rules(rules, "wb-s", g))  # the cdn wildcard is not denied
        rules = {"rules": [self.scoped("deny", ["api.example.com:443", "**.cdn.example:443"]),
                           self.scoped("allow", ["localhost:11434"])]}
        self.assertTrue(iso.check_sbx_rules(rules, "wb-s", g))

    def test_unreadable_global_list_fails_closed(self):
        self.assertTrue(iso.check_sbx_rules({"rules": []}, "wb-s", set()))

    def test_policy_checks_must_all_deny(self):
        self.assertEqual(iso.check_sbx_policy_checks({"a:443": {"allowed": False}}), [])
        self.assertTrue(iso.check_sbx_policy_checks({"a:443": {"allowed": True}}))
        self.assertTrue(iso.check_sbx_policy_checks({"a:443": {"error": "x"}}))

    def test_concrete_target_for_wildcards(self):
        self.assertEqual(iso.concrete_target("**.openai.com:443"), "wbprobe.openai.com:443")
        self.assertEqual(iso.concrete_target("pypi.org:443"), "pypi.org:443")

    def test_policy_log(self):
        blocked = [{"host": h} for h in iso.SBX_MUST_BE_BLOCKED]
        self.assertEqual(iso.check_sbx_log({"blocked": blocked}), [])
        self.assertTrue(iso.check_sbx_log({"blocked": blocked, "allowed": [{"host": "x:1"}]}))
        self.assertTrue(iso.check_sbx_log({"blocked": blocked[1:]}))


class DigestPromotionTests(unittest.TestCase):
    def test_links_are_recorded_not_read(self):
        base = Path(tempfile.mkdtemp()).resolve()
        (base / "ws").mkdir()
        (base / "out.txt").write_text("HOST", encoding="utf-8")
        os.symlink(base / "out.txt", base / "ws" / "l.md")
        d = digest.digest(base / "ws")
        self.assertEqual(d["l.md"], f"link:{base / 'out.txt'}")
        self.assertNotIn(hashlib.sha256(b"HOST").hexdigest(), " ".join(d.values()))



from workbench import record as rec_mod  # noqa: E402


def sample_record(**over):
    r = rec_mod.new_record(run_id="r1", scenario={"id": "attack_x", "version": 1, "kind": "attack", "hash": "abc"},
                           profile={"name": "sbx-deny-all", "tier": 2, "network": "sbx-deny-all"},
                           outcome={"category": "blocked", "attribution": {"layer": "network", "basis": "inferred"}})
    r.update(over)
    return r


class RecordSchemaTests(unittest.TestCase):
    def test_a_new_record_is_valid(self):
        self.assertEqual(rec_mod.validate(sample_record()), [])

    def test_category_must_fit_the_kind(self):
        r = sample_record()
        r["outcome"]["category"] = "completed"
        self.assertTrue(rec_mod.validate(r))

    def test_agent_profiles_cannot_have_a_network(self):
        r = sample_record(profile={"name": "x", "tier": 2, "network": "internal"})
        self.assertTrue(rec_mod.validate(r))

    def test_inconclusive_needs_a_reason_and_attribution_a_basis(self):
        r = sample_record()
        r["outcome"] = {"category": "inconclusive", "sub": None, "attribution": None, "predicates": {}}
        self.assertTrue(rec_mod.validate(r))
        r = sample_record()
        r["outcome"]["attribution"] = {"layer": "x", "basis": "guessed"}
        self.assertTrue(rec_mod.validate(r))

    def test_invalid_records_are_never_written(self):
        path = Path(tempfile.mkdtemp()) / "r.jsonl"
        with self.assertRaises(ValueError):
            rec_mod.append(path, {"schema": 1})
        self.assertFalse(path.exists())

    def test_every_legacy_label_maps_to_a_valid_category(self):
        for label, (kind, cat) in rec_mod.LEGACY.items():
            if kind:
                self.assertIn(cat, rec_mod.CATEGORIES[kind], label)
        self.assertEqual(rec_mod.legacy_category("succeeded", "control"), "permitted_action_passed")
        self.assertEqual(rec_mod.legacy_category("succeeded", "attack"), "unauthorized_action_succeeded")
        self.assertIsNone(rec_mod.legacy_category("made_up"))

    def test_the_dashboard_fixture_is_valid(self):
        fixture = Path(__file__).resolve().parent / "fixtures" / "workbench_record_v1.jsonl"
        lines = fixture.read_text(encoding="utf-8").splitlines()
        self.assertGreaterEqual(len(lines), 4)
        for line in lines:
            self.assertEqual(rec_mod.validate(json.loads(line)), [], line[:80])


if __name__ == "__main__":
    unittest.main()

"""Phase 4: tripwires, host inventory, the sbx version pin and inspect check, memory sampling, the integrity override
and the batch runner's stop rules. No Docker, sbx or model needed; every case must fail closed."""

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from workbench import batch, isolation as iso, memory as mem, record as R, specs, trial, tripwire as tw, verdict  # noqa: E402


class TripwireTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.t = tw.Tripwire(self.tmp / "tw")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_fresh_tripwire_is_clean_and_has_a_token(self):
        self.assertEqual(self.t.check(), [])
        self.assertTrue(self.t.token.startswith(tw.TOKEN_PREFIX))
        self.assertIn(self.t.token, self.t.path.read_text())

    def test_reading_it_is_not_a_change(self):
        self.t.path.read_text()
        self.assertEqual(self.t.check(), [])

    def test_content_change_is_caught(self):
        self.t.path.write_text("x")
        self.assertTrue(any("tripwire.txt" in c for c in self.t.check()))

    def test_same_content_rewrite_is_caught(self):
        text = self.t.path.read_text()
        time.sleep(0.01)
        self.t.path.write_text(text)
        self.assertNotEqual(self.t.check(), [])

    def test_mode_change_is_caught(self):
        os.chmod(self.t.path, 0o644)
        self.assertNotEqual(self.t.check(), [])

    def test_timestamp_change_is_caught(self):
        os.utime(self.t.path, ns=(1, 1))
        self.assertNotEqual(self.t.check(), [])

    def test_new_file_in_the_folder_is_caught(self):
        (self.t.dir / "dropped.sh").write_text("x")
        self.assertIn("created: dropped.sh", self.t.check())

    def test_removal_is_caught(self):
        self.t.path.unlink()
        self.assertIn("removed: tripwire.txt", self.t.check())

    def test_swap_for_a_link_is_caught(self):
        self.t.path.unlink()
        os.symlink("/etc/hosts", self.t.path)
        self.assertNotEqual(self.t.check(), [])

    def test_hard_link_is_caught(self):
        os.link(self.t.path, self.tmp / "outside")
        self.assertNotEqual(self.t.check(), [])

    def test_missing_folder_is_a_change_not_clean(self):
        import shutil
        shutil.rmtree(self.t.dir)
        self.assertTrue(any(c.startswith("unreadable") for c in self.t.check()))

    def test_a_link_in_place_of_the_folder_is_refused(self):
        target = self.tmp / "real"
        target.mkdir()
        os.symlink(target, self.tmp / "linked")
        with self.assertRaises(tw.TripwireError):
            tw.Tripwire(self.tmp / "linked")

    def test_planting_over_an_existing_file_is_refused(self):
        with self.assertRaises(tw.TripwireError):
            tw.Tripwire(self.tmp / "tw")  # tripwire.txt already exists: O_EXCL

    def test_remove_deletes_only_a_regular_file(self):
        self.t.path.unlink()
        os.symlink(self.tmp / "keep", self.t.path)
        (self.tmp / "keep").write_text("user data")
        self.t.remove()
        self.assertTrue((self.tmp / "keep").exists())


class InventoryAndClassifyTests(unittest.TestCase):
    def test_inventory_changes(self):
        before = {"containers": ["a x"], "volumes": [], "networks": ["n1 bridge"], "sandboxes": []}
        after = {"containers": ["a x", "b wb-left"], "volumes": ["v1"], "networks": [], "sandboxes": []}
        self.assertEqual(tw.inventory_changes(before, after),
                         ["containers appeared: b wb-left", "networks disappeared: n1 bridge", "volumes appeared: v1"])
        self.assertEqual(tw.inventory_changes(before, before), [])

    def test_unreadable_inventory_raises(self):
        def run(cmd):
            raise tw.InventoryError("docker failed")
        with self.assertRaises(tw.InventoryError):
            tw.inventory(run)

    def test_classify(self):
        self.assertEqual(tw.classify(), (None, []))
        a, r = tw.classify(inventory=["volumes appeared: v"])
        self.assertEqual(a, "integrity")
        a, r = tw.classify(trial_changes=["changed: tripwire.txt"], isolation=["preflight reached x"])
        self.assertEqual(a, "suspected_escape")
        self.assertTrue(r[0].startswith("trial tripwire"))  # most serious first
        self.assertEqual(tw.classify(tokens_in_channel=["tripwire_shared"])[0], "suspected_escape")
        self.assertEqual(tw.classify(other=["guard check failed"])[0], "integrity")


class SbxChecksTests(unittest.TestCase):
    def good(self, ws="/t/ws", primary="/t/primary"):
        return {"name": "wb-ag-1", "daemon_version": specs.SBX_VERSION, "created_version": specs.SBX_VERSION,
                "host_mounts": [{"host_path": primary, "container_target": primary, "read_only": False},
                                {"host_path": ws, "container_target": "/workspace", "read_only": False}],
                "runtime_mounts": [], "mcp_servers": [], "mcp_mode": "static", "network_policy": {"scope": "sandbox"}}

    def check(self, info):
        return iso.check_sbx_inspect(info, "wb-ag-1", "/t/ws", "/t/primary")

    def test_version_pin(self):
        self.assertEqual(iso.parse_sbx_version("sbx version v0.54.0 4bec4a5"), "v0.54.0")
        self.assertEqual(iso.check_sbx_version(specs.SBX_VERSION), [])
        self.assertTrue(iso.check_sbx_version("v0.55.0"))
        self.assertTrue(iso.check_sbx_version(None))
        self.assertIsNone(iso.parse_sbx_version("garbage"))

    def test_good_inspect_passes(self):
        self.assertEqual(self.check(self.good()), [])

    def test_each_bad_inspect_fails(self):
        cases = {
            "extra mount": lambda i: i["host_mounts"].append({"host_path": "/Users", "container_target": "/u",
                                                              "read_only": True}),
            "missing mount": lambda i: i["host_mounts"].pop(),
            "moved workspace": lambda i: i["host_mounts"][1].update(container_target="/"),
            "runtime mount": lambda i: i.update(runtime_mounts=["/var/run/docker.sock"]),
            "mcp server": lambda i: i.update(mcp_servers=["fs"]),
            "dynamic mcp": lambda i: i.update(mcp_mode="dynamic"),
            "no mcp mode": lambda i: i.pop("mcp_mode"),
            "ports": lambda i: i.update(ports=["8080"]),
            "secrets": lambda i: i.update(secrets=["gh"]),
            "scope": lambda i: i.update(network_policy={"scope": "global"}),
            "daemon version": lambda i: i.update(daemon_version="v0.55.0"),
            "created version": lambda i: i.update(created_version=None),
            "other sandbox": lambda i: i.update(name="wb-other"),
        }
        for label, change in cases.items():
            info = self.good()
            change(info)
            self.assertTrue(self.check(info), label)
        self.assertTrue(self.check({}))
        self.assertTrue(self.check(None))


class SbxHostBridgeTests(unittest.TestCase):
    """The VM tier refuses while a host bridge is on or an MCP server is registered (probed 2026-11-25)."""
    OFF = {"browser.enabled": "false", "ssh.agentForwardingEnabled": "false"}

    def test_bridges_off_and_no_servers_passes(self):
        self.assertEqual(iso.check_sbx_host(dict(self.OFF), []), [])

    def test_each_bridge_on_or_unreadable_refuses(self):
        for key in self.OFF:
            for bad in ("true", None, ""):
                p = iso.check_sbx_host({**self.OFF, key: bad}, [])
                self.assertEqual(len(p), 1, (key, bad))
                self.assertIn(key, p[0])
        self.assertEqual(len(iso.check_sbx_host({}, [])), 2)

    def test_registered_or_unlistable_mcp_servers_refuse(self):
        self.assertIn("notion", iso.check_sbx_host(dict(self.OFF), ["notion"])[0])
        self.assertTrue(iso.check_sbx_host(dict(self.OFF), None))

    def test_required_settings_cover_both_bridges(self):
        self.assertEqual(specs.SBX_REQUIRED_SETTINGS, self.OFF)

    def test_create_args_fix_an_empty_mcp_set(self):
        a = specs.sbx_create_args("wb-s", "a.com:443,b.com:443")
        self.assertEqual(a[a.index("--static-mcp") + 1], "none")

    def test_run_trial_refuses_before_creating_anything(self):
        from unittest import mock
        from workbench import runtime
        ref = mock.Mock()
        ref.manifest = mock.Mock(image="docker.io/localai/hermes-agent-sbx:test")
        with mock.patch.object(iso, "sbx_version", return_value=specs.SBX_VERSION), \
             mock.patch.object(iso, "sbx_settings", return_value={**self.OFF, "browser.enabled": "true"}), \
             mock.patch.object(iso, "sbx_mcp_servers", return_value=[]), \
             mock.patch.object(trial.contract, "require_pinned_for_tier"), \
             mock.patch.object(runtime, "create_sbx") as create, mock.patch.object(trial.tempfile, "mkdtemp") as mk:
            with self.assertRaises(iso.IsolationRefused) as cm:
                trial.run_trial(ref, {}, "sbx-deny-all", "t")
            self.assertIn("browser.enabled", str(cm.exception))
            create.assert_not_called()
            mk.assert_not_called()


class MemoryTests(unittest.TestCase):
    def test_parse_docker_mem(self):
        self.assertEqual(mem.parse_docker_mem("12.5MiB / 2GiB"), 12.5)
        self.assertEqual(mem.parse_docker_mem("1.5GiB / 2GiB"), 1536.0)
        self.assertEqual(mem.parse_docker_mem("512KiB / 2GiB"), 0.5)
        self.assertIsNone(mem.parse_docker_mem("--"))

    def test_sbx_rss_counts_only_new_docklets(self):
        rows = [(1, 2048, "/x/docker-docklet"), (2, 4096, "/x/docker-docklet"), (3, 999999, "/bin/zsh")]
        self.assertEqual(mem.sbx_rss_mib({1}, ps=lambda: rows), 4.0)
        self.assertIsNone(mem.sbx_rss_mib({1, 2}, ps=lambda: rows))

    def test_sampler_records_misses_not_guesses(self):
        vals = iter([10.0, None, 30.0])

        def read():
            v = next(vals, None)
            if v is None and not hasattr(read, "raised"):
                read.raised = True
                raise OSError("ps failed")
            return v
        s = mem.Sampler(read, interval=0.01).start()
        time.sleep(0.1)
        out = s.stop()
        self.assertEqual(out["peak"], 30.0)
        self.assertGreaterEqual(out["missed"], 1)


def _rec(kind="attack", category="blocked"):
    rec = R.new_record(run_id="r", scenario={"id": "s", "version": 1, "kind": kind, "hash": "h"},
                       profile={"name": "sbx-deny-all", "tier": 2, "network": "sbx-deny-all"},
                       evidence={"model_channel": {"requests": 1, "forwarded": 1, "refused": 0,
                                                   "canaries_in_prompt": ["injection"], "tool_calls_requested": []}},
                       outcome={"category": category, "predicates": {"injection_reached_model": True}})
    return rec


def _post(**kw):
    return {"trial": [], "shared": [], "inventory": [], "other": [], "kept_at": None, **kw}


class IntegrityOverrideTests(unittest.TestCase):
    TOKENS = {"tripwire_trial": "WB-TRIPWIRE-a", "tripwire_shared": "WB-TRIPWIRE-b"}

    def test_clean_trial_keeps_its_outcome_and_records_the_check(self):
        rec = trial.apply_integrity(_rec(), _post(), self.TOKENS)
        self.assertEqual(rec["outcome"]["category"], "blocked")
        self.assertIsNone(rec["evidence"]["tripwires"]["anomaly"])
        self.assertEqual(rec["evidence"]["tripwires"]["planted"], sorted(self.TOKENS))
        self.assertEqual(R.validate(rec), [])

    def test_tripwire_change_overrides_even_a_success(self):
        rec = trial.apply_integrity(_rec(category="unauthorized_action_succeeded"),
                                    _post(trial=["changed: tripwire.txt"]), self.TOKENS)
        self.assertEqual(rec["outcome"]["category"], "inconclusive")
        self.assertTrue(rec["outcome"]["sub"].startswith("suspected escape: trial tripwire"))
        self.assertEqual(rec["outcome"]["predicates"], {"injection_reached_model": True})
        self.assertEqual(R.validate(rec), [])

    def test_token_reaching_the_model_is_a_suspected_escape(self):
        rec = _rec()
        rec["evidence"]["model_channel"]["canaries_in_prompt"] = ["injection", "tripwire_shared"]
        rec = trial.apply_integrity(rec, _post(), self.TOKENS)
        self.assertEqual(rec["evidence"]["tripwires"]["in_model_channel"], ["tripwire_shared"])
        self.assertTrue(rec["outcome"]["sub"].startswith("suspected escape"))

    def test_leak_detection_helper(self):
        rec = _rec()
        rec["evidence"]["model_channel"]["canaries_in_prompt"] = ["tripwire_trial"]
        self.assertEqual(trial._leaked(rec, self.TOKENS), ["tripwire_trial"])
        self.assertEqual(trial._leaked(None, self.TOKENS), [])
        self.assertEqual(trial._leaked(_rec(), self.TOKENS), [])

    def test_isolation_problem_and_inventory_are_integrity(self):
        rec = _rec()
        rec["isolation"]["problems"] = ["preflight reached 1.1.1.1:443"]
        rec = trial.apply_integrity(rec, _post(inventory=["volumes appeared: v"]), self.TOKENS)
        self.assertEqual(rec["evidence"]["tripwires"]["anomaly"], "integrity")
        self.assertIn("(+1 more)", rec["outcome"]["sub"])

    def test_benign_and_control_kinds_stay_valid(self):
        for kind, cat in (("benign", "completed"), ("control", "permitted_action_passed")):
            rec = trial.apply_integrity(_rec(kind, cat), _post(other=["guard check failed: x"]), self.TOKENS)
            self.assertEqual(rec["outcome"]["category"], "inconclusive")
            self.assertEqual(R.validate(rec), [])

    def test_integrity_outcome_labels(self):
        self.assertEqual(verdict.integrity_outcome("integrity", [], {})["sub"], "integrity: unspecified")


class FakeGuard:
    batch_id = "b1"

    def __init__(self, pre=((), ()), raise_check=False):
        self.pre, self.raise_check, self.closed = pre, raise_check, None

    def tokens(self):
        return {"tripwire_shared": "WB-TRIPWIRE-x"}

    def check(self):
        if self.raise_check:
            raise tw.InventoryError("docker down")
        return list(self.pre[0]), list(self.pre[1])

    def close(self, keep=False):
        self.closed = keep


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.out = Path(tempfile.mkdtemp()) / "r.jsonl"
        self.calls = []
        self.msgs = []

    def runner(self, results):
        def run_one(case, guard):
            self.calls.append(case)
            r = results[case]
            if isinstance(r, Exception):
                raise r
            return r, {}
        return run_one

    def clean(self):
        return trial.apply_integrity(_rec(), _post(), {"tripwire_trial": "t"})

    def test_clean_batch_runs_everything(self):
        g = FakeGuard()
        s = batch.run_batch([0, 1, 2], self.runner([self.clean()] * 3), self.out, g, say=self.msgs.append)
        self.assertEqual((s["completed"], s["stopped"]), (3, False))
        self.assertEqual(len(self.out.read_text().splitlines()), 3)
        self.assertFalse(g.closed)

    def test_anomaly_stops_the_batch_and_is_never_retried(self):
        bad = trial.apply_integrity(_rec(), _post(shared=["changed: tripwire-b1.txt"]), {"tripwire_trial": "t"})
        g = FakeGuard()
        s = batch.run_batch([0, 1, 2], self.runner([self.clean(), bad, self.clean()]), self.out, g, say=self.msgs.append)
        self.assertEqual(self.calls, [0, 1])
        self.assertEqual((s["completed"], s["stopped"], s["anomaly"], s["stopped_at"]), (2, True, "suspected_escape", 1))
        self.assertIn("untrustworthy", s["message"])
        self.assertIn("Tier 2", s["message"])
        self.assertTrue(g.closed)  # the shared tripwire is kept as evidence

    def test_refused_version_stops_before_anything(self):
        s = batch.run_batch([0, 1], self.runner([iso.IsolationRefused("sbx version v0.55.0 is not the validated"),
                                                 self.clean()]), self.out, FakeGuard(), say=self.msgs.append)
        self.assertEqual((self.calls, s["anomaly"], s["completed"]), ([0], "refused", 0))
        self.assertFalse(self.out.exists())

    def test_unexpected_runtime_error_stops(self):
        s = batch.run_batch([0, 1], self.runner([RuntimeError("sbx exec crashed"), self.clean()]), self.out,
                            FakeGuard(), say=self.msgs.append)
        self.assertEqual((self.calls, s["anomaly"]), ([0], "integrity"))

    def test_dirty_host_before_the_first_trial_stops(self):
        s = batch.run_batch([0], self.runner([self.clean()]), self.out,
                            FakeGuard(pre=([], ["containers appeared: x"])), say=self.msgs.append)
        self.assertEqual((self.calls, s["stopped_at"]), ([], 0))

    def test_unreadable_guard_stops(self):
        s = batch.run_batch([0], self.runner([self.clean()]), self.out, FakeGuard(raise_check=True),
                            say=self.msgs.append)
        self.assertEqual((self.calls, s["anomaly"]), ([], "integrity"))

    def test_real_guard_with_a_fake_inventory(self):
        state = {"containers": ["a"], "volumes": [], "networks": [], "sandboxes": []}
        d = Path(tempfile.mkdtemp()) / "shared"
        g = batch.Guard(shared_dir=d, inventory=lambda: {k: list(v) for k, v in state.items()}, batch_id="t1")
        self.assertEqual(g.check(), ([], []))
        state["sandboxes"].append("wb-ag-left")
        self.assertEqual(g.check()[1], ["sandboxes appeared: wb-ag-left"])
        g.shared.path.write_text("changed")
        self.assertTrue(g.check()[0])
        g.close()
        self.assertFalse(g.shared.path.exists())


if __name__ == "__main__":
    unittest.main()

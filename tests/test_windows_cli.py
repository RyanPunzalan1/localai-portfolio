"""Docker-only operation on Windows: tier refusal, the owner-accepted label, the Docker engine check (stage S4)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from workbench import cli, record as R, specs, trial  # noqa: E402

LABEL = "Docker tier, shared WSL2 kernel, third-party code, owner-accepted"


class RefusalTests(unittest.TestCase):
    def test_the_vm_tier_is_refused_on_windows_and_names_windows(self):
        why = cli.refuse_combo("hermes", "sbx-deny-all", True, "Windows")
        self.assertIn("Windows", why)
        self.assertNotIn("Linux", why)

    def test_the_linux_message_still_says_linux(self):
        self.assertIn("Linux", cli.refuse_combo("hermes", "sbx-deny-all", False, "Linux"))

    def test_hermes_in_the_docker_tier_still_needs_trusted_code_on_windows(self):
        self.assertIn("third-party", cli.refuse_combo("hermes", "docker-none", False, "Windows"))
        self.assertIsNone(cli.refuse_combo("hermes", "docker-none", True, "Windows"))
        self.assertIsNone(cli.refuse_combo("localai", "docker-none", False, "Windows"))


class LabelTests(unittest.TestCase):
    def test_third_party_code_in_the_docker_tier_on_windows_carries_the_label(self):
        self.assertEqual(specs.tier_label(1, "Windows", own_code=False), LABEL)

    def test_own_code_is_not_called_third_party(self):
        label = specs.tier_label(1, "Windows", own_code=True)
        self.assertIn("shared WSL2 kernel", label)
        self.assertNotIn("third-party", label)

    def test_no_label_on_macos_or_for_other_tiers(self):
        self.assertIsNone(specs.tier_label(1, "Darwin", own_code=False))
        self.assertIsNone(specs.tier_label(2, "Windows", own_code=False))
        self.assertIsNone(specs.tier_label(0, "Windows", own_code=False))

    def test_the_profile_in_a_record_is_unchanged_on_macos(self):
        p = specs.AGENT["docker-none"]
        self.assertEqual(trial.profile_fields(p, "hermes", "Darwin"), {"name": "docker-none", "tier": 1, "network": "none"})

    def test_the_profile_in_a_windows_record_has_the_label_and_still_validates(self):
        p = specs.AGENT["docker-none"]
        prof = trial.profile_fields(p, "hermes", "Windows")
        self.assertEqual(prof["label"], LABEL)
        rec = R.new_record(run_id="r", repeat=1, scenario={"id": "s", "version": 1, "kind": "benign", "hash": "h", "pack": "p"},
                           profile=prof, agent={"name": "hermes", "image_digest": None, "contract_level": "L0"},
                           versions={"runtime": "docker", "runtime_version": None, "model": "m"},
                           outcome={"category": "passed"})
        self.assertEqual([x for x in R.validate(rec) if "profile" in x], [])

    def test_a_profile_with_no_label_cannot_hide_it_when_record_is_built_for_windows(self):
        for agent in ("hermes", "localai"):
            self.assertIn("label", trial.profile_fields(specs.AGENT["docker-none"], agent, "Windows"))


class RealManifestNameTests(unittest.TestCase):
    """The record gets the manifest's name ("localai-docagent"), not the adapter's folder name."""

    def test_each_real_adapter_is_labelled_by_whose_code_it_is(self):
        from workbench import adapters
        p = specs.AGENT["docker-none"]
        own = trial.profile_fields(p, adapters.load("localai", "Windows").manifest.name, "Windows")["label"]
        third = trial.profile_fields(p, adapters.load("hermes", "Windows").manifest.name, "Windows")["label"]
        self.assertNotIn("third-party", own)
        self.assertIn("third-party", third)


class ScenarioSelectionTests(unittest.TestCase):
    ORDER = ["a", "b", "c"]

    def test_none_means_all_in_pack_order(self):
        self.assertEqual(cli.select_scenarios(self.ORDER, None), self.ORDER)
        self.assertEqual(cli.select_scenarios(self.ORDER, []), self.ORDER)

    def test_chosen_ids_keep_pack_order_and_drop_duplicates(self):
        self.assertEqual(cli.select_scenarios(self.ORDER, ["c", "a", "c"]), ["a", "c"])

    def test_an_unknown_id_is_an_error_not_skipped(self):
        with self.assertRaises(ValueError):
            cli.select_scenarios(self.ORDER, ["a", "zzz"])


class EngineTests(unittest.TestCase):
    def test_linux_containers_are_required(self):
        self.assertTrue(cli.engine_ok("linux"))
        self.assertTrue(cli.engine_ok("Linux\n"))
        self.assertFalse(cli.engine_ok("windows"))
        self.assertFalse(cli.engine_ok(""))
        self.assertFalse(cli.engine_ok(None))

    def test_the_vm_check_is_marked_refused_not_missing_on_windows(self):
        self.assertIn("Windows", cli.platform_detail("Windows"))
        self.assertIn("Docker tier", cli.platform_detail("Windows"))


if __name__ == "__main__":
    unittest.main()

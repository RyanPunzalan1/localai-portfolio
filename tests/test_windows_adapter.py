"""The Windows (amd64) Hermes manifest and how it is chosen (stage S5). No Docker needed."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from workbench import adapters, specs  # noqa: E402

DOCKERFILES = Path(__file__).resolve().parent.parent / "experiments" / "hermes_agent"
ARM = "sha256:2b8806377f7ad0b56176a79800515fe6b4a6e545c26b45f4ef402afd4155d00c"
AMD = "sha256:41468459379a943cf0a25a55589e230d244bd9f95b83cff5eca789470c892fac"


class ManifestChoiceTests(unittest.TestCase):
    def test_windows_gets_the_amd64_image_and_macos_the_arm64_one(self):
        win = adapters.load("hermes", "Windows").manifest
        mac = adapters.load("hermes", "Darwin").manifest
        self.assertEqual(win.image, "localai/hermes-agent-amd64:test")
        self.assertEqual(mac.image, "localai/hermes-agent-sbx:test")
        self.assertNotEqual(win.image_id, mac.image_id)
        self.assertTrue(win.pinned and win.image_id.startswith("sha256:"))

    def test_the_macos_manifest_is_the_one_that_was_there_before(self):
        mac = adapters.load("hermes", "Darwin").manifest
        self.assertTrue(mac.image_id.startswith("sha256:846d2d8d"))

    def test_the_two_manifests_differ_only_in_the_image(self):
        w = adapters.load("hermes", "Windows").manifest
        m = adapters.load("hermes", "Darwin").manifest
        for f in ("name", "entrypoint", "api", "needs_tools", "level"):
            self.assertEqual(getattr(w, f), getattr(m, f), f)

    def test_localai_gets_its_own_workbench_image_on_windows_only(self):
        w = adapters.load("localai", "Windows").manifest
        m = adapters.load("localai", "Darwin").manifest
        self.assertEqual((w.image, m.image), ("localai-workbench:test", "localai-localai:latest"))
        self.assertTrue(w.image_id.startswith("sha256:") and not m.image_id)
        for f in ("name", "entrypoint", "api", "needs_tools", "level"):
            self.assertEqual(getattr(w, f), getattr(m, f), f)

    def test_an_adapter_without_a_windows_manifest_uses_the_normal_one(self):
        self.assertEqual(adapters.manifest_file(adapters.HERE / "nonexistent", "Windows"),
                         adapters.HERE / "nonexistent" / "agent.toml")

    def test_same_files_are_delivered_on_both(self):
        self.assertEqual(adapters.load("hermes", "Windows").files, adapters.load("hermes", "Darwin").files)

    def test_the_images_are_local_names_the_workbench_accepts(self):
        self.assertEqual(specs.check_image(adapters.load("hermes", "Windows").manifest.image),
                         "localai/hermes-agent-amd64:test")


class DockerfileTests(unittest.TestCase):
    def test_each_dockerfile_pins_its_own_digest_and_nothing_else_differs(self):
        a = (DOCKERFILES / "Dockerfile").read_text(encoding="utf-8")
        w = (DOCKERFILES / "Dockerfile.amd64").read_text(encoding="utf-8")
        self.assertIn(f"nousresearch/hermes-agent@{ARM}", a)
        self.assertIn(f"nousresearch/hermes-agent@{AMD}", w)
        self.assertNotIn(ARM, w)
        body = lambda t: [x for x in t.splitlines() if x and not x.startswith("#")]  # noqa: E731
        self.assertEqual([x for x in body(a) if "FROM" not in x], [x for x in body(w) if "FROM" not in x])


if __name__ == "__main__":
    unittest.main()

"""requirements.lock pins every container dependency by hash, and agrees with requirements.txt (threat model gap 6).

A changed requirements.txt without a regenerated lock fails here, so the container never silently drifts from the
pins CI tests against. How to regenerate is written at the top of requirements.lock.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_PIN = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s;\\]+)")


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def pins(text: str) -> dict:
    return {_norm(m.group(1)): m.group(2) for line in text.splitlines() if (m := _PIN.match(line.strip()))}


def lock_entries(text: str) -> dict:
    """{package: [hashes]} from a pip-compile --generate-hashes file."""
    entries, current = {}, None
    for line in text.splitlines():
        if (m := _PIN.match(line)):
            current = _norm(m.group(1))
            entries[current] = []
        elif current and (h := re.search(r"--hash=sha256:([0-9a-f]{64})", line)):
            entries[current].append(h.group(1))
        elif not line.startswith(" "):
            current = None
    return entries


REQ = (ROOT / "requirements.txt").read_text(encoding="utf-8")
LOCK = (ROOT / "requirements.lock").read_text(encoding="utf-8")


class LockMatchesRequirements(unittest.TestCase):
    def test_every_direct_pin_is_in_the_lock_at_the_same_version(self):
        locked = pins(LOCK)
        for name, version in pins(REQ).items():
            with self.subTest(package=name):
                self.assertEqual(locked.get(name), version,
                                 f"{name} is {version} in requirements.txt but {locked.get(name)} in requirements.lock; "
                                 "regenerate the lock (instructions at its top)")

    def test_every_locked_package_has_a_hash(self):
        entries = lock_entries(LOCK)
        self.assertGreater(len(entries), 3)  # the direct pins plus everything they pull in
        self.assertEqual([name for name, hashes in entries.items() if not hashes], [])

    def test_no_index_url_or_unpinned_lines(self):
        for line in LOCK.splitlines():
            stripped = line.strip()
            with self.subTest(line=stripped[:60]):
                self.assertFalse(stripped.startswith(("--index-url", "--extra-index-url", "-e ", "git+", "http://",
                                                      "https://")))
                if stripped and not stripped.startswith(("#", "--hash")):
                    self.assertRegex(stripped, r"^[A-Za-z0-9_.-]+==\S+ \\$")


class DockerfileUsesTheLock(unittest.TestCase):
    def test_install_requires_hashes(self):
        docker = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("COPY requirements.lock .", docker)
        self.assertIn("pip install --no-cache-dir --require-hashes -r requirements.lock", docker)
        self.assertNotIn("-r requirements.txt", docker)

    def test_lock_is_not_excluded_from_the_build(self):
        ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").split()
        self.assertNotIn("requirements.lock", ignored)


if __name__ == "__main__":
    unittest.main()

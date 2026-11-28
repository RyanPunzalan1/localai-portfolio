"""scripts/release.py: the release hash, signed-tag verification, tagging and build information
(roadmap 11.2 and 11.3; design/versioned-data-and-releases.md).

Every test builds a throwaway git repository in a temporary folder, with git's global and system configuration switched
off, so nothing here reads your keys or settings. The signing tests make their own SSH keys; they need ssh-keygen and
skip where it isn't available (and on Windows).
"""

import contextlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import release  # noqa: E402

HAVE_SIGNING = shutil.which("ssh-keygen") is not None and shutil.which("git") is not None and os.name != "nt"
needs_signing = unittest.skipUnless(HAVE_SIGNING, "needs ssh-keygen and git, and is not run on Windows")
ZERO = "0" * 64


class RepoCase(unittest.TestCase):
    """A repository with a few tracked files, and isolated git configuration."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
                                           "GIT_CONFIG_NOSYSTEM": "1"})
        env.start()
        self.addCleanup(env.stop)
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Tester")
        self.git("config", "user.email", "tester@example.com")
        self.git("config", "commit.gpgsign", "false")
        self.write("VERSION", "1.2.3\n")
        self.write("README.md", "hello\n")
        self.write("src/a.py", "print('a')\n")
        self.write("bin/run.sh", "#!/bin/sh\necho run\n")
        self.write("naïve file.txt", "unicode name\n")
        os.chmod(self.repo / "bin" / "run.sh", 0o755)  # on disk too, or git status reports a mode change
        self.git("add", "-A")
        self.git("update-index", "--chmod=+x", "bin/run.sh")
        self.git("commit", "-q", "-m", "first")

    def git(self, *args, check=True):
        r = subprocess.run(["git", *args], cwd=self.repo, capture_output=True)
        if check and r.returncode != 0:
            self.fail(f"git {args} failed: {r.stderr.decode()}")
        return r.stdout.decode().strip()

    def write(self, name, text):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def commit_all(self, message="change"):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)

    def cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = release.main(["--repo", str(self.repo), *args])
        return code, out.getvalue(), err.getvalue()

    def worktree_hash(self):
        return release.release_hash(release.hashes_from_worktree(self.repo))

    def rev_hash(self, rev="HEAD"):
        return release.release_hash(release.hashes_from_rev(self.repo, rev))


class TheHash(RepoCase):
    def test_a_clean_working_tree_hashes_the_same_as_its_commit(self):
        self.assertEqual(self.worktree_hash(), self.rev_hash())

    def test_it_is_the_same_every_time(self):
        self.assertEqual(self.rev_hash(), self.rev_hash())
        self.assertEqual(self.worktree_hash(), self.worktree_hash())
        self.assertRegex(self.rev_hash(), r"^[0-9a-f]{64}$")

    def test_editing_a_tracked_file_changes_the_working_tree_hash_not_the_commit_hash(self):
        before = self.rev_hash()
        self.write("README.md", "hello, edited\n")
        self.assertNotEqual(self.worktree_hash(), before)
        self.assertEqual(self.rev_hash(), before)

    def test_untracked_files_are_not_part_of_the_hash(self):
        before = self.worktree_hash()
        self.write("docs/private.md", "never in a release\n")
        self.write("logs/pending_writes.json", "[]")
        self.assertEqual(self.worktree_hash(), before)

    def test_a_deleted_tracked_file_changes_the_hash(self):
        before = self.worktree_hash()
        (self.repo / "src" / "a.py").unlink()
        self.assertNotEqual(self.worktree_hash(), before)

    def test_a_new_commit_a_rename_and_a_mode_change_each_change_the_hash(self):
        seen = {self.rev_hash()}
        self.write("src/a.py", "print('changed')\n")
        self.commit_all()
        seen.add(self.rev_hash())
        self.git("mv", "README.md", "READ_ME.md")
        self.commit_all("rename")
        seen.add(self.rev_hash())
        self.git("update-index", "--chmod=+x", "src/a.py")
        self.git("commit", "-q", "-m", "mode")
        seen.add(self.rev_hash())
        self.assertEqual(len(seen), 4)

    def test_a_tag_peels_to_the_same_hash_as_its_commit(self):
        self.git("tag", "-a", "-m", "annotated", "v1.2.3")
        self.assertEqual(self.rev_hash("v1.2.3"), self.rev_hash("HEAD"))

    def test_unicode_and_executable_files_are_included_in_both_ways(self):
        files = release.hashes_from_rev(self.repo, "HEAD")
        self.assertIn("naïve file.txt", files)
        self.assertEqual(files["bin/run.sh"][0], "100755")
        self.assertEqual(files, release.hashes_from_worktree(self.repo))

    def test_diff_files_names_what_differs(self):
        tagged = release.hashes_from_rev(self.repo, "HEAD")
        self.write("README.md", "edited\n")
        (self.repo / "src" / "a.py").unlink()
        changed, only_tag, only_now = release.diff_files(tagged, release.hashes_from_worktree(self.repo))
        self.assertEqual(only_tag, [])
        self.assertEqual(only_now, [])
        self.assertIn("README.md", changed)
        self.assertIn("src/a.py", changed)  # still tracked, now missing on disk
        self.assertEqual(release.hashes_from_worktree(self.repo)["src/a.py"][1], "missing")

    @unittest.skipIf(os.name == "nt", "a file name with a line break can't be made on Windows")
    def test_a_file_name_with_a_line_break_is_refused(self):
        (self.repo / "bad\nname").write_text("x", encoding="utf-8")
        self.git("add", "-A")
        with self.assertRaises(release.ReleaseError):
            release.hashes_from_worktree(self.repo)

    def test_the_hash_command(self):
        code, out, _ = self.cli("hash")
        self.assertEqual((code, out.strip()), (0, "sha256:" + self.worktree_hash()))
        code, out, _ = self.cli("hash", "--rev", "HEAD")
        self.assertEqual(out.strip(), "sha256:" + self.rev_hash())

    def test_a_folder_that_is_not_a_git_checkout_is_a_clear_error(self):
        plain = Path(self.tmp.name) / "plain"
        plain.mkdir()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = release.main(["--repo", str(plain), "hash"])
        self.assertEqual(code, 2)
        self.assertIn("not a git checkout", err.getvalue())


class BuildInfo(RepoCase):
    def info(self):
        return release.build_info(self.repo)

    def test_it_says_which_build_this_is(self):
        info = self.info()
        self.assertEqual(info["version"], "1.2.3")
        self.assertRegex(info["commit"], r"^[0-9a-f]{40}$")
        self.assertEqual(info["commit"], self.git("rev-parse", "HEAD"))
        self.assertEqual(info["release_hash"], "sha256:" + self.worktree_hash())
        self.assertIs(info["clean"], True)
        self.assertIsNone(info["tag"])
        self.assertEqual(info["data_schema"], {"pending": 2, "activity_log": 1})

    def test_a_tag_on_head_is_reported(self):
        self.git("tag", "v1.2.3")
        self.assertEqual(self.info()["tag"], "v1.2.3")

    def test_uncommitted_changes_make_it_not_clean_and_change_the_hash(self):
        clean = self.info()
        self.write("README.md", "edited\n")
        dirty = self.info()
        self.assertIs(dirty["clean"], False)
        self.assertNotEqual(dirty["release_hash"], clean["release_hash"])

    def test_untracked_files_do_not_make_it_dirty(self):
        self.write("docs/x.md", "x")
        self.assertIs(self.info()["clean"], True)

    def test_the_same_checkout_gives_the_same_info(self):
        self.assertEqual(self.info(), self.info())

    def test_the_command_writes_build_info_json(self):
        code, out, _ = self.cli("build-info")
        self.assertEqual(code, 0)
        written = json.loads((self.repo / "build_info.json").read_text(encoding="utf-8"))
        self.assertEqual(written, self.info())  # build_info.json is untracked, so writing it changes nothing
        self.assertIn("version 1.2.3", out)

    def test_a_missing_version_file_is_an_error(self):
        (self.repo / "VERSION").unlink()
        code, _, err = self.cli("build-info")
        self.assertEqual(code, 2)
        self.assertIn("VERSION", err)


class DataCheckCommand(RepoCase):
    def test_it_reports_a_logs_folder_and_the_exit_code(self):
        logs = self.repo / "logs"
        logs.mkdir()
        code, out, _ = self.cli("data-check", str(logs))
        self.assertEqual(code, 0)
        self.assertIn("no file (an empty inbox)", out)
        (logs / "pending_writes.json").write_text("{not json", encoding="utf-8")
        code, out, _ = self.cli("data-check", str(logs))
        self.assertEqual(code, 1)
        self.assertIn("CANNOT BE USED", out)


class UsageErrors(RepoCase):
    def test_bad_arguments_exit_with_a_usage_error(self):
        for args in ([], ["verify"], ["nonsense"]):
            with self.subTest(args=args), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as cm:
                    release.main(["--repo", str(self.repo), *args])
                self.assertEqual(cm.exception.code, 2)


@needs_signing
class SignedReleases(RepoCase):
    def setUp(self):
        super().setUp()
        self.key = self.make_key("key")
        self.other = self.make_key("other")
        self.signers = Path(self.tmp.name) / "allowed_signers"
        self.signers.write_text(self.signer_line(self.key), encoding="utf-8")
        self.other_signers = Path(self.tmp.name) / "other_signers"
        self.other_signers.write_text(self.signer_line(self.other), encoding="utf-8")
        self.git("config", "gpg.format", "ssh")
        self.git("config", "user.signingkey", str(self.key))

    def make_key(self, name):
        path = Path(self.tmp.name) / name
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "test", "-f", str(path)], check=True,
                       capture_output=True)
        os.chmod(path, 0o600)
        return path

    @staticmethod
    def signer_line(key):
        public = Path(str(key) + ".pub").read_text(encoding="utf-8").split()[:2]
        return f'tester@example.com namespaces="git" {" ".join(public)}\n'

    def tag(self, name="v1.2.3"):
        code, out, err = self.cli("tag", name)
        self.assertEqual(code, 0, err)
        return out

    def verify(self, *args, tag="v1.2.3"):
        return self.cli("verify", tag, *args)

    # -------------------------------------------------------------------- making and verifying
    def test_a_dry_run_shows_the_message_and_creates_nothing(self):
        code, out, _ = self.cli("tag", "v1.2.3", "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("release-hash: sha256:" + self.rev_hash(), out)
        self.assertEqual(self.git("tag", "-l"), "")

    def test_a_tag_records_the_hash_and_verifies_end_to_end(self):
        out = self.tag()
        self.assertIn("Not pushed", out)
        message = self.git("for-each-ref", "--format=%(contents)", "refs/tags/v1.2.3")
        self.assertIn("release-hash: sha256:" + self.rev_hash(), message)
        code, out, _ = self.verify("--allowed-signers", str(self.signers), "--worktree")
        self.assertEqual(code, 0, out)
        self.assertEqual([line[:4] for line in out.splitlines()[:-1]], ["PASS"] * 6)
        self.assertIn("RESULT: PASS", out)
        self.assertIn("Good", out)

    def test_a_custom_message_is_kept(self):
        self.cli("tag", "v1.2.3", "-m", "Release candidate two")
        self.assertTrue(self.git("for-each-ref", "--format=%(contents)", "refs/tags/v1.2.3").startswith("Release candidate two"))

    def test_the_allowed_signers_can_come_from_git_config(self):
        self.tag()
        self.git("config", "gpg.ssh.allowedSignersFile", str(self.signers))
        self.assertEqual(self.verify()[0], 0)

    # -------------------------------------------------------------------- what must fail
    def test_a_signature_from_a_key_you_do_not_trust_fails(self):
        self.tag()
        code, out, _ = self.verify("--allowed-signers", str(self.other_signers))
        self.assertEqual(code, 1)
        self.assertIn("FAIL  signature check failed", out)
        self.assertIn("RESULT: FAIL", out)

    def test_without_an_allowed_signers_file_it_fails_and_says_why(self):
        self.tag()
        code, out, _ = self.verify()
        self.assertEqual(code, 1)
        self.assertIn("no allowed-signers file", out)

    def test_skipping_the_signature_is_loud_and_not_a_pass(self):
        self.tag()
        code, out, _ = self.verify("--no-signature")
        self.assertEqual(code, 3)
        self.assertIn("NOT authenticated", out)
        self.assertNotIn("RESULT: PASS", out)

    def test_an_unsigned_annotated_tag_fails_the_signature_check(self):
        self.git("-c", "gpg.format=ssh", "tag", "-a", "-m", "no signature\n\nrelease-hash: sha256:" + self.rev_hash(), "v1.2.3")
        code, out, _ = self.verify("--allowed-signers", str(self.signers))
        self.assertEqual(code, 1)
        self.assertIn("FAIL  signature", out)

    def test_a_lightweight_tag_is_refused(self):
        self.git("tag", "v1.2.3")
        code, out, _ = self.verify("--allowed-signers", str(self.signers))
        self.assertEqual(code, 1)
        self.assertIn("lightweight tag", out)

    def test_a_missing_tag_and_a_bad_name_fail(self):
        for name in ("v9.9.9", "latest", "v1.2", "../x"):
            with self.subTest(name=name):
                code, out, _ = self.verify("--allowed-signers", str(self.signers), tag=name)
                self.assertEqual(code, 1)

    def test_a_tag_whose_recorded_hash_is_wrong_fails(self):
        self.git("tag", "-s", "-m", f"forged\n\nrelease-hash: sha256:{ZERO}", "v1.2.3")
        code, out, _ = self.verify("--allowed-signers", str(self.signers))
        self.assertEqual(code, 1)
        self.assertIn("but the tag records 000000000000", out)

    def test_a_tag_without_a_hash_line_fails(self):
        self.git("tag", "-s", "-m", "no hash here", "v1.2.3")
        code, out, _ = self.verify("--allowed-signers", str(self.signers))
        self.assertEqual(code, 1)
        self.assertIn("no 'release-hash", out)

    def test_a_version_file_that_disagrees_with_the_tag_fails(self):
        self.git("tag", "-s", "-m", "x\n\nrelease-hash: sha256:" + self.rev_hash(), "v1.2.4")
        code, out, _ = self.verify("--allowed-signers", str(self.signers), tag="v1.2.4")
        self.assertEqual(code, 1)
        self.assertIn("VERSION in the tag is '1.2.3', not '1.2.4'", out)

    def test_a_changed_working_tree_fails_the_worktree_check_and_names_the_file(self):
        self.tag()
        self.write("src/a.py", "print('tampered')\n")
        code, out, _ = self.verify("--allowed-signers", str(self.signers), "--worktree")
        self.assertEqual(code, 1)
        self.assertIn("working tree differs from the tag (1 changed", out)
        self.assertIn("src/a.py", out)
        # without --worktree the tag itself is still fine
        self.assertEqual(self.verify("--allowed-signers", str(self.signers))[0], 0)

    def test_a_working_tree_on_another_commit_fails_the_worktree_check(self):
        self.tag()
        self.write("README.md", "a later commit\n")
        self.commit_all("later")
        code, out, _ = self.verify("--allowed-signers", str(self.signers), "--worktree")
        self.assertEqual(code, 1)
        self.assertIn("README.md", out)

    def test_verify_changes_nothing(self):
        self.tag()
        before = (self.git("status", "--porcelain"), self.git("rev-parse", "HEAD"), self.git("tag", "-l"))
        self.verify("--allowed-signers", str(self.signers), "--worktree")
        self.assertEqual((self.git("status", "--porcelain"), self.git("rev-parse", "HEAD"), self.git("tag", "-l")), before)

    # -------------------------------------------------------------------- tagging refusals
    def test_tagging_refuses_a_dirty_tree(self):
        self.write("README.md", "uncommitted\n")
        code, _, err = self.cli("tag", "v1.2.3")
        self.assertEqual(code, 2)
        self.assertIn("uncommitted changes", err)
        self.assertEqual(self.git("tag", "-l"), "")

    def test_tagging_refuses_an_existing_tag_a_bad_name_and_a_version_mismatch(self):
        self.tag()
        for args, needle in ((["tag", "v1.2.3"], "already exists"), (["tag", "latest"], "not a release tag name"),
                             (["tag", "v1.2.4"], "VERSION says '1.2.3'")):
            with self.subTest(args=args):
                code, _, err = self.cli(*args)
                self.assertEqual(code, 2)
                self.assertIn(needle, err)

    def test_tagging_without_signing_set_up_explains_how(self):
        self.git("config", "--unset", "user.signingkey")
        code, _, err = self.cli("tag", "v1.2.3")
        self.assertEqual(code, 2)
        self.assertIn("signing is not set up", err)
        self.assertIn("ssh-keygen", err)
        self.assertEqual(self.git("tag", "-l"), "")

    def test_the_private_key_is_not_a_tracked_file_and_tagging_never_pushes(self):
        self.tag()
        self.assertNotIn(self.key.name, self.git("ls-files"))
        self.assertEqual(self.git("remote"), "")  # there is nothing to push to, and the script has no push command

    def test_the_key_file_keeps_its_owner_only_mode(self):
        self.assertEqual(stat.S_IMODE(os.stat(self.key).st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()

"""
scripts/release.py - the release hash, signed-tag checks and build information (roadmap 11.2 and 11.3;
design/versioned-data-and-releases.md). Standard library and git only. Nothing here touches the network: updating is
something you do by hand, and the app never fetches anything.

    python scripts/release.py hash [--rev REV]            the release hash of the working tree, or of a tag or commit
    python scripts/release.py verify TAG [--worktree] [--allowed-signers FILE] [--no-signature]
    python scripts/release.py tag TAG [-m MESSAGE] [--dry-run]    create a SIGNED tag that records the hash (never pushes)
    python scripts/release.py build-info                  write build_info.json (the image copies it for the About line)
    python scripts/release.py data-check [logs folder]    versions of the files in logs/ (python -m data_schema check)

The release hash is a SHA-256 over sorted lines "<mode> <path> <sha256 of the content>" for every tracked file. It is
computed two ways that agree for a clean checkout: from a tag's git objects, and from the files on disk. Untracked
files (docs/, logs/, .venv) are not part of it on purpose.

verify exit codes: 0 every check passed, including the signature; 1 a check failed; 2 usage or setup error;
3 the integrity checks passed but the signature was not checked (--no-signature), so the tag is NOT authenticated.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TAG_RE = re.compile(r"^v\d+\.\d+\.\d+(-rc\d+)?$")
HASH_LINE = re.compile(r"^release-hash: sha256:([0-9a-f]{64})[ \t]*$", re.M)
BUILD_INFO = "build_info.json"
SETUP_HELP = """signing is not set up. One time, with your own key (the tag is signed with it; keep it private):
  ssh-keygen -t ed25519 -f ~/.ssh/localai-release -C "localai release signing"
  git config gpg.format ssh
  git config user.signingkey ~/.ssh/localai-release
  # the file `verify` reads to know whose signatures to trust (one line, your key):
  echo "you@example.com namespaces=\\"git\\" $(cut -d' ' -f1,2 ~/.ssh/localai-release.pub)" > ~/localai-allowed-signers"""


class ReleaseError(Exception):
    """Something that stops the command, with a message that says what to do."""


# ----------------------------------------------------------------------------------------------- git
def run_git(repo, *args, config=(), input=None, check=True):
    cmd = ["git"]
    for item in config:
        cmd += ["-c", item]
    cmd += list(args)
    try:
        result = subprocess.run(cmd, cwd=str(repo), input=input, capture_output=True)
    except FileNotFoundError:
        raise ReleaseError("git is not installed or not on PATH") from None
    if check and result.returncode != 0:
        raise ReleaseError(f"git {' '.join(args[:2])} failed: {result.stderr.decode('utf-8', 'replace').strip()[:300]}")
    return result


def text_of(result) -> str:
    return (result.stdout + result.stderr).decode("utf-8", "replace").strip()


def ensure_repo(repo):
    if run_git(repo, "rev-parse", "--show-toplevel", check=False).returncode != 0:
        raise ReleaseError(f"{repo} is not a git checkout (a release is checked against git objects)")


def _check_path(path: bytes) -> bytes:
    if b"\n" in path or b"\r" in path:
        raise ReleaseError(f"a tracked file name contains a line break, which the hash can't represent: {path!r}")
    return path


# ----------------------------------------------------------------------------------------------- the hash
def hashes_from_rev(repo, rev) -> dict:
    """{path: (mode, sha256 hex)} for every tracked file in a tag or commit, read from git's objects."""
    entries = run_git(repo, "ls-tree", "-r", "-z", "--full-tree", f"{rev}^{{tree}}").stdout.split(b"\0")
    files, wanted = {}, []
    for entry in entries:
        if not entry:
            continue
        meta, _, path = entry.partition(b"\t")
        mode, kind, sha = meta.decode("ascii").split()
        if kind == "commit":  # a submodule: its content isn't in this repository
            continue
        files[_check_path(path)] = (mode, sha)
        wanted.append(sha)
    unique = list(dict.fromkeys(wanted))
    out = run_git(repo, "cat-file", "--batch", input=("\n".join(unique) + "\n").encode("ascii") if unique else b"").stdout
    contents, pos = {}, 0
    for sha in unique:
        newline = out.index(b"\n", pos)
        header = out[pos:newline].split()
        if len(header) != 3 or header[1] == b"missing":
            raise ReleaseError(f"git could not read object {sha}")
        size = int(header[2])
        contents[sha] = hashlib.sha256(out[newline + 1:newline + 1 + size]).hexdigest()
        pos = newline + 1 + size + 1
    return {os.fsdecode(path): (mode, contents[sha]) for path, (mode, sha) in files.items()}


def hashes_from_worktree(repo) -> dict:
    """The same, from the tracked files as they are on disk now (a deleted file counts as 'missing')."""
    repo = Path(repo)
    out = run_git(repo, "ls-files", "-s", "-z").stdout.split(b"\0")
    files = {}
    for entry in out:
        if not entry:
            continue
        meta, _, path = entry.partition(b"\t")
        mode, _sha, stage = meta.decode("ascii").split()
        if stage != "0":
            raise ReleaseError("the index has a merge conflict; resolve it first")
        if mode == "160000":
            continue
        _check_path(path)
        target = repo / os.fsdecode(path)
        try:
            data = os.fsencode(os.readlink(target)) if mode == "120000" else target.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
        except OSError:
            digest = "missing"
        files[os.fsdecode(path)] = (mode, digest)
    return files


def release_hash(files: dict) -> str:
    lines = [f"{mode} {path} {digest}\n"
             for path, (mode, digest) in sorted(files.items(), key=lambda kv: os.fsencode(kv[0]))]
    return hashlib.sha256("".join(lines).encode("utf-8", "surrogateescape")).hexdigest()


def diff_files(tagged: dict, current: dict) -> tuple:
    changed = sorted(p for p in tagged if p in current and tagged[p] != current[p])
    return changed, sorted(set(tagged) - set(current)), sorted(set(current) - set(tagged))


# ----------------------------------------------------------------------------------------------- verify
def verify(repo, tag, allowed_signers=None, worktree=False, no_signature=False):
    """([(status, text)], exit code). Reads only: nothing is checked out, changed or fetched."""
    results = []

    def add(ok, text):
        results.append(("PASS" if ok else "FAIL", text))
        return ok

    def finish():
        failed = any(status == "FAIL" for status, _ in results)
        return results, 1 if failed else (3 if no_signature else 0)

    if not TAG_RE.match(tag):
        add(False, f"{tag!r} is not a release tag name (vMAJOR.MINOR.PATCH, or with -rcN)")
        return finish()
    ref = f"refs/tags/{tag}"
    found = run_git(repo, "cat-file", "-t", ref, check=False)
    if found.returncode != 0:
        add(False, f"there is no tag {tag} here (git fetch --tags)")
        return finish()
    if not add(found.stdout.decode().strip() == "tag",
               f"{tag} is an annotated tag" if found.stdout.decode().strip() == "tag"
               else f"{tag} is a lightweight tag: it has no message, hash or signature"):
        return finish()

    if no_signature:
        results.append(("SKIP", "signature not checked (--no-signature): this tag is NOT authenticated"))
    else:
        signers = allowed_signers or text_of(run_git(repo, "config", "--get", "gpg.ssh.allowedSignersFile", check=False))
        if not signers:
            add(False, "no allowed-signers file: pass --allowed-signers FILE (or set gpg.ssh.allowedSignersFile); "
                       "without one nobody can be identified as the signer")
        else:
            signers = str(Path(signers).expanduser().resolve())
            checked = run_git(repo, "verify-tag", tag, config=["gpg.format=ssh", f"gpg.ssh.allowedSignersFile={signers}"],
                              check=False)
            first = (text_of(checked).splitlines() or [""])[0]
            add(checked.returncode == 0, f"signature: {first}" if checked.returncode == 0
                else f"signature check failed: {first or 'the tag has no signature'}")

    message = run_git(repo, "for-each-ref", "--format=%(contents)", ref).stdout.decode("utf-8", "replace")
    recorded = HASH_LINE.search(message)
    files = hashes_from_rev(repo, tag)
    actual = release_hash(files)
    if not add(bool(recorded), "the tag records a release hash" if recorded
               else "the tag message has no 'release-hash: sha256:...' line"):
        pass
    else:
        add(actual == recorded.group(1), "the files in the tag match the recorded hash" if actual == recorded.group(1)
            else f"the files in the tag hash to {actual[:12]}..., but the tag records {recorded.group(1)[:12]}...")

    version = run_git(repo, "show", f"{ref}^{{tree}}:VERSION", check=False)
    shown = version.stdout.decode().strip() if version.returncode == 0 else None
    add(shown == tag[1:], f"VERSION in the tag is {tag[1:]}" if shown == tag[1:]
        else f"VERSION in the tag is {shown!r}, not {tag[1:]!r}")

    if worktree:
        changed, only_tag, only_now = diff_files(files, hashes_from_worktree(repo))
        names = (changed + only_tag + only_now)[:5]
        same = not (changed or only_tag or only_now)
        add(same, "your working tree equals the tag" if same else
            f"your working tree differs from the tag ({len(changed)} changed, {len(only_tag)} missing, "
            f"{len(only_now)} not in the tag): {', '.join(names)}")
    return finish()


# ----------------------------------------------------------------------------------------------- tag, build-info
def make_tag(repo, tag, message=None, dry_run=False) -> str:
    """Create a signed annotated tag at HEAD whose message records the release hash. Never pushes."""
    if not TAG_RE.match(tag):
        raise ReleaseError(f"{tag!r} is not a release tag name (vMAJOR.MINOR.PATCH, or with -rcN)")
    if run_git(repo, "status", "--porcelain", "--untracked-files=no").stdout.strip():
        raise ReleaseError("the working tree has uncommitted changes to tracked files; commit them first")
    if run_git(repo, "rev-parse", "-q", "--verify", f"refs/tags/{tag}", check=False).returncode == 0:
        raise ReleaseError(f"the tag {tag} already exists")
    try:
        version = (Path(repo) / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        raise ReleaseError("there is no VERSION file") from None
    if version != tag[1:]:
        raise ReleaseError(f"VERSION says {version!r}; set it to {tag[1:]!r} and commit before tagging {tag}")
    if text_of(run_git(repo, "config", "--get", "gpg.format", check=False)) != "ssh" or not text_of(
            run_git(repo, "config", "--get", "user.signingkey", check=False)):
        raise ReleaseError(SETUP_HELP)
    digest = release_hash(hashes_from_rev(repo, "HEAD"))
    full = f"{message or f'Release {tag}'}\n\nrelease-hash: sha256:{digest}\n"
    if not dry_run:
        run_git(repo, "tag", "-s", "-m", full, tag)
    return full


def build_info(repo) -> dict:
    """What the About line shows. No timestamp, so the same checkout gives the same file."""
    repo = Path(repo)
    try:
        version = (repo / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        raise ReleaseError("there is no VERSION file") from None
    import data_schema
    exact = run_git(repo, "describe", "--tags", "--exact-match", "HEAD", check=False)
    return {
        "version": version,
        "commit": text_of(run_git(repo, "rev-parse", "HEAD")),
        "tag": exact.stdout.decode().strip() if exact.returncode == 0 else None,
        "release_hash": "sha256:" + release_hash(hashes_from_worktree(repo)),
        "clean": not run_git(repo, "status", "--porcelain", "--untracked-files=no").stdout.strip(),
        "data_schema": {**data_schema.CURRENT, "activity_log": data_schema.LOG_VERSION},
    }


# ----------------------------------------------------------------------------------------------- command line
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="release.py", description="Release hash, signed-tag checks and build information.")
    ap.add_argument("--repo", default=str(ROOT), help="the git checkout to use (default: this one)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("hash", help="print the release hash")
    p.add_argument("--rev", help="a tag or commit; default is the working tree")
    p = sub.add_parser("verify", help="check a release tag")
    p.add_argument("tag")
    p.add_argument("--worktree", action="store_true", help="also require your files to equal the tag")
    p.add_argument("--allowed-signers", help="the file listing whose signatures to trust")
    p.add_argument("--no-signature", action="store_true", help="skip the signature check (the tag is then NOT authenticated)")
    p = sub.add_parser("tag", help="create a signed tag that records the release hash (never pushes)")
    p.add_argument("tag")
    p.add_argument("-m", "--message")
    p.add_argument("--dry-run", action="store_true")
    sub.add_parser("build-info", help=f"write {BUILD_INFO}")
    p = sub.add_parser("data-check", help="versions of the files in logs/")
    p.add_argument("logs", nargs="?")
    args = ap.parse_args(argv)
    repo = Path(args.repo)
    try:
        ensure_repo(repo)
        if args.cmd == "hash":
            files = hashes_from_rev(repo, args.rev) if args.rev else hashes_from_worktree(repo)
            print("sha256:" + release_hash(files))
            return 0
        if args.cmd == "verify":
            results, code = verify(repo, args.tag, args.allowed_signers, args.worktree, args.no_signature)
            for status, text in results:
                print(f"{status:5} {text}")
            print({0: "RESULT: PASS", 1: "RESULT: FAIL",
                   3: "RESULT: integrity checks passed, but the tag is NOT authenticated (signature not checked)"}[code])
            return code
        if args.cmd == "tag":
            full = make_tag(repo, args.tag, args.message, args.dry_run)
            print(("would create" if args.dry_run else "created") + f" signed tag {args.tag} with message:\n\n{full}")
            if not args.dry_run:
                print(f"Not pushed. To publish it: git push origin {args.tag}")
            return 0
        if args.cmd == "build-info":
            info = build_info(repo)
            (repo / BUILD_INFO).write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
            print(f"wrote {BUILD_INFO}: version {info['version']}, commit {info['commit'][:12]}, {info['release_hash'][:19]}..."
                  + ("" if info["clean"] else "  (the working tree has uncommitted changes)"))
            return 0
        if args.cmd == "data-check":
            import data_schema
            code, lines = data_schema.check(args.logs or repo / "logs")
            print("\n".join(lines))
            return code
    except ReleaseError as e:
        print(f"release.py: {e}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())

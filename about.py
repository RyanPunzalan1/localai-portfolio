"""
about.py - the one line the app shows about itself: version, commit, release hash, data schema
(design/versioned-data-and-releases.md, roadmap 11.3).

The values come from VERSION and from build_info.json, which `python scripts/release.py build-info` writes and the image
copies in at build time. The app only DISPLAYS them: it has no network and fetches nothing, and it can't check them
against a tag. The comparison is `python scripts/release.py verify`, run by you.

Both files are untrusted input here (build_info.json is a file anyone with write access to the checkout could edit),
so every value is matched against a strict pattern and anything else is ignored. Nothing is ever shown as written.
Plain text only.
"""

import json
import re
from pathlib import Path

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(-rc\d+)?$")
TAG_RE = re.compile(r"^v\d+\.\d+\.\d+(-rc\d+)?$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
MAX_BUILD_INFO_BYTES = 16 * 1024


def _read_text(path, limit=MAX_BUILD_INFO_BYTES):
    try:
        with open(path, "rb") as f:
            return f.read(limit + 1).decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def about_info(root=None) -> dict:
    """The validated facts. Anything missing, oversized or not in the expected form is None."""
    root = Path(root) if root is not None else Path(__file__).resolve().parent
    info = {"version": None, "build_version": None, "commit": None, "tag": None, "release_hash": None,
            "clean": None, "pending_schema": None, "built": False}
    text = _read_text(root / "VERSION", 100)
    if text is not None and VERSION_RE.match(text.strip()):
        info["version"] = text.strip()
    raw = _read_text(root / "build_info.json")
    if raw is None or len(raw.encode("utf-8")) > MAX_BUILD_INFO_BYTES:
        return info
    try:
        build = json.loads(raw)
    except ValueError:
        return info
    if not isinstance(build, dict):
        return info

    def pick(key, pattern):
        value = build.get(key)
        return value if isinstance(value, str) and pattern.match(value) else None

    info["build_version"] = pick("version", VERSION_RE)
    info["commit"] = pick("commit", COMMIT_RE)
    info["tag"] = pick("tag", TAG_RE)
    info["release_hash"] = pick("release_hash", HASH_RE)
    info["clean"] = build.get("clean") if isinstance(build.get("clean"), bool) else None
    schema = build.get("data_schema")
    pending = schema.get("pending") if isinstance(schema, dict) else None
    info["pending_schema"] = pending if isinstance(pending, int) and not isinstance(pending, bool) and 0 < pending < 1000 else None
    info["built"] = bool(info["commit"] and info["release_hash"])
    return info


def about_line(root=None) -> str:
    info = about_info(root)
    parts = [f"Version {info['version'] or 'unknown'}"]
    if not info["built"]:
        parts.append("no build information (run python scripts/release.py build-info, then rebuild the containers)")
        return " · ".join(parts)
    if info["tag"]:
        parts.append(f"tag {info['tag']}")
    parts.append(f"commit {info['commit'][:7]}")
    parts.append(f"hash {info['release_hash'][:19]}…")
    if info["pending_schema"]:
        parts.append(f"inbox schema {info['pending_schema']}")
    if info["clean"] is False:
        parts.append("built from a tree with uncommitted changes")
    if info["build_version"] and info["build_version"] != info["version"]:
        parts.append(f"build information is for {info['build_version']}, not {info['version'] or 'this version'}")
    return " · ".join(parts)

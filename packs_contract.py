"""
packs_contract.py - the checks every pack must pass (design/pack-contract.md, roadmap 10.1).

    python -m packs_contract packs/tasks packs/lessons
    python -m packs_contract --all packs          (every folder in packs/ that has a manifest.toml)

Each check runs in a throwaway docs/ holding dummy files only (never the real docs/), by calling the pack's tools
directly with hostile arguments, the way a manipulated model might. It prints the problems it finds; no output
problems means the pack keeps the rules. Exit code 0 = every pack passed.

What this is not: a security boundary. It catches mistakes in honest, reviewed code. Python has no in-process
sandbox, so a malicious pack that someone merges can still do harm (design/pack-contract.md, section 4).

Checks (ids are used in messages and in the tests):
  C1  the manifest is valid, and runnable (permissions.model = true)
  C2  pack.py imports, and its tools are exactly the manifest's tools (same check the app makes at load)
  C3  no tool call changes any file before approval
  C4  every staged item is for a listed file in a listed mode, and its name is plain
  C5  a tool declared writes = false stages nothing
  C6  hostile names (../, absolute, drive, reserved, NUL, glob traversal) never escape the list or docs/
  C7  a symlink or hard link named like a readable file is never followed
  C8  text from a file outside the read list never reaches a tool's output
  C9  pack.py has no direct file, network, shell or code-execution access (an accident check)
  C10 the core refuses, at Approve, an item that claims to come from this pack but breaks its manifest
"""

import ast
import inspect
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest import mock

import agent as agent_mod
from packs_agent import _load_pack_module, wrap_pack_tools
from packs_gateway import Gateway, _allowed
from packs_manifest import WRITE_MODES, ManifestError, PackError, check_runnable, parse_manifest

FORBIDDEN_MODULES = {"os", "pathlib", "shutil", "subprocess", "socket", "urllib", "http", "requests", "ctypes",
                     "importlib"}
FORBIDDEN_NAMES = {"open", "eval", "exec", "compile", "__import__"}

CANARY_UNLISTED = "CANARY-UNLISTED-4f2a91"   # lives in a file the manifest does not list
CANARY_OUTSIDE = "CANARY-OUTSIDE-9c07e3"     # lives outside docs/, reachable only through a link
UNLISTED_NAMES = ("zz-unlisted.md", "zz-unlisted.txt", "zz-other.md")
HOSTILE = ["../x.md", "/etc/passwd.md", "C:x.md", "..\\x.md", "CON.md", "a\x00b.md", "../../etc/passwd",
           "\n- [ ] injected line", "A" * 10000, "*", "x/../x.md", "~/x.md"]


# ----------------------------------------------------------------------------------------- C9, a static scan
def scan_source(text: str) -> list:
    """C9 (and a syntax check): [(check id, message)] for forbidden imports and calls in pack.py."""
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        return [("C2", f"pack.py has a syntax error: {e.msg} (line {e.lineno})")]
    found = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in FORBIDDEN_MODULES:
                    found.setdefault(f"imports '{alias.name}'", node.lineno)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module and node.module.split(".")[0] in FORBIDDEN_MODULES:
                found.setdefault(f"imports from '{node.module}'", node.lineno)
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            found.setdefault(f"uses '{node.id}'", node.lineno)
        elif isinstance(node, ast.Attribute) and node.attr == "open":
            found.setdefault("calls an .open() method", node.lineno)
    return [("C9", f"pack.py {what} (line {line}); packs reach files only through the gateway")
            for what, line in sorted(found.items(), key=lambda kv: kv[1])]


# ----------------------------------------------------------------------------------------- the throwaway world
def _sample_name(pattern: str):
    """A plain file name that a manifest pattern matches, or None."""
    name = pattern
    if any(c in pattern for c in "*?["):
        name = pattern.replace("*", "sample").replace("?", "x")
        if "[" in name:
            return None
    return name if _allowed([pattern], name) else None


def _snapshot(root: Path) -> dict:
    snap = {}
    for path in sorted(root.rglob("*")):
        rel = str(path.relative_to(root))
        if path.is_symlink():
            snap[rel] = ("link", os.readlink(path))
        elif path.is_file():
            snap[rel] = ("file", path.read_bytes())
        else:
            snap[rel] = ("dir", None)
    return snap


class _World:
    """A temporary docs/ and an 'outside' folder. Rebuilt before every call, so calls cannot affect each other."""

    def __init__(self, manifest):
        self.manifest = manifest
        self._tmp = tempfile.TemporaryDirectory(prefix="packcheck-")
        root = Path(self._tmp.name).resolve()
        self.docs, self.outside = root / "docs", root / "outside"
        self.outside.mkdir()
        self.secret = self.outside / "secret.txt"
        self.secret.write_text(f"{CANARY_OUTSIDE}\n", encoding="utf-8")
        patterns = list(manifest.read) + list(manifest.write)
        self.names = sorted({n for n in (_sample_name(p) for p in patterns) if n})
        self.unlisted = next((n for n in UNLISTED_NAMES if not _allowed(manifest.read, n)), None)

    def close(self):
        self._tmp.cleanup()

    def populate(self, kind="normal"):
        """kind: 'normal' (real files), 'symlink' or 'hardlink' (every listed name is a link to the outside secret)."""
        shutil.rmtree(self.docs, ignore_errors=True)
        self.docs.mkdir()
        for name in self.names:
            target = self.docs / name
            if kind == "symlink":
                os.symlink(self.secret, target)
            elif kind == "hardlink":
                os.link(self.secret, target)
            else:
                target.write_text(f"- [ ] sample task\nsample text in {name}\n", encoding="utf-8")
        if kind == "normal" and self.unlisted:
            (self.docs / self.unlisted).write_text(f"{CANARY_UNLISTED}\n", encoding="utf-8")

    def arg_strings(self) -> list:
        strings = list(HOSTILE) + self.names + ([self.unlisted] if self.unlisted else [])
        stem = Path(self.unlisted).stem if self.unlisted else "zz-unlisted"
        for pattern in list(self.manifest.read) + list(self.manifest.write):
            if any(c in pattern for c in "*?["):
                # matches the pattern as typed, but names another file once the folder part is dropped
                strings.append(pattern.replace("*", f"x/../{stem}", 1))
                strings.append(pattern.replace("*", "/../evil", 1))
        return list(dict.fromkeys(strings))


def _short(value, limit=50) -> str:
    text = repr(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."


# ----------------------------------------------------------------------------------------- the run
def run_checks(pack_dir) -> list:
    """[(check id, message)] for everything wrong with the pack. Empty means it passes."""
    pack_dir = Path(pack_dir)
    try:
        manifest = parse_manifest((pack_dir / "manifest.toml").read_text(encoding="utf-8"), pack_dir)
        check_runnable(manifest)
    except (ManifestError, PackError, OSError, UnicodeDecodeError) as e:
        return [("C1", str(e))]

    source = pack_dir / "pack.py"
    if not source.is_file():
        return [("C2", "pack.py is missing")]
    problems = scan_source(source.read_text(encoding="utf-8"))
    if any(cid == "C2" for cid, _ in problems):
        return problems
    try:
        module = _load_pack_module(pack_dir, manifest.name)
    except Exception as e:  # a pack that cannot even import is a failed pack, not a crash of the checker
        return problems + [("C2", f"pack.py failed to import: {e.__class__.__name__}: {e}")]
    if not callable(getattr(module, "build_tools", None)):
        return problems + [("C2", "pack.py has no build_tools(gateway) function")]

    world = _World(manifest)
    seen = set()

    def bad(cid, key, message):
        if (cid, key) not in seen:
            seen.add((cid, key))
            problems.append((cid, message))

    try:
        with mock.patch.object(agent_mod, "DOCS", world.docs):
            for kind in ("normal", "symlink", "hardlink"):
                try:
                    world.populate(kind)
                except (OSError, NotImplementedError):
                    continue  # this machine can't make that kind of link (for example Windows without a privilege)
                _run_phase(manifest, module, world, kind, bad)
            _check_core_refusal(manifest, world, bad)
    finally:
        world.close()
    return problems


def _run_phase(manifest, module, world, kind, bad):
    pending = []
    gateway = Gateway(manifest, pending, label=manifest.agent)
    try:
        # the same function the app uses (packs_agent.PackAgent), so the contract tests what really runs
        tools = wrap_pack_tools(manifest, module.build_tools(gateway), gateway)
    except PackError as e:
        bad("C2", "tools", str(e))
        return
    except Exception as e:
        bad("C2", "build", f"build_tools raised {e.__class__.__name__}: {e}")
        return
    declared = {t["name"]: bool(t.get("writes", False)) for t in manifest.tools}
    violations_before = 0

    for tool_name, fn in tools.items():
        writes = declared.get(tool_name, False)  # an undeclared tool is held to the stricter, read-only rule
        params = list(inspect.signature(fn).parameters)
        strings = world.arg_strings() + ["test"] if params else [None]
        for text in strings:
            kwargs = {p: text for p in params}
            world.populate(kind)
            pending.clear()
            before = (_snapshot(world.docs), _snapshot(world.outside))
            try:
                out = str(fn(**kwargs))
            except Exception:
                out = ""  # a refusal or an error is an acceptable answer to a hostile argument
            after = (_snapshot(world.docs), _snapshot(world.outside))
            staged = list(pending)
            where = f"tool '{tool_name}' called with {_short(text)}"
            _check_call(manifest, world, kind, where, tool_name, writes, before, after, out, staged, bad)
            read_only_violations = getattr(gateway, "read_only_violations", None)
            if read_only_violations is not None and len(read_only_violations) > violations_before:
                bad("C5", tool_name, f"tool '{tool_name}' is declared writes = false but tried to stage a write")
                violations_before = len(read_only_violations)


def _check_core_refusal(manifest, world, bad):
    """C10: forged items (the pack's label, but a file or mode its manifest does not allow) are refused at Approve,
    and nothing is written. This tests the core against this pack's manifest, the last line if a pack gets past the
    gateway (for example by reaching into the inbox)."""
    world.populate("normal")
    forged = []
    evil = next((n for n in ("zz-evil.md", "zz-evil.txt") if not _allowed(manifest.write, n)), None)
    if evil:
        forged.append({"name": evil, "content": "forged", "agent": manifest.agent})
    allowed_name = next((n for n in world.names if _allowed(manifest.write, n)), None)
    banned = sorted(WRITE_MODES - set(manifest.write_modes))
    if allowed_name and banned:
        forged.append({"name": allowed_name, "content": "forged", "agent": manifest.agent, "mode": banned[0]})
    for item in forged:
        approver = agent_mod.DocAgent(pending_writes=[dict(item)])
        approver.register_pack_rules(manifest.agent, manifest.write, manifest.write_modes)
        before = _snapshot(world.docs)
        try:
            approver.approve_write(0)
            refused = False
        except agent_mod.ApprovalRefused:
            refused = True
        except Exception:
            refused = True  # refused for another reason, and nothing was written (checked next)
        if not refused or _snapshot(world.docs) != before:
            bad("C10", item.get("mode", "name"),
                f"Approve did not refuse a forged change to {_short(item['name'])} (mode '{item.get('mode', 'create')}')")


def _check_call(manifest, world, kind, where, tool_name, writes, before, after, out, staged, bad):
    if before != after:
        bad("C3", tool_name, f"{where} changed files before approval")
    if staged and not writes:
        bad("C5", tool_name, f"{where} is declared writes = false but staged a change")
    texts = [out] + [str(v) for item in staged for v in item.values()]
    for item in staged:
        _check_item(manifest, world, item, f"{where} staged", tool_name, bad)
    if kind != "normal":
        if any(CANARY_OUTSIDE in t for t in texts):
            bad("C7", tool_name, f"{where} followed a {kind} to a file outside docs/")
    elif any(CANARY_UNLISTED in t for t in texts):
        bad("C8", tool_name, f"{where} exposed text from a file outside its read list")


def _check_item(manifest, world, item, where, tool_name, bad):
    name, mode = item.get("name"), item.get("mode", "create")
    if not isinstance(name, str) or name != Path(name.replace("\\", "/")).name or any(
            c in name for c in ("/", "\\", ":", "\x00")) or name in {"", ".", ".."}:
        bad("C6", tool_name, f"{where} a change with a name that is not a plain file name: {_short(name)}")
        return
    if not _allowed(manifest.write, name) or mode not in manifest.write_modes:
        bad("C4", tool_name, f"{where} a change to {_short(name)} in mode '{mode}', which the manifest does not allow")
        return
    try:
        path = agent_mod._safe_path(name)
    except ValueError:
        bad("C6", tool_name, f"{where} a change to {_short(name)}, which the file guard refuses")
        return
    if path.parent != world.docs:
        bad("C6", tool_name, f"{where} a change to {_short(name)}, which is not directly inside docs/")


def check_pack(pack_dir) -> list:
    """Problems as 'C4: ...' strings. Empty means the pack passes."""
    return [f"{cid}: {message}" for cid, message in run_checks(pack_dir)]


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["--all"]:
        if len(args) != 2 or not Path(args[1]).is_dir():
            print("usage: python -m packs_contract --all <folder of packs>")
            return 2
        args = [str(p) for p in sorted(Path(args[1]).iterdir()) if (p / "manifest.toml").is_file()]
        if not args:
            print("no packs found")
            return 2
    if not args:
        print("usage: python -m packs_contract packs/<name> [packs/<name> ...]   |   --all <folder of packs>")
        return 2
    failed = 0
    for arg in args:
        problems = check_pack(arg)
        print(f"{'FAIL' if problems else 'PASS'}  {Path(arg).name}")
        for problem in problems:
            print(f"      - {problem}")
        failed += bool(problems)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

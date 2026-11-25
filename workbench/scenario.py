"""Scenario packs: TOML files of plain data (design 5.3; Phase 5). Trusted host-side code; the files are not trusted.

A pack is a folder with `pack.toml` and one `<id>.toml` per scenario. Loading is strict: an unknown key, a wrong type, a
path that is not a plain file name, an unknown capability, predicate or placeholder, or anything over the size limits is
refused with ScenarioError. Scenario files hold no code, no shell, no regular expressions and no paths outside the
fixture, so loading one can only produce data.

Scenario file (every key below; nothing else is accepted):
  id, version, kind (attack | benign | control), description, request, requires = [capabilities]
  [canaries]       name = "PREFIX-"      a fresh value PREFIX + 8 hex characters is made per trial
  [files]          "name.md" = "text"    fixture files in the agent's notes folder; may use {canary} placeholders
  [outside_files]  "name.txt" = "text"   files beside (not inside) the notes folder, for reads the tools do not offer
  [expect]         answer_contains = "phrase"            (benign: the expected result)
  [predicates]     model_saw = "canary"                  the injected text reached the model (host-side channel log)
                   canary_in_answer = "canary"           this canary in the answer is the harm
                   allowed_writes = ["name"]             any other workspace change is the harm
                   forbidden_tools = ["tool"]            asking for one is an attempt the tool layer stopped
                   write_tools = ["tool"]                tools that write (used to say when an attempt is not observable)

The outcome rules stay in verdict.decide (owner decision 2026-11-25); `instantiate` turns a scenario into the dict that
decide and run_trial already take.
"""

import hashlib
import json
import re
import secrets
import tomllib
from pathlib import Path

PACKS = Path(__file__).resolve().parent / "scenarios"
FORMAT = 1
KINDS = {"attack", "benign", "control"}
CAPABILITIES = {"file_read", "file_write", "file_write_approval", "shell", "network_client"}
TOP_KEYS = {"id", "version", "kind", "description", "request", "requires", "canaries", "files", "outside_files",
            "expect", "predicates"}
PACK_KEYS = {"format", "name", "version", "description", "order"}
EXPECT_KEYS = {"answer_contains"}
PREDICATE_KEYS = {"model_saw", "canary_in_answer", "allowed_writes", "forbidden_tools", "write_tools"}
NAME = re.compile(r"[a-z][a-z0-9_]{0,47}")
FILE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
PREFIX = re.compile(r"[A-Z][A-Z0-9-]{0,23}")
PLACEHOLDER = re.compile(r"\{([^{}]*)\}")
MAX_FILE_BYTES = 64 * 1024
MAX_SCENARIO_BYTES = 256 * 1024
MAX_TEXT = 2000
MAX_FILES = 20
MAX_SCENARIOS = 200


class ScenarioError(Exception):
    """A scenario or pack file broke the format. The message names the file and the problem, never file contents."""


def _fail(where, msg):
    raise ScenarioError(f"{where}: {msg}")


def _text(where, key, v, limit=MAX_TEXT, empty_ok=False):
    if not isinstance(v, str):
        _fail(where, f"{key} must be text")
    if not v and not empty_ok:
        _fail(where, f"{key} is empty")
    if len(v) > limit:
        _fail(where, f"{key} is longer than {limit} characters")
    if "\x00" in v:
        _fail(where, f"{key} contains a NUL character")
    return v


def _names(where, key, v, pattern):
    if not isinstance(v, list) or not all(isinstance(x, str) and pattern.fullmatch(x) for x in v):
        _fail(where, f"{key} must be a list of plain names")
    if len(set(v)) != len(v):
        _fail(where, f"{key} has duplicates")
    return list(v)


def _read_toml(path: Path, limit):
    try:
        raw = path.read_bytes()
    except OSError as e:
        _fail(path.name, f"cannot be read ({e.__class__.__name__})")
    if len(raw) > limit:
        _fail(path.name, f"is larger than {limit} bytes")
    try:
        return tomllib.loads(raw.decode("utf-8")), raw
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
        _fail(path.name, f"is not valid UTF-8 TOML ({e.__class__.__name__})")


def _placeholders(where, key, text, canaries):
    for name in PLACEHOLDER.findall(text):
        if name not in canaries:
            _fail(where, f"{key} uses {{{name}}}, which is not a declared canary")
    if text.count("{") != len(PLACEHOLDER.findall(text)) or text.count("}") != len(PLACEHOLDER.findall(text)):
        _fail(where, f"{key} has an unmatched brace")


def validate(doc, where="scenario") -> dict:
    """Check one parsed scenario file. Returns it unchanged; raises ScenarioError on the first problem."""
    if not isinstance(doc, dict):
        _fail(where, "is not a table")
    extra = set(doc) - TOP_KEYS
    if extra:
        _fail(where, f"unknown keys {sorted(extra)}")
    for k in ("id", "version", "kind", "description", "request", "requires", "files"):
        if k not in doc:
            _fail(where, f"missing {k}")
    if not isinstance(doc["id"], str) or not NAME.fullmatch(doc["id"]):
        _fail(where, "id must be a lowercase name (letters, digits, underscores)")
    if type(doc["version"]) is not int or not 1 <= doc["version"] <= 10_000:
        _fail(where, "version must be a whole number from 1")
    if doc["kind"] not in KINDS:
        _fail(where, f"kind must be one of {sorted(KINDS)}")
    _text(where, "description", doc["description"])
    _text(where, "request", doc["request"])
    unknown = set(_names(where, "requires", doc["requires"], NAME)) - CAPABILITIES
    if unknown:
        _fail(where, f"unknown capabilities {sorted(unknown)}")

    canaries = doc.get("canaries", {})
    if not isinstance(canaries, dict) or len(canaries) > 8:
        _fail(where, "canaries must be a table of at most 8 entries")
    for name, prefix in canaries.items():
        if not NAME.fullmatch(name) or not isinstance(prefix, str) or not PREFIX.fullmatch(prefix):
            _fail(where, f"canary {name!r} needs a lowercase name and an uppercase prefix such as \"INJ-\"")

    total = 0
    for section in ("files", "outside_files"):
        files = doc.get(section, {})
        if not isinstance(files, dict) or len(files) > MAX_FILES:
            _fail(where, f"{section} must be a table of at most {MAX_FILES} files")
        for fname, text in files.items():
            if not FILE_NAME.fullmatch(fname) or fname in (".", "..") or ".." in fname:
                _fail(where, f"{section} name {fname!r} must be a plain file name (no folders)")
            _text(where, f"{section}.{fname}", text, MAX_FILE_BYTES, empty_ok=True)
            _placeholders(where, f"{section}.{fname}", text, canaries)
            total += len(text.encode())
    if not doc["files"]:
        _fail(where, "files is empty")
    if total > MAX_SCENARIO_BYTES:
        _fail(where, f"fixture files total more than {MAX_SCENARIO_BYTES} bytes")
    clash = set(doc["files"]) & set(doc.get("outside_files", {}))
    if clash:
        _fail(where, f"{sorted(clash)} is both a notes file and an outside file")
    if len(doc.get("outside_files", {})) > 1 or set(doc.get("outside_files", {})) - {"secret.txt"}:
        _fail(where, "outside_files may only hold secret.txt (the one place the runner writes outside the notes folder)")
    _placeholders(where, "request", doc["request"], {})

    expect = doc.get("expect", {})
    if not isinstance(expect, dict) or set(expect) - EXPECT_KEYS:
        _fail(where, f"expect may only hold {sorted(EXPECT_KEYS)}")
    if "answer_contains" in expect:
        _text(where, "expect.answer_contains", expect["answer_contains"], 200)
    preds = doc.get("predicates", {})
    if not isinstance(preds, dict) or set(preds) - PREDICATE_KEYS:
        _fail(where, f"predicates may only hold {sorted(PREDICATE_KEYS)}")
    for k in ("model_saw", "canary_in_answer"):
        if k in preds and (not isinstance(preds[k], str) or preds[k] not in canaries):
            _fail(where, f"predicates.{k} must name a declared canary")
    for k in ("allowed_writes",):
        if k in preds:
            for f in _names(where, f"predicates.{k}", preds[k], FILE_NAME):
                if ".." in f:
                    _fail(where, f"predicates.{k} entry {f!r} must be a plain file name")
    for k in ("forbidden_tools", "write_tools"):
        if k in preds:
            _names(where, f"predicates.{k}", preds[k], NAME)

    if doc["kind"] == "benign" and "answer_contains" not in expect:
        _fail(where, "a benign scenario needs expect.answer_contains")
    if doc["kind"] == "attack" and not ({"model_saw", "canary_in_answer", "allowed_writes", "forbidden_tools"} & set(preds)):
        _fail(where, "an attack scenario needs at least one predicate")
    if doc["kind"] == "control":
        _fail(where, "control scenarios are not supported by the runner yet")
    return doc


def scenario_hash(doc) -> str:
    return hashlib.sha256(json.dumps(doc, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


class Pack:
    def __init__(self, name, version, description, order, scenarios, digest):
        self.name, self.version, self.description = name, version, description
        self.order, self.scenarios, self.hash = order, scenarios, digest

    def ref(self) -> dict:
        """What every record carries about the pack (design 5.3: packs are versioned and hashed into every record)."""
        return {"name": self.name, "version": self.version, "hash": self.hash}

    def instantiate(self, scenario_id: str, values=None) -> dict:
        return instantiate(self.scenarios[scenario_id], self.ref(), values)


def load_pack(path) -> Pack:
    """Load and validate a whole pack folder. Only `pack.toml` and the `<id>.toml` files it lists are read."""
    d = Path(path)
    if not d.is_dir() or d.is_symlink():
        _fail(str(d.name), "is not a pack folder")
    meta, meta_raw = _read_toml(d / "pack.toml", 16 * 1024)
    if set(meta) - PACK_KEYS or not PACK_KEYS - {"description"} <= set(meta):
        _fail("pack.toml", f"must hold exactly {sorted(PACK_KEYS)}")
    if meta["format"] != FORMAT:
        _fail("pack.toml", f"format {meta['format']!r} is not supported (this workbench reads format {FORMAT})")
    if not isinstance(meta["name"], str) or not NAME.fullmatch(meta["name"]):
        _fail("pack.toml", "name must be a lowercase name")
    if type(meta["version"]) is not int or meta["version"] < 1:
        _fail("pack.toml", "version must be a whole number from 1")
    order = _names("pack.toml", "order", meta["order"], NAME)
    if not order or len(order) > MAX_SCENARIOS:
        _fail("pack.toml", f"order must list 1 to {MAX_SCENARIOS} scenarios")
    listed = {f"{i}.toml" for i in order} | {"pack.toml"}
    stray = sorted(p.name for p in d.iterdir() if p.suffix == ".toml" and p.name not in listed)
    if stray:
        _fail("pack.toml", f"files not listed in order: {stray}")
    h = hashlib.sha256(b"pack.toml\0" + meta_raw)
    scenarios = {}
    for sid in order:
        f = d / f"{sid}.toml"
        if f.is_symlink():
            _fail(f.name, "is a link; scenario files must be plain files")
        doc, raw = _read_toml(f, MAX_SCENARIO_BYTES + 16 * 1024)
        validate(doc, f.name)
        if doc["id"] != sid:
            _fail(f.name, f"id {doc['id']!r} does not match the file name")
        scenarios[sid] = doc
        h.update(f"\0{f.name}\0".encode() + raw)
    return Pack(meta["name"], meta["version"], _text("pack.toml", "description", meta.get("description", "-")),
                order, scenarios, h.hexdigest()[:16])


def _fill(text, values):
    return PLACEHOLDER.sub(lambda m: values[m.group(1)], text)


def instantiate(doc, pack_ref=None, values=None) -> dict:
    """One trial's scenario: fresh canary values (or the given ones, for tests), placeholders filled in, and the
    predicate inputs in the shape verdict.decide and run_trial take. The unfilled file is what gets hashed."""
    canaries = doc.get("canaries", {})
    values = dict(values) if values else {n: p + secrets.token_hex(4) for n, p in canaries.items()}
    if set(values) != set(canaries):
        raise ScenarioError(f"{doc['id']}: values must cover exactly the canaries {sorted(canaries)}")
    preds, expect = doc.get("predicates", {}), doc.get("expect", {})
    scn = {
        "id": doc["id"], "version": doc["version"], "kind": doc["kind"], "request": doc["request"],
        "requires": list(doc["requires"]),
        "files": {n: _fill(t, values) for n, t in doc["files"].items()},
        "allowed_write_targets": list(preds.get("allowed_writes", [])),
        "forbidden_tools": list(preds.get("forbidden_tools", [])),
        "write_tools": list(preds.get("write_tools", [])),
        "injection": preds.get("model_saw"), "secret": preds.get("canary_in_answer"),
        "values": values, "template": doc, "hash": scenario_hash(doc), "pack": pack_ref,
    }
    if "answer_contains" in expect:
        scn["expect_answer"] = expect["answer_contains"]
    if "secret.txt" in doc.get("outside_files", {}):
        scn["secret_file"] = _fill(doc["outside_files"]["secret.txt"], values)
    return scn


def core() -> Pack:
    return load_pack(PACKS / "core")

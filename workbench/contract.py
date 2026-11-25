"""Agent integration contract, version 1 (design section 6). A process boundary, never an import.

An agent is an OCI image plus a manifest (agent.toml). The workbench never loads the agent's code into its own process
and never trusts what the manifest says about the agent's safety: capabilities only decide whether a scenario applies
("not applicable" instead of "passed"), and the integration level only decides how much evidence a trial can produce.

Manifest (TOML; standard library tomllib; unknown keys are refused so a manifest cannot widen anything):

  contract = 1
  name = "my-agent"                      # [a-z0-9][a-z0-9._-]{0,47}
  image = "registry-less/ref@sha256:..." # a local image reference; never pulled (specs.check_image)
  image_id = "sha256:..."                # optional: pins a locally built image by its image ID (checked before each run)
  entrypoint = ["python3", "/run/adapter/run.py"]   # argv, run inside the sandbox as the sandbox user
  [model]       api = "openai-chat" | "ollama-chat"      needs_tools = true|false
  [capabilities] file_read = bool   file_write = "no"|"direct"|"approval"   shell = bool   network_client = bool
  [approval]    supported = bool     # the agent asks the approval endpoint before any write, send or delete
  [limits]      timeout_seconds = 30..1800

Integration levels (design 6.4): L0 black box; L1 approval-aware (approval.supported); L2 adds agent-reported events,
which are diagnosis only and never decide an outcome.

Files the workbench provides inside the sandbox: /run/task.json (the request), /workspace (the fixture copy),
/run/out/answer.txt and optional /run/out/events.jsonl (self-reported). The model and approval endpoints are on the
sandbox's own loopback: http://127.0.0.1:13131 (workbench/channel.py).
"""

import json
import re
import tomllib
from dataclasses import dataclass

from workbench import specs

CONTRACT_VERSION = 1
TASK_PATH = "/run/task.json"
ANSWER_PATH = "/run/out/answer.txt"
EVENTS_PATH = "/run/out/events.jsonl"
MODEL_BASE = "http://127.0.0.1:13131"
MAX_ANSWER_BYTES = 64 * 1024
MAX_EVENTS_BYTES = 256 * 1024
NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,47}$")
APIS = ("openai-chat", "ollama-chat")
WRITE_MODES = ("no", "direct", "approval")
TOP_KEYS = {"contract", "name", "image", "image_id", "entrypoint", "model", "capabilities", "approval", "limits"}
IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
SECTION_KEYS = {"model": {"api", "needs_tools"},
                "capabilities": {"file_read", "file_write", "shell", "network_client"},
                "approval": {"supported"}, "limits": {"timeout_seconds"}}


class ContractError(ValueError):
    """The manifest or a contract file is invalid. The agent is not run."""


@dataclass(frozen=True)
class Manifest:
    name: str
    image: str
    image_id: str
    entrypoint: tuple
    api: str
    needs_tools: bool
    file_read: bool
    file_write: str
    shell: bool
    network_client: bool
    approval: bool
    timeout_seconds: int

    @property
    def level(self) -> str:
        return "L1" if self.approval else "L0"

    @property
    def pinned(self) -> bool:
        return "@sha256:" in self.image or bool(self.image_id)

    def capabilities(self) -> set:
        caps = set()
        if self.file_read:
            caps.add("file_read")
        if self.file_write != "no":
            caps.add("file_write")
        if self.file_write == "approval":
            caps.add("file_write_approval")
        if self.shell:
            caps.add("shell")
        if self.network_client:
            caps.add("network_client")
        return caps


def _section(doc, key):
    value = doc.get(key, {})
    if not isinstance(value, dict):
        raise ContractError(f"[{key}] must be a table")
    extra = set(value) - SECTION_KEYS[key]
    if extra:
        raise ContractError(f"unknown keys in [{key}]: {sorted(extra)}")
    return value


def parse_manifest(text: str) -> Manifest:
    """Validate a manifest. Raises ContractError for anything unknown, malformed or widening."""
    try:
        doc = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ContractError(f"not valid TOML: {e}") from None
    extra = set(doc) - TOP_KEYS
    if extra:
        raise ContractError(f"unknown keys: {sorted(extra)}")
    if doc.get("contract") != CONTRACT_VERSION:
        raise ContractError(f"contract must be {CONTRACT_VERSION}")
    name = doc.get("name")
    if not isinstance(name, str) or not NAME.match(name):
        raise ContractError("bad name")
    try:
        image = specs.check_image(doc.get("image"))
    except specs.SpecError as e:
        raise ContractError(str(e)) from None
    image_id = doc.get("image_id", "")
    if image_id and (not isinstance(image_id, str) or not IMAGE_ID.match(image_id)):
        raise ContractError("image_id must look like sha256:<64 hex>")
    entry = doc.get("entrypoint")
    if (not isinstance(entry, list) or not 1 <= len(entry) <= 16
            or not all(isinstance(x, str) and 0 < len(x) <= 256 and "\x00" not in x for x in entry)):
        raise ContractError("entrypoint must be a list of 1 to 16 non-empty strings")
    model, caps = _section(doc, "model"), _section(doc, "capabilities")
    appr, limits = _section(doc, "approval"), _section(doc, "limits")
    api = model.get("api")
    if api not in APIS:
        raise ContractError(f"model.api must be one of {APIS}")
    write = caps.get("file_write", "no")
    if write not in WRITE_MODES:
        raise ContractError(f"capabilities.file_write must be one of {WRITE_MODES}")
    flags = {"needs_tools": model.get("needs_tools", False), "file_read": caps.get("file_read", False),
             "shell": caps.get("shell", False), "network_client": caps.get("network_client", False),
             "approval": appr.get("supported", False)}
    for key, value in flags.items():
        if not isinstance(value, bool):
            raise ContractError(f"{key} must be true or false")
    timeout = limits.get("timeout_seconds", 300)
    if not isinstance(timeout, int) or isinstance(timeout, bool) or not 30 <= timeout <= 1800:
        raise ContractError("limits.timeout_seconds must be an integer from 30 to 1800")
    if flags["approval"] and write != "approval":
        raise ContractError("approval.supported needs capabilities.file_write = \"approval\"")
    return Manifest(name=name, image=image, image_id=image_id, entrypoint=tuple(entry), api=api, needs_tools=flags["needs_tools"],
                    file_read=flags["file_read"], file_write=write, shell=flags["shell"],
                    network_client=flags["network_client"], approval=flags["approval"], timeout_seconds=timeout)


def require_pinned_for_tier(manifest: Manifest, tier: int):
    """Third-party agents in the VM tier must be pinned by digest (design T8)."""
    if tier == 2 and not manifest.pinned:
        raise ContractError("Tier 2 needs an image pinned by digest (name@sha256:...) or by image_id")


def task_file(request: str, trial_id: str) -> str:
    if not isinstance(request, str) or not request.strip() or len(request) > 8000:
        raise ContractError("request must be 1 to 8000 characters")
    return json.dumps({"request": request, "trial_id": trial_id, "contract": CONTRACT_VERSION})


def applies(requires, manifest: Manifest) -> list:
    """Capabilities a scenario needs that the agent does not declare. Empty means the scenario applies."""
    return sorted(set(requires) - manifest.capabilities())


def parse_answer(raw: bytes) -> str:
    """The agent's answer text: size-capped, decoded leniently, control characters (except newline and tab) removed."""
    text = raw[:MAX_ANSWER_BYTES].decode("utf-8", "replace")
    return "".join(c for c in text if c in "\n\t" or ord(c) >= 32)


def redact(text, values: dict):
    """Replace scenario canary values (name -> value) with <name>, in a string or in every string of a list of dicts.
    Applied to everything the agent wrote before it is stored in a record; the verdict still sees the raw text."""
    if isinstance(text, str):
        for name, value in values.items():
            if value:
                text = text.replace(value, f"<{name}>")
        return text
    if isinstance(text, list):
        return [{k: redact(v, values) for k, v in ev.items()} if isinstance(ev, dict) else ev for ev in text]
    return text


def parse_events(raw: bytes) -> list:
    """Self-reported events (L2): a list of small JSON objects; bad lines are dropped, never trusted."""
    out = []
    for line in raw[:MAX_EVENTS_BYTES].decode("utf-8", "replace").splitlines()[:2000]:
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if isinstance(ev, dict):
            out.append({str(k)[:40]: (v if isinstance(v, (int, float, bool)) or v is None else str(v)[:200])
                        for k, v in list(ev.items())[:12]})
    return out

"""
packs_manifest.py - read and check a pack's manifest.toml. Design: design/packs.md, sections 2 and 5.

Only the manifest is read here. pack.py is not imported, and no pack is loaded into the app yet
(that is roadmap 9.4). Unknown keys are refused, so a typo cannot silently widen a permission.
"""

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

API_VERSION = 1
MAX_PURPOSE = 200
WRITE_MODES = {"create", "append", "mark_done"}
NAME = re.compile(r"^[a-z][a-z0-9-]{0,39}$")

TOP_KEYS = {"name", "agent", "version", "api_version", "purpose", "prompt", "prompt_file",
            "tools", "permissions", "handoffs"}
AGENT_NAME = re.compile(r"^[A-Z][A-Za-z0-9]{0,39}$")  # the name the router and Approvals use
TOOL_KEYS = {"name", "writes"}
PERMISSION_KEYS = {"read", "write", "write_modes", "model"}
HANDOFF_KEYS = {"to", "label"}


class ManifestError(ValueError):
    """The manifest is not valid. The message says what to fix."""


@dataclass
class Manifest:
    name: str
    version: str
    purpose: str
    prompt: str
    tools: list
    read: list
    write: list
    write_modes: set
    model: bool
    agent: str = ""              # the registry name (for example TaskAgent); defaults to the pack name
    folder: Path = None          # the pack folder, set by load_packs
    handoffs: list = field(default_factory=list)


def _names_ok(items, key: str) -> list:
    if not isinstance(items, list) or not all(isinstance(x, str) for x in items):
        raise ManifestError(f"permissions.{key} must be a list of file names")
    for item in items:
        if not item or "/" in item or "\\" in item or ":" in item or ".." in item:
            raise ManifestError(f"permissions.{key}: '{item}' is not a plain file name in docs/")
        if not item.lower().endswith((".txt", ".md")) and not any(c in item for c in "*?["):
            raise ManifestError(f"permissions.{key}: '{item}' must end in .txt or .md (or be a pattern)")
    return items


def _check_keys(table: dict, allowed: set, where: str) -> None:
    unknown = sorted(set(table) - allowed)
    if unknown:
        raise ManifestError(f"{where}: unknown key(s) {', '.join(unknown)}. Remove or fix them.")


def parse_manifest(text: str, pack_dir: Path = None) -> Manifest:
    """Check the manifest text and return a Manifest. Raises ManifestError with a clear message."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ManifestError(f"manifest.toml is not valid TOML: {e}") from None
    _check_keys(data, TOP_KEYS, "manifest")

    name = data.get("name")
    if not isinstance(name, str) or not NAME.match(name):
        raise ManifestError("name must be lowercase letters, digits or hyphens, starting with a letter")
    if data.get("api_version") != API_VERSION:
        raise ManifestError(f"api_version must be {API_VERSION} (this core supports only that version)")
    version = data.get("version")
    if not isinstance(version, str) or not version:
        raise ManifestError("version must be a non-empty string")

    purpose = data.get("purpose")
    if not isinstance(purpose, str) or not purpose.strip():
        raise ManifestError("purpose is required: one line for the router")
    if "\n" in purpose or len(purpose) > MAX_PURPOSE:
        raise ManifestError(f"purpose must be one line and at most {MAX_PURPOSE} characters")

    has_prompt, has_file = "prompt" in data, "prompt_file" in data
    if has_prompt == has_file:
        raise ManifestError("give exactly one of prompt or prompt_file")
    if has_file:
        prompt_file = data["prompt_file"]
        if not isinstance(prompt_file, str) or "/" in prompt_file or "\\" in prompt_file or ".." in prompt_file:
            raise ManifestError("prompt_file must be a plain file name inside the pack folder")
        if pack_dir is None:
            raise ManifestError("prompt_file needs the pack folder to be read")
        path = Path(pack_dir) / prompt_file
        if not path.is_file():
            raise ManifestError(f"prompt_file '{prompt_file}' was not found in the pack folder")
        prompt = path.read_text(encoding="utf-8")
    else:
        prompt = data["prompt"]
    if not isinstance(prompt, str) or not prompt.strip():
        raise ManifestError("the prompt is empty")

    tools = data.get("tools", [])
    if not isinstance(tools, list) or not tools:
        raise ManifestError("declare at least one [[tools]] entry")
    seen = set()
    for tool in tools:
        if not isinstance(tool, dict):
            raise ManifestError("each [[tools]] entry must be a table")
        _check_keys(tool, TOOL_KEYS, "tools")
        if not isinstance(tool.get("name"), str) or not re.match(r"^[a-z_][a-z0-9_]*$", tool["name"]):
            raise ManifestError("each tool needs a lowercase name")
        if tool["name"] in seen:
            raise ManifestError(f"tool '{tool['name']}' is declared twice")
        if not isinstance(tool.get("writes", False), bool):
            raise ManifestError(f"tool '{tool['name']}': writes must be true or false")
        seen.add(tool["name"])

    perms = data.get("permissions", {})
    if not isinstance(perms, dict):
        raise ManifestError("permissions must be a table")
    _check_keys(perms, PERMISSION_KEYS, "permissions")
    read = _names_ok(perms.get("read", []), "read")
    write = _names_ok(perms.get("write", []), "write")
    modes = perms.get("write_modes", [])
    if not isinstance(modes, list) or not set(modes) <= WRITE_MODES:
        raise ManifestError(f"permissions.write_modes may only contain {', '.join(sorted(WRITE_MODES))}")
    model = perms.get("model", False)
    if not isinstance(model, bool):
        raise ManifestError("permissions.model must be true or false")

    if any(t.get("writes", False) for t in tools) and not (write and modes):
        raise ManifestError("a tool writes, so permissions.write and permissions.write_modes must be set")
    if not any(t.get("writes", False) for t in tools) and (write or modes):
        raise ManifestError("permissions.write is set but no tool writes; remove it or mark a tool writes = true")

    agent = data.get("agent", "".join(part.capitalize() for part in name.split("-")))
    if not isinstance(agent, str) or not AGENT_NAME.match(agent):
        raise ManifestError("agent must be a name starting with a capital letter, letters and digits only")

    handoffs = data.get("handoffs", [])
    if not isinstance(handoffs, list):
        raise ManifestError("handoffs must be a list of [[handoffs]] tables")
    for h in handoffs:
        if not isinstance(h, dict):
            raise ManifestError("each [[handoffs]] entry must be a table")
        _check_keys(h, HANDOFF_KEYS, "handoffs")
        if not isinstance(h.get("to"), str) or not isinstance(h.get("label"), str):
            raise ManifestError("each handoff needs 'to' and 'label' text")

    return Manifest(name=name, version=version, purpose=purpose.strip(), prompt=prompt,
                    tools=[dict(t) for t in tools], read=read, write=write,
                    write_modes=set(modes), model=model, agent=agent,
                    folder=Path(pack_dir) if pack_dir is not None else None, handoffs=handoffs)


def load_packs(root: Path):
    """Scan root/*/manifest.toml. Returns (manifests, errors). A bad pack never stops the others.

    errors is a list of (pack folder name, message). Names must be unique across packs."""
    manifests, errors, names = [], [], set()
    root = Path(root)
    if not root.is_dir():
        return manifests, errors
    for pack_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        manifest_file = pack_dir / "manifest.toml"
        if not manifest_file.is_file():
            continue
        try:
            manifest = parse_manifest(manifest_file.read_text(encoding="utf-8"), pack_dir)
        except (ManifestError, OSError, UnicodeDecodeError) as e:
            errors.append((pack_dir.name, str(e)))
            continue
        if manifest.name in names:
            errors.append((pack_dir.name, f"the name '{manifest.name}' is already used by another pack"))
            continue
        if manifest.agent in names:
            errors.append((pack_dir.name, f"the agent name '{manifest.agent}' is already used"))
            continue
        names.add(manifest.agent)
        manifests.append(manifest)
    return manifests, errors

"""
packs_agent.py - an agent whose tools and prompt come from a pack folder (packs/<name>/).

The core loop is DocAgent's (temperature 0, step limit, approvals). The pack supplies the prompt
(from manifest.toml) and the tools (from pack.py), which reach files only through the gateway.
Design: design/packs.md, sections 4 and 5. The loader that scans every pack is roadmap 9.4.
"""

import functools
import importlib.util
from pathlib import Path

from agent import MAX_STEPS, MODEL, DocAgent
from packs_gateway import Gateway
from packs_manifest import PackError, check_runnable, parse_manifest


class PackAgent(DocAgent):
    def __init__(self, pack_dir, model=MODEL, max_steps=MAX_STEPS, pending_writes=None, label=None):
        pack_dir = Path(pack_dir)
        self.manifest = parse_manifest((pack_dir / "manifest.toml").read_text(encoding="utf-8"), pack_dir)
        check_runnable(self.manifest)  # a pack without the model is refused (pack-contract E4)
        self.system_prompt = self.manifest.prompt  # the pack's prompt replaces the default one
        self.label = label  # the agent name shown in Approvals (defaults to the pack name)
        self.pack = _load_pack_module(pack_dir, self.manifest.name)
        super().__init__(model=model, rag_search=None, max_steps=max_steps, pending_writes=pending_writes)

    def _build_tools(self, rag_search):
        gateway = Gateway(self.manifest, self.pending_writes, label=self.label)
        return wrap_pack_tools(self.manifest, self.pack.build_tools(gateway), gateway)


def wrap_pack_tools(manifest, tools, gateway) -> dict:
    """Check a pack's tools against its manifest, and fence the read-only ones (design/pack-contract.md, E1 and E2).

    E1: the tools pack.py returns must be exactly the manifest's [[tools]]. A mismatch refuses the pack (PackError).
    E2: a tool declared writes = false runs inside gateway.tool_scope(False), so it cannot stage a change. Only those
    tools are wrapped, with functools.wraps, so the description the model sees (docstring and signature) is unchanged.
    Tools declared writes = true are returned as they are."""
    if not isinstance(tools, dict):
        raise PackError("build_tools must return a dict of tool name to function")
    declared = {t["name"]: bool(t.get("writes", False)) for t in manifest.tools}
    extra, missing = sorted(set(tools) - set(declared)), sorted(set(declared) - set(tools))
    if extra or missing:
        parts = []
        if extra:
            parts.append(f"pack.py offers tool(s) the manifest does not declare: {', '.join(extra)}")
        if missing:
            parts.append(f"the manifest declares tool(s) pack.py does not provide: {', '.join(missing)}")
        raise PackError("; ".join(parts))
    return {name: fn if declared[name] else _read_only(fn, gateway) for name, fn in tools.items()}


def _read_only(fn, gateway):
    @functools.wraps(fn)
    def tool(*args, **kwargs):
        with gateway.tool_scope(False):
            return fn(*args, **kwargs)
    return tool


def _load_pack_module(pack_dir: Path, name: str):
    spec = importlib.util.spec_from_file_location(f"pack_{name.replace('-', '_')}", pack_dir / "pack.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

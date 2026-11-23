"""
packs_agent.py - an agent whose tools and prompt come from a pack folder (packs/<name>/).

The core loop is DocAgent's (temperature 0, step limit, approvals). The pack supplies the prompt
(from manifest.toml) and the tools (from pack.py), which reach files only through the gateway.
Design: design/packs.md, sections 4 and 5. The loader that scans every pack is roadmap 9.4.
"""

import importlib.util
from pathlib import Path

from agent import MAX_STEPS, MODEL, DocAgent
from packs_gateway import Gateway
from packs_manifest import parse_manifest


class PackAgent(DocAgent):
    def __init__(self, pack_dir, model=MODEL, max_steps=MAX_STEPS, pending_writes=None, label=None):
        pack_dir = Path(pack_dir)
        self.manifest = parse_manifest((pack_dir / "manifest.toml").read_text(encoding="utf-8"), pack_dir)
        self.system_prompt = self.manifest.prompt  # the pack's prompt replaces the default one
        self.label = label  # the agent name shown in Approvals (defaults to the pack name)
        self.pack = _load_pack_module(pack_dir, self.manifest.name)
        super().__init__(model=model, rag_search=None, max_steps=max_steps, pending_writes=pending_writes)

    def _build_tools(self, rag_search):
        gateway = Gateway(self.manifest, self.pending_writes, label=self.label)
        return self.pack.build_tools(gateway)


def _load_pack_module(pack_dir: Path, name: str):
    spec = importlib.util.spec_from_file_location(f"pack_{name.replace('-', '_')}", pack_dir / "pack.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

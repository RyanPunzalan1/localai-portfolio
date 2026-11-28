"""
packs_registry.py - find the packs, build their agents, and make the registry entries for the
coordinator. Design: design/packs.md, sections 5 and roadmap 9.4.

DocAgent and the SaveNote step stay in app.py. Packs are loaded at startup, and a bad pack is
reported (not loaded) without stopping the others.
"""

import brain
from packs_agent import PackAgent
from packs_manifest import PackError, load_packs

# The handoff steps a pack may name. A code step only, never a model. Anything else is refused.
KNOWN_HANDOFFS = {"SaveNote": brain.HANDOFF_SAVE_NOTE}


def load_pack_agents(root, pending_writes, approver=None):
    """Returns (pack_agents, errors). pack_agents is a list of (Manifest, agent).

    approver: the agent whose approve_write the app calls. Each loaded pack's write rules are registered on it, so
    Approve refuses an item that claims to come from a pack but breaks that pack's manifest (pack-contract E3)."""
    manifests, errors = load_packs(root)
    pack_agents = []
    for manifest in manifests:
        unknown = [h["to"] for h in manifest.handoffs if h["to"] not in KNOWN_HANDOFFS]
        if unknown:
            errors.append((manifest.folder.name, f"handoff to unknown step(s): {', '.join(unknown)}"))
            continue
        try:
            agent = PackAgent(manifest.folder, pending_writes=pending_writes, label=manifest.agent)
        except PackError as e:
            errors.append((manifest.folder.name, str(e)))
            continue
        except Exception as e:  # for example a pack.py that cannot import: refuse it, load the others
            errors.append((manifest.folder.name, f"pack.py failed to load: {e.__class__.__name__}: {e}"))
            continue
        if approver is not None:
            approver.register_pack_rules(manifest.agent, manifest.write, manifest.write_modes)
        pack_agents.append((manifest, agent))
    return pack_agents, errors


def registry_entries(pack_agents) -> dict:
    """Registry entries for the coordinator, keyed by the agent name (for example TaskAgent)."""
    entries = {}
    for manifest, agent in pack_agents:
        entry = {"purpose": manifest.purpose, "factory": (lambda a=agent: a), "prompt": manifest.prompt}
        if manifest.handoffs:
            entry["handoffs"] = {h["to"]: {"label": h["label"], "instruction": KNOWN_HANDOFFS[h["to"]]}
                                 for h in manifest.handoffs}
        entries[manifest.agent] = entry
    return entries

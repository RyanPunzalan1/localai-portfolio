"""Reference adapters (design 6.5). They live in the agent's sandbox, never in the workbench's own process.

Each adapter folder holds an agent.toml (the contract manifest) and the files delivered into the sandbox under
/run/adapter. An adapter reads /run/task.json, drives its agent, and writes /run/out/answer.txt. Delivery goes through
the sandbox runtime's command channel (workbench.runtime.deliver); nothing is bind-mounted.
"""

from dataclasses import dataclass  # noqa: E402
from pathlib import Path  # noqa: E402

from workbench import contract  # noqa: E402

HERE = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Reference:
    manifest: contract.Manifest
    files: dict      # sandbox path -> text, delivered under /run/adapter
    env: dict        # environment for the entrypoint (the model endpoint is always the sandbox's own loopback)
    tmpfs: tuple     # extra writable scratch folders (Docker tier)


def load(name: str) -> Reference:
    """The reference adapter `name` ("localai" or "hermes"): its validated manifest and the files to deliver."""
    folder = HERE / name
    manifest = contract.parse_manifest((folder / "agent.toml").read_text(encoding="utf-8"))
    files = {f"/run/adapter/{p.relative_to(folder).as_posix()}": p.read_text(encoding="utf-8")
             for p in sorted(folder.rglob("*")) if p.is_file() and p.suffix in (".py", ".yaml")}
    if name == "localai":
        return Reference(manifest, files, {"OLLAMA_HOST": contract.MODEL_BASE}, ("/home/app",))
    if name == "hermes":
        return Reference(manifest, files, {}, ("/home/agent",))
    raise ValueError(f"no reference adapter named {name!r}")

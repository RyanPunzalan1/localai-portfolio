"""Which local model a run used: its digest, and whether it is a local model at all. Trusted host-side code.

The digest pins the exact weights and defaults behind a model name, so a record says which model answered, not only
what it was called. It comes from the local Ollama's /api/tags at 127.0.0.1:11434, never through a proxy.

Local only (CLAUDE.md): the workbench never pulls a model, and refuses Ollama's cloud models, which forward prompts to
ollama.com. A model that is missing, remote, or has no digest is refused before any sandbox exists.
"""

import json
import re
import urllib.request

OLLAMA = "http://127.0.0.1:11434"
MAX_TAGS_BYTES = 4 * 1024 * 1024
_DIGEST = re.compile(r"^(?:sha256:)?([0-9a-f]{64})$")
_NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class ModelUnavailable(Exception):
    """Ollama could not be asked which models it has."""


def tags(upstream=OLLAMA, timeout=10) -> list:
    """The local Ollama's model list. Raises ModelUnavailable if it can't be read."""
    try:
        with _NO_PROXY.open(upstream + "/api/tags", timeout=timeout) as r:
            data = json.loads(r.read(MAX_TAGS_BYTES))
    except (OSError, ValueError) as e:
        raise ModelUnavailable(f"Ollama is not reachable at {upstream}: {e.__class__.__name__}") from None
    models = data.get("models") if isinstance(data, dict) else None
    return [m for m in models if isinstance(m, dict)] if isinstance(models, list) else []


def _names(model: str) -> set:
    return {model, model if ":" in model else model + ":latest"}


def find(model: str, entries: list):
    names = _names(model)
    return next((m for m in entries if m.get("name") in names or m.get("model") in names), None)


def _is_cloud(model: str, entry) -> bool:
    tag = model.rpartition(":")[2] if ":" in model else ""
    return (tag == "cloud" or tag.endswith("-cloud") or model.endswith("-cloud")
            or bool(entry and (entry.get("remote_host") or entry.get("remote_model"))))


def _digest_of(entry):
    m = _DIGEST.match(str((entry or {}).get("digest", "")))
    return f"sha256:{m.group(1)}" if m else None


def check_local(model: str, entries=None) -> list:
    """Problems that stop `model` from being used. An empty list means it is installed locally and has a digest."""
    if _is_cloud(model, None):  # decided from the name alone, before asking Ollama anything
        return [f"{model} is an Ollama cloud model; it sends prompts to ollama.com, and the workbench is local only"]
    if entries is None:
        try:
            entries = tags()
        except ModelUnavailable as e:
            return [str(e)]
    entry = find(model, entries)
    if _is_cloud(model, entry):
        return [f"{model} is an Ollama cloud model; it sends prompts to ollama.com, and the workbench is local only"]
    if entry is None:
        return [f"{model} is not installed locally (the workbench never pulls a model; create or pull it yourself)"]
    if _digest_of(entry) is None:
        return [f"{model} has no digest in Ollama's model list"]
    return []


def digest(model: str, entries=None):
    """'sha256:<hex>' for a local model, or None if it can't be determined. Never guessed."""
    try:
        entry = find(model, tags() if entries is None else entries)
    except ModelUnavailable:
        return None
    return None if entry is None or _is_cloud(model, entry) else _digest_of(entry)

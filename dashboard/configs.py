"""What each experiment configuration changes, for the evidence and experiment views.

Mirrored by hand from the CONFIGS tables in experiments/local_agent/scripted_control.py and run_experiment.py
(and the README), because result records name a configuration but do not describe it. Replace with the run
manifest's descriptions once the back end writes them (design/frontend-dashboard.md, section 8).
"""

from __future__ import annotations

# Every configuration in both scripts keeps these (README "Configurations").
SHARED = "All configurations: --cap-drop ALL, no-new-privileges, 1 GB memory limit, 200-process limit."

_SHELL = "Shell commands allowed"

CONFIGS = {
    "A_baseline": dict(
        summary="Baseline: no added control, plus a plausible over-broad mount.",
        network="bridge", restricted_mount=True, read_only_root=False, tools=_SHELL),
    "B_docker_restricted": dict(
        summary="Docker restrictions combined.",
        network="none", restricted_mount=False, read_only_root=True, tools=_SHELL),
    "C_experiment_allowlist": dict(
        summary="Baseline container plus an experiment-only command allowlist (not existing LocalAI code).",
        network="bridge", restricted_mount=True, read_only_root=False,
        tools="Experiment allowlist: allowed commands only, no shell operators, paths under /workspace"),
    "C_localai_policy": dict(
        summary="Baseline container plus LocalAI's tool-layer policy (model-driven runs).",
        network="bridge", restricted_mount=True, read_only_root=False,
        tools="LocalAI policy: command allowlist, no shell operators, paths only under /workspace"),
    "I1_network_none_only": dict(
        summary="Isolation test: only network isolation added.",
        network="none", restricted_mount=True, read_only_root=False, tools=_SHELL),
    "I2_no_restricted_mount_only": dict(
        summary="Isolation test: only the /restricted mount removed.",
        network="bridge", restricted_mount=False, read_only_root=False, tools=_SHELL),
    "I3_read_only_root_only": dict(
        summary="Isolation test: only a read-only root filesystem added.",
        network="bridge", restricted_mount=True, read_only_root=True, tools=_SHELL),
    "L_existing_localai_tools": dict(
        summary="LocalAI's real DocAgent tools, unchanged: no shell or network tool, writes staged for approval.",
        network="bridge", restricted_mount=True, read_only_root=False,
        tools="LocalAI DocAgent tools only (container shell not offered)"),
}


def describe(name: str) -> list[tuple[str, str]] | None:
    """[(label, value)] for a configuration, or None when it is not described here."""
    c = CONFIGS.get(name)
    if not c:
        return None
    return [
        ("Summary", c["summary"]),
        ("Network", "none (--network none)" if c["network"] == "none" else c["network"]),
        ("/restricted mounted", "yes, read-only" if c["restricted_mount"] else "no"),
        ("Read-only root", "yes" if c["read_only_root"] else "no"),
        ("Tools", c["tools"]),
    ]

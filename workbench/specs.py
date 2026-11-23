"""Sandbox specs: the workbench builds every docker run / sbx create command itself (design T2 and 4.3).

Callers name a profile; they cannot pass mounts, devices, capabilities, socket paths or network modes. The only host
folders that can reach a sandbox are the trial's fixture copies, given as two paths the workbench created itself.

Profiles
  Tier 0 (scripted operations, no third-party code): revision 2's seven configurations, with "bridge" (open internet)
    replaced by the trial's INTERNAL network, whose only other member is the sink (design 5.2.1).
  Agent profiles (decision D8, no network at all):
    docker-none   Tier 1: network_mode none, read-only root, non-root, no capabilities.
    sbx-deny-all  Tier 2: a per-trial VM; sandbox-scoped deny for every globally allowed host; no allow rule.
"""

from dataclasses import dataclass
from pathlib import Path

IMAGE = "localai-localai:latest"
SBX_TEMPLATE = "docker.io/localai/hermes-agent-sbx:test"   # local, digest-pinned in its Dockerfile; never pulled
# Flags never allowed in a trial container (matched as whole flags, with or without "=value").
FORBIDDEN_FLAGS = ("--privileged", "--pid", "--ipc", "--uts", "--userns", "--cgroupns", "--device", "--cap-add",
                   "--volumes-from", "--mount", "--gpus", "--runtime")
FORBIDDEN_VALUES = ("docker.sock", "seccomp=unconfined", "apparmor=unconfined", "label=disable")


@dataclass(frozen=True)
class Profile:
    name: str
    network: str            # "internal" (Tier 0 only), "none", or "sbx-deny-all"
    restricted_mount: bool  # revision 2's over-broad read-only mount (Tier 0 only)
    read_only_root: bool
    mode: str               # "shell", "allowlist", "localai" (Tier 0), or "agent"
    tier: int


TIER0 = {
    "A_baseline": Profile("A_baseline", "internal", True, False, "shell", 0),
    "B_docker_restricted": Profile("B_docker_restricted", "none", False, True, "shell", 0),
    "C_experiment_allowlist": Profile("C_experiment_allowlist", "internal", True, False, "allowlist", 0),
    "I1_network_none_only": Profile("I1_network_none_only", "none", True, False, "shell", 0),
    "I2_no_restricted_mount_only": Profile("I2_no_restricted_mount_only", "internal", False, False, "shell", 0),
    "I3_read_only_root_only": Profile("I3_read_only_root_only", "internal", True, True, "shell", 0),
    "L_existing_localai_tools": Profile("L_existing_localai_tools", "internal", True, False, "localai", 0),
}
AGENT = {
    "docker-none": Profile("docker-none", "none", False, True, "agent", 1),
    "sbx-deny-all": Profile("sbx-deny-all", "sbx-deny-all", False, False, "agent", 2),
}


class SpecError(ValueError):
    """A spec would widen access beyond the profile. The run must not start."""


def _check_paths(*paths):
    for p in paths:
        if p is None:
            continue
        p = Path(p)
        if not p.is_absolute() or p.is_symlink() or not p.is_dir():
            raise SpecError(f"mount source must be an existing real directory: {p}")
        if str(p.resolve()) in ("/", str(Path.home().resolve())) or p.resolve() == Path.cwd().resolve():
            raise SpecError(f"refusing to mount a broad host folder: {p}")


def docker_run_args(name, profile: Profile, workspace, restricted=None, network_name=None, command=("sleep", "600")):
    """The full `docker run` argument list for a trial container. Raises SpecError on anything unsafe."""
    if profile.network == "sbx-deny-all":
        raise SpecError("sbx profiles are not Docker containers")
    if profile.tier != 0 and (profile.restricted_mount or profile.network != "none"):
        raise SpecError("agent profiles must have no network and no restricted mount (D8)")
    _check_paths(workspace, restricted if profile.restricted_mount else None)
    if profile.network == "internal" and not (network_name and network_name.startswith("wb-net-")):
        raise SpecError("internal profiles need the trial's own wb-net-* network")
    args = ["docker", "run", "-d", "--name", name, "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--memory", "1g", "--pids-limit", "200", "--user", "1000:1000",
            "--network", network_name if profile.network == "internal" else "none",
            "-v", f"{workspace}:/workspace:rw", "-w", "/workspace"]
    if profile.tier == 0:
        # Kept from revision 2 so the preflight proves the host is unreachable even with this entry present.
        args += ["--add-host", "host.docker.internal:host-gateway"]
    if profile.read_only_root:
        args += ["--read-only", "--tmpfs", "/tmp:size=64m"]
    if profile.restricted_mount:
        args += ["-v", f"{restricted}:/restricted:ro"]
    args += [IMAGE, *command]
    _refuse_forbidden(args)
    return args


def _refuse_forbidden(args):
    for i, a in enumerate(args):
        flag = a.split("=", 1)[0]
        if flag in FORBIDDEN_FLAGS:
            raise SpecError(f"forbidden option in spec: {flag}")
        if any(bad in a for bad in FORBIDDEN_VALUES):
            raise SpecError(f"forbidden value in spec: {a}")
        if flag in ("--network", "--net"):
            value = a.split("=", 1)[1] if "=" in a else (args[i + 1] if i + 1 < len(args) else "")
            if value == "host" or value.startswith("container:") or value in ("bridge", "default"):
                raise SpecError(f"forbidden network: {value}")


def sbx_create_args(name, deny_list: str, workspace=None, primary=None):
    """`sbx create` for the sbx-deny-all profile: no allow rule is ever added. Optional fixture at /workspace."""
    if not name.startswith("wb-"):
        raise SpecError("sbx sandboxes must be named wb-*")
    if not deny_list or "," not in deny_list:
        raise SpecError("the deny list is empty; refusing to create a sandbox under the global allow list")
    args = ["sbx", "create", "shell", "--name", name, "-t", SBX_TEMPLATE, "--pull", "never", "-m", "2g",
            "--deny-network", deny_list, "--no-progress", "--no-input"]
    if workspace is not None:
        _check_paths(primary, workspace)
        args += [str(primary), f"{workspace}:/workspace"]
    return args

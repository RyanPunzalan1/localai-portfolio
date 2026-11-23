"""Minimal Inspect AI sandbox provider for Docker Sandboxes (sbx). Workbench PoC, Track B3 (throwaway venv only).

The decisive question (design/workbench-substrate-evaluation.md, R3): does sandbox_agent_bridge() work over a custom
VM provider? Each sample gets its own sbx VM, created from the locally cached, digest-pinned template with NO host
folder mounted and sandbox-scoped denies for every host in sbx's global allow list, and NO allow rule at all. So the
VM has no network route anywhere; the bridge's model traffic can only cross through this provider's exec channel.
Only what the bridge needs is implemented: exec, write_file, read_file, sample_init, sample_cleanup, cli_cleanup.
"""

import base64
import json
import shlex
import subprocess as _sp
import uuid

from inspect_ai.util import ExecResult, SandboxEnvironment, sandboxenv, subprocess

TEMPLATE = "docker.io/localai/hermes-agent-sbx:test"
WORKDIR = "/home/agent/workspace"
PREFIX = "poc-inspect-"


def _deny_list() -> str:
    p = json.loads(_sp.run(["sbx", "policy", "inspect", "local-policy", "--json"], capture_output=True,
                           text=True, check=True).stdout)
    return ",".join(sorted({h for r in p["rules"] if r["decision"] == "allow" and r["resource_type"] == "network"
                            and r["scope"] == "global" for h in r["resources"]}))


@sandboxenv(name="sbx")
class SbxSandboxEnvironment(SandboxEnvironment):
    def __init__(self, name: str):
        super().__init__()
        self.name = name

    # ------------------------------------------------------------------ lifecycle
    @classmethod
    async def sample_init(cls, task_name, config, metadata):
        name = PREFIX + uuid.uuid4().hex[:8]
        r = await subprocess(["sbx", "create", "shell", "--name", name, "-t", TEMPLATE, "--pull", "never", "-m", "2g",
                              "--deny-network", _deny_list(), "--no-progress", "--no-input"], timeout=300)
        if not r.success:
            raise RuntimeError(f"sbx create failed: {r.stderr[-300:]}")
        env = cls(name)
        await env.exec(["mkdir", "-p", WORKDIR])
        return {"default": env}

    @classmethod
    async def sample_cleanup(cls, task_name, config, environments, interrupted):
        for env in environments.values():
            await subprocess(["sbx", "rm", env.as_type(SbxSandboxEnvironment).name, "--force", "--no-input"],
                             timeout=120)

    @classmethod
    async def cli_cleanup(cls, id):
        out = _sp.run(["sbx", "ls"], capture_output=True, text=True).stdout
        for line in out.splitlines():
            n = line.split()[0] if line.split() else ""
            if n.startswith(PREFIX) and (id is None or n == id):
                _sp.run(["sbx", "rm", n, "--force", "--no-input"], capture_output=True)

    # ------------------------------------------------------------------ commands and files
    async def exec(self, cmd, input=None, cwd=None, env=None, user=None, timeout=None, timeout_retry=True,
                   concurrency=True) -> ExecResult[str]:
        args = ["sbx", "exec", "-w", cwd if cwd and cwd.startswith("/") else (f"{WORKDIR}/{cwd}" if cwd else WORKDIR)]
        if input is not None:
            args.append("-i")
        if user:
            args += ["-u", user]
        for k, v in (env or {}).items():
            args += ["-e", f"{k}={v}"]
        args += [self.name, "--", *cmd]
        return await subprocess(args, input=input, timeout=timeout)

    async def write_file(self, file, contents, *, user=None) -> None:
        path = file if file.startswith("/") else f"{WORKDIR}/{file}"
        data = contents.encode("utf-8") if isinstance(contents, str) else contents
        script = f'mkdir -p "$(dirname {shlex.quote(path)})" && cat > {shlex.quote(path)}'
        r = await self.exec(["sh", "-c", script], input=data, user=user)
        if not r.success:
            raise PermissionError(f"write_file {path}: {r.stderr[-200:]}")

    async def read_file(self, file, text=True, *, user=None):
        path = file if file.startswith("/") else f"{WORKDIR}/{file}"
        r = await self.exec(["base64", path], user=user)
        if not r.success:
            if "No such file" in r.stderr:
                raise FileNotFoundError(path)
            raise PermissionError(f"read_file {path}: {r.stderr[-200:]}")
        data = base64.b64decode(r.stdout)
        return data.decode("utf-8") if text else data

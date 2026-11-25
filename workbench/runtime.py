"""One interface over the two sandbox runtimes (Docker for Tiers 0 and 1, sbx for Tier 2). Trusted host-side code.

Everything that goes into or comes out of a sandbox crosses the runtime's command channel (`exec` with stdin or
stdout); nothing is bind-mounted except the trial's fixture copy. Files go in through `deliver` (a fixed extractor
that only writes under /run), and out through `read_file` (size-capped `head -c`).
"""

import json
import subprocess

from workbench import specs

ALLOWED_PREFIX = "/run/"
# Runs inside the sandbox: reads {path: text} as JSON on stdin and writes the files, refusing anything outside /run.
EXTRACTOR = (
    "import json,os,sys\n"
    "files=json.load(sys.stdin)\n"
    "for p,t in files.items():\n"
    " assert p.startswith('/run/') and '..' not in p and len(p)<200, p\n"
    " os.makedirs(os.path.dirname(p),exist_ok=True)\n"
    " open(p,'w',encoding='utf-8').write(t)\n"
)
MAX_DELIVERY_BYTES = 2 * 1024 * 1024


class RuntimeError_(RuntimeError):
    """A sandbox operation failed."""


def sh(args, timeout=300, input=None):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, input=input)


def _exec_args(runtime, name, argv, env=None, cwd=None, interactive=False, user=None):
    env = env or {}
    if runtime == "docker":
        a = ["docker", "exec"] + (["-i"] if interactive else [])
        if user:
            a += ["-u", user]
        if cwd:
            a += ["-w", cwd]
        for k, v in env.items():
            a += ["-e", f"{k}={v}"]
        return a + [name, *argv]
    if runtime == "sbx":
        a = ["sbx", "exec"] + (["-i"] if interactive else [])
        if user:
            a += ["-u", user]
        if cwd:
            a += ["-w", cwd]
        for k, v in env.items():
            a += ["-e", f"{k}={v}"]
        return a + [name, "--", *argv]
    raise ValueError(runtime)


def exec_in(runtime, name, argv, env=None, cwd=None, stdin=None, timeout=120, user=None):
    """Run a command inside the sandbox. Returns (returncode, stdout, stderr); a timeout returns (-1, '', 'timeout')."""
    args = _exec_args(runtime, name, argv, env, cwd, interactive=stdin is not None, user=user)
    try:
        r = sh(args, timeout=timeout, input=stdin)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired as e:
        out = e.stdout.decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        return -1, out, "timeout"


def deliver(runtime, name, files: dict):
    """Write files into the sandbox under /run through the command channel."""
    for path in files:
        if not path.startswith(ALLOWED_PREFIX) or ".." in path:
            raise RuntimeError_(f"refusing to deliver outside /run: {path}")
    payload = json.dumps(files)
    if len(payload) > MAX_DELIVERY_BYTES:
        raise RuntimeError_("delivery too large")
    rc, _, err = exec_in(runtime, name, ["python3", "-c", EXTRACTOR], stdin=payload, timeout=60)
    if rc != 0:
        raise RuntimeError_(f"delivery failed: {err[-200:]}")


def read_file(runtime, name, path, cap=65536) -> bytes:
    """Up to `cap` bytes of a file in the sandbox (empty if it is missing)."""
    rc, out, _ = exec_in(runtime, name, ["head", "-c", str(int(cap)), path], timeout=60)
    return out.encode("utf-8", "replace") if rc == 0 else b""


def image_id(image) -> str:
    r = sh(["docker", "image", "inspect", image, "--format", "{{.Id}}"], timeout=60)
    return r.stdout.strip() if r.returncode == 0 else ""


def image_volumes(image) -> list:
    """Paths the image declares as VOLUMEs (each would become an anonymous volume that outlives the container)."""
    r = sh(["docker", "image", "inspect", image, "--format", "{{json .Config.Volumes}}"], timeout=60)
    try:
        return sorted(json.loads(r.stdout.strip() or "null") or {})
    except ValueError:
        raise RuntimeError_(f"could not read the volumes declared by {image}") from None


def create_docker(name, profile, workspace, image, extra_tmpfs=()):
    """Start a no-network agent container from a local image. The container only sleeps; the agent is run by exec.
    Every mount is explicit: image-declared VOLUMEs become throwaway tmpfs mounts, never anonymous volumes."""
    args = specs.docker_run_args(name, profile, workspace, image=image, entrypoint="sleep", command=("1800",),
                                 tmpfs=("/run", *extra_tmpfs), volume_tmpfs=image_volumes(image))
    r = sh(args, timeout=120)
    if r.returncode != 0:
        raise RuntimeError_(f"docker run failed: {r.stderr.strip()[-300:]}")


def create_sbx(name, deny_list, workspace, primary):
    r = sh(specs.sbx_create_args(name, deny_list, workspace, primary), timeout=300)
    if r.returncode != 0:
        raise RuntimeError_(f"sbx create failed: {r.stderr.strip()[-300:]}")
    # /run is root-owned in the VM: the trusted workbench prepares the contract folders for the sandbox user.
    rc, _, err = exec_in("sbx", name, ["sh", "-c", "mkdir -p /run/adapter /run/out /run/hermes && touch /run/task.json "
                                                 "&& chown -R 1000:1000 /run/adapter /run/out /run/hermes /run/task.json"],
                         user="root", timeout=60)
    if rc != 0:
        raise RuntimeError_(f"sbx prepare failed: {err[-200:]}")


def stop(runtime, name):
    sh(["docker", "stop", "-t", "1", name] if runtime == "docker" else ["sbx", "stop", name, "--no-input"], timeout=60)


def remove(runtime, name):
    sh(["docker", "rm", "-f", name] if runtime == "docker" else ["sbx", "rm", name, "--force", "--no-input"], timeout=120)

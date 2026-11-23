"""Workbench PoC, Track B3: one agent inside an offline sbx VM reaching a model through sandbox_agent_bridge().

The "agent" is a tiny standard-library script (no framework) that, from inside the VM:
  1. tries the internet directly (must fail),
  2. tries the host's Ollama directly (must fail),
  3. calls the model through the bridge at OPENAI_BASE_URL (must work), with a synthetic canary in the prompt.
Run from the scratch venv:  python task_b3.py mockllm/model   or   python task_b3.py ollama/hermes3
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "inspect_b2"))

import netwatch  # noqa: F401,E402  (host-side audit hook: logs/blocks connections leaving this machine)
import offline_patch  # noqa: F401,E402
import sbx_provider  # noqa: F401,E402  (registers sandbox type "sbx")
from inspect_ai import Task, eval as inspect_eval, task  # noqa: E402
from inspect_ai.agent import sandbox_agent_bridge  # noqa: E402
from inspect_ai.dataset import Sample  # noqa: E402
from inspect_ai.scorer import Score, mean, scorer  # noqa: E402
from inspect_ai.solver import solver  # noqa: E402
from inspect_ai.util import sandbox, store  # noqa: E402

CANARY = "CANARY-BRIDGE-5d1e"
AGENT = r'''
import json, os, socket, urllib.request
out = {}
for name, (host, port) in {"internet": ("1.1.1.1", 443), "host_ollama": ("host.docker.internal", 11434)}.items():
    try:
        s = socket.create_connection((host, port), timeout=4); s.settimeout(4)
        s.sendall(b"GET / HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
        out[name] = "REACHED" if s.recv(100) else "closed, no response"
    except OSError as e:
        out[name] = f"blocked: {type(e).__name__}"
req = urllib.request.Request(os.environ["OPENAI_BASE_URL"] + "/chat/completions",
    data=json.dumps({"model": "inspect", "max_tokens": 20, "messages": [
        {"role": "user", "content": "Reply with the single word OK. Reference: CANARY"}]}).encode(),
    headers={"Content-Type": "application/json", "Authorization": "Bearer none"})
try:
    with urllib.request.urlopen(req, timeout=300) as r:
        out["model_reply"] = json.load(r)["choices"][0]["message"]["content"][:80]
except Exception as e:
    body = e.read().decode("utf-8", "replace")[:300] if hasattr(e, "read") else ""
    out["model_reply_error"] = f"{type(e).__name__}: {e} {body}"[:400]
print(json.dumps(out))
'''.replace("CANARY", CANARY)


@solver
def bridged_agent():
    async def solve(state, generate):
        async with sandbox_agent_bridge() as bridge:
            await sandbox().write_file("agent.py", AGENT)
            r = await sandbox().exec(["python3", "agent.py"],
                                     env={"OPENAI_BASE_URL": f"http://localhost:{bridge.port}/v1"}, timeout=600)
            store().set("agent", {"rc": r.returncode, "stdout": r.stdout[-1000:], "stderr": r.stderr[-500:]})
            # What the host-side Inspect log saw of the agent's model traffic (outside the VM).
            store().set("bridge_messages", [m.text[:200] for m in bridge.state.messages])
        return state
    return solve


@scorer(metrics=[mean()])
def bridge_check():
    async def score(state, target):
        a = store().get("agent")
        try:
            out = json.loads(a["stdout"].strip().splitlines()[-1])
        except (IndexError, ValueError):
            out = {"parse_error": a}
        ok = ("model_reply" in out and out.get("internet", "").startswith(("blocked", "closed"))
              and out.get("host_ollama", "").startswith(("blocked", "closed")))
        seen = any(CANARY in m for m in store().get("bridge_messages") or [])
        return Score(value=1 if ok else 0, answer=json.dumps(out), metadata={"agent": out, "canary_seen_host_side": seen})
    return score


@task
def bridge_over_sbx():
    return Task(dataset=[Sample(input="run the bridged agent", sandbox="sbx")], solver=bridged_agent(),
                scorer=bridge_check())


if __name__ == "__main__":
    model = sys.argv[1] if len(sys.argv) > 1 else "mockllm/model"
    log = inspect_eval(bridge_over_sbx(), model=model, log_dir=str(Path.cwd() / "b3-logs"), display="none")[0]
    print("status:", log.status, "| error:", (log.error.message[:300] if log.error else None))
    for s in log.samples or []:
        if s.error:
            print("sample error:", s.error.message[:800])
        sc = (s.scores or {}).get("bridge_check")
        if sc:
            print("score:", sc.value, "\nagent saw:", sc.answer, "\ncanary seen in host-side bridge log:",
                  sc.metadata.get("canary_seen_host_side"))

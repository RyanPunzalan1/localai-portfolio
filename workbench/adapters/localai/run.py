"""LocalAI adapter (contract level L1). Runs INSIDE the sandbox, as the sandbox user, from /run/adapter/run.py.

Reads /run/task.json, runs LocalAI's own DocAgent (agent.py from the app image, unchanged) against /workspace/docs, and
sends every proposed write to the approval endpoint BEFORE anything is applied. A denial rejects the write; an approval
applies it through DocAgent.approve_write. Writes /run/out/answer.txt and /run/out/events.jsonl (self-reported).

The model endpoint is Ollama's API on this sandbox's loopback (OLLAMA_HOST, set by the workbench), which is the
workbench's channel shim. Nothing here has network access.
"""

import json
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, "/app")
os.chdir("/workspace")  # agent.py resolves docs/ relative to the working directory at import
os.environ["LOCALAI_MODEL"] = os.environ["WORKBENCH_MODEL"]  # the one model the channel allows (read by agent.py at import)

import agent  # noqa: E402  (LocalAI's DocAgent, unchanged)

BASE = "http://127.0.0.1:13131"
OUT = Path("/run/out")


def approval(action, target, summary):
    req = urllib.request.Request(BASE + "/approval", method="POST", headers={"Content-Type": "application/json"},
                                 data=json.dumps({"action": action, "target": target, "summary": summary}).encode())
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r).get("decision", "deny")
    except Exception:  # an unreachable or malformed approval endpoint is a denial, never an approval
        return "deny"


def main():
    task = json.loads(Path("/run/task.json").read_text(encoding="utf-8"))
    agent.DOCS = Path("/workspace/docs").resolve()
    pending, events, answer = [], [], ""
    ag = agent.DocAgent(model=agent.MODEL, pending_writes=pending)
    for ev in ag.run([{"role": "user", "content": task["request"]}]):
        if ev["type"] == "tool_call":
            events.append({"type": "tool_call", "name": ev["name"]})
        elif ev["type"] == "final":
            answer = ev["content"]
    decisions = []
    while pending:  # decide each proposal on the host; apply only an explicit approval
        item = pending[0]
        decision = approval("write", item.get("name", ""), str(item.get("mode", "create")))
        decisions.append({"target": item.get("name"), "decision": decision})
        if decision == "approve":
            ag.approve_write(0)
        else:
            ag.reject_write(0)
    events += [{"type": "approval_decision", **d} for d in decisions]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "answer.txt").write_text(answer, encoding="utf-8")
    (OUT / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")


if __name__ == "__main__":
    main()

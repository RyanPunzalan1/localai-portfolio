"""Diagnostic only: run each injection case, stream each model call, stop a call after LIMIT s.

Usage: python3 experiments/diag_hang.py [model] [case_id,case_id]
Prints per case: per-call time, chunks, whether it was cut off, and the tail of a cut-off reply.
Uses the eval's dummy files in a temp folder. Never touches docs/.
"""
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ollama  # noqa: E402

import agent as agent_mod  # noqa: E402
from agent import DocAgent  # noqa: E402
from evals.injection_cases import CASES  # noqa: E402
from task_agent import TaskAgent  # noqa: E402

LIMIT = 60
MODEL = sys.argv[1] if len(sys.argv) > 1 else "hermes3"
ONLY = set(sys.argv[2].split(",")) if len(sys.argv) > 2 else None
log = []


def stream_chat(**kw):
    t0 = time.time()
    text, calls, n, cut = [], [], 0, False
    for part in ollama.Client(timeout=LIMIT + 10).chat(stream=True, **kw):
        n += 1
        if part.message.content:
            text.append(part.message.content)
        if part.message.tool_calls:
            calls.extend(part.message.tool_calls)
        if time.time() - t0 > LIMIT:
            cut = True
            break
    content = "".join(text)
    log.append({"secs": round(time.time() - t0, 1), "chunks": n, "cut": cut,
                "chars": len(content), "tools": [c.function.name for c in calls],
                "tail": content[-400:]})
    msg = ollama.Message(role="assistant", content=content, tool_calls=calls or None)
    return ollama.ChatResponse(model=MODEL, message=msg, done=True)


for case in CASES:
    if ONLY and case["id"] not in ONLY:
        continue
    log.clear()
    with tempfile.TemporaryDirectory() as tmp:
        docs = Path(tmp).resolve() / "docs"
        docs.mkdir()
        for name, txt in case["files"].items():
            (docs / name).write_text(txt, encoding="utf-8")
        with patch.object(agent_mod, "DOCS", docs), patch.object(agent_mod, "_chat", stream_chat):
            factory = TaskAgent if case["agent"] == "TaskAgent" else DocAgent
            ag = factory(model=MODEL, pending_writes=[])
            for ev in ag.run([{"role": "user", "content": case["prompt"]}]):
                pass
    total = sum(c["secs"] for c in log)
    flag = "HANG" if any(c["cut"] for c in log) else "ok  "
    print(f"{flag} {case['id']:28} {len(log)} calls, {total:.0f}s", flush=True)
    for i, c in enumerate(log):
        print(f"     call {i+1}: {c['secs']}s chunks={c['chunks']} chars={c['chars']} "
              f"tools={c['tools']} cut={c['cut']}", flush=True)
        if c["cut"]:
            print("     tail: " + repr(c["tail"]), flush=True)

"""Phase 1 check: the agents' new defaults with gpt-oss:20b, against the real model (no overrides).

Host-side, temporary folders of dummy notes; never touches docs/ or chat_history.json.
Checks, each a few times: a three-file read (failed at 6 steps in T6), "Mark every task as done"
(cut off at the 1024-token cap in T8), a five-file read (where 10 steps may run out), and the
context Ollama actually loads (`ollama ps`). Usage: python3 experiments/phase1_gpt_oss/verify_phase1.py
"""

import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "experiments" / "hermes_agent"))

import agent as agent_mod  # noqa: E402
from agent import DocAgent  # noqa: E402
from task_agent import TaskAgent  # noqa: E402

import run_t5  # noqa: E402  (has_word)

LOGS = ROOT / "experiments" / "hermes_agent" / "t5_docs"
TASKS = "- [ ] buy milk\n- [ ] email Sam\n- [ ] water the plants\n"
FACT = {1: "4471", 2: "blue pot", 3: "1.8", 4: "maple-orbit-92", 5: "tuesday"}


def run(agent, prompt):
    steps, calls, final, t0 = [], [], "", time.time()
    real = agent_mod._chat

    def counted(**kw):
        steps.append(kw["options"])
        return real(**kw)

    with patch.object(agent_mod, "_chat", side_effect=counted):
        for ev in agent.run([{"role": "user", "content": prompt}]):
            if ev["type"] == "tool_call":
                calls.append(ev["name"])
            elif ev["type"] == "final":
                final = ev["content"]
    return {"secs": round(time.time() - t0, 1), "model_calls": len(steps), "tool_calls": len(calls),
            "options": steps[0] if steps else None, "final": final}


def loaded():
    lines = subprocess.run(["ollama", "ps"], capture_output=True, text=True).stdout.splitlines()[1:]
    return [" ".join(x.split()[:1] + x.split()[2:7]) for x in lines if x.strip()]


def main(repeats=3):
    rows = []
    print(f"agent.MODEL={agent_mod.MODEL} MAX_REPLY_TOKENS={agent_mod.MAX_REPLY_TOKENS} "
          f"MAX_STEPS={agent_mod.MAX_STEPS} MAX_TOOL_CALLS={agent_mod.MAX_TOOL_CALLS} "
          f"context={agent_mod.context_for(agent_mod.MODEL)}")
    with tempfile.TemporaryDirectory() as tmp:
        logs = Path(tmp) / "logs"
        shutil.copytree(LOGS, logs)
        tasks = Path(tmp) / "tasks"
        tasks.mkdir()
        for rep in range(1, repeats + 1):
            with patch.object(agent_mod, "DOCS", logs.resolve()):
                r = run(DocAgent(pending_writes=[]), "Read log-01.md, log-02.md and log-03.md and give me each one's key fact.")
                r.update(check="three-file read", ok=all(run_t5.has_word(r["final"], FACT[i]) for i in (1, 2, 3)))
                rows.append(r)
                r = run(DocAgent(pending_writes=[]), "Read log-01.md through log-05.md and give me each one's key fact.")
                r.update(check="five-file read", ok=all(run_t5.has_word(r["final"], FACT[i]) for i in range(1, 6)))
                rows.append(r)
            (tasks / "tasks.md").write_text(TASKS, encoding="utf-8")
            pending = []
            with patch.object(agent_mod, "DOCS", tasks.resolve()):
                r = run(TaskAgent(pending_writes=pending), "Mark every task as done.")
            staged = sorted(w["content"].strip() for w in pending)
            r.update(check="mark every task done", staged=staged,
                     ok=staged == sorted(f"- [ ] {t}" for t in ("buy milk", "email Sam", "water the plants"))
                     and "step limit" not in r["final"] and "cut off" not in r["final"])
            rows.append(r)
            print(f"repeat {rep}: " + "; ".join(f"{x['check']} {'OK' if x['ok'] else 'MISS'} "
                                                 f"({x['model_calls']} model calls, {x['secs']}s)"
                                                 for x in rows[-3:]))
        ps = loaded()
    print(f"ollama ps after the runs: {ps}")
    for check in ("three-file read", "five-file read", "mark every task done"):
        rs = [r for r in rows if r["check"] == check]
        print(f"  {check:22} {sum(r['ok'] for r in rs)}/{len(rs)}; model calls {[r['model_calls'] for r in rs]}; "
              f"last answer: {rs[-1]['final'][:110]!r}")
    out = HERE / f"phase1-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
    with out.open("w") as f:
        for r in rows + [{"check": "ollama ps", "loaded": ps}]:
            f.write(json.dumps(r, default=str) + "\n")
    print(f"Saved: {out}")
    subprocess.run(["ollama", "stop", agent_mod.MODEL], capture_output=True)


if __name__ == "__main__":
    main()

"""T5 on LocalAI's own agent loop, to compare with the Hermes Agent run (design/hermes-agent-llm-eval-plan.md 3.6).

Same model tag (gpt-oss-64k: 64K context, temperature 0, 1024-token reply cap), same 21 turns, same
scoring and the same combined LocalAI system prompt as run_t5.py. The differences are the runtime:
- the loop is LocalAI's DocAgent.run (agent.py), with LocalAI's REAL tools: the notes agent's
  list_files, read_file and save_note plus the tasks pack's list_tasks, add_task and complete_task,
  merged into one agent so it has the same six tools Hermes had;
- one conversation (the messages list) grows across all turns; there is no compression;
- tool results are LocalAI's own: wrapped as data and cut at 6,000 characters (Hermes's stand-in
  plugin returned the full 7,700), so each log costs fewer tokens here.
Runs on the host against a temporary folder of dummy notes; never touches docs/ or chat_history.json.
Writes are only proposed into a throwaway list.
Usage: python3 experiments/hermes_agent/run_t5_localai_loop.py [model] [--sessions N]
"""

import json
import shutil
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import agent as agent_mod  # noqa: E402
from agent import DocAgent  # noqa: E402
from task_agent import TaskAgent  # noqa: E402

import run_t2  # noqa: E402
import run_t5  # noqa: E402


def to_pending(item):
    """LocalAI's approvals-inbox entry in the same shape the stand-in plugin logged."""
    mode, content = item.get("mode"), item.get("content", "")
    text = content.strip().removeprefix("- [ ]").strip()
    if item.get("name") == "tasks.md" and mode == "append":
        return {"tool": "add_task", "text": text}
    if item.get("name") == "tasks.md" and mode == "mark_done":
        return {"tool": "complete_task", "text": text}
    return {"tool": "save_note", "name": item.get("name"), "content": content}


def status_of(result: str) -> str:
    r = result.strip()
    if r.startswith("Error") or "does not exist" in r[:80]:
        return "error"
    if r.startswith("Proposed"):
        return "staged"
    return "ok"


def make_agent(model, pending, prompt):
    doc = DocAgent(model=model, pending_writes=pending)
    tasks = TaskAgent(model=model, pending_writes=pending)
    doc.tools.update(tasks.tools)  # one agent with both tool sets, like the Hermes run
    doc.system_prompt = prompt
    doc.max_steps = 10  # the Hermes run allowed 10 tool steps per turn
    return doc


def run_session(model, n, prompt):
    pending, rows = [], []
    messages = [{"role": "system", "content": prompt}]
    ag = make_agent(model, pending, prompt)
    for k, spec in enumerate(run_t5.TURNS, 1):
        start_msgs, start_pending = len(messages), len(pending)
        messages.append({"role": "user", "content": spec[1]})
        calls, answer, t0 = [], "", time.time()
        last_call = None
        for ev in ag.run(messages):
            if ev["type"] == "tool_call":
                last_call = {"tool": ev["name"], "args": ev["args"]}
            elif ev["type"] == "tool_result" and last_call:
                calls.append({**last_call, "status": status_of(ev["result"])})
                last_call = None
            elif ev["type"] == "final":
                answer = ev["content"]
        secs = time.time() - t0
        new = messages[start_msgs:]
        both = sum(1 for m in new if getattr(m, "role", None) == "assistant"
                   and (getattr(m, "content", "") or "").strip() and getattr(m, "tool_calls", None))
        staged = [to_pending(x) for x in pending[start_pending:]]
        checks = run_t5.turn_ok(spec, calls, staged, answer)
        row = {"runtime": "localai-loop", "session": n, "turn": k, "kind": spec[0], "prompt": spec[1],
               "secs": round(secs, 1), "calls": calls, "pending": staged, "answer": answer[-500:],
               "checks": checks, "ok": all(checks.values()),
               "ok_lenient": all(v for c, v in checks.items() if not c.startswith("read_file(")),
               "answer_and_tool_call_in_one_reply": both, "messages_total": len(messages),
               **run_t5.host_memory()}
        rows.append(row)
        print(f"  s{n} turn {k:2} {spec[0]:6} {secs:6.1f}s {'OK  ' if row['ok'] else 'MISS'} "
              f"tools={[c['tool'] for c in calls]} answer+call={both} msgs={len(messages)} free={row['free']}")
    return rows


def main():
    argv = sys.argv[1:]
    flag_values = {argv[i + 1] for i, a in enumerate(argv[:-1]) if a.startswith("--")}
    model = next((a for a in argv if not a.startswith("--") and not a.isdigit() and a not in flag_values),
                 "gpt-oss-64k")
    sessions = int(argv[argv.index("--sessions") + 1]) if "--sessions" in argv else 2
    if "--turns" in argv:  # e.g. 9: the first 9 turns, which reproduce the Hermes misses
        run_t5.TURNS = run_t5.TURNS[:int(argv[argv.index("--turns") + 1])]
    # --prompt-file: use another system prompt (for example Hermes's full one) instead of LocalAI's.
    prompt_file = argv[argv.index("--prompt-file") + 1] if "--prompt-file" in argv else None
    prompt = Path(prompt_file).read_text(encoding="utf-8") if prompt_file else run_t2.localai_prompt()
    tag = "hermes-prompt" if prompt_file else "localai-prompt"
    print(f"system prompt: {tag} ({len(prompt)} chars), turns: {len(run_t5.TURNS)}")
    out = HERE / "results" / f"t5-localai-loop-{tag}-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
    all_rows = []
    with tempfile.TemporaryDirectory() as tmp:
        docs = Path(tmp) / "docs"
        shutil.copytree(HERE / "smoke_docs", docs)
        for f in (HERE / "t5_docs").iterdir():
            shutil.copy(f, docs / f.name)
        with patch.object(agent_mod, "DOCS", docs.resolve()):
            for n in range(1, sessions + 1):
                rows = run_session(model, n, prompt)
                all_rows += rows
                print(f"\n  session {n}: {sum(r['ok'] for r in rows)}/21 OK (lenient "
                      f"{sum(r['ok_lenient'] for r in rows)}); replies with an answer AND a tool call: "
                      f"{sum(r['answer_and_tool_call_in_one_reply'] for r in rows)}\n")
    with out.open("w") as f:
        for r in all_rows:
            f.write(json.dumps(r, default=str) + "\n")
    n = len(all_rows)
    print(f"T5 on LocalAI's loop, {model}: {sum(r['ok'] for r in all_rows)}/{n} turns OK "
          f"(lenient {sum(r['ok_lenient'] for r in all_rows)})")
    for kind in ("list", "read", "task", "recall"):
        ks = [r for r in all_rows if r["kind"] == kind]
        print(f"  {kind:6} {sum(r['ok'] for r in ks)}/{len(ks)}")
    print(f"  replies with an answer and a tool call: {sum(r['answer_and_tool_call_in_one_reply'] for r in all_rows)}")
    print(f"  median {sorted(r['secs'] for r in all_rows)[n // 2]:.1f}s, slowest {max(r['secs'] for r in all_rows):.1f}s; "
          f"lowest free memory {min(int(r['free'].rstrip('%')) for r in all_rows)}%")
    print(f"Saved: {out}")
    subprocess_stop(model)
    return 0


def subprocess_stop(model):
    import subprocess
    subprocess.run(["ollama", "stop", model], capture_output=True)


if __name__ == "__main__":
    sys.exit(main())

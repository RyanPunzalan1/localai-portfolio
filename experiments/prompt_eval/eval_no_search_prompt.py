#!/usr/bin/env python3
"""Eval: does a model pass the read-a-named-file task with the no-search prompt?

Runs DocAgent with NO rag_search (so the no-search prompt applies) against a temporary folder of
synthetic notes (never docs/). Pass = the final answer names every TODO in the file.
Usage: python3 experiments/prompt_eval/eval_no_search_prompt.py --model hermes3 --runs 5 [--prompt current|candidate]
"""

import argparse
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

import agent  # noqa: E402

TASK_MD = "# Tasks\n- [ ] TODO: buy oat milk\n- [ ] TODO: call the dentist on Friday\n"
# Several synthetic notes with similar names, as a real docs/ folder has. A folder with one file hides
# the failure the roadmap recorded: the model calls list_files, then never read_file.
FILES = {
    "task.md": TASK_MD,
    "tasks-archive.md": "# Archive\n- [x] TODO: renew passport (done)\n",
    "todo-ideas.md": "# Ideas\n- garden planter for herbs\n- learn chess openings\n",
    "meeting-notes.md": "# Notes\n- Kickoff moved to Tuesday\n",
    "recipes.md": "# Recipes\n- lentil soup, 40 minutes\n",
    "travel.md": "# Travel\n- book train to Osaka\n",
}
NEEDLES = ("oat milk", "dentist")
# The candidate replacement for agent._PROMPT_NO_SEARCH, tested before it goes into agent.py.
CANDIDATE_NO_SEARCH = (
    "To answer about what a named note says, call read_file with its file name. "
    "list_files only shows names, never contents, so do not use it to answer about a note. "
)
REQUEST = "Read task.md and list its TODOs."


def run_once(model, prompt_text):
    with tempfile.TemporaryDirectory() as tmp:
        docs = Path(tmp) / "docs"
        docs.mkdir()
        for name, text in FILES.items():
            (docs / name).write_text(text, encoding="utf-8")
        agent.DOCS = docs.resolve()
        ag = agent.DocAgent(model=model)  # no rag_search: the no-search prompt applies
        if prompt_text is not None:
            ag.system_prompt = prompt_text
        answer, calls = "", []
        for ev in ag.run([{"role": "user", "content": REQUEST}]):
            if ev["type"] == "tool_call":
                calls.append(ev["name"])
            elif ev["type"] == "final":
                answer = ev["content"]
        ok = all(n in answer.lower() for n in NEEDLES)
        return {"pass": ok, "tools": calls, "answer": answer[:300]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="hermes3")
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--prompt", choices=["current", "candidate", "search"], default="current")
    args = ap.parse_args()
    prompts = {
        "current": None,  # the class default: SYSTEM_PROMPT_NO_SEARCH as shipped
        "candidate": agent._PROMPT_START + CANDIDATE_NO_SEARCH + agent._PROMPT_END,
        "search": agent.SYSTEM_PROMPT,
    }
    rows = [run_once(args.model, prompts[args.prompt]) for _ in range(args.runs)]
    passed = sum(r["pass"] for r in rows)
    print(f"model={args.model} prompt={args.prompt}: {passed}/{args.runs} pass")
    for r in rows:
        print(f"  pass={r['pass']} tools={r['tools']} answer={r['answer']!r}")
    out = HERE / "results" / f"{args.model}-{args.prompt}-{datetime.now():%Y%m%d-%H%M%S}.json"
    out.write_text(json.dumps({"model": args.model, "prompt": args.prompt, "passed": passed,
                               "runs": args.runs, "rows": rows}, indent=2), encoding="utf-8")
    print(f"record: {out}")


if __name__ == "__main__":
    main()

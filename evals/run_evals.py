"""Run the eval cases against a model and print pass/fail.

Usage: python3 evals/run_evals.py [model] [temperature] [num_ctx]   (default: agent.MODEL)
num_ctx overrides the agents' per-model context (agent.context_for) for this run only.

Runs in a temporary folder with dummy notes. Never touches docs/ or chat_history.json.
Writes are proposed only, never saved: the approvals list is a throwaway list here.
"""

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ollama  # noqa: E402

import agent as agent_mod  # noqa: E402
import brain  # noqa: E402
from agent import DocAgent  # noqa: E402
from evals.cases import CASES  # noqa: E402
from lessons import build_lesson  # noqa: E402
from lessons_agent import LESSONS_PURPOSE, LessonsAgent  # noqa: E402
from task_agent import TASKS_FILE, TaskAgent  # noqa: E402

NAMES = ["DocAgent", "TaskAgent", "LessonsAgent"]
# Same purposes as the app registry in app.py.
PURPOSES = {
    "DocAgent": "Lists, reads, and saves note files. Use for any request about files or notes.",
    "TaskAgent": "Only for the task list: add a task, show tasks, or mark a task done.",
    "LessonsAgent": LESSONS_PURPOSE,
}
DUMMY = {
    TASKS_FILE: "- [ ] buy milk\n- [ ] call the dentist\n- [ ] email Sam\n",
    "ideas.md": "Ideas: a local chess club app.\n",
}
for _args in [("Docker needs no-cache", "docker", "Build with --no-cache after changing requirements.",
               "Old layers were cached."),
              ("Streamlit reruns the script", "streamlit, caching", "Wrap slow setup in st.cache_resource.",
               "Every click reruns the whole script.")]:
    _name, _text = build_lesson(*_args)
    DUMMY[_name] = _text


def make_docs(root: Path) -> Path:
    docs = root / "docs"
    docs.mkdir()
    for name, text in DUMMY.items():
        (docs / name).write_text(text, encoding="utf-8")
    return docs


class NullLog:
    def append(self, event):
        return event


def tool_called(agent, prompt):
    """Run the agent and return the names of the tools it called."""
    called = []
    for ev in agent.run([{"role": "user", "content": prompt}]):
        if ev.get("type") == "tool_call":
            called.append(ev["name"])
    return called


def eval_options(temperature=None, num_ctx=None):
    """Model options for the eval, or None to measure the app's own settings."""
    options = {}
    if temperature is not None:
        options["temperature"] = temperature
    if num_ctx is not None:
        options["num_ctx"] = num_ctx  # the route call uses it too, so Ollama does not reload the model
    return options or None


def main(model: str, temperature=None, num_ctx=None) -> int:
    options = eval_options(temperature, num_ctx)
    ask = lambda prompt: ollama.chat(model=model, options=options,
                                     messages=[{"role": "user", "content": prompt}])["message"]["content"]
    pick = brain.model_picker(ask, PURPOSES)
    rows = []
    with tempfile.TemporaryDirectory() as tmp, patch.object(agent_mod, "DOCS", make_docs(Path(tmp)).resolve()):
        for case in CASES:
            try:
                route = pick(case["prompt"], NAMES)
            except brain.RouteError as e:
                route = f"ERROR: {e}"
            route_ok = route == case["route"]

            pending = []
            if case["route"] == "TaskAgent":
                agent = TaskAgent(model=model, pending_writes=pending)
            elif case["route"] == "LessonsAgent":
                agent = LessonsAgent(model=model, pending_writes=pending)
            else:
                agent = DocAgent(model=model, pending_writes=pending)
            if options is not None:  # no argument: measure the app's own setting
                agent.options = {**agent.options, **options}  # keep the reply-length cap
            calls = tool_called(agent, case["prompt"])
            tool_ok = case["tool"] in calls

            # Only for cases with "contains": the proposed note must keep the user's own words.
            fields_ok = None
            if "contains" in case:
                proposed = " ".join(w["content"].lower() for w in pending)
                fields_ok = bool(pending) and all(word in proposed for word in case["contains"])

            rows.append((case["prompt"], route, route_ok, calls, tool_ok, case["tool"], fields_ok))

    print(f"Model: {model}   temperature: {'app setting' if temperature is None else temperature}   "
          f"num_ctx: {'Ollama default' if num_ctx is None else num_ctx}\n")
    print(f"{'route':6}  {'tool':6}  request  (got route, got tools)")
    for prompt, route, route_ok, calls, tool_ok, want, fields_ok in rows:
        print(f"{'PASS' if route_ok else 'FAIL':6}  {'PASS' if tool_ok else 'FAIL':6}  {prompt}")
        print(f"        want tool {want}; route {route}; tools {calls}"
              + ("" if fields_ok is None else f"; fields {'PASS' if fields_ok else 'FAIL'}"))
    r = sum(1 for row in rows if row[2])
    t = sum(1 for row in rows if row[4])
    checked = [row[6] for row in rows if row[6] is not None]
    print(f"\nRoute: {r}/{len(rows)}   Tool: {t}/{len(rows)}   "
          f"Lesson fields: {sum(checked)}/{len(checked)}")
    return 0 if r == t == len(rows) and all(checked) else 1


if __name__ == "__main__":
    model_name = sys.argv[1] if len(sys.argv) > 1 else agent_mod.MODEL  # the configured default
    temp = float(sys.argv[2]) if len(sys.argv) > 2 else None  # for example: run_evals.py hermes3 0
    ctx = int(sys.argv[3]) if len(sys.argv) > 3 else None  # for example: run_evals.py hermes3 0 65536
    sys.exit(main(model_name, temp, ctx))

"""T2: multi-step tasks with several tools, under Hermes Agent in a locked-down sbx sandbox.

Plan: design/hermes-agent-llm-eval-plan.md (T2). Uses the same sandbox, lock-down, config and stand-in
plugin as run_t1_smoke.py, with all six tools enabled. Writes are only staged, never applied.
Usage: python3 experiments/hermes_agent/run_t2.py [model] [--repeats N] [--hermes-prompt] [--keep]
       (default gpt-oss-64k, 3 repeats, LocalAI's system prompt added; --hermes-prompt = Hermes's own only)

Scoring is done by code from the plugin's call log and staged writes, never from the model's text
(except where a case checks that the answer mentions something really in the file).
"""

import json
import sys
import tempfile
import time
from pathlib import Path

import run_t1_smoke as base

ROOT = base.HERE.parent.parent  # the LocalAI project folder


def localai_prompt() -> str:
    """LocalAI's own instructions for these tools: the notes agent's prompt (agent.py) plus the tasks
    pack's rules (packs/tasks/prompt.txt). One Hermes agent has both tool sets, so it gets both."""
    sys.path.insert(0, str(ROOT))
    import agent  # noqa: E402  (only reads the prompt string; touches no files)
    tasks = (ROOT / "packs" / "tasks" / "prompt.txt").read_text(encoding="utf-8").strip()
    return agent.SYSTEM_PROMPT.strip() + "\n\n" + tasks


def config_with_prompt(prompt: str, folder: str) -> Path:
    """A copy of config.yaml with agent.system_prompt set (Hermes adds it to its own base prompt)."""
    text = (base.HERE / "config" / "config.yaml").read_text(encoding="utf-8")
    block = "agent:\n  system_prompt: " + json.dumps(prompt) + "\n"  # JSON string is valid YAML
    path = Path(folder) / "config.yaml"
    path.write_text(text.rstrip() + "\n\n# Added by run_t2.py: LocalAI's system prompt.\n" + block,
                    encoding="utf-8")
    return path

TOOLS = ["list_files", "read_file", "save_note", "list_tasks", "add_task", "complete_task"]
FAILED = {"error", "missing", "refused", "no_match"}


def read(name):
    return ("read_file", lambda c: c["args"].get("name") == name, f"read_file({name})")


def call(tool, label=None):
    return (tool, lambda c: True, label or tool)


def staged(tool, test, label):
    return (tool, test, label)


def has(text, *words):
    return all(w.lower() in str(text).lower() for w in words)


# Each case: id, prompt, required calls, required staged writes, max staged writes,
# order rule (earlier tool, later tool) or None, answer word or None.
CASES = [
    ("dentist-followup", "Find my note about the dentist and add a task for the follow-up it mentions.",
     [read("dentist.md")], [staged("add_task", lambda w: has(w.get("text"), "insurance"), "add_task(insurance)")],
     1, ("read_file", "add_task"), None),
    ("trip-booking", "Read my trip note and add a task for what I need to book.",
     [read("trip.md")], [staged("add_task", lambda w: has(w.get("text"), "ticket"), "add_task(tickets)")],
     1, ("read_file", "add_task"), None),
    ("veg-note", "Read groceries.md and save a note called vegetables.md that lists only the vegetables.",
     [read("groceries.md")],
     [staged("save_note", lambda w: w.get("name") == "vegetables.md" and has(w.get("content"), "spinach")
             and not any(x in str(w.get("content")).lower() for x in ("milk", "eggs")),
             "save_note(vegetables.md, spinach only)")],
     1, ("read_file", "save_note"), None),
    ("plumber-done", "I called the plumber today. Mark that task as done.",
     [call("list_tasks")],
     [staged("complete_task", lambda w: w.get("text") == "call the plumber", "complete_task(call the plumber)")],
     1, ("list_tasks", "complete_task"), None),
    ("library-check", "Do I have a task about the library? If so, mark it done.",
     [call("list_tasks")],
     [staged("complete_task", lambda w: w.get("text") == "renew library card", "complete_task(renew library card)")],
     1, ("list_tasks", "complete_task"), None),
    ("thursday", "Which of my notes mentions Thursday? Add a task to confirm that appointment.",
     [read("dentist.md")],
     [staged("add_task", lambda w: any(x in str(w.get("text")).lower() for x in ("dentist", "appointment")),
             "add_task(dentist appointment)")],
     1, ("read_file", "add_task"), None),
    ("two-note-summary", "Read ideas.md and trip.md, then save a note called summary.md with one line about each.",
     [read("ideas.md"), read("trip.md")],
     [staged("save_note", lambda w: w.get("name") == "summary.md" and has(w.get("content"), "chess", "lisbon"),
             "save_note(summary.md, chess + Lisbon)")],
     1, ("read_file", "save_note"), None),
    ("no-write", "Read ideas.md and tell me which idea is about money.",
     [read("ideas.md")], [], 0, None, "budget"),
    ("not-in-list", "Mark the task 'buy a new car' as done.",
     [call("list_tasks")], [], 0, None, None),
    ("add-and-list", "Add a task to buy stamps, then show me my task list.",
     [call("list_tasks")], [staged("add_task", lambda w: has(w.get("text"), "stamp"), "add_task(stamps)")],
     1, None, None),
    # Added 2026-11-20 after run 1: "dentist-followup" above is ambiguous (confirming the appointment is
    # also a fair follow-up). It is kept unchanged; this one has one right answer.
    ("dentist-bring", "Read my dentist note and add a task for the thing I need to bring.",
     [read("dentist.md")], [staged("add_task", lambda w: has(w.get("text"), "insurance"), "add_task(insurance)")],
     1, ("read_file", "add_task"), None),
]


def count_lines(path):
    r = base.sbx_exec(f"wc -l < {path} 2>/dev/null || echo 0")
    return int((r.stdout.strip() or "0").split()[0])


def lines_after(path, start):
    r = base.sbx_exec(f"tail -n +{start + 1} {path} 2>/dev/null")
    return [json.loads(x) for x in r.stdout.splitlines() if x.strip().startswith("{")]


def docs_fingerprint():
    return base.sbx_exec(f"cd {base.HOME}/workspace/docs && sha256sum * | sha256sum").stdout.strip()


def run_one(model, case):
    calls_log, pend_log = f"{base.HOME}/workspace/calls.jsonl", f"{base.HOME}/workspace/pending.jsonl"
    c0, p0 = count_lines(calls_log), count_lines(pend_log)
    q = case[1].replace("'", "'\\''")
    t0 = time.time()
    r = base.sbx_exec(f"timeout 300 hermes chat -Q -q '{q}' -m {model} --provider custom "
                      f"--ignore-rules --max-turns 10 2>&1", timeout=360)
    secs = time.time() - t0
    return secs, r.stdout.strip(), r.returncode, lines_after(calls_log, c0), lines_after(pend_log, p0)


def score(case, calls, pending, answer):
    _, _, req_calls, req_writes, max_writes, order, word = case
    checks = {}
    for tool, test, label in req_calls:
        checks[label] = any(c["tool"] == tool and test(c) for c in calls)
    for tool, test, label in req_writes:
        checks[label] = any(w["tool"] == tool and test(w) for w in pending)
    checks[f"staged writes <= {max_writes}"] = len(pending) <= max_writes
    if order:
        first = next((i for i, c in enumerate(calls) if c["tool"] == order[0]), None)
        later = next((i for i, c in enumerate(calls) if c["tool"] == order[1]), None)
        checks[f"{order[0]} before {order[1]}"] = first is not None and later is not None and first < later
    if word:
        checks[f"answer mentions {word}"] = word.lower() in answer.lower()
    required = len(req_calls) + len(req_writes)
    hit = sum(checks[label] for _, _, label in req_calls + req_writes)
    return {
        "completed": all(checks.values()),
        "checks": checks,
        "tool_accuracy": round(hit / required, 2) if required else 1.0,
        "failed_calls": sum(1 for c in calls if c["status"] in FAILED),
        "blocked_calls": sum(1 for c in calls if c["status"] == "blocked_by_hook"),
        "steps": len(calls),
        "staged": len(pending),
    }


def main():
    argv = sys.argv[1:]
    model = next((a for a in argv if not a.startswith("--") and not a.isdigit()), "gpt-oss-64k")
    repeats = int(argv[argv.index("--repeats") + 1]) if "--repeats" in argv else 3
    keep = "--keep" in argv
    prompt_mode = "hermes-default" if "--hermes-prompt" in argv else "localai"
    tmp = tempfile.TemporaryDirectory()
    config_path = None if prompt_mode == "hermes-default" else config_with_prompt(localai_prompt(), tmp.name)
    out_dir = base.HERE / "results"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"t2-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
    base.sh(["sbx", "rm", base.NAME, "--force", "--no-input"], check=False)
    print("Creating locked sandbox ...")
    base.create_locked_sandbox()
    try:
        print("Reachability check:")
        if not base.reachability_ok():
            print("FAIL CLOSED: network lock-down not as expected; nothing was run.")
            return 2
        base.install_files(TOOLS, config_path)
        print("  " + base.sbx_exec("hermes --version | head -1").stdout.strip())
        check = base.sbx_exec(
            "cd /opt/hermes && /opt/hermes/.venv/bin/python -c \"import sys; sys.path.insert(0, '.'); "
            "from hermes_cli.config import load_config; from hermes_cli.personality import "
            "resolve_ephemeral_system_prompt as r; print('PROMPT_CHARS=%d' % len(r(load_config())))\"")
        chars = next((int(x.split("=")[1]) for x in check.stdout.splitlines() if x.startswith("PROMPT_CHARS=")), -1)
        print(f"  system prompt: {prompt_mode} (Hermes reads {chars} extra characters)")
        if (prompt_mode == "localai") != (chars > 0):
            print("FAIL CLOSED: Hermes is not using the intended system prompt; nothing was run.")
            return 4
        sent = base.tools_sent()
        print(f"  tools Hermes will send: {sent}")
        if sent != sorted(TOOLS):
            print("FAIL CLOSED: the model would get other tools (or none); nothing was run.")
            return 3
        before = docs_fingerprint()
        rows = []
        for rep in range(1, repeats + 1):
            for case in CASES:
                secs, answer, rc, calls, pending = run_one(model, case)
                row = {"model": model, "prompt": prompt_mode, "case": case[0], "repeat": rep,
                       "secs": round(secs, 1), "rc": rc,
                       "calls": [{k: c.get(k) for k in ("tool", "args", "status")} for c in calls],
                       "pending": pending, "answer": answer[-600:]}
                row.update(score(case, calls, pending, answer))
                rows.append(row)
                print(f"  rep {rep} {case[0]:18} {secs:6.1f}s {'PASS' if row['completed'] else 'FAIL'} "
                      f"tools={[c['tool'] for c in calls]} staged={row['staged']}")
        files_changed = docs_fingerprint() != before
        base.sh(["ollama", "stop", model], check=False)
        with out.open("w") as f:
            for row in rows:
                f.write(json.dumps(row) + "\n")
        n = len(rows)
        print(f"\nResults for {model} ({repeats} repeats x {len(CASES)} cases):")
        print(f"  tasks completed: {sum(r['completed'] for r in rows)}/{n}")
        print(f"  tool-call accuracy (required calls and writes present): "
              f"{sum(r['tool_accuracy'] for r in rows) / n:.2f}")
        print(f"  failed tool calls: {sum(r['failed_calls'] for r in rows)}; blocked by hook: "
              f"{sum(r['blocked_calls'] for r in rows)}; errors: {sum(1 for r in rows if r['rc'] != 0)}")
        print(f"  median time: {sorted(r['secs'] for r in rows)[n // 2]:.1f}s; "
              f"mean steps: {sum(r['steps'] for r in rows) / n:.1f}")
        print(f"  dummy files changed on disk: {files_changed} (want False)")
        for case in CASES:
            mine = [r for r in rows if r["case"] == case[0]]
            fails = [r for r in mine if not r["completed"]]
            print(f"  {case[0]:18} {len(mine) - len(fails)}/{len(mine)}"
                  + ("" if not fails else "  failed: " + "; ".join(
                      k for k, v in fails[0]["checks"].items() if not v)))
        other = base.outbound_attempts()
        print(f"\nOutbound attempts other than Ollama and the check's own: {other or 'none'}")
        print(f"Saved: {out}")
        return 0
    finally:
        tmp.cleanup()
        if not keep:
            base.sh(["sbx", "rm", base.NAME, "--force", "--no-input"], check=False)
            print("Sandbox removed.")


if __name__ == "__main__":
    sys.exit(main())

"""T3 (argument accuracy) and T4 (recovery from failed calls) under Hermes Agent in a locked sbx sandbox.

Plan: design/hermes-agent-llm-eval-plan.md (T3, T4). Same sandbox, lock-down, config, stand-in plugin
and LocalAI system prompt as run_t2.py. Extra dummy notes with odd names come from t34_docs/.
T4 plants failures through the plugin's faults file (a call fails with a temporary error N times).
Usage: python3 experiments/hermes_agent/run_t34.py [model] [--suite t3|t4|both] [--repeats N] [--keep]
       (default gpt-oss-64k, both, 3 repeats)

Scoring is by code from the call log and staged writes. Answer checks only test for words that are
really in a file, or for a plain "it does not exist" message.
"""

import json
import sys
import tempfile
import time

import run_t1_smoke as base
import run_t2 as t2

FAILED = t2.FAILED
NOT_FOUND = ("not exist", "doesn't exist", "does not exist", "not found", "no such", "couldn't find",
             "could not find", "no file", "no note", "isn't a", "is not a", "don't have", "do not have",
             "there is no", "there's no", "unable to find", "not available", "only .md", "only .txt",
             "only allows", "not allowed", "can't open", "cannot open", "can only")


def says_not_found(answer):
    # gpt-oss writes curly apostrophes ("couldn’t"); the first scoring missed them (fixed 2026-11-20).
    text = answer.lower().replace("’", "'").replace("‘", "'")
    return any(p in text for p in NOT_FOUND)


def called(calls, tool, **args):
    return any(c["tool"] == tool and all(c["args"].get(k) == v for k, v in args.items()) for c in calls)


def ok_call(calls, tool, **args):
    return any(c["tool"] == tool and c["status"] == "ok" and all(c["args"].get(k) == v for k, v in args.items())
               for c in calls)


def staged_only(pending, tool, test):
    return len(pending) == 1 and pending[0]["tool"] == tool and test(pending[0])


# Each case: id, prompt, check(calls, pending, answer) -> {label: bool}, faults (T4), max_writes.
T3 = [
    ("spaces-name", "Read the note called Meeting Notes 2026.md and tell me who owns the slides.",
     lambda c, p, a: {"read_file(Meeting Notes 2026.md) ok": ok_call(c, "read_file", name="Meeting Notes 2026.md"),
                      "answer says Sam": "sam" in a.lower()}, None, 0),
    ("punctuation-name", "Open my-project_plan.v2.txt and tell me what launches in April.",
     lambda c, p, a: {"read_file(my-project_plan.v2.txt) ok": ok_call(c, "read_file", name="my-project_plan.v2.txt"),
                      "answer says chess": "chess" in a.lower()}, None, 0),
    ("unicode-name", "What's in café-ideas.md?",
     lambda c, p, a: {"read_file(café-ideas.md) ok": ok_call(c, "read_file", name="café-ideas.md"),
                      "answer says board games": "board game" in a.lower()}, None, 0),
    ("quotes-task", 'Add a task: ask Sam about the "blue folder" report.',
     lambda c, p, a: {"one add_task with Sam and blue folder": staged_only(
         p, "add_task", lambda w: t2.has(w["text"], "sam", "blue folder", "report"))}, None, 1),
    ("apostrophe-done", "I picked up Mia's prescription. Mark it done.",
     lambda c, p, a: {"one complete_task(pick up Mia's prescription)": staged_only(
         p, "complete_task", lambda w: w["text"] == "pick up Mia's prescription")}, None, 1),
    ("exact-note-name", "Save a note called packing-list.md with: passport, charger, socks.",
     lambda c, p, a: {"one save_note(packing-list.md) with all three items": staged_only(
         p, "save_note", lambda w: w["name"] == "packing-list.md"
         and t2.has(w["content"], "passport", "charger", "socks"))}, None, 1),
    ("numbers-task", "Add a task to pay the $45.50 water bill by 12/03.",
     lambda c, p, a: {"one add_task with $45.50 and 12/03": staged_only(
         p, "add_task", lambda w: "45.50" in w["text"] and "12/03" in w["text"])}, None, 1),
    ("dated-note-name", "Copy my grocery list from groceries.md into a new note named shopping-2026-11.md.",
     lambda c, p, a: {"read_file(groceries.md) ok": ok_call(c, "read_file", name="groceries.md"),
                      "one save_note(shopping-2026-11.md) with the list": staged_only(
                          p, "save_note", lambda w: w["name"] == "shopping-2026-11.md"
                          and t2.has(w["content"], "milk", "spinach"))}, None, 1),
    ("exact-copy-done", "Mark 'renew library card' as done.",
     lambda c, p, a: {"one complete_task(renew library card)": staged_only(
         p, "complete_task", lambda w: w["text"] == "renew library card")}, None, 1),
]

T4 = [
    ("missing-similar", "Read meeting-notes.md",  # does not exist; "Meeting Notes 2026.md" does
     lambda c, p, a: {"read the real file or said it is missing":
                      ok_call(c, "read_file", name="Meeting Notes 2026.md") or says_not_found(a)}, None, 0),
    ("path-escape", "Read ../secrets.md",
     lambda c, p, a: {"said it is not available": says_not_found(a)}, None, 0),
    ("wrong-suffix", "Read report.pdf",
     lambda c, p, a: {"said it cannot open it": says_not_found(a)}, None, 0),
    ("flaky-read", "Read ideas.md and tell me the first idea.",
     lambda c, p, a: {"retried and read ideas.md": ok_call(c, "read_file", name="ideas.md"),
                      "answer says chess": "chess" in a.lower()}, {"read_file|ideas.md": 1}, 0),
    ("flaky-list", "What files do I have?",
     lambda c, p, a: {"retried and listed": ok_call(c, "list_files"),
                      "answer names a real file": "groceries" in a.lower() or "ideas" in a.lower()},
     {"list_files|": 1}, 0),
    ("no-such-note", "What does my note about the gym say?",
     lambda c, p, a: {"said there is no gym note": says_not_found(a)}, None, 0),
    ("near-miss-task", "I watered the plant. Mark it done.",
     lambda c, p, a: {"one complete_task(water the plants)": staged_only(
         p, "complete_task", lambda w: w["text"] == "water the plants")}, None, 1),
    ("bad-note-suffix", "Save a note called notes.docx that says: hello world.",
     lambda c, p, a: {"staged a .md/.txt note or explained":
                      (len(p) == 1 and p[0]["tool"] == "save_note" and "hello world" in p[0]["content"].lower())
                      or (len(p) == 0 and says_not_found(a))}, None, 1),
    ("flaky-add", "Add a task to buy stamps.",
     lambda c, p, a: {"one add_task(stamps) after the error": staged_only(
         p, "add_task", lambda w: "stamp" in w["text"].lower())}, {"add_task|buy stamps": 1}, 1),
]


def repeated_failures(calls):
    """Most times the same failing call (same tool and arguments) was repeated."""
    seen = {}
    for c in calls:
        if c["status"] in FAILED:
            key = (c["tool"], json.dumps(c["args"], sort_keys=True))
            seen[key] = seen.get(key, 0) + 1
    return max(seen.values(), default=0)


def score(case, calls, pending, answer):
    _, _, check, _, max_writes = case
    checks = check(calls, pending, answer)
    checks[f"staged writes <= {max_writes}"] = len(pending) <= max_writes
    checks["same failing call at most 2 times"] = repeated_failures(calls) <= 2
    checks["no blocked tool"] = not any(c["status"] == "blocked_by_hook" for c in calls)
    return {"completed": all(checks.values()), "checks": checks,
            "failed_calls": sum(1 for c in calls if c["status"] in FAILED),
            "max_repeat_failure": repeated_failures(calls), "steps": len(calls), "staged": len(pending)}


def set_faults(faults):
    body = json.dumps(faults or {}).replace("'", "'\\''")
    base.sbx_exec(f"printf '%s' '{body}' > {base.HOME}/workspace/faults.json")


def main():
    argv = sys.argv[1:]
    model = next((a for a in argv if not a.startswith("--") and a not in ("t3", "t4", "both")
                  and not a.isdigit()), "gpt-oss-64k")
    suite = argv[argv.index("--suite") + 1] if "--suite" in argv else "both"
    repeats = int(argv[argv.index("--repeats") + 1]) if "--repeats" in argv else 3
    keep = "--keep" in argv
    suites = {"t3": [("t3", c) for c in T3], "t4": [("t4", c) for c in T4]}
    cases = suites["t3"] + suites["t4"] if suite == "both" else suites[suite]
    tmp = tempfile.TemporaryDirectory()
    config_path = t2.config_with_prompt(t2.localai_prompt(), tmp.name)
    out = base.HERE / "results" / f"t34-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
    out.parent.mkdir(exist_ok=True)
    base.sh(["sbx", "rm", base.NAME, "--force", "--no-input"], check=False)
    print("Creating locked sandbox ...")
    base.create_locked_sandbox()
    try:
        print("Reachability check:")
        if not base.reachability_ok():
            print("FAIL CLOSED: network lock-down not as expected; nothing was run.")
            return 2
        base.install_files(t2.TOOLS, config_path, base.HERE / "t34_docs")
        sent = base.tools_sent()
        print(f"  tools Hermes will send: {sent}")
        if sent != sorted(t2.TOOLS):
            print("FAIL CLOSED: the model would get other tools (or none); nothing was run.")
            return 3
        before = t2.docs_fingerprint()
        rows = []
        for rep in range(1, repeats + 1):
            for name, case in cases:
                set_faults(case[3])
                secs, answer, rc, calls, pending = t2.run_one(model, case)
                set_faults(None)
                row = {"model": model, "suite": name, "case": case[0], "repeat": rep, "secs": round(secs, 1),
                       "rc": rc, "faults": case[3],
                       "calls": [{k: c.get(k) for k in ("tool", "args", "status")} for c in calls],
                       "pending": pending, "answer": answer[-600:]}
                row.update(score(case, calls, pending, answer))
                rows.append(row)
                print(f"  rep {rep} {name} {case[0]:17} {secs:6.1f}s {'PASS' if row['completed'] else 'FAIL'} "
                      f"tools={[(c['tool'], c['status']) for c in calls]}")
        files_changed = t2.docs_fingerprint() != before
        base.sh(["ollama", "stop", model], check=False)
        with out.open("w") as f:
            for row in rows:
                f.write(json.dumps(row) + "\n")
        for name in ("t3", "t4"):
            mine = [r for r in rows if r["suite"] == name]
            if not mine:
                continue
            n = len(mine)
            print(f"\n{name.upper()} for {model} ({repeats} repeats x {n // repeats} cases):")
            print(f"  completed: {sum(r['completed'] for r in mine)}/{n}; failed tool calls: "
                  f"{sum(r['failed_calls'] for r in mine)} (planted or real); worst repeat of one failing "
                  f"call: {max(r['max_repeat_failure'] for r in mine)}; errors: {sum(1 for r in mine if r['rc'])}")
            print(f"  median time: {sorted(r['secs'] for r in mine)[n // 2]:.1f}s")
            for cid in dict.fromkeys(r["case"] for r in mine):
                rs = [r for r in mine if r["case"] == cid]
                fails = [r for r in rs if not r["completed"]]
                print(f"  {cid:17} {len(rs) - len(fails)}/{len(rs)}" + ("" if not fails else "  failed: " + "; ".join(
                    k for k, v in fails[0]["checks"].items() if not v)))
        print(f"\nDummy files changed on disk: {files_changed} (want False)")
        print(f"Outbound attempts other than Ollama and the check's own: {base.outbound_attempts() or 'none'}")
        print(f"Saved: {out}")
        return 0
    finally:
        tmp.cleanup()
        if not keep:
            base.sh(["sbx", "rm", base.NAME, "--force", "--no-input"], check=False)
            print("Sandbox removed.")


if __name__ == "__main__":
    sys.exit(main())

"""T5: one long Hermes Agent session that builds up past the compression point, in a locked sbx sandbox.

Plan: design/hermes-agent-llm-eval-plan.md (T5). Same sandbox, lock-down, config, stand-in plugin and
LocalAI system prompt as run_t2.py. 15 large dummy logs (t5_docs/, about 3,350 tokens each, one planted
"KEY FACT" each) are read one per turn in ONE session (hermes chat --resume), about 50K tokens of tool
output, past Hermes's compression point (75% of the 64K window, about 49K tokens). Between reads the
session adds a task, marks a task done, and is asked about facts read many turns earlier.
Usage: python3 experiments/hermes_agent/run_t5.py [model] [--sessions N] [--keep]   (default gpt-oss-64k, 2)

Per turn it records: tools and arguments (from the call log), whether the answer has the planted fact,
time, compression events so far (Hermes's own log), and host memory, swap and `ollama ps`.
"""

import json
import re
import subprocess
import sys
import tempfile
import time

import run_t1_smoke as base
import run_t2 as t2

FACT = {1: "4471", 2: "blue pot", 3: "1.8", 4: "maple-orbit-92", 5: "tuesday", 6: "3309", 7: "red door",
        8: "diesel", 9: "06:15", 10: "hallway", 11: "200", 12: "green", 13: "150", 14: "40", 15: "2019"}


def read_turn(i):
    return ("read", f"Read log-{i:02d}.md and tell me its key fact.", {"tool": "read_file", "name": f"log-{i:02d}.md"},
            [FACT[i]])


TURNS = ([("list", "List my log files.", {"tool": "list_files"}, ["log-01"])]
         + [read_turn(i) for i in range(1, 9)]
         + [("task", "Add a task to renew the parking permit.", {"tool": "add_task", "contains": "parking"}, [])]
         + [("recall", "Without reading it again if you can: what was the key fact in log-02.md?", None, [FACT[2]])]
         + [read_turn(i) for i in range(9, 14)]
         + [("recall", "What was the key fact in log-01.md?", None, [FACT[1]])]
         + [read_turn(14)]
         + [("task", "Mark 'water the plants' as done.", {"tool": "complete_task", "text": "water the plants"}, [])]
         + [read_turn(15)]
         + [("recall", "Which log mentioned the boiler pressure, and what was the pressure?", None, ["log-03", FACT[3]])])


def host_memory():
    free = subprocess.run(["memory_pressure"], capture_output=True, text=True).stdout.strip().splitlines()[-1].split()[-1]
    swap = subprocess.run(["sysctl", "-n", "vm.swapusage"], capture_output=True, text=True).stdout.split()[5]
    ps = subprocess.run(["ollama", "ps"], capture_output=True, text=True).stdout.splitlines()
    loaded = " ".join(ps[1].split()[2:6]) if len(ps) > 1 else "not loaded"
    return {"free": free, "swap_used": swap, "ollama": loaded}


def compressions():
    r = base.sbx_exec(f"grep -c 'Compressed:' {base.HOME}/.hermes/logs/agent.log 2>/dev/null || echo 0")
    return int((r.stdout.strip() or "0").splitlines()[0])


def compression_lines():
    return base.sbx_exec(f"grep -h 'Compressed:' {base.HOME}/.hermes/logs/agent.log 2>/dev/null").stdout.strip()


def norm(text):
    """gpt-oss writes Unicode hyphens and narrow spaces ("Log‑03.md", "3 pm"); match them as plain."""
    text = text.lower()
    for ch in "‐‑‒–—":
        text = text.replace(ch, "-")
    for ch in "  ":
        text = text.replace(ch, " ")
    return text.replace("’", "'")


def has_word(answer, word):
    a, w = norm(answer), norm(word)
    if re.fullmatch(r"log-\d\d", w):  # "log-03", "log 03" and "log03" all name the same log
        return re.search(w.replace("-", r"[\s\-]?"), a) is not None
    return w in a


def turn_ok(spec, calls, pending, answer):
    kind, _, need, words = spec
    checks = {}
    if need:
        tool = need["tool"]
        if tool == "read_file":
            checks[f"read_file({need['name']}) ok"] = any(
                c["tool"] == "read_file" and c["args"].get("name") == need["name"] and c["status"] == "ok" for c in calls)
        elif tool == "add_task":
            checks["one add_task(parking)"] = len(pending) == 1 and need["contains"] in pending[0].get("text", "").lower()
        elif tool == "complete_task":
            checks["one complete_task(water the plants)"] = (len(pending) == 1
                                                             and pending[0].get("text") == need["text"])
        else:
            checks[f"{tool} called"] = any(c["tool"] == tool for c in calls)
    if kind in ("read", "recall", "list"):
        checks["no write staged"] = not pending
    for w in words:
        checks[f"answer has '{w}'"] = has_word(answer, w)
    return checks


def run_session(model, n):
    calls_log, pend_log = f"{base.HOME}/workspace/calls.jsonl", f"{base.HOME}/workspace/pending.jsonl"
    api_log = f"{base.HOME}/workspace/api.jsonl"
    session, rows = None, []
    for k, spec in enumerate(TURNS, 1):
        c0, p0, a0 = t2.count_lines(calls_log), t2.count_lines(pend_log), t2.count_lines(api_log)
        q = spec[1].replace("'", "'\\''")
        resume = f"--resume {session} " if session else ""
        t0 = time.time()
        r = base.sbx_exec(f"timeout 600 hermes chat -Q -q '{q}' {resume}-m {model} --provider custom "
                          f"--ignore-rules --max-turns 10 2>&1", timeout=660)
        secs = time.time() - t0
        out = r.stdout.strip()
        m = re.search(r"session_id:\s*(\S+)", out)
        if session is None and m:
            session = m.group(1)
        same_session = bool(m) and m.group(1) == session
        answer = out.split("\n\nsession_id")[0]
        calls, pending = t2.lines_after(calls_log, c0), t2.lines_after(pend_log, p0)
        api = t2.lines_after(api_log, a0)
        prompt_max = max((a.get("prompt_tokens") or 0 for a in api), default=0)
        cut = sum(1 for a in api if a.get("finish") == "length")
        ctx_seen = sorted({a.get("context_length") for a in api if a.get("context_length")})
        checks = turn_ok(spec, calls, pending, answer)
        row = {"session": n, "turn": k, "kind": spec[0], "prompt": spec[1], "secs": round(secs, 1), "rc": r.returncode,
               "same_session": same_session, "calls": [{x: c.get(x) for x in ("tool", "args", "status")} for c in calls],
               "pending": pending, "answer": answer[-500:], "checks": checks, "ok": all(checks.values()) and same_session,
               # Lenient: a read turn may answer from a log already read earlier in the session.
               "ok_lenient": all(v for c, v in checks.items() if not c.startswith("read_file(")) and same_session,
               "compressions_so_far": compressions(), "api_requests": len(api), "prompt_tokens_max": prompt_max,
               "replies_cut_by_length": cut, "context_length_seen": ctx_seen, **host_memory()}
        rows.append(row)
        print(f"  s{n} turn {k:2} {spec[0]:6} {secs:6.1f}s {'OK  ' if row['ok'] else 'MISS'} "
              f"tools={[c['tool'] for c in calls]} prompt={prompt_max} cut={cut} "
              f"compressions={row['compressions_so_far']} free={row['free']} swap={row['swap_used']}")
    return session, rows


def session_stats(session):
    """Message count and token use Hermes stored for the session (its own SQLite store)."""
    py = ("import sqlite3, json; db = sqlite3.connect('/home/agent/.hermes/state.db'); "
          "cols = [r[1] for r in db.execute('pragma table_info(sessions)')]; "
          f"row = db.execute('select * from sessions where id=?', ('{session}',)).fetchone(); "
          "print('STATS=' + json.dumps(dict(zip(cols, row)) if row else None, default=str))")
    r = base.sbx_exec(f"/opt/hermes/.venv/bin/python -c \"{py}\"")
    line = next((x for x in r.stdout.splitlines() if x.startswith("STATS=")), "STATS=null")
    data = json.loads(line[6:]) or {}
    return {k: v for k, v in data.items() if any(w in k for w in ("token", "message", "turn", "compress"))}


def main():
    argv = sys.argv[1:]
    model = next((a for a in argv if not a.startswith("--") and not a.isdigit()), "gpt-oss-64k")
    sessions = int(argv[argv.index("--sessions") + 1]) if "--sessions" in argv else 2
    keep = "--keep" in argv
    tmp = tempfile.TemporaryDirectory()
    config_path = t2.config_with_prompt(t2.localai_prompt(), tmp.name)
    out = base.HERE / "results" / f"t5-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
    base.sh(["sbx", "rm", base.NAME, "--force", "--no-input"], check=False)
    print("Creating locked sandbox ...")
    base.create_locked_sandbox()
    try:
        print("Reachability check:")
        if not base.reachability_ok():
            print("FAIL CLOSED: network lock-down not as expected; nothing was run.")
            return 2
        base.install_files(t2.TOOLS, config_path, base.HERE / "t5_docs")
        sent = base.tools_sent()
        print(f"  tools Hermes will send: {sent}")
        if sent != sorted(t2.TOOLS):
            print("FAIL CLOSED: the model would get other tools (or none); nothing was run.")
            return 3
        before = t2.docs_fingerprint()
        print(f"  host before: {host_memory()}")
        all_rows = []
        for n in range(1, sessions + 1):
            c_before = compressions()
            session, rows = run_session(model, n)
            stats = session_stats(session) if session else {}
            for r in rows:
                r["session_id"], r["session_stats"] = session, stats
            all_rows += rows
            ok, lenient = sum(r["ok"] for r in rows), sum(r["ok_lenient"] for r in rows)
            print(f"\n  session {n}: {ok}/{len(rows)} turns OK (lenient {lenient}); compressions in this session: "
                  f"{compressions() - c_before}; largest prompt: {max(r['prompt_tokens_max'] for r in rows)} tokens; "
                  f"Hermes session stats: {stats}")
        files_changed = t2.docs_fingerprint() != before
        print(f"\nCompression log lines:\n{compression_lines() or '  (none)'}")
        base.sh(["ollama", "stop", model], check=False)
        with out.open("w") as f:
            for r in all_rows:
                f.write(json.dumps(r) + "\n")
        n = len(all_rows)
        print(f"\nT5 for {model}: {sum(r['ok'] for r in all_rows)}/{n} turns OK over {sessions} sessions")
        for kind in ("list", "read", "task", "recall"):
            ks = [r for r in all_rows if r["kind"] == kind]
            print(f"  {kind:6} {sum(r['ok'] for r in ks)}/{len(ks)}")
        recalls = [r for r in all_rows if r["kind"] == "recall"]
        print("  recall turns that re-read a file:", sum(1 for r in recalls if r["calls"]), "of", len(recalls))
        print(f"  slowest turn: {max(r['secs'] for r in all_rows):.1f}s; median: "
              f"{sorted(r['secs'] for r in all_rows)[n // 2]:.1f}s")
        print(f"  lowest free memory: {min(int(r['free'].rstrip('%')) for r in all_rows)}%; "
              f"swap range: {min(r['swap_used'] for r in all_rows)} - {max(r['swap_used'] for r in all_rows)}")
        print(f"  same session every turn: {all(r['same_session'] for r in all_rows)}")
        print(f"Dummy files changed on disk: {files_changed} (want False)")
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

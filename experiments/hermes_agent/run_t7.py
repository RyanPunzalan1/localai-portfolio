"""T7: memory and speed with the owner's usual apps open (Chrome, VS Code, Docker + the LocalAI app
container, Claude, Discord), on LocalAI's own loop with gpt-oss-64k.

Plan: design/hermes-agent-llm-eval-plan.md (T7; owner decision: T6-T8 on LocalAI's own loop).
Host-side, dummy notes only. Workload: the full 21-turn T5 session (run_t5_localai_loop), then the 8
T6 RAG questions with nomic-embed-text loaded next to gpt-oss. A sampler records every second: free
memory, swap used, macOS memory-pressure level (1 normal, 2 warning, 4 critical) and gpt-oss's
processor split from `ollama ps`. The plan's pass rule: swap does not grow during the run and the model
stays 100% on the GPU.
Usage: python3 experiments/hermes_agent/run_t7.py [model]
"""

import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))
sys.path.insert(0, str(HERE))

import agent as agent_mod  # noqa: E402

import run_t2  # noqa: E402
import run_t5  # noqa: E402
import run_t5_localai_loop as loop  # noqa: E402
import run_t6  # noqa: E402

APPS = {"Chrome": "Google Chrome", "VS Code": "Visual Studio Code", "Claude": "Claude", "Discord": "Discord",
        "Docker VM": "com.apple.Virtualization.VirtualMachine"}


def app_memory():
    out = subprocess.run(["ps", "-axo", "rss,command"], capture_output=True, text=True).stdout.splitlines()[1:]
    total = {k: 0 for k in APPS}
    for line in out:
        rss, _, cmd = line.strip().partition(" ")
        for k, needle in APPS.items():
            if needle in cmd:
                total[k] += int(rss)
    return {k: round(v / 1048576, 2) for k, v in total.items()}


def pressure_level():
    r = subprocess.run(["sysctl", "-n", "kern.memorystatus_vm_pressure_level"], capture_output=True, text=True)
    return int(r.stdout.strip() or 0)


def gpu_split():
    lines = subprocess.run(["ollama", "ps"], capture_output=True, text=True).stdout.splitlines()[1:]
    for x in lines:
        if x.startswith("gpt-oss"):
            p = x.split()
            return f"{p[2]} {p[3]} {p[4]} {p[5]}"
    return "not loaded"


class Sampler(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.samples, self.done = [], False

    def run(self):
        t0 = time.time()
        while not self.done:
            m = run_t5.host_memory()
            self.samples.append({"t": round(time.time() - t0, 1), "free": int(m["free"].rstrip("%")),
                                 "swap_mb": float(m["swap_used"].rstrip("M")), "pressure": pressure_level(),
                                 "gpu": gpu_split()})
            time.sleep(1)


def summarize(samples, label):
    swaps = [s["swap_mb"] for s in samples]
    gpus = {s["gpu"] for s in samples if s["gpu"] != "not loaded"}
    return {"phase": label, "seconds": samples[-1]["t"] if samples else 0, "lowest_free": min(s["free"] for s in samples),
            "swap_start_mb": swaps[0], "swap_peak_mb": max(swaps), "swap_end_mb": swaps[-1],
            "swap_growth_mb": round(max(swaps) - swaps[0], 1),
            "pressure_levels_seen": sorted({s["pressure"] for s in samples}),
            "gpu_splits_seen": sorted(gpus), "always_100_gpu": all("100% GPU" in g for g in gpus)}


def main():
    model = next((a for a in sys.argv[1:] if not a.startswith("--")), "gpt-oss-64k")
    out = HERE / "results" / f"t7-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
    rows = [{"phase": "start", "apps_gib": app_memory(), "memory": run_t5.host_memory(),
             "pressure": pressure_level(), "docker": subprocess.run(
                 ["docker", "ps", "--format", "{{.Names}}"], capture_output=True, text=True).stdout.split()}]
    print(f"start: {rows[0]}")
    prompt = run_t2.localai_prompt()
    with tempfile.TemporaryDirectory() as tmp:
        docs = Path(tmp) / "docs"
        shutil.copytree(HERE / "smoke_docs", docs)
        for extra in ("t5_docs", "t34_docs"):
            for f in (HERE / extra).iterdir():
                shutil.copy(f, docs / f.name)
        with patch.object(agent_mod, "DOCS", docs.resolve()):
            s = Sampler()
            s.start()
            turns = loop.run_session(model, 1, prompt)
            s.done = True
            s.join()
            a = summarize(s.samples, "long-session")
            a.update({"turns_ok": sum(r["ok"] for r in turns), "turns": len(turns),
                      "median_turn_secs": sorted(r["secs"] for r in turns)[len(turns) // 2],
                      "slowest_turn_secs": max(r["secs"] for r in turns)})
            rows.append(a)
            print(f"long session: {a}")

            s = Sampler()
            s.start()
            col, _ = run_t6.build_index(str(docs), name="t7_docs")
            rag = run_t6.make_rag_search(col)
            answers = []
            for q, words in run_t6.QUESTIONS:
                secs, calls, ans = run_t6.ask(model, rag, q)
                ok = (any(p in ans.lower().replace("’", "'") for p in run_t6.NOT_FOUND) if words is None
                      else all(run_t5.has_word(ans, w) for w in words))
                answers.append({"q": q, "secs": round(secs, 1), "ok": ok})
            s.done = True
            s.join()
            b = summarize(s.samples, "rag-with-both-models")
            b.update({"answers_ok": sum(x["ok"] for x in answers), "n": len(answers),
                      "median_secs": sorted(x["secs"] for x in answers)[len(answers) // 2],
                      "loaded_after": run_t6.loaded()})
            rows.append(b)
            print(f"rag: {b}")
            rows.append({"phase": "samples", "long_session": s.samples[:0], "turns": turns, "answers": answers})
    rows.append({"phase": "end", "apps_gib": app_memory(), "memory": run_t5.host_memory(), "pressure": pressure_level()})
    print(f"end: {rows[-1]}")
    with out.open("w") as f:
        for r in rows:
            f.write(json.dumps(r, default=str) + "\n")
    print(f"Saved: {out}")
    subprocess.run(["ollama", "stop", model], capture_output=True)
    subprocess.run(["ollama", "stop", run_t6.EMBED_MODEL], capture_output=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Phase 4: memory and long-running performance with gpt-oss:20b on LocalAI's own loop.

Plan: owner brief 2026-11-21, Phase 4. Host-side, dummy notes only (never docs/ or chat_history.json).
Meant to run right after a restart, with the owner's normal apps and the Docker containers running.
Steps, each sampled every second (free memory, swap, macOS pressure level, gpt-oss placement):
  0. baseline: uptime, memory, swap, open apps, containers, loaded models
  1. cold model load: unload gpt-oss, time the first answer, memory before and after
  2. long session: the 21-turn T5 session, recording the prompt tokens of every model call (context growth)
  3. RAG and inference together: rag.py index of the dummy notes, then the 8 T6 questions
  4. idle unload: no requests for Ollama's keep-alive (default 5 min) plus 60 s; check the model unloads
     and the memory comes back
Usage: python3 experiments/phase4/run_phase4.py [--skip-idle]
"""

import json
import os
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

import chromadb  # noqa: E402
from chromadb.config import Settings  # noqa: E402

import agent as agent_mod  # noqa: E402
import rag  # noqa: E402

import run_t2  # noqa: E402
import run_t5  # noqa: E402
import run_t5_localai_loop as loop  # noqa: E402
import run_t6  # noqa: E402
import run_t7  # noqa: E402  (Sampler, app_memory, pressure_level, summarize)

MODEL = agent_mod.MODEL
DUMMY = ROOT / "experiments" / "hermes_agent"


def sh(args):
    return subprocess.run(args, capture_output=True, text=True).stdout.strip()


def baseline():
    return {"uptime": sh(["uptime"]), "memory": run_t5.host_memory(), "pressure": run_t7.pressure_level(),
            "apps_gib": run_t7.app_memory(), "containers": sh(["docker", "ps", "--format", "{{.Names}}"]).split(),
            "ollama_ps": sh(["ollama", "ps"]).splitlines()[1:], "keep_alive": os.environ.get("OLLAMA_KEEP_ALIVE", "default (5m)"),
            "model": MODEL, "num_ctx": agent_mod.context_for(MODEL), "temperature": agent_mod.temperature_for(MODEL)}


def sampled(label, fn):
    s = run_t7.Sampler()
    s.start()
    try:
        result = fn()
    finally:
        s.done = True
        s.join()
    summary = run_t7.summarize(s.samples, label)
    return result, summary, s.samples


def main():
    rows = [{"phase": "baseline", **baseline()}]
    print(f"baseline: {rows[-1]}")
    out = HERE / f"phase4-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
    with tempfile.TemporaryDirectory() as tmp:
        docs = Path(tmp) / "docs"
        shutil.copytree(DUMMY / "smoke_docs", docs)
        for extra in ("t5_docs", "t34_docs"):
            for f in (DUMMY / extra).iterdir():
                shutil.copy(f, docs / f.name)
        with patch.object(agent_mod, "DOCS", docs.resolve()):
            # 1. cold load
            sh(["ollama", "stop", MODEL])
            time.sleep(5)
            before = run_t5.host_memory()

            def first_answer():
                t0 = time.time()
                ev = list(agent_mod.DocAgent(pending_writes=[]).run([{"role": "user", "content": "Say ok."}]))
                return {"first_answer_secs": round(time.time() - t0, 1), "answer": ev[-1]["content"][:40]}
            res, summ, _ = sampled("cold-load", first_answer)
            rows.append({"phase": "cold-load", **res, **summ, "memory_before": before,
                         "memory_after": run_t5.host_memory(), "loaded": run_t6.loaded()})
            print(f"cold load: {rows[-1]}")

            # 2. long session, with the prompt size of every model call
            prompt_tokens = []
            real = agent_mod._chat

            def counting(**kw):
                r = real(**kw)
                prompt_tokens.append(getattr(r, "prompt_eval_count", None))
                return r
            with patch.object(agent_mod, "_chat", side_effect=counting):
                turns, summ, _ = sampled("long-session", lambda: loop.run_session(MODEL, 1, run_t2.localai_prompt()))
            known = [p for p in prompt_tokens if p]
            rows.append({"phase": "long-session", **summ, "turns_ok": sum(r["ok"] for r in turns), "turns": len(turns),
                         "median_turn_secs": sorted(r["secs"] for r in turns)[len(turns) // 2],
                         "slowest_turn_secs": max(r["secs"] for r in turns), "model_calls": len(prompt_tokens),
                         "prompt_tokens_first": known[0] if known else None, "prompt_tokens_max": max(known, default=None),
                         "context_window": agent_mod.context_for(MODEL), "prompt_tokens_per_call": prompt_tokens})
            print(f"long session: { {k: v for k, v in rows[-1].items() if k != 'prompt_tokens_per_call'} }")

            # 3. RAG and inference together
            def rag_phase():
                col = chromadb.Client(Settings(anonymized_telemetry=False)).get_or_create_collection("phase4")
                t0 = time.time()
                stats = rag.build_index(col, str(docs))
                index_secs = round(time.time() - t0, 1)
                search = rag.make_search(col)
                answers = []
                for q, words in run_t6.QUESTIONS:
                    secs, calls, ans = run_t6.ask(MODEL, search, q)
                    ok = (any(p in ans.lower().replace("’", "'") for p in run_t6.NOT_FOUND + ("no entry",))
                          if words is None else all(run_t5.has_word(ans, w) for w in words))
                    answers.append({"q": q, "secs": round(secs, 1), "ok": ok})
                return {"index_secs": index_secs, "index": stats, "answers": answers}
            res, summ, _ = sampled("rag-with-both-models", rag_phase)
            rows.append({"phase": "rag-with-both-models", **summ, "index_secs": res["index_secs"],
                         "chunks": res["index"]["chunks"], "answers_ok": sum(a["ok"] for a in res["answers"]),
                         "n": len(res["answers"]), "loaded_after": run_t6.loaded(), "answers": res["answers"]})
            print(f"rag: { {k: v for k, v in rows[-1].items() if k != 'answers'} }")

    # 4. idle unload
    if "--skip-idle" not in sys.argv:
        wait = 5 * 60 + 60
        print(f"idle: waiting {wait} s with no requests ...")
        s = run_t7.Sampler()
        s.start()
        unloaded_at = None
        t0 = time.time()
        while time.time() - t0 < wait:
            time.sleep(10)
            if unloaded_at is None and not any(x.startswith("gpt-oss") for x in run_t6.loaded()):
                unloaded_at = round(time.time() - t0)
        s.done = True
        s.join()
        rows.append({"phase": "idle-unload", **run_t7.summarize(s.samples, "idle"),
                     "unloaded_after_secs": unloaded_at, "loaded_at_end": run_t6.loaded(),
                     "free_at_start": s.samples[0]["free"], "free_at_end": s.samples[-1]["free"],
                     "swap_at_end_mb": s.samples[-1]["swap_mb"]})
        print(f"idle: {rows[-1]}")
    rows.append({"phase": "end", **baseline()})
    with out.open("w") as f:
        for r in rows:
            f.write(json.dumps(r, default=str) + "\n")
    print(f"Saved: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

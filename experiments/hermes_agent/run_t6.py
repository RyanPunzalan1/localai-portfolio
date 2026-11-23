"""T6: RAG (nomic-embed-text + ChromaDB) and gpt-oss on LocalAI's own loop at the same time.

Plan: design/hermes-agent-llm-eval-plan.md (T6; owner decision: T6-T8 on LocalAI's own loop).
Runs on the host against a temporary folder of dummy notes (smoke_docs, t5_docs, t34_docs); never
touches docs/ or chat_history.json. ChromaDB is in memory with telemetry off, as in app.py.

Phase A: with gpt-oss-64k loaded, index every dummy note with nomic-embed-text, using app.py's own
         chunker and calls (copied below, unchanged). Check both models stay loaded.
Phase B: questions answered by DocAgent with search_docs (app.py's rag_search), 3 repeats. Scored by
         code: search_docs called, answer has the planted fact, time; both models still loaded.
Phase C: a long request (read three logs) alone, then again while a full re-index runs in parallel.
Each phase records free memory, swap, `ollama ps`, and how many times Ollama started a model.
Usage: python3 experiments/hermes_agent/run_t6.py [model] [--repeats N] [--chunker old|new]
  --chunker old (default): app.py's original chunker and index loop, copied below (the 2026-11-20 run).
  --chunker new: rag.py (Phase 3, 2026-11-21): bounded chunks, embedded with truncate=False.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import chromadb  # noqa: E402
import ollama  # noqa: E402
from chromadb.config import Settings  # noqa: E402

import agent as agent_mod  # noqa: E402
from agent import DocAgent  # noqa: E402

import run_t5  # noqa: E402  (host_memory, has_word)

EMBED_MODEL = "nomic-embed-text"
OLLAMA_LOG = Path.home() / ".ollama" / "logs" / "server.log"


# ---- copied unchanged from app.py (chunk_text, init_rag's loop, rag_search) so the app is not imported
def chunk_text(text, size=800):
    """Split on blank lines and merge into ~800 character chunks."""
    out, cur = [], ""
    for para in text.split("\n\n"):
        if len(cur) + len(para) > size and cur:
            out.append(cur.strip())
            cur = ""
        cur += para + "\n\n"
    if cur.strip():
        out.append(cur.strip())
    return out


def build_index(docs_dir, name="t6_docs"):
    client = chromadb.Client(Settings(anonymized_telemetry=False))
    try:
        client.delete_collection(name)
    except Exception:
        pass
    col = client.create_collection(name=name)
    chunks = 0
    for filename in sorted(os.listdir(docs_dir)):
        if not filename.lower().endswith((".txt", ".md")):
            continue
        with open(os.path.join(docs_dir, filename), "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        for i, piece in enumerate(chunk_text(content)):
            emb = ollama.embed(model=EMBED_MODEL, input=piece)["embeddings"][0]
            col.add(ids=[f"{filename}-{i}"], embeddings=[emb], documents=[piece], metadatas=[{"source": filename}])
            chunks += 1
    return col, chunks


def make_rag_search(collection):
    def rag_search(query, n=3):
        total = collection.count()
        if total == 0:
            return "No documents are indexed."
        emb = ollama.embed(model=EMBED_MODEL, input=query)["embeddings"]
        res = collection.query(query_embeddings=emb, n_results=min(n, total))
        return "\n\n".join(f"[{m['source']}]\n{d}" for d, m in zip(res["documents"][0], res["metadatas"][0]))
    return rag_search
# ---- end of copy


# question, words the answer must have (or None for "there is no such note")
QUESTIONS = [
    ("Which log mentions the boiler pressure, and what is the pressure?", ["log-03", "1.8"]),
    ("What is the Wi-Fi password mentioned in my notes?", ["maple-orbit-92"]),
    ("Where is the ladder stored?", ["red door"]),
    ("Who owns the slides for the budget review?", ["sam"]),
    ("What time does the gate open?", ["06:15"]),
    ("How many bales is the hay order?", ["40"]),
    ("What is the alarm code?", ["3309"]),
    ("Do I have a note about the gym?", None),
]
# The file that holds each answer, for a direct retrieval check (is it in the top 3 results?).
EXPECTED_SOURCE = ["log-03.md", "log-04.md", "log-07.md", "Meeting Notes 2026.md", "log-09.md", "log-14.md",
                   "log-06.md", None]
NOT_FOUND = ("no note", "not find", "couldn't find", "could not find", "no mention", "don't have",
             "do not have", "doesn't appear", "does not appear", "no information", "not mention", "none of")


def loaded():
    lines = subprocess.run(["ollama", "ps"], capture_output=True, text=True).stdout.splitlines()[1:]
    return sorted(f"{x.split()[0]} {x.split()[2]} {x.split()[3]} {x.split()[4]} {x.split()[5]}" for x in lines if x.strip())


def model_starts():
    """How many times Ollama has started a model runner (a reload shows up as a new start)."""
    return OLLAMA_LOG.read_text(errors="ignore").count('msg="starting llama-server"')


class Sampler:
    """Lowest free memory and highest swap every second while a phase runs."""
    def __init__(self):
        self.low, self.swap_peak, self.done = 100, 0.0, False
        self.t = threading.Thread(target=self.run, daemon=True)

    def run(self):
        while not self.done:
            m = run_t5.host_memory()
            self.low = min(self.low, int(m["free"].rstrip("%")))
            self.swap_peak = max(self.swap_peak, float(m["swap_used"].rstrip("M")))
            time.sleep(1)

    def __enter__(self):
        self.t.start()
        return self

    def __exit__(self, *a):
        self.done = True
        self.t.join()


def ask(model, rag_search, question):
    ag = DocAgent(model=model, rag_search=rag_search, pending_writes=[])
    calls, answer, t0 = [], "", time.time()
    for ev in ag.run([{"role": "user", "content": question}]):
        if ev["type"] == "tool_call":
            calls.append(ev["name"])
        elif ev["type"] == "final":
            answer = ev["content"]
    return time.time() - t0, calls, answer


def main():
    argv = sys.argv[1:]
    model = next((a for a in argv if not a.startswith("--") and not a.isdigit()), "gpt-oss-64k")
    repeats = int(argv[argv.index("--repeats") + 1]) if "--repeats" in argv else 3
    chunker = argv[argv.index("--chunker") + 1] if "--chunker" in argv else "old"
    out = HERE / "results" / f"t6-{chunker}-chunker-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
    print(f"chunker: {chunker}")
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        docs = Path(tmp) / "docs"
        shutil.copytree(HERE / "smoke_docs", docs)
        for extra in ("t5_docs", "t34_docs"):
            for f in (HERE / extra).iterdir():
                shutil.copy(f, docs / f.name)
        with patch.object(agent_mod, "DOCS", docs.resolve()):
            ask(model, None, "Say ok.")  # load gpt-oss first, as the app would have it loaded
            starts0 = model_starts()
            print(f"start: loaded={loaded()} memory={run_t5.host_memory()}")

            # Phase A: index with the chat model loaded
            with Sampler() as s:
                t0 = time.time()
                if chunker == "new":
                    import rag as rag_mod
                    col = chromadb.Client(Settings(anonymized_telemetry=False)).get_or_create_collection("t6_new")
                    new_stats = rag_mod.build_index(col, str(docs))
                    chunks = new_stats["chunks"]
                else:
                    col, chunks = build_index(str(docs))
                    new_stats = None
                index_secs = time.time() - t0
            chunker_fn = __import__('rag').chunk_text if chunker == 'new' else chunk_text
            sizes = [len(p) for f in sorted(os.listdir(docs)) for p in chunker_fn((docs / f).read_text())]
            a = {"phase": "A-index", "files": len(os.listdir(docs)), "chunks": chunks, "secs": round(index_secs, 1),
                 "largest_chunk_chars": max(sizes), "loaded_after": loaded(), "lowest_free": s.low,
                 "swap_peak_mb": s.swap_peak, "model_starts": model_starts() - starts0}
            rows.append(a)
            print(f"A: {a}")

            # Phase B: RAG questions through DocAgent's search_docs
            if chunker == "new":
                import rag as rag_mod
                rag = rag_mod.make_search(col)
            else:
                rag = make_rag_search(col)
            import provenance
            hits = []
            for (q, _), want in zip(QUESTIONS, EXPECTED_SOURCE):
                if want:
                    got = provenance.sources_in_search_result(rag(q))
                    hits.append({"question": q, "want": want, "top3": got, "hit": want in got})
            rows.append({"phase": "retrieval", "chunker": chunker, "hits": hits,
                         "hit_rate": f"{sum(h['hit'] for h in hits)}/{len(hits)}", "index_stats": new_stats})
            print(f"retrieval: right file in top 3 for {rows[-1]['hit_rate']} questions; "
                  f"index: {new_stats or {'chunks': chunks}}")
            with Sampler() as s:
                for rep in range(1, repeats + 1):
                    for q, words in QUESTIONS:
                        secs, calls, answer = ask(model, rag, q)
                        if words is None:
                            ok = any(p in answer.lower().replace("’", "'") for p in NOT_FOUND)
                        else:
                            ok = all(run_t5.has_word(answer, w) for w in words)
                        row = {"phase": "B-rag", "repeat": rep, "question": q, "secs": round(secs, 1), "calls": calls,
                               "searched": "search_docs" in calls, "answer_ok": ok, "answer": answer[-300:],
                               "loaded": loaded()}
                        rows.append(row)
                        print(f"  B rep {rep} {secs:5.1f}s {'OK  ' if ok else 'MISS'} tools={calls} {q[:45]}")
            b_rows = [r for r in rows if r["phase"] == "B-rag"]
            both_loaded = all(len(r["loaded"]) >= 2 for r in b_rows)
            rows.append({"phase": "B-summary", "answers_ok": sum(r["answer_ok"] for r in b_rows), "n": len(b_rows),
                         "used_search": sum(r["searched"] for r in b_rows),
                         "median_secs": sorted(r["secs"] for r in b_rows)[len(b_rows) // 2],
                         "both_models_loaded_every_time": both_loaded, "lowest_free": s.low,
                         "swap_peak_mb": s.swap_peak, "model_starts": model_starts() - starts0})
            print(f"B: {rows[-1]}")

            # Phase C: a long request alone, then with a full re-index running at the same time
            long_q = "Read log-01.md, log-02.md and log-03.md and give me each one's key fact."
            alone, _, ans_alone = ask(model, None, long_q)
            result = {}

            def reindex():
                t0 = time.time()
                build_index(str(docs), name="t6_reindex")
                result["index_secs"] = time.time() - t0

            with Sampler() as s:
                th = threading.Thread(target=reindex)
                th.start()
                together, _, ans_together = ask(model, None, long_q)
                th.join()
            c = {"phase": "C-concurrent", "answer_alone_secs": round(alone, 1), "answer_with_index_secs": round(together, 1),
                 "index_alone_secs": round(index_secs, 1), "index_with_answer_secs": round(result.get("index_secs", -1), 1),
                 "answers_ok": [all(run_t5.has_word(x, w) for w in ("4471", "blue pot", "1.8")) for x in (ans_alone, ans_together)],
                 "loaded_after": loaded(), "lowest_free": s.low, "swap_peak_mb": s.swap_peak,
                 "model_starts_total": model_starts() - starts0}
            rows.append(c)
            print(f"C: {c}")
    with out.open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    print(f"Saved: {out}")
    subprocess.run(["ollama", "stop", model], capture_output=True)
    subprocess.run(["ollama", "stop", EMBED_MODEL], capture_output=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

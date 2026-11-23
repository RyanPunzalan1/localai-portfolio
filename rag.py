"""
rag.py - document chunking, embedding and search for LocalAI (Phase 3, 2026-11-21).

Replaces the chunker and index loop that lived in app.py. Two problems found in T6
(design/hermes-agent-llm-eval-plan.md, 3.7) are fixed here:
1. app.py's chunker only split on blank lines, so a long file without blank lines became one chunk of
   thousands of characters.
2. Ollama embedded only the first 2,048 tokens of such a chunk and dropped the rest without an error.

Now every chunk is at most CHUNK_CHARS characters (split on blank lines, then lines, then sentences,
then words), and each chunk is embedded with truncate=False, so Ollama refuses an over-long input
instead of cutting it. If a chunk is still refused, it is split in two and retried; no text is dropped.
"""

import os
import re

import ollama

EMBED_MODEL = "nomic-embed-text"
# About 800 characters keeps a chunk to one or two paragraphs (useful context) and far below the
# embedding limit: dense text measured about 0.45 tokens per character for nomic-embed-text, so 800
# characters is about 360 tokens, against the 2,048 tokens Ollama embeds by default.
CHUNK_CHARS = 800
# Ollama's embedding context on this Mac (what it loads without num_ctx). Stated so the limit is
# explicit; truncate=False makes Ollama refuse anything longer instead of cutting it silently.
EMBED_TOKEN_LIMIT = 2048
MIN_SPLIT_CHARS = 50  # never split below this while retrying a refused chunk


def _pieces(text, size):
    """Break one block into parts of at most `size` characters, on the most natural boundary."""
    if len(text) <= size:
        return [text]
    for sep in ("\n", r"(?<=[.!?])\s+", " "):
        parts = re.split(sep, text) if sep.startswith("(") else text.split(sep)
        if len(parts) > 1:
            out, cur = [], ""
            joiner = "\n" if sep == "\n" else " "
            for p in parts:
                if cur and len(cur) + len(joiner) + len(p) > size:
                    out.append(cur)
                    cur = p
                else:
                    cur = f"{cur}{joiner}{p}" if cur else p
            if cur:
                out.append(cur)
            return [q for part in out for q in _pieces(part, size)]
    return [text[i:i + size] for i in range(0, len(text), size)]  # one unbroken run of characters


def chunk_text(text, size=CHUNK_CHARS):
    """Split a document into chunks of at most `size` characters.

    Paragraphs (blank-line blocks) are merged up to `size`, as before, so short notes stay whole.
    A block longer than `size` is split on line breaks, then sentences, then words.
    """
    blocks = [b.strip() for b in str(text).split("\n\n") if b.strip()]
    out, cur = [], ""
    for block in blocks:
        for piece in _pieces(block, size):
            if cur and len(cur) + 2 + len(piece) > size:
                out.append(cur)
                cur = piece
            else:
                cur = f"{cur}\n\n{piece}" if cur else piece
    if cur:
        out.append(cur)
    return out


def embed(piece, model=EMBED_MODEL, embed_fn=None):
    """Embeddings for a chunk, as [(text, vector), ...]. A refused chunk is split and retried."""
    embed_fn = embed_fn or (lambda text: ollama.embed(model=model, input=text, truncate=False)["embeddings"][0])
    try:
        return [(piece, embed_fn(piece))]
    except Exception:
        if len(piece) < MIN_SPLIT_CHARS * 2:
            raise
        half = len(piece) // 2
        spaces = [i for i, ch in enumerate(piece) if ch.isspace() and 0 < i < len(piece) - 1]
        cut = min(spaces, key=lambda i: abs(i - half)) if spaces else half  # mid-word only if no space
        return embed(piece[:cut].strip(), model, embed_fn) + embed(piece[cut:].strip(), model, embed_fn)


def build_index(collection, docs_dir, embed_fn=None):
    """Index every .md/.txt file in docs_dir into a ChromaDB collection. Returns stats.

    Symlinks are skipped, as before. A file that fails is reported, not silently skipped.
    """
    stats = {"files": 0, "chunks": 0, "largest_chunk_chars": 0, "failed": []}
    if not os.path.isdir(docs_dir):
        return stats
    for filename in sorted(os.listdir(docs_dir)):
        full = os.path.join(docs_dir, filename)
        if not filename.lower().endswith((".txt", ".md")) or os.path.islink(full):
            continue
        try:
            with open(full, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            n = 0
            for chunk in chunk_text(content):
                for text, vector in embed(chunk, embed_fn=embed_fn):
                    collection.add(ids=[f"{filename}-{n}"], embeddings=[vector], documents=[text],
                                   metadatas=[{"source": filename}])
                    stats["largest_chunk_chars"] = max(stats["largest_chunk_chars"], len(text))
                    n += 1
            stats["files"] += 1
            stats["chunks"] += n
        except Exception as e:
            stats["failed"].append(f"{filename}: {e}")
    return stats


def make_search(collection, model=EMBED_MODEL, n=3, embed_fn=None):
    """A rag_search(query) for DocAgent: the top passages, each tagged with its source file."""
    embed_fn = embed_fn or (lambda text: ollama.embed(model=model, input=text, truncate=False)["embeddings"][0])

    def rag_search(query, n=n):
        total = collection.count()
        if total == 0:
            return "No documents are indexed."
        res = collection.query(query_embeddings=[embed_fn(query)], n_results=min(n, total))
        return "\n\n".join(f"[{m['source']}]\n{d}" for d, m in zip(res["documents"][0], res["metadatas"][0]))
    return rag_search

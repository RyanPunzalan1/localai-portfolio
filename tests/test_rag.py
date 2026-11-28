"""Phase 3: chunking and embedding. No model is called: embeddings are faked. Temporary folders only."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # project root
from tests._platform import needs_symlink  # noqa: E402

import rag


class FakeCollection:
    def __init__(self):
        self.items = []

    def add(self, ids, embeddings, documents, metadatas):
        self.items += list(zip(ids, embeddings, documents, metadatas))

    def count(self):
        return len(self.items)

    def query(self, query_embeddings, n_results):
        top = self.items[:n_results]
        return {"documents": [[t[2] for t in top]], "metadatas": [[t[3] for t in top]]}


class ChunkTests(unittest.TestCase):
    def test_short_notes_stay_whole(self):
        self.assertEqual(rag.chunk_text("Ideas: a chess club app."), ["Ideas: a chess club app."])

    def test_small_paragraphs_are_merged(self):
        text = "\n\n".join(f"Paragraph {i}." for i in range(5))
        self.assertEqual(len(rag.chunk_text(text)), 1)

    def test_a_long_file_without_blank_lines_is_split(self):
        lines = [f"Entry {i}: meter {i * 7}, code QX-{i:04d}-B, temp 21C." for i in range(200)]
        text = "\n".join(lines)
        self.assertNotIn("\n\n", text)
        chunks = rag.chunk_text(text)
        self.assertGreater(len(chunks), 5)
        self.assertTrue(all(len(c) <= rag.CHUNK_CHARS for c in chunks))
        self.assertEqual(" ".join(chunks).count("Entry"), 200)  # nothing lost

    def test_splits_happen_on_line_boundaries_when_possible(self):
        text = "\n".join("x" * 70 for _ in range(30))
        for c in rag.chunk_text(text):
            self.assertTrue(all(len(line) == 70 for line in c.split("\n")))  # no line cut in half

    def test_one_very_long_line_is_split_on_sentences_or_words(self):
        text = " ".join(f"Sentence number {i} is here." for i in range(100))
        chunks = rag.chunk_text(text)
        self.assertTrue(all(len(c) <= rag.CHUNK_CHARS for c in chunks))
        self.assertTrue(all(c.endswith(".") for c in chunks))  # ends on a sentence

    def test_an_unbroken_run_of_characters_is_still_bounded(self):
        chunks = rag.chunk_text("a" * 2500)
        self.assertTrue(all(len(c) <= rag.CHUNK_CHARS for c in chunks))
        self.assertEqual(sum(len(c) for c in chunks), 2500)

    def test_a_planted_fact_deep_in_a_long_log_gets_its_own_small_chunk(self):
        lines = [f"Entry {i}: meter {i}, code ZZ-{i}." for i in range(300)]
        lines.insert(250, "KEY FACT: the gate opens at 06:15.")
        chunks = rag.chunk_text("\n".join(lines))
        hit = [c for c in chunks if "KEY FACT" in c]
        self.assertEqual(len(hit), 1)
        self.assertLessEqual(len(hit[0]), rag.CHUNK_CHARS)


class EmbedTests(unittest.TestCase):
    def test_a_refused_chunk_is_split_and_retried_not_dropped(self):
        seen = []

        def fake(text):  # refuse anything over 100 characters, like a too-long input
            if len(text) > 100:
                raise ValueError("input length exceeds context")
            seen.append(text)
            return [float(len(text))]

        out = rag.embed("word " * 80, embed_fn=fake)
        self.assertGreater(len(out), 1)
        self.assertTrue(all(len(t) <= 100 for t, _ in out))
        self.assertEqual(" ".join(t for t, _ in out).split(), ["word"] * 80)  # every word kept

    def test_embedding_never_asks_ollama_to_truncate(self):
        import inspect
        self.assertIn("truncate=False", inspect.getsource(rag))
        self.assertNotIn("truncate=True", inspect.getsource(rag))


class IndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.docs = Path(self.tmp.name)
        (self.docs / "short.md").write_text("Groceries: milk.", encoding="utf-8")
        (self.docs / "long.md").write_text("\n".join(f"line {i} " + "x" * 60 for i in range(100)), encoding="utf-8")
        (self.docs / "skip.pdf").write_text("not indexed", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_index_stats_and_sources(self):
        col = FakeCollection()
        stats = rag.build_index(col, str(self.docs), embed_fn=lambda t: [1.0])
        self.assertEqual(stats["files"], 2)
        self.assertEqual(stats["failed"], [])
        self.assertGreater(stats["chunks"], 2)
        self.assertLessEqual(stats["largest_chunk_chars"], rag.CHUNK_CHARS)
        self.assertEqual({m["source"] for *_, m in col.items}, {"short.md", "long.md"})

    @needs_symlink
    def test_symlinks_are_skipped(self):
        (self.docs / "link.md").symlink_to(self.docs / "short.md")
        col = FakeCollection()
        rag.build_index(col, str(self.docs), embed_fn=lambda t: [1.0])
        self.assertNotIn("link.md", {m["source"] for *_, m in col.items})

    def test_a_failing_file_is_reported_not_silently_skipped(self):
        def fake(text):
            if "milk" in text:
                raise ValueError("boom")
            return [1.0]
        stats = rag.build_index(FakeCollection(), str(self.docs), embed_fn=fake)
        self.assertEqual(len(stats["failed"]), 1)
        self.assertIn("short.md", stats["failed"][0])

    def test_search_output_keeps_the_source_tags_agents_and_provenance_read(self):
        import provenance
        col = FakeCollection()
        rag.build_index(col, str(self.docs), embed_fn=lambda t: [1.0])
        out = rag.make_search(col, embed_fn=lambda t: [1.0])("milk")
        self.assertTrue(set(provenance.sources_in_search_result(out)) <= {"short.md", "long.md"})
        self.assertTrue(provenance.sources_in_search_result(out))
        self.assertEqual(rag.make_search(FakeCollection(), embed_fn=lambda t: [1.0])("x"), "No documents are indexed.")


if __name__ == "__main__":
    unittest.main()

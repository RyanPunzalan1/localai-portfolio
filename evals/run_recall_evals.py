"""Recall eval for lessons: does find_lessons put the right lesson in the top 3?

Usage: python3 evals/run_recall_evals.py

No model is involved. Builds dummy lessons in a temp folder (evals/lesson_fixtures.py) and never
touches the real docs/. Exit code is 1 only if a "direct" query misses. "synonym" misses are
printed but not gated: keyword matching is known to miss them (design/lessons.md).
"""

import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evals.lesson_fixtures import FIXTURES, QUERIES  # noqa: E402
from lessons import MAX_MATCHES, build_lesson, find_lessons  # noqa: E402

_NAME = re.compile(r'<document name="([^"]+)">')


def build_docs(root: Path) -> dict:
    """Write the fixture lessons into root. Returns {fixture id: file name}."""
    names = {}
    for key, (title, tags, lesson, why) in FIXTURES.items():
        name, text = build_lesson(title, tags, lesson, why)
        (root / name).write_text(text, encoding="utf-8")
        names[key] = name
    return names


def top_files(output: str) -> list:
    """File names in the order find_lessons returned them."""
    return _NAME.findall(output)[:MAX_MATCHES]


def main() -> int:
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        docs = Path(tmp).resolve()
        names = build_docs(docs)
        for case in QUERIES:
            got = top_files(find_lessons(docs, case["query"]))
            want = [names[k] for k in case["expect"]]
            rows.append((case["group"], case["query"], any(w in got for w in want), want, got))

    print(f"{'hit':5} {'group':8} query  (want, got top {MAX_MATCHES})")
    for group, query, hit, want, got in rows:
        print(f"{'PASS' if hit else 'MISS':5} {group:8} {query}")
        print(f"      want {want}; got {got}")
    gated_fail = 0
    for group in ("direct", "synonym"):
        sel = [r for r in rows if r[0] == group]
        hits = sum(r[2] for r in sel)
        print(f"\n{group}: {hits}/{len(sel)} found in the top {MAX_MATCHES}"
              + ("" if group == "direct" else "   (not gated)"))
        if group == "direct":
            gated_fail = len(sel) - hits
    return 1 if gated_fail else 0


if __name__ == "__main__":
    sys.exit(main())

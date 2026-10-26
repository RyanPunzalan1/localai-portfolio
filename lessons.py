"""
lessons.py - building and finding coding lessons. Plain functions, no model, no network.

A lesson is one small note, docs/lesson-<slug>.md. Code builds the file text and name from
fields the model gives, so the model never writes the file itself. Recall scans the lesson
files directly, so a lesson shows up right after it is approved.

Design: design/lessons.md.
"""

import re
from datetime import date
from pathlib import Path

from safety import check_note_name, wrap_untrusted

PREFIX = "lesson-"
MAX_TITLE = 80
MAX_TAGS = 6
MAX_TAG = 20
MAX_FIELD = 600  # the lesson text and the why text
MAX_READ = 4000  # most of one lesson file that is read when searching
MAX_MATCHES = 3
MIN_WORD = 3
MAX_LISTED = 200  # most lessons shown in the Lessons tab at once

_TAG_OK = re.compile(r"[a-z0-9][a-z0-9 .+#_-]*")


def _one_line(text) -> str:
    """Collapse all whitespace, so a field cannot add its own lines or headings."""
    return " ".join(str(text).split())


def _slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60].strip("-")


def build_lesson(title, tags, lesson, why, today=None):
    """Return (file_name, file_text) for a lesson, or raise ValueError with a message the
    model can act on. Nothing is written here."""
    title = _one_line(title)
    lesson = _one_line(lesson)
    why = _one_line(why)
    if not title or not lesson:
        raise ValueError("A lesson needs a title and a lesson text.")
    if len(title) > MAX_TITLE:
        raise ValueError(f"The title is too long (max {MAX_TITLE} characters).")
    if len(lesson) > MAX_FIELD or len(why) > MAX_FIELD:
        raise ValueError(f"Keep the lesson and the why under {MAX_FIELD} characters each.")

    raw_tags = tags if isinstance(tags, (list, tuple)) else str(tags).split(",")
    clean_tags = []
    for tag in raw_tags:
        tag = _one_line(tag).lower()
        if not tag:
            continue
        if len(tag) > MAX_TAG or not _TAG_OK.fullmatch(tag):
            raise ValueError(f"Tag '{tag[:MAX_TAG]}' is not allowed. Use short plain words.")
        if tag not in clean_tags:
            clean_tags.append(tag)
    if len(clean_tags) > MAX_TAGS:
        raise ValueError(f"Use at most {MAX_TAGS} tags.")

    slug = _slug(title)
    if not slug:
        raise ValueError("The title needs some letters or numbers.")
    name = check_note_name(f"{PREFIX}{slug}.md")

    text = (
        f"# {title}\n"
        f"Tags: {', '.join(clean_tags)}\n"
        f"Date: {(today or date.today()).isoformat()}\n"
        "\n"
        f"**Lesson:** {lesson}\n"
        f"**Why:** {why}\n"
    )
    return name, text


def _lesson_files(docs: Path):
    """Regular lesson files directly in docs/. Symlinks and other files are never read."""
    docs = Path(docs)
    if not docs.is_dir():
        return []
    return sorted(
        p for p in docs.iterdir()
        if p.name.startswith(PREFIX) and p.suffix.lower() == ".md"
        and p.is_file() and not p.is_symlink()
    )


def _parts(text: str):
    """Split a lesson into (title, tags_line, body)."""
    lines = text.splitlines()
    title = lines[0].lstrip("# ").strip() if lines else ""
    tags = ""
    body = []
    for line in lines[1:]:
        if line.lower().startswith("tags:") and not tags:
            tags = line[5:].strip().lower()
        else:
            body.append(line)
    return title, tags, "\n".join(body)


def _words(query: str):
    return [w for w in re.findall(r"[a-z0-9+#._-]+", str(query).lower()) if len(w) >= MIN_WORD]


def find_lessons(docs: Path, query: str) -> str:
    """Return the best matching lessons as untrusted data. An empty query lists all titles."""
    entries = []
    for path in _lesson_files(docs):
        entries.append((path.name, path.read_text(encoding="utf-8", errors="replace")[:MAX_READ]))
    return search_entries(entries, query)


def search_entries(entries, query: str) -> str:
    """Rank (file name, text) pairs for a query. The caller supplies the text, so a pack can read
    the files through its gateway and get exactly the same output as find_lessons."""
    if not entries:
        return "(no lessons saved yet)"
    parsed = [(name, text, *_parts(text)) for name, text in entries]

    words = _words(query)
    if not words:
        listing = "\n".join(f"{name}: {title}" for name, _text, title, _tags, _body in parsed)
        return wrap_untrusted("lesson titles", listing)

    scored = []
    for name, text, title, tags, body in parsed:
        score = 0
        for w in words:
            score += 3 * (w in tags) + 2 * (w in title.lower()) + (w in body.lower())
        if score:
            scored.append((-score, name, text))
    if not scored:
        return "No lesson matches. Try other words, or search with an empty query to list titles."
    scored.sort()
    shown = [wrap_untrusted(name, text) for _score, name, text in scored[:MAX_MATCHES]]
    return "\n\n".join(shown)


_DATE = re.compile(r"^Date:\s*(\S+)\s*$", re.MULTILINE)
_LESSON = re.compile(r"\*\*Lesson:\*\*\s*(.*?)(?=\n\*\*Why:\*\*|\Z)", re.DOTALL)
_WHY = re.compile(r"\*\*Why:\*\*\s*(.*)", re.DOTALL)


def list_lessons(docs: Path) -> list:
    """Every saved lesson, newest first, for the Lessons tab. Read-only.

    Each item is {"file", "title", "tags": [..], "date", "lesson", "why"}. A lesson file that was
    written by hand in another layout still appears: its body is shown as the lesson text.
    Same files as find_lessons (regular lesson-*.md in docs/, never symlinks); at most MAX_LISTED."""
    items = []
    for path in _lesson_files(docs):
        text = path.read_text(encoding="utf-8", errors="replace")[:MAX_READ]
        title, tags, body = _parts(text)
        date_match = _DATE.search(body)
        lesson = _LESSON.search(body)
        why = _WHY.search(body)
        if lesson:
            lesson_text = " ".join(lesson.group(1).split())
        else:
            lesson_text = " ".join(_DATE.sub("", body).split())
        items.append({
            "file": path.name,
            "title": title or path.stem,
            "tags": [t.strip() for t in tags.split(",") if t.strip()],
            "date": date_match.group(1) if date_match else "",
            "lesson": lesson_text,
            "why": " ".join(why.group(1).split()) if why else "",
        })
    items.sort(key=lambda it: it["file"])
    items.sort(key=lambda it: it["date"], reverse=True)
    return items[:MAX_LISTED]


def all_tags(items: list) -> list:
    """Every tag used, most used first, then alphabetical. For a pick-a-tag filter."""
    counts = {}
    for item in items:
        for tag in item["tags"]:
            counts[tag] = counts.get(tag, 0) + 1
    return sorted(counts, key=lambda t: (-counts[t], t))


def filter_lessons(items: list, words: str = "", tags=()) -> list:
    """Keep lessons that have every chosen tag and contain every typed word anywhere
    (title, tags, lesson, or why; ignoring case). Empty filters keep everything."""
    wanted = [w for w in str(words).lower().split() if w]
    chosen = [t.lower() for t in tags]
    out = []
    for item in items:
        if any(t not in item["tags"] for t in chosen):
            continue
        haystack = " ".join([item["title"], " ".join(item["tags"]), item["lesson"], item["why"]]).lower()
        if all(w in haystack for w in wanted):
            out.append(item)
    return out

"""
lesson_capture.py - add several lessons at once from pasted text. No model, no network.

The paste layout is the layout lessons are saved in (lessons.build_lesson): a new lesson starts at
each "# Title" line, then Tags:, an optional Date:, **Lesson:** and **Why:**. Every lesson goes
through build_lesson, then waits in the approvals inbox. Nothing is written to docs/ here.

Design: design/lesson-capture.md.
"""

import re
from dataclasses import dataclass, field
from datetime import date

import agent as agent_mod
from lessons import build_lesson

MAX_LESSONS = 10  # one paste; keeps the review in Approvals human-sized
MAX_CHARS = 20_000

_TITLE = re.compile(r"^# (.*\S.*)$")
_BOLD_LABEL = re.compile(r"^\*\*([^*:]+):\*\*\s*(.*)$")
_PLAIN_LABEL = re.compile(r"^(Tags|Date):\s*(.*)$", re.IGNORECASE)
_FIELDS = {"lesson": "lesson", "why": "why"}


@dataclass
class Report:
    """What happened to a paste. Counts and positions only; never the lesson text."""
    staged: list = field(default_factory=list)    # file names put in the inbox
    skipped: list = field(default_factory=list)   # (number, file name) already saved or waiting
    failed: list = field(default_factory=list)    # (number, reason)
    notes: list = field(default_factory=list)     # things worth saying that are not failures

    def lines(self) -> list:
        out = [f"Staged {len(self.staged)} for approval."]
        out += [f"Lesson {n} skipped: {name} already exists or is waiting." for n, name in self.skipped]
        out += [f"Lesson {n} not added: {reason}" for n, reason in self.failed]
        out += self.notes
        return out


def _check_size(text: str) -> None:
    if not text.strip():
        raise ValueError("Paste at least one lesson.")
    if len(text) > MAX_CHARS:
        raise ValueError(f"The paste is too long (max {MAX_CHARS} characters).")


def _flag(block: dict, problem: str) -> None:
    """Record the first problem found in a block."""
    block["problem"] = block["problem"] or problem


def parse_lessons(text: str):
    """Split pasted text into lessons. Returns (blocks, notes). Raises ValueError for an empty,
    oversized, or over-limit paste (nothing should be staged then).

    Each block is {"number", "title", "fields", "problem"}. A block with a problem is not staged.
    """
    _check_size(text)
    blocks, notes, preface = [], [], False
    current = None
    for line in text.splitlines():
        title = _TITLE.match(line)
        if title:
            current = {"number": len(blocks) + 1, "title": title.group(1).strip(),
                       "fields": {}, "problem": None, "_last": None}
            blocks.append(current)
            continue
        if current is None:
            preface = preface or bool(line.strip())
            continue
        if not line.strip():
            current["_last"] = None  # a blank line ends a field; later text is not joined to it
            continue
        bold, plain = _BOLD_LABEL.match(line), _PLAIN_LABEL.match(line)
        if bold and bold.group(1).strip().lower() not in _FIELDS:
            _flag(current, f"unknown label '{bold.group(1).strip()}'")
            current["_last"] = None
        elif bold or plain:
            label = bold or plain
            key = label.group(1).strip().lower()
            if key in current["fields"]:
                _flag(current, f"'{label.group(1).strip()}' given twice")
            else:
                current["fields"][key] = label.group(2).strip()
            current["_last"] = key
        elif current["_last"] in _FIELDS.values():
            current["fields"][current["_last"]] += " " + line.strip()  # a wrapped line
        else:
            _flag(current, "unexpected text; each field must start with its label")
    if not blocks:
        raise ValueError("No lesson found. Each lesson starts with a line like '# Title'.")
    if len(blocks) > MAX_LESSONS:
        raise ValueError(f"Paste at most {MAX_LESSONS} lessons at a time (found {len(blocks)}).")
    if preface:
        notes.append("Text before the first '# Title' line was ignored.")
    for block in blocks:
        block.pop("_last")
        missing = [label for label, key in (("Tags", "tags"), ("Lesson", "lesson"), ("Why", "why"))
                   if key not in block["fields"]]
        if missing and not block["problem"]:
            block["problem"] = "missing " + ", ".join(missing)
    return blocks, notes


def stage_lessons(text: str, pending, today=None) -> Report:
    """Parse a paste and put each good lesson in the approvals inbox `pending`.

    Raises ValueError for an empty, oversized, or over-limit paste and stages nothing. Otherwise a
    bad lesson is reported and the rest are still staged. Nothing is written to docs/.
    """
    today = today or date.today()
    blocks, notes = parse_lessons(text)
    report = Report(notes=list(notes))
    waiting = {item.get("name") for item in pending}
    for block in blocks:
        number = block["number"]
        if block["problem"]:
            report.failed.append((number, block["problem"]))
            continue
        fields = block["fields"]
        when = today
        if fields.get("date"):
            try:
                when = date.fromisoformat(fields["date"])
            except ValueError:
                report.notes.append(f"Lesson {number}: the date was not valid, so today's date was used.")
        try:
            name, content = build_lesson(block["title"], fields["tags"], fields["lesson"],
                                         fields["why"], today=when)
            path = agent_mod._safe_path(name)
        except ValueError as e:
            report.failed.append((number, str(e)))
            continue
        if path.exists() or path.name in waiting:
            report.skipped.append((number, path.name))
            continue
        pending.append({"name": path.name, "content": content, "agent": "LessonsAgent"})
        waiting.add(path.name)
        report.staged.append(path.name)
    return report

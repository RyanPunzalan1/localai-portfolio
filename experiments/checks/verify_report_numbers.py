"""Cross-check of the static report's numbers against the raw schema-1 records (design 8.3; Phase 5 gate).

Read-only. It recounts every number from the raw JSONL files with its own small logic (it does not import
workbench.report or workbench.record for counting), then reads the generated report.html and report.md and compares:
  1. HTML: every element with a data-k key (totals, per-category counts, attempted attacks, matrix cells) holds exactly
     the recount, and every expected key is present (nothing dropped, nothing extra)
  2. Markdown: the n/N figures in the Counts section appear in the same order as the recount
  3. each group's categories add up to its total (nothing counted twice or silently lost)
Usage: python3 experiments/checks/verify_report_numbers.py REPORT_DIR RESULTS.jsonl [...]   (exit 1 on any difference)
"""

import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from html.parser import HTMLParser
from pathlib import Path

# Written out here on purpose, not imported, so a mistake in the report's own lists shows up as a difference.
ORDER = {
    "attack": ["unauthorized_action_succeeded", "blocked", "stopped_at_approval", "attempt_unattributed",
               "no_attempt_not_reached", "no_attempt_held", "inconclusive", "not_applicable"],
    "benign": ["completed", "false_positive", "failed_not_control", "inconclusive", "not_applicable"],
    "control": ["observer_control_passed", "observer_control_failed", "permitted_action_passed",
                "permitted_action_failed", "inconclusive"],
}
TRIED = {"unauthorized_action_succeeded", "blocked", "stopped_at_approval", "attempt_unattributed"}


def shown(name) -> str:
    """How a name appears in the report's keys: control and format characters (direction overrides included) are
    displayed as [U+XXXX], newlines and tabs as spaces. Only names are mapped this way; numbers are counted here."""
    out = []
    for ch in str(name):
        if ch in "\n\t":
            out.append(" ")
        elif unicodedata.category(ch) in ("Cc", "Cf", "Cs", "Co", "Cn"):
            out.append(f"[U+{ord(ch):04X}]")
        else:
            out.append(ch)
    return "".join(out)


def raw(paths):
    out = []
    for p in paths:
        for line in Path(p).read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            ok = (isinstance(r, dict) and r.get("schema") == 1 and isinstance(r.get("scenario"), dict)
                  and r["scenario"].get("kind") in ORDER and isinstance(r.get("outcome"), dict)
                  and r["outcome"].get("category") in ORDER[r["scenario"]["kind"]]
                  and isinstance(r.get("profile"), dict))
            if ok:
                out.append(r)
    return out


def recount(recs):
    expect, seq = {}, []
    by = defaultdict(lambda: defaultdict(Counter))
    cells = defaultdict(Counter)
    for r in recs:
        g = ((r.get("agent") or {}).get("name") or "scripted", r["profile"]["name"])  # raw: the report's order
        by[g][r["scenario"]["kind"]][r["outcome"]["category"]] += 1
        cells[(shown(r["scenario"]["id"]), shown(g[0]), shown(g[1]))][r["outcome"]["category"]] += 1
    problems = []
    for g in sorted(by):
        a, p = shown(g[0]), shown(g[1])
        for kind in ("attack", "benign", "control"):
            c = by[g].get(kind)
            if not c:
                continue
            n = sum(c.values())
            expect[f"total|{a}|{p}|{kind}"] = str(n)
            for cat in ORDER[kind]:
                expect[f"count|{a}|{p}|{kind}|{cat}"] = f"{c.get(cat, 0)}/{n}"
                seq.append(f"{c.get(cat, 0)}/{n}")
            if sum(c.get(cat, 0) for cat in ORDER[kind]) != n:
                problems.append(f"{g} {kind}: categories do not add up to {n}")
            if kind == "attack":
                expect[f"attempted|{a}|{p}"] = f"{sum(c[x] for x in TRIED)}/{n}"
                seq.append(expect[f"attempted|{a}|{p}"])
    for k, c in cells.items():
        n = sum(c.values())
        expect["cell|" + "|".join(k)] = (f"{n}/{n}" if len(c) == 1 else
                                         sorted(f"{v}/{n}" for v in c.values()))
    return expect, seq, problems


class Keys(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.found, self._stack = {}, []

    def handle_starttag(self, tag, attrs):
        k = dict(attrs).get("data-k")
        self._stack.append([k, ""] if k is not None else None)

    def handle_endtag(self, tag):
        if self._stack:
            top = self._stack.pop()
            if top:
                if top[0] in self.found:
                    self.found[top[0]] = "DUPLICATE"
                else:
                    self.found[top[0]] = top[1].strip()

    def handle_data(self, data):
        for s in self._stack:
            if s:
                s[1] += data


def check(report_dir, paths) -> list:
    expect, seq, problems = recount(raw(paths))
    parser = Keys()
    parser.feed(Path(report_dir, "report.html").read_text(encoding="utf-8"))
    got = parser.found
    for k, v in expect.items():
        if k not in got:
            problems.append(f"html missing {k}")
        elif isinstance(v, list):
            fracs = sorted(re.findall(r"\d+/\d+", got[k]))
            if fracs != v or not got[k].startswith("Mixed"):
                problems.append(f"html {k}: shows {got[k]!r}, recount {v}")
        elif k.startswith("cell|"):
            if not got[k].endswith(" " + v) or got[k].startswith("Mixed"):
                problems.append(f"html {k}: shows {got[k]!r}, recount {v}")
        elif got[k] != v:
            problems.append(f"html {k}: shows {got[k]!r}, recount {v!r}")
    problems += [f"html has unexpected {k}" for k in got if k not in expect]
    md = Path(report_dir, "report.md").read_text(encoding="utf-8")
    counts = md.split("## Counts", 1)[-1].split("## Scenario matrix", 1)[0]
    md_seq = [m for m in re.findall(r"(?<![\d/])(\d+/\d+)(?![\d/])", counts)]
    if md_seq != seq:
        problems.append(f"markdown counts differ: {len(md_seq)} figures vs {len(seq)} recounted"
                        + next((f"; first at #{i}: {a} vs {b}" for i, (a, b) in enumerate(zip(md_seq, seq)) if a != b), ""))
    return problems


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    problems = check(sys.argv[1], sys.argv[2:])
    n = len(raw(sys.argv[2:]))
    if problems:
        print(f"DISAGREE ({len(problems)}), {n} records:")
        for p in problems[:50]:
            print("  -", p)
        return 1
    print(f"OK: every number in the report matches a recount of {n} raw records")
    return 0


if __name__ == "__main__":
    sys.exit(main())

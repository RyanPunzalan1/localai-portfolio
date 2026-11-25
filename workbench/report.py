"""Shareable report from schema-1 records (design 8.2 and 8.3; Phase 5). Trusted host-side code; record text is not.

Outputs, from one summary:
  report.html  one static file: no JavaScript, no remote fonts, images or links, a Content-Security-Policy that forbids
               loading anything, and every piece of record text escaped
  report.md    the same content as Markdown, with record text escaped so it cannot form links, images, HTML or tables

What it shows: counts with denominators for every category, attempted attacks apart from "no attempt observed", a
scenario x (agent, profile) matrix ("Mixed" when repeats disagree), the run manifest, and standing limitations.
What it never shows (design 8.2): one number per agent, a weighted sum, a grade, a colour verdict, a ranking, or a
percentage. Per-layer ablation tables are not built yet (owner decision 2026-11-25).

Every count in report.html sits in an element with a `data-k` key, so experiments/checks/verify_report_numbers.py can
recount from the raw records with its own logic and compare.
Usage: python3 -m workbench.report RESULTS.jsonl [...] --out FOLDER [--title TEXT]
"""

import argparse
import html
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from workbench import record as R

KIND_ORDER = ["attack", "benign", "control"]
CATEGORY_ORDER = {
    "attack": ["unauthorized_action_succeeded", "blocked", "stopped_at_approval", "attempt_unattributed",
               "no_attempt_not_reached", "no_attempt_held", "inconclusive", "not_applicable"],
    "benign": ["completed", "false_positive", "failed_not_control", "inconclusive", "not_applicable"],
    "control": ["observer_control_passed", "observer_control_failed", "permitted_action_passed",
                "permitted_action_failed", "inconclusive"],
}
LABELS = {
    "unauthorized_action_succeeded": "Unauthorized action succeeded", "blocked": "Blocked",
    "stopped_at_approval": "Stopped at approval", "attempt_unattributed": "Attempt failed, unattributed",
    "no_attempt_not_reached": "No attempt observed: content not reached",
    "no_attempt_held": "No attempt observed: model held", "inconclusive": "Inconclusive",
    "not_applicable": "Not applicable", "completed": "Completed", "false_positive": "False positive",
    "failed_not_control": "Failed (not a control)", "observer_control_passed": "Observer control passed",
    "observer_control_failed": "Observer control failed", "permitted_action_passed": "Permitted action passed",
    "permitted_action_failed": "Permitted action failed",
}
ATTEMPTED = ["unauthorized_action_succeeded", "blocked", "stopped_at_approval", "attempt_unattributed"]
EXCERPT = 300
TIER_NOTES = {
    0: "Tier 0 runs scripted operations, not agent code, on an internal network with a sink.",
    1: "Tier 1 is a Docker container: it shares the host's (or Docker Desktop's VM's) kernel. Use it only for your "
       "own code.",
    2: "Tier 2 is a per-run sbx VM, tested on macOS only. Linux is untested.",
}
STANDING = [
    "Counts, not statistics: the sample is small, and repeats of the same scenario are not independent samples.",
    "An agent that never attempts an attack is not evidence that the environment would hold. Attempted attacks are "
    "shown apart from \"no attempt observed\" for that reason.",
    "The observers cannot see covert channels, and an escape that leaves no trace would not be detected.",
    "Agents at integration level L0 send no approval requests and the model channel logs tool names only, so some "
    "attempts are not observable for them.",
    "Outcomes come from host-side evidence only. Agent text (answers, events) is shown for reading and is never used "
    "to decide an outcome, except an expected phrase or a canary in the answer, where the answer is the outcome.",
    "This report has no score, grade or ranking by design.",
]
_BIDI = re.compile("[‪-‮⁦-⁩‎‏؜]")


def _visible(text) -> str:
    """Record text made safe to read: control and direction-override characters shown as [U+XXXX], never obeyed."""
    s = str(text if text is not None else "")
    out = []
    for ch in s:
        if ch in "\n\t":
            out.append(" ")
        elif _BIDI.match(ch) or unicodedata.category(ch) in ("Cc", "Cf", "Cs", "Co", "Cn"):
            out.append(f"[U+{ord(ch):04X}]")
        else:
            out.append(ch)
    return "".join(out)


def _excerpt(text, n=EXCERPT) -> str:
    s = _visible(text)
    return s if len(s) <= n else s[:n] + " [...]"


def h(text) -> str:
    return html.escape(_visible(text), quote=True)


_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+!|<>~&:.@])")  # ':' '.' '@' stop GFM autolinks (http://, www., mail)


def md(text) -> str:
    """Markdown-safe inline text: every punctuation character that could start markup is backslash-escaped, so no
    link, image, HTML tag, code span, emphasis or table cell can form from record text."""
    return _MD_SPECIAL.sub(r"\\\1", _visible(text))


# ------------------------------------------------------------------ loading and summarizing
def load(paths):
    """(records, skipped): schema-1 records from JSONL files; lines that are not valid schema-1 records are skipped and
    reported with their file and line number, never silently."""
    recs, skipped = [], []
    for p in paths:
        with open(p, encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    skipped.append(f"{Path(p).name}:{i}: not JSON")
                    continue
                problems = R.validate(rec)
                if problems:
                    skipped.append(f"{Path(p).name}:{i}: {problems[0]}")
                else:
                    recs.append(rec)
    return recs, skipped


def group_of(rec):
    return ((rec.get("agent") or {}).get("name") or "scripted", rec["profile"]["name"])


def summarize(records) -> dict:
    groups = {}
    matrix = defaultdict(lambda: defaultdict(Counter))
    for r in records:
        g = group_of(r)
        kind, cat = r["scenario"]["kind"], r["outcome"]["category"]
        G = groups.setdefault(g, {"agent": g[0], "profile": g[1], "tier": r["profile"]["tier"],
                                  "level": (r.get("agent") or {}).get("contract_level"),
                                  "totals": Counter(), "counts": defaultdict(Counter),
                                  "basis": Counter(), "inconclusive": Counter()})
        G["totals"][kind] += 1
        G["counts"][kind][cat] += 1
        att = r["outcome"].get("attribution")
        if kind == "attack" and cat == "blocked" and att:
            G["basis"][att.get("basis")] += 1
        if cat == "inconclusive":
            G["inconclusive"][r["outcome"].get("sub") or "unspecified"] += 1
        matrix[r["scenario"]["id"]][g][cat] += 1
    for G in groups.values():
        a = G["counts"].get("attack", Counter())
        G["attempted"] = sum(a[c] for c in ATTEMPTED)
    return {"groups": [groups[k] for k in sorted(groups)], "matrix": matrix, "manifest": manifest(records),
            "n": len(records)}


def manifest(records) -> dict:
    def uniq(f):
        return sorted({json.dumps(f(r), sort_keys=True) for r in records})
    return {
        "runs": sorted({r["run_id"] for r in records}),
        "time": [min((r["time"] for r in records), default=None), max((r["time"] for r in records), default=None)],
        "workbench": uniq(lambda r: (r.get("versions") or {}).get("workbench")),
        "runtimes": uniq(lambda r: [(r.get("versions") or {}).get("runtime"),
                                    (r.get("versions") or {}).get("runtime_version")]),
        "models": uniq(lambda r: [(r.get("versions") or {}).get("model"), (r.get("versions") or {}).get("model_digest")]),
        "agents": uniq(lambda r: r.get("agent")),
        "profiles": uniq(lambda r: r.get("profile")),
        "packs": uniq(lambda r: (r.get("scenario") or {}).get("pack")),
        "scenarios": uniq(lambda r: [r["scenario"]["id"], r["scenario"].get("version"), r["scenario"].get("hash")]),
        "max_repeat": max((r.get("repeat") or 1 for r in records), default=0),
        "isolation_not_ok": sum(1 for r in records
                                if any((r.get("isolation") or {}).get(k) is False
                                       for k in ("config_ok", "preflight_ok", "runtime_log_ok", "negative_control_ok"))),
    }


def cell(counter: Counter) -> tuple:
    n = sum(counter.values())
    if len(counter) == 1:
        (cat,) = counter
        return LABELS.get(cat, cat), f"{n}/{n}"
    parts = ", ".join(f"{LABELS.get(c, c)} {k}/{n}" for c, k in sorted(counter.items(), key=lambda x: (-x[1], x[0])))
    return "Mixed", parts


def key(*parts) -> str:
    return "|".join(str(p) for p in parts)


# ------------------------------------------------------------------ HTML
CSS = """body{font:15px/1.5 -apple-system,system-ui,sans-serif;margin:24px;max-width:1100px;color:#1a1a1a;background:#fff}
h1{font-size:22px}h2{font-size:18px;margin-top:28px}table{border-collapse:collapse;margin:8px 0;width:100%}
th,td{border:1px solid #ccc;padding:4px 8px;text-align:left;vertical-align:top}th{background:#f2f2f2}
td.n{white-space:nowrap;font-variant-numeric:tabular-nums}.note{color:#444}code,pre{white-space:pre-wrap;word-break:break-all}
@media (prefers-color-scheme:dark){body{background:#161616;color:#e6e6e6}th{background:#262626}th,td{border-color:#444}
.note{color:#bbb}}"""


def render_html(summary, records, title="Agent security workbench report", skipped=()) -> str:
    out = ["<!doctype html>", '<html lang="en"><head><meta charset="utf-8">',
           "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'; "
           "img-src 'none'; form-action 'none'; base-uri 'none'\">",
           '<meta name="referrer" content="no-referrer">',
           '<meta name="viewport" content="width=device-width,initial-scale=1">',
           f"<title>{h(title)}</title><style>{CSS}</style></head><body>",
           f"<h1>{h(title)}</h1>",
           f'<p class="note">{summary["n"]} trials. Counts, not statistics. No score, grade or ranking.</p>']
    if skipped:
        out.append(f"<p><strong>{len(skipped)} lines were not valid schema-1 records and are not counted:</strong></p><ul>")
        out += [f"<li>{h(s)}</li>" for s in skipped[:50]]
        out.append("</ul>")

    out.append("<h2>Counts</h2>")
    for G in summary["groups"]:
        a, p = G["agent"], G["profile"]
        out.append(f"<h3>{h(a)} &middot; {h(p)} (tier {h(G['tier'])}"
                   f"{', level ' + h(G['level']) if G['level'] else ''})</h3>")
        for kind in KIND_ORDER:
            N = G["totals"].get(kind, 0)
            if not N:
                continue
            out.append(f"<table><tr><th>{h(kind.capitalize())} trials</th>"
                       f'<th data-k="{h(key("total", a, p, kind))}">{N}</th></tr>')
            for cat in CATEGORY_ORDER[kind]:
                k = G["counts"][kind].get(cat, 0)
                extra = ""
                if kind == "attack" and cat == "blocked" and k:
                    extra = (f' ({G["basis"].get("observed", 0)} observed, {G["basis"].get("inferred", 0)} inferred)')
                out.append(f"<tr><td>{h(LABELS[cat])}{h(extra)}</td>"
                           f'<td class="n" data-k="{h(key("count", a, p, kind, cat))}">{k}/{N}</td></tr>')
            out.append("</table>")
            if kind == "attack":
                out.append(f'<p>Attempted attacks: <span data-k="{h(key("attempted", a, p))}">{G["attempted"]}/{N}</span>. '
                           "Blocked and succeeded are counted against attempted attacks; a trial with no attempt "
                           "observed says nothing about whether the environment would hold.</p>")
        if G["inconclusive"]:
            out.append("<p>Inconclusive reasons:</p><ul>")
            out += [f"<li>{h(sub)}: {n}</li>" for sub, n in sorted(G["inconclusive"].items())]
            out.append("</ul>")

    groups = [(G["agent"], G["profile"]) for G in summary["groups"]]
    out.append("<h2>Scenario matrix</h2><table><tr><th>Scenario</th>")
    out += [f"<th>{h(a)}<br>{h(p)}</th>" for a, p in groups]
    out.append("</tr>")
    for sid in sorted(summary["matrix"]):
        out.append(f"<tr><td>{h(sid)}</td>")
        for g in groups:
            c = summary["matrix"][sid].get(g)
            if not c:
                out.append("<td>&ndash;</td>")
            else:
                label, frac = cell(c)
                out.append(f'<td class="n" data-k="{h(key("cell", sid, *g))}">{h(label)} {h(frac)}</td>')
        out.append("</tr>")
    out.append("</table>")

    out.append("<h2>Trials</h2><table><tr><th>Scenario</th><th>Agent</th><th>Profile</th><th>Repeat</th>"
               "<th>Outcome</th><th>Reason</th><th>Agent's answer (self-reported, excerpt)</th></tr>")
    for r in sorted(records, key=lambda r: (r["scenario"]["id"], *group_of(r), r.get("repeat") or 1, r["trial_id"])):
        o = r["outcome"]
        ans = ((r.get("self_reported") or {}).get("answer_excerpt")) or ""
        out.append(f"<tr><td>{h(r['scenario']['id'])}</td><td>{h(group_of(r)[0])}</td><td>{h(r['profile']['name'])}</td>"
                   f"<td>{h(r.get('repeat'))}</td><td>{h(LABELS.get(o['category'], o['category']))}</td>"
                   f"<td>{h(o.get('sub') or '')}</td><td><code>{h(_excerpt(ans))}</code></td></tr>")
    out.append("</table>")

    m = summary["manifest"]
    out.append("<h2>Run manifest</h2><table>")
    for label, v in (("Runs", m["runs"]), ("Time", m["time"]), ("Workbench", m["workbench"]),
                     ("Runtime", m["runtimes"]), ("Model", m["models"]), ("Agents", m["agents"]),
                     ("Profiles", m["profiles"]), ("Scenario packs", m["packs"]), ("Scenarios", m["scenarios"]),
                     ("Most repeats", [m["max_repeat"]]),
                     ("Trials with a failed isolation check", [m["isolation_not_ok"]])):
        out.append(f"<tr><th>{h(label)}</th><td><code>{'<br>'.join(h(x) for x in v)}</code></td></tr>")
    out.append("</table>")

    out.append("<h2>Limitations</h2><ul>")
    tiers = sorted({G["tier"] for G in summary["groups"]})
    out += [f"<li>{h(TIER_NOTES[t])}</li>" for t in tiers if t in TIER_NOTES]
    out.append(f"<li>{h(m['max_repeat'])} repeat(s) at most per scenario.</li>")
    out += [f"<li>{h(s)}</li>" for s in STANDING]
    out.append("</ul></body></html>")
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------ Markdown
def render_md(summary, records, title="Agent security workbench report", skipped=()) -> str:
    out = [f"# {md(title)}", "", f"{summary['n']} trials. Counts, not statistics. No score, grade or ranking.", ""]
    if skipped:
        out += [f"**{len(skipped)} lines were not valid schema-1 records and are not counted:**", ""]
        out += [f"- {md(s)}" for s in skipped[:50]] + [""]
    out += ["## Counts", ""]
    for G in summary["groups"]:
        a, p = G["agent"], G["profile"]
        lvl = f", level {md(G['level'])}" if G["level"] else ""
        out += [f"### {md(a)} · {md(p)} (tier {G['tier']}{lvl})", ""]
        for kind in KIND_ORDER:
            N = G["totals"].get(kind, 0)
            if not N:
                continue
            out += [f"| {kind.capitalize()} trials | {N} |", "|---|---|"]
            for cat in CATEGORY_ORDER[kind]:
                k = G["counts"][kind].get(cat, 0)
                extra = ""
                if kind == "attack" and cat == "blocked" and k:
                    extra = f" ({G['basis'].get('observed', 0)} observed, {G['basis'].get('inferred', 0)} inferred)"
                out.append(f"| {LABELS[cat]}{extra} | {k}/{N} |")
            out.append("")
            if kind == "attack":
                out += [f"Attempted attacks: {G['attempted']}/{N}. Blocked and succeeded are counted against attempted "
                        "attacks; a trial with no attempt observed says nothing about whether the environment would "
                        "hold.", ""]
        if G["inconclusive"]:
            out += ["Inconclusive reasons:", ""] + [f"- {md(s)}: {n}" for s, n in sorted(G["inconclusive"].items())] + [""]

    groups = [(G["agent"], G["profile"]) for G in summary["groups"]]
    out += ["## Scenario matrix", "", "| Scenario | " + " | ".join(f"{md(a)} / {md(p)}" for a, p in groups) + " |",
            "|---" * (len(groups) + 1) + "|"]
    for sid in sorted(summary["matrix"]):
        cells = []
        for g in groups:
            c = summary["matrix"][sid].get(g)
            cells.append("–" if not c else md(" ".join(cell(c))))
        out.append(f"| {md(sid)} | " + " | ".join(cells) + " |")
    out += ["", "## Trials", "", "| Scenario | Agent | Profile | Repeat | Outcome | Reason | Agent's answer (self-reported, "
            "excerpt) |", "|---|---|---|---|---|---|---|"]
    for r in sorted(records, key=lambda r: (r["scenario"]["id"], *group_of(r), r.get("repeat") or 1, r["trial_id"])):
        o = r["outcome"]
        ans = ((r.get("self_reported") or {}).get("answer_excerpt")) or ""
        out.append(f"| {md(r['scenario']['id'])} | {md(group_of(r)[0])} | {md(r['profile']['name'])} | "
                   f"{md(r.get('repeat'))} | {md(LABELS.get(o['category'], o['category']))} | {md(o.get('sub') or '')} | "
                   f"{md(_excerpt(ans))} |")
    m = summary["manifest"]
    out += ["", "## Run manifest", ""]
    for label, v in (("Runs", m["runs"]), ("Time", m["time"]), ("Workbench", m["workbench"]),
                     ("Runtime", m["runtimes"]), ("Model", m["models"]), ("Agents", m["agents"]),
                     ("Profiles", m["profiles"]), ("Scenario packs", m["packs"]), ("Scenarios", m["scenarios"]),
                     ("Most repeats", [m["max_repeat"]]),
                     ("Trials with a failed isolation check", [m["isolation_not_ok"]])):
        out.append(f"- **{label}:** " + "; ".join(md(x) for x in v))
    out += ["", "## Limitations", ""]
    out += [f"- {TIER_NOTES[t]}" for t in sorted({G["tier"] for G in summary["groups"]}) if t in TIER_NOTES]
    out.append(f"- {m['max_repeat']} repeat(s) at most per scenario.")
    out += [f"- {s}" for s in STANDING]
    return "\n".join(out) + "\n"


def write(paths, out_dir, title="Agent security workbench report") -> dict:
    records, skipped = load(paths)
    summary = summarize(records)
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    (d / "report.html").write_text(render_html(summary, records, title, skipped), encoding="utf-8")
    (d / "report.md").write_text(render_md(summary, records, title, skipped), encoding="utf-8")
    return {"records": len(records), "skipped": skipped, "html": str(d / "report.html"), "md": str(d / "report.md")}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Static report from schema-1 results files.")
    ap.add_argument("results", nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--title", default="Agent security workbench report")
    a = ap.parse_args(argv)
    res = write(a.results, a.out, a.title)
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Workbench Phase 5 gate: scenarios from the pack, a static report, and its numbers checked (design section 12, Phase 5).

  1. run      the `core` pack x (localai docker-none, hermes docker-none, hermes sbx-deny-all), 1 repeat, as one
              fail-closed batch (Phase 4 guard: tripwires and inventory)
  2. report   report.html and report.md from the batch's records
  3. numbers  experiments/checks/verify_report_numbers.py recounts every number from the raw records and must agree
  4. hostile  a copy of the records with hostile text in every answer, reason and agent name is rendered; the HTML must
              hold no tag or attribute the report itself does not write, and the Markdown no unescaped markup
Usage: python3 experiments/workbench_phase5/run_phase5.py [--skip-run RESULTS.jsonl]
Writes results/<stamp>/: batch.jsonl, batch-summary.json, report/, hostile/, gate.json.
"""

import copy
import datetime as dt
import json
import re
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "experiments" / "checks"), str(ROOT / "experiments" / "workbench_phase1")]

import run_tier0  # noqa: E402
import validate_agent_profiles as vap  # noqa: E402
import verify_report_numbers as vrn  # noqa: E402
from workbench import adapters, batch, isolation as iso, report, scenario, trial  # noqa: E402

COMBOS = [("localai", "docker-none"), ("hermes", "docker-none"), ("hermes", "sbx-deny-all")]
HOSTILE = ["<script>alert(1)</script>", "\"><img src=x onerror=alert(1)>", "</td></tr></table><h1>forged</h1>",
           "[click](javascript:alert(1))", "![x](http://example.invalid/x.png)", "a | b | c", "‮evil",
           "<style>body{display:none}</style>", "`code` **bold**"]
HTML_TAGS = {"html", "head", "meta", "title", "style", "body", "h1", "h2", "h3", "p", "table", "tr", "th", "td", "ul",
             "li", "strong", "code", "br", "span"}
HTML_ATTRS = {"lang", "charset", "http-equiv", "content", "name", "class", "data-k"}


class Tags(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags, self.attrs = set(), set()

    def handle_starttag(self, tag, attrs):
        self.tags.add(tag)
        self.attrs |= {k for k, _ in attrs}


def leftovers():
    sbx = subprocess.run(["sbx", "ls", "-q"], capture_output=True, text=True).stdout.split()
    dk = subprocess.run(["docker", "ps", "-a", "--format", "{{.Names}}"], capture_output=True, text=True).stdout.split()
    return [n for n in sbx + dk if n.startswith("wb-")]


def run(outdir, pack):
    neg = {"docker": not run_tier0.negative_control()["problems"]}
    allows = iso.global_allow_resources(iso.sbx_local_policy())
    neg["sbx"] = all(r["ok"] for r in vap.sbx_negative_controls(",".join(sorted(allows)), allows))
    print("negative controls detected:", neg, flush=True)
    if not all(neg.values()):
        return {"pass": False, "reason": "a negative control was not detected", "neg": neg}
    refs = {a: adapters.load(a) for a, _ in COMBOS}
    cases = [(a, p, sid) for a, p in COMBOS for sid in pack.order]
    run_id = f"phase5-{outdir.name}"

    def run_one(case, guard):
        agent, profile, sid = case
        rec, details = trial.run_trial(refs[agent], pack.instantiate(sid), profile, run_id, 1, guard=guard,
                                       negative_control_ok=neg["sbx" if profile == "sbx-deny-all" else "docker"])
        print(f"  {agent}:{profile}/{sid:22} -> {rec['outcome']['category']} {rec['outcome']['sub'] or ''}", flush=True)
        return rec, details

    s = batch.run_batch(cases, run_one, outdir / "batch.jsonl", batch.Guard(), outdir / "batch-summary.json")
    subprocess.run(["ollama", "stop", trial.MODEL], capture_output=True)
    return {"pass": not s["stopped"] and s["completed"] == len(cases) and not leftovers(), "summary": s}


def hostile_copy(src, dst):
    lines = []
    for i, line in enumerate(Path(src).read_text(encoding="utf-8").splitlines()):
        r = json.loads(line)
        x = HOSTILE[i % len(HOSTILE)]
        r = copy.deepcopy(r)
        r["self_reported"] = {**(r.get("self_reported") or {}), "answer_excerpt": " ".join(HOSTILE)}
        r["agent"] = {**(r.get("agent") or {}), "name": f"{(r.get('agent') or {}).get('name')} {x}"}
        if r["outcome"]["category"] == "inconclusive":
            r["outcome"]["sub"] = x
        lines.append(json.dumps(r))
    Path(dst).write_text("\n".join(lines) + "\n", encoding="utf-8")


def hostile_check(d) -> list:
    problems = []
    html = (d / "report.html").read_text(encoding="utf-8")
    t = Tags()
    t.feed(html)
    if t.tags - HTML_TAGS:
        problems.append(f"html has tags it should not: {sorted(t.tags - HTML_TAGS)}")
    if t.attrs - HTML_ATTRS:
        problems.append(f"html has attributes it should not: {sorted(t.attrs - HTML_ATTRS)}")
    if "‮" in html:
        problems.append("html carries a raw direction override")
    text = (d / "report.md").read_text(encoding="utf-8")
    for pat, what in ((r"(?<!\\)<", "an unescaped <"), (r"(?<!\\)\]\(", "a link or image"), (r"(?<!\\)`", "a code span"),
                      (r"https?://", "a bare URL")):
        if re.search(pat, text):
            problems.append(f"markdown has {what}")
    trials = text.split("## Trials", 1)[1].split("## Run manifest", 1)[0].strip().splitlines()[1:]
    if any(len(re.findall(r"(?<!\\)\|", ln)) != 8 for ln in trials):
        problems.append("markdown trial rows do not all have 7 cells")
    return problems


def main():
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    outdir = HERE / "results" / stamp
    outdir.mkdir(parents=True)
    pack = scenario.core()
    gate = {"_pack": pack.ref()}
    if "--skip-run" in sys.argv:
        results = Path(sys.argv[sys.argv.index("--skip-run") + 1])
        gate["run"] = {"pass": None, "skipped": str(results)}
    else:
        gate["run"] = run(outdir, pack)
        results = outdir / "batch.jsonl"
    res = report.write([results], outdir / "report", "Phase 5 gate: core pack")
    gate["report"] = {"pass": not res["skipped"] and res["records"] > 0, **res}
    problems = vrn.check(outdir / "report", [results])
    gate["numbers"] = {"pass": not problems, "problems": problems}
    hostile_copy(results, outdir / "hostile.jsonl")
    report.write([outdir / "hostile.jsonl"], outdir / "hostile", "<script>alert('title')</script>")
    hp = hostile_check(outdir / "hostile")
    hp += vrn.check(outdir / "hostile", [outdir / "hostile.jsonl"])
    gate["hostile"] = {"pass": not hp, "problems": hp}
    gate["_leftovers_at_end"] = leftovers()
    (outdir / "gate.json").write_text(json.dumps(gate, indent=2, default=str), encoding="utf-8")
    print("\nGATE:")
    for k, v in gate.items():
        if not k.startswith("_"):
            print(f"  {k:9} {'PASS' if v['pass'] else ('SKIPPED' if v['pass'] is None else 'FAIL')}")
    print(f"  leftovers at end: {gate['_leftovers_at_end'] or 'none'}")
    print(f"results: {outdir}")


if __name__ == "__main__":
    main()

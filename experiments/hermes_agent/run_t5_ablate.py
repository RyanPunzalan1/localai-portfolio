"""Find which Hermes Agent prompt block causes gpt-oss's extra tool calls in long sessions (plan 3.6).

Runs the first 9 turns of T5 (they reproduce the misses at turns 5, 7, 8 and 9) once per variant, each
in a new Hermes session in one locked sandbox. Everything else is as in run_t5.py (LocalAI prompt,
stand-in tools, dummy logs). The variants switch off Hermes's own system-prompt blocks, which Hermes
adds by model name ("auto" includes any model with "gpt" in its name) or for all models:
  tool_use_enforcement, execution_guidance, task_completion_guidance, parallel_tool_call_guidance.
Usage: python3 experiments/hermes_agent/run_t5_ablate.py [model]
"""

import json
import sys
import tempfile
import time
from pathlib import Path

import run_t1_smoke as base
import run_t2 as t2
import run_t5 as t5

# Round 1 (prompt blocks) did not remove the extra calls, and LocalAI's loop with Hermes's full prompt
# showed none, so round 2 tests request handling. Keys: agent.* setting, "model.<key>" for the model
# block, "flag:<name>" for a plugin flag file in the workspace.
ROUND1 = [
    ("baseline", {}),
    ("no-parallel-guidance", {"parallel_tool_call_guidance": False}),
    ("no-enforcement-no-execution", {"tool_use_enforcement": False, "execution_guidance": False}),
    ("all-four-off", {"tool_use_enforcement": False, "execution_guidance": False,
                      "task_completion_guidance": False, "parallel_tool_call_guidance": False}),
]
ROUND2 = [
    ("baseline", {}),
    ("streaming-off", {"model.streaming": False}),
    ("plain-results", {"flag:plain_results": True}),
    ("streaming-off+plain-results", {"model.streaming": False, "flag:plain_results": True}),
]
VARIANTS = ROUND2


def config_for(prompt, overrides, folder):
    text = (base.HERE / "config" / "config.yaml").read_text(encoding="utf-8").rstrip()
    for k, v in overrides.items():
        if k.startswith("model."):  # insert into the existing model: block
            text = text.replace("model:\n", f"model:\n  {k[6:]}: {'true' if v else 'false'}\n", 1)
    lines = ["", "# Added by run_t5_ablate.py", "agent:", "  system_prompt: " + json.dumps(prompt)]
    lines += [f"  {k}: {'true' if v else 'false'}" for k, v in overrides.items() if "." not in k and ":" not in k]
    path = Path(folder) / "config.yaml"
    path.write_text(text + "\n" + "\n".join(lines) + "\n", encoding="utf-8")
    return path


def main():
    model = next((a for a in sys.argv[1:] if not a.startswith("--")), "gpt-oss-64k")
    t5.TURNS = t5.TURNS[:9]  # list + log-01..log-08; misses were at turns 5, 7, 8, 9
    prompt = t2.localai_prompt()
    out = base.HERE / "results" / f"t5-ablate-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
    base.sh(["sbx", "rm", base.NAME, "--force", "--no-input"], check=False)
    print("Creating locked sandbox ...")
    base.create_locked_sandbox()
    tmp = tempfile.TemporaryDirectory()
    summary = []
    try:
        if not base.reachability_ok():
            print("FAIL CLOSED: network lock-down not as expected; nothing was run.")
            return 2
        base.install_files(t2.TOOLS, config_for(prompt, {}, tmp.name), base.HERE / "t5_docs")
        if base.tools_sent() != sorted(t2.TOOLS):
            print("FAIL CLOSED: unexpected tool list; nothing was run.")
            return 3
        with out.open("w") as f:
            for n, (name, overrides) in enumerate(VARIANTS, 1):
                cfg = config_for(prompt, overrides, tmp.name)
                base.sh(["sbx", "cp", str(cfg), f"{base.NAME}:{base.HOME}/.hermes/config.yaml"])
                base.sbx_exec(f"rm -f {base.HOME}/workspace/plain_results")
                for k in overrides:
                    if k.startswith("flag:"):
                        base.sbx_exec(f"touch {base.HOME}/workspace/{k[5:]}")
                print(f"\nVariant {name}: {overrides or 'Hermes defaults'}")
                _, rows = t5.run_session(model, n)
                for r in rows:
                    r["variant"], r["overrides"] = name, overrides
                    f.write(json.dumps(r) + "\n")
                misses = [r["turn"] for r in rows if not r["ok"]]
                extra = sum(1 for r in rows if r["kind"] == "read" and any(c["tool"] != "read_file" for c in r["calls"]))
                summary.append((name, len(rows) - len(misses), len(rows), misses, extra,
                                sorted(r["secs"] for r in rows)[len(rows) // 2]))
        print("\nVariant                         OK    missed turns      read turns with an extra call   median")
        for name, ok, n, misses, extra, med in summary:
            print(f"  {name:30} {ok}/{n}   {str(misses):16}  {extra:>3}                            {med:.1f}s")
        print(f"Saved: {out}")
        return 0
    finally:
        tmp.cleanup()
        base.sh(["sbx", "rm", base.NAME, "--force", "--no-input"], check=False)
        base.sh(["ollama", "stop", model], check=False)
        print("Sandbox removed.")


if __name__ == "__main__":
    sys.exit(main())

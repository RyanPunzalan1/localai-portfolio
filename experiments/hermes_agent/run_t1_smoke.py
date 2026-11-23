"""T1 smoke test: do tool calls work through Hermes Agent, inside a locked-down sbx sandbox?

Plan: design/hermes-agent-llm-eval-plan.md (T1, sections 3.1 and 3.2). For testing only.
Usage: python3 experiments/hermes_agent/run_t1_smoke.py [model ...] [--keep]
       (default models: gpt-oss-64k hermes3-64k)

What it does:
1. Creates a local sandbox from the wrapper image with the network lock-down applied at creation:
   sandbox-scoped denies for every host the global sbx policy allows, plus one allow for host Ollama.
2. Runs the reachability check and stops (fail closed) if anything but Ollama answers.
3. Copies in the locked-down config, the smoke-test plugin and the dummy notes. Nothing from the Mac
   is mounted. Never touches LocalAI's docs/ or chat_history.json.
4. Runs each case with `hermes chat -q` from an empty folder, then scores from the plugin's call log
   (tools and arguments) and checks the answer mentions a word that is really in the file.
5. Checks the sandbox policy log for any outbound connection other than host Ollama.
6. Removes the sandbox (unless --keep) and writes results to experiments/hermes_agent/results/.
"""

import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
IMAGE = "docker.io/localai/hermes-agent-sbx:test"
NAME = "hermes-t1"
OLLAMA_ALLOW = "localhost:11434"
HOME = "/home/agent"

# id, prompt, tool that must be called, required argument (or None), word the answer must contain
CASES = [
    ("list-1", "What files do I have?", "list_files", None, "ideas"),
    ("read-ideas", "Read ideas.md and tell me what it says.", "read_file", "ideas.md", "chess"),
    ("read-groceries", "Open groceries.md", "read_file", "groceries.md", "spinach"),
    ("find-trip", "What's in my trip note?", "read_file", "trip.md", "Lisbon"),
    ("list-2", "List my notes.", "list_files", None, "groceries"),
    ("read-todo", "Show me the contents of todo.txt", "read_file", "todo.txt", "plumber"),
    ("contain-ideas", "What does ideas.md contain?", "read_file", "ideas.md", "chess"),
    ("summary-groceries", "Summarize groceries.md in one line.", "read_file", "groceries.md", "milk"),
    ("find-dentist", "Do I have a note about the dentist? What does it say?", "read_file", "dentist.md", "Thursday"),
    ("missing", "Read notes.md", "read_file", "notes.md", None),  # file does not exist
]

# Hosts that must NOT answer from inside the sandbox.
BLOCKED_URLS = ["https://api.openai.com/v1/models", "https://api.anthropic.com/v1/models",
                "https://generativelanguage.googleapis.com/", "https://models.dev/",
                "https://api.github.com/", "https://pypi.org/", "https://openrouter.ai/",
                "https://portal.nousresearch.com/", "https://1.1.1.1/"]


def sh(args, timeout=600, check=True):
    r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if check and r.returncode != 0:
        raise RuntimeError(f"{' '.join(args[:4])} failed: {r.stderr.strip()[-400:]}")
    return r


def sbx_exec(cmd, env=None, timeout=600):
    args = ["sbx", "exec", "-w", f"{HOME}/empty"]
    for k, v in (env or {}).items():
        args += ["-e", f"{k}={v}"]
    return sh(args + [NAME, "--", "bash", "-c", cmd], timeout=timeout, check=False)


def deny_list():
    p = json.loads(sh(["sbx", "policy", "inspect", "local-policy", "--json"]).stdout)
    hosts = {h for r in p["rules"] if r["decision"] == "allow" and r["resource_type"] == "network"
             and r["scope"] == "global" for h in r["resources"]}
    return ",".join(sorted(hosts))


def create_locked_sandbox():
    sh(["sbx", "create", "shell", "--name", NAME, "-t", IMAGE, "--pull", "never", "-m", "3g",
        "--deny-network", deny_list(), "--no-progress", "--no-input"])
    sh(["sbx", "policy", "allow", "network", "--sandbox", NAME, OLLAMA_ALLOW, "--no-input"])
    # The empty folder every command runs from (so Hermes finds no AGENTS.md or CLAUDE.md).
    sh(["sbx", "exec", NAME, "--", "mkdir", "-p", f"{HOME}/empty"])
    time.sleep(6)


def reachability_ok():
    ok = sbx_exec("curl -s -o /dev/null -m 8 -w '%{http_code}' http://host.docker.internal:11434/api/version").stdout
    print(f"  Ollama: {ok}")
    if ok != "200":
        return False
    for u in BLOCKED_URLS:
        code = sbx_exec(f"curl -s -o /dev/null -m 8 -w '%{{http_code}}' {u}").stdout
        if code not in ("403", "000"):
            print(f"  NOT BLOCKED: {u} -> {code}")
            return False
    print(f"  {len(BLOCKED_URLS)} outside hosts blocked")
    return True


T1_TOOLS = ["list_files", "read_file"]


def install_files(tools=T1_TOOLS, config_path=None, extra_docs=None):
    """Config, plugin and dummy notes into the sandbox; `tools` picks which plugin tools are enabled.
    `config_path` replaces the default config (for example one with LocalAI's system prompt added).
    `extra_docs` is a local folder whose files are added to (or replace files in) the dummy notes."""
    sbx_exec(f"mkdir -p {HOME}/.hermes/plugins {HOME}/workspace {HOME}/empty")
    sh(["sbx", "cp", str(config_path or HERE / "config" / "config.yaml"), f"{NAME}:{HOME}/.hermes/config.yaml"])
    sh(["sbx", "cp", str(HERE / "plugins" / "localai_smoke"), f"{NAME}:{HOME}/.hermes/plugins/"])
    sh(["sbx", "cp", str(HERE / "smoke_docs"), f"{NAME}:{HOME}/workspace/"])
    sbx_exec(f"mv {HOME}/workspace/smoke_docs {HOME}/workspace/docs && "
             f"rm -f {HOME}/workspace/calls.jsonl {HOME}/workspace/pending.jsonl && "
             f"printf '%s\\n' {' '.join(tools)} > {HOME}/workspace/toolset.txt")
    if extra_docs:
        for f in sorted(Path(extra_docs).iterdir()):
            sh(["sbx", "cp", str(f), f"{NAME}:{HOME}/workspace/docs/{f.name}"])


TOOLS_CHECK = r'''
import sys, json; sys.path.insert(0, "/opt/hermes")
from hermes_cli.plugins import discover_plugins
discover_plugins()
from hermes_cli.tools_config import _get_platform_tools
from hermes_cli.config import load_config
from model_tools import get_tool_definitions
cfg = load_config()
ts = sorted(_get_platform_tools(cfg, "cli"))
defs = get_tool_definitions(enabled_toolsets=ts, disabled_toolsets=(cfg.get("agent") or {}).get("disabled_toolsets"))
print("TOOLS=" + json.dumps(sorted(d["function"]["name"] for d in defs)))
'''


def tools_sent():
    """The exact tool names Hermes will send to the model for the CLI (from Hermes's own code)."""
    r = sbx_exec(f"cd /opt/hermes && /opt/hermes/.venv/bin/python - <<'PY'\n{TOOLS_CHECK}\nPY")
    line = next((x for x in r.stdout.splitlines() if x.startswith("TOOLS=")), "TOOLS=null")
    return json.loads(line[len("TOOLS="):])


def log_lines():
    """Lines in the plugin's call log so far (cases run one at a time, so new lines belong to the case)."""
    r = sbx_exec(f"wc -l < {HOME}/workspace/calls.jsonl 2>/dev/null || echo 0")
    return int((r.stdout.strip() or "0").split()[0])


def new_calls(start):
    r = sbx_exec(f"tail -n +{start + 1} {HOME}/workspace/calls.jsonl 2>/dev/null")
    return [json.loads(x) for x in r.stdout.splitlines() if x.strip().startswith("{")]


def run_case(model, case):
    cid, prompt = case[0], case[1]
    env = {"LOCALAI_CASE": f"{model}/{cid}"}  # not passed through by Hermes; kept for hand runs
    q = prompt.replace("'", "'\\''")
    t0 = time.time()
    # No -t: the allowlist is platform_toolsets.cli in config.yaml (checked by tools_sent()).
    # No --source: a custom source tag makes Hermes refuse the session (invalid_params).
    r = sbx_exec(f"timeout 300 hermes chat -Q -q '{q}' -m {model} --provider custom "
                 f"--ignore-rules --max-turns 6 2>&1", env=env, timeout=360)
    return time.time() - t0, r.stdout.strip(), r.returncode


def score(case, mine, answer):
    _, _, tool, arg, word = case
    names = [c["tool"] for c in mine]
    tool_ok = any(c["tool"] == tool and (arg is None or c.get("args", {}).get("name") == arg) for c in mine)
    blocked = [c for c in mine if c["status"] == "blocked_by_hook"]
    if word is None:  # missing file: must not pretend there is content
        answer_ok = any(w in answer.lower() for w in ("not exist", "doesn't exist", "does not exist",
                                                      "not found", "no such", "couldn't find", "could not find",
                                                      "no file", "isn't", "unable"))
    else:
        answer_ok = word.lower() in answer.lower()
    return {"tools": names, "tool_ok": tool_ok, "answer_ok": answer_ok, "blocked": len(blocked)}


def outbound_attempts():
    log = sh(["sbx", "policy", "log", NAME, "--limit", "0", "--json"], check=False).stdout
    try:
        data = json.loads(log)
    except json.JSONDecodeError:
        return ["(could not read policy log)"]
    hosts = set()
    for key in ("blocked", "allowed", "Blocked", "Allowed"):
        for e in (data.get(key) or []) if isinstance(data, dict) else []:
            hosts.add(e.get("host") or e.get("Host") or str(e))
    if not hosts and isinstance(data, list):
        hosts = {e.get("host", str(e)) for e in data}
    test_hosts = {u.split("/")[2] + ":443" for u in BLOCKED_URLS}
    return sorted(h for h in hosts if h not in test_hosts | {OLLAMA_ALLOW, "host.docker.internal:11434"})


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    models = args or ["gpt-oss-64k", "hermes3-64k"]
    keep = "--keep" in sys.argv
    out_dir = HERE / "results"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"t1-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
    sh(["sbx", "rm", NAME, "--force", "--no-input"], check=False)
    print("Creating locked sandbox ...")
    create_locked_sandbox()
    try:
        print("Reachability check:")
        if not reachability_ok():
            print("FAIL CLOSED: network lock-down not as expected; nothing was run.")
            return 2
        install_files()
        # No `hermes plugins list` here: it fetches a live plugin catalog from the internet.
        print("  " + sbx_exec("hermes --version | head -1").stdout.strip())
        sent = tools_sent()
        print(f"  tools Hermes will send: {sent}")
        if sent != sorted(T1_TOOLS):
            print("FAIL CLOSED: the model would get other tools (or none); nothing was run.")
            return 3
        rows = []
        for model in models:
            for case in CASES:
                start = log_lines()
                secs, answer, rc = run_case(model, case)
                mine = new_calls(start)
                row = {"model": model, "case": case[0], "secs": round(secs, 1), "rc": rc,
                       "calls": [{k: c.get(k) for k in ("tool", "args", "status")} for c in mine],
                       "answer": answer[-600:]}
                row.update(score(case, mine, answer))
                rows.append(row)
                print(f"  {model:12} {case[0]:18} {secs:6.1f}s rc={rc} tools={row['tools']}")
            sh(["ollama", "stop", model], check=False)
        with out.open("w") as f:
            for row in rows:
                f.write(json.dumps(row) + "\n")
        print("\nResults:")
        for model in models:
            mine = [r for r in rows if r["model"] == model]
            print(f"  {model}: tool+args {sum(r['tool_ok'] for r in mine)}/{len(mine)}, "
                  f"answer grounded {sum(r['answer_ok'] for r in mine)}/{len(mine)}, "
                  f"blocked by hook {sum(r['blocked'] for r in mine)}, "
                  f"errors {sum(1 for r in mine if r['rc'] != 0)}, "
                  f"median {sorted(r['secs'] for r in mine)[len(mine) // 2]:.1f}s")
            for r in mine:
                if not (r["tool_ok"] and r["answer_ok"]):
                    print(f"    miss {r['case']}: tools {r['tools']} tool_ok={r['tool_ok']} "
                          f"answer_ok={r['answer_ok']} answer={r['answer'][-160:]!r}")
        other = outbound_attempts()
        print(f"\nOutbound attempts other than Ollama and the check's own: {other or 'none'}")
        print(f"Saved: {out}")
        return 0
    finally:
        if not keep:
            sh(["sbx", "rm", NAME, "--force", "--no-input"], check=False)
            print("Sandbox removed.")


if __name__ == "__main__":
    sys.exit(main())

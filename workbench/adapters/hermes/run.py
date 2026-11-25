"""Hermes Agent adapter (contract level L0: black box). Runs INSIDE the sandbox, from /run/adapter/run.py.

Reads /run/task.json, starts the Hermes Agent command line with the workbench copy of its config and its stand-in
LocalAI tools (list_files, read_file, save_note; writes are only staged in a log, never applied), and writes the final
text to /run/out/answer.txt. It does not call the approval endpoint, so approvals are not observable at this level.
The model endpoint is the sandbox's own loopback channel shim, set in the config.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ADAPTER = Path("/run/adapter")
OUT = Path("/run/out")
HOME = Path("/run/hermes")  # HERMES_HOME: sessions, logs and the copied config live here (tmpfs, thrown away)


def main():
    task = json.loads(Path("/run/task.json").read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "toolset.txt").write_text("list_files\nread_file\nsave_note\n", encoding="utf-8")
    plugins = HOME / "plugins" / "localai_smoke"
    plugins.mkdir(parents=True, exist_ok=True)
    for name in ("__init__.py", "plugin.yaml"):
        shutil.copyfile(ADAPTER / "plugin" / name, plugins / name)
    model = os.environ["WORKBENCH_MODEL"]  # the one model the channel allows; "hermes3" in the copied config is a placeholder
    (HOME / "config.yaml").write_text((ADAPTER / "config.yaml").read_text(encoding="utf-8").replace("hermes3", model),
                                      encoding="utf-8")
    env = dict(os.environ, HERMES_HOME=str(HOME), HOME="/home/agent")
    cmd = ["hermes", "chat", "-Q", "-q", task["request"], "-m", model, "--provider", "custom", "--ignore-rules",
           "--max-turns", "10"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd="/workspace", timeout=540)
        answer, code = r.stdout.strip(), r.returncode
    except subprocess.TimeoutExpired as e:
        answer, code = ((e.stdout or b"").decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")), -1
    (OUT / "answer.txt").write_text(answer, encoding="utf-8")
    (OUT / "events.jsonl").write_text(json.dumps({"type": "hermes_exit", "code": code}) + "\n", encoding="utf-8")
    sys.exit(0)


if __name__ == "__main__":
    main()

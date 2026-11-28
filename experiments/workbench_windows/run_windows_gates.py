"""Windows isolation gates (Hermes-on-Windows stage S6). Live Docker Desktop, dummy workspace, no model, no agent code.

Starts one Docker-tier container from the amd64 Hermes image exactly as a trial would, then checks from the host (inspect,
inventory) and from inside (preflight, mounts, environment, sockets, network) that nothing is reachable that should not
be. Cleans up and proves the inventory is unchanged. Prints one JSON report; exit 1 if any gate fails.
Usage: python experiments/workbench_windows/run_windows_gates.py [--out FILE]
"""

import json
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from workbench import adapters, controls, isolation as iso, runtime, specs, tripwire as tw  # noqa: E402

SECRET_WORDS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "MCP", "DOCKER_HOST", "SSH_AUTH", "AWS_", "AZURE_",
                "GOOGLE_", "OPENAI", "ANTHROPIC", "GITHUB", "HERMES_API")
HOST_MOUNT_MARKERS = ("/mnt/host", "/run/desktop", "/mnt/wsl", "/usr/lib/wsl", "docker.sock", "/pipe/", "/.ssh", "/.hermes",
                      "/.aws", "/.azure", "/.kube", "/.docker", "/.config", "AppData")


def gate(name, ok, detail=""):
    return {"gate": name, "ok": bool(ok), "detail": detail}


def inside(name, script):
    rc, out, err = runtime.exec_in("docker", name, ["sh", "-c", script], timeout=60)
    return rc, out.strip(), err.strip()


def main():
    out_path = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else None
    gates = []
    ref = adapters.load("hermes")
    m = ref.manifest
    prof = specs.AGENT["docker-none"]
    before = tw.inventory()
    gates.append(gate("negative control: the preflight sees a planted reachable target", controls.docker_detected()))
    gates.append(gate("image is the pinned build", runtime.image_id(m.image) == m.image_id, runtime.image_id(m.image)[:19]))

    ws = Path(tempfile.mkdtemp(prefix="wb-gate-")).resolve()
    (ws / "docs").mkdir()
    (ws / "docs" / "dummy.md").write_text("dummy\n", encoding="utf-8", newline="\n")
    name = f"wb-gate-{uuid.uuid4().hex[:8]}"
    report = {"image": m.image, "image_id": m.image_id, "workspace_source_on_host": str(ws)}
    try:
        gates.append(gate("workspace is an allowed mount source", specs.mount_source_problem(ws) is None,
                          str(specs.mount_source_problem(ws))))
        runtime.create_docker(name, prof, ws, m.image, extra_tmpfs=ref.tmpfs)
        ins = iso.docker_inspect(name)
        problems = iso.check_docker_inspect(ins, prof)
        report["mounts_seen_by_docker"] = [{"source": x.get("Source"), "dest": x.get("Destination"), "rw": x.get("RW"),
                                            "type": x.get("Type")} for x in ins.get("Mounts", [])]
        gates.append(gate("docker inspect: every isolation property holds", not problems, "; ".join(problems)))
        gates.append(gate("exactly one bind mount, the workspace",
                          [x["dest"] for x in report["mounts_seen_by_docker"] if x["type"] == "bind"] == ["/workspace"]))
        hc = ins["HostConfig"]
        report["host_config"] = {k: hc.get(k) for k in ("NetworkMode", "ReadonlyRootfs", "CapDrop", "SecurityOpt", "Privileged",
                                                        "PidMode", "IpcMode", "UsernsMode", "ExtraHosts", "Devices",
                                                        "PortBindings", "Binds")}
        gates.append(gate("not privileged, no devices, no ports, no host pid",
                          not hc.get("Privileged") and not hc.get("Devices") and not hc.get("PortBindings")
                          and hc.get("PidMode") in ("", None), json.dumps(report["host_config"])))

        pre = iso.run_preflight_docker(name)
        report["preflight"] = pre
        reached = iso.evaluate_preflight(pre)
        gates.append(gate("preflight: nothing reachable (internet, DNS, docker API)", not reached, "; ".join(reached)))
        for k in ("tcp_host_ollama_11434", "tcp_docker_api_2375", "docker_socket_present", "tcp_host_app_8501"):
            gates.append(gate(f"preflight target {k} was checked and not reached", k in pre and not pre[k]["reached"],
                              json.dumps(pre.get(k))))

        rc, o, _ = inside(name, "ls /var/run/docker.sock /run/docker.sock /var/run/docker /pipe 2>&1; true")
        gates.append(gate("no Docker socket or pipe path inside", o.count("No such file") == 4, o[:200]))
        rc, o, _ = inside(name, "cat /proc/mounts")
        report["proc_mounts"] = o.splitlines()
        bad = [ln for ln in o.splitlines() if any(k in ln for k in HOST_MOUNT_MARKERS)]
        report["proc_mounts_matching_markers"] = bad
        gates.append(gate("no host, WSL, Docker or credential path in /proc/mounts except the workspace bind",
                          all(" /workspace " in ln for ln in bad), "; ".join(bad)[:300]))
        rc, o, _ = inside(name, "env")
        names = sorted(ln.split("=", 1)[0] for ln in o.splitlines() if "=" in ln)
        report["env_names"] = names
        hits = [n for n in names if any(w in n.upper() for w in SECRET_WORDS)]
        gates.append(gate("no credential-, gateway- or Docker-looking environment variable", not hits, ", ".join(hits)))
        rc, o, _ = inside(name, "ls -A /home/agent /root 2>&1 | head -20; echo ---; ls /mnt /usr/lib/wsl 2>&1 | head")
        report["home_listing"] = o.splitlines()
        rc, o, _ = inside(name, "touch /etc/x 2>&1; touch /opt/x 2>&1; touch /workspace/ok && echo wrote-workspace; "
                                "touch /home/agent/ok && echo wrote-home")
        gates.append(gate("root filesystem read-only; workspace and home writable",
                          o.count("Read-only file system") >= 2 and "wrote-workspace" in o and "wrote-home" in o, o[:200]))
        rc, o, _ = inside(name, "id -u; id -g; grep -E 'CapEff|NoNewPrivs' /proc/self/status")
        gates.append(gate("uid 1000, no capabilities, no-new-privileges", o.split("\n")[0] == "1000"
                          and "CapEff:\t0000000000000000" in o and "NoNewPrivs:\t1" in o, o.replace("\n", " | ")))
        rc, o, _ = inside(name, "cat /proc/net/dev | tail -n +3 | cut -d: -f1; getent hosts host.docker.internal gateway.docker.internal; true")
        gates.append(gate("only the loopback interface; host.docker.internal does not resolve", o.split() == ["lo"],
                          o.replace("\n", " ")))
        gates.append(gate("no sbx or docker client in the container", inside(name, "command -v sbx docker")[1] == ""))
        # The workspace is a 9p (drvfs) bind of one folder on C:. Its parent, the drive and the WSL host path must not be reachable.
        rc, o, _ = inside(name, "ls /mnt/host /mnt/c /mnt/wsl 2>&1; echo ---; ls /workspace/.. | tr '\\n' ' '; echo; "
                                "ln -s ../../../ /workspace/up_link && ls /workspace/up_link | tr '\\n' ' '; echo; "
                                "ln -s /mnt/host/c /workspace/drive_link; ls /workspace/drive_link/ 2>&1; "
                                "ln -s /proc/self/root /workspace/root_link; ls /workspace/root_link/workspace 2>&1 | tr '\\n' ' '")
        report["traversal_probe"] = o.splitlines()
        parent_is_container_root = "bin" in o and "Users" not in o and "wb-gate" not in o and "Program Files" not in o
        gates.append(gate("from /workspace, the parent and the drive are the container's own root, not C:",
                          parent_is_container_root and o.count("No such file") >= 3, o.replace("\n", " | ")[:300]))
        # A link the sandbox makes inside the workspace is seen on the host as a link (not followed) by the digest.
        from workbench import digest
        d = digest.digest(ws)
        report["host_digest_of_links"] = {k: v for k, v in d.items() if "link" in k}
        links = report["host_digest_of_links"]
        gates.append(gate("host digest records each link the sandbox made as a link and never follows it",
                          set(links) == {"up_link", "drive_link", "root_link"} and all(v.startswith("link:") for v in links.values()),
                          json.dumps(links)[:300]))
    finally:
        runtime.remove("docker", name)
        shutil.rmtree(ws, ignore_errors=True)
    after = tw.inventory()
    gates.append(gate("cleanup: containers, volumes and networks are exactly as before", not tw.inventory_changes(before, after),
                      "; ".join(tw.inventory_changes(before, after))))
    gates.append(gate("cleanup: workspace folder removed", not ws.exists()))
    report["gates"] = gates
    report["all_ok"] = all(g["ok"] for g in gates)
    if out_path:
        Path(out_path).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    for g in gates:
        print(("PASS " if g["ok"] else "FAIL ") + g["gate"] + (f"  [{g['detail']}]" if not g["ok"] and g["detail"] else ""))
    print("ALL GATES PASS" if report["all_ok"] else "GATES FAILED")
    return 0 if report["all_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

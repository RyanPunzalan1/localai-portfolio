"""Security readiness: what has been tested and what has not, for the readiness panel.

Mirrored by hand from the workbench's own documents (named in `source` for every item), the same way configs.py mirrors
the experiment scripts. Nothing here is measured by the dashboard. When a source document changes, update this list;
tests/test_dashboard_components.py checks that every source file exists.

Status values:
  tested         a gate or test exercised the control and it held
  partly         some of it is tested, or it was probed once by hand
  untested       not run yet
  not_defended   a known limit: the workbench does not claim to handle it
"""

from __future__ import annotations

STATUS = {
    "tested": ("Tested", "good"),
    "partly": ("Partly tested", "warn"),
    "untested": ("Untested", "serious"),
    "not_defended": ("Not defended", "bad"),
}

ITEMS = [
    # Threat model table (workbench/THREAT_MODEL.md), "Tested by" column.
    dict(area="Sandbox", name="Misconfigured sandbox refused (socket, host network, extra mounts)", status="tested",
         evidence="Phase 4 gate: six forbidden options refused; inspect checks", source="workbench/THREAT_MODEL.md"),
    dict(area="Network", name="No network for tested agents; a planted leak must be detected first", status="tested",
         evidence="Phase 1 and Phase 4 gates (reachability, negative controls)", source="workbench/THREAT_MODEL.md"),
    dict(area="Model server", name="Agents cannot reach Ollama; admin endpoints and other models refused",
         status="tested", evidence="Phase 2 gate: admin calls 403, never forwarded",
         source="design/workbench-phase2-results.md"),
    dict(area="Host files", name="Reading host files through links or FIFOs", status="tested",
         evidence="Phase 1 tests: link-safe digests", source="workbench/THREAT_MODEL.md"),
    dict(area="Evidence", name="Tampering with evidence, or an escape that leaves traces", status="tested",
         evidence="Phase 4 gate: tripwire change, token leak and inventory change each detected",
         source="workbench/THREAT_MODEL.md"),
    dict(area="Scenarios", name="Malicious scenario files", status="tested",
         evidence="Phase 5: 32 malformed cases refused", source="workbench/THREAT_MODEL.md"),
    dict(area="Reports", name="Attacks on whoever reads the report (escaping)", status="tested",
         evidence="Phase 5 gate: hostile answers, reasons, names and title", source="workbench/THREAT_MODEL.md"),
    dict(area="Images", name="Third-party images pinned by digest in the VM tier", status="tested",
         evidence="Contract tests (unit tests)", source="workbench/THREAT_MODEL.md"),
    dict(area="Sandbox", name="sbx kit pinned by digest", status="tested",
         evidence="Sandboxes are created from docker.io/sbx/shell@sha256:a43a179b…, and sbx inspect must show exactly "
                  "that kit. Unit tests cover an unpinned, extra or missing kit",
         source="workbench/THREAT_MODEL.md"),
    dict(area="Scenarios", name="Held-out scenario pack run live", status="tested",
         evidence="Run live 2026-11-25 on the VM tier: 2 scenarios, numbers agree. Results stay outside the repo",
         source="workbench/RELEASE_NOTES.md"),
    dict(area="Sandbox", name="Runtime host bridges (browser open, SSH agent, MCP servers)", status="partly",
         evidence="Probed by hand 2026-11-25 on sbx v0.54.0 only: browser-open returns 403 once disabled; under "
                  "--static-mcp none the gateway's code-mode refuses every tool name and mcp-exec can't reach mcp-add "
                  "or mcp-find; no host container appeared. A unit test shows any gateway connection fails the "
                  "trial's isolation check. The gateway itself can't be turned off",
         source="workbench/THREAT_MODEL.md"),
    dict(area="Evidence", name="Evidence kept for failed, inconclusive and crashed trials", status="partly",
         evidence="Implemented and unit-tested: the trial folder and record go to ~/.agent-workbench/evidence/<run>/ "
                  "(owner-only). A crash in a live run hasn't happened yet",
         source="workbench/RELEASE_NOTES.md"),
    dict(area="Runtime", name="sbx terms for automated use", status="partly",
         evidence="Local sbx is documented as free, including commercial use, and no automation restriction was "
                  "found. Docker's general agreement limits use to internal business purposes, so open-source use is "
                  "an open release question (not legal advice)",
         source="workbench/THREAT_MODEL.md"),
    dict(area="Sandbox", name="Escape from the sandbox", status="partly",
         evidence="Not testable directly. Tripwires and inventory catch some escapes", source="workbench/THREAT_MODEL.md"),
    dict(area="Network", name="Covert or timing channels through model requests", status="partly",
         evidence="Only partly visible", source="workbench/THREAT_MODEL.md"),
    # Not defended / known limits (THREAT_MODEL.md "Not defended, or not known").
    dict(area="Sandbox", name="An escape that leaves no trace", status="not_defended",
         evidence="Not detected; after a real escape the records can't be trusted", source="workbench/THREAT_MODEL.md"),
    dict(area="Sandbox", name="Docker tier shares the host kernel", status="not_defended",
         evidence="Limited to trusted code (decision D1); third-party agents use the VM tier",
         source="workbench/THREAT_MODEL.md"),
    dict(area="Sandbox", name="GH_TOKEN in the VM sandbox", status="not_defended",
         evidence="sbx puts one in every sandbox. It looks like a placeholder the proxy swaps, but that's unproven. "
                  "It is removed from the agent's process, but PID 1's environment still holds it",
         source="workbench/THREAT_MODEL.md"),
    # Untested (Phase 6 results, "Not verified" and "Still open for the gate").
    dict(area="Platform", name="Linux", status="untested",
         evidence="Nothing tested; the VM tier is refused there. Refusal tested only with a fake platform name",
         source="design/workbench-phase6-results.md"),
    dict(area="Release", name="External run on another machine", status="untested",
         evidence="Gate still open: needs an independent person (workbench/REVIEWING.md part 1)",
         source="design/workbench-phase6-results.md"),
    dict(area="Release", name="Outside review", status="untested",
         evidence="Gate still open (workbench/REVIEWING.md part 2)", source="design/workbench-phase6-results.md"),
    dict(area="Platform", name="Windows", status="untested",
         evidence="Planned, nothing implemented or run (audit and plan only)", source="design/windows-compatibility.md"),
]


def counts() -> dict[str, int]:
    out = {k: 0 for k in STATUS}
    for item in ITEMS:
        out[item["status"]] += 1
    return out

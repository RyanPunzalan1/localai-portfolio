"""A batch of trials with escape handling (design 4.5; Phase 4). Trusted host-side code.

The batch plants one shared host tripwire and records the host inventory before the first trial. Before and after every
trial it checks both. It stops at the first anomaly and never retries:

  contained attempt   the trial is labelled by the usual rules; the batch continues
  integrity anomaly   the trial is inconclusive (integrity); the batch stops; evidence is kept; the sandbox is removed
  suspected escape    as above, plus a plain warning: treat the results as untrustworthy (Tier 1: the host or Docker's VM
                      may be compromised; Tier 2: the disposable VM should have absorbed it, report it upstream)
  refused / error     a trial that raises (for example an unvalidated sbx version) stops the batch before anything else

What this cannot promise (design 4.5): an escape that leaves no trace is not detected, and after a real escape the
workbench's own logs live on the compromised side.
"""

import json
import uuid
from pathlib import Path

from workbench import isolation as iso, record as R, tripwire as tw


class Guard:
    """The batch's shared tripwire and inventory baseline. tokens() and check() are what run_trial uses."""

    def __init__(self, shared_dir=tw.SHARED_DIR, inventory=tw.inventory, batch_id=None):
        self.batch_id = batch_id or uuid.uuid4().hex[:8]
        self._inventory = inventory
        self.shared = tw.Tripwire(shared_dir, name=f"tripwire-{self.batch_id}.txt", create_parents=True)
        self.baseline = inventory()

    def tokens(self) -> dict:
        return {"tripwire_shared": self.shared.token}

    def check(self):
        """(shared tripwire changes, inventory changes since the batch started). Raises if the inventory is unreadable."""
        return self.shared.check(), tw.inventory_changes(self.baseline, self._inventory())

    def close(self, keep=False):
        if not keep:
            self.shared.remove()


def stop_message(anomaly, reasons, tier=None) -> str:
    if anomaly == "suspected_escape":
        lines = ["SUSPECTED ESCAPE: the batch is stopped. Treat this run's results as untrustworthy."]
        if tier == 2:
            lines.append("Tier 2 (VM): the disposable VM should have absorbed it. Report it to the sandbox runtime's project.")
        elif tier in (0, 1):
            lines.append("Tier 0/1 (Docker): treat the host or Docker Desktop's VM as possibly compromised.")
    elif anomaly == "refused":
        lines = ["REFUSED: the batch did not start this trial."]
    else:
        lines = ["INTEGRITY ANOMALY: the batch is stopped. Evidence is kept; the sandbox was removed."]
    lines += [f"  - {r}" for r in reasons[:6]]
    if anomaly != "refused":
        lines.append("Kept trial folders: ~/.agent-workbench/evidence/<run id>/")
    lines.append("Nothing was retried.")
    return "\n".join(lines)


def run_batch(cases, run_one, out_path, guard, summary_path=None, say=print) -> dict:
    """Run `run_one(case, guard) -> (record, details)` for each case, appending records to out_path, until the end or the
    first anomaly. Returns (and optionally writes) a summary. The guard is closed; its tripwire is kept on an anomaly."""
    summary = {"batch_id": guard.batch_id, "planned": len(cases), "completed": 0, "stopped": False, "anomaly": None,
               "reasons": [], "stopped_at": None, "message": None}

    def stop(anomaly, reasons, at, tier=None):
        summary.update(stopped=True, anomaly=anomaly, reasons=reasons, stopped_at=at,
                       message=stop_message(anomaly, reasons, tier))
        say(summary["message"])

    try:
        try:
            shared, inv = guard.check()
            pre = shared + inv
        except Exception as e:
            pre = [f"guard check failed: {e}"]
        if pre:
            stop("integrity", [f"before the first trial: {p}" for p in pre], 0)
        for i, case in enumerate(cases):
            if summary["stopped"]:
                break
            try:
                rec, _details = run_one(case, guard)
            except iso.IsolationRefused as e:
                stop("refused", [str(e)], i)
                break
            except Exception as e:  # the runtime did something it should not; never retried
                stop("integrity", [f"trial raised {e.__class__.__name__}: {str(e)[:200]}"], i)
                break
            R.append(out_path, rec)
            summary["completed"] += 1
            t = rec["evidence"].get("tripwires") or {}
            if t.get("anomaly"):
                stop(t["anomaly"], t.get("reasons") or [], i, rec["profile"]["tier"])
    finally:
        guard.close(keep=summary["anomaly"] in ("suspected_escape", "integrity"))
        if summary_path:
            Path(summary_path).write_text(json.dumps(summary, indent=2), encoding="utf-8", newline="\n")
    return summary

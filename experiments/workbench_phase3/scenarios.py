"""The Phase 3 scenarios, now loaded from the workbench's `core` scenario pack (workbench/scenarios/core, Phase 5).

Kept as a thin wrapper so the Phase 3 and Phase 4 harnesses run unchanged. The pre-Phase-5 Python definitions are
frozen in tests/fixtures/phase3_scenarios_legacy.py, and tests/test_workbench_phase5.py proves the pack is equivalent.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from workbench import scenario  # noqa: E402

PACK = scenario.core()
ORDER = list(PACK.order)


def instantiate(template_id: str) -> dict:
    return PACK.instantiate(template_id)

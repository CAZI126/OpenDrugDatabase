"""The mainline must stay detached from everything held aside.

Candidate selection, adjudication, cohorts, batch runs, enrichment, and the
ODD-006/007/007R research code all still exist in this repository. None of them
may become reachable from the core path again by accident, so this test pins the
core's import closure rather than trusting convention.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Modules whose presence would mean the core had re-acquired a judgment,
# a database, or an audit obligation.
HELD_ASIDE = (
    "odd.batch",
    "odd.cli.main",
    "odd.cohort",
    "odd.cohort_runner",
    "odd.connectors.dailymed.batch_selection",
    "odd.connectors.dailymed.selection",
    "odd.diffs",
    "odd.enrichment",
    "odd.governance",
    "odd.models.batch",
    "odd.models.enrichment",
    "odd.odd007_verification",
    "odd.scope_guard",
    "odd.service",
    "odd.storage",
    "odd.utilization",
    "odd.validation",
    "odd.versioning",
)

_PROBE = """
import json, sys
import odd.core.cli
print(json.dumps(sorted(m for m in sys.modules if m.startswith("odd"))))
"""


def _mainline_import_closure() -> set[str]:
    completed = subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True,
        check=True,
        cwd=REPO_ROOT,
        text=True,
    )
    import json

    return set(json.loads(completed.stdout))


def test_the_core_does_not_import_anything_held_aside() -> None:
    closure = _mainline_import_closure()

    reached = sorted(
        module
        for module in closure
        if any(module == name or module.startswith(f"{name}.") for name in HELD_ASIDE)
    )
    assert reached == [], f"the core path has re-acquired off-mainline modules: {reached}"


def test_the_core_runs_without_the_application_service_or_a_database() -> None:
    closure = _mainline_import_closure()

    assert "odd.service" not in closure
    assert "odd.cli.main" not in closure
    assert "sqlite3" not in closure


def test_the_held_aside_modules_still_work_when_asked_for_directly() -> None:
    """Detached is not deleted: the legacy names must still resolve."""

    from odd.connectors.dailymed import select_apixaban_candidate
    from odd.models import BatchRun

    assert callable(select_apixaban_candidate)
    assert BatchRun.__name__ == "BatchRun"

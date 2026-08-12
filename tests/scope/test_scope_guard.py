from __future__ import annotations

import pytest

from odd.constants import (
    REGULATORY_ROLE_DISCOVERY_SCOPE,
    VALIDATION_LABEL_SCOPE,
)
from odd.errors import ProvenanceValidationFailure
from odd.models import SelectionStatus
from odd.models.enrichment import EnrichmentDecisionRevision
from odd.scope_guard import require_input_scope, require_role_discovery_input


def test_matching_scope_is_accepted_and_recorded() -> None:
    diagnostics: list[dict[str, str]] = []
    result = require_input_scope(
        intended_use_scope=VALIDATION_LABEL_SCOPE,
        required_input_scope=VALIDATION_LABEL_SCOPE,
        save_diagnostic=diagnostics.append,
    )
    assert result["status"] == "SCOPE_MATCH"
    assert diagnostics == [result]


@pytest.mark.parametrize("producer_scope", [None, VALIDATION_LABEL_SCOPE])
def test_missing_or_mismatched_scope_fails_closed(producer_scope: str | None) -> None:
    diagnostics: list[dict[str, str]] = []
    with pytest.raises(ProvenanceValidationFailure) as captured:
        require_input_scope(
            intended_use_scope=producer_scope,
            required_input_scope=REGULATORY_ROLE_DISCOVERY_SCOPE,
            save_diagnostic=diagnostics.append,
        )
    assert diagnostics[0]["status"] == "INTENDED_USE_SCOPE_VIOLATION"
    assert captured.value.details == diagnostics[0]


def test_scope_failure_precedes_selection_and_ingest() -> None:
    calls: list[str] = []
    with pytest.raises(ProvenanceValidationFailure):
        require_role_discovery_input(VALIDATION_LABEL_SCOPE, lambda value: calls.append("saved"))
        calls.extend(("selected", "ingested"))
    assert calls == ["saved"]


def test_odd005_exact_lexical_decision_is_rejected_by_role_discovery() -> None:
    decision = EnrichmentDecisionRevision(
        revision_id="revision",
        enrichment_run_id="run",
        enrichment_snapshot_id="snapshot",
        parent_decision_id="parent",
        previous_revision_id=None,
        rank=1,
        ingredient_id="atorvastatin",
        selection_status=SelectionStatus.MANUAL_REVIEW_REQUIRED,
        selected_candidate_id=None,
        selected_set_id=None,
        selected_source_version=None,
        selection_reason="development fixture",
        manual_review_required=True,
        intended_use_scope=VALIDATION_LABEL_SCOPE,
    )
    diagnostics: list[dict[str, str]] = []
    with pytest.raises(ProvenanceValidationFailure):
        require_role_discovery_input(decision.intended_use_scope, diagnostics.append)
    assert diagnostics[0]["intended_use_scope"] == VALIDATION_LABEL_SCOPE
    assert diagnostics[0]["required_input_scope"] == REGULATORY_ROLE_DISCOVERY_SCOPE

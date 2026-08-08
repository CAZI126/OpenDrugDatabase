"""ODD-003 candidate evidence, classification, and deterministic selection tests."""

from __future__ import annotations

from dataclasses import replace

import pytest

from odd.connectors.dailymed.batch_selection import classify_and_select_candidates
from odd.connectors.dailymed.client import DailyMedConnector
from odd.models import (
    CandidateClassification,
    CandidateLookup,
    DailyMedCandidate,
    SelectionStatus,
)
from odd.provenance.canonical import canonical_json_bytes
from odd.provenance.hashing import sha256_bytes
from odd.utilization import ingredient_identity, load_utilization_list
from tests.odd003_support import Top10Transport
from tests.odd_support import FixedClock


def _selection(name: str, *, reverse: bool = False):
    entries = {entry.ingredient_name: entry for entry in load_utilization_list().entries}
    transport = Top10Transport(reverse_results=reverse)
    connector = DailyMedConnector(
        base_url="https://dailymed.example/services/v2",
        transport=transport,
        clock=FixedClock(),
    )
    lookup = connector.lookup(name)
    return classify_and_select_candidates(
        lookup,
        ingredient_identity(entries[name]),
        utilization_list_id="us-top10-2023",
    )


def test_exact_single_ingredient_prescription_candidate_is_accepted() -> None:
    decision = _selection("atorvastatin")
    selected = next(
        item for item in decision.candidates if item.candidate_id == decision.selected_candidate_id
    )
    assert decision.selection_status is SelectionStatus.SELECTED
    assert CandidateClassification.EXACT_SINGLE_INGREDIENT_MATCH in selected.classifications
    assert CandidateClassification.PRESCRIPTION_PRODUCT in selected.classifications


def test_normalized_single_ingredient_match_is_recorded() -> None:
    decision = _selection("levothyroxine")
    assert CandidateClassification.SINGLE_INGREDIENT_NORMALIZED_MATCH in (
        decision.candidates[0].classifications
    )


def test_combination_false_positive_is_rejected_but_retained() -> None:
    decision = _selection("lisinopril")
    combination = next(
        item
        for item in decision.candidates
        if CandidateClassification.COMBINATION_PRODUCT in item.classifications
    )
    assert not combination.accepted_for_selection
    assert "combination product" in combination.rejection_reasons[0]
    assert decision.selected_set_id == "44444444-4444-4444-8444-444444444444"


def test_wrong_ingredient_is_rejected() -> None:
    decision = _selection("gabapentin")
    wrong = next(
        item
        for item in decision.candidates
        if CandidateClassification.WRONG_INGREDIENT in item.classifications
    )
    assert not wrong.accepted_for_selection
    assert wrong.generic_name == "pregabalin"


def test_repackaged_candidate_is_rejected() -> None:
    decision = _selection("atorvastatin")
    repackaged = next(
        item
        for item in decision.candidates
        if CandidateClassification.REPACKAGED_PRODUCT in item.classifications
    )
    assert not repackaged.accepted_for_selection


def test_archived_candidate_is_rejected() -> None:
    decision = _selection("amlodipine")
    assert any(
        CandidateClassification.ARCHIVED_OR_INACTIVE in item.classifications
        for item in decision.candidates
    )
    assert decision.selection_status is SelectionStatus.SELECTED


def test_incomplete_metadata_is_explicit() -> None:
    decision = _selection("losartan")
    incomplete = next(
        item
        for item in decision.candidates
        if CandidateClassification.MISSING_REQUIRED_METADATA in item.classifications
    )
    assert "incomplete" in incomplete.rejection_reasons[0]


def test_inhalation_candidate_preserves_dosage_form_and_route() -> None:
    decision = _selection("albuterol")
    selected = next(item for item in decision.candidates if item.accepted_for_selection)
    assert selected.dosage_form == "AEROSOL, METERED"
    assert selected.route == "RESPIRATORY (INHALATION)"


def test_duplicate_candidate_is_retained_with_distinct_evidence_id() -> None:
    decision = _selection("metoprolol")
    assert len(decision.candidates) == 2
    assert len({item.candidate_id for item in decision.candidates}) == 2
    assert any(
        CandidateClassification.DUPLICATE_CANDIDATE in item.classifications
        for item in decision.candidates
    )


def test_higher_version_is_deterministic_tie_break() -> None:
    decision = _selection("metformin")
    assert decision.selected_source_version == "4"
    assert decision.selected_set_id == "22222222-2222-4222-8222-222222222222"


def test_response_order_does_not_change_winner_or_evidence_order() -> None:
    first = _selection("metformin")
    second = _selection("metformin", reverse=True)
    assert first.selected_set_id == second.selected_set_id
    assert [item.set_id for item in first.candidates] == [
        item.set_id for item in second.candidates
    ]


def test_equal_authoritative_tie_is_unresolved_not_lexically_selected() -> None:
    decision = _selection("omeprazole")
    assert decision.selection_status is SelectionStatus.MULTIPLE_EQUIVALENT_CANDIDATES
    assert decision.selected_set_id is None
    assert decision.manual_review_required
    assert all(
        CandidateClassification.AMBIGUOUS in item.classifications
        for item in decision.candidates
    )


def test_no_candidates_is_explicit() -> None:
    template = _selection("atorvastatin")
    empty = CandidateLookup(
        candidates=(),
        source_url="https://dailymed.example/empty",
        retrieved_at=FixedClock()(),
        raw_body=b'{"data":[]}',
        payload={"data": []},
    )
    entry = load_utilization_list().entries[0]
    decision = classify_and_select_candidates(
        empty,
        ingredient_identity(entry),
        utilization_list_id="us-top10-2023",
        selection_rule_version=template.selection_rule_version,
    )
    assert decision.selection_status is SelectionStatus.NO_CANDIDATE
    assert decision.candidates == ()


def test_truncated_candidate_page_never_forces_a_selection() -> None:
    transport = Top10Transport()
    connector = DailyMedConnector(
        base_url="https://dailymed.example/services/v2",
        transport=transport,
        clock=FixedClock(),
    )
    original = connector.lookup("atorvastatin")
    truncated = replace(
        original,
        payload={**original.payload, "metadata": {"total_elements": "101"}},
    )
    decision = classify_and_select_candidates(
        truncated,
        ingredient_identity(load_utilization_list().entries[0]),
        utilization_list_id="us-top10-2023",
    )
    assert decision.selection_status is SelectionStatus.AMBIGUOUS_REQUIRES_REVIEW
    assert decision.selected_set_id is None
    assert "pagination" in decision.selection_reason


@pytest.mark.parametrize("total_elements", [None, True, float("inf"), {"invalid": 1}])
def test_invalid_candidate_count_metadata_does_not_abort_selection(
    total_elements: object,
) -> None:
    transport = Top10Transport()
    connector = DailyMedConnector(
        base_url="https://dailymed.example/services/v2",
        transport=transport,
        clock=FixedClock(),
    )
    original = connector.lookup("atorvastatin")
    lookup = replace(
        original,
        payload={**original.payload, "metadata": {"total_elements": total_elements}},
    )
    decision = classify_and_select_candidates(
        lookup,
        ingredient_identity(load_utilization_list().entries[0]),
        utilization_list_id="us-top10-2023",
    )
    assert decision.selection_status is SelectionStatus.SELECTED


def test_salt_or_form_variant_is_not_treated_as_equivalent() -> None:
    base = _selection("atorvastatin")
    candidate = DailyMedCandidate(
        set_id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        source_version="1",
        title="ATORVASTATIN CALCIUM",
        published_date="Jul 01, 2026",
        metadata={
            **base.candidates[0].raw_metadata,
            "setid": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            "spl_version": "1",
            "active_ingredients": ["atorvastatin calcium"],
        },
    )
    lookup = CandidateLookup(
        candidates=(candidate,),
        source_url="https://dailymed.example/salt",
        retrieved_at=FixedClock()(),
        raw_body=canonical_json_bytes({"data": [candidate.metadata]}),
        payload={"data": [candidate.metadata]},
    )
    decision = classify_and_select_candidates(
        lookup,
        ingredient_identity(load_utilization_list().entries[0]),
        utilization_list_id="us-top10-2023",
    )
    assert decision.selection_status is SelectionStatus.NO_ACCEPTABLE_CANDIDATE
    assert CandidateClassification.SALT_OR_FORM_VARIANT in decision.candidates[0].classifications


def test_raw_candidate_metadata_hash_is_canonical_and_stable() -> None:
    decision = _selection("atorvastatin")
    for item in decision.candidates:
        assert item.raw_metadata_sha256 == sha256_bytes(canonical_json_bytes(item.raw_metadata))


def test_selection_rule_version_changes_decision_identity() -> None:
    decision = _selection("atorvastatin")
    transport = Top10Transport()
    connector = DailyMedConnector(
        base_url="https://dailymed.example/services/v2",
        transport=transport,
        clock=FixedClock(),
    )
    changed = classify_and_select_candidates(
        connector.lookup("atorvastatin"),
        ingredient_identity(load_utilization_list().entries[0]),
        utilization_list_id="us-top10-2023",
        selection_rule_version="test-rule/2",
    )
    assert changed.decision_id != decision.decision_id
    assert replace(changed, decision_id=decision.decision_id) != decision

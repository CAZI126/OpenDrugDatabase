"""Offline ODD-005 budget, resume, drift, revision, and artifact tests."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from odd.errors import ProvenanceValidationFailure, RawHashConflict
from odd.models import SelectionStatus
from odd.models.enrichment import (
    EnrichmentBudget,
    EnrichmentCompleteness,
    EnrichmentItemStatus,
    EnrichmentRunStatus,
    EvidenceResult,
    EvidenceType,
)
from odd.provenance.hashing import sha256_file
from tests.odd005_support import odd005_service


def test_read_only_plan_shows_candidate_request_and_byte_bounds(tmp_path: Path) -> None:
    application, transport, parent_run_id = odd005_service(tmp_path)
    plan = application.enrichment_plan(
        parent_run_id,
        ranks=(1,),
        budget=_budget(max_requests=3, max_detail_pages=2),
    )
    assert plan.parent_live_batch_run_id == parent_run_id
    assert plan.items[0].candidate_count == 1
    assert plan.items[0].tier1_minimum_requests == 1
    assert plan.items[0].tier1_maximum_requests == 2
    assert plan.planned_maximum_downloaded_bytes <= 3 * (65_536 + 1)
    assert transport.packaging_request_count == 0


def test_new_observation_rejects_non_hex_parent_database_hash(tmp_path: Path) -> None:
    application, _transport, parent_run_id = odd005_service(tmp_path)
    with pytest.raises(ProvenanceValidationFailure, match="64 hex digits"):
        application.enrichment_new_observation(
            parent_run_id, ranks=(1,), parent_database_sha256="z" * 64
        )


def test_tier1_run_is_incomplete_without_nonrepackager_or_structure_proof(
    tmp_path: Path,
) -> None:
    application, transport, parent_run_id = odd005_service(tmp_path)
    run, _items = application.enrichment_new_observation(
        parent_run_id,
        ranks=(1,),
        parent_database_sha256=sha256_file(application.repository.path),
    )
    artifact = application.enrichment_execute(
        run.enrichment_run_id,
        budget=_budget(),
        allow_tier2=False,
    )
    final_run, items = application.enrichment_status(run.enrichment_run_id)
    assert transport.packaging_request_count == 1
    assert transport.xml_request_count == 0
    assert final_run.status is EnrichmentRunStatus.COMPLETED_WITH_UNRESOLVED_ITEMS
    assert final_run.selected_count == 0
    assert final_run.manual_review_count == 1
    assert items[0].enrichment_completeness is EnrichmentCompleteness.INCOMPLETE
    assert items[0].selection_status is SelectionStatus.MANUAL_REVIEW_REQUIRED
    assert items[0].candidates_unknown == 1
    assert "UNKNOWN required evidence" in items[0].manual_review_reason
    assert len(artifact.canonical_sha256) == 64
    assert all(application.enrichment_verify(run.enrichment_run_id).values())


def test_tier1_fetches_contiguous_pages_through_a_short_terminal_page(
    tmp_path: Path,
) -> None:
    application, transport, parent_run_id = odd005_service(tmp_path)
    set_id = next(
        value for value, (ingredient, _rank) in transport.by_set_id.items()
        if ingredient == "atorvastatin"
    )
    first_page = [
        {
            "active_ingredients": [{"name": "atorvastatin"}],
            "product_code": f"00001-{index:03d}",
        }
        for index in range(100)
    ]
    transport.packaging_pages[set_id] = [
        first_page,
        [
            {
                "active_ingredients": [{"name": "atorvastatin"}],
                "product_code": "00001-100",
            }
        ],
    ]
    run, _items = application.enrichment_new_observation(
        parent_run_id,
        ranks=(1,),
        parent_database_sha256=sha256_file(application.repository.path),
    )
    application.enrichment_execute(
        run.enrichment_run_id,
        budget=_budget(max_requests=2),
        allow_tier2=False,
    )
    _final, items = application.enrichment_status(run.enrichment_run_id)
    assert transport.packaging_request_count == 2
    assert items[0].tier1_complete == 1
    assertion = next(
        value
        for value in application.enrichment_evidence(run.enrichment_run_id, rank=1)
        if value.evidence_type is EvidenceType.EXACT_INGREDIENT_IDENTITY
        and value.tier.value == "TIER_1"
    )
    assert assertion.raw_response_sha256 is None
    assert len(assertion.source_response_sha256s) == 2
    retained_hashes = {
        value.raw_sha256
        for value in application.repository.get_detail_responses(
            run.enrichment_run_id, successful_only=True
        )
    }
    assert set(assertion.source_response_sha256s) <= retained_hashes


def test_tier1_duplicate_product_identity_keeps_candidate_incomplete(
    tmp_path: Path,
) -> None:
    application, transport, parent_run_id = odd005_service(tmp_path)
    set_id = next(
        value for value, (ingredient, _rank) in transport.by_set_id.items()
        if ingredient == "atorvastatin"
    )
    first_page = [
        {
            "active_ingredients": [{"name": "atorvastatin"}],
            "product_code": f"00001-{index:03d}",
        }
        for index in range(100)
    ]
    transport.packaging_pages[set_id] = [first_page, [first_page[0]]]
    run, _items = application.enrichment_new_observation(
        parent_run_id,
        ranks=(1,),
        parent_database_sha256=sha256_file(application.repository.path),
    )
    application.enrichment_execute(
        run.enrichment_run_id,
        budget=_budget(max_requests=2),
        allow_tier2=False,
    )
    _final, items = application.enrichment_status(run.enrichment_run_id)
    assert items[0].tier1_complete == 0
    assertions = application.enrichment_evidence(run.enrichment_run_id, rank=1)
    single = next(
        value
        for value in assertions
        if value.evidence_type is EvidenceType.SINGLE_ACTIVE_INGREDIENT
        and value.tier.value == "TIER_1"
    )
    assert single.result is EvidenceResult.UNKNOWN
    assert "repeated a product identity" in single.diagnostic


def test_tier1_conflicting_product_metadata_keeps_candidate_incomplete(
    tmp_path: Path,
) -> None:
    application, transport, parent_run_id = odd005_service(tmp_path)
    set_id = next(
        value
        for value, (ingredient, _rank) in transport.by_set_id.items()
        if ingredient == "atorvastatin"
    )
    first_page = [
        {
            "active_ingredients": [{"name": "atorvastatin"}],
            "product_code": f"00001-{index:03d}",
        }
        for index in range(100)
    ]
    transport.packaging_pages[set_id] = [
        first_page,
        [
            {
                "active_ingredients": [{"name": "amlodipine"}],
                "product_code": "00001-000",
            }
        ],
    ]
    run, _items = application.enrichment_new_observation(
        parent_run_id,
        ranks=(1,),
        parent_database_sha256=sha256_file(application.repository.path),
    )
    application.enrichment_execute(
        run.enrichment_run_id,
        budget=_budget(max_requests=2),
        allow_tier2=False,
    )
    _final, items = application.enrichment_status(run.enrichment_run_id)
    assert items[0].tier1_complete == 0
    assertion = next(
        value
        for value in application.enrichment_evidence(run.enrichment_run_id, rank=1)
        if value.evidence_type is EvidenceType.SINGLE_ACTIVE_INGREDIENT
        and value.tier.value == "TIER_1"
    )
    assert assertion.result is EvidenceResult.CONFLICT
    assert "conflicting metadata" in assertion.diagnostic


def test_tier1_missing_product_identity_does_not_invent_page_index_identity(
    tmp_path: Path,
) -> None:
    application, transport, parent_run_id = odd005_service(tmp_path)
    set_id = next(
        value
        for value, (ingredient, _rank) in transport.by_set_id.items()
        if ingredient == "atorvastatin"
    )
    transport.packaging_pages[set_id] = [
        [{"active_ingredients": [{"name": "atorvastatin"}]}]
    ]
    run, _items = application.enrichment_new_observation(
        parent_run_id,
        ranks=(1,),
        parent_database_sha256=sha256_file(application.repository.path),
    )
    application.enrichment_execute(
        run.enrichment_run_id, budget=_budget(), allow_tier2=False
    )
    _final, items = application.enrichment_status(run.enrichment_run_id)
    assert items[0].tier1_complete == 0
    assertion = next(
        value
        for value in application.enrichment_evidence(run.enrichment_run_id, rank=1)
        if value.evidence_type is EvidenceType.SINGLE_ACTIVE_INGREDIENT
        and value.tier.value == "TIER_1"
    )
    assert assertion.result is EvidenceResult.UNKNOWN
    assert "product_code" in assertion.diagnostic


def test_malformed_tier1_metadata_keeps_exact_bytes_and_is_not_redownloaded(
    tmp_path: Path,
) -> None:
    application, transport, parent_run_id = odd005_service(
        tmp_path, malformed_packaging_rank=1
    )
    run, _items = application.enrichment_new_observation(
        parent_run_id,
        ranks=(1,),
        parent_database_sha256=sha256_file(application.repository.path),
    )
    first = application.enrichment_execute(
        run.enrichment_run_id, budget=_budget(), allow_tier2=False
    )
    responses = application.repository.get_detail_responses(run.enrichment_run_id)
    assert responses[-1].raw_body == b'{"data":'
    assert responses[-1].raw_sha256 is not None
    assert responses[-1].error_category == "malformed_metadata"
    _final, items = application.enrichment_status(run.enrichment_run_id)
    assert items[0].failure_count == 1
    assert items[0].tier1_complete == 0
    request_count = len(transport.requests)
    repeated = application.enrichment_execute(
        run.enrichment_run_id, budget=_budget(), allow_tier2=False
    )
    assert len(transport.requests) == request_count
    assert repeated.canonical_sha256 == first.canonical_sha256
    assert all(application.enrichment_verify(run.enrichment_run_id).values())


def test_completed_resume_is_network_free_and_keeps_artifact_and_database_hash(
    tmp_path: Path,
) -> None:
    application, transport, parent_run_id = odd005_service(tmp_path)
    run, _items = application.enrichment_new_observation(
        parent_run_id,
        ranks=(1,),
        parent_database_sha256=sha256_file(application.repository.path),
    )
    first = application.enrichment_execute(
        run.enrichment_run_id, budget=_budget(), allow_tier2=False
    )
    request_count = len(transport.requests)
    database_hash = sha256_file(application.repository.path)
    revisions = application.enrichment_decisions(run.enrichment_run_id)
    repeated = application.enrichment_execute(
        run.enrichment_run_id, budget=_budget(), allow_tier2=False
    )
    assert len(transport.requests) == request_count
    assert repeated.canonical_sha256 == first.canonical_sha256
    assert sha256_file(application.repository.path) == database_hash
    assert application.enrichment_decisions(run.enrichment_run_id) == revisions


def test_budget_partial_state_resumes_only_missing_candidate(tmp_path: Path) -> None:
    application, transport, parent_run_id = odd005_service(tmp_path)
    run, _items = application.enrichment_new_observation(
        parent_run_id,
        ranks=(1, 2),
        parent_database_sha256=sha256_file(application.repository.path),
    )
    first = application.enrichment_execute(
        run.enrichment_run_id,
        budget=_budget(max_requests=1, retry_limit=0),
        allow_tier2=False,
    )
    partial, _items = application.enrichment_status(run.enrichment_run_id)
    assert partial.status is EnrichmentRunStatus.PARTIAL_BUDGET
    assert transport.packaging_request_count == 1
    second = application.enrichment_execute(
        run.enrichment_run_id,
        budget=_budget(max_requests=1, retry_limit=0),
        allow_tier2=False,
    )
    final, items = application.enrichment_status(run.enrichment_run_id)
    assert final.status is EnrichmentRunStatus.COMPLETED_WITH_UNRESOLVED_ITEMS
    assert transport.packaging_request_count == 2
    assert final.cache_hit_count == 1
    assert tuple(item.tier1_complete for item in items) == (1, 1)
    assert first.canonical_sha256 != second.canonical_sha256


def test_source_version_drift_is_retained_and_blocks_selection(tmp_path: Path) -> None:
    application, _transport, parent_run_id = odd005_service(
        tmp_path, source_drift_rank=1
    )
    run, _items = application.enrichment_new_observation(
        parent_run_id,
        ranks=(1,),
        parent_database_sha256=sha256_file(application.repository.path),
    )
    application.enrichment_execute(
        run.enrichment_run_id, budget=_budget(), allow_tier2=False
    )
    final, items = application.enrichment_status(run.enrichment_run_id)
    assert final.source_drift_count == 1
    assert items[0].item_status is EnrichmentItemStatus.SOURCE_DRIFT
    assert items[0].enrichment_completeness is EnrichmentCompleteness.SOURCE_DRIFT
    assert items[0].selected_set_id is None


def test_source_set_id_drift_is_retained_and_blocks_selection(tmp_path: Path) -> None:
    application, _transport, parent_run_id = odd005_service(
        tmp_path, set_id_drift_rank=1
    )
    run, _items = application.enrichment_new_observation(
        parent_run_id,
        ranks=(1,),
        parent_database_sha256=sha256_file(application.repository.path),
    )
    application.enrichment_execute(
        run.enrichment_run_id, budget=_budget(), allow_tier2=False
    )
    final, items = application.enrichment_status(run.enrichment_run_id)
    assert final.source_drift_count == 1
    assert items[0].item_status is EnrichmentItemStatus.SOURCE_DRIFT
    assert items[0].selected_set_id is None


def test_source_publication_date_drift_is_retained_and_blocks_selection(
    tmp_path: Path,
) -> None:
    application, _transport, parent_run_id = odd005_service(
        tmp_path, published_date_drift_rank=1
    )
    run, _items = application.enrichment_new_observation(
        parent_run_id,
        ranks=(1,),
        parent_database_sha256=sha256_file(application.repository.path),
    )
    application.enrichment_execute(
        run.enrichment_run_id, budget=_budget(), allow_tier2=False
    )
    final, items = application.enrichment_status(run.enrichment_run_id)
    assert final.source_drift_count == 1
    assert items[0].item_status is EnrichmentItemStatus.SOURCE_DRIFT
    assert "SOURCE_DRIFT" in items[0].manual_review_reason


def test_combination_candidate_is_proven_ineligible_without_tier2(tmp_path: Path) -> None:
    application, transport, parent_run_id = odd005_service(
        tmp_path, combination_rank=1
    )
    run, _items = application.enrichment_new_observation(
        parent_run_id,
        ranks=(1,),
        parent_database_sha256=sha256_file(application.repository.path),
    )
    application.enrichment_execute(
        run.enrichment_run_id, budget=_budget(), allow_tier2=False
    )
    _final, items = application.enrichment_status(run.enrichment_run_id)
    assert transport.xml_request_count == 0
    assert items[0].enrichment_completeness is EnrichmentCompleteness.COMPLETE
    assert items[0].selection_status is SelectionStatus.NO_ACCEPTABLE_CANDIDATE
    assert items[0].candidates_proven_ineligible == 1


def test_tier2_gate_stops_before_xml_when_candidate_cap_is_zero(tmp_path: Path) -> None:
    application, transport, parent_run_id = odd005_service(tmp_path)
    run, _items = application.enrichment_new_observation(
        parent_run_id,
        ranks=(1,),
        parent_database_sha256=sha256_file(application.repository.path),
    )
    application.enrichment_execute(
        run.enrichment_run_id,
        budget=_budget(max_tier2_candidates=0),
        allow_tier2=True,
    )
    _final, items = application.enrichment_status(run.enrichment_run_id)
    assert transport.xml_request_count == 0
    assert "Tier 2 gate stopped" in items[0].manual_review_reason


def test_tier2_xml_is_cached_but_absent_repack_code_remains_unknown(
    tmp_path: Path,
) -> None:
    application, transport, parent_run_id = odd005_service(tmp_path)
    run, _items = application.enrichment_new_observation(
        parent_run_id,
        ranks=(1,),
        parent_database_sha256=sha256_file(application.repository.path),
    )
    application.enrichment_execute(
        run.enrichment_run_id,
        budget=_budget(
            max_requests=2,
            max_bytes=4_000_000,
            max_response_bytes=1_500_000,
            max_tier2_candidates=1,
        ),
        allow_tier2=True,
    )
    _final, items = application.enrichment_status(run.enrichment_run_id)
    assert transport.packaging_request_count == 1
    assert transport.xml_request_count == 1
    assert items[0].tier2_complete == 1
    assert items[0].raw_xml_sha256 is None
    assert items[0].selection_status is SelectionStatus.MANUAL_REVIEW_REQUIRED


def test_terminal_tier1_run_can_advance_once_to_explicit_bounded_tier2(
    tmp_path: Path,
) -> None:
    application, transport, parent_run_id = odd005_service(tmp_path)
    run, _items = application.enrichment_new_observation(
        parent_run_id,
        ranks=(1,),
        parent_database_sha256=sha256_file(application.repository.path),
    )
    tier1 = application.enrichment_execute(
        run.enrichment_run_id, budget=_budget(), allow_tier2=False
    )
    assert transport.packaging_request_count == 1
    assert transport.xml_request_count == 0
    tier2_budget = _budget(
        max_requests=1,
        max_bytes=2_000_000,
        max_response_bytes=1_500_000,
        max_tier2_candidates=1,
    )
    tier2 = application.enrichment_execute(
        run.enrichment_run_id, budget=tier2_budget, allow_tier2=True
    )
    assert transport.xml_request_count == 1
    assert tier2.canonical_sha256 != tier1.canonical_sha256
    request_count = len(transport.requests)
    repeated = application.enrichment_execute(
        run.enrichment_run_id, budget=tier2_budget, allow_tier2=True
    )
    assert len(transport.requests) == request_count
    assert repeated.canonical_sha256 == tier2.canonical_sha256


def test_terminal_tier2_permanent_failure_is_not_retried_or_revised(
    tmp_path: Path,
) -> None:
    application, transport, parent_run_id = odd005_service(tmp_path, xml_status=406)
    run, _items = application.enrichment_new_observation(
        parent_run_id,
        ranks=(1,),
        parent_database_sha256=sha256_file(application.repository.path),
    )
    tier1 = application.enrichment_execute(
        run.enrichment_run_id, budget=_budget(), allow_tier2=False
    )
    revisions = application.enrichment_decisions(run.enrichment_run_id)
    tier2_budget = _budget(
        max_requests=1,
        max_bytes=2_000_000,
        max_response_bytes=1_500_000,
        max_tier2_candidates=1,
    )
    failed = application.enrichment_execute(
        run.enrichment_run_id, budget=tier2_budget, allow_tier2=True
    )
    assert failed.canonical_sha256 != tier1.canonical_sha256
    assert application.enrichment_decisions(run.enrichment_run_id) == revisions
    request_count = len(transport.requests)
    repeated = application.enrichment_execute(
        run.enrichment_run_id, budget=tier2_budget, allow_tier2=True
    )
    final, items = application.enrichment_status(run.enrichment_run_id)
    assert len(transport.requests) == request_count
    assert repeated.canonical_sha256 == failed.canonical_sha256
    assert final.request_count == 2
    assert final.failure_count == items[0].failure_count == 1


def test_interrupted_post_download_resume_materializes_cache_without_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    application, transport, parent_run_id = odd005_service(tmp_path)
    run, _items = application.enrichment_new_observation(
        parent_run_id,
        ranks=(1,),
        parent_database_sha256=sha256_file(application.repository.path),
    )
    application.enrichment_execute(
        run.enrichment_run_id, budget=_budget(), allow_tier2=False
    )
    original_store = application.repository.store_decision_revision

    def interrupt(*args: object, **kwargs: object) -> bool:
        del args, kwargs
        raise RawHashConflict("synthetic interruption after exact-byte storage")

    monkeypatch.setattr(application.repository, "store_decision_revision", interrupt)
    tier2_budget = _budget(
        max_requests=1,
        max_bytes=2_000_000,
        max_response_bytes=1_500_000,
        max_tier2_candidates=1,
    )
    with pytest.raises(RawHashConflict, match="synthetic interruption"):
        application.enrichment_execute(
            run.enrichment_run_id, budget=tier2_budget, allow_tier2=True
        )
    request_count = len(transport.requests)
    monkeypatch.setattr(
        application.repository, "store_decision_revision", original_store
    )
    resumed = application.enrichment_execute(
        run.enrichment_run_id, budget=tier2_budget, allow_tier2=True
    )
    final, items = application.enrichment_status(run.enrichment_run_id)
    assert len(transport.requests) == request_count
    assert final.request_count == 2
    assert items[0].tier2_complete == 1
    assert resumed.report.run.current_snapshot_id != run.current_snapshot_id
    assert all(application.enrichment_verify(run.enrichment_run_id).values())


def test_malformed_tier2_xml_keeps_exact_bytes_and_proves_unsupported_structure(
    tmp_path: Path,
) -> None:
    application, transport, parent_run_id = odd005_service(
        tmp_path, malformed_xml_rank=1
    )
    run, _items = application.enrichment_new_observation(
        parent_run_id,
        ranks=(1,),
        parent_database_sha256=sha256_file(application.repository.path),
    )
    application.enrichment_execute(
        run.enrichment_run_id,
        budget=_budget(
            max_requests=2,
            max_bytes=4_000_000,
            max_response_bytes=1_500_000,
            max_tier2_candidates=1,
        ),
        allow_tier2=True,
    )
    assert transport.xml_request_count == 1
    responses = application.repository.get_detail_responses(
        run.enrichment_run_id, tier=None, successful_only=True
    )
    xml_response = next(value for value in responses if value.tier.value == "TIER_2")
    assert xml_response.raw_body == b"<document"
    assert xml_response.raw_sha256 is not None
    assert xml_response.error_category == "malformed_xml"
    assertions = application.enrichment_evidence(run.enrichment_run_id, rank=1)
    structure = next(
        value
        for value in assertions
        if value.evidence_type is EvidenceType.SUPPORTED_DOCUMENT_STRUCTURE
        and value.tier.value == "TIER_2"
    )
    assert structure.result is EvidenceResult.PROVEN_FALSE
    assert structure.source_response_sha256s == (xml_response.raw_sha256,)
    _final, items = application.enrichment_status(run.enrichment_run_id)
    assert items[0].failure_count == 1
    assert items[0].selection_status is SelectionStatus.NO_ACCEPTABLE_CANDIDATE
    assert all(application.enrichment_verify(run.enrichment_run_id).values())


def test_selected_xml_is_promoted_from_exact_cache_without_redownload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    application, transport, parent_run_id = odd005_service(tmp_path)
    original_extract = application.enrichment.extractor.spl_xml

    def synthetic_nonrepack_proof(*args: object, **kwargs: object):
        extracted = original_extract(*args, **kwargs)
        drafts = tuple(
            replace(
                draft,
                result=EvidenceResult.PROVEN_FALSE,
                diagnostic="Synthetic explicit non-repackager proof for offline reuse test.",
            )
            if draft.evidence_type is EvidenceType.REPACKAGED_PRODUCT
            else draft
            for draft in extracted.drafts
        )
        return replace(extracted, drafts=drafts)

    monkeypatch.setattr(
        application.enrichment.extractor, "spl_xml", synthetic_nonrepack_proof
    )
    run, _items = application.enrichment_new_observation(
        parent_run_id,
        ranks=(1,),
        parent_database_sha256=sha256_file(application.repository.path),
    )
    first = application.enrichment_execute(
        run.enrichment_run_id,
        budget=_budget(
            max_requests=2,
            max_bytes=4_000_000,
            max_response_bytes=1_500_000,
            max_tier2_candidates=1,
        ),
        allow_tier2=True,
    )
    final, items = application.enrichment_status(run.enrichment_run_id)
    assert final.selected_count == final.ingested_count == final.verified_count == 1
    assert items[0].raw_xml_sha256 is not None
    assert transport.xml_request_count == 1
    request_count = len(transport.requests)
    repeated = application.enrichment_execute(
        run.enrichment_run_id,
        budget=_budget(
            max_requests=2,
            max_bytes=4_000_000,
            max_response_bytes=1_500_000,
            max_tier2_candidates=1,
        ),
        allow_tier2=True,
    )
    assert len(transport.requests) == request_count
    assert transport.xml_request_count == 1
    assert repeated.canonical_sha256 == first.canonical_sha256


def test_permanent_detail_404_is_not_retried(tmp_path: Path) -> None:
    application, transport, parent_run_id = odd005_service(
        tmp_path, packaging_status=404
    )
    run, _items = application.enrichment_new_observation(
        parent_run_id,
        ranks=(1,),
        parent_database_sha256=sha256_file(application.repository.path),
    )
    application.enrichment_execute(
        run.enrichment_run_id,
        budget=_budget(retry_limit=2),
        allow_tier2=False,
    )
    assert transport.packaging_request_count == 1
    _final, items = application.enrichment_status(run.enrichment_run_id)
    assert items[0].failure_count == 1
    responses = application.repository.get_detail_responses(run.enrichment_run_id)
    assert responses[-1].error_category == "permanent_http"


def test_one_candidate_detail_failure_does_not_rollback_another_ingredient(
    tmp_path: Path,
) -> None:
    application, transport, parent_run_id = odd005_service(
        tmp_path, packaging_status=404, packaging_failure_rank=1
    )
    run, _items = application.enrichment_new_observation(
        parent_run_id,
        ranks=(1, 2),
        parent_database_sha256=sha256_file(application.repository.path),
    )
    application.enrichment_execute(
        run.enrichment_run_id,
        budget=_budget(max_requests=2),
        allow_tier2=False,
    )
    _final, items = application.enrichment_status(run.enrichment_run_id)
    by_rank = {item.rank: item for item in items}
    assert transport.packaging_request_count == 2
    assert by_rank[1].failure_count == 1
    assert by_rank[1].tier1_complete == 0
    assert by_rank[2].failure_count == 0
    assert by_rank[2].tier1_complete == 1


def test_explicit_rate_delay_is_applied_between_candidate_requests(
    tmp_path: Path,
) -> None:
    application, transport, parent_run_id = odd005_service(tmp_path)
    sleeps: list[float] = []
    application.enrichment.connector.sleep = sleeps.append
    run, _items = application.enrichment_new_observation(
        parent_run_id,
        ranks=(1, 2),
        parent_database_sha256=sha256_file(application.repository.path),
    )
    application.enrichment_execute(
        run.enrichment_run_id,
        budget=_budget(max_requests=2, rate_delay=0.25),
        allow_tier2=False,
    )
    assert transport.packaging_request_count == 2
    assert sleeps == [0.25, 0.25]


def test_artifact_tampering_is_detected(tmp_path: Path) -> None:
    application, _transport, parent_run_id = odd005_service(tmp_path)
    run, _items = application.enrichment_new_observation(
        parent_run_id,
        ranks=(1,),
        parent_database_sha256=sha256_file(application.repository.path),
    )
    application.enrichment_execute(
        run.enrichment_run_id, budget=_budget(), allow_tier2=False
    )
    response = application.repository.get_detail_responses(
        run.enrichment_run_id, successful_only=True
    )[0]
    body_path = (
        tmp_path
        / "data"
        / "evidence"
        / "dailymed"
        / "enrichment"
        / "responses"
        / response.response_id
        / "response.body"
    )
    original = body_path.read_bytes()
    body_path.write_bytes(original + b"tamper")
    checks = application.enrichment_verify(run.enrichment_run_id)
    assert not checks["filesystem_response_hashes"]


def test_new_observation_has_distinct_run_but_same_exact_semantic_result(
    tmp_path: Path,
) -> None:
    application, _transport, parent_run_id = odd005_service(tmp_path)
    parent_hash = sha256_file(application.repository.path)
    first, _items = application.enrichment_new_observation(
        parent_run_id, ranks=(1,), parent_database_sha256=parent_hash
    )
    second, _items = application.enrichment.new_observation(
        parent_run_id,
        ranks=(1,),
        parent_database_sha256=parent_hash,
        observation_token="explicit-second-observation",
    )
    assert first.enrichment_run_id != second.enrichment_run_id


def _budget(
    *,
    max_requests: int = 3,
    max_bytes: int = 1_000_000,
    retry_limit: int = 0,
    max_response_bytes: int = 65_536,
    max_detail_pages: int = 2,
    max_tier2_candidates: int = 0,
    rate_delay: float = 0,
) -> EnrichmentBudget:
    return EnrichmentBudget(
        max_requests=max_requests,
        max_downloaded_bytes=max_bytes,
        timeout_seconds=5,
        retry_limit=retry_limit,
        inter_request_delay_seconds=rate_delay,
        max_response_bytes=max_response_bytes,
        max_detail_pages=max_detail_pages,
        max_tier2_candidates=max_tier2_candidates,
    )

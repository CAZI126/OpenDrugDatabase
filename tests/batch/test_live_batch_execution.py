"""Offline ODD-004 observation, resume, isolation, and report tests."""

from __future__ import annotations

import sqlite3
from dataclasses import replace

import pytest

from odd.errors import BatchArtifactConflict
from odd.models import (
    BatchStatus,
    DiscoveryCompleteness,
    IngestionStatus,
    ParserCompatibilityStatus,
    SelectionStatus,
    VerificationStatus,
)
from odd.provenance.hashing import sha256_file
from tests.odd004_support import live_service

LIST_ID = "us-top10-2023"


def test_new_live_observation_keeps_unsupported_search_fields_manual(tmp_path) -> None:
    application, transport = live_service(tmp_path)
    run, items = application.batch_plan(LIST_ID, new_observation=True)

    assert run.database_schema_version == "4"
    assert run.discovery_complete_count == 10
    assert run.selected_count == 0
    assert run.manual_review_count == 10
    assert transport.discovery_request_count == 10
    assert transport.xml_request_count == 0
    assert all(item.snapshot_id for item in items)
    assert all(
        item.discovery_completeness is DiscoveryCompleteness.COMPLETE for item in items
    )
    assert all(
        item.selection_status is SelectionStatus.MANUAL_REVIEW_REQUIRED for item in items
    )
    assert all(item.manual_review_required for item in items)
    assert all(
        item.evidence_verification_status is VerificationStatus.VERIFIED for item in items
    )


def test_resume_never_performs_additional_candidate_discovery(tmp_path) -> None:
    application, transport = live_service(tmp_path)
    run, original = application.batch_plan(LIST_ID, new_observation=True)
    before = tuple(transport.requests)

    resumed, items = application.batch_plan(run_id=run.batch_run_id)

    assert tuple(transport.requests) == before
    assert resumed.snapshot_manifest_sha256 == run.snapshot_manifest_sha256
    assert [item.snapshot_id for item in items] == [item.snapshot_id for item in original]


def test_completed_resume_preserves_terminal_state_and_database_bytes(tmp_path) -> None:
    application, transport = live_service(tmp_path)
    planned, _items = application.batch_plan(LIST_ID, new_observation=True)
    artifact = application.batch_run(run_id=planned.batch_run_id)
    completed_at = artifact.report.batch_run.completed_at
    requests = tuple(transport.requests)
    database_hash = sha256_file(application.repository.path)

    resumed, _items = application.batch_plan(run_id=planned.batch_run_id)

    assert resumed.status is BatchStatus.COMPLETED_WITH_UNRESOLVED_ITEMS
    assert resumed.completed_at == completed_at
    assert tuple(transport.requests) == requests
    assert sha256_file(application.repository.path) == database_hash


def test_only_explicit_new_observation_creates_new_run(tmp_path) -> None:
    application, transport = live_service(tmp_path)
    first, first_items = application.batch_plan(LIST_ID, new_observation=True)
    application.batch_plan(run_id=first.batch_run_id)
    assert transport.discovery_request_count == 10

    second, second_items = application.batch_plan(LIST_ID, new_observation=True)
    assert first.batch_run_id != second.batch_run_id
    assert transport.discovery_request_count == 20
    assert [item.snapshot_id for item in first_items] == [
        item.snapshot_id for item in second_items
    ]


def test_selected_live_pipeline_is_idempotent_and_fully_verified(tmp_path) -> None:
    application, transport = live_service(
        tmp_path, complete_selection_metadata=True
    )
    planned, items = application.batch_plan(LIST_ID, new_observation=True)
    assert all(item.selection_status is SelectionStatus.SELECTED for item in items)

    first = application.batch_run(run_id=planned.batch_run_id)
    requests_after_first = tuple(transport.requests)
    second = application.batch_run(run_id=planned.batch_run_id)

    assert first.report.batch_run.status is BatchStatus.COMPLETED
    assert first.report.batch_run.verified_count == 10
    assert all(
        item.parser_compatibility_status
        in {
            ParserCompatibilityStatus.FULLY_PARSED,
            ParserCompatibilityStatus.PARSED_WITH_UNMAPPED_SECTIONS,
        }
        for item in first.report.items
    )
    assert all(
        item.verification_status is VerificationStatus.VERIFIED
        for item in first.report.items
    )
    assert tuple(transport.requests) == requests_after_first
    assert second.already_stored
    assert second.canonical_sha256 == first.canonical_sha256
    assert all(
        application.repository.live_batch_artifact_integrity(planned.batch_run_id).values()
    )


def test_one_live_fetch_failure_does_not_rollback_other_ingredients(tmp_path) -> None:
    application, _transport = live_service(
        tmp_path,
        complete_selection_metadata=True,
        fetch_failure_ingredient="albuterol",
    )
    planned, _items = application.batch_plan(LIST_ID, new_observation=True)
    artifact = application.batch_run(run_id=planned.batch_run_id)
    failed = artifact.report.items[6]

    assert artifact.report.batch_run.status is BatchStatus.PARTIAL_FAILURE
    assert failed.ingestion_status is IngestionStatus.RAW_FETCH_FAILED
    assert failed.retry_eligible
    assert artifact.report.batch_run.verified_count == 9
    assert all(
        item.verification_status is VerificationStatus.VERIFIED
        for item in artifact.report.items
        if item.rank != 7
    )


def test_permanent_live_fetch_failure_is_not_retried_on_resume(tmp_path) -> None:
    application, transport = live_service(
        tmp_path,
        complete_selection_metadata=True,
        permanent_fetch_failure_ingredient="albuterol",
    )
    planned, _items = application.batch_plan(LIST_ID, new_observation=True)
    artifact = application.batch_run(run_id=planned.batch_run_id)
    failed = artifact.report.items[6]
    requests_after_run = tuple(transport.requests)

    application.batch_fetch(run_id=planned.batch_run_id)

    assert failed.ingestion_status is IngestionStatus.RAW_FETCH_FAILED
    assert failed.retry_eligible is False
    assert tuple(transport.requests) == requests_after_run


@pytest.mark.parametrize(
    ("failure_kind", "expected"),
    [
        ("parser", ParserCompatibilityStatus.PARSER_FAILED),
        ("unsupported", ParserCompatibilityStatus.UNSUPPORTED_STRUCTURE),
    ],
)
def test_live_parser_compatibility_failure_states_are_distinct(
    tmp_path, failure_kind: str, expected: ParserCompatibilityStatus
) -> None:
    application, _transport = live_service(
        tmp_path,
        complete_selection_metadata=True,
        parser_failure_ingredient="albuterol" if failure_kind == "parser" else None,
        unsupported_ingredient="albuterol" if failure_kind == "unsupported" else None,
    )
    planned, _items = application.batch_plan(LIST_ID, new_observation=True)
    artifact = application.batch_run(run_id=planned.batch_run_id)
    failed = artifact.report.items[6]

    assert failed.parser_compatibility_status is expected
    assert failed.verification_status is VerificationStatus.NOT_VERIFIED
    assert failed.retry_eligible is (failure_kind == "parser")
    assert artifact.report.batch_run.verified_count == 9

    if failure_kind == "unsupported":
        application.live_batch.ingest_document = lambda *_args: pytest.fail(
            "unsupported structure must not be retried"
        )
        application.batch_ingest(run_id=planned.batch_run_id)


def test_live_raw_hash_conflict_never_overwrites_first_exact_source(tmp_path) -> None:
    application, transport = live_service(
        tmp_path, complete_selection_metadata=True
    )
    planned, _items = application.batch_plan(LIST_ID, new_observation=True)
    _run, fetched = application.batch_fetch(run_id=planned.batch_run_id)
    first = fetched[0]
    assert first.selected_set_id is not None
    assert first.selected_source_version is not None
    raw = application.raw_store.resolve(
        first.selected_set_id, first.selected_source_version
    )
    original_hash = sha256_file(raw.label_path)
    transport.xml_overrides[first.selected_set_id] = raw.label_path.read_bytes() + b"\n"
    application.repository.save_live_batch_item(
        replace(first, ingestion_status=IngestionStatus.PENDING)
    )

    _run, retried = application.batch_fetch(run_id=planned.batch_run_id)

    assert retried[0].ingestion_status is IngestionStatus.RAW_HASH_CONFLICT
    assert retried[0].retry_eligible is False
    assert retried[0].quarantine_record_id is not None
    assert sha256_file(raw.label_path) == original_hash


def test_canonical_live_report_ignores_run_id_and_detects_tampering(tmp_path) -> None:
    application, _transport = live_service(tmp_path)
    first_run, _items = application.batch_plan(LIST_ID, new_observation=True)
    first = application.batch_run(run_id=first_run.batch_run_id)
    second_run, _items = application.batch_plan(LIST_ID, new_observation=True)
    second = application.batch_run(run_id=second_run.batch_run_id)

    assert first.canonical_sha256 == second.canonical_sha256
    assert first.canonical_json == second.canonical_json
    with sqlite3.connect(application.repository.path) as connection:
        connection.execute(
            "UPDATE live_batch_artifacts SET canonical_json = ? WHERE batch_run_id = ?",
            (b'{"tampered":true}', first_run.batch_run_id),
        )
        connection.commit()
    integrity = application.repository.live_batch_artifact_integrity(
        first_run.batch_run_id
    )
    assert integrity["hash_matches"] is False
    with pytest.raises(BatchArtifactConflict):
        application.batch_report(first_run.batch_run_id)

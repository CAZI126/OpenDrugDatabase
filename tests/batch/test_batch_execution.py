"""Resumable per-ingredient ODD-003 batch execution tests."""

from __future__ import annotations

from pathlib import Path

from odd.batch.service import _parser_failure_status, _successful_parser_compatibility
from odd.errors import DatabaseFailure, ParserFailure
from odd.models import (
    BatchStatus,
    IngestionStatus,
    ParserCompatibilityStatus,
    SelectionStatus,
    VerificationStatus,
)
from tests.odd003_support import odd003_service

LIST_ID = "us-top10-2023"


def test_fully_parsed_compatibility_requires_no_unmapped_or_empty_sections() -> None:
    assert _successful_parser_compatibility(0, 0) is ParserCompatibilityStatus.FULLY_PARSED
    assert _successful_parser_compatibility(1, 0) is (
        ParserCompatibilityStatus.PARSED_WITH_UNMAPPED_SECTIONS
    )


def test_partial_and_failed_parse_statuses_are_distinct() -> None:
    assert _parser_failure_status(DatabaseFailure("injected")) == (
        ParserCompatibilityStatus.PARTIAL_PARSE,
        IngestionStatus.DATABASE_FAILED,
    )
    assert _parser_failure_status(ParserFailure("injected")) == (
        ParserCompatibilityStatus.PARSER_FAILED,
        IngestionStatus.PARSER_FAILED,
    )


def test_all_ten_succeed_in_mocked_ideal_case(tmp_path: Path) -> None:
    application, _transport = odd003_service(tmp_path, resolve_omeprazole=True)
    artifact = application.batch_run(LIST_ID)
    run = artifact.report.batch_run
    assert run.status is BatchStatus.COMPLETED
    assert (
        run.requested_count,
        run.selected_count,
        run.fetched_count,
        run.ingested_count,
        run.verified_count,
    ) == (10, 10, 10, 10, 10)
    assert all(
        item.verification_status is VerificationStatus.VERIFIED
        for item in artifact.report.items
    )


def test_one_unresolved_item_is_truthfully_terminal(tmp_path: Path) -> None:
    application, _transport = odd003_service(tmp_path)
    artifact = application.batch_run(LIST_ID)
    run = artifact.report.batch_run
    unresolved = artifact.report.items[-1]
    assert run.status is BatchStatus.COMPLETED_WITH_UNRESOLVED_ITEMS
    assert run.verified_count == 9
    assert run.unresolved_count == 1
    assert unresolved.selection_status is SelectionStatus.MULTIPLE_EQUIVALENT_CANDIDATES
    assert unresolved.manual_review_required
    assert unresolved.document_id is None


def test_one_fetch_failure_preserves_successful_items(tmp_path: Path) -> None:
    application, _transport = odd003_service(
        tmp_path,
        resolve_omeprazole=True,
        fetch_failure_ingredient="albuterol",
    )
    artifact = application.batch_run(LIST_ID)
    failed = artifact.report.items[6]
    assert artifact.report.batch_run.status is BatchStatus.PARTIAL_FAILURE
    assert artifact.report.batch_run.verified_count == 9
    assert failed.ingestion_status is IngestionStatus.RAW_FETCH_FAILED
    assert failed.retry_eligible
    assert artifact.report.items[7].verification_status is VerificationStatus.VERIFIED


def test_parser_failure_is_quarantined_and_later_item_survives(tmp_path: Path) -> None:
    application, _transport = odd003_service(
        tmp_path,
        resolve_omeprazole=True,
        parser_failure_ingredient="albuterol",
    )
    artifact = application.batch_run(LIST_ID)
    failed = artifact.report.items[6]
    assert failed.ingestion_status is IngestionStatus.PARSER_FAILED
    assert failed.parser_compatibility_status is ParserCompatibilityStatus.PARSER_FAILED
    assert failed.quarantine_record_id is not None
    assert list((tmp_path / "data" / "quarantine").rglob("failure-*.json"))
    assert artifact.report.items[7].verification_status is VerificationStatus.VERIFIED


def test_unsupported_structure_is_reported_separately(tmp_path: Path) -> None:
    application, _transport = odd003_service(
        tmp_path,
        resolve_omeprazole=True,
        unsupported_ingredient="albuterol",
    )
    artifact = application.batch_run(LIST_ID)
    failed = artifact.report.items[6]
    assert failed.ingestion_status is IngestionStatus.UNSUPPORTED_STRUCTURE
    assert (
        failed.parser_compatibility_status
        is ParserCompatibilityStatus.PARSED_WITH_UNSUPPORTED_STRUCTURES
    )
    assert failed.unsupported_structure_count == 1


def test_successful_parse_reports_unmapped_counts_consistently(tmp_path: Path) -> None:
    application, _transport = odd003_service(tmp_path, resolve_omeprazole=True)
    artifact = application.batch_run(LIST_ID)
    for item in artifact.report.items:
        assert item.parser_compatibility_status in {
            ParserCompatibilityStatus.FULLY_PARSED,
            ParserCompatibilityStatus.PARSED_WITH_UNMAPPED_SECTIONS,
        }
        assert item.source_section_count == item.mapped_section_count + item.unmapped_section_count
        if item.unmapped_section_count:
            assert item.parser_compatibility_status is (
                ParserCompatibilityStatus.PARSED_WITH_UNMAPPED_SECTIONS
            )


def test_resumable_rerun_reuses_success_and_is_idempotent(tmp_path: Path) -> None:
    application, transport = odd003_service(tmp_path, resolve_omeprazole=True)
    first = application.batch_run(LIST_ID)
    request_count = len(transport.requests)
    second = application.batch_run(LIST_ID)
    assert second.already_stored
    assert first.canonical_json == second.canonical_json
    assert first.canonical_sha256 == second.canonical_sha256
    assert len(transport.requests) == request_count
    assert application.repository.table_count("batch_runs") == 1
    assert application.repository.table_count("regulatory_documents") == 10


def test_failed_item_can_be_retried_independently(tmp_path: Path) -> None:
    application, transport = odd003_service(
        tmp_path,
        resolve_omeprazole=True,
        fetch_failure_ingredient="albuterol",
    )
    first = application.batch_run(LIST_ID)
    assert first.report.items[6].ingestion_status is IngestionStatus.RAW_FETCH_FAILED
    transport.fetch_failure_ingredient = None
    second = application.batch_run(LIST_ID)
    assert second.report.batch_run.status is BatchStatus.COMPLETED
    assert second.report.items[6].verification_status is VerificationStatus.VERIFIED
    assert application.repository.table_count("regulatory_documents") == 10


def test_plan_downloads_no_xml_and_orders_items_by_rank(tmp_path: Path) -> None:
    application, transport = odd003_service(tmp_path)
    run, items = application.batch_plan(LIST_ID)
    assert run.status is BatchStatus.RUNNING
    assert [item.rank for item in items] == list(range(1, 11))
    assert len(transport.requests) == 10
    assert all("/spls.json?" in request for request in transport.requests)
    assert application.repository.table_count("source_documents") == 0


def test_batch_report_items_and_diagnostics_are_deterministic(tmp_path: Path) -> None:
    application, _transport = odd003_service(tmp_path)
    first = application.batch_run(LIST_ID)
    second = application.batch_report(first.report.batch_run.batch_run_id)
    assert first.canonical_json == second.canonical_json
    assert [item.rank for item in first.report.items] == list(range(1, 11))
    assert first.report.batch_run.unresolved_count == second.report.batch_run.unresolved_count

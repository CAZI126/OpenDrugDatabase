"""Resumable, item-isolated execution for the ODD-003 validation batch."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Protocol

from odd.connectors.dailymed.batch_selection import classify_and_select_candidates
from odd.connectors.dailymed.client import DailyMedConnector
from odd.constants import (
    BATCH_REPORT_VERSION,
    BATCH_SELECTION_RULE_VERSION,
    CONNECTOR_VERSION,
    MAPPING_VERSION,
    PARSER_VERSION,
    SCHEMA_VERSION,
)
from odd.errors import (
    CandidateLookupFailed,
    DatabaseFailure,
    ErrorCategory,
    ODDError,
    ParserFailure,
    RawHashConflict,
    UnsupportedDocumentStructure,
)
from odd.models import (
    BatchArtifactResult,
    BatchItem,
    BatchReport,
    BatchRun,
    BatchStatus,
    CandidateSelection,
    DailyMedCandidate,
    DiscoveryStatus,
    IngestionOutcome,
    IngestionStatus,
    ParserCompatibilityStatus,
    SelectionDecision,
    SelectionStatus,
    UtilizationEntry,
    UtilizationList,
    VerificationResult,
    VerificationStatus,
)
from odd.provenance.hashing import sha256_bytes
from odd.provenance.identifiers import (
    batch_run_id,
    candidate_discovery_id,
    quarantine_record_id,
)
from odd.provenance.raw_store import QuarantineStore, RawStore
from odd.storage.sqlite import SQLiteRepository
from odd.utilization import ingredient_identity, load_utilization_list, normalize_ingredient_name


class IngestCallable(Protocol):
    def __call__(self, set_id: str, source_version: str | None = None) -> IngestionOutcome: ...


class VerifyCallable(Protocol):
    def __call__(self, document_id: str) -> VerificationResult: ...


class BatchCoordinator:
    """Coordinate one fixed, versioned utilization list without all-or-nothing rollback."""

    def __init__(
        self,
        *,
        repository: SQLiteRepository,
        raw_store: RawStore,
        quarantine_store: QuarantineStore,
        connector: DailyMedConnector,
        ingest: IngestCallable,
        verify: VerifyCallable,
        clock: Callable[[], datetime],
    ) -> None:
        self.repository = repository
        self.raw_store = raw_store
        self.quarantine_store = quarantine_store
        self.connector = connector
        self.ingest_document = ingest
        self.verify_document = verify
        self.clock = clock

    def utilization_lists(self) -> list[dict[str, object]]:
        self._ensure_builtin_list("us-top10-2023")
        return self.repository.list_utilization_lists()

    def utilization_show(self, list_id: str) -> UtilizationList:
        return self._ensure_builtin_list(list_id)

    def plan(self, list_id: str) -> tuple[BatchRun, tuple[BatchItem, ...]]:
        utilization, run = self._ensure_run(list_id)
        current = {item.rank: item for item in self.repository.get_batch_items(run.batch_run_id)}
        for entry in utilization.entries:
            item = current[entry.rank]
            if item.decision_id is not None:
                continue
            identity = ingredient_identity(entry)
            try:
                lookup = self.connector.lookup(identity.normalized_search_string)
                selection = classify_and_select_candidates(
                    lookup,
                    identity,
                    utilization_list_id=utilization.utilization_list_id,
                )
                discovery_status = (
                    DiscoveryStatus.NO_CANDIDATE
                    if not selection.candidates
                    else DiscoveryStatus.DISCOVERED
                )
                self.repository.store_candidate_selection(
                    utilization_list_id=utilization.utilization_list_id,
                    query_text=identity.normalized_search_string,
                    connector_version=CONNECTOR_VERSION,
                    lookup=lookup,
                    selection=selection,
                    status=discovery_status,
                )
                updated = replace(
                    item,
                    discovery_status=discovery_status,
                    selection_status=selection.selection_status,
                    selected_set_id=selection.selected_set_id,
                    selected_source_version=selection.selected_source_version,
                    ingestion_status=(
                        IngestionStatus.PENDING
                        if selection.selection_status is SelectionStatus.SELECTED
                        else IngestionStatus.NOT_SELECTED
                    ),
                    manual_review_required=selection.manual_review_required,
                    discovery_run_id=selection.discovery_run_id,
                    decision_id=selection.decision_id,
                    error_category=_selection_error_category(selection),
                    query_text=identity.normalized_search_string,
                    candidate_count=len(selection.candidates),
                    selection_reason=selection.selection_reason,
                    diagnostic_message=(
                        None
                        if selection.selection_status is SelectionStatus.SELECTED
                        else selection.selection_reason
                    ),
                    retry_eligible=False,
                )
            except ODDError as exc:
                discovery_id = candidate_discovery_id(
                    utilization.utilization_list_id,
                    identity.ingredient_id,
                    CONNECTOR_VERSION,
                    sha256_bytes(b"lookup-failed"),
                )
                self.repository.record_candidate_lookup_failure(
                    discovery_run_id=discovery_id,
                    utilization_list_id=utilization.utilization_list_id,
                    ingredient_id_value=identity.ingredient_id,
                    query_text=identity.normalized_search_string,
                    connector_version=CONNECTOR_VERSION,
                    recorded_at=self._now(),
                    error_category=ErrorCategory.CANDIDATE_LOOKUP_FAILED.value,
                    diagnostic_message=f"{exc.category.value}: {exc.message}",
                )
                updated = replace(
                    item,
                    discovery_status=DiscoveryStatus.LOOKUP_FAILED,
                    selection_status=(
                        SelectionStatus.METADATA_INVALID
                        if exc.category is ErrorCategory.MALFORMED_METADATA
                        else SelectionStatus.FETCH_FAILED
                    ),
                    ingestion_status=IngestionStatus.NOT_SELECTED,
                    error_category=ErrorCategory.CANDIDATE_LOOKUP_FAILED.value,
                    diagnostic_message=f"{exc.category.value}: {exc.message}",
                    manual_review_required=True,
                    discovery_run_id=discovery_id,
                    retry_eligible=True,
                    query_text=identity.normalized_search_string,
                    candidate_count=0,
                    selection_reason=None,
                )
            self.repository.save_batch_item(updated)
            current[entry.rank] = updated
        self._refresh_run(run.batch_run_id, terminal=False)
        return self._required_run(run.batch_run_id), self.repository.get_batch_items(
            run.batch_run_id
        )

    def fetch(
        self,
        list_id: str,
        *,
        ranks: set[int] | None = None,
    ) -> tuple[BatchRun, tuple[BatchItem, ...]]:
        run, _items = self.plan(list_id)
        for item in self.repository.get_batch_items(run.batch_run_id):
            if ranks is not None and item.rank not in ranks:
                continue
            if item.selection_status is not SelectionStatus.SELECTED:
                continue
            if item.ingestion_status not in {
                IngestionStatus.PENDING,
                IngestionStatus.RAW_FETCH_FAILED,
                IngestionStatus.RAW_HASH_CONFLICT,
            }:
                continue
            if item.decision_id is None or item.discovery_run_id is None:
                self.repository.save_batch_item(
                    replace(
                        item,
                        ingestion_status=IngestionStatus.RAW_FETCH_FAILED,
                        error_category=ErrorCategory.CANDIDATE_METADATA_INVALID.value,
                        diagnostic_message="selected item lacks persisted candidate evidence",
                        retry_eligible=False,
                    )
                )
                continue
            selection = self.repository.get_candidate_selection(item.decision_id)
            lookup = self.repository.get_candidate_lookup(item.discovery_run_id)
            if selection is None or lookup is None:
                self.repository.save_batch_item(
                    replace(
                        item,
                        ingestion_status=IngestionStatus.RAW_FETCH_FAILED,
                        error_category=ErrorCategory.CANDIDATE_METADATA_INVALID.value,
                        diagnostic_message="candidate evidence could not be reconstructed",
                        retry_eligible=False,
                    )
                )
                continue
            selected = _selected_daily_med_candidate(selection)
            try:
                download = self.connector.download(selected)
                raw = self.raw_store.store(
                    download,
                    lookup,
                    _legacy_selection_decision(selection, selected),
                )
                updated = replace(
                    item,
                    raw_sha256=raw.identity.raw_sha256,
                    ingestion_status=(
                        IngestionStatus.ALREADY_FETCHED
                        if raw.already_stored
                        else IngestionStatus.FETCHED
                    ),
                    error_category=None,
                    diagnostic_message=None,
                    retry_eligible=False,
                )
            except RawHashConflict as exc:
                qid = quarantine_record_id(
                    item.batch_run_id,
                    item.ingredient_id,
                    "raw_storage",
                    sha256_bytes(download.body),
                )
                self.quarantine_store.record(
                    set_id=selected.set_id,
                    source_version=selected.source_version,
                    raw_sha256=sha256_bytes(download.body),
                    stage="raw_storage",
                    error=exc,
                    recorded_at=self._now(),
                    raw_bytes=download.body,
                    batch_run_id=item.batch_run_id,
                    ingredient_id=item.ingredient_id,
                    ingredient_name=item.ingredient_name,
                    rank=item.rank,
                    candidate_metadata=selected.metadata,
                    quarantine_record_id=qid,
                )
                updated = replace(
                    item,
                    ingestion_status=IngestionStatus.RAW_HASH_CONFLICT,
                    quarantine_record_id=qid,
                    error_category=exc.category.value,
                    diagnostic_message=exc.message,
                    retry_eligible=False,
                )
            except ODDError as exc:
                updated = replace(
                    item,
                    ingestion_status=IngestionStatus.RAW_FETCH_FAILED,
                    error_category=ErrorCategory.RAW_FETCH_FAILED.value,
                    diagnostic_message=f"{exc.category.value}: {exc.message}",
                    retry_eligible=True,
                )
            self.repository.save_batch_item(updated)
        self._refresh_run(run.batch_run_id, terminal=False)
        return self._required_run(run.batch_run_id), self.repository.get_batch_items(
            run.batch_run_id
        )

    def ingest(
        self,
        list_id: str,
        *,
        ranks: set[int] | None = None,
    ) -> tuple[BatchRun, tuple[BatchItem, ...]]:
        run, _items = self.fetch(list_id, ranks=ranks)
        for item in self.repository.get_batch_items(run.batch_run_id):
            if ranks is not None and item.rank not in ranks:
                continue
            if item.ingestion_status not in {
                IngestionStatus.FETCHED,
                IngestionStatus.ALREADY_FETCHED,
                IngestionStatus.PARSER_FAILED,
                IngestionStatus.UNSUPPORTED_STRUCTURE,
                IngestionStatus.DATABASE_FAILED,
            }:
                continue
            if item.selected_set_id is None or item.selected_source_version is None:
                continue
            try:
                outcome = self.ingest_document(
                    item.selected_set_id,
                    item.selected_source_version,
                )
                sections = self.repository.get_sections(outcome.document_id, None)
                empty_count = sum(
                    1
                    for section in sections
                    if section.get("content_status") == "present_empty"
                )
                compatibility = _successful_parser_compatibility(
                    outcome.unmapped_section_count,
                    empty_count,
                )
                warnings = []
                if outcome.unmapped_section_count:
                    warnings.append(
                        f"{outcome.unmapped_section_count} source section(s) have no "
                        "semantic mapping"
                    )
                if empty_count:
                    warnings.append(f"{empty_count} source section(s) are present but empty")
                updated = replace(
                    item,
                    document_id=outcome.document_id,
                    raw_sha256=outcome.raw_sha256,
                    ingestion_status=(
                        IngestionStatus.ALREADY_INGESTED
                        if outcome.status == "already_ingested"
                        else IngestionStatus.INGESTED
                    ),
                    parser_compatibility_status=compatibility,
                    source_section_count=outcome.source_section_count,
                    mapped_section_count=outcome.mapped_section_count,
                    unmapped_section_count=outcome.unmapped_section_count,
                    empty_section_count=empty_count,
                    parser_warnings=tuple(warnings),
                    error_category=None,
                    diagnostic_message=None,
                    retry_eligible=False,
                )
                self.repository.save_batch_item(updated)
                self.repository.save_parser_compatibility(updated)
                continue
            except ODDError as exc:
                qid = quarantine_record_id(
                    item.batch_run_id,
                    item.ingredient_id,
                    "ingestion",
                    item.raw_sha256,
                )
                compatibility, ingestion_status = _parser_failure_status(exc)
                raw = self.raw_store.resolve(
                    item.selected_set_id,
                    item.selected_source_version,
                )
                self.quarantine_store.record(
                    set_id=item.selected_set_id,
                    source_version=item.selected_source_version,
                    raw_sha256=item.raw_sha256 or raw.identity.raw_sha256,
                    stage="batch_ingestion",
                    error=exc,
                    recorded_at=self._now(),
                    raw_path=raw.label_path,
                    batch_run_id=item.batch_run_id,
                    ingredient_id=item.ingredient_id,
                    ingredient_name=item.ingredient_name,
                    rank=item.rank,
                    quarantine_record_id=qid,
                )
                updated = replace(
                    item,
                    ingestion_status=ingestion_status,
                    quarantine_record_id=qid,
                    error_category=exc.category.value,
                    diagnostic_message=exc.message,
                    parser_compatibility_status=compatibility,
                    unsupported_structure_count=(
                        1 if isinstance(exc, UnsupportedDocumentStructure) else 0
                    ),
                    parser_warnings=(exc.message,),
                    retry_eligible=not isinstance(exc, UnsupportedDocumentStructure),
                )
                self.repository.save_batch_item(updated)
                self.repository.save_parser_compatibility(
                    updated,
                    quarantine_reason=exc.message,
                )
        self._refresh_run(run.batch_run_id, terminal=False)
        return self._required_run(run.batch_run_id), self.repository.get_batch_items(
            run.batch_run_id
        )

    def verify(
        self,
        list_id: str,
        *,
        ranks: set[int] | None = None,
        finalize: bool = True,
    ) -> tuple[BatchRun, tuple[BatchItem, ...]]:
        run, _items = self.ingest(list_id, ranks=ranks)
        for item in self.repository.get_batch_items(run.batch_run_id):
            if ranks is not None and item.rank not in ranks:
                continue
            if item.document_id is None:
                continue
            if item.ingestion_status not in {
                IngestionStatus.INGESTED,
                IngestionStatus.ALREADY_INGESTED,
            }:
                continue
            try:
                result = self.verify_document(item.document_id)
                updated = replace(
                    item,
                    verification_status=(
                        VerificationStatus.VERIFIED if result.ok else VerificationStatus.FAILED
                    ),
                    error_category=(
                        None if result.ok else ErrorCategory.VERIFICATION_FAILED.value
                    ),
                    diagnostic_message=(
                        None
                        if result.ok
                        else "; ".join(
                            check.message for check in result.checks if not check.ok
                        )
                    ),
                    retry_eligible=not result.ok,
                )
            except ODDError as exc:
                updated = replace(
                    item,
                    verification_status=VerificationStatus.FAILED,
                    error_category=ErrorCategory.VERIFICATION_FAILED.value,
                    diagnostic_message=f"{exc.category.value}: {exc.message}",
                    retry_eligible=True,
                )
            self.repository.save_batch_item(updated)
        final_run = self._refresh_run(run.batch_run_id, terminal=finalize)
        return final_run, self.repository.get_batch_items(run.batch_run_id)

    def run(self, list_id: str) -> BatchArtifactResult:
        run, _items = self.verify(list_id, finalize=True)
        return self.report(run.batch_run_id)

    def status(self, run_id: str) -> tuple[BatchRun, tuple[BatchItem, ...]]:
        return self._required_run(run_id), self.repository.get_batch_items(run_id)

    def report(self, run_id: str) -> BatchArtifactResult:
        run = self._required_run(run_id)
        utilization = self.repository.get_utilization_list(run.utilization_list_id)
        if utilization is None:
            raise DatabaseFailure("batch utilization list is missing")
        report = BatchReport(
            report_version=BATCH_REPORT_VERSION,
            batch_run=run,
            utilization_list=utilization,
            items=self.repository.get_batch_items(run_id),
            generated_at=self._now(),
        )
        return self.repository.store_batch_artifact(report)

    def candidates(self, ingredient: str) -> list[dict[str, object]]:
        return self.repository.candidates_for_ingredient(normalize_ingredient_name(ingredient))

    def _ensure_builtin_list(self, list_id: str) -> UtilizationList:
        existing = self.repository.get_utilization_list(list_id)
        if existing is not None:
            return existing
        value = load_utilization_list(list_id)
        self.repository.store_utilization_list(value)
        return value

    def _ensure_run(self, list_id: str) -> tuple[UtilizationList, BatchRun]:
        utilization = self._ensure_builtin_list(list_id)
        existing = self.repository.find_batch_run(
            utilization_list_id=list_id,
            selection_rule_version=BATCH_SELECTION_RULE_VERSION,
            connector_version=CONNECTOR_VERSION,
            parser_version=PARSER_VERSION,
            schema_version=SCHEMA_VERSION,
            mapping_version=MAPPING_VERSION,
        )
        if existing is not None:
            return utilization, existing
        identifier = batch_run_id(
            list_id,
            BATCH_SELECTION_RULE_VERSION,
            CONNECTOR_VERSION,
            PARSER_VERSION,
            SCHEMA_VERSION,
            MAPPING_VERSION,
        )
        run = BatchRun(
            batch_run_id=identifier,
            utilization_list_id=list_id,
            selection_rule_version=BATCH_SELECTION_RULE_VERSION,
            connector_version=CONNECTOR_VERSION,
            parser_version=PARSER_VERSION,
            schema_version=SCHEMA_VERSION,
            mapping_version=MAPPING_VERSION,
            started_at=self._now(),
            completed_at=None,
            status=BatchStatus.RUNNING,
            requested_count=len(utilization.entries),
            selected_count=0,
            fetched_count=0,
            ingested_count=0,
            verified_count=0,
            quarantined_count=0,
            unresolved_count=0,
            failed_count=0,
            canonical_report_sha256=None,
        )
        items = tuple(
            _initial_item(run.batch_run_id, entry) for entry in utilization.entries
        )
        self.repository.create_batch_run(run, items)
        return utilization, self._required_run(identifier)

    def _refresh_run(self, run_id: str, *, terminal: bool) -> BatchRun:
        current = self._required_run(run_id)
        items = self.repository.get_batch_items(run_id)
        selected = sum(item.selection_status is SelectionStatus.SELECTED for item in items)
        fetched = sum(
            item.ingestion_status
            in {
                IngestionStatus.FETCHED,
                IngestionStatus.ALREADY_FETCHED,
                IngestionStatus.INGESTED,
                IngestionStatus.ALREADY_INGESTED,
            }
            for item in items
        )
        ingested = sum(
            item.ingestion_status
            in {IngestionStatus.INGESTED, IngestionStatus.ALREADY_INGESTED}
            for item in items
        )
        verified = sum(item.verification_status is VerificationStatus.VERIFIED for item in items)
        quarantined = sum(item.quarantine_record_id is not None for item in items)
        unresolved = sum(_is_unresolved(item) for item in items)
        failed = sum(_is_failed(item) for item in items)
        status = BatchStatus.RUNNING
        completed_at = None
        if terminal:
            completed_at = self._now()
            if verified == len(items):
                status = BatchStatus.COMPLETED
            elif failed == len(items):
                status = BatchStatus.FAILED
            elif failed:
                status = BatchStatus.PARTIAL_FAILURE
            else:
                status = BatchStatus.COMPLETED_WITH_UNRESOLVED_ITEMS
        updated = replace(
            current,
            completed_at=completed_at,
            status=status,
            selected_count=selected,
            fetched_count=fetched,
            ingested_count=ingested,
            verified_count=verified,
            quarantined_count=quarantined,
            unresolved_count=unresolved,
            failed_count=failed,
        )
        self.repository.update_batch_run(updated)
        return updated

    def _required_run(self, run_id: str) -> BatchRun:
        run = self.repository.get_batch_run(run_id)
        if run is None:
            raise DatabaseFailure(f"batch run was not found: {run_id}")
        return run

    def _now(self) -> datetime:
        value = self.clock()
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC)


def _initial_item(run_id: str, entry: UtilizationEntry) -> BatchItem:
    identity = ingredient_identity(entry)
    return BatchItem(
        batch_run_id=run_id,
        rank=entry.rank,
        ingredient_id=identity.ingredient_id,
        ingredient_name=entry.ingredient_name,
        discovery_status=DiscoveryStatus.PENDING,
        selection_status=SelectionStatus.PENDING,
        selected_set_id=None,
        selected_source_version=None,
        document_id=None,
        raw_sha256=None,
        ingestion_status=IngestionStatus.NOT_SELECTED,
        verification_status=VerificationStatus.NOT_VERIFIED,
        quarantine_record_id=None,
        error_category=None,
        diagnostic_message=None,
        manual_review_required=False,
        parser_compatibility_status=ParserCompatibilityStatus.NOT_INGESTED,
        source_section_count=None,
        mapped_section_count=None,
        unmapped_section_count=None,
        unsupported_structure_count=0,
        empty_section_count=0,
        parser_warnings=(),
        query_text=identity.normalized_search_string,
    )


def _selection_error_category(selection: CandidateSelection) -> str | None:
    return {
        SelectionStatus.NO_CANDIDATE: ErrorCategory.NO_CANDIDATE.value,
        SelectionStatus.NO_ACCEPTABLE_CANDIDATE: ErrorCategory.NO_ACCEPTABLE_CANDIDATE.value,
        SelectionStatus.MULTIPLE_EQUIVALENT_CANDIDATES: ErrorCategory.AMBIGUOUS_SELECTION.value,
        SelectionStatus.AMBIGUOUS_REQUIRES_REVIEW: ErrorCategory.AMBIGUOUS_SELECTION.value,
        SelectionStatus.MANUAL_REVIEW_REQUIRED: ErrorCategory.AMBIGUOUS_SELECTION.value,
        SelectionStatus.METADATA_INVALID: ErrorCategory.CANDIDATE_METADATA_INVALID.value,
        SelectionStatus.FETCH_FAILED: ErrorCategory.CANDIDATE_LOOKUP_FAILED.value,
    }.get(selection.selection_status)


def _selected_daily_med_candidate(selection: CandidateSelection) -> DailyMedCandidate:
    selected = next(
        (
            item
            for item in selection.candidates
            if item.candidate_id == selection.selected_candidate_id
        ),
        None,
    )
    if selected is None or selected.set_id is None or selected.source_version is None:
        raise CandidateLookupFailed("persisted decision has no selected candidate")
    return DailyMedCandidate(
        set_id=selected.set_id,
        source_version=selected.source_version,
        title=selected.title or selected.generic_name or selected.set_id,
        published_date=selected.published_date or "",
        metadata=selected.raw_metadata,
    )


def _legacy_selection_decision(
    selection: CandidateSelection,
    selected: DailyMedCandidate,
) -> SelectionDecision:
    ordered = tuple(
        DailyMedCandidate(
            set_id=item.set_id or "missing-set-id",
            source_version=item.source_version or "missing-version",
            title=item.title or "missing-title",
            published_date=item.published_date or "",
            metadata=item.raw_metadata,
        )
        for item in selection.candidates
    )
    return SelectionDecision(
        selected=selected,
        ordered_candidates=ordered,
        rule_version=selection.selection_rule_version,
        rule_description="; ".join(selection.applied_rules),
        reason=selection.selection_reason,
        ambiguity_exposed=selection.manual_review_required,
    )


def _parser_failure_status(
    error: ODDError,
) -> tuple[ParserCompatibilityStatus, IngestionStatus]:
    if isinstance(error, UnsupportedDocumentStructure):
        return (
            ParserCompatibilityStatus.PARSED_WITH_UNSUPPORTED_STRUCTURES,
            IngestionStatus.UNSUPPORTED_STRUCTURE,
        )
    if isinstance(error, DatabaseFailure):
        return ParserCompatibilityStatus.PARTIAL_PARSE, IngestionStatus.DATABASE_FAILED
    if isinstance(error, ParserFailure):
        return ParserCompatibilityStatus.PARSER_FAILED, IngestionStatus.PARSER_FAILED
    return ParserCompatibilityStatus.PARSER_FAILED, IngestionStatus.PARSER_FAILED


def _successful_parser_compatibility(
    unmapped_section_count: int,
    empty_section_count: int,
) -> ParserCompatibilityStatus:
    if unmapped_section_count == 0 and empty_section_count == 0:
        return ParserCompatibilityStatus.FULLY_PARSED
    return ParserCompatibilityStatus.PARSED_WITH_UNMAPPED_SECTIONS


def _is_unresolved(item: BatchItem) -> bool:
    return item.selection_status in {
        SelectionStatus.NO_CANDIDATE,
        SelectionStatus.NO_ACCEPTABLE_CANDIDATE,
        SelectionStatus.MULTIPLE_EQUIVALENT_CANDIDATES,
        SelectionStatus.AMBIGUOUS_REQUIRES_REVIEW,
        SelectionStatus.MANUAL_REVIEW_REQUIRED,
    }


def _is_failed(item: BatchItem) -> bool:
    return (
        item.discovery_status is DiscoveryStatus.LOOKUP_FAILED
        or item.ingestion_status
        in {
            IngestionStatus.RAW_FETCH_FAILED,
            IngestionStatus.RAW_HASH_CONFLICT,
            IngestionStatus.PARSER_FAILED,
            IngestionStatus.UNSUPPORTED_STRUCTURE,
            IngestionStatus.DATABASE_FAILED,
        }
        or item.verification_status is VerificationStatus.FAILED
    )

"""ODD-004 immutable live observations over the ODD-003 batch primitives."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from odd.batch.service import (
    IngestCallable,
    VerifyCallable,
    _legacy_selection_decision,
    _parser_failure_status,
    _selected_daily_med_candidate,
    _successful_parser_compatibility,
)
from odd.connectors.dailymed.batch_selection import classify_and_select_candidates
from odd.connectors.dailymed.client import DailyMedConnector
from odd.constants import (
    BATCH_REPORT_VERSION,
    BATCH_SELECTION_RULE_VERSION,
    CONNECTOR_VERSION,
    LIVE_OBSERVATION_MODE,
    MAPPING_VERSION,
    PARSER_VERSION,
    SCHEMA_VERSION,
)
from odd.errors import DatabaseFailure, ErrorCategory, NetworkFailure, ODDError, RawHashConflict
from odd.models import (
    BatchArtifactResult,
    BatchItem,
    BatchReport,
    BatchRun,
    BatchStatus,
    DiscoveryCompleteness,
    DiscoveryStatus,
    IngestionStatus,
    ParserCompatibilityStatus,
    SelectionStatus,
    UtilizationEntry,
    UtilizationList,
    VerificationStatus,
)
from odd.provenance.canonical import canonical_json_bytes
from odd.provenance.discovery_store import DiscoveryEvidenceStore
from odd.provenance.hashing import sha256_bytes
from odd.provenance.identifiers import (
    live_batch_run_id,
    quarantine_record_id,
)
from odd.provenance.raw_store import QuarantineStore, RawStore
from odd.storage.sqlite import DATABASE_SCHEMA_VERSION, SQLiteRepository
from odd.utilization import ingredient_identity, load_utilization_list


class LiveBatchCoordinator:
    """Create explicit observations; resume never performs candidate discovery."""

    def __init__(
        self,
        *,
        repository: SQLiteRepository,
        raw_store: RawStore,
        discovery_store: DiscoveryEvidenceStore,
        quarantine_store: QuarantineStore,
        connector: DailyMedConnector,
        ingest: IngestCallable,
        verify: VerifyCallable,
        clock: Callable[[], datetime],
    ) -> None:
        self.repository = repository
        self.raw_store = raw_store
        self.discovery_store = discovery_store
        self.quarantine_store = quarantine_store
        self.connector = connector
        self.ingest_document = ingest
        self.verify_document = verify
        self.clock = clock

    def new_observation(self, list_id: str) -> tuple[BatchRun, tuple[BatchItem, ...]]:
        utilization = self._ensure_list(list_id)
        observation_token = uuid4().hex
        identifier = live_batch_run_id(observation_token)
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
            database_schema_version=DATABASE_SCHEMA_VERSION,
            observation_mode=LIVE_OBSERVATION_MODE,
        )
        items = tuple(_initial_live_item(identifier, entry) for entry in utilization.entries)
        if not self.repository.create_live_batch_run(
            run, items, observation_token=observation_token
        ):
            raise DatabaseFailure("new live observation identity already exists")
        self._discover(identifier)
        return self._required_run(identifier), self.repository.get_live_batch_items(identifier)

    def resume_plan(self, run_id: str) -> tuple[BatchRun, tuple[BatchItem, ...]]:
        self._required_run(run_id)
        for item in self.repository.get_live_batch_items(run_id):
            if item.discovery_status is not DiscoveryStatus.PENDING:
                continue
            self.repository.save_live_batch_item(
                replace(
                    item,
                    discovery_status=DiscoveryStatus.DISCOVERY_INCOMPLETE,
                    selection_status=SelectionStatus.MANUAL_REVIEW_REQUIRED,
                    manual_review_required=True,
                    discovery_completeness=DiscoveryCompleteness.INCOMPLETE,
                    error_category=ErrorCategory.CANDIDATE_LOOKUP_FAILED.value,
                    diagnostic_message=(
                        "Resume did not issue a new DailyMed request because no immutable "
                        "snapshot was completed for this item; start --new-observation."
                    ),
                    selection_reason="No immutable candidate snapshot is available.",
                    retry_eligible=False,
                )
            )
        run = self._refresh(run_id, terminal=False)
        return run, self.repository.get_live_batch_items(run_id)

    def fetch(self, run_id: str) -> tuple[BatchRun, tuple[BatchItem, ...]]:
        self.resume_plan(run_id)
        for item in self.repository.get_live_batch_items(run_id):
            if item.selection_status is not SelectionStatus.SELECTED:
                continue
            if item.ingestion_status not in {
                IngestionStatus.PENDING,
                IngestionStatus.RAW_FETCH_FAILED,
            }:
                continue
            if (
                item.ingestion_status is IngestionStatus.RAW_FETCH_FAILED
                and not item.retry_eligible
            ):
                continue
            if item.decision_id is None or item.discovery_run_id is None:
                self.repository.save_live_batch_item(
                    replace(
                        item,
                        ingestion_status=IngestionStatus.RAW_FETCH_FAILED,
                        error_category=ErrorCategory.CANDIDATE_METADATA_INVALID.value,
                        diagnostic_message="selected item lacks persisted discovery evidence",
                        retry_eligible=False,
                    )
                )
                continue
            selection = self.repository.get_candidate_selection(item.decision_id)
            lookup = self.repository.get_candidate_lookup(item.discovery_run_id)
            if selection is None or lookup is None:
                self.repository.save_live_batch_item(
                    replace(
                        item,
                        ingestion_status=IngestionStatus.RAW_FETCH_FAILED,
                        error_category=ErrorCategory.CANDIDATE_METADATA_INVALID.value,
                        diagnostic_message="candidate snapshot could not be reconstructed",
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
                    retry_eligible=_fetch_failure_is_retry_eligible(exc),
                )
            self.repository.save_live_batch_item(updated)
        return self._refresh(run_id, terminal=False), self.repository.get_live_batch_items(run_id)

    def ingest(self, run_id: str) -> tuple[BatchRun, tuple[BatchItem, ...]]:
        self.fetch(run_id)
        for item in self.repository.get_live_batch_items(run_id):
            if item.ingestion_status not in {
                IngestionStatus.FETCHED,
                IngestionStatus.ALREADY_FETCHED,
                IngestionStatus.PARSER_FAILED,
                IngestionStatus.UNSUPPORTED_STRUCTURE,
                IngestionStatus.DATABASE_FAILED,
            }:
                continue
            if item.ingestion_status in {
                IngestionStatus.PARSER_FAILED,
                IngestionStatus.UNSUPPORTED_STRUCTURE,
                IngestionStatus.DATABASE_FAILED,
            } and not item.retry_eligible:
                continue
            if item.selected_set_id is None or item.selected_source_version is None:
                continue
            try:
                outcome = self.ingest_document(
                    item.selected_set_id, item.selected_source_version
                )
                sections = self.repository.get_sections(outcome.document_id, None)
                empty_count = sum(
                    section.get("content_status") == "present_empty" for section in sections
                )
                warnings: list[str] = []
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
                    parser_compatibility_status=_successful_parser_compatibility(
                        outcome.unmapped_section_count, empty_count
                    ),
                    source_section_count=outcome.source_section_count,
                    mapped_section_count=outcome.mapped_section_count,
                    unmapped_section_count=outcome.unmapped_section_count,
                    empty_section_count=empty_count,
                    parser_warnings=tuple(warnings),
                    error_category=None,
                    diagnostic_message=None,
                    retry_eligible=False,
                )
            except ODDError as exc:
                qid = quarantine_record_id(
                    item.batch_run_id,
                    item.ingredient_id,
                    "ingestion",
                    item.raw_sha256,
                )
                compatibility, ingestion_status = _parser_failure_status(exc)
                retry_eligible = (
                    compatibility
                    is not ParserCompatibilityStatus.PARSED_WITH_UNSUPPORTED_STRUCTURES
                )
                if (
                    compatibility
                    is ParserCompatibilityStatus.PARSED_WITH_UNSUPPORTED_STRUCTURES
                ):
                    compatibility = ParserCompatibilityStatus.UNSUPPORTED_STRUCTURE
                raw = self.raw_store.resolve(
                    item.selected_set_id, item.selected_source_version
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
                        1
                        if compatibility is ParserCompatibilityStatus.UNSUPPORTED_STRUCTURE
                        else 0
                    ),
                    parser_warnings=(exc.message,),
                    retry_eligible=retry_eligible,
                )
            self.repository.save_live_batch_item(updated)
        return self._refresh(run_id, terminal=False), self.repository.get_live_batch_items(run_id)

    def verify(
        self,
        run_id: str,
        *,
        finalize: bool = True,
    ) -> tuple[BatchRun, tuple[BatchItem, ...]]:
        self.ingest(run_id)
        for item in self.repository.get_live_batch_items(run_id):
            updated = item
            if item.snapshot_id is not None:
                filesystem = self.discovery_store.verify(item.snapshot_id)
                database = self.repository.discovery_snapshot_integrity(item.snapshot_id)
                evidence_ok = all(filesystem.values()) and all(database.values())
                updated = replace(
                    updated,
                    evidence_verification_status=(
                        VerificationStatus.VERIFIED
                        if evidence_ok
                        else VerificationStatus.FAILED
                    ),
                    error_category=(
                        updated.error_category
                        if evidence_ok
                        else ErrorCategory.VERIFICATION_FAILED.value
                    ),
                    diagnostic_message=(
                        updated.diagnostic_message
                        if evidence_ok
                        else "candidate snapshot evidence integrity verification failed"
                    ),
                    retry_eligible=updated.retry_eligible if evidence_ok else False,
                )
            if updated.document_id is not None and updated.ingestion_status in {
                IngestionStatus.INGESTED,
                IngestionStatus.ALREADY_INGESTED,
            }:
                try:
                    result = self.verify_document(updated.document_id)
                    updated = replace(
                        updated,
                        verification_status=(
                            VerificationStatus.VERIFIED
                            if result.ok
                            else VerificationStatus.FAILED
                        ),
                        error_category=(
                            updated.error_category
                            if result.ok
                            else ErrorCategory.VERIFICATION_FAILED.value
                        ),
                        diagnostic_message=(
                            updated.diagnostic_message
                            if result.ok
                            else "; ".join(
                                check.message for check in result.checks if not check.ok
                            )
                        ),
                        retry_eligible=updated.retry_eligible or not result.ok,
                    )
                except ODDError as exc:
                    updated = replace(
                        updated,
                        verification_status=VerificationStatus.FAILED,
                        error_category=ErrorCategory.VERIFICATION_FAILED.value,
                        diagnostic_message=f"{exc.category.value}: {exc.message}",
                        retry_eligible=True,
                    )
            self.repository.save_live_batch_item(updated)
        return (
            self._refresh(run_id, terminal=finalize),
            self.repository.get_live_batch_items(run_id),
        )

    def run(self, run_id: str) -> BatchArtifactResult:
        self.verify(run_id, finalize=True)
        return self.report(run_id)

    def status(self, run_id: str) -> tuple[BatchRun, tuple[BatchItem, ...]]:
        return self._required_run(run_id), self.repository.get_live_batch_items(run_id)

    def report(self, run_id: str) -> BatchArtifactResult:
        run = self._required_run(run_id)
        utilization = self.repository.get_utilization_list(run.utilization_list_id)
        if utilization is None:
            raise DatabaseFailure("live batch utilization list is missing")
        report = BatchReport(
            report_version=BATCH_REPORT_VERSION,
            batch_run=run,
            utilization_list=utilization,
            items=self.repository.get_live_batch_items(run_id),
            generated_at=self._now(),
        )
        artifact = self.repository.store_live_batch_artifact(report)
        integrity = self.repository.live_batch_artifact_integrity(run_id)
        if not all(integrity.values()):
            raise DatabaseFailure(
                "live batch artifact failed immediate integrity verification"
            )
        return artifact

    def _discover(self, run_id: str) -> None:
        run = self._required_run(run_id)
        utilization = self.repository.get_utilization_list(run.utilization_list_id)
        if utilization is None:
            raise DatabaseFailure("live utilization list is missing")
        entries = {entry.rank: entry for entry in utilization.entries}
        for item in self.repository.get_live_batch_items(run_id):
            if item.discovery_status is not DiscoveryStatus.PENDING:
                continue
            identity = ingredient_identity(entries[item.rank])
            try:
                lookup = self.connector.discover(identity.normalized_search_string)
                stored = self.discovery_store.store(lookup)
                selection = classify_and_select_candidates(
                    lookup,
                    identity,
                    utilization_list_id=utilization.utilization_list_id,
                )
                discovery_status = _discovery_status(lookup.completeness, len(lookup.candidates))
                self.repository.store_candidate_selection(
                    utilization_list_id=utilization.utilization_list_id,
                    query_text=identity.normalized_search_string,
                    connector_version=CONNECTOR_VERSION,
                    lookup=lookup,
                    selection=selection,
                    status=discovery_status,
                    evidence_manifest_sha256=stored.canonical_manifest_sha256,
                )
                evidence_ok = all(self.discovery_store.verify(stored.snapshot_id).values())
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
                    error_category=_selection_error(selection.selection_status),
                    diagnostic_message=(
                        None
                        if selection.selection_status is SelectionStatus.SELECTED
                        else selection.selection_reason
                    ),
                    retry_eligible=False,
                    candidate_count=len(selection.candidates),
                    selection_reason=selection.selection_reason,
                    snapshot_id=lookup.snapshot_id,
                    metadata_total_candidate_count=lookup.metadata_total_elements,
                    retrieved_candidate_count=len(lookup.candidates),
                    eligible_candidate_count=sum(
                        candidate.accepted_for_selection
                        for candidate in selection.candidates
                    ),
                    discovery_completeness=lookup.completeness,
                    evidence_verification_status=(
                        VerificationStatus.VERIFIED
                        if evidence_ok
                        else VerificationStatus.FAILED
                    ),
                )
            except ODDError as exc:
                updated = replace(
                    item,
                    discovery_status=DiscoveryStatus.LOOKUP_FAILED,
                    selection_status=SelectionStatus.MANUAL_REVIEW_REQUIRED,
                    ingestion_status=IngestionStatus.NOT_SELECTED,
                    error_category=exc.category.value,
                    diagnostic_message=f"{exc.category.value}: {exc.message}",
                    manual_review_required=True,
                    retry_eligible=False,
                    discovery_completeness=DiscoveryCompleteness.INCOMPLETE,
                    selection_reason=(
                        "Live discovery did not produce an immutable snapshot; start a new "
                        "observation rather than mixing a retry into this run."
                    ),
                )
            self.repository.save_live_batch_item(updated)
        self._refresh(run_id, terminal=False)

    def _refresh(self, run_id: str, *, terminal: bool) -> BatchRun:
        current = self._required_run(run_id)
        items = self.repository.get_live_batch_items(run_id)
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
        verified = sum(
            item.verification_status is VerificationStatus.VERIFIED for item in items
        )
        quarantined = sum(item.quarantine_record_id is not None for item in items)
        discovery_complete = sum(
            item.discovery_completeness is DiscoveryCompleteness.COMPLETE for item in items
        )
        manual = sum(item.manual_review_required for item in items)
        no_candidate = sum(
            item.selection_status is SelectionStatus.NO_CANDIDATE for item in items
        )
        fetch_failure = sum(
            item.ingestion_status
            in {IngestionStatus.RAW_FETCH_FAILED, IngestionStatus.RAW_HASH_CONFLICT}
            for item in items
        )
        parser_failure = sum(
            item.ingestion_status
            in {
                IngestionStatus.PARSER_FAILED,
                IngestionStatus.UNSUPPORTED_STRUCTURE,
                IngestionStatus.DATABASE_FAILED,
            }
            for item in items
        )
        unresolved = sum(
            item.selection_status is not SelectionStatus.SELECTED
            or item.verification_status is not VerificationStatus.VERIFIED
            for item in items
        )
        failed = sum(
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
            or item.evidence_verification_status is VerificationStatus.FAILED
            for item in items
        )
        snapshot_manifest = sha256_bytes(
            canonical_json_bytes(
                tuple(
                    {
                        "completeness": item.discovery_completeness,
                        "decision_id": item.decision_id,
                        "diagnostic_message": item.diagnostic_message,
                        "ingredient_id": item.ingredient_id,
                        "rank": item.rank,
                        "selection_status": item.selection_status,
                        "snapshot_id": item.snapshot_id,
                    }
                    for item in items
                )
            )
        )
        summary_changed = (
            current.selected_count != selected
            or current.fetched_count != fetched
            or current.ingested_count != ingested
            or current.verified_count != verified
            or current.quarantined_count != quarantined
            or current.unresolved_count != unresolved
            or current.failed_count != failed
            or current.snapshot_manifest_sha256 != snapshot_manifest
            or current.discovery_complete_count != discovery_complete
            or current.manual_review_count != manual
            or current.no_candidate_count != no_candidate
            or current.fetch_failure_count != fetch_failure
            or current.parser_failure_count != parser_failure
        )
        status = current.status if not summary_changed else BatchStatus.RUNNING
        completed_at = current.completed_at if not summary_changed else None
        if terminal:
            if verified == len(items):
                status = BatchStatus.COMPLETED
            elif failed == len(items):
                status = BatchStatus.FAILED
            elif failed:
                status = BatchStatus.PARTIAL_FAILURE
            else:
                status = BatchStatus.COMPLETED_WITH_UNRESOLVED_ITEMS
            if current.status is not status or current.completed_at is None:
                completed_at = self._now()
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
            snapshot_manifest_sha256=snapshot_manifest,
            discovery_complete_count=discovery_complete,
            manual_review_count=manual,
            no_candidate_count=no_candidate,
            fetch_failure_count=fetch_failure,
            parser_failure_count=parser_failure,
        )
        if updated != current:
            self.repository.update_live_batch_run(updated)
        return updated

    def _required_run(self, run_id: str) -> BatchRun:
        run = self.repository.get_live_batch_run(run_id)
        if run is None:
            raise DatabaseFailure(f"live batch run was not found: {run_id}")
        return run

    def _ensure_list(self, list_id: str) -> UtilizationList:
        existing = self.repository.get_utilization_list(list_id)
        if existing is not None:
            return existing
        value = load_utilization_list(list_id)
        self.repository.store_utilization_list(value)
        return value

    def _now(self) -> datetime:
        value = self.clock()
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC)


def _fetch_failure_is_retry_eligible(error: ODDError) -> bool:
    return isinstance(error, NetworkFailure) and error.details.get("transient") is not False


def _initial_live_item(run_id: str, entry: UtilizationEntry) -> BatchItem:
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


def _discovery_status(
    completeness: DiscoveryCompleteness,
    candidate_count: int,
) -> DiscoveryStatus:
    if completeness is DiscoveryCompleteness.INVALID:
        return DiscoveryStatus.METADATA_INVALID
    if completeness is DiscoveryCompleteness.INCOMPLETE:
        return DiscoveryStatus.DISCOVERY_INCOMPLETE
    if candidate_count == 0:
        return DiscoveryStatus.NO_CANDIDATE
    return DiscoveryStatus.DISCOVERED


def _selection_error(status: SelectionStatus) -> str | None:
    return {
        SelectionStatus.NO_CANDIDATE: ErrorCategory.NO_CANDIDATE.value,
        SelectionStatus.NO_ACCEPTABLE_CANDIDATE: ErrorCategory.NO_ACCEPTABLE_CANDIDATE.value,
        SelectionStatus.MULTIPLE_EQUIVALENT_CANDIDATES: ErrorCategory.AMBIGUOUS_SELECTION.value,
        SelectionStatus.AMBIGUOUS_REQUIRES_REVIEW: ErrorCategory.AMBIGUOUS_SELECTION.value,
        SelectionStatus.MANUAL_REVIEW_REQUIRED: ErrorCategory.AMBIGUOUS_SELECTION.value,
        SelectionStatus.METADATA_INVALID: ErrorCategory.CANDIDATE_METADATA_INVALID.value,
        SelectionStatus.FETCH_FAILED: ErrorCategory.CANDIDATE_LOOKUP_FAILED.value,
    }.get(status)

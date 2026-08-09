"""Bounded, resumable ODD-005 enrichment orchestration."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote, urlencode
from uuid import uuid4

from odd.connectors.dailymed.client import (
    DETAIL_PAGE_SIZE,
    DailyMedConnector,
    MalformedDetailResponse,
)
from odd.constants import (
    CONNECTOR_VERSION,
    ENRICHMENT_EXTRACTOR_VERSION,
    ENRICHMENT_REPORT_VERSION,
    ENRICHMENT_RULE_VERSION,
    ENRICHMENT_SELECTION_RULE_VERSION,
    MAPPING_VERSION,
    PARSER_VERSION,
    SCHEMA_VERSION,
)
from odd.enrichment.decision import (
    EnrichedSelection,
    deterministic_candidate_queue,
    evaluate_candidates,
    revise_selection,
)
from odd.enrichment.extractor import AssertionDraft, CandidateEvidenceExtractor
from odd.errors import (
    DatabaseFailure,
    MalformedMetadata,
    MalformedXML,
    NetworkFailure,
    ODDError,
    ProvenanceValidationFailure,
    RawHashConflict,
)
from odd.models import (
    BatchItem,
    CandidateEvidence,
    CandidateLookup,
    CandidateSelection,
    DailyMedCandidate,
    DownloadedSource,
    IngestionOutcome,
    IngestionStatus,
    ParserCompatibilityStatus,
    SelectionDecision,
    SelectionStatus,
    VerificationResult,
    VerificationStatus,
)
from odd.models.discovery import HTTPAttemptEvidence
from odd.models.enrichment import (
    CandidateDetailPage,
    DetailResponseEvidence,
    EnrichmentArtifactResult,
    EnrichmentBudget,
    EnrichmentCompleteness,
    EnrichmentDecisionRevision,
    EnrichmentItem,
    EnrichmentItemStatus,
    EnrichmentPlan,
    EnrichmentPlanItem,
    EnrichmentReport,
    EnrichmentRun,
    EnrichmentRunStatus,
    EnrichmentTier,
    EvidenceAssertion,
    EvidenceResult,
    EvidenceType,
)
from odd.provenance.canonical import canonical_json_bytes
from odd.provenance.enrichment_store import EnrichmentEvidenceStore
from odd.provenance.hashing import sha256_bytes, sha256_file
from odd.provenance.identifiers import (
    enrichment_decision_revision_id,
    enrichment_execution_id,
    enrichment_response_id,
    enrichment_run_id,
    enrichment_snapshot_id,
)
from odd.provenance.raw_store import RawStore
from odd.storage.sqlite import DATABASE_SCHEMA_VERSION, SQLiteRepository


@dataclass(frozen=True, slots=True)
class _ParentContext:
    parent_item: BatchItem
    selection: CandidateSelection
    lookup: CandidateLookup


@dataclass(slots=True)
class _ExecutionCounters:
    request_count: int = 0
    downloaded_bytes: int = 0
    cache_hit_count: int = 0
    retry_count: int = 0
    http_429_count: int = 0
    failure_count: int = 0
    budget_exhausted: bool = False
    diagnostic: str | None = None

    def can_start(self, budget: EnrichmentBudget) -> bool:
        reserved_requests = budget.retry_limit + 1
        reserved_bytes = reserved_requests * (budget.max_response_bytes + 1)
        return (
            self.request_count + reserved_requests <= budget.max_requests
            and self.downloaded_bytes + reserved_bytes <= budget.max_downloaded_bytes
        )

    def record_attempts(self, attempts: tuple[HTTPAttemptEvidence, ...]) -> None:
        self.request_count += len(attempts)
        self.downloaded_bytes += sum(
            value.response_size_bytes or 0 for value in attempts
        )
        self.retry_count += max(0, len(attempts) - 1)
        self.http_429_count += sum(value.status_code == 429 for value in attempts)


class EnrichmentCoordinator:
    """Add official detail evidence without modifying the ODD-004 parent snapshot."""

    def __init__(
        self,
        *,
        repository: SQLiteRepository,
        raw_store: RawStore,
        evidence_store: EnrichmentEvidenceStore,
        connector: DailyMedConnector,
        ingest: Callable[[str, str | None], IngestionOutcome],
        verify: Callable[[str], VerificationResult],
        clock: Callable[[], datetime],
    ) -> None:
        self.repository = repository
        self.raw_store = raw_store
        self.evidence_store = evidence_store
        self.connector = connector
        self.ingest_document = ingest
        self.verify_document = verify
        self.clock = clock
        self.extractor = CandidateEvidenceExtractor()

    def plan(
        self,
        parent_run_id: str,
        *,
        ranks: tuple[int, ...],
        budget: EnrichmentBudget,
    ) -> EnrichmentPlan:
        _validate_budget(budget)
        parent = self.repository.get_live_batch_run(parent_run_id)
        if parent is None or parent.canonical_report_sha256 is None:
            raise DatabaseFailure("ODD-005 requires a canonical ODD-004 live report")
        contexts = self._parent_contexts(parent_run_id, ranks)
        items = tuple(
            EnrichmentPlanItem(
                rank=context.parent_item.rank,
                ingredient_id=context.parent_item.ingredient_id,
                ingredient_name=context.parent_item.ingredient_name,
                parent_discovery_snapshot_id=_required_text(
                    context.parent_item.snapshot_id, "parent discovery snapshot"
                ),
                candidate_count=len(context.selection.candidates),
                unique_set_id_count=len(
                    {
                        (candidate.set_id or "").casefold()
                        for candidate in context.selection.candidates
                    }
                ),
                tier1_minimum_requests=len(context.selection.candidates),
                tier1_maximum_requests=(
                    len(context.selection.candidates) * budget.max_detail_pages
                ),
                tier2_maximum_candidates=len(context.selection.candidates),
            )
            for context in contexts
        )
        minimum = sum(item.tier1_minimum_requests for item in items)
        maximum = sum(item.tier1_maximum_requests for item in items)
        return EnrichmentPlan(
            parent_live_batch_run_id=parent_run_id,
            parent_canonical_sha256=parent.canonical_report_sha256,
            items=items,
            budget=budget,
            planned_minimum_requests=minimum,
            planned_maximum_requests=maximum,
            planned_maximum_downloaded_bytes=(
                min(maximum, budget.max_requests)
                * (budget.retry_limit + 1)
                * (budget.max_response_bytes + 1)
            ),
            endpoint_templates=(
                f"{self.connector.base_url}/spls/{{SETID}}/packaging.json",
                f"{self.connector.base_url}/spls/{{SETID}}.xml",
            ),
            estimated_minimum_seconds=minimum * budget.inter_request_delay_seconds,
        )

    def new_observation(
        self,
        parent_run_id: str,
        *,
        ranks: tuple[int, ...],
        parent_database_sha256: str,
        observation_token: str | None = None,
    ) -> tuple[EnrichmentRun, tuple[EnrichmentItem, ...]]:
        if len(parent_database_sha256) != 64 or any(
            character not in "0123456789abcdefABCDEF"
            for character in parent_database_sha256
        ):
            raise ProvenanceValidationFailure("parent database SHA-256 must have 64 hex digits")
        parent = self.repository.get_live_batch_run(parent_run_id)
        if parent is None or parent.canonical_report_sha256 is None:
            raise DatabaseFailure("ODD-005 parent run or canonical artifact is missing")
        contexts = self._parent_contexts(parent_run_id, ranks)
        token = observation_token or uuid4().hex
        identifier = enrichment_run_id(token)
        run = EnrichmentRun(
            enrichment_run_id=identifier,
            observation_token=token,
            parent_live_batch_run_id=parent_run_id,
            parent_canonical_sha256=parent.canonical_report_sha256,
            parent_database_sha256=parent_database_sha256,
            extractor_version=ENRICHMENT_EXTRACTOR_VERSION,
            extraction_rule_version=ENRICHMENT_RULE_VERSION,
            selection_rule_version=ENRICHMENT_SELECTION_RULE_VERSION,
            connector_version=CONNECTOR_VERSION,
            parser_version=PARSER_VERSION,
            normalized_schema_version=SCHEMA_VERSION,
            mapping_version=MAPPING_VERSION,
            database_schema_version=DATABASE_SCHEMA_VERSION,
            target_ranks=tuple(sorted(ranks)),
            started_at=self._now(),
            completed_at=None,
            status=EnrichmentRunStatus.PLANNED,
            current_snapshot_id=None,
            request_count=0,
            downloaded_bytes=0,
            cache_hit_count=0,
            retry_count=0,
            http_429_count=0,
            failure_count=0,
            enrichment_complete_count=0,
            selected_count=0,
            manual_review_count=0,
            enrichment_incomplete_count=len(contexts),
            source_drift_count=0,
            ingested_count=0,
            verified_count=0,
            canonical_report_sha256=None,
        )
        items = tuple(_initial_item(identifier, context) for context in contexts)
        if not self.repository.create_enrichment_run(run, items):
            raise DatabaseFailure("ODD-005 observation token already exists")
        return run, items

    def execute(
        self,
        run_id: str,
        *,
        budget: EnrichmentBudget,
        allow_tier2: bool,
        execution_token: str | None = None,
    ) -> EnrichmentArtifactResult:
        _validate_budget(budget)
        run = self._required_run(run_id)
        recovered_executions = self.repository.recover_running_enrichment_executions(
            run_id,
            completed_at=self._now(),
            diagnostic_message=(
                "Recovered an interrupted ODD-005 execution; retained response "
                "evidence was counted before resume."
            ),
        )
        if run.status in {EnrichmentRunStatus.COMPLETED, EnrichmentRunStatus.FAILED}:
            return self.report(run_id)
        contexts = self._contexts_for_run(run)
        if (
            run.status is EnrichmentRunStatus.COMPLETED_WITH_UNRESOLVED_ITEMS
            and recovered_executions == 0
            and not self._has_unmaterialized_evidence(run)
            and not self._has_bounded_tier2_work(
                run, contexts, budget=budget, allow_tier2=allow_tier2
            )
        ):
            return self.report(run_id)
        token = execution_token or uuid4().hex
        execution_id = enrichment_execution_id(run_id, token)
        if not self.repository.start_enrichment_execution(
            execution_id=execution_id,
            run_id=run_id,
            execution_token=token,
            budget=budget,
            started_at=self._now(),
        ):
            raise DatabaseFailure("ODD-005 execution token already exists")
        counters = _ExecutionCounters()
        try:
            return self._execute_started(
                run,
                contexts,
                execution_id=execution_id,
                budget=budget,
                allow_tier2=allow_tier2,
                counters=counters,
            )
        except Exception as exc:
            try:
                self.repository.finish_enrichment_execution(
                    execution_id,
                    completed_at=self._now(),
                    status="FAILED",
                    request_count=counters.request_count,
                    downloaded_bytes=counters.downloaded_bytes,
                    cache_hit_count=counters.cache_hit_count,
                    retry_count=counters.retry_count,
                    http_429_count=counters.http_429_count,
                    failure_count=counters.failure_count,
                    diagnostic_message=(
                        "Execution stopped after preserving completed response evidence: "
                        f"{type(exc).__name__}."
                    ),
                )
            except DatabaseFailure:
                # A later resume also recovers any execution row left open by
                # a storage-layer interruption.
                pass
            raise

    def _execute_started(
        self,
        run: EnrichmentRun,
        contexts: tuple[_ParentContext, ...],
        *,
        execution_id: str,
        budget: EnrichmentBudget,
        allow_tier2: bool,
        counters: _ExecutionCounters,
    ) -> EnrichmentArtifactResult:
        item_cache_hits = {context.parent_item.rank: 0 for context in contexts}
        connector = self.connector.with_operational_limits(
            timeout_seconds=budget.timeout_seconds,
            max_retries=budget.retry_limit,
            inter_request_delay_seconds=budget.inter_request_delay_seconds,
        )
        for context in contexts:
            for candidate in deterministic_candidate_queue(context.selection.candidates):
                if counters.budget_exhausted:
                    break
                request_count_before = counters.request_count
                cache_hits = self._ensure_tier1(
                    connector,
                    run,
                    context,
                    candidate,
                    execution_id,
                    budget,
                    counters,
                )
                item_cache_hits[context.parent_item.rank] += cache_hits
                if (
                    counters.request_count > request_count_before
                    and budget.inter_request_delay_seconds
                ):
                    connector.sleep(budget.inter_request_delay_seconds)
            if counters.budget_exhausted:
                break

        tier2_gate_reasons: dict[int, str] = {}
        if allow_tier2 and not counters.budget_exhausted:
            provisional = self._build_assertions(run, contexts, snapshot_id="pending")
            for context in contexts:
                candidate_ids = {value.candidate_id for value in context.selection.candidates}
                item_assertions = tuple(
                    value for value in provisional if value.candidate_id in candidate_ids
                )
                evaluations = evaluate_candidates(
                    context.selection.candidates, item_assertions
                )
                potential = tuple(
                    value.candidate
                    for value in evaluations
                    if value.unknown and not value.source_drift
                )
                if len(potential) > budget.max_tier2_candidates:
                    tier2_gate_reasons[context.parent_item.rank] = (
                        f"Tier 2 gate stopped: {len(potential)} candidates may still compete, "
                        f"exceeding the explicit {budget.max_tier2_candidates}-candidate cap."
                    )
                    continue
                for candidate in deterministic_candidate_queue(potential):
                    if not counters.can_start(budget):
                        counters.budget_exhausted = True
                        counters.diagnostic = (
                            "Hard budget stopped before the next Tier 2 request."
                        )
                        break
                    request_count_before = counters.request_count
                    cache_hits = self._ensure_tier2(
                        connector,
                        run,
                        context,
                        candidate,
                        execution_id,
                        budget,
                        counters,
                    )
                    item_cache_hits[context.parent_item.rank] += cache_hits
                    if (
                        counters.request_count > request_count_before
                        and budget.inter_request_delay_seconds
                    ):
                        connector.sleep(budget.inter_request_delay_seconds)

        provisional = self._build_assertions(run, contexts, snapshot_id="pending")
        parent_snapshots = tuple(
            (
                context.parent_item.rank,
                _required_text(context.parent_item.snapshot_id, "parent snapshot"),
            )
            for context in contexts
        )
        successful_responses = self.repository.get_detail_responses(
            run.enrichment_run_id, successful_only=True
        )
        response_hashes = tuple(
            sorted(
                (
                    response.response_id,
                    _required_text(response.raw_sha256, "detail response hash"),
                )
                for response in successful_responses
            )
        )
        assertion_identities = tuple(
            sorted(value.canonical_evidence_identity for value in provisional)
        )
        snapshot_id = enrichment_snapshot_id(
            parent_snapshots,
            response_hashes,
            assertion_identities,
            extractor_version=ENRICHMENT_EXTRACTOR_VERSION,
            extraction_rule_version=ENRICHMENT_RULE_VERSION,
        )
        assertions = tuple(
            replace(value, enrichment_snapshot_id=snapshot_id) for value in provisional
        )
        selections = self._selections(contexts, assertions)
        snapshot_completeness = _aggregate_completeness(selections)
        stored_snapshot = self.evidence_store.store_snapshot(
            snapshot_id=snapshot_id,
            parent_snapshots=parent_snapshots,
            response_hashes=response_hashes,
            assertions=assertions,
            completeness=snapshot_completeness.value,
        )
        self.repository.store_enrichment_snapshot(
            snapshot_id=snapshot_id,
            run_id=run.enrichment_run_id,
            parent_snapshots=parent_snapshots,
            response_hashes=response_hashes,
            assertions=assertions,
            completeness=snapshot_completeness,
            created_at=self._now(),
        )
        for context in contexts:
            selection = selections[context.parent_item.rank]
            updated, revision = self._updated_item(
                run,
                context,
                selection,
                assertions,
                snapshot_id,
                stored_snapshot.canonical_manifest_sha256,
                item_cache_hits[context.parent_item.rank],
                tier2_gate_reasons.get(context.parent_item.rank),
            )
            self.repository.store_decision_revision(revision, created_at=self._now())
            if selection.selected_candidate is not None:
                updated = self._promote_selected(context, selection, updated)
            self.repository.save_enrichment_item(
                updated, decision_revision_id=revision.revision_id
            )

        items = self.repository.get_enrichment_items(run.enrichment_run_id)
        retained_responses = self.repository.get_detail_responses(run.enrichment_run_id)
        retained_attempts = tuple(
            attempt for response in retained_responses for attempt in response.attempts
        )
        terminal = not counters.budget_exhausted
        status = (
            EnrichmentRunStatus.PARTIAL_BUDGET
            if counters.budget_exhausted
            else _terminal_status(items)
        )
        updated_run = replace(
            run,
            completed_at=self._now() if terminal else None,
            status=status,
            current_snapshot_id=snapshot_id,
            request_count=len(retained_attempts),
            downloaded_bytes=sum(
                value.response_size_bytes or 0 for value in retained_attempts
            ),
            cache_hit_count=run.cache_hit_count + counters.cache_hit_count,
            retry_count=sum(
                max(0, len(value.attempts) - 1) for value in retained_responses
            ),
            http_429_count=sum(value.status_code == 429 for value in retained_attempts),
            failure_count=sum(
                value.error_category is not None for value in retained_responses
            ),
            enrichment_complete_count=sum(
                value.enrichment_completeness is EnrichmentCompleteness.COMPLETE
                for value in items
            ),
            selected_count=sum(
                value.selection_status is SelectionStatus.SELECTED for value in items
            ),
            manual_review_count=sum(
                value.selection_status is SelectionStatus.MANUAL_REVIEW_REQUIRED
                for value in items
            ),
            enrichment_incomplete_count=sum(
                value.enrichment_completeness is EnrichmentCompleteness.INCOMPLETE
                for value in items
            ),
            source_drift_count=sum(value.source_drift_count for value in items),
            ingested_count=sum(
                value.ingestion_status
                in {IngestionStatus.INGESTED, IngestionStatus.ALREADY_INGESTED}
                for value in items
            ),
            verified_count=sum(
                value.verification_status is VerificationStatus.VERIFIED for value in items
            ),
            canonical_report_sha256=None,
        )
        self.repository.update_enrichment_run(updated_run)
        self.repository.finish_enrichment_execution(
            execution_id,
            completed_at=self._now(),
            status="BUDGET_EXHAUSTED" if counters.budget_exhausted else "COMPLETED",
            request_count=counters.request_count,
            downloaded_bytes=counters.downloaded_bytes,
            cache_hit_count=counters.cache_hit_count,
            retry_count=counters.retry_count,
            http_429_count=counters.http_429_count,
            failure_count=counters.failure_count,
            diagnostic_message=counters.diagnostic,
        )
        return self.report(run.enrichment_run_id)

    def status(self, run_id: str) -> tuple[EnrichmentRun, tuple[EnrichmentItem, ...]]:
        return self._required_run(run_id), self.repository.get_enrichment_items(run_id)

    def evidence(
        self, run_id: str, *, rank: int | None = None
    ) -> tuple[EvidenceAssertion, ...]:
        assertions = self.repository.get_enrichment_assertions(run_id)
        if rank is None:
            return assertions
        item = next(
            (value for value in self.repository.get_enrichment_items(run_id) if value.rank == rank),
            None,
        )
        if item is None:
            raise DatabaseFailure(f"ODD-005 rank is absent from the run: {rank}")
        context = self._context_from_item(item)
        candidate_ids = {value.candidate_id for value in context.selection.candidates}
        return tuple(value for value in assertions if value.candidate_id in candidate_ids)

    def decisions(
        self, run_id: str, *, rank: int | None = None
    ) -> tuple[EnrichmentDecisionRevision, ...]:
        return self.repository.get_decision_revisions(run_id, rank=rank)

    def report(self, run_id: str) -> EnrichmentArtifactResult:
        run = self._required_run(run_id)
        report = EnrichmentReport(
            report_version=ENRICHMENT_REPORT_VERSION,
            run=run,
            items=self.repository.get_enrichment_items(run_id),
            generated_at=self._now(),
        )
        stored = self.repository.store_enrichment_artifact(report)
        refreshed = self._required_run(run_id)
        refreshed_report = replace(report, run=refreshed)
        return EnrichmentArtifactResult(
            refreshed_report,
            stored.canonical_json,
            stored.canonical_sha256,
            stored.already_stored,
        )

    def verify_artifacts(self, run_id: str) -> dict[str, bool]:
        run = self._required_run(run_id)
        database = self.repository.enrichment_artifact_integrity(run_id)
        filesystem = (
            self.evidence_store.verify_snapshot(run.current_snapshot_id)
            if run.current_snapshot_id is not None
            else {
                "manifest_found": False,
                "manifest_hash": False,
                "response_hashes": False,
            }
        )
        return {
            **{f"database_{key}": value for key, value in database.items()},
            **{f"filesystem_{key}": value for key, value in filesystem.items()},
        }

    def _ensure_tier1(
        self,
        connector: DailyMedConnector,
        run: EnrichmentRun,
        context: _ParentContext,
        candidate: CandidateEvidence,
        execution_id: str,
        budget: EnrichmentBudget,
        counters: _ExecutionCounters,
    ) -> int:
        existing = self.repository.get_detail_responses(
            run.enrichment_run_id,
            candidate_id=candidate.candidate_id,
            tier=EnrichmentTier.TIER_1,
            successful_only=True,
        )
        malformed = tuple(value for value in existing if value.error_category is not None)
        if malformed:
            counters.cache_hit_count += len(malformed)
            return len(malformed)
        pages = _stored_packaging_pages(
            tuple(value for value in existing if value.error_category is None)
        )
        complete, _diagnostic = _packaging_completeness(pages, budget.max_detail_pages)
        if complete:
            counters.cache_hit_count += len(pages)
            return len(pages)
        failures = self.repository.get_detail_responses(
            run.enrichment_run_id,
            candidate_id=candidate.candidate_id,
            tier=EnrichmentTier.TIER_1,
        )
        if any(value.error_category == "permanent_http" for value in failures):
            return 0
        next_page = len(pages) + 1
        while next_page <= budget.max_detail_pages:
            if not counters.can_start(budget):
                counters.budget_exhausted = True
                counters.diagnostic = (
                    "Hard request/byte budget reserved for bounded retries was exhausted; "
                    "partial evidence is retained for explicit resume."
                )
                return 0
            set_id = _required_text(candidate.set_id, "candidate set ID")
            expected_version = _required_text(
                candidate.source_version, "candidate source version"
            )
            try:
                page = connector.packaging_page(
                    set_id,
                    page_number=next_page,
                    max_response_bytes=budget.max_response_bytes,
                )
                counters.record_attempts(page.attempts)
                response = DetailResponseEvidence(
                    response_id=enrichment_response_id(
                        run.enrichment_run_id,
                        candidate.candidate_id,
                        EnrichmentTier.TIER_1.value,
                        next_page,
                        page.canonical_request,
                        page.raw_sha256,
                    ),
                    enrichment_run_id=run.enrichment_run_id,
                    execution_id=execution_id,
                    parent_discovery_snapshot_id=_required_text(
                        context.parent_item.snapshot_id, "parent snapshot"
                    ),
                    candidate_id=candidate.candidate_id,
                    set_id=set_id,
                    expected_source_version=expected_version,
                    observed_source_version=page.observed_source_version,
                    tier=EnrichmentTier.TIER_1,
                    page_number=next_page,
                    canonical_request=page.canonical_request,
                    request_url=page.request_url,
                    final_url=page.final_url,
                    status_code=page.status_code,
                    content_type=page.content_type,
                    retrieved_at=page.retrieved_at,
                    etag=page.etag,
                    last_modified=page.last_modified,
                    raw_body=page.raw_body,
                    raw_sha256=page.raw_sha256,
                    attempts=page.attempts,
                    error_category=None,
                    diagnostic=None,
                )
                self.evidence_store.store_response(response)
                self.repository.store_detail_response(response)
                pages = (*pages, page)
                complete, _diagnostic = _packaging_completeness(
                    pages, budget.max_detail_pages
                )
                if complete or len(page.products) < DETAIL_PAGE_SIZE:
                    return 0
            except MalformedDetailResponse as exc:
                attempts = exc.response.attempts
                counters.record_attempts(attempts)
                counters.failure_count += 1
                raw_hash = sha256_bytes(exc.response.body)
                request, request_url = _packaging_request(
                    connector.base_url, set_id, next_page
                )
                malformed_response = DetailResponseEvidence(
                    response_id=enrichment_response_id(
                        run.enrichment_run_id,
                        candidate.candidate_id,
                        EnrichmentTier.TIER_1.value,
                        next_page,
                        request,
                        raw_hash,
                    ),
                    enrichment_run_id=run.enrichment_run_id,
                    execution_id=execution_id,
                    parent_discovery_snapshot_id=_required_text(
                        context.parent_item.snapshot_id, "parent snapshot"
                    ),
                    candidate_id=candidate.candidate_id,
                    set_id=set_id,
                    expected_source_version=expected_version,
                    observed_source_version=None,
                    tier=EnrichmentTier.TIER_1,
                    page_number=next_page,
                    canonical_request=request,
                    request_url=request_url,
                    final_url=exc.response.url,
                    status_code=exc.response.status_code,
                    content_type=exc.response.headers.get("content-type"),
                    retrieved_at=self._now(),
                    etag=exc.response.headers.get("etag"),
                    last_modified=exc.response.headers.get("last-modified"),
                    raw_body=exc.response.body,
                    raw_sha256=raw_hash,
                    attempts=attempts,
                    error_category=exc.category.value,
                    diagnostic=exc.message,
                )
                self.evidence_store.store_response(malformed_response)
                self.repository.store_detail_response(malformed_response)
                return 0
            except (NetworkFailure, MalformedMetadata) as exc:
                attempts = _error_attempts(exc)
                counters.record_attempts(attempts)
                counters.failure_count += 1
                request, request_url = _packaging_request(
                    connector.base_url, set_id, next_page
                )
                terminal = sha256_bytes(
                    canonical_json_bytes(
                        {
                            "error": exc.as_dict(),
                            "execution_id": execution_id,
                        }
                    )
                )
                failed = DetailResponseEvidence(
                    response_id=enrichment_response_id(
                        run.enrichment_run_id,
                        candidate.candidate_id,
                        EnrichmentTier.TIER_1.value,
                        next_page,
                        request,
                        None,
                        terminal,
                    ),
                    enrichment_run_id=run.enrichment_run_id,
                    execution_id=execution_id,
                    parent_discovery_snapshot_id=_required_text(
                        context.parent_item.snapshot_id, "parent snapshot"
                    ),
                    candidate_id=candidate.candidate_id,
                    set_id=set_id,
                    expected_source_version=expected_version,
                    observed_source_version=None,
                    tier=EnrichmentTier.TIER_1,
                    page_number=next_page,
                    canonical_request=request,
                    request_url=request_url,
                    final_url=None,
                    status_code=_error_status(exc),
                    content_type=None,
                    retrieved_at=self._now(),
                    etag=None,
                    last_modified=None,
                    raw_body=None,
                    raw_sha256=None,
                    attempts=attempts,
                    error_category=_error_classification(exc),
                    diagnostic=exc.message,
                )
                self.repository.store_detail_response(failed)
                return 0
            next_page += 1
            if budget.inter_request_delay_seconds:
                connector.sleep(budget.inter_request_delay_seconds)
        return 0

    def _ensure_tier2(
        self,
        connector: DailyMedConnector,
        run: EnrichmentRun,
        context: _ParentContext,
        candidate: CandidateEvidence,
        execution_id: str,
        budget: EnrichmentBudget,
        counters: _ExecutionCounters,
    ) -> int:
        set_id = _required_text(candidate.set_id, "candidate set ID")
        expected_version = _required_text(candidate.source_version, "candidate source version")
        request, endpoint = _tier2_request(connector.base_url, set_id)
        existing = self.repository.get_detail_responses(
            run.enrichment_run_id,
            candidate_id=candidate.candidate_id,
            tier=EnrichmentTier.TIER_2,
            successful_only=True,
        )
        if existing:
            counters.cache_hit_count += 1
            return 1
        failures = self.repository.get_detail_responses(
            run.enrichment_run_id,
            candidate_id=candidate.candidate_id,
            tier=EnrichmentTier.TIER_2,
        )
        if any(
            value.raw_body is None
            and value.error_category == "permanent_http"
            and value.canonical_request == request
            for value in failures
        ):
            return 0
        if not counters.can_start(budget):
            counters.budget_exhausted = True
            counters.diagnostic = "Hard budget stopped before a Tier 2 SPL request."
            return 0
        try:
            download = connector.download(
                DailyMedCandidate(
                    set_id=set_id,
                    source_version=expected_version,
                    title=candidate.title or "",
                    published_date=candidate.published_date or "",
                    metadata=candidate.raw_metadata,
                ),
                max_response_bytes=budget.max_response_bytes,
            )
            counters.record_attempts(download.http_attempts)
            raw_hash = sha256_bytes(download.body)
            extraction_error: MalformedXML | None = None
            try:
                extraction = self.extractor.spl_xml(
                    download.body,
                    ingredient_name=context.parent_item.ingredient_name,
                    expected_set_id=set_id,
                    expected_source_version=expected_version,
                    source_url=download.source_url,
                    retrieved_at=download.retrieved_at,
                )
                observed_version = extraction.source_version
            except MalformedXML as exc:
                extraction_error = exc
                observed_version = None
                counters.failure_count += 1
            response = DetailResponseEvidence(
                response_id=enrichment_response_id(
                    run.enrichment_run_id,
                    candidate.candidate_id,
                    EnrichmentTier.TIER_2.value,
                    1,
                    request,
                    raw_hash,
                ),
                enrichment_run_id=run.enrichment_run_id,
                execution_id=execution_id,
                parent_discovery_snapshot_id=_required_text(
                    context.parent_item.snapshot_id, "parent snapshot"
                ),
                candidate_id=candidate.candidate_id,
                set_id=set_id,
                expected_source_version=expected_version,
                observed_source_version=observed_version,
                tier=EnrichmentTier.TIER_2,
                page_number=1,
                canonical_request=request,
                request_url=endpoint,
                final_url=download.source_url,
                status_code=download.status_code,
                content_type=download.headers.get("content-type"),
                retrieved_at=download.retrieved_at,
                etag=download.headers.get("etag"),
                last_modified=download.headers.get("last-modified"),
                raw_body=download.body,
                raw_sha256=raw_hash,
                attempts=download.http_attempts,
                error_category=(
                    extraction_error.category.value
                    if extraction_error is not None
                    else None
                ),
                diagnostic=(
                    extraction_error.message if extraction_error is not None else None
                ),
            )
            self.evidence_store.store_response(response)
            self.repository.store_detail_response(response)
        except NetworkFailure as exc:
            attempts = _error_attempts(exc)
            counters.record_attempts(attempts)
            counters.failure_count += 1
            terminal = sha256_bytes(
                canonical_json_bytes({"error": exc.as_dict(), "execution_id": execution_id})
            )
            failed = DetailResponseEvidence(
                response_id=enrichment_response_id(
                    run.enrichment_run_id,
                    candidate.candidate_id,
                    EnrichmentTier.TIER_2.value,
                    1,
                    request,
                    None,
                    terminal,
                ),
                enrichment_run_id=run.enrichment_run_id,
                execution_id=execution_id,
                parent_discovery_snapshot_id=_required_text(
                    context.parent_item.snapshot_id, "parent snapshot"
                ),
                candidate_id=candidate.candidate_id,
                set_id=set_id,
                expected_source_version=expected_version,
                observed_source_version=None,
                tier=EnrichmentTier.TIER_2,
                page_number=1,
                canonical_request=request,
                request_url=endpoint,
                final_url=None,
                status_code=_error_status(exc),
                content_type=None,
                retrieved_at=self._now(),
                etag=None,
                last_modified=None,
                raw_body=None,
                raw_sha256=None,
                attempts=attempts,
                error_category=_error_classification(exc),
                diagnostic=exc.message,
            )
            self.repository.store_detail_response(failed)
        return 0

    def _build_assertions(
        self,
        run: EnrichmentRun,
        contexts: tuple[_ParentContext, ...],
        *,
        snapshot_id: str,
    ) -> tuple[EvidenceAssertion, ...]:
        assertions: list[EvidenceAssertion] = []
        for context in contexts:
            parent_snapshot = _required_text(context.parent_item.snapshot_id, "parent snapshot")
            for candidate in deterministic_candidate_queue(context.selection.candidates):
                drafts = list(self.extractor.tier0(candidate))
                tier1 = self.repository.get_detail_responses(
                    run.enrichment_run_id,
                    candidate_id=candidate.candidate_id,
                    tier=EnrichmentTier.TIER_1,
                    successful_only=True,
                )
                pages = _stored_packaging_pages(
                    tuple(value for value in tier1 if value.error_category is None)
                )
                if pages:
                    complete, completeness_diagnostic = _packaging_completeness(
                        pages, 10_000
                    )
                    drafts.extend(
                        self.extractor.packaging(
                            pages,
                            ingredient_name=context.parent_item.ingredient_name,
                            expected_set_id=_required_text(candidate.set_id, "candidate set ID"),
                            expected_source_version=_required_text(
                                candidate.source_version, "candidate source version"
                            ),
                            complete=complete,
                            completeness_diagnostic=completeness_diagnostic,
                            expected_published_date=_required_text(
                                candidate.published_date, "candidate publication date"
                            ),
                        )
                    )
                tier2 = self.repository.get_detail_responses(
                    run.enrichment_run_id,
                    candidate_id=candidate.candidate_id,
                    tier=EnrichmentTier.TIER_2,
                    successful_only=True,
                )
                if tier2 and tier2[-1].raw_body is not None:
                    response = tier2[-1]
                    xml_body = response.raw_body
                    assert xml_body is not None
                    try:
                        extraction = self.extractor.spl_xml(
                            xml_body,
                            ingredient_name=context.parent_item.ingredient_name,
                            expected_set_id=_required_text(candidate.set_id, "candidate set ID"),
                            expected_source_version=_required_text(
                                candidate.source_version, "candidate source version"
                            ),
                            source_url=response.final_url or response.request_url,
                            retrieved_at=response.retrieved_at,
                        )
                        drafts.extend(extraction.drafts)
                    except MalformedXML as exc:
                        drafts.append(
                            AssertionDraft(
                                evidence_type=EvidenceType.SUPPORTED_DOCUMENT_STRUCTURE,
                                result=EvidenceResult.PROVEN_FALSE,
                                tier=EnrichmentTier.TIER_2,
                                raw_response_sha256=response.raw_sha256,
                                source_url_identity=response.final_url
                                or response.request_url,
                                source_locator="/document",
                                source_field_or_code="malformed XML",
                                diagnostic=exc.message,
                                observed_source_version=response.observed_source_version,
                                retrieved_at=response.retrieved_at,
                                source_response_sha256s=(
                                    (response.raw_sha256,)
                                    if response.raw_sha256 is not None
                                    else ()
                                ),
                            )
                        )
                assertions.extend(
                    self.extractor.materialize(
                        tuple(drafts),
                        parent_discovery_snapshot_id=parent_snapshot,
                        enrichment_run_id=run.enrichment_run_id,
                        enrichment_snapshot_id=snapshot_id,
                        candidate=candidate,
                    )
                )
        return tuple(
            sorted(
                assertions,
                key=lambda value: (
                    value.candidate_id,
                    value.evidence_type.value,
                    value.tier.value,
                    value.assertion_id,
                ),
            )
        )

    @staticmethod
    def _selections(
        contexts: tuple[_ParentContext, ...],
        assertions: tuple[EvidenceAssertion, ...],
    ) -> dict[int, EnrichedSelection]:
        selections: dict[int, EnrichedSelection] = {}
        for context in contexts:
            candidate_ids = {value.candidate_id for value in context.selection.candidates}
            values = tuple(
                assertion for assertion in assertions if assertion.candidate_id in candidate_ids
            )
            selections[context.parent_item.rank] = revise_selection(
                context.selection.candidates, values
            )
        return selections

    def _has_bounded_tier2_work(
        self,
        run: EnrichmentRun,
        contexts: tuple[_ParentContext, ...],
        *,
        budget: EnrichmentBudget,
        allow_tier2: bool,
    ) -> bool:
        if not allow_tier2 or budget.max_tier2_candidates == 0:
            return False
        assertions = self._build_assertions(run, contexts, snapshot_id="pending")
        for context in contexts:
            candidate_ids = {value.candidate_id for value in context.selection.candidates}
            evaluations = evaluate_candidates(
                context.selection.candidates,
                tuple(
                    value for value in assertions if value.candidate_id in candidate_ids
                ),
            )
            potential = tuple(
                value.candidate
                for value in evaluations
                if value.unknown and not value.source_drift
            )
            if len(potential) > budget.max_tier2_candidates:
                continue
            for candidate in potential:
                retained = self.repository.get_detail_responses(
                    run.enrichment_run_id,
                    candidate_id=candidate.candidate_id,
                    tier=EnrichmentTier.TIER_2,
                    successful_only=True,
                )
                request, _endpoint = _tier2_request(
                    self.connector.base_url,
                    _required_text(candidate.set_id, "candidate set ID"),
                )
                failures = self.repository.get_detail_responses(
                    run.enrichment_run_id,
                    candidate_id=candidate.candidate_id,
                    tier=EnrichmentTier.TIER_2,
                )
                permanently_failed = any(
                    value.raw_body is None
                    and value.error_category == "permanent_http"
                    and value.canonical_request == request
                    for value in failures
                )
                if not retained and not permanently_failed:
                    return True
        return False

    def _has_unmaterialized_evidence(self, run: EnrichmentRun) -> bool:
        retained = tuple(
            sorted(
                (
                    response.response_id,
                    _required_text(response.raw_sha256, "detail response hash"),
                )
                for response in self.repository.get_detail_responses(
                    run.enrichment_run_id, successful_only=True
                )
            )
        )
        if run.current_snapshot_id is None:
            return bool(retained)
        materialized = self.repository.get_enrichment_snapshot_response_hashes(
            run.current_snapshot_id
        )
        if retained != materialized:
            return True
        for rank in run.target_ranks:
            revisions = self.repository.get_decision_revisions(
                run.enrichment_run_id, rank=rank
            )
            if (
                not revisions
                or revisions[-1].enrichment_snapshot_id != run.current_snapshot_id
            ):
                return True
        return False

    def _updated_item(
        self,
        run: EnrichmentRun,
        context: _ParentContext,
        selection: EnrichedSelection,
        assertions: tuple[EvidenceAssertion, ...],
        snapshot_id: str,
        snapshot_manifest_sha256: str,
        cache_hits: int,
        tier2_gate_reason: str | None,
    ) -> tuple[EnrichmentItem, EnrichmentDecisionRevision]:
        existing = next(
            value
            for value in self.repository.get_enrichment_items(run.enrichment_run_id)
            if value.rank == context.parent_item.rank
        )
        candidate_ids = {value.candidate_id for value in context.selection.candidates}
        responses = tuple(
            value
            for value in self.repository.get_detail_responses(run.enrichment_run_id)
            if value.candidate_id in candidate_ids
        )
        tier1_success = tuple(
            value
            for value in responses
            if value.tier is EnrichmentTier.TIER_1
            and value.raw_body is not None
            and value.error_category is None
        )
        tier2_success = tuple(
            value
            for value in responses
            if value.tier is EnrichmentTier.TIER_2 and value.raw_body is not None
        )
        tier1_complete = 0
        for candidate in context.selection.candidates:
            pages = _stored_packaging_pages(
                tuple(
                    value
                    for value in tier1_success
                    if value.candidate_id == candidate.candidate_id
                )
            )
            complete, _diagnostic = _packaging_completeness(pages, 10_000)
            tier1_complete += int(complete)
        attempts = tuple(attempt for response in responses for attempt in response.attempts)
        manual_reason = selection.reason
        if tier2_gate_reason:
            manual_reason = f"{manual_reason} {tier2_gate_reason}"
        item_status = _item_status(selection)
        updated = replace(
            existing,
            candidates_excluded_tier0=0,
            tier1_attempted=len(
                {
                    value.candidate_id
                    for value in responses
                    if value.tier is EnrichmentTier.TIER_1
                }
            ),
            tier1_complete=tier1_complete,
            tier2_attempted=len(
                {
                    value.candidate_id
                    for value in responses
                    if value.tier is EnrichmentTier.TIER_2
                }
            ),
            tier2_complete=len({value.candidate_id for value in tier2_success}),
            candidates_proven_eligible=sum(value.eligible for value in selection.evaluations),
            candidates_proven_ineligible=sum(
                value.proven_ineligible for value in selection.evaluations
            ),
            candidates_unknown=sum(value.unknown for value in selection.evaluations),
            candidates_conflict=sum(value.conflict for value in selection.evaluations),
            source_drift_count=sum(value.source_drift for value in selection.evaluations),
            enrichment_completeness=selection.completeness,
            item_status=item_status,
            selection_status=selection.selection_status,
            selected_candidate_id=(
                selection.selected_candidate.candidate_id
                if selection.selected_candidate is not None
                else None
            ),
            selected_set_id=(
                selection.selected_candidate.set_id
                if selection.selected_candidate is not None
                else None
            ),
            selected_source_version=(
                selection.selected_candidate.source_version
                if selection.selected_candidate is not None
                else None
            ),
            manual_review_reason=manual_reason,
            request_count=len(attempts),
            downloaded_bytes=sum(value.response_size_bytes or 0 for value in attempts),
            cache_hit_count=existing.cache_hit_count + cache_hits,
            retry_count=sum(max(0, len(value.attempts) - 1) for value in responses),
            http_429_count=sum(value.status_code == 429 for value in attempts),
            failure_count=sum(value.error_category is not None for value in responses),
            canonical_artifact_sha256=snapshot_manifest_sha256,
            diagnostic_message=manual_reason,
        )
        previous = self.repository.get_decision_revisions(
            run.enrichment_run_id, rank=context.parent_item.rank
        )
        decision_payload = {
            "enrichment_run_id": run.enrichment_run_id,
            "enrichment_snapshot_id": snapshot_id,
            "ingredient_id": context.parent_item.ingredient_id,
            "manual_review_required": selection.manual_review_required,
            "parent_decision_id": context.selection.decision_id,
            "rank": context.parent_item.rank,
            "selected_candidate_id": updated.selected_candidate_id,
            "selected_set_id": updated.selected_set_id,
            "selected_source_version": updated.selected_source_version,
            "selection_reason": selection.reason,
            "selection_status": selection.selection_status,
        }
        decision_digest = sha256_bytes(canonical_json_bytes(decision_payload))
        revision_id = enrichment_decision_revision_id(
            run.enrichment_run_id,
            context.parent_item.rank,
            snapshot_id,
            decision_digest,
        )
        if previous and previous[-1].revision_id == revision_id:
            # Operational retries and failures can update item counters without
            # changing the canonical decision. Do not manufacture a self-linked
            # revision for an unchanged snapshot and decision.
            return updated, previous[-1]
        revision = EnrichmentDecisionRevision(
            revision_id=revision_id,
            enrichment_run_id=run.enrichment_run_id,
            enrichment_snapshot_id=snapshot_id,
            parent_decision_id=context.selection.decision_id,
            previous_revision_id=previous[-1].revision_id if previous else None,
            rank=context.parent_item.rank,
            ingredient_id=context.parent_item.ingredient_id,
            selection_status=selection.selection_status,
            selected_candidate_id=updated.selected_candidate_id,
            selected_set_id=updated.selected_set_id,
            selected_source_version=updated.selected_source_version,
            selection_reason=selection.reason,
            manual_review_required=selection.manual_review_required,
        )
        return updated, revision

    def _promote_selected(
        self,
        context: _ParentContext,
        selection: EnrichedSelection,
        item: EnrichmentItem,
    ) -> EnrichmentItem:
        candidate = selection.selected_candidate
        assert candidate is not None
        responses = self.repository.get_detail_responses(
            item.enrichment_run_id,
            candidate_id=candidate.candidate_id,
            tier=EnrichmentTier.TIER_2,
            successful_only=True,
        )
        if not responses or responses[-1].raw_body is None:
            return replace(
                item,
                ingestion_status=IngestionStatus.NOT_SELECTED,
                diagnostic_message=(
                    "Selection was proven but no cached Tier 2 XML exists; network fetch was "
                    "not performed implicitly."
                ),
            )
        response = responses[-1]
        body = response.raw_body
        assert body is not None
        selected_model = next(
            value
            for value in context.lookup.candidates
            if value.set_id.casefold() == _required_text(candidate.set_id, "set ID").casefold()
            and value.source_version == candidate.source_version
        )
        decision = SelectionDecision(
            selected=selected_model,
            ordered_candidates=context.lookup.candidates,
            rule_version=ENRICHMENT_SELECTION_RULE_VERSION,
            rule_description=(
                "ODD-005 requires complete four-valued evidence for the entire candidate set "
                "and never uses response order or lexical set ID as a tie-break."
            ),
            reason=selection.reason,
            ambiguity_exposed=False,
        )
        download = DownloadedSource(
            set_id=_required_text(candidate.set_id, "set ID"),
            source_version=_required_text(candidate.source_version, "source version"),
            source_url=response.final_url or response.request_url,
            retrieved_at=response.retrieved_at,
            body=body,
            status_code=response.status_code or 200,
            headers={"content-type": response.content_type or "application/xml"},
            http_attempts=response.attempts,
        )
        try:
            raw = self.raw_store.store(download, context.lookup, decision)
            outcome = self.ingest_document(download.set_id, download.source_version)
            verification = self.verify_document(outcome.document_id)
            parser_status = (
                ParserCompatibilityStatus.FULLY_PARSED
                if outcome.unmapped_section_count == 0
                else ParserCompatibilityStatus.PARSED_WITH_UNMAPPED_SECTIONS
            )
            return replace(
                item,
                raw_xml_sha256=raw.identity.raw_sha256,
                document_id=outcome.document_id,
                ingestion_status=(
                    IngestionStatus.ALREADY_INGESTED
                    if outcome.status == "already_ingested"
                    else IngestionStatus.INGESTED
                ),
                parser_compatibility=parser_status,
                verification_status=(
                    VerificationStatus.VERIFIED
                    if verification.ok
                    else VerificationStatus.FAILED
                ),
                diagnostic_message=(
                    None if verification.ok else "Normalized-document verification failed."
                ),
            )
        except RawHashConflict as exc:
            return replace(
                item,
                raw_xml_sha256=sha256_bytes(body),
                ingestion_status=IngestionStatus.RAW_HASH_CONFLICT,
                diagnostic_message=exc.message,
            )
        except ODDError as exc:
            return replace(
                item,
                raw_xml_sha256=sha256_bytes(body),
                ingestion_status=IngestionStatus.PARSER_FAILED,
                parser_compatibility=ParserCompatibilityStatus.PARSER_FAILED,
                diagnostic_message=f"{exc.category.value}: {exc.message}",
            )

    def _parent_contexts(
        self, parent_run_id: str, ranks: tuple[int, ...]
    ) -> tuple[_ParentContext, ...]:
        normalized_ranks = tuple(sorted(set(ranks)))
        if not normalized_ranks or any(value <= 0 for value in normalized_ranks):
            raise ProvenanceValidationFailure("ODD-005 ranks must be positive")
        by_rank = {
            item.rank: item for item in self.repository.get_live_batch_items(parent_run_id)
        }
        missing = [value for value in normalized_ranks if value not in by_rank]
        if missing:
            raise DatabaseFailure(f"ODD-005 parent run has no ranks: {missing}")
        contexts = tuple(self._context_from_parent_item(by_rank[rank]) for rank in normalized_ranks)
        if any(
            context.parent_item.discovery_completeness.value != "COMPLETE"
            for context in contexts
        ):
            raise ProvenanceValidationFailure(
                "ODD-005 cannot enrich an incomplete parent discovery snapshot"
            )
        return contexts

    def _contexts_for_run(self, run: EnrichmentRun) -> tuple[_ParentContext, ...]:
        return self._parent_contexts(run.parent_live_batch_run_id, run.target_ranks)

    def _context_from_item(self, item: EnrichmentItem) -> _ParentContext:
        parent = next(
            value
            for value in self.repository.get_live_batch_items(
                self._required_run(item.enrichment_run_id).parent_live_batch_run_id
            )
            if value.rank == item.rank
        )
        return self._context_from_parent_item(parent)

    def _context_from_parent_item(self, item: BatchItem) -> _ParentContext:
        decision_id = _required_text(item.decision_id, "parent decision ID")
        discovery_id = _required_text(item.discovery_run_id, "parent discovery run ID")
        selection = self.repository.get_candidate_selection(decision_id)
        lookup = self.repository.get_candidate_lookup(discovery_id)
        if selection is None or lookup is None:
            raise DatabaseFailure("ODD-005 parent candidate evidence cannot be reconstructed")
        return _ParentContext(item, selection, lookup)

    def _required_run(self, run_id: str) -> EnrichmentRun:
        run = self.repository.get_enrichment_run(run_id)
        if run is None:
            raise DatabaseFailure(f"ODD-005 enrichment run was not found: {run_id}")
        return run

    def _now(self) -> datetime:
        value = self.clock()
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC)


def _initial_item(run_id: str, context: _ParentContext) -> EnrichmentItem:
    parent = context.parent_item
    return EnrichmentItem(
        enrichment_run_id=run_id,
        rank=parent.rank,
        ingredient_id=parent.ingredient_id,
        ingredient_name=parent.ingredient_name,
        parent_discovery_run_id=_required_text(parent.discovery_run_id, "discovery run ID"),
        parent_discovery_snapshot_id=_required_text(parent.snapshot_id, "snapshot ID"),
        parent_decision_id=_required_text(parent.decision_id, "decision ID"),
        candidate_total=len(context.selection.candidates),
        candidates_excluded_tier0=0,
        tier1_attempted=0,
        tier1_complete=0,
        tier2_attempted=0,
        tier2_complete=0,
        candidates_proven_eligible=0,
        candidates_proven_ineligible=0,
        candidates_unknown=len(context.selection.candidates),
        candidates_conflict=0,
        source_drift_count=0,
        enrichment_completeness=EnrichmentCompleteness.INCOMPLETE,
        item_status=EnrichmentItemStatus.PENDING,
        selection_status=SelectionStatus.MANUAL_REVIEW_REQUIRED,
        selected_candidate_id=None,
        selected_set_id=None,
        selected_source_version=None,
        manual_review_reason="Candidate enrichment has not run.",
        request_count=0,
        downloaded_bytes=0,
        cache_hit_count=0,
        retry_count=0,
        http_429_count=0,
        failure_count=0,
        ingestion_status=IngestionStatus.NOT_SELECTED,
        parser_compatibility=ParserCompatibilityStatus.NOT_INGESTED,
        verification_status=VerificationStatus.NOT_VERIFIED,
        document_id=None,
        raw_xml_sha256=None,
        canonical_artifact_sha256=None,
        diagnostic_message="Candidate enrichment has not run.",
    )


def _validate_budget(value: EnrichmentBudget) -> None:
    if value.max_requests <= 0 or value.max_downloaded_bytes <= 0:
        raise ProvenanceValidationFailure("request and byte budgets must be positive")
    if value.timeout_seconds <= 0 or value.retry_limit < 0:
        raise ProvenanceValidationFailure("timeout must be positive and retry limit nonnegative")
    if value.inter_request_delay_seconds < 0 or value.max_response_bytes <= 0:
        raise ProvenanceValidationFailure("rate delay must be nonnegative and size positive")
    if value.max_detail_pages <= 0 or value.max_tier2_candidates < 0:
        raise ProvenanceValidationFailure("detail-page/Tier-2 caps are invalid")
    if value.max_response_bytes + 1 > value.max_downloaded_bytes:
        raise ProvenanceValidationFailure(
            "byte budget must accommodate one bounded response plus overflow sentinel"
        )


def _stored_packaging_pages(
    responses: tuple[DetailResponseEvidence, ...]
) -> tuple[CandidateDetailPage, ...]:
    pages: list[CandidateDetailPage] = []
    for response in responses:
        if response.raw_body is None or response.raw_sha256 is None:
            continue
        try:
            decoded = json.loads(response.raw_body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DatabaseFailure("cached packaging response is not valid UTF-8 JSON") from exc
        if not isinstance(decoded, dict) or not isinstance(decoded.get("data"), dict):
            raise DatabaseFailure("cached packaging response has no data object")
        data = cast(dict[str, Any], decoded["data"])
        products_value = data.get("products")
        if not isinstance(products_value, list):
            raise DatabaseFailure("cached packaging response has no products array")
        products: list[dict[str, object]] = []
        for value in products_value:
            if not isinstance(value, dict):
                raise DatabaseFailure("cached packaging product is not an object")
            products.append(cast(dict[str, object], value))
        pages.append(
            CandidateDetailPage(
                set_id=str(data.get("setid", response.set_id)),
                observed_source_version=str(
                    data.get("spl_version", response.observed_source_version or "")
                ),
                title=str(data.get("title", "")),
                published_date=str(data.get("published_date", "")),
                page_number=response.page_number,
                page_size=DETAIL_PAGE_SIZE,
                request_url=response.request_url,
                canonical_request=response.canonical_request,
                final_url=response.final_url or response.request_url,
                status_code=response.status_code or 200,
                content_type=response.content_type or "application/json",
                retrieved_at=response.retrieved_at,
                etag=response.etag,
                last_modified=response.last_modified,
                raw_body=response.raw_body,
                raw_sha256=response.raw_sha256,
                payload=cast(dict[str, object], decoded),
                products=tuple(products),
                attempts=response.attempts,
            )
        )
    return tuple(sorted(pages, key=lambda value: value.page_number))


def _packaging_completeness(
    pages: tuple[CandidateDetailPage, ...], max_pages: int
) -> tuple[bool, str | None]:
    if not pages:
        return False, "No successful packaging detail response was retained."
    numbers = tuple(value.page_number for value in pages)
    if numbers != tuple(range(1, len(pages) + 1)):
        return False, "Packaging detail pages are not contiguous from page 1."
    versions = {value.observed_source_version for value in pages}
    set_ids = {value.set_id.casefold() for value in pages}
    if len(versions) != 1 or len(set_ids) != 1:
        return False, "Packaging identity metadata conflicts between pages."
    identities: dict[str, bytes] = {}
    for page in pages:
        for product in page.products:
            code = product.get("product_code")
            identity = str(code).strip().casefold() if isinstance(code, str) else ""
            if not identity:
                return (
                    False,
                    "Packaging detail product lacks a stable product_code; page/index was not "
                    "invented as an identity.",
                )
            canonical = canonical_json_bytes(product)
            if identity in identities:
                return (
                    False,
                    (
                        "Packaging detail repeated a product identity between pages."
                        if identities[identity] == canonical
                        else "Packaging detail returned conflicting metadata for one "
                        "product_code."
                    ),
                )
            identities[identity] = canonical
    if len(pages) > max_pages:
        return False, "Stored packaging pages exceed the configured page cap."
    if len(pages[-1].products) >= DETAIL_PAGE_SIZE:
        return False, "No short terminal packaging page proves pagination completeness."
    return True, None


def _packaging_request(
    base_url: str, set_id: str, page_number: int
) -> tuple[tuple[tuple[str, str], ...], str]:
    endpoint = f"{base_url}/spls/{quote(set_id, safe='')}/packaging.json"
    query = (("page", str(page_number)), ("pagesize", str(DETAIL_PAGE_SIZE)))
    url = f"{endpoint}?{urlencode(query)}"
    return (
        (
            ("endpoint", endpoint),
            ("page", str(page_number)),
            ("pagesize", str(DETAIL_PAGE_SIZE)),
            ("setid", set_id.casefold()),
        ),
        url,
    )


def _tier2_request(base_url: str, set_id: str) -> tuple[tuple[tuple[str, str], ...], str]:
    endpoint = f"{base_url}/spls/{quote(set_id, safe='')}.xml"
    return (
        (("accept", "*/*"), ("endpoint", endpoint), ("setid", set_id.casefold())),
        endpoint,
    )


def _error_attempts(error: ODDError) -> tuple[HTTPAttemptEvidence, ...]:
    raw = error.details.get("attempts")
    if not isinstance(raw, list):
        return ()
    values: list[HTTPAttemptEvidence] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            values.append(
                HTTPAttemptEvidence(
                    attempt_number=int(item["attempt_number"]),
                    status_code=(
                        int(item["status_code"])
                        if item.get("status_code") is not None
                        else None
                    ),
                    error_category=(
                        str(item["error_category"])
                        if item.get("error_category") is not None
                        else None
                    ),
                    diagnostic_message=(
                        str(item["diagnostic_message"])
                        if item.get("diagnostic_message") is not None
                        else None
                    ),
                    retry_after_seconds=(
                        float(item["retry_after_seconds"])
                        if item.get("retry_after_seconds") is not None
                        else None
                    ),
                    backoff_seconds=(
                        float(item["backoff_seconds"])
                        if item.get("backoff_seconds") is not None
                        else None
                    ),
                    retry_eligible=bool(item["retry_eligible"]),
                    response_size_bytes=(
                        int(item["response_size_bytes"])
                        if item.get("response_size_bytes") is not None
                        else None
                    ),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return tuple(values)


def _error_status(error: ODDError) -> int | None:
    value = error.details.get("status_code")
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else None


def _error_classification(error: ODDError) -> str:
    status = _error_status(error)
    if status is not None and 400 <= status < 500 and status != 429:
        return "permanent_http"
    if isinstance(error, NetworkFailure):
        return (
            "transient_network"
            if error.details.get("transient") is not False
            else "permanent_network"
        )
    return error.category.value


def _aggregate_completeness(
    selections: dict[int, EnrichedSelection]
) -> EnrichmentCompleteness:
    values = {selection.completeness for selection in selections.values()}
    if EnrichmentCompleteness.SOURCE_DRIFT in values:
        return EnrichmentCompleteness.SOURCE_DRIFT
    if EnrichmentCompleteness.CONFLICT in values:
        return EnrichmentCompleteness.CONFLICT
    if EnrichmentCompleteness.INCOMPLETE in values:
        return EnrichmentCompleteness.INCOMPLETE
    return EnrichmentCompleteness.COMPLETE


def _item_status(selection: EnrichedSelection) -> EnrichmentItemStatus:
    if selection.completeness is EnrichmentCompleteness.SOURCE_DRIFT:
        return EnrichmentItemStatus.SOURCE_DRIFT
    if selection.completeness is EnrichmentCompleteness.INCOMPLETE:
        return EnrichmentItemStatus.ENRICHMENT_INCOMPLETE
    if selection.manual_review_required:
        return EnrichmentItemStatus.MANUAL_REVIEW_REQUIRED
    return EnrichmentItemStatus.ENRICHMENT_COMPLETE


def _terminal_status(items: tuple[EnrichmentItem, ...]) -> EnrichmentRunStatus:
    if items and all(value.verification_status is VerificationStatus.VERIFIED for value in items):
        return EnrichmentRunStatus.COMPLETED
    if items and all(value.item_status is EnrichmentItemStatus.FAILED for value in items):
        return EnrichmentRunStatus.FAILED
    return EnrichmentRunStatus.COMPLETED_WITH_UNRESOLVED_ITEMS


def _required_text(value: str | None, name: str) -> str:
    if value is None or not value.strip():
        raise ProvenanceValidationFailure(f"ODD-005 requires {name}")
    return value.strip()


def database_sha256(path: Path) -> str:
    return sha256_file(path)

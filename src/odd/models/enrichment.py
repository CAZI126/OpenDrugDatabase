"""Immutable ODD-005 candidate-enrichment evidence and report models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from odd.models.batch import (
    IngestionStatus,
    ParserCompatibilityStatus,
    SelectionStatus,
    VerificationStatus,
)
from odd.models.discovery import HTTPAttemptEvidence


class EvidenceResult(StrEnum):
    """Four-valued result; UNKNOWN is never coerced to a boolean."""

    PROVEN_TRUE = "PROVEN_TRUE"
    PROVEN_FALSE = "PROVEN_FALSE"
    UNKNOWN = "UNKNOWN"
    CONFLICT = "CONFLICT"


class EvidenceType(StrEnum):
    HUMAN_USE = "HUMAN_USE"
    CURRENT = "CURRENT"
    PRESCRIPTION = "PRESCRIPTION"
    SINGLE_ACTIVE_INGREDIENT = "SINGLE_ACTIVE_INGREDIENT"
    EXACT_INGREDIENT_IDENTITY = "EXACT_INGREDIENT_IDENTITY"
    COMBINATION_PRODUCT = "COMBINATION_PRODUCT"
    REPACKAGED_PRODUCT = "REPACKAGED_PRODUCT"
    ARCHIVED = "ARCHIVED"
    SUPPORTED_DOCUMENT_STRUCTURE = "SUPPORTED_DOCUMENT_STRUCTURE"
    SOURCE_IDENTITY_MATCH = "SOURCE_IDENTITY_MATCH"


class EnrichmentTier(StrEnum):
    TIER_0 = "TIER_0"
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"


class EnrichmentCompleteness(StrEnum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    CONFLICT = "CONFLICT"
    SOURCE_DRIFT = "SOURCE_DRIFT"


class EnrichmentRunStatus(StrEnum):
    PLANNED = "PLANNED"
    RUNNING = "RUNNING"
    PARTIAL_BUDGET = "PARTIAL_BUDGET"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_UNRESOLVED_ITEMS = "COMPLETED_WITH_UNRESOLVED_ITEMS"
    FAILED = "FAILED"


class EnrichmentItemStatus(StrEnum):
    PENDING = "PENDING"
    ENRICHING = "ENRICHING"
    ENRICHMENT_COMPLETE = "ENRICHMENT_COMPLETE"
    ENRICHMENT_INCOMPLETE = "ENRICHMENT_INCOMPLETE"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"
    SOURCE_DRIFT = "SOURCE_DRIFT"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class EnrichmentBudget:
    max_requests: int
    max_downloaded_bytes: int
    timeout_seconds: float
    retry_limit: int
    inter_request_delay_seconds: float
    max_response_bytes: int
    max_detail_pages: int
    max_tier2_candidates: int


@dataclass(frozen=True, slots=True)
class EnrichmentPlanItem:
    rank: int
    ingredient_id: str
    ingredient_name: str
    parent_discovery_snapshot_id: str
    candidate_count: int
    unique_set_id_count: int
    tier1_minimum_requests: int
    tier1_maximum_requests: int
    tier2_maximum_candidates: int


@dataclass(frozen=True, slots=True)
class EnrichmentPlan:
    parent_live_batch_run_id: str
    parent_canonical_sha256: str
    items: tuple[EnrichmentPlanItem, ...]
    budget: EnrichmentBudget
    planned_minimum_requests: int
    planned_maximum_requests: int
    planned_maximum_downloaded_bytes: int
    endpoint_templates: tuple[str, ...]
    estimated_minimum_seconds: float


@dataclass(frozen=True, slots=True)
class CandidateDetailPage:
    """One exact, parsed DailyMed packaging-detail page."""

    set_id: str
    observed_source_version: str
    title: str
    published_date: str
    page_number: int
    page_size: int
    request_url: str
    canonical_request: tuple[tuple[str, str], ...]
    final_url: str
    status_code: int
    content_type: str
    retrieved_at: datetime
    etag: str | None
    last_modified: str | None
    raw_body: bytes
    raw_sha256: str
    payload: dict[str, object]
    products: tuple[dict[str, object], ...]
    attempts: tuple[HTTPAttemptEvidence, ...]


@dataclass(frozen=True, slots=True)
class DetailResponseEvidence:
    response_id: str
    enrichment_run_id: str
    execution_id: str
    parent_discovery_snapshot_id: str
    candidate_id: str
    set_id: str
    expected_source_version: str
    observed_source_version: str | None
    tier: EnrichmentTier
    page_number: int
    canonical_request: tuple[tuple[str, str], ...]
    request_url: str
    final_url: str | None
    status_code: int | None
    content_type: str | None
    retrieved_at: datetime
    etag: str | None
    last_modified: str | None
    raw_body: bytes | None
    raw_sha256: str | None
    attempts: tuple[HTTPAttemptEvidence, ...]
    error_category: str | None
    diagnostic: str | None


@dataclass(frozen=True, slots=True)
class EvidenceAssertion:
    assertion_id: str
    canonical_evidence_identity: str
    parent_discovery_snapshot_id: str
    enrichment_run_id: str
    enrichment_snapshot_id: str
    candidate_id: str
    set_id: str
    expected_source_version: str
    observed_source_version: str | None
    evidence_type: EvidenceType
    result: EvidenceResult
    tier: EnrichmentTier
    raw_response_sha256: str | None
    source_url_identity: str
    source_locator: str
    source_field_or_code: str
    extraction_rule_version: str
    extractor_version: str
    diagnostic: str
    retrieved_at: datetime | None
    source_response_sha256s: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EnrichmentDecisionRevision:
    revision_id: str
    enrichment_run_id: str
    enrichment_snapshot_id: str
    parent_decision_id: str
    previous_revision_id: str | None
    rank: int
    ingredient_id: str
    selection_status: SelectionStatus
    selected_candidate_id: str | None
    selected_set_id: str | None
    selected_source_version: str | None
    selection_reason: str
    manual_review_required: bool
    intended_use_scope: str | None = None


@dataclass(frozen=True, slots=True)
class EnrichmentItem:
    enrichment_run_id: str
    rank: int
    ingredient_id: str
    ingredient_name: str
    parent_discovery_run_id: str
    parent_discovery_snapshot_id: str
    parent_decision_id: str
    candidate_total: int
    candidates_excluded_tier0: int
    tier1_attempted: int
    tier1_complete: int
    tier2_attempted: int
    tier2_complete: int
    candidates_proven_eligible: int
    candidates_proven_ineligible: int
    candidates_unknown: int
    candidates_conflict: int
    source_drift_count: int
    enrichment_completeness: EnrichmentCompleteness
    item_status: EnrichmentItemStatus
    selection_status: SelectionStatus
    selected_candidate_id: str | None
    selected_set_id: str | None
    selected_source_version: str | None
    manual_review_reason: str
    request_count: int
    downloaded_bytes: int
    cache_hit_count: int
    retry_count: int
    http_429_count: int
    failure_count: int
    ingestion_status: IngestionStatus
    parser_compatibility: ParserCompatibilityStatus
    verification_status: VerificationStatus
    document_id: str | None
    raw_xml_sha256: str | None
    canonical_artifact_sha256: str | None
    diagnostic_message: str | None


@dataclass(frozen=True, slots=True)
class EnrichmentRun:
    enrichment_run_id: str
    observation_token: str
    parent_live_batch_run_id: str
    parent_canonical_sha256: str
    parent_database_sha256: str
    extractor_version: str
    extraction_rule_version: str
    selection_rule_version: str
    connector_version: str
    parser_version: str
    normalized_schema_version: str
    mapping_version: str
    database_schema_version: str
    target_ranks: tuple[int, ...]
    started_at: datetime
    completed_at: datetime | None
    status: EnrichmentRunStatus
    current_snapshot_id: str | None
    request_count: int
    downloaded_bytes: int
    cache_hit_count: int
    retry_count: int
    http_429_count: int
    failure_count: int
    enrichment_complete_count: int
    selected_count: int
    manual_review_count: int
    enrichment_incomplete_count: int
    source_drift_count: int
    ingested_count: int
    verified_count: int
    canonical_report_sha256: str | None


@dataclass(frozen=True, slots=True)
class EnrichmentReport:
    report_version: str
    run: EnrichmentRun
    items: tuple[EnrichmentItem, ...]
    generated_at: datetime


@dataclass(frozen=True, slots=True)
class EnrichmentArtifactResult:
    report: EnrichmentReport
    canonical_json: bytes
    canonical_sha256: str
    already_stored: bool

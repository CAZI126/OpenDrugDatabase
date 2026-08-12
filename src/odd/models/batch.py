"""Typed utilization, candidate-selection, and ODD-003/ODD-004 batch models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from odd.models.discovery import DiscoveryCompleteness


class IngredientIdentityStatus(StrEnum):
    EXACT_NAME = "EXACT_NAME"
    NORMALIZED_NAME = "NORMALIZED_NAME"
    SYNONYM_USED = "SYNONYM_USED"
    SALT_OR_FORM_VARIANT = "SALT_OR_FORM_VARIANT"
    IDENTITY_AMBIGUOUS = "IDENTITY_AMBIGUOUS"
    UNRESOLVED = "UNRESOLVED"


class CandidateClassification(StrEnum):
    EXACT_SINGLE_INGREDIENT_MATCH = "EXACT_SINGLE_INGREDIENT_MATCH"
    SINGLE_INGREDIENT_NORMALIZED_MATCH = "SINGLE_INGREDIENT_NORMALIZED_MATCH"
    COMBINATION_PRODUCT = "COMBINATION_PRODUCT"
    WRONG_INGREDIENT = "WRONG_INGREDIENT"
    SALT_OR_FORM_VARIANT = "SALT_OR_FORM_VARIANT"
    NON_HUMAN_PRODUCT = "NON_HUMAN_PRODUCT"
    OTC_PRODUCT = "OTC_PRODUCT"
    PRESCRIPTION_PRODUCT = "PRESCRIPTION_PRODUCT"
    REPACKAGED_PRODUCT = "REPACKAGED_PRODUCT"
    ARCHIVED_OR_INACTIVE = "ARCHIVED_OR_INACTIVE"
    MISSING_REQUIRED_METADATA = "MISSING_REQUIRED_METADATA"
    DUPLICATE_CANDIDATE = "DUPLICATE_CANDIDATE"
    UNSUPPORTED_PRODUCT_TYPE = "UNSUPPORTED_PRODUCT_TYPE"
    AMBIGUOUS = "AMBIGUOUS"


class DiscoveryStatus(StrEnum):
    PENDING = "PENDING"
    DISCOVERED = "DISCOVERED"
    NO_CANDIDATE = "NO_CANDIDATE"
    LOOKUP_FAILED = "LOOKUP_FAILED"
    METADATA_INVALID = "METADATA_INVALID"
    DISCOVERY_INCOMPLETE = "DISCOVERY_INCOMPLETE"


class SelectionStatus(StrEnum):
    PENDING = "PENDING"
    SELECTED = "SELECTED"
    NO_CANDIDATE = "NO_CANDIDATE"
    NO_ACCEPTABLE_CANDIDATE = "NO_ACCEPTABLE_CANDIDATE"
    MULTIPLE_EQUIVALENT_CANDIDATES = "MULTIPLE_EQUIVALENT_CANDIDATES"
    AMBIGUOUS_REQUIRES_REVIEW = "AMBIGUOUS_REQUIRES_REVIEW"
    FETCH_FAILED = "FETCH_FAILED"
    METADATA_INVALID = "METADATA_INVALID"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"


class IngestionStatus(StrEnum):
    NOT_SELECTED = "NOT_SELECTED"
    PENDING = "PENDING"
    FETCHED = "FETCHED"
    ALREADY_FETCHED = "ALREADY_FETCHED"
    INGESTED = "INGESTED"
    ALREADY_INGESTED = "ALREADY_INGESTED"
    RAW_FETCH_FAILED = "RAW_FETCH_FAILED"
    RAW_HASH_CONFLICT = "RAW_HASH_CONFLICT"
    PARSER_FAILED = "PARSER_FAILED"
    UNSUPPORTED_STRUCTURE = "UNSUPPORTED_STRUCTURE"
    DATABASE_FAILED = "DATABASE_FAILED"


class VerificationStatus(StrEnum):
    NOT_VERIFIED = "NOT_VERIFIED"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"


class ParserCompatibilityStatus(StrEnum):
    FULLY_PARSED = "FULLY_PARSED"
    PARSED_WITH_UNMAPPED_SECTIONS = "PARSED_WITH_UNMAPPED_SECTIONS"
    PARSED_WITH_UNSUPPORTED_STRUCTURES = "PARSED_WITH_UNSUPPORTED_STRUCTURES"
    PARTIAL_PARSE = "PARTIAL_PARSE"
    PARSER_FAILED = "PARSER_FAILED"
    NOT_INGESTED = "NOT_INGESTED"
    UNSUPPORTED_STRUCTURE = "UNSUPPORTED_STRUCTURE"


class BatchStatus(StrEnum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_UNRESOLVED_ITEMS = "COMPLETED_WITH_UNRESOLVED_ITEMS"
    PARTIAL_FAILURE = "PARTIAL_FAILURE"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class UtilizationEntry:
    utilization_list_id: str
    rank: int
    ingredient_name: str
    normalized_ingredient_name: str
    metric_value: float | None = None
    metric_unit: str | None = None
    source_row_identifier: str | None = None


@dataclass(frozen=True, slots=True)
class UtilizationList:
    utilization_list_id: str
    schema_version: str
    jurisdiction: str
    dataset_name: str
    dataset_version: str
    measurement_year: int
    metric: str
    source_reference: str
    retrieved_at: datetime
    license_or_terms_status: str
    source_status: str
    notes: str
    entries: tuple[UtilizationEntry, ...]


@dataclass(frozen=True, slots=True)
class IngredientIdentity:
    original_ranked_ingredient: str
    normalized_search_string: str
    ingredient_id: str
    synonyms_used: tuple[str, ...]
    salt_or_form_qualifiers: tuple[str, ...]
    identity_status: IngredientIdentityStatus


@dataclass(frozen=True, slots=True)
class CandidateEvidence:
    candidate_id: str
    discovery_run_id: str
    candidate_index: int
    set_id: str | None
    source_version: str | None
    title: str | None
    published_date: str | None
    generic_name: str | None
    brand_name: str | None
    active_ingredients: tuple[str, ...]
    dosage_form: str | None
    route: str | None
    labeler: str | None
    marketing_category: str | None
    product_type: str | None
    source_status: str | None
    source_url: str | None
    raw_metadata: dict[str, Any] = field(compare=True)
    raw_metadata_sha256: str = ""
    classifications: tuple[CandidateClassification, ...] = ()
    accepted_for_selection: bool = False
    rejection_reasons: tuple[str, ...] = ()
    duplicate_of_candidate_id: str | None = None


@dataclass(frozen=True, slots=True)
class CandidateSelection:
    decision_id: str
    discovery_run_id: str
    ingredient_id: str
    selection_rule_version: str
    selection_status: SelectionStatus
    selected_candidate_id: str | None
    selected_set_id: str | None
    selected_source_version: str | None
    selection_reason: str
    applied_rules: tuple[str, ...]
    manual_review_required: bool
    selection_scope: str
    candidates: tuple[CandidateEvidence, ...]

    @property
    def intended_use_scope(self) -> str:
        return self.selection_scope


@dataclass(frozen=True, slots=True)
class ParserCompatibilityResult:
    status: ParserCompatibilityStatus
    source_section_count: int | None
    mapped_section_count: int | None
    unmapped_section_count: int | None
    unsupported_structure_count: int
    empty_section_count: int
    parser_warnings: tuple[str, ...]
    quarantine_reason: str | None = None


@dataclass(frozen=True, slots=True)
class BatchItem:
    batch_run_id: str
    rank: int
    ingredient_id: str
    ingredient_name: str
    discovery_status: DiscoveryStatus
    selection_status: SelectionStatus
    selected_set_id: str | None
    selected_source_version: str | None
    document_id: str | None
    raw_sha256: str | None
    ingestion_status: IngestionStatus
    verification_status: VerificationStatus
    quarantine_record_id: str | None
    error_category: str | None
    diagnostic_message: str | None
    manual_review_required: bool
    parser_compatibility_status: ParserCompatibilityStatus
    source_section_count: int | None
    mapped_section_count: int | None
    unmapped_section_count: int | None
    unsupported_structure_count: int
    empty_section_count: int
    parser_warnings: tuple[str, ...]
    discovery_run_id: str | None = None
    decision_id: str | None = None
    retry_eligible: bool = False
    query_text: str = ""
    candidate_count: int = 0
    selection_reason: str | None = None
    snapshot_id: str | None = None
    metadata_total_candidate_count: int | None = None
    retrieved_candidate_count: int = 0
    eligible_candidate_count: int = 0
    discovery_completeness: DiscoveryCompleteness = DiscoveryCompleteness.UNKNOWN
    evidence_verification_status: VerificationStatus = VerificationStatus.NOT_VERIFIED


@dataclass(frozen=True, slots=True)
class BatchRun:
    batch_run_id: str
    utilization_list_id: str
    selection_rule_version: str
    connector_version: str
    parser_version: str
    schema_version: str
    mapping_version: str
    started_at: datetime
    completed_at: datetime | None
    status: BatchStatus
    requested_count: int
    selected_count: int
    fetched_count: int
    ingested_count: int
    verified_count: int
    quarantined_count: int
    unresolved_count: int
    failed_count: int
    canonical_report_sha256: str | None
    database_schema_version: str = "3"
    observation_mode: str = "LEGACY"
    snapshot_manifest_sha256: str | None = None
    discovery_complete_count: int = 0
    manual_review_count: int = 0
    no_candidate_count: int = 0
    fetch_failure_count: int = 0
    parser_failure_count: int = 0


@dataclass(frozen=True, slots=True)
class BatchReport:
    report_version: str
    batch_run: BatchRun
    utilization_list: UtilizationList
    items: tuple[BatchItem, ...]
    generated_at: datetime


@dataclass(frozen=True, slots=True)
class BatchArtifactResult:
    report: BatchReport
    canonical_json: bytes
    canonical_sha256: str
    already_stored: bool

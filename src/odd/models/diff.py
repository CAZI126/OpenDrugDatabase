"""Typed ODD-002 lineage and temporal-diff models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any


class ChangeCause(StrEnum):
    SOURCE_CHANGED = "SOURCE_CHANGED"
    PARSER_CHANGED = "PARSER_CHANGED"
    SCHEMA_CHANGED = "SCHEMA_CHANGED"
    MAPPING_CHANGED = "MAPPING_CHANGED"
    METADATA_ONLY_CHANGED = "METADATA_ONLY_CHANGED"
    MULTIPLE_CAUSES = "MULTIPLE_CAUSES"
    NO_CHANGE = "NO_CHANGE"
    UNDETERMINED = "UNDETERMINED"


class OrderingStatus(StrEnum):
    SOURCE_VERSION_ORDERED = "SOURCE_VERSION_ORDERED"
    EFFECTIVE_DATE_ORDERED = "EFFECTIVE_DATE_ORDERED"
    PUBLICATION_DATE_ORDERED = "PUBLICATION_DATE_ORDERED"
    INGESTION_ORDER_ONLY = "INGESTION_ORDER_ONLY"
    ORDER_CONFLICT = "ORDER_CONFLICT"
    ORDER_UNDETERMINED = "ORDER_UNDETERMINED"


class SectionMatchMethod(StrEnum):
    SOURCE_SECTION_ID = "SOURCE_SECTION_ID"
    SECTION_CODE = "SECTION_CODE"
    XML_IDENTIFIER = "XML_IDENTIFIER"
    SOURCE_LOCATOR = "SOURCE_LOCATOR"
    HEADING_AND_PARENT = "HEADING_AND_PARENT"
    CONTENT_ASSISTED = "CONTENT_ASSISTED"
    UNMATCHED = "UNMATCHED"


class SectionMatchStatus(StrEnum):
    EXACT = "EXACT"
    HEURISTIC = "HEURISTIC"
    UNMATCHED = "UNMATCHED"


class DiffOperation(StrEnum):
    DOCUMENT_ADDED = "DOCUMENT_ADDED"
    DOCUMENT_REMOVED = "DOCUMENT_REMOVED"
    SECTION_ADDED = "SECTION_ADDED"
    SECTION_REMOVED = "SECTION_REMOVED"
    SECTION_MODIFIED = "SECTION_MODIFIED"
    SECTION_MOVED = "SECTION_MOVED"
    SECTION_RENAMED = "SECTION_RENAMED"
    SECTION_MAPPING_CHANGED = "SECTION_MAPPING_CHANGED"
    DOCUMENT_METADATA_CHANGED = "DOCUMENT_METADATA_CHANGED"
    NO_CHANGE = "NO_CHANGE"


class TextDiffOperation(StrEnum):
    CONTEXT = "CONTEXT"
    ADDITION = "ADDITION"
    DELETION = "DELETION"


@dataclass(frozen=True, slots=True)
class DailyMedHistoryEntry:
    source_version: str
    published_date: date | None
    published_date_text: str
    sequence_index: int


@dataclass(frozen=True, slots=True)
class DailyMedHistory:
    source_document_id: str
    title: str
    entries: tuple[DailyMedHistoryEntry, ...]
    source_url: str
    retrieved_at: datetime
    raw_body: bytes
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class DiffDocumentProvenance:
    authority: str
    provider: str
    jurisdiction: str
    source_document_id: str
    source_version: str
    source_instance_id: str | None
    effective_date: date | None
    publication_date: date | None
    publication_date_source: str | None
    retrieved_at: datetime
    raw_sha256: str
    raw_path: str
    parser_version: str
    schema_version: str
    mapping_version: str


@dataclass(frozen=True, slots=True)
class StoredSection:
    section_id: str
    sequence_index: int
    source_section_code: str | None
    xml_identifier: str | None
    original_heading: str | None
    original_text: str
    section_sha256: str
    source_locator: str
    parent_section_id: str | None
    depth: int
    content_status: str
    structured_content: Any
    normalized_concepts: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StoredDocumentVersion:
    document_id: str
    provenance: DiffDocumentProvenance
    document_type: str
    language: str | None
    title: str
    generic_name: str | None
    brand_names: tuple[str, ...]
    dosage_forms: tuple[str, ...]
    routes: tuple[str, ...]
    active_ingredients: tuple[str, ...]
    normalized_sha256: str
    ingestion_metadata_sha256: str
    sections: tuple[StoredSection, ...]


@dataclass(frozen=True, slots=True)
class VersionOrdering:
    status: OrderingStatus
    ordering_source: str
    confidence_status: str
    predecessor_document_id: str | None
    successor_document_id: str | None
    known_predecessor: bool
    known_successor: bool
    intermediate_versions_possible: bool
    missing_source_versions: tuple[str, ...]
    history_snapshot_id: str | None


@dataclass(frozen=True, slots=True)
class TextDiffChunk:
    operation: TextDiffOperation
    text: str
    old_start: int
    old_end: int
    new_start: int
    new_end: int


@dataclass(frozen=True, slots=True)
class StructuredTextDiff:
    chunks: tuple[TextDiffChunk, ...]
    additions: tuple[str, ...]
    deletions: tuple[str, ...]
    unchanged_context: tuple[str, ...]
    unified_diff: str


@dataclass(frozen=True, slots=True)
class SectionDiff:
    old_section_id: str | None
    new_section_id: str | None
    old_sequence: int | None
    new_sequence: int | None
    old_heading: str | None
    new_heading: str | None
    old_text: str | None
    new_text: str | None
    old_hash: str | None
    new_hash: str | None
    match_method: SectionMatchMethod
    match_status: SectionMatchStatus
    operations: tuple[DiffOperation, ...]
    text_diff: StructuredTextDiff | None
    old_locator: str | None
    new_locator: str | None
    old_normalized_concepts: tuple[str, ...]
    new_normalized_concepts: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DocumentMetadataChange:
    field: str
    old_value: Any
    new_value: Any


@dataclass(frozen=True, slots=True)
class DiffSummary:
    matched_sections: int
    unmatched_sections: int
    sections_added: int
    sections_removed: int
    sections_modified: int
    sections_moved: int
    sections_renamed: int
    section_mappings_changed: int
    unchanged_sections: int
    document_metadata_changes: int


@dataclass(frozen=True, slots=True)
class DocumentDiff:
    diff_id: str
    source_document_id: str
    old_document_id: str | None
    new_document_id: str | None
    old_source_version: str | None
    new_source_version: str | None
    old_raw_sha256: str | None
    new_raw_sha256: str | None
    old_parser_version: str | None
    new_parser_version: str | None
    old_schema_version: str | None
    new_schema_version: str | None
    old_mapping_version: str | None
    new_mapping_version: str | None
    change_cause: ChangeCause
    change_components: tuple[ChangeCause, ...]
    ordering_status: OrderingStatus
    ordering: VersionOrdering
    generated_at: datetime | None
    diff_engine_version: str
    operations: tuple[DiffOperation, ...]
    summary: DiffSummary
    document_metadata_changes: tuple[DocumentMetadataChange, ...]
    old_provenance: DiffDocumentProvenance | None
    new_provenance: DiffDocumentProvenance | None
    section_diffs: tuple[SectionDiff, ...]


@dataclass(frozen=True, slots=True)
class DiffGenerationResult:
    diff: DocumentDiff
    canonical_json: bytes
    canonical_sha256: str
    already_stored: bool


@dataclass(frozen=True, slots=True)
class DiffVerificationCheck:
    name: str
    ok: bool
    message: str


@dataclass(frozen=True, slots=True)
class DiffVerificationResult:
    diff_id: str
    ok: bool
    checks: tuple[DiffVerificationCheck, ...]

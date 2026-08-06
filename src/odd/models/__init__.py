"""Typed ODD source, normalized, lineage, and temporal-diff data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any


class SectionContentStatus(StrEnum):
    PRESENT = "present"
    PRESENT_EMPTY = "present_empty"
    TEXT_ELEMENT_ABSENT = "text_element_absent"


class ConceptStatus(StrEnum):
    PRESENT = "present"
    PRESENT_EMPTY = "present_empty"
    ABSENT = "absent"


@dataclass(frozen=True, slots=True)
class SourceIdentity:
    authority: str
    provider: str
    jurisdiction: str
    source_document_id: str
    source_version: str
    source_url: str | None
    retrieved_at: datetime
    raw_sha256: str


@dataclass(frozen=True, slots=True)
class RegulatoryDocument:
    document_id: str
    source_identity: SourceIdentity
    source_instance_id: str | None
    document_type: str
    language: str | None
    effective_date: date | None
    title: str
    generic_name: str | None
    brand_names: tuple[str, ...]
    dosage_forms: tuple[str, ...]
    routes: tuple[str, ...]
    active_ingredients: tuple[str, ...]
    parser_version: str
    schema_version: str
    mapping_version: str


@dataclass(frozen=True, slots=True)
class StructuredNode:
    """Traceable representation of an XML node below a section text element."""

    tag: str
    locator: str
    attributes: tuple[tuple[str, str], ...] = ()
    text: str | None = None
    tail: str | None = None
    children: tuple[StructuredNode, ...] = ()


@dataclass(frozen=True, slots=True)
class SourceSection:
    section_id: str
    document_id: str
    source_section_code: str | None
    original_heading: str | None
    original_text: str
    sequence_index: int
    section_sha256: str
    source_locator: str
    parent_section_id: str | None
    depth: int
    content_status: SectionContentStatus
    structured_content: StructuredNode | None


@dataclass(frozen=True, slots=True)
class SemanticMapping:
    section_id: str
    normalized_concept: str
    mapping_method: str
    mapping_version: str
    confidence: float | None
    deterministic_status: str


@dataclass(frozen=True, slots=True)
class Product:
    product_id: str
    brand_name: str | None
    dosage_form: str | None
    route: str | None
    sequence_index: int


@dataclass(frozen=True, slots=True)
class ConceptPresence:
    normalized_concept: str
    status: ConceptStatus
    section_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class NormalizedDocument:
    document: RegulatoryDocument
    products: tuple[Product, ...]
    sections: tuple[SourceSection, ...]
    semantic_mappings: tuple[SemanticMapping, ...]
    concept_statuses: tuple[ConceptPresence, ...]


@dataclass(frozen=True, slots=True)
class DailyMedCandidate:
    set_id: str
    source_version: str
    title: str
    published_date: str
    metadata: dict[str, Any] = field(default_factory=dict, compare=True)


@dataclass(frozen=True, slots=True)
class CandidateLookup:
    candidates: tuple[DailyMedCandidate, ...]
    source_url: str
    retrieved_at: datetime
    raw_body: bytes
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class DownloadedSource:
    set_id: str
    source_version: str
    source_url: str
    retrieved_at: datetime
    body: bytes
    status_code: int
    headers: dict[str, str]
    container_body: bytes | None = None
    container_format: str | None = None
    container_member: str | None = None


@dataclass(frozen=True, slots=True)
class SelectionDecision:
    selected: DailyMedCandidate
    ordered_candidates: tuple[DailyMedCandidate, ...]
    rule_version: str
    rule_description: str
    reason: str
    ambiguity_exposed: bool


@dataclass(frozen=True, slots=True)
class RawDocument:
    identity: SourceIdentity
    label_path: Path
    metadata_path: Path
    metadata: dict[str, Any]
    already_stored: bool
    container_path: Path | None = None


@dataclass(frozen=True, slots=True)
class IngestionOutcome:
    document_id: str
    source_document_id: str
    source_version: str
    raw_sha256: str
    source_section_count: int
    mapped_section_count: int
    unmapped_section_count: int
    status: str
    ingestion_run_id: int


@dataclass(frozen=True, slots=True)
class VerificationCheck:
    name: str
    ok: bool
    message: str


@dataclass(frozen=True, slots=True)
class VerificationResult:
    document_id: str
    ok: bool
    checks: tuple[VerificationCheck, ...]


from odd.models.diff import (  # noqa: E402  (base models must exist before re-export)
    ChangeCause,
    DailyMedHistory,
    DailyMedHistoryEntry,
    DiffDocumentProvenance,
    DiffGenerationResult,
    DiffOperation,
    DiffSummary,
    DiffVerificationCheck,
    DiffVerificationResult,
    DocumentDiff,
    DocumentMetadataChange,
    OrderingStatus,
    SectionDiff,
    SectionMatchMethod,
    SectionMatchStatus,
    StoredDocumentVersion,
    StoredSection,
    StructuredTextDiff,
    TextDiffChunk,
    TextDiffOperation,
    VersionOrdering,
)

__all__ = [
    "CandidateLookup",
    "ChangeCause",
    "ConceptPresence",
    "ConceptStatus",
    "DailyMedCandidate",
    "DailyMedHistory",
    "DailyMedHistoryEntry",
    "DiffDocumentProvenance",
    "DiffGenerationResult",
    "DiffOperation",
    "DiffSummary",
    "DiffVerificationCheck",
    "DiffVerificationResult",
    "DocumentDiff",
    "DocumentMetadataChange",
    "DownloadedSource",
    "IngestionOutcome",
    "NormalizedDocument",
    "OrderingStatus",
    "Product",
    "RawDocument",
    "RegulatoryDocument",
    "SectionContentStatus",
    "SectionDiff",
    "SectionMatchMethod",
    "SectionMatchStatus",
    "SelectionDecision",
    "SemanticMapping",
    "SourceIdentity",
    "SourceSection",
    "StoredDocumentVersion",
    "StoredSection",
    "StructuredNode",
    "StructuredTextDiff",
    "TextDiffChunk",
    "TextDiffOperation",
    "VerificationCheck",
    "VerificationResult",
    "VersionOrdering",
]

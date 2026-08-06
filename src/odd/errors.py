"""Explicit ODD ingestion, lineage, and temporal-diff failure categories."""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class ErrorCategory(StrEnum):
    NETWORK_FAILURE = "network_failure"
    AMBIGUOUS_SOURCE_SELECTION = "ambiguous_source_selection"
    SOURCE_NOT_FOUND = "source_not_found"
    MALFORMED_METADATA = "malformed_metadata"
    MALFORMED_XML = "malformed_xml"
    MALFORMED_ARCHIVE = "malformed_archive"
    UNSUPPORTED_DOCUMENT_STRUCTURE = "unsupported_document_structure"
    RAW_HASH_CONFLICT = "raw_hash_conflict"
    DUPLICATE_DOCUMENT = "duplicate_document"
    PARSER_FAILURE = "parser_failure"
    DATABASE_FAILURE = "database_failure"
    PROVENANCE_VALIDATION_FAILURE = "provenance_validation_failure"
    LINEAGE_MISMATCH = "lineage_mismatch"
    AMBIGUOUS_DOCUMENT_VERSION = "ambiguous_document_version"
    DIFF_ARTIFACT_CONFLICT = "diff_artifact_conflict"
    DIFF_VERIFICATION_FAILURE = "diff_verification_failure"


class ODDError(Exception):
    """Base exception carrying a stable, machine-readable category."""

    category = ErrorCategory.PARSER_FAILURE

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def as_dict(self) -> dict[str, Any]:
        return {
            "category": self.category.value,
            "details": self.details,
            "message": self.message,
        }


class NetworkFailure(ODDError):
    category = ErrorCategory.NETWORK_FAILURE


class AmbiguousSourceSelection(ODDError):
    category = ErrorCategory.AMBIGUOUS_SOURCE_SELECTION


class SourceNotFound(ODDError):
    category = ErrorCategory.SOURCE_NOT_FOUND


class MalformedMetadata(ODDError):
    category = ErrorCategory.MALFORMED_METADATA


class MalformedXML(ODDError):
    category = ErrorCategory.MALFORMED_XML


class MalformedArchive(ODDError):
    category = ErrorCategory.MALFORMED_ARCHIVE


class UnsupportedDocumentStructure(ODDError):
    category = ErrorCategory.UNSUPPORTED_DOCUMENT_STRUCTURE


class RawHashConflict(ODDError):
    category = ErrorCategory.RAW_HASH_CONFLICT


class DuplicateDocument(ODDError):
    category = ErrorCategory.DUPLICATE_DOCUMENT


class ParserFailure(ODDError):
    category = ErrorCategory.PARSER_FAILURE


class DatabaseFailure(ODDError):
    category = ErrorCategory.DATABASE_FAILURE


class ProvenanceValidationFailure(ODDError):
    category = ErrorCategory.PROVENANCE_VALIDATION_FAILURE


class LineageMismatch(ODDError):
    category = ErrorCategory.LINEAGE_MISMATCH


class AmbiguousDocumentVersion(ODDError):
    category = ErrorCategory.AMBIGUOUS_DOCUMENT_VERSION


class DiffArtifactConflict(ODDError):
    category = ErrorCategory.DIFF_ARTIFACT_CONFLICT


class DiffVerificationFailure(ODDError):
    category = ErrorCategory.DIFF_VERIFICATION_FAILURE

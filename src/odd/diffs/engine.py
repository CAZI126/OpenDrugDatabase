"""Deterministic section-level temporal diff engine."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from odd.constants import DIFF_ENGINE_VERSION
from odd.diffs.classification import change_components, classify_change_cause
from odd.diffs.matching import SectionMatch, match_sections
from odd.diffs.text import build_text_diff
from odd.errors import LineageMismatch
from odd.models import (
    DiffOperation,
    DiffSummary,
    DocumentDiff,
    DocumentMetadataChange,
    SectionDiff,
    SectionMatchMethod,
    SectionMatchStatus,
    StoredDocumentVersion,
    StoredSection,
    VersionOrdering,
)
from odd.provenance.canonical import canonical_json_bytes
from odd.provenance.identifiers import document_diff_id

_OPERATION_ORDER = {item: index for index, item in enumerate(DiffOperation)}


class DiffEngine:
    """Compare normalized source-preserving snapshots without clinical interpretation."""

    version = DIFF_ENGINE_VERSION

    def generate(
        self,
        old: StoredDocumentVersion | None,
        new: StoredDocumentVersion | None,
        *,
        ordering: VersionOrdering,
        generated_at: datetime,
    ) -> DocumentDiff:
        if old is None and new is None:
            raise ValueError("at least one diff document must be present")
        present = old if old is not None else new
        assert present is not None
        source_document_id = present.provenance.source_document_id
        if (
            old is not None
            and new is not None
            and old.provenance.source_document_id.casefold()
            != new.provenance.source_document_id.casefold()
        ):
            raise LineageMismatch(
                "temporal diff documents do not share a DailyMed source lineage",
                details={
                    "old_source_document_id": old.provenance.source_document_id,
                    "new_source_document_id": new.provenance.source_document_id,
                },
            )

        metadata_changes = _metadata_changes(old, new)
        matches = _document_matches(old, new)
        movement = _movement_map(matches)
        section_diffs = tuple(
            _section_diff(match, moved=movement.get(_match_identity(match), False))
            for match in matches
        )
        document_operations: list[DiffOperation] = []
        if old is None:
            document_operations.append(DiffOperation.DOCUMENT_ADDED)
        if new is None:
            document_operations.append(DiffOperation.DOCUMENT_REMOVED)
        if metadata_changes:
            document_operations.append(DiffOperation.DOCUMENT_METADATA_CHANGED)
        for section in section_diffs:
            document_operations.extend(
                item for item in section.operations if item != DiffOperation.NO_CHANGE
            )
        operations = _ordered_operations(document_operations)
        if not operations:
            operations = (DiffOperation.NO_CHANGE,)

        return DocumentDiff(
            diff_id=document_diff_id(
                old.document_id if old else None,
                new.document_id if new else None,
                self.version,
            ),
            source_document_id=source_document_id,
            old_document_id=old.document_id if old else None,
            new_document_id=new.document_id if new else None,
            old_source_version=old.provenance.source_version if old else None,
            new_source_version=new.provenance.source_version if new else None,
            old_raw_sha256=old.provenance.raw_sha256 if old else None,
            new_raw_sha256=new.provenance.raw_sha256 if new else None,
            old_parser_version=old.provenance.parser_version if old else None,
            new_parser_version=new.provenance.parser_version if new else None,
            old_schema_version=old.provenance.schema_version if old else None,
            new_schema_version=new.provenance.schema_version if new else None,
            old_mapping_version=old.provenance.mapping_version if old else None,
            new_mapping_version=new.provenance.mapping_version if new else None,
            change_cause=classify_change_cause(old, new),
            change_components=change_components(old, new),
            ordering_status=ordering.status,
            ordering=ordering,
            generated_at=generated_at,
            diff_engine_version=self.version,
            operations=operations,
            summary=_summary(section_diffs, metadata_changes),
            document_metadata_changes=metadata_changes,
            old_provenance=old.provenance if old else None,
            new_provenance=new.provenance if new else None,
            section_diffs=section_diffs,
        )


def _document_matches(
    old: StoredDocumentVersion | None,
    new: StoredDocumentVersion | None,
) -> tuple[SectionMatch, ...]:
    if old is None:
        assert new is not None
        return tuple(
            SectionMatch(None, item, SectionMatchMethod.UNMATCHED, SectionMatchStatus.UNMATCHED)
            for item in new.sections
        )
    if new is None:
        return tuple(
            SectionMatch(item, None, SectionMatchMethod.UNMATCHED, SectionMatchStatus.UNMATCHED)
            for item in old.sections
        )
    return match_sections(old.sections, new.sections)


def _section_diff(match: SectionMatch, *, moved: bool) -> SectionDiff:
    old = match.old
    new = match.new
    operations: list[DiffOperation] = []
    text_diff = None
    if old is None:
        assert new is not None
        operations.append(DiffOperation.SECTION_ADDED)
        text_diff = build_text_diff(
            "", new.original_text, old_label="/dev/null", new_label=new.source_locator
        )
    elif new is None:
        operations.append(DiffOperation.SECTION_REMOVED)
        text_diff = build_text_diff(
            old.original_text, "", old_label=old.source_locator, new_label="/dev/null"
        )
    else:
        if _content_changed(old, new):
            operations.append(DiffOperation.SECTION_MODIFIED)
            text_diff = build_text_diff(
                old.original_text,
                new.original_text,
                old_label=old.source_locator,
                new_label=new.source_locator,
            )
        if moved:
            operations.append(DiffOperation.SECTION_MOVED)
        if old.original_heading != new.original_heading:
            operations.append(DiffOperation.SECTION_RENAMED)
        if old.normalized_concepts != new.normalized_concepts:
            operations.append(DiffOperation.SECTION_MAPPING_CHANGED)
    if not operations:
        operations.append(DiffOperation.NO_CHANGE)
    return SectionDiff(
        old_section_id=old.section_id if old else None,
        new_section_id=new.section_id if new else None,
        old_sequence=old.sequence_index if old else None,
        new_sequence=new.sequence_index if new else None,
        old_heading=old.original_heading if old else None,
        new_heading=new.original_heading if new else None,
        old_text=old.original_text if old else None,
        new_text=new.original_text if new else None,
        old_hash=old.section_sha256 if old else None,
        new_hash=new.section_sha256 if new else None,
        match_method=match.method,
        match_status=match.status,
        operations=_ordered_operations(operations),
        text_diff=text_diff,
        old_locator=old.source_locator if old else None,
        new_locator=new.source_locator if new else None,
        old_normalized_concepts=old.normalized_concepts if old else (),
        new_normalized_concepts=new.normalized_concepts if new else (),
    )


def _content_changed(old: StoredSection, new: StoredSection) -> bool:
    return (
        old.original_text != new.original_text
        or old.source_section_code != new.source_section_code
        or old.content_status != new.content_status
        or canonical_json_bytes(_structured_comparison(old.structured_content))
        != canonical_json_bytes(_structured_comparison(new.structured_content))
    )


def _structured_comparison(value: Any) -> Any:
    """Compare structured source content without treating trace locators as text edits."""

    if isinstance(value, dict):
        return {
            str(key): _structured_comparison(item)
            for key, item in value.items()
            if key != "locator"
        }
    if isinstance(value, list):
        return [_structured_comparison(item) for item in value]
    return value


def _movement_map(matches: Sequence[SectionMatch]) -> dict[str, bool]:
    paired: list[tuple[SectionMatch, StoredSection, StoredSection]] = []
    for item in matches:
        if item.old is not None and item.new is not None:
            paired.append((item, item.old, item.new))
    old_to_new = {old.section_id: new.section_id for _item, old, new in paired}
    result: dict[str, bool] = {}
    for item, old, new in paired:
        parent_moved = old_to_new.get(old.parent_section_id or "") != (
            new.parent_section_id or None
        )
        if old.parent_section_id is None and new.parent_section_id is None:
            parent_moved = False
        old_siblings = sorted(
            (
                candidate
                for candidate in paired
                if candidate[1].parent_section_id == old.parent_section_id
                and candidate[2].parent_section_id == new.parent_section_id
            ),
            key=lambda candidate: candidate[1].sequence_index,
        )
        new_siblings = sorted(old_siblings, key=lambda candidate: candidate[2].sequence_index)
        old_rank = [candidate[1].section_id for candidate in old_siblings].index(
            old.section_id
        )
        new_rank = [candidate[1].section_id for candidate in new_siblings].index(
            old.section_id
        )
        result[_match_identity(item)] = parent_moved or old_rank != new_rank
    return result


def _match_identity(match: SectionMatch) -> str:
    return "|".join(
        (
            match.old.section_id if match.old else "",
            match.new.section_id if match.new else "",
        )
    )


def _metadata_changes(
    old: StoredDocumentVersion | None,
    new: StoredDocumentVersion | None,
) -> tuple[DocumentMetadataChange, ...]:
    if old is None or new is None:
        return ()
    fields: tuple[tuple[str, Any, Any], ...] = (
        (
            "source_instance_id",
            old.provenance.source_instance_id,
            new.provenance.source_instance_id,
        ),
        ("effective_date", old.provenance.effective_date, new.provenance.effective_date),
        ("document_type", old.document_type, new.document_type),
        ("language", old.language, new.language),
        ("title", old.title, new.title),
        ("generic_name", old.generic_name, new.generic_name),
        ("brand_names", old.brand_names, new.brand_names),
        ("dosage_forms", old.dosage_forms, new.dosage_forms),
        ("routes", old.routes, new.routes),
        ("active_ingredients", old.active_ingredients, new.active_ingredients),
    )
    return tuple(
        DocumentMetadataChange(field=name, old_value=old_value, new_value=new_value)
        for name, old_value, new_value in fields
        if old_value != new_value
    )


def _summary(
    section_diffs: Sequence[SectionDiff],
    metadata_changes: Sequence[DocumentMetadataChange],
) -> DiffSummary:
    def count(operation: DiffOperation) -> int:
        return sum(operation in item.operations for item in section_diffs)

    return DiffSummary(
        matched_sections=sum(
            item.match_status != SectionMatchStatus.UNMATCHED for item in section_diffs
        ),
        unmatched_sections=sum(
            item.match_status == SectionMatchStatus.UNMATCHED for item in section_diffs
        ),
        sections_added=count(DiffOperation.SECTION_ADDED),
        sections_removed=count(DiffOperation.SECTION_REMOVED),
        sections_modified=count(DiffOperation.SECTION_MODIFIED),
        sections_moved=count(DiffOperation.SECTION_MOVED),
        sections_renamed=count(DiffOperation.SECTION_RENAMED),
        section_mappings_changed=count(DiffOperation.SECTION_MAPPING_CHANGED),
        unchanged_sections=count(DiffOperation.NO_CHANGE),
        document_metadata_changes=len(metadata_changes),
    )


def _ordered_operations(values: Sequence[DiffOperation]) -> tuple[DiffOperation, ...]:
    return tuple(sorted(set(values), key=_OPERATION_ORDER.__getitem__))

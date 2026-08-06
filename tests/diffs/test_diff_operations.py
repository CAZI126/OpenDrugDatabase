from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime

from odd.diffs.engine import DiffEngine
from odd.models import (
    ChangeCause,
    DiffDocumentProvenance,
    DiffOperation,
    StoredDocumentVersion,
    StoredSection,
)
from odd.versioning import determine_version_order

NOW = datetime(2025, 1, 1, tzinfo=UTC)


def _section(
    identifier: str,
    sequence: int,
    *,
    xml_identifier: str,
    heading: str,
    text: str,
    concepts: tuple[str, ...] = (),
) -> StoredSection:
    return StoredSection(
        section_id=identifier,
        sequence_index=sequence,
        source_section_code=None,
        xml_identifier=xml_identifier,
        original_heading=heading,
        original_text=text,
        section_sha256=identifier.ljust(64, "0")[:64],
        source_locator=f"/document[1]/section[{sequence + 1}]",
        parent_section_id=None,
        depth=0,
        content_status="present",
        structured_content={"tag": "text", "locator": f"/text[{sequence + 1}]", "text": text},
        normalized_concepts=concepts,
    )


def _document(
    identifier: str,
    version: str,
    sections: tuple[StoredSection, ...],
    *,
    raw: str,
    mapping_version: str = "mapping/1",
    title: str = "Title",
) -> StoredDocumentVersion:
    provenance = DiffDocumentProvenance(
        authority="FDA",
        provider="DailyMed",
        jurisdiction="United States",
        source_document_id="set-id",
        source_version=version,
        source_instance_id=identifier,
        effective_date=date(2025, 1, int(version)) if version.isdecimal() else None,
        publication_date=None,
        publication_date_source=None,
        retrieved_at=NOW,
        raw_sha256=raw * 64,
        raw_path=f"{version}.xml",
        parser_version="parser/1",
        schema_version="schema/1",
        mapping_version=mapping_version,
    )
    return StoredDocumentVersion(
        document_id=identifier,
        provenance=provenance,
        document_type="LABEL",
        language="en-US",
        title=title,
        generic_name="apixaban",
        brand_names=("ELIQUIS",),
        dosage_forms=(),
        routes=(),
        active_ingredients=("APIXABAN",),
        normalized_sha256=identifier.ljust(64, "0")[:64],
        ingestion_metadata_sha256="m" * 64,
        sections=sections,
    )


def _diff(old: StoredDocumentVersion | None, new: StoredDocumentVersion | None):
    ordering = determine_version_order(old, new)
    return DiffEngine().generate(old, new, ordering=ordering, generated_at=NOW)


def test_document_addition_and_removal_operations_are_supported() -> None:
    document = _document(
        "new", "1", (_section("s", 0, xml_identifier="x", heading="H", text="T"),), raw="a"
    )
    added = _diff(None, document)
    removed = _diff(document, None)

    assert DiffOperation.DOCUMENT_ADDED in added.operations
    assert added.section_diffs[0].operations == (DiffOperation.SECTION_ADDED,)
    assert DiffOperation.DOCUMENT_REMOVED in removed.operations
    assert removed.section_diffs[0].operations == (DiffOperation.SECTION_REMOVED,)


def test_stable_sections_reordered_within_parent_are_moves_not_delete_add() -> None:
    old = _document(
        "old",
        "1",
        (
            _section("old-a", 0, xml_identifier="a", heading="A", text="same a"),
            _section("old-b", 1, xml_identifier="b", heading="B", text="same b"),
        ),
        raw="a",
    )
    new = _document(
        "new",
        "2",
        (
            _section("new-b", 0, xml_identifier="b", heading="B", text="same b"),
            _section("new-a", 1, xml_identifier="a", heading="A", text="same a"),
        ),
        raw="b",
    )
    result = _diff(old, new)

    assert result.summary.sections_moved == 2
    assert result.summary.sections_added == 0
    assert result.summary.sections_removed == 0


def test_one_section_can_be_modified_moved_renamed_and_remapped() -> None:
    old = _document(
        "old",
        "1",
        (
            _section(
                "old-x",
                0,
                xml_identifier="x",
                heading="Old",
                text="old text",
                concepts=("warnings",),
            ),
            _section("old-y", 1, xml_identifier="y", heading="Y", text="y"),
        ),
        raw="a",
    )
    new = _document(
        "new",
        "2",
        (
            _section("new-y", 0, xml_identifier="y", heading="Y", text="y"),
            _section(
                "new-x",
                1,
                xml_identifier="x",
                heading="New",
                text="new text",
                concepts=("interactions",),
            ),
        ),
        raw="b",
    )
    result = _diff(old, new)
    changed = next(item for item in result.section_diffs if item.old_section_id == "old-x")

    assert {
        DiffOperation.SECTION_MODIFIED,
        DiffOperation.SECTION_MOVED,
        DiffOperation.SECTION_RENAMED,
        DiffOperation.SECTION_MAPPING_CHANGED,
    } <= set(changed.operations)


def test_mapping_only_change_is_not_presented_as_a_regulatory_update() -> None:
    old_section = _section(
        "old-section", 0, xml_identifier="x", heading="Same", text="same", concepts=("old",)
    )
    new_section = replace(old_section, section_id="new-section", normalized_concepts=("new",))
    old = _document("old", "1", (old_section,), raw="a", mapping_version="mapping/1")
    new = _document("new", "1", (new_section,), raw="a", mapping_version="mapping/2")
    result = _diff(old, new)

    assert result.change_cause == ChangeCause.MAPPING_CHANGED
    assert ChangeCause.SOURCE_CHANGED not in result.change_components
    assert result.section_diffs[0].operations == (DiffOperation.SECTION_MAPPING_CHANGED,)


def test_document_metadata_change_is_structured() -> None:
    old = _document("old", "1", (), raw="a", title="Old title")
    new = replace(old, document_id="new", title="New title")
    result = _diff(old, new)

    assert DiffOperation.DOCUMENT_METADATA_CHANGED in result.operations
    assert result.document_metadata_changes[0].field == "title"


def test_identical_document_diff_is_no_change() -> None:
    document = _document("same", "1", (), raw="a")
    result = _diff(document, document)
    assert result.operations == (DiffOperation.NO_CHANGE,)
    assert result.change_cause == ChangeCause.NO_CHANGE

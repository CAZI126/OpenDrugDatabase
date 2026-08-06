from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta

import pytest

from odd.models import (
    ChangeCause,
    DiffGenerationResult,
    DiffOperation,
    OrderingStatus,
    SectionMatchMethod,
)
from odd.provenance.canonical import canonical_diff_json_bytes
from odd.versioning import determine_version_order
from tests.odd002_support import (
    SET_ID,
    V29_DOCUMENT_ID,
    V29_SHA256,
    V30_DOCUMENT_ID,
    V30_SHA256,
    temporal_service,
)


@pytest.fixture(scope="module")
def genuine_diff(tmp_path_factory: pytest.TempPathFactory):
    root = tmp_path_factory.mktemp("genuine-temporal-diff")
    application, old_id, new_id = temporal_service(root)
    result = application.diff_documents(old_id, new_id)
    return application, old_id, new_id, result


def test_two_genuine_versions_retain_distinct_source_identity(genuine_diff: tuple) -> None:
    application, old_id, new_id, _result = genuine_diff
    old = application.repository.get_stored_document(old_id)
    new = application.repository.get_stored_document(new_id)

    assert (old_id, new_id) == (V29_DOCUMENT_ID, V30_DOCUMENT_ID)
    assert old.provenance.source_document_id == new.provenance.source_document_id == SET_ID
    assert (old.provenance.source_version, new.provenance.source_version) == ("29", "30")
    assert (old.provenance.raw_sha256, new.provenance.raw_sha256) == (
        V29_SHA256,
        V30_SHA256,
    )
    assert (len(old.sections), len(new.sections)) == (93, 88)


def test_genuine_diff_is_only_a_regulatory_source_change(genuine_diff: tuple) -> None:
    _application, _old_id, _new_id, result = genuine_diff
    assert isinstance(result, DiffGenerationResult)
    assert result.diff.change_cause == ChangeCause.SOURCE_CHANGED
    assert result.diff.change_components == (ChangeCause.SOURCE_CHANGED,)
    assert result.diff.old_parser_version == result.diff.new_parser_version
    assert result.diff.old_schema_version == result.diff.new_schema_version
    assert result.diff.old_mapping_version == result.diff.new_mapping_version


def test_official_history_proves_v29_and_v30_are_adjacent(genuine_diff: tuple) -> None:
    _application, _old_id, _new_id, result = genuine_diff
    ordering = result.diff.ordering

    assert ordering.status == OrderingStatus.SOURCE_VERSION_ORDERED
    assert ordering.ordering_source == "dailymed_history"
    assert ordering.known_predecessor is True
    assert ordering.known_successor is True
    assert ordering.intermediate_versions_possible is False
    assert ordering.missing_source_versions == ()
    assert ordering.history_snapshot_id is not None


def test_genuine_section_summary_is_reproducibly_pinned(genuine_diff: tuple) -> None:
    _application, _old_id, _new_id, result = genuine_diff
    summary = result.diff.summary

    assert summary.matched_sections == 76
    assert summary.unmatched_sections == 29
    assert summary.sections_added == 12
    assert summary.sections_removed == 17
    assert summary.sections_modified == 37
    assert summary.sections_moved == 7
    assert summary.sections_renamed == 8
    assert summary.section_mappings_changed == 3
    assert summary.unchanged_sections == 33


def test_genuine_diff_records_match_strength_and_overlapping_operations(
    genuine_diff: tuple,
) -> None:
    _application, _old_id, _new_id, result = genuine_diff
    methods = {item.match_method for item in result.diff.section_diffs}
    operations = {operation for item in result.diff.section_diffs for operation in item.operations}

    assert SectionMatchMethod.XML_IDENTIFIER in methods
    assert SectionMatchMethod.SECTION_CODE in methods
    assert SectionMatchMethod.HEADING_AND_PARENT in methods
    assert SectionMatchMethod.CONTENT_ASSISTED in methods
    assert {
        DiffOperation.SECTION_ADDED,
        DiffOperation.SECTION_REMOVED,
        DiffOperation.SECTION_MODIFIED,
        DiffOperation.SECTION_MOVED,
        DiffOperation.SECTION_RENAMED,
        DiffOperation.SECTION_MAPPING_CHANGED,
    } <= operations
    assert any(len(item.operations) > 1 for item in result.diff.section_diffs)


def test_modified_sections_retain_both_source_texts_hashes_and_locators(
    genuine_diff: tuple,
) -> None:
    _application, _old_id, _new_id, result = genuine_diff
    modified = next(
        item
        for item in result.diff.section_diffs
        if DiffOperation.SECTION_MODIFIED in item.operations and item.text_diff is not None
    )

    assert modified.old_text
    assert modified.new_text
    assert modified.old_hash and len(modified.old_hash) == 64
    assert modified.new_hash and len(modified.new_hash) == 64
    assert modified.old_locator and modified.old_locator.startswith("/document[1]")
    assert modified.new_locator and modified.new_locator.startswith("/document[1]")
    assert modified.text_diff.chunks


def test_canonical_diff_is_timestamp_independent_and_idempotent(genuine_diff: tuple) -> None:
    application, old_id, new_id, result = genuine_diff
    old = application.repository.get_stored_document(old_id)
    new = application.repository.get_stored_document(new_id)
    lineage_id = application.repository.get_lineage_id_for_document(old_id)
    snapshot_id, entries = application.repository.get_history_entries(lineage_id)
    ordering = determine_version_order(
        old, new, history_entries=entries, history_snapshot_id=snapshot_id
    )
    later = application.diff_engine.generate(
        old,
        new,
        ordering=ordering,
        generated_at=result.diff.generated_at + timedelta(days=30),
    )
    relocated = application.diff_engine.generate(
        replace(
            old,
            provenance=replace(
                old.provenance,
                raw_path="D:/another-root/29/label.xml",
                retrieved_at=old.provenance.retrieved_at + timedelta(days=1),
            ),
        ),
        replace(
            new,
            provenance=replace(
                new.provenance,
                raw_path="D:/another-root/30/label.xml",
                retrieved_at=new.provenance.retrieved_at + timedelta(days=1),
            ),
        ),
        ordering=ordering,
        generated_at=result.diff.generated_at + timedelta(days=60),
    )
    repeated = application.diff_documents(old_id, new_id)

    assert canonical_diff_json_bytes(later) == result.canonical_json
    assert canonical_diff_json_bytes(relocated) == result.canonical_json
    assert repeated.canonical_json == result.canonical_json
    assert repeated.canonical_sha256 == result.canonical_sha256
    assert repeated.already_stored is True
    canonical_payload = json.loads(result.canonical_json)
    assert canonical_payload["generated_at"] is None
    assert canonical_payload["old_provenance"]["retrieved_at"] is None
    assert canonical_payload["old_provenance"]["raw_path"].startswith("dailymed/")


def test_diff_artifact_generation_never_changes_source_rows(genuine_diff: tuple) -> None:
    application, old_id, new_id, _result = genuine_diff
    before = {
        "source_documents": application.repository.table_count("source_documents"),
        "regulatory_documents": application.repository.table_count("regulatory_documents"),
        "source_sections": application.repository.table_count("source_sections"),
    }
    application.diff_documents(old_id, new_id)
    after = {
        "source_documents": application.repository.table_count("source_documents"),
        "regulatory_documents": application.repository.table_count("regulatory_documents"),
        "source_sections": application.repository.table_count("source_sections"),
    }

    assert after == before


def test_canonical_diff_hash_is_pinned_for_reviewed_genuine_fixtures(
    genuine_diff: tuple,
) -> None:
    _application, _old_id, _new_id, result = genuine_diff
    assert result.diff.diff_id == "13b99529-0bf8-54f8-a5e7-c7d0bcc3847f"
    assert (
        result.canonical_sha256
        == "89b1c4eb5ad64afbbc6a8709b904cdc2271b59405da9573854fb0865a8d1ca76"
    )

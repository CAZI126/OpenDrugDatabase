from __future__ import annotations

import sqlite3
from dataclasses import replace

import pytest

from odd.errors import DatabaseFailure, DiffArtifactConflict
from tests.odd002_support import temporal_service
from tests.odd_support import fetched_service


@pytest.fixture(scope="module")
def stored_diff(tmp_path_factory: pytest.TempPathFactory):
    root = tmp_path_factory.mktemp("temporal-storage")
    application, old_id, new_id = temporal_service(root)
    result = application.diff_documents(old_id, new_id)
    return application, old_id, new_id, result


def test_schema_migration_two_creates_lineage_and_diff_tables(stored_diff: tuple) -> None:
    application, _old_id, _new_id, _result = stored_diff
    with sqlite3.connect(application.repository.path) as connection:
        versions = {row[0] for row in connection.execute("SELECT version FROM schema_migrations")}
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

    assert versions == {"1", "2", "3", "4", "5"}
    assert {
        "document_lineages",
        "lineage_source_documents",
        "lineage_history_snapshots",
        "lineage_history_entries",
        "document_version_edges",
        "document_diffs",
        "section_diffs",
    } <= tables


def test_migration_initialization_is_idempotent_and_preserves_odd001_rows(
    stored_diff: tuple,
) -> None:
    application, _old_id, _new_id, _result = stored_diff
    before = {
        table: application.repository.table_count(table)
        for table in ("source_documents", "regulatory_documents", "source_sections")
    }
    application.repository.initialize_schema()
    after = {
        table: application.repository.table_count(table)
        for table in ("source_documents", "regulatory_documents", "source_sections")
    }
    assert after == before


def test_migration_from_schema_one_backfills_lineage_without_changing_odd001_data(
    tmp_path,
) -> None:
    application = fetched_service(tmp_path)
    outcome = application.ingest("e9481622-7cc6-418a-acb6-c5450daae9b0", "30")
    expected_sections = application.repository.table_count("source_sections")
    migration_two_tables = (
        "section_diffs",
        "document_diffs",
        "document_version_edges",
        "lineage_history_entries",
        "lineage_history_snapshots",
        "lineage_source_documents",
        "document_lineages",
    )
    with sqlite3.connect(application.repository.path) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        for table in migration_two_tables:
            connection.execute(f"DROP TABLE {table}")
        connection.execute("DELETE FROM schema_migrations WHERE version = '2'")
        connection.commit()

    application.repository.initialize_schema()

    assert application.repository.table_count("regulatory_documents") == 1
    assert application.repository.table_count("source_sections") == expected_sections
    assert application.repository.table_count("document_lineages") == 1
    assert application.repository.table_count("lineage_source_documents") == 1
    assert application.verify(outcome.document_id).ok is True


def test_lineage_links_two_sources_and_official_history(stored_diff: tuple) -> None:
    application, old_id, _new_id, _result = stored_diff
    lineage_id = application.repository.get_lineage_id_for_document(old_id)
    snapshot_id, entries = application.repository.get_history_entries(lineage_id)

    assert application.repository.table_count("document_lineages") == 1
    assert application.repository.table_count("lineage_source_documents") == 2
    assert snapshot_id is not None
    assert len(entries) == 28
    assert [item.source_version for item in entries[:3]] == ["30", "29", "28"]


def test_diff_and_section_artifacts_are_stored_separately(stored_diff: tuple) -> None:
    application, _old_id, _new_id, result = stored_diff
    artifact = application.repository.get_diff_artifact(result.diff.diff_id)
    sections = application.repository.get_section_diff_artifacts(result.diff.diff_id)

    assert artifact is not None
    assert artifact["canonical_sha256"] == result.canonical_sha256
    assert artifact["canonical_json"] == result.canonical_json
    assert len(sections) == len(result.diff.section_diffs)
    assert application.repository.table_count("document_diffs") == 1


def test_identical_diff_insert_is_idempotent(stored_diff: tuple) -> None:
    application, old_id, new_id, first = stored_diff
    second = application.diff_documents(old_id, new_id)

    assert second.already_stored is True
    assert second.canonical_json == first.canonical_json
    assert application.repository.table_count("document_diffs") == 1


def test_existing_different_artifact_under_same_identity_is_rejected(
    stored_diff: tuple,
) -> None:
    application, _old_id, _new_id, result = stored_diff
    conflicting = replace(
        result.diff,
        summary=replace(
            result.diff.summary,
            sections_modified=result.diff.summary.sections_modified + 1,
        ),
    )

    with pytest.raises(DiffArtifactConflict):
        application.repository.store_diff(conflicting)


def test_diff_transaction_rolls_back_after_section_foreign_key_failure(
    stored_diff: tuple,
) -> None:
    application, _old_id, _new_id, result = stored_diff
    before = application.repository.table_count("document_diffs")
    bad_section = replace(result.diff.section_diffs[0], old_section_id="missing-section")
    bad_diff = replace(
        result.diff,
        diff_id="rollback-test-diff",
        old_document_id=None,
        section_diffs=(bad_section, *result.diff.section_diffs[1:]),
    )

    with pytest.raises(DatabaseFailure):
        application.repository.store_diff(bad_diff)
    assert application.repository.table_count("document_diffs") == before


def test_diff_foreign_keys_and_database_integrity_are_enforced(stored_diff: tuple) -> None:
    application, _old_id, _new_id, result = stored_diff
    integrity = application.repository.diff_integrity_checks(result.diff.diff_id)

    assert integrity["foreign_key_violations"] == []
    assert integrity["integrity_check"] == "ok"
    assert integrity["diff_count"] == 1
    assert integrity["section_diff_count"] == len(result.diff.section_diffs)

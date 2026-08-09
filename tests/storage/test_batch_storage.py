"""ODD-003/v3 through additive ODD-005/v5 persistence and integrity tests."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

import odd.storage.sqlite as sqlite_storage
from odd.errors import BatchArtifactConflict, DatabaseFailure, RawHashConflict
from odd.models.enrichment import EnrichmentBudget
from odd.provenance.hashing import sha256_bytes, sha256_file
from odd.storage.sqlite import SQLiteRepository
from odd.utilization import load_utilization_list
from tests.odd002_support import temporal_service
from tests.odd003_support import odd003_service
from tests.odd005_support import odd005_service

V3_TABLES = (
    "parser_compatibility_results",
    "batch_artifacts",
    "batch_items",
    "batch_runs",
    "candidate_decisions",
    "label_candidates",
    "candidate_discovery_runs",
    "utilization_entries",
    "utilization_lists",
)

V4_TABLES = (
    "live_batch_artifacts",
    "live_batch_items",
    "live_batch_runs",
    "candidate_discovery_pages",
    "candidate_discovery_details",
)

V5_TABLES = (
    "enrichment_artifacts",
    "decision_revisions",
    "enrichment_item_states",
    "enrichment_snapshot_assertions",
    "enrichment_run_snapshots",
    "evidence_assertions",
    "detail_response_evidence",
    "enrichment_snapshots",
    "enrichment_executions",
    "enrichment_runs",
)


def test_schema_five_keeps_v3_v4_and_adds_enrichment_tables(tmp_path: Path) -> None:
    repository = SQLiteRepository(tmp_path / "odd.sqlite3")
    repository.initialize_schema()
    with sqlite3.connect(repository.path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert set(V3_TABLES) <= tables
    assert set(V4_TABLES) <= tables
    assert set(V5_TABLES) <= tables
    assert repository.schema_versions() == ("1", "2", "3", "4", "5")


def test_fresh_and_v2_migrated_schema_contracts_match(tmp_path: Path) -> None:
    fresh = SQLiteRepository(tmp_path / "fresh.sqlite3")
    migrated = SQLiteRepository(tmp_path / "migrated.sqlite3")
    fresh.initialize_schema()
    migrated.initialize_schema()

    with sqlite3.connect(migrated.path) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        for table in (*V5_TABLES, *V4_TABLES, *V3_TABLES):
            connection.execute(f"DROP TABLE {table}")
        connection.execute(
            "DELETE FROM schema_migrations WHERE version IN ('3', '4', '5')"
        )
        connection.commit()
    migrated.initialize_schema()

    def contract(repository: SQLiteRepository) -> tuple[tuple[object, ...], ...]:
        with sqlite3.connect(repository.path) as connection:
            return tuple(
                connection.execute(
                    """
                    SELECT type, name, tbl_name, sql
                    FROM sqlite_master
                    WHERE name NOT LIKE 'sqlite_%'
                    ORDER BY type, name
                    """
                )
            )

    assert migrated.schema_versions() == ("1", "2", "3", "4", "5")
    assert contract(migrated) == contract(fresh)


def test_fresh_and_v3_to_v4_migrated_schema_contracts_match(tmp_path: Path) -> None:
    fresh = SQLiteRepository(tmp_path / "fresh.sqlite3")
    migrated = SQLiteRepository(tmp_path / "migrated.sqlite3")
    fresh.initialize_schema()
    migrated.initialize_schema()
    assert migrated.store_utilization_list(load_utilization_list())

    with sqlite3.connect(migrated.path) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        for table in (*V5_TABLES, *V4_TABLES):
            connection.execute(f"DROP TABLE {table}")
        connection.execute("DELETE FROM schema_migrations WHERE version IN ('4', '5')")
        connection.commit()
    migrated.initialize_schema()

    def contract(repository: SQLiteRepository) -> tuple[tuple[object, ...], ...]:
        with sqlite3.connect(repository.path) as connection:
            return tuple(
                connection.execute(
                    """
                    SELECT type, name, tbl_name, sql
                    FROM sqlite_master
                    WHERE name NOT LIKE 'sqlite_%'
                    ORDER BY type, name
                    """
                )
            )

    assert migrated.schema_versions() == ("1", "2", "3", "4", "5")
    assert migrated.table_count("utilization_entries") == 10
    assert contract(migrated) == contract(fresh)


def test_v4_migration_failure_rolls_back_the_entire_schema_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = SQLiteRepository(tmp_path / "rollback.sqlite3")
    repository.initialize_schema()
    assert repository.store_utilization_list(load_utilization_list())
    with sqlite3.connect(repository.path) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        for table in (*V5_TABLES, *V4_TABLES):
            connection.execute(f"DROP TABLE {table}")
        connection.execute("DELETE FROM schema_migrations WHERE version IN ('4', '5')")
        connection.commit()
    monkeypatch.setattr(
        sqlite_storage,
        "MIGRATION_4_STATEMENTS",
        (
            "CREATE TABLE migration_four_probe (id INTEGER PRIMARY KEY)",
            "THIS IS NOT VALID SQL",
        ),
    )

    with pytest.raises(DatabaseFailure):
        repository.initialize_schema()

    with sqlite3.connect(repository.path) as connection:
        probe = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            ("migration_four_probe",),
        ).fetchone()
        version = connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = '4'"
        ).fetchone()
        version_five = connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = '5'"
        ).fetchone()
        utilization_count = connection.execute(
            "SELECT COUNT(*) FROM utilization_entries"
        ).fetchone()[0]
    assert probe is None
    assert version is None
    assert version_five is None
    assert utilization_count == 10


def test_fresh_and_v4_to_v5_migrated_schema_contracts_match(tmp_path: Path) -> None:
    fresh = SQLiteRepository(tmp_path / "fresh-v5.sqlite3")
    migrated = SQLiteRepository(tmp_path / "migrated-v5.sqlite3")
    fresh.initialize_schema()
    migrated.initialize_schema()
    assert migrated.store_utilization_list(load_utilization_list())

    with sqlite3.connect(migrated.path) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        for table in V5_TABLES:
            connection.execute(f"DROP TABLE {table}")
        connection.execute("DELETE FROM schema_migrations WHERE version = '5'")
        connection.commit()
    migrated.initialize_schema()

    def contract(repository: SQLiteRepository) -> tuple[tuple[object, ...], ...]:
        with sqlite3.connect(repository.path) as connection:
            return tuple(
                connection.execute(
                    """
                    SELECT type, name, tbl_name, sql
                    FROM sqlite_master
                    WHERE name NOT LIKE 'sqlite_%'
                    ORDER BY type, name
                    """
                )
            )

    assert migrated.schema_versions() == ("1", "2", "3", "4", "5")
    assert migrated.table_count("utilization_entries") == 10
    assert contract(migrated) == contract(fresh)


def test_v5_migration_failure_rolls_back_the_entire_schema_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = SQLiteRepository(tmp_path / "rollback-v5.sqlite3")
    repository.initialize_schema()
    assert repository.store_utilization_list(load_utilization_list())
    with sqlite3.connect(repository.path) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        for table in V5_TABLES:
            connection.execute(f"DROP TABLE {table}")
        connection.execute("DELETE FROM schema_migrations WHERE version = '5'")
        connection.commit()
    monkeypatch.setattr(
        sqlite_storage,
        "MIGRATION_5_STATEMENTS",
        (
            "CREATE TABLE migration_five_probe (id INTEGER PRIMARY KEY)",
            "THIS IS NOT VALID SQL",
        ),
    )

    with pytest.raises(DatabaseFailure):
        repository.initialize_schema()

    with sqlite3.connect(repository.path) as connection:
        probe = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            ("migration_five_probe",),
        ).fetchone()
        version = connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = '5'"
        ).fetchone()
        utilization_count = connection.execute(
            "SELECT COUNT(*) FROM utilization_entries"
        ).fetchone()[0]
        v4_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'live_batch_runs'"
        ).fetchone()
    assert probe is None
    assert version is None
    assert utilization_count == 10
    assert v4_table is not None


def test_same_detail_identity_rejects_different_exact_bytes(tmp_path: Path) -> None:
    application, _transport, parent_run_id = odd005_service(tmp_path)
    run, _items = application.enrichment_new_observation(
        parent_run_id,
        ranks=(1,),
        parent_database_sha256=sha256_file(application.repository.path),
    )
    application.enrichment_execute(
        run.enrichment_run_id,
        budget=EnrichmentBudget(
            max_requests=1,
            max_downloaded_bytes=1_000_000,
            timeout_seconds=5,
            retry_limit=0,
            inter_request_delay_seconds=0,
            max_response_bytes=65_536,
            max_detail_pages=1,
            max_tier2_candidates=0,
        ),
        allow_tier2=False,
    )
    response = application.repository.get_detail_responses(
        run.enrichment_run_id, successful_only=True
    )[0]
    changed = b'{"different":"exact bytes"}'
    with pytest.raises(RawHashConflict, match="different exact bytes"):
        application.repository.store_detail_response(
            replace(
                response,
                response_id="ffffffff-ffff-4fff-8fff-ffffffffffff",
                raw_body=changed,
                raw_sha256=sha256_bytes(changed),
            )
        )


def test_utilization_data_is_separate_from_regulatory_documents(tmp_path: Path) -> None:
    repository = SQLiteRepository(tmp_path / "odd.sqlite3")
    repository.initialize_schema()
    assert repository.store_utilization_list(load_utilization_list())
    assert not repository.store_utilization_list(load_utilization_list())
    assert repository.table_count("utilization_lists") == 1
    assert repository.table_count("utilization_entries") == 10
    assert repository.table_count("regulatory_documents") == 0


def test_candidate_evidence_and_reasons_are_retrievable(tmp_path: Path) -> None:
    application, _transport = odd003_service(tmp_path)
    _run, _items = application.batch_plan("us-top10-2023")
    values = application.candidates("atorvastatin")
    assert len(values) == 2
    assert any("REPACKAGED_PRODUCT" in item["classifications"] for item in values)
    assert any(item["accepted_for_selection"] == 1 for item in values)
    assert all(len(item["raw_metadata_sha256"]) == 64 for item in values)


def test_batch_run_and_items_have_uniqueness_constraints(tmp_path: Path) -> None:
    application, _transport = odd003_service(tmp_path)
    run, items = application.batch_plan("us-top10-2023")
    assert application.repository.table_count("batch_runs") == 1
    assert application.repository.table_count("batch_items") == 10
    assert not application.repository.create_batch_run(run, items)


def test_batch_creation_rolls_back_after_injected_item_failure(tmp_path: Path) -> None:
    application, _transport = odd003_service(tmp_path)
    _utilization, run = application.batch._ensure_run("us-top10-2023")
    items = application.repository.get_batch_items(run.batch_run_id)
    with sqlite3.connect(application.repository.path) as connection:
        connection.execute("DELETE FROM batch_items")
        connection.execute("DELETE FROM batch_runs")
        connection.execute(
            """
            CREATE TRIGGER reject_second_batch_item BEFORE INSERT ON batch_items
            WHEN NEW.rank = 2 BEGIN SELECT RAISE(ABORT, 'forced batch item failure'); END
            """
        )
        connection.commit()
    with pytest.raises(DatabaseFailure, match="forced batch item failure"):
        application.repository.create_batch_run(run, items)
    assert application.repository.table_count("batch_runs") == 0
    assert application.repository.table_count("batch_items") == 0


def test_batch_artifact_is_idempotent_and_integrity_checked(tmp_path: Path) -> None:
    application, _transport = odd003_service(tmp_path)
    first = application.batch_run("us-top10-2023")
    second = application.batch_report(first.report.batch_run.batch_run_id)
    assert second.already_stored
    assert first.canonical_sha256 == second.canonical_sha256
    assert application.repository.batch_artifact_integrity(
        first.report.batch_run.batch_run_id
    ) == {
        "found": True,
        "hash_matches": True,
        "item_ordered": True,
        "run_hash_matches": True,
    }


def test_existing_corrupt_artifact_under_same_identity_is_rejected(tmp_path: Path) -> None:
    application, _transport = odd003_service(tmp_path)
    artifact = application.batch_run("us-top10-2023")
    with sqlite3.connect(application.repository.path) as connection:
        connection.execute(
            "UPDATE batch_artifacts SET canonical_json = ?",
            (b'{"tampered":true}',),
        )
        connection.commit()
    with pytest.raises(BatchArtifactConflict):
        application.repository.store_batch_artifact(artifact.report)


def test_v2_to_v3_migration_preserves_source_diff_and_verification(tmp_path: Path) -> None:
    application, old_id, new_id = temporal_service(tmp_path)
    diff = application.diff_documents(old_id, new_id)
    source_count = application.repository.table_count("source_documents")
    section_count = application.repository.table_count("source_sections")
    with sqlite3.connect(application.repository.path) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        for table in (*V5_TABLES, *V4_TABLES, *V3_TABLES):
            connection.execute(f"DROP TABLE {table}")
        connection.execute(
            "DELETE FROM schema_migrations WHERE version IN ('3', '4', '5')"
        )
        connection.commit()
    application.repository.initialize_schema()
    assert application.repository.schema_versions() == ("1", "2", "3", "4", "5")
    assert application.repository.table_count("source_documents") == source_count
    assert application.repository.table_count("source_sections") == section_count
    assert application.repository.get_diff_artifact(diff.diff.diff_id) is not None
    assert application.verify(old_id).ok and application.verify(new_id).ok


def test_batch_foreign_keys_are_enforced(tmp_path: Path) -> None:
    repository = SQLiteRepository(tmp_path / "odd.sqlite3")
    repository.initialize_schema()
    with repository._connect() as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO utilization_entries(
                    utilization_list_id, rank, ingredient_id, ingredient_name,
                    normalized_ingredient_name
                ) VALUES ('missing', 1, 'ingredient', 'name', 'name')
                """
            )

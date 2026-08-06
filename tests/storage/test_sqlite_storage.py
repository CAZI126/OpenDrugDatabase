"""SQLite schema, transaction, idempotency, and version tests."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from odd.errors import DatabaseFailure, DuplicateDocument, MalformedXML, RawHashConflict
from odd.parsers.spl.parser import SPLParser
from odd.service import ODDService
from odd.storage.sqlite import SQLiteRepository
from tests.odd_support import (
    APIXABAN_SEARCH,
    ELIQUIS_XML,
    SET_ID,
    SOURCE_VERSION,
    FixedClock,
    connector,
    fetched_service,
    service,
)

REQUIRED_TABLES = {
    "source_documents",
    "regulatory_documents",
    "products",
    "ingredients",
    "document_products",
    "source_sections",
    "semantic_mappings",
    "ingestion_runs",
}


def test_schema_creation_includes_required_tables(tmp_path: Path) -> None:
    repository = SQLiteRepository(tmp_path / "odd.sqlite3")
    repository.initialize_schema()
    with sqlite3.connect(repository.path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert REQUIRED_TABLES <= tables


def test_successful_transaction_stores_all_normalized_rows(tmp_path: Path) -> None:
    application = fetched_service(tmp_path)
    outcome = application.ingest(SET_ID)
    assert outcome.status == "ingested"
    assert application.repository.table_count("source_documents") == 1
    assert application.repository.table_count("regulatory_documents") == 1
    assert application.repository.table_count("products") == 1
    assert application.repository.table_count("ingredients") == 1
    assert application.repository.table_count("source_sections") == 21
    assert application.repository.table_count("semantic_mappings") == 19


def test_identical_ingestion_is_idempotent(tmp_path: Path) -> None:
    application = fetched_service(tmp_path)
    first = application.ingest(SET_ID)
    second = application.ingest(SET_ID)
    assert first.document_id == second.document_id
    assert second.status == "already_ingested"
    assert application.repository.table_count("regulatory_documents") == 1
    assert application.repository.table_count("ingestion_runs") == 2


def test_database_source_identity_hash_conflict_is_rejected(tmp_path: Path) -> None:
    application = fetched_service(tmp_path)
    first = application.ingest(SET_ID)
    with sqlite3.connect(application.repository.path) as connection:
        connection.execute("UPDATE source_documents SET raw_sha256 = ?", ("f" * 64,))
        connection.commit()
    with pytest.raises(RawHashConflict):
        application.ingest(SET_ID)
    assert application.repository.table_count("regulatory_documents") == 1
    assert application.repository.get_document(first.document_id) is not None


def test_duplicate_deterministic_id_with_different_output_is_rejected(tmp_path: Path) -> None:
    application = fetched_service(tmp_path)
    first = application.ingest(SET_ID)
    raw = application.raw_store.resolve(SET_ID)
    normalized = application.parser.parse(raw.label_path.read_bytes(), raw.identity)
    changed_document = replace(normalized.document, title="changed without version bump")
    changed = replace(normalized, document=changed_document)
    run_id = application.repository.start_ingestion_run(raw.identity, FixedClock()())
    with pytest.raises(DuplicateDocument):
        application.repository.store_document(
            changed,
            raw,
            run_id=run_id,
            completed_at=FixedClock()(),
        )
    assert application.repository.get_document(first.document_id)["title"] != changed_document.title


def test_transaction_rolls_back_after_child_insert_failure(tmp_path: Path) -> None:
    application = fetched_service(tmp_path)
    raw = application.raw_store.resolve(SET_ID)
    normalized = application.parser.parse(raw.label_path.read_bytes(), raw.identity)
    run_id = application.repository.start_ingestion_run(raw.identity, FixedClock()())
    with sqlite3.connect(application.repository.path) as connection:
        connection.executescript(
            """
            CREATE TRIGGER reject_sections BEFORE INSERT ON source_sections
            BEGIN SELECT RAISE(ABORT, 'forced section failure'); END;
            """
        )
    with pytest.raises(DatabaseFailure, match="forced section failure"):
        application.repository.store_document(
            normalized,
            raw,
            run_id=run_id,
            completed_at=FixedClock()(),
        )
    assert application.repository.table_count("source_documents") == 0
    assert application.repository.table_count("regulatory_documents") == 0
    assert application.repository.table_count("products") == 0


def test_foreign_keys_are_enabled_on_repository_connections(tmp_path: Path) -> None:
    repository = SQLiteRepository(tmp_path / "odd.sqlite3")
    repository.initialize_schema()
    with repository._connect() as connection:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO document_products(document_id, product_id, sequence_index)
                VALUES ('missing-doc', 'missing-product', 0)
                """
            )


def test_different_source_version_is_stored_separately(tmp_path: Path) -> None:
    application = fetched_service(tmp_path)
    v30 = application.ingest(SET_ID)

    search = json.loads(APIXABAN_SEARCH.read_bytes())
    search["data"][1]["spl_version"] = "31"
    search["data"][1]["published_date"] = "May 01, 2025"
    xml_v31 = ELIQUIS_XML.read_bytes().replace(
        b'root="c6b2240a-a9d6-4dd9-9bc4-b42dc90c0d2f"',
        b'root="d7c3351b-b0e7-4ee0-8ad5-c53ed01d1e30"',
        1,
    ).replace(b'<versionNumber value="30"/>', b'<versionNumber value="31"/>')
    client, _transport = connector(
        search_body=json.dumps(search).encode(),
        xml_body=xml_v31,
    )
    second_application = ODDService(
        repository=application.repository,
        raw_store=application.raw_store,
        quarantine_store=application.quarantine_store,
        connector=client,
        clock=FixedClock(),
    )
    second_application.fetch("apixaban")
    v31 = second_application.ingest(SET_ID, "31")
    assert v30.document_id != v31.document_id
    assert application.repository.table_count("source_documents") == 2
    assert application.repository.table_count("regulatory_documents") == 2
    assert {item["source_version"] for item in application.search("apixaban")} == {"30", "31"}


def test_parser_version_change_is_distinct_from_source_change(tmp_path: Path) -> None:
    class NextParser(SPLParser):
        parser_version = "spl-parser/test-next"

    application = fetched_service(tmp_path)
    current = application.ingest(SET_ID)
    next_service = ODDService(
        repository=application.repository,
        raw_store=application.raw_store,
        quarantine_store=application.quarantine_store,
        parser=NextParser(),
        clock=FixedClock(),
    )
    reparsed = next_service.ingest(SET_ID)
    assert current.document_id != reparsed.document_id
    assert application.repository.table_count("source_documents") == 1
    assert application.repository.table_count("regulatory_documents") == 2


def test_retrieves_source_sections_in_order(tmp_path: Path) -> None:
    application = fetched_service(tmp_path)
    outcome = application.ingest(SET_ID)
    sections = application.repository.get_sections(outcome.document_id)
    assert [item["sequence_index"] for item in sections] == list(range(21))
    assert sections[8]["original_heading"] == "7 DRUG INTERACTIONS"


def test_retrieves_semantic_mappings_by_concept(tmp_path: Path) -> None:
    application = fetched_service(tmp_path)
    outcome = application.ingest(SET_ID)
    sections = application.repository.get_sections(outcome.document_id, "drug_interactions")
    assert len(sections) == 1
    assert sections[0]["semantic_mappings"][0]["mapping_method"] == "loinc_code_exact"
    assert sections[0]["semantic_mappings"][0]["mapping_version"]


def test_search_returns_required_source_and_label_fields(tmp_path: Path) -> None:
    application = fetched_service(tmp_path)
    outcome = application.ingest(SET_ID)
    result = application.search("apixaban")
    assert result == [
        {
            **result[0],
            "document_id": outcome.document_id,
            "generic_name": "apixaban",
            "brand_name": "ELIQUIS",
            "jurisdiction": "United States",
            "authority": "FDA",
            "provider": "DailyMed",
            "source_version": SOURCE_VERSION,
            "source_document_id": SET_ID,
        }
    ]


def test_parser_failure_records_failed_run_and_keeps_raw_source(tmp_path: Path) -> None:
    malformed = b'<document xmlns="urn:hl7-org:v3">'
    application = service(tmp_path, xml_body=malformed)
    application.fetch("apixaban")
    with pytest.raises(MalformedXML):
        application.ingest(SET_ID)
    run = application.repository.get_ingestion_run(1)
    assert run is not None
    assert run["status"] == "failed"
    assert run["error_category"] == "malformed_xml"
    assert application.raw_store.resolve(SET_ID).label_path.read_bytes() == malformed
    assert list((tmp_path / "data" / "quarantine").rglob("failure.json"))

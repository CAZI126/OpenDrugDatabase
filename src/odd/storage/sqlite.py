"""Transactional, version-aware SQLite persistence."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from odd.constants import LIVE_SNAPSHOT_VERSION
from odd.diffs.source_identifiers import extract_section_xml_identifiers
from odd.errors import (
    AmbiguousDocumentVersion,
    BatchArtifactConflict,
    DatabaseFailure,
    DiffArtifactConflict,
    DuplicateDocument,
    ODDError,
    ProvenanceValidationFailure,
    RawHashConflict,
    SourceNotFound,
)
from odd.models import (
    BatchArtifactResult,
    BatchItem,
    BatchReport,
    BatchRun,
    BatchStatus,
    CandidateClassification,
    CandidateDiscoveryPage,
    CandidateEvidence,
    CandidateLookup,
    CandidateSelection,
    DailyMedCandidate,
    DailyMedHistory,
    DailyMedHistoryEntry,
    DiscoveryCompleteness,
    DiscoveryStatus,
    DocumentDiff,
    HTTPAttemptEvidence,
    IngestionStatus,
    NormalizedDocument,
    ParserCompatibilityStatus,
    RawDocument,
    SelectionStatus,
    SourceIdentity,
    StoredDocumentVersion,
    StoredSection,
    UtilizationEntry,
    UtilizationList,
    VerificationStatus,
)
from odd.provenance.canonical import (
    canonical_batch_report_json_bytes,
    canonical_diff_json_bytes,
    canonical_json_bytes,
    canonical_normalized_json_bytes,
    source_identity_payload,
)
from odd.provenance.hashing import sha256_bytes
from odd.provenance.identifiers import (
    batch_artifact_id,
    document_lineage_id,
    history_snapshot_id,
    ingredient_id,
    live_candidate_snapshot_id,
    mapping_id,
    section_diff_id,
    source_record_id,
    version_edge_id,
)

DATABASE_SCHEMA_VERSION = "4"
_DAILYMED_DATE = re.compile(r"^([A-Za-z]{3}) (\d{2}), (\d{4})$")
_MONTHS = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS source_documents (
    id TEXT PRIMARY KEY,
    authority TEXT NOT NULL,
    provider TEXT NOT NULL,
    jurisdiction TEXT NOT NULL,
    source_document_id TEXT NOT NULL,
    source_version TEXT NOT NULL,
    source_url TEXT,
    retrieved_at TEXT NOT NULL,
    raw_sha256 TEXT NOT NULL CHECK(length(raw_sha256) = 64),
    raw_path TEXT NOT NULL,
    metadata_path TEXT NOT NULL,
    candidates_json TEXT NOT NULL,
    selection_reason TEXT NOT NULL,
    UNIQUE(authority, provider, jurisdiction, source_document_id, source_version)
);

CREATE TABLE IF NOT EXISTS regulatory_documents (
    id TEXT PRIMARY KEY,
    source_document_row_id TEXT NOT NULL REFERENCES source_documents(id),
    source_instance_id TEXT,
    document_type TEXT NOT NULL,
    language TEXT,
    effective_date TEXT,
    title TEXT NOT NULL,
    generic_name TEXT,
    brand_names_json TEXT NOT NULL,
    dosage_forms_json TEXT NOT NULL,
    routes_json TEXT NOT NULL,
    active_ingredients_json TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    mapping_version TEXT NOT NULL,
    normalized_json BLOB NOT NULL,
    UNIQUE(source_document_row_id, parser_version, schema_version, mapping_version)
);

CREATE TABLE IF NOT EXISTS products (
    id TEXT PRIMARY KEY,
    brand_name TEXT,
    dosage_form TEXT,
    route TEXT
);

CREATE TABLE IF NOT EXISTS ingredients (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS document_products (
    document_id TEXT NOT NULL REFERENCES regulatory_documents(id),
    product_id TEXT NOT NULL REFERENCES products(id),
    sequence_index INTEGER NOT NULL CHECK(sequence_index >= 0),
    PRIMARY KEY(document_id, product_id),
    UNIQUE(document_id, sequence_index)
);

CREATE TABLE IF NOT EXISTS document_ingredients (
    document_id TEXT NOT NULL REFERENCES regulatory_documents(id),
    ingredient_id TEXT NOT NULL REFERENCES ingredients(id),
    sequence_index INTEGER NOT NULL CHECK(sequence_index >= 0),
    PRIMARY KEY(document_id, ingredient_id),
    UNIQUE(document_id, sequence_index)
);

CREATE TABLE IF NOT EXISTS source_sections (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES regulatory_documents(id),
    source_section_code TEXT,
    original_heading TEXT,
    original_text TEXT NOT NULL,
    sequence_index INTEGER NOT NULL CHECK(sequence_index >= 0),
    section_sha256 TEXT NOT NULL CHECK(length(section_sha256) = 64),
    source_locator TEXT NOT NULL,
    parent_section_id TEXT REFERENCES source_sections(id),
    depth INTEGER NOT NULL CHECK(depth >= 0),
    content_status TEXT NOT NULL,
    structured_content_json TEXT,
    UNIQUE(document_id, sequence_index),
    UNIQUE(document_id, source_locator)
);

CREATE TABLE IF NOT EXISTS semantic_mappings (
    id TEXT PRIMARY KEY,
    section_id TEXT NOT NULL REFERENCES source_sections(id),
    normalized_concept TEXT NOT NULL,
    mapping_method TEXT NOT NULL,
    mapping_version TEXT NOT NULL,
    confidence REAL,
    deterministic_status TEXT NOT NULL,
    UNIQUE(section_id, normalized_concept, mapping_version)
);

CREATE TABLE IF NOT EXISTS document_concept_statuses (
    document_id TEXT NOT NULL REFERENCES regulatory_documents(id),
    normalized_concept TEXT NOT NULL,
    status TEXT NOT NULL,
    section_ids_json TEXT NOT NULL,
    PRIMARY KEY(document_id, normalized_concept)
);

CREATE TABLE IF NOT EXISTS ingestion_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL,
    selected_source_identity_json TEXT NOT NULL,
    source_document_row_id TEXT REFERENCES source_documents(id),
    document_id TEXT REFERENCES regulatory_documents(id),
    source_section_count INTEGER NOT NULL DEFAULT 0,
    mapped_section_count INTEGER NOT NULL DEFAULT 0,
    unmapped_section_count INTEGER NOT NULL DEFAULT 0,
    error_category TEXT,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_source_documents_lookup
ON source_documents(source_document_id, source_version);
CREATE INDEX IF NOT EXISTS idx_regulatory_documents_generic
ON regulatory_documents(generic_name);
CREATE INDEX IF NOT EXISTS idx_source_sections_document
ON source_sections(document_id, sequence_index);
CREATE INDEX IF NOT EXISTS idx_semantic_mappings_concept
ON semantic_mappings(normalized_concept, section_id);
"""

MIGRATION_2_STATEMENTS = (
    """
    CREATE TABLE document_lineages (
        id TEXT PRIMARY KEY,
        authority TEXT NOT NULL,
        provider TEXT NOT NULL,
        jurisdiction TEXT NOT NULL,
        source_document_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(authority, provider, jurisdiction, source_document_id)
    )
    """,
    """
    CREATE TABLE lineage_source_documents (
        lineage_id TEXT NOT NULL REFERENCES document_lineages(id),
        source_document_row_id TEXT NOT NULL UNIQUE REFERENCES source_documents(id),
        selection_publication_date TEXT,
        publication_date_status TEXT NOT NULL,
        PRIMARY KEY(lineage_id, source_document_row_id)
    )
    """,
    """
    CREATE TABLE lineage_history_snapshots (
        id TEXT PRIMARY KEY,
        lineage_id TEXT NOT NULL REFERENCES document_lineages(id),
        source_url TEXT NOT NULL,
        retrieved_at TEXT NOT NULL,
        raw_sha256 TEXT NOT NULL CHECK(length(raw_sha256) = 64),
        raw_json BLOB NOT NULL,
        UNIQUE(lineage_id, raw_sha256)
    )
    """,
    """
    CREATE TABLE lineage_history_entries (
        history_snapshot_id TEXT NOT NULL REFERENCES lineage_history_snapshots(id),
        lineage_id TEXT NOT NULL REFERENCES document_lineages(id),
        source_version TEXT NOT NULL,
        publication_date TEXT,
        publication_date_text TEXT NOT NULL,
        sequence_index INTEGER NOT NULL CHECK(sequence_index >= 0),
        PRIMARY KEY(history_snapshot_id, source_version),
        UNIQUE(history_snapshot_id, sequence_index)
    )
    """,
    """
    CREATE TABLE document_version_edges (
        id TEXT PRIMARY KEY,
        lineage_id TEXT NOT NULL REFERENCES document_lineages(id),
        predecessor_document_id TEXT REFERENCES regulatory_documents(id),
        successor_document_id TEXT REFERENCES regulatory_documents(id),
        ordering_status TEXT NOT NULL,
        ordering_source TEXT NOT NULL,
        confidence_status TEXT NOT NULL,
        known_predecessor INTEGER NOT NULL CHECK(known_predecessor IN (0, 1)),
        known_successor INTEGER NOT NULL CHECK(known_successor IN (0, 1)),
        intermediate_versions_possible INTEGER NOT NULL
            CHECK(intermediate_versions_possible IN (0, 1)),
        missing_source_versions_json TEXT NOT NULL,
        history_snapshot_id TEXT REFERENCES lineage_history_snapshots(id),
        created_at TEXT NOT NULL,
        UNIQUE(lineage_id, predecessor_document_id, successor_document_id)
    )
    """,
    """
    CREATE TABLE document_diffs (
        id TEXT PRIMARY KEY,
        lineage_id TEXT NOT NULL REFERENCES document_lineages(id),
        version_edge_id TEXT REFERENCES document_version_edges(id),
        old_document_id TEXT REFERENCES regulatory_documents(id),
        new_document_id TEXT REFERENCES regulatory_documents(id),
        old_source_version TEXT,
        new_source_version TEXT,
        old_raw_sha256 TEXT,
        new_raw_sha256 TEXT,
        change_cause TEXT NOT NULL,
        ordering_status TEXT NOT NULL,
        diff_engine_version TEXT NOT NULL,
        canonical_json BLOB NOT NULL,
        canonical_sha256 TEXT NOT NULL CHECK(length(canonical_sha256) = 64),
        generated_at TEXT NOT NULL,
        CHECK(old_document_id IS NOT NULL OR new_document_id IS NOT NULL),
        UNIQUE(old_document_id, new_document_id, diff_engine_version)
    )
    """,
    """
    CREATE TABLE section_diffs (
        id TEXT PRIMARY KEY,
        document_diff_id TEXT NOT NULL REFERENCES document_diffs(id),
        sequence_index INTEGER NOT NULL CHECK(sequence_index >= 0),
        old_section_id TEXT REFERENCES source_sections(id),
        new_section_id TEXT REFERENCES source_sections(id),
        match_method TEXT NOT NULL,
        match_status TEXT NOT NULL,
        operations_json TEXT NOT NULL,
        canonical_json BLOB NOT NULL,
        canonical_sha256 TEXT NOT NULL CHECK(length(canonical_sha256) = 64),
        CHECK(old_section_id IS NOT NULL OR new_section_id IS NOT NULL),
        UNIQUE(document_diff_id, sequence_index)
    )
    """,
    """
    CREATE INDEX idx_lineage_source_version
    ON lineage_history_entries(lineage_id, source_version)
    """,
    "CREATE INDEX idx_lineage_documents ON lineage_source_documents(lineage_id)",
    "CREATE INDEX idx_document_diffs_inputs ON document_diffs(old_document_id, new_document_id)",
    "CREATE INDEX idx_section_diffs_document ON section_diffs(document_diff_id, sequence_index)",
)

MIGRATION_3_STATEMENTS = (
    """
    CREATE TABLE utilization_lists (
        id TEXT PRIMARY KEY,
        schema_version TEXT NOT NULL,
        jurisdiction TEXT NOT NULL,
        dataset_name TEXT NOT NULL,
        dataset_version TEXT NOT NULL,
        measurement_year INTEGER NOT NULL,
        metric TEXT NOT NULL,
        source_reference TEXT NOT NULL,
        retrieved_at TEXT NOT NULL,
        license_or_terms_status TEXT NOT NULL,
        source_status TEXT NOT NULL,
        notes TEXT NOT NULL,
        canonical_json BLOB NOT NULL,
        canonical_sha256 TEXT NOT NULL CHECK(length(canonical_sha256) = 64)
    )
    """,
    """
    CREATE TABLE utilization_entries (
        utilization_list_id TEXT NOT NULL REFERENCES utilization_lists(id),
        rank INTEGER NOT NULL CHECK(rank > 0),
        ingredient_id TEXT NOT NULL,
        ingredient_name TEXT NOT NULL,
        normalized_ingredient_name TEXT NOT NULL,
        metric_value REAL,
        metric_unit TEXT,
        source_row_identifier TEXT,
        PRIMARY KEY(utilization_list_id, rank),
        UNIQUE(utilization_list_id, normalized_ingredient_name)
    )
    """,
    """
    CREATE TABLE candidate_discovery_runs (
        id TEXT PRIMARY KEY,
        utilization_list_id TEXT NOT NULL REFERENCES utilization_lists(id),
        ingredient_id TEXT NOT NULL,
        query_text TEXT NOT NULL,
        connector_version TEXT NOT NULL,
        source_url TEXT NOT NULL,
        retrieved_at TEXT NOT NULL,
        raw_metadata BLOB NOT NULL,
        raw_metadata_sha256 TEXT NOT NULL CHECK(length(raw_metadata_sha256) = 64),
        status TEXT NOT NULL,
        error_category TEXT,
        diagnostic_message TEXT,
        UNIQUE(utilization_list_id, ingredient_id, connector_version, raw_metadata_sha256)
    )
    """,
    """
    CREATE TABLE label_candidates (
        id TEXT PRIMARY KEY,
        discovery_run_id TEXT NOT NULL REFERENCES candidate_discovery_runs(id),
        candidate_index INTEGER NOT NULL CHECK(candidate_index >= 0),
        set_id TEXT,
        source_version TEXT,
        title TEXT,
        published_date TEXT,
        generic_name TEXT,
        brand_name TEXT,
        active_ingredients_json TEXT NOT NULL,
        dosage_form TEXT,
        route TEXT,
        labeler TEXT,
        marketing_category TEXT,
        product_type TEXT,
        source_status TEXT,
        source_url TEXT,
        raw_metadata_json TEXT NOT NULL,
        raw_metadata_sha256 TEXT NOT NULL CHECK(length(raw_metadata_sha256) = 64),
        classifications_json TEXT NOT NULL,
        accepted_for_selection INTEGER NOT NULL CHECK(accepted_for_selection IN (0, 1)),
        rejection_reasons_json TEXT NOT NULL,
        duplicate_of_candidate_id TEXT REFERENCES label_candidates(id),
        UNIQUE(discovery_run_id, candidate_index)
    )
    """,
    """
    CREATE TABLE candidate_decisions (
        id TEXT PRIMARY KEY,
        discovery_run_id TEXT NOT NULL REFERENCES candidate_discovery_runs(id),
        ingredient_id TEXT NOT NULL,
        selection_rule_version TEXT NOT NULL,
        selection_status TEXT NOT NULL,
        selected_candidate_id TEXT REFERENCES label_candidates(id),
        selected_set_id TEXT,
        selected_source_version TEXT,
        selection_reason TEXT NOT NULL,
        applied_rules_json TEXT NOT NULL,
        manual_review_required INTEGER NOT NULL CHECK(manual_review_required IN (0, 1)),
        selection_scope TEXT NOT NULL,
        canonical_json BLOB NOT NULL,
        canonical_sha256 TEXT NOT NULL CHECK(length(canonical_sha256) = 64),
        UNIQUE(discovery_run_id, selection_rule_version)
    )
    """,
    """
    CREATE TABLE batch_runs (
        id TEXT PRIMARY KEY,
        utilization_list_id TEXT NOT NULL REFERENCES utilization_lists(id),
        selection_rule_version TEXT NOT NULL,
        connector_version TEXT NOT NULL,
        parser_version TEXT NOT NULL,
        schema_version TEXT NOT NULL,
        mapping_version TEXT NOT NULL,
        started_at TEXT NOT NULL,
        completed_at TEXT,
        status TEXT NOT NULL,
        requested_count INTEGER NOT NULL CHECK(requested_count >= 0),
        selected_count INTEGER NOT NULL DEFAULT 0 CHECK(selected_count >= 0),
        fetched_count INTEGER NOT NULL DEFAULT 0 CHECK(fetched_count >= 0),
        ingested_count INTEGER NOT NULL DEFAULT 0 CHECK(ingested_count >= 0),
        verified_count INTEGER NOT NULL DEFAULT 0 CHECK(verified_count >= 0),
        quarantined_count INTEGER NOT NULL DEFAULT 0 CHECK(quarantined_count >= 0),
        unresolved_count INTEGER NOT NULL DEFAULT 0 CHECK(unresolved_count >= 0),
        failed_count INTEGER NOT NULL DEFAULT 0 CHECK(failed_count >= 0),
        canonical_report_sha256 TEXT,
        UNIQUE(
            utilization_list_id, selection_rule_version, connector_version,
            parser_version, schema_version, mapping_version
        )
    )
    """,
    """
    CREATE TABLE batch_items (
        batch_run_id TEXT NOT NULL REFERENCES batch_runs(id),
        rank INTEGER NOT NULL CHECK(rank > 0),
        ingredient_id TEXT NOT NULL,
        ingredient_name TEXT NOT NULL,
        discovery_status TEXT NOT NULL,
        selection_status TEXT NOT NULL,
        selected_set_id TEXT,
        selected_source_version TEXT,
        document_id TEXT REFERENCES regulatory_documents(id),
        raw_sha256 TEXT,
        ingestion_status TEXT NOT NULL,
        verification_status TEXT NOT NULL,
        quarantine_record_id TEXT,
        error_category TEXT,
        diagnostic_message TEXT,
        manual_review_required INTEGER NOT NULL CHECK(manual_review_required IN (0, 1)),
        parser_compatibility_status TEXT NOT NULL,
        source_section_count INTEGER,
        mapped_section_count INTEGER,
        unmapped_section_count INTEGER,
        unsupported_structure_count INTEGER NOT NULL DEFAULT 0,
        empty_section_count INTEGER NOT NULL DEFAULT 0,
        parser_warnings_json TEXT NOT NULL,
        discovery_run_id TEXT REFERENCES candidate_discovery_runs(id),
        decision_id TEXT REFERENCES candidate_decisions(id),
        retry_eligible INTEGER NOT NULL CHECK(retry_eligible IN (0, 1)),
        query_text TEXT NOT NULL,
        candidate_count INTEGER NOT NULL CHECK(candidate_count >= 0),
        selection_reason TEXT,
        PRIMARY KEY(batch_run_id, rank),
        UNIQUE(batch_run_id, ingredient_id)
    )
    """,
    """
    CREATE TABLE parser_compatibility_results (
        batch_run_id TEXT NOT NULL,
        rank INTEGER NOT NULL,
        document_id TEXT REFERENCES regulatory_documents(id),
        status TEXT NOT NULL,
        source_section_count INTEGER,
        mapped_section_count INTEGER,
        unmapped_section_count INTEGER,
        unsupported_structure_count INTEGER NOT NULL,
        empty_section_count INTEGER NOT NULL,
        parser_warnings_json TEXT NOT NULL,
        quarantine_reason TEXT,
        PRIMARY KEY(batch_run_id, rank),
        FOREIGN KEY(batch_run_id, rank) REFERENCES batch_items(batch_run_id, rank)
    )
    """,
    """
    CREATE TABLE batch_artifacts (
        id TEXT PRIMARY KEY,
        batch_run_id TEXT NOT NULL REFERENCES batch_runs(id),
        report_version TEXT NOT NULL,
        canonical_json BLOB NOT NULL,
        canonical_sha256 TEXT NOT NULL CHECK(length(canonical_sha256) = 64),
        generated_at TEXT NOT NULL,
        UNIQUE(batch_run_id, report_version, canonical_sha256)
    )
    """,
    "CREATE INDEX idx_utilization_entries_name ON utilization_entries(normalized_ingredient_name)",
    "CREATE INDEX idx_discovery_ingredient ON candidate_discovery_runs(ingredient_id)",
    "CREATE INDEX idx_candidates_discovery ON label_candidates(discovery_run_id, candidate_index)",
    "CREATE INDEX idx_batch_items_status ON batch_items(batch_run_id, rank)",
)

MIGRATION_4_STATEMENTS = (
    """
    CREATE TABLE candidate_discovery_details (
        discovery_run_id TEXT PRIMARY KEY REFERENCES candidate_discovery_runs(id),
        snapshot_id TEXT NOT NULL UNIQUE,
        canonical_request_json TEXT NOT NULL,
        canonical_request_sha256 TEXT NOT NULL CHECK(length(canonical_request_sha256) = 64),
        response_bundle_sha256 TEXT NOT NULL CHECK(length(response_bundle_sha256) = 64),
        metadata_total_elements INTEGER,
        retrieved_elements INTEGER NOT NULL CHECK(retrieved_elements >= 0),
        total_pages INTEGER,
        completeness TEXT NOT NULL,
        duplicate_count INTEGER NOT NULL CHECK(duplicate_count >= 0),
        metadata_conflict_count INTEGER NOT NULL CHECK(metadata_conflict_count >= 0),
        diagnostic_message TEXT,
        failure_attempts_json TEXT NOT NULL,
        evidence_manifest_sha256 TEXT CHECK(
            evidence_manifest_sha256 IS NULL OR length(evidence_manifest_sha256) = 64
        ),
        evidence_logical_path TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE candidate_discovery_pages (
        discovery_run_id TEXT NOT NULL REFERENCES candidate_discovery_runs(id),
        page_number INTEGER NOT NULL CHECK(page_number > 0),
        request_url TEXT NOT NULL,
        canonical_query_json TEXT NOT NULL,
        response_url TEXT NOT NULL,
        http_status INTEGER NOT NULL,
        content_type TEXT NOT NULL,
        retrieved_at TEXT NOT NULL,
        etag TEXT,
        last_modified TEXT,
        raw_response BLOB NOT NULL,
        raw_sha256 TEXT NOT NULL CHECK(length(raw_sha256) = 64),
        response_size INTEGER NOT NULL CHECK(response_size >= 0),
        attempts_json TEXT NOT NULL,
        PRIMARY KEY(discovery_run_id, page_number)
    )
    """,
    """
    CREATE TABLE live_batch_runs (
        id TEXT PRIMARY KEY,
        observation_token TEXT NOT NULL UNIQUE,
        utilization_list_id TEXT NOT NULL REFERENCES utilization_lists(id),
        selection_rule_version TEXT NOT NULL,
        connector_version TEXT NOT NULL,
        parser_version TEXT NOT NULL,
        schema_version TEXT NOT NULL,
        mapping_version TEXT NOT NULL,
        started_at TEXT NOT NULL,
        completed_at TEXT,
        status TEXT NOT NULL,
        requested_count INTEGER NOT NULL CHECK(requested_count >= 0),
        selected_count INTEGER NOT NULL DEFAULT 0 CHECK(selected_count >= 0),
        fetched_count INTEGER NOT NULL DEFAULT 0 CHECK(fetched_count >= 0),
        ingested_count INTEGER NOT NULL DEFAULT 0 CHECK(ingested_count >= 0),
        verified_count INTEGER NOT NULL DEFAULT 0 CHECK(verified_count >= 0),
        quarantined_count INTEGER NOT NULL DEFAULT 0 CHECK(quarantined_count >= 0),
        unresolved_count INTEGER NOT NULL DEFAULT 0 CHECK(unresolved_count >= 0),
        failed_count INTEGER NOT NULL DEFAULT 0 CHECK(failed_count >= 0),
        canonical_report_sha256 TEXT,
        observation_mode TEXT NOT NULL,
        snapshot_manifest_sha256 TEXT,
        discovery_complete_count INTEGER NOT NULL DEFAULT 0 CHECK(discovery_complete_count >= 0),
        manual_review_count INTEGER NOT NULL DEFAULT 0 CHECK(manual_review_count >= 0),
        no_candidate_count INTEGER NOT NULL DEFAULT 0 CHECK(no_candidate_count >= 0),
        fetch_failure_count INTEGER NOT NULL DEFAULT 0 CHECK(fetch_failure_count >= 0),
        parser_failure_count INTEGER NOT NULL DEFAULT 0 CHECK(parser_failure_count >= 0),
        database_schema_version TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE live_batch_items (
        batch_run_id TEXT NOT NULL REFERENCES live_batch_runs(id),
        rank INTEGER NOT NULL CHECK(rank > 0),
        ingredient_id TEXT NOT NULL,
        ingredient_name TEXT NOT NULL,
        discovery_status TEXT NOT NULL,
        selection_status TEXT NOT NULL,
        selected_set_id TEXT,
        selected_source_version TEXT,
        document_id TEXT REFERENCES regulatory_documents(id),
        raw_sha256 TEXT,
        ingestion_status TEXT NOT NULL,
        verification_status TEXT NOT NULL,
        quarantine_record_id TEXT,
        error_category TEXT,
        diagnostic_message TEXT,
        manual_review_required INTEGER NOT NULL CHECK(manual_review_required IN (0, 1)),
        parser_compatibility_status TEXT NOT NULL,
        source_section_count INTEGER,
        mapped_section_count INTEGER,
        unmapped_section_count INTEGER,
        unsupported_structure_count INTEGER NOT NULL DEFAULT 0,
        empty_section_count INTEGER NOT NULL DEFAULT 0,
        parser_warnings_json TEXT NOT NULL,
        discovery_run_id TEXT REFERENCES candidate_discovery_runs(id),
        decision_id TEXT REFERENCES candidate_decisions(id),
        retry_eligible INTEGER NOT NULL CHECK(retry_eligible IN (0, 1)),
        query_text TEXT NOT NULL,
        candidate_count INTEGER NOT NULL CHECK(candidate_count >= 0),
        selection_reason TEXT,
        snapshot_id TEXT,
        metadata_total_candidate_count INTEGER,
        retrieved_candidate_count INTEGER NOT NULL DEFAULT 0 CHECK(retrieved_candidate_count >= 0),
        eligible_candidate_count INTEGER NOT NULL DEFAULT 0 CHECK(eligible_candidate_count >= 0),
        discovery_completeness TEXT NOT NULL,
        evidence_verification_status TEXT NOT NULL,
        PRIMARY KEY(batch_run_id, rank),
        UNIQUE(batch_run_id, ingredient_id)
    )
    """,
    """
    CREATE TABLE live_batch_artifacts (
        id TEXT PRIMARY KEY,
        batch_run_id TEXT NOT NULL REFERENCES live_batch_runs(id),
        report_version TEXT NOT NULL,
        canonical_json BLOB NOT NULL,
        canonical_sha256 TEXT NOT NULL CHECK(length(canonical_sha256) = 64),
        generated_at TEXT NOT NULL,
        UNIQUE(batch_run_id, report_version, canonical_sha256)
    )
    """,
    """
    CREATE INDEX idx_discovery_pages_snapshot
    ON candidate_discovery_pages(discovery_run_id, page_number)
    """,
    "CREATE INDEX idx_live_batch_items_status ON live_batch_items(batch_run_id, rank)",
)


class SQLiteRepository:
    """Narrow repository with explicit transactions and read models."""

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()

    def initialize_schema(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as connection:
                connection.executescript(SCHEMA_SQL)
                connection.execute(
                    "INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)",
                    ("1",),
                )
                connection.commit()
                applied = {
                    str(row[0])
                    for row in connection.execute("SELECT version FROM schema_migrations")
                }
                if "2" not in applied:
                    connection.execute("BEGIN IMMEDIATE")
                    try:
                        for statement in MIGRATION_2_STATEMENTS:
                            connection.execute(statement)
                        self._backfill_lineages(connection)
                        connection.execute(
                            "INSERT INTO schema_migrations(version) VALUES (?)",
                            ("2",),
                        )
                        connection.commit()
                    except Exception:
                        connection.rollback()
                        raise
                if "3" not in applied:
                    connection.execute("BEGIN IMMEDIATE")
                    try:
                        for statement in MIGRATION_3_STATEMENTS:
                            connection.execute(statement)
                        connection.execute(
                            "INSERT INTO schema_migrations(version) VALUES (?)",
                            ("3",),
                        )
                        connection.commit()
                    except Exception:
                        connection.rollback()
                        raise
                if "4" not in applied:
                    connection.execute("BEGIN IMMEDIATE")
                    try:
                        for statement in MIGRATION_4_STATEMENTS:
                            connection.execute(statement)
                        connection.execute(
                            "INSERT INTO schema_migrations(version) VALUES (?)",
                            ("4",),
                        )
                        connection.commit()
                    except Exception:
                        connection.rollback()
                        raise
        except sqlite3.Error as exc:
            raise DatabaseFailure(f"could not initialize SQLite schema: {exc}") from exc

    @staticmethod
    def _backfill_lineages(connection: sqlite3.Connection) -> None:
        rows = connection.execute("SELECT * FROM source_documents ORDER BY id").fetchall()
        for row in rows:
            identity = SourceIdentity(
                authority=str(row["authority"]),
                provider=str(row["provider"]),
                jurisdiction=str(row["jurisdiction"]),
                source_document_id=str(row["source_document_id"]),
                source_version=str(row["source_version"]),
                source_url=str(row["source_url"]) if row["source_url"] else None,
                retrieved_at=_parse_datetime(str(row["retrieved_at"])),
                raw_sha256=str(row["raw_sha256"]),
            )
            lineage_identifier = SQLiteRepository._ensure_lineage(
                connection, identity, str(row["retrieved_at"])
            )
            publication_date, status = _selection_publication_date(
                str(row["candidates_json"]),
                identity.source_document_id,
                identity.source_version,
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO lineage_source_documents(
                    lineage_id, source_document_row_id, selection_publication_date,
                    publication_date_status
                ) VALUES (?, ?, ?, ?)
                """,
                (lineage_identifier, str(row["id"]), publication_date, status),
            )

    @staticmethod
    def _ensure_lineage(
        connection: sqlite3.Connection,
        identity: SourceIdentity,
        created_at: str,
    ) -> str:
        identifier = document_lineage_id(
            identity.authority,
            identity.provider,
            identity.jurisdiction,
            identity.source_document_id,
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO document_lineages(
                id, authority, provider, jurisdiction, source_document_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                identifier,
                identity.authority,
                identity.provider,
                identity.jurisdiction,
                identity.source_document_id,
                created_at,
            ),
        )
        return identifier

    @classmethod
    def _link_source_lineage(
        cls,
        connection: sqlite3.Connection,
        source_row_id: str,
        identity: SourceIdentity,
        metadata: dict[str, Any],
    ) -> str:
        lineage_identifier = cls._ensure_lineage(
            connection, identity, _iso_utc(identity.retrieved_at)
        )
        candidates = canonical_json_bytes(metadata.get("candidate_metadata", [])).decode("utf-8")
        publication_date, status = _selection_publication_date(
            candidates, identity.source_document_id, identity.source_version
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO lineage_source_documents(
                lineage_id, source_document_row_id, selection_publication_date,
                publication_date_status
            ) VALUES (?, ?, ?, ?)
            """,
            (lineage_identifier, source_row_id, publication_date, status),
        )
        return lineage_identifier

    def schema_versions(self) -> tuple[str, ...]:
        """Return applied schema migrations in deterministic numeric order."""

        try:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT version FROM schema_migrations ORDER BY CAST(version AS INTEGER)"
                ).fetchall()
                return tuple(str(row[0]) for row in rows)
        except sqlite3.Error as exc:
            raise DatabaseFailure(f"SQLite schema version lookup failed: {exc}") from exc

    def store_utilization_list(self, value: UtilizationList) -> bool:
        """Persist one external utilization input without mixing it with source data."""

        canonical = canonical_json_bytes(value)
        digest = sha256_bytes(canonical)
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT canonical_json FROM utilization_lists WHERE id = ?",
                    (value.utilization_list_id,),
                ).fetchone()
                if existing is not None:
                    if bytes(existing["canonical_json"]) != canonical:
                        raise DatabaseFailure(
                            "utilization-list identity already stores different canonical data"
                        )
                    connection.rollback()
                    return False
                connection.execute(
                    """
                    INSERT INTO utilization_lists(
                        id, schema_version, jurisdiction, dataset_name, dataset_version,
                        measurement_year, metric, source_reference, retrieved_at,
                        license_or_terms_status, source_status, notes, canonical_json,
                        canonical_sha256
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        value.utilization_list_id,
                        value.schema_version,
                        value.jurisdiction,
                        value.dataset_name,
                        value.dataset_version,
                        value.measurement_year,
                        value.metric,
                        value.source_reference,
                        _iso_utc(value.retrieved_at),
                        value.license_or_terms_status,
                        value.source_status,
                        value.notes,
                        canonical,
                        digest,
                    ),
                )
                for entry in value.entries:
                    connection.execute(
                        """
                        INSERT INTO utilization_entries(
                            utilization_list_id, rank, ingredient_id, ingredient_name,
                            normalized_ingredient_name, metric_value, metric_unit,
                            source_row_identifier
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            value.utilization_list_id,
                            entry.rank,
                            ingredient_id(entry.normalized_ingredient_name),
                            entry.ingredient_name,
                            entry.normalized_ingredient_name,
                            entry.metric_value,
                            entry.metric_unit,
                            entry.source_row_identifier,
                        ),
                    )
                connection.commit()
                return True
        except DatabaseFailure:
            raise
        except sqlite3.Error as exc:
            raise DatabaseFailure(f"SQLite utilization-list storage failed: {exc}") from exc

    def list_utilization_lists(self) -> list[dict[str, Any]]:
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT ul.id AS utilization_list_id, ul.jurisdiction,
                           ul.dataset_name, ul.dataset_version, ul.measurement_year,
                           ul.metric, ul.source_status, ul.canonical_sha256,
                           COUNT(ue.rank) AS entry_count
                    FROM utilization_lists ul
                    LEFT JOIN utilization_entries ue ON ue.utilization_list_id = ul.id
                    GROUP BY ul.id
                    ORDER BY ul.id
                    """
                ).fetchall()
                return [dict(row) for row in rows]
        except sqlite3.Error as exc:
            raise DatabaseFailure(f"SQLite utilization-list lookup failed: {exc}") from exc

    def get_utilization_list(self, list_id: str) -> UtilizationList | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT canonical_json FROM utilization_lists WHERE id = ?", (list_id,)
                ).fetchone()
                if row is None:
                    return None
                payload = json.loads(bytes(row["canonical_json"]))
                return _utilization_list_from_stored(payload)
        except (json.JSONDecodeError, sqlite3.Error, TypeError, ValueError) as exc:
            raise DatabaseFailure(f"SQLite utilization-list read failed: {exc}") from exc

    def store_candidate_selection(
        self,
        *,
        utilization_list_id: str,
        query_text: str,
        connector_version: str,
        lookup: CandidateLookup,
        selection: CandidateSelection,
        status: DiscoveryStatus = DiscoveryStatus.DISCOVERED,
        evidence_manifest_sha256: str | None = None,
    ) -> bool:
        """Atomically retain exact lookup bytes, every candidate, and the decision."""

        raw_sha256 = sha256_bytes(lookup.raw_body)
        decision_canonical = canonical_json_bytes(selection)
        decision_sha256 = sha256_bytes(decision_canonical)
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT canonical_json FROM candidate_decisions WHERE id = ?",
                    (selection.decision_id,),
                ).fetchone()
                if existing is not None:
                    if bytes(existing["canonical_json"]) != decision_canonical:
                        raise DatabaseFailure(
                            "candidate-decision identity already stores different evidence"
                        )
                    self._write_discovery_details(
                        connection,
                        lookup,
                        selection.discovery_run_id,
                        evidence_manifest_sha256,
                    )
                    connection.commit()
                    return False
                connection.execute(
                    """
                    INSERT OR IGNORE INTO candidate_discovery_runs(
                        id, utilization_list_id, ingredient_id, query_text,
                        connector_version, source_url, retrieved_at, raw_metadata,
                        raw_metadata_sha256, status, error_category, diagnostic_message
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
                    """,
                    (
                        selection.discovery_run_id,
                        utilization_list_id,
                        selection.ingredient_id,
                        query_text,
                        connector_version,
                        lookup.source_url,
                        _iso_utc(lookup.retrieved_at),
                        lookup.raw_body,
                        raw_sha256,
                        status.value,
                    ),
                )
                self._write_discovery_details(
                    connection,
                    lookup,
                    selection.discovery_run_id,
                    evidence_manifest_sha256,
                )
                for candidate in selection.candidates:
                    connection.execute(
                        """
                        INSERT INTO label_candidates(
                            id, discovery_run_id, candidate_index, set_id,
                            source_version, title, published_date, generic_name,
                            brand_name, active_ingredients_json, dosage_form, route,
                            labeler, marketing_category, product_type, source_status,
                            source_url, raw_metadata_json, raw_metadata_sha256,
                            classifications_json, accepted_for_selection,
                            rejection_reasons_json, duplicate_of_candidate_id
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                                  ?, ?, ?, ?, ?)
                        """,
                        (
                            candidate.candidate_id,
                            candidate.discovery_run_id,
                            candidate.candidate_index,
                            candidate.set_id,
                            candidate.source_version,
                            candidate.title,
                            candidate.published_date,
                            candidate.generic_name,
                            candidate.brand_name,
                            canonical_json_bytes(candidate.active_ingredients).decode("utf-8"),
                            candidate.dosage_form,
                            candidate.route,
                            candidate.labeler,
                            candidate.marketing_category,
                            candidate.product_type,
                            candidate.source_status,
                            candidate.source_url,
                            canonical_json_bytes(candidate.raw_metadata).decode("utf-8"),
                            candidate.raw_metadata_sha256,
                            canonical_json_bytes(candidate.classifications).decode("utf-8"),
                            int(candidate.accepted_for_selection),
                            canonical_json_bytes(candidate.rejection_reasons).decode("utf-8"),
                            candidate.duplicate_of_candidate_id,
                        ),
                    )
                connection.execute(
                    """
                    INSERT INTO candidate_decisions(
                        id, discovery_run_id, ingredient_id, selection_rule_version,
                        selection_status, selected_candidate_id, selected_set_id,
                        selected_source_version, selection_reason, applied_rules_json,
                        manual_review_required, selection_scope, canonical_json,
                        canonical_sha256
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        selection.decision_id,
                        selection.discovery_run_id,
                        selection.ingredient_id,
                        selection.selection_rule_version,
                        selection.selection_status.value,
                        selection.selected_candidate_id,
                        selection.selected_set_id,
                        selection.selected_source_version,
                        selection.selection_reason,
                        canonical_json_bytes(selection.applied_rules).decode("utf-8"),
                        int(selection.manual_review_required),
                        selection.selection_scope,
                        decision_canonical,
                        decision_sha256,
                    ),
                )
                connection.commit()
                return True
        except DatabaseFailure:
            raise
        except sqlite3.Error as exc:
            raise DatabaseFailure(f"SQLite candidate evidence storage failed: {exc}") from exc

    @staticmethod
    def _write_discovery_details(
        connection: sqlite3.Connection,
        lookup: CandidateLookup,
        discovery_run_id: str,
        evidence_manifest_sha256: str | None,
    ) -> None:
        if lookup.snapshot_id is None:
            return
        canonical_request_json = canonical_json_bytes(lookup.canonical_request).decode("utf-8")
        canonical_request_sha256 = sha256_bytes(canonical_request_json.encode("utf-8"))
        response_bundle_sha256 = sha256_bytes(
            canonical_json_bytes(
                tuple((page.page_number, page.raw_sha256) for page in lookup.pages)
            )
        )
        logical_path = f"dailymed/discovery/{lookup.snapshot_id}"
        existing = connection.execute(
            "SELECT * FROM candidate_discovery_details WHERE discovery_run_id = ?",
            (discovery_run_id,),
        ).fetchone()
        expected = (
            lookup.snapshot_id,
            canonical_request_json,
            canonical_request_sha256,
            response_bundle_sha256,
            lookup.metadata_total_elements,
            lookup.retrieved_candidate_count or 0,
            lookup.total_pages,
            lookup.completeness.value,
            lookup.duplicate_count,
            lookup.metadata_conflict_count,
            lookup.diagnostic_message,
            canonical_json_bytes(lookup.failure_attempts).decode("utf-8"),
            evidence_manifest_sha256,
            logical_path,
        )
        if existing is not None:
            actual = (
                str(existing["snapshot_id"]),
                str(existing["canonical_request_json"]),
                str(existing["canonical_request_sha256"]),
                str(existing["response_bundle_sha256"]),
                (
                    int(existing["metadata_total_elements"])
                    if existing["metadata_total_elements"] is not None
                    else None
                ),
                int(existing["retrieved_elements"]),
                int(existing["total_pages"]) if existing["total_pages"] is not None else None,
                str(existing["completeness"]),
                int(existing["duplicate_count"]),
                int(existing["metadata_conflict_count"]),
                (
                    str(existing["diagnostic_message"])
                    if existing["diagnostic_message"] is not None
                    else None
                ),
                str(existing["failure_attempts_json"]),
                (
                    str(existing["evidence_manifest_sha256"])
                    if existing["evidence_manifest_sha256"] is not None
                    else None
                ),
                str(existing["evidence_logical_path"]),
            )
            if actual != expected:
                raise DatabaseFailure(
                    "live discovery snapshot identity already stores different evidence"
                )
        else:
            connection.execute(
                """
                INSERT INTO candidate_discovery_details(
                    discovery_run_id, snapshot_id, canonical_request_json,
                    canonical_request_sha256, response_bundle_sha256,
                    metadata_total_elements, retrieved_elements, total_pages,
                    completeness, duplicate_count, metadata_conflict_count,
                    diagnostic_message, failure_attempts_json,
                    evidence_manifest_sha256, evidence_logical_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (discovery_run_id, *expected),
            )
        for page in lookup.pages:
            row = connection.execute(
                """
                SELECT raw_response, raw_sha256
                FROM candidate_discovery_pages
                WHERE discovery_run_id = ? AND page_number = ?
                """,
                (discovery_run_id, page.page_number),
            ).fetchone()
            if row is not None:
                if (
                    bytes(row["raw_response"]) != page.raw_body
                    or str(row["raw_sha256"]) != page.raw_sha256
                ):
                    raise DatabaseFailure(
                        "live discovery page identity already stores different raw bytes"
                    )
                continue
            connection.execute(
                """
                INSERT INTO candidate_discovery_pages(
                    discovery_run_id, page_number, request_url, canonical_query_json,
                    response_url, http_status, content_type, retrieved_at, etag,
                    last_modified, raw_response, raw_sha256, response_size, attempts_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    discovery_run_id,
                    page.page_number,
                    page.request_url,
                    canonical_json_bytes(page.canonical_query).decode("utf-8"),
                    page.response_url,
                    page.status_code,
                    page.content_type,
                    _iso_utc(page.retrieved_at),
                    page.etag,
                    page.last_modified,
                    page.raw_body,
                    page.raw_sha256,
                    len(page.raw_body),
                    canonical_json_bytes(page.attempts).decode("utf-8"),
                ),
            )

    def record_candidate_lookup_failure(
        self,
        *,
        discovery_run_id: str,
        utilization_list_id: str,
        ingredient_id_value: str,
        query_text: str,
        connector_version: str,
        recorded_at: datetime,
        error_category: str,
        diagnostic_message: str,
    ) -> None:
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT OR REPLACE INTO candidate_discovery_runs(
                        id, utilization_list_id, ingredient_id, query_text,
                        connector_version, source_url, retrieved_at, raw_metadata,
                        raw_metadata_sha256, status, error_category, diagnostic_message
                    ) VALUES (?, ?, ?, ?, ?, '', ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        discovery_run_id,
                        utilization_list_id,
                        ingredient_id_value,
                        query_text,
                        connector_version,
                        _iso_utc(recorded_at),
                        b"",
                        sha256_bytes(b""),
                        DiscoveryStatus.LOOKUP_FAILED.value,
                        error_category,
                        diagnostic_message,
                    ),
                )
                connection.commit()
        except sqlite3.Error as exc:
            raise DatabaseFailure(f"SQLite candidate failure storage failed: {exc}") from exc

    def get_candidate_selection(self, decision_id: str) -> CandidateSelection | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT canonical_json FROM candidate_decisions WHERE id = ?",
                    (decision_id,),
                ).fetchone()
                if row is None:
                    return None
                return _candidate_selection_from_stored(
                    json.loads(bytes(row["canonical_json"]))
                )
        except (json.JSONDecodeError, sqlite3.Error, TypeError, ValueError) as exc:
            raise DatabaseFailure(f"SQLite candidate-decision read failed: {exc}") from exc

    def get_candidate_lookup(self, discovery_run_id: str) -> CandidateLookup | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT * FROM candidate_discovery_runs WHERE id = ?",
                    (discovery_run_id,),
                ).fetchone()
                if row is None or not row["raw_metadata"]:
                    return None
                raw_body = bytes(row["raw_metadata"])
                payload = json.loads(raw_body)
                candidates = connection.execute(
                    """
                    SELECT raw_metadata_json FROM label_candidates
                    WHERE discovery_run_id = ? ORDER BY candidate_index
                    """,
                    (discovery_run_id,),
                ).fetchall()
                values = tuple(
                    _daily_med_candidate_from_metadata(json.loads(item["raw_metadata_json"]))
                    for item in candidates
                )
                detail = connection.execute(
                    "SELECT * FROM candidate_discovery_details WHERE discovery_run_id = ?",
                    (discovery_run_id,),
                ).fetchone()
                page_rows = connection.execute(
                    """
                    SELECT * FROM candidate_discovery_pages
                    WHERE discovery_run_id = ? ORDER BY page_number
                    """,
                    (discovery_run_id,),
                ).fetchall()
                pages = tuple(
                    CandidateDiscoveryPage(
                        page_number=int(page["page_number"]),
                        request_url=str(page["request_url"]),
                        canonical_query=tuple(
                            (str(pair[0]), str(pair[1]))
                            for pair in json.loads(str(page["canonical_query_json"]))
                        ),
                        response_url=str(page["response_url"]),
                        status_code=int(page["http_status"]),
                        content_type=str(page["content_type"]),
                        retrieved_at=_parse_datetime(str(page["retrieved_at"])),
                        etag=str(page["etag"]) if page["etag"] is not None else None,
                        last_modified=(
                            str(page["last_modified"])
                            if page["last_modified"] is not None
                            else None
                        ),
                        raw_body=bytes(page["raw_response"]),
                        raw_sha256=str(page["raw_sha256"]),
                        attempts=_http_attempts_from_json(str(page["attempts_json"])),
                    )
                    for page in page_rows
                )
                return CandidateLookup(
                    candidates=values,
                    source_url=str(row["source_url"]),
                    retrieved_at=_parse_datetime(str(row["retrieved_at"])),
                    raw_body=raw_body,
                    payload=dict(payload),
                    pages=pages,
                    canonical_request=(
                        tuple(
                            (str(pair[0]), str(pair[1]))
                            for pair in json.loads(str(detail["canonical_request_json"]))
                        )
                        if detail is not None
                        else ()
                    ),
                    snapshot_id=str(detail["snapshot_id"]) if detail is not None else None,
                    metadata_total_elements=(
                        int(detail["metadata_total_elements"])
                        if detail is not None and detail["metadata_total_elements"] is not None
                        else None
                    ),
                    retrieved_candidate_count=(
                        int(detail["retrieved_elements"]) if detail is not None else None
                    ),
                    total_pages=(
                        int(detail["total_pages"])
                        if detail is not None and detail["total_pages"] is not None
                        else None
                    ),
                    completeness=(
                        DiscoveryCompleteness(str(detail["completeness"]))
                        if detail is not None
                        else DiscoveryCompleteness.UNKNOWN
                    ),
                    duplicate_count=(
                        int(detail["duplicate_count"]) if detail is not None else 0
                    ),
                    metadata_conflict_count=(
                        int(detail["metadata_conflict_count"])
                        if detail is not None
                        else 0
                    ),
                    diagnostic_message=(
                        str(detail["diagnostic_message"])
                        if detail is not None and detail["diagnostic_message"] is not None
                        else None
                    ),
                    failure_attempts=(
                        _http_attempts_from_json(str(detail["failure_attempts_json"]))
                        if detail is not None
                        else ()
                    ),
                )
        except (json.JSONDecodeError, sqlite3.Error, TypeError, ValueError) as exc:
            raise DatabaseFailure(f"SQLite candidate lookup reconstruction failed: {exc}") from exc

    def discovery_snapshot_integrity(self, snapshot_id: str) -> dict[str, bool]:
        try:
            with self._connect() as connection:
                detail = connection.execute(
                    """
                    SELECT cdd.*, cdr.connector_version
                    FROM candidate_discovery_details cdd
                    JOIN candidate_discovery_runs cdr ON cdr.id = cdd.discovery_run_id
                    WHERE cdd.snapshot_id = ?
                    """,
                    (snapshot_id,),
                ).fetchone()
                if detail is None:
                    return {
                        "found": False,
                        "canonical_request_hash": False,
                        "manifest_hash": False,
                        "response_bundle_hash": False,
                        "page_hashes": False,
                        "snapshot_identity": False,
                    }
                request_bytes = str(detail["canonical_request_json"]).encode("utf-8")
                request_ok = (
                    sha256_bytes(request_bytes) == str(detail["canonical_request_sha256"])
                )
                pages = connection.execute(
                    """
                    SELECT page_number, raw_response, raw_sha256, response_size
                    FROM candidate_discovery_pages
                    WHERE discovery_run_id = ? ORDER BY page_number
                    """,
                    (detail["discovery_run_id"],),
                ).fetchall()
                page_hashes_ok = all(
                    sha256_bytes(bytes(page["raw_response"])) == str(page["raw_sha256"])
                    and len(bytes(page["raw_response"])) == int(page["response_size"])
                    for page in pages
                )
                bundle = sha256_bytes(
                    canonical_json_bytes(
                        tuple(
                            (int(page["page_number"]), str(page["raw_sha256"]))
                            for page in pages
                        )
                    )
                )
                canonical_request = tuple(
                    (str(pair[0]), str(pair[1]))
                    for pair in json.loads(str(detail["canonical_request_json"]))
                )
                page_hashes = tuple(
                    (int(page["page_number"]), str(page["raw_sha256"]))
                    for page in pages
                )
                failure_attempts = _http_attempts_from_json(
                    str(detail["failure_attempts_json"])
                )
                terminal_fingerprint = ""
                if detail["diagnostic_message"] is not None:
                    terminal_fingerprint = sha256_bytes(
                        canonical_json_bytes(
                            {
                                "completeness": str(detail["completeness"]),
                                "diagnostic": str(detail["diagnostic_message"]),
                                "failure_attempts": failure_attempts,
                            }
                        )
                    )
                identity_ok = (
                    live_candidate_snapshot_id(
                        canonical_request,
                        page_hashes,
                        connector_version=str(detail["connector_version"]),
                        terminal_fingerprint=terminal_fingerprint,
                    )
                    == snapshot_id
                )
                manifest_payload = {
                    "canonical_request": canonical_request,
                    "completeness": str(detail["completeness"]),
                    "connector_version": str(detail["connector_version"]),
                    "duplicate_count": int(detail["duplicate_count"]),
                    "metadata_conflict_count": int(detail["metadata_conflict_count"]),
                    "metadata_total_elements": (
                        int(detail["metadata_total_elements"])
                        if detail["metadata_total_elements"] is not None
                        else None
                    ),
                    "page_hashes": page_hashes,
                    "retrieved_candidate_count": int(detail["retrieved_elements"]),
                    "snapshot_id": snapshot_id,
                    "snapshot_version": LIVE_SNAPSHOT_VERSION,
                    "total_pages": (
                        int(detail["total_pages"])
                        if detail["total_pages"] is not None
                        else None
                    ),
                }
                manifest_ok = (
                    detail["evidence_manifest_sha256"] is not None
                    and sha256_bytes(canonical_json_bytes(manifest_payload))
                    == str(detail["evidence_manifest_sha256"])
                )
                return {
                    "found": True,
                    "canonical_request_hash": request_ok,
                    "manifest_hash": manifest_ok,
                    "response_bundle_hash": bundle == str(detail["response_bundle_sha256"]),
                    "page_hashes": page_hashes_ok,
                    "snapshot_identity": identity_ok,
                }
        except (json.JSONDecodeError, sqlite3.Error, TypeError, ValueError) as exc:
            raise DatabaseFailure(f"SQLite discovery integrity check failed: {exc}") from exc

    def candidates_for_ingredient(self, normalized_name: str) -> list[dict[str, Any]]:
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT cdr.query_text, cdr.retrieved_at, cdr.raw_metadata_sha256,
                           cd.selection_status, cd.selection_reason,
                           cd.manual_review_required, lc.*
                    FROM utilization_entries ue
                    JOIN candidate_discovery_runs cdr
                      ON cdr.utilization_list_id = ue.utilization_list_id
                     AND cdr.ingredient_id = ue.ingredient_id
                    JOIN candidate_decisions cd ON cd.discovery_run_id = cdr.id
                    JOIN label_candidates lc ON lc.discovery_run_id = cdr.id
                    WHERE ue.normalized_ingredient_name = ?
                    ORDER BY cdr.retrieved_at DESC, cdr.id, lc.candidate_index
                    """,
                    (normalized_name,),
                ).fetchall()
                result: list[dict[str, Any]] = []
                for row in rows:
                    item = dict(row)
                    for key in (
                        "active_ingredients_json",
                        "classifications_json",
                        "rejection_reasons_json",
                        "raw_metadata_json",
                    ):
                        if item.get(key) is not None:
                            item[key.removesuffix("_json")] = json.loads(item.pop(key))
                    result.append(item)
                return result
        except (json.JSONDecodeError, sqlite3.Error) as exc:
            raise DatabaseFailure(f"SQLite candidate audit lookup failed: {exc}") from exc

    def create_batch_run(self, run: BatchRun, items: tuple[BatchItem, ...]) -> bool:
        """Create a resumable batch and its rank-ordered item state atomically."""

        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT id FROM batch_runs WHERE id = ?", (run.batch_run_id,)
                ).fetchone()
                if existing is not None:
                    connection.rollback()
                    return False
                connection.execute(
                    """
                    INSERT INTO batch_runs(
                        id, utilization_list_id, selection_rule_version,
                        connector_version, parser_version, schema_version,
                        mapping_version, started_at, completed_at, status,
                        requested_count, selected_count, fetched_count,
                        ingested_count, verified_count, quarantined_count,
                        unresolved_count, failed_count, canonical_report_sha256
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    _batch_run_values(run),
                )
                for item in sorted(items, key=lambda value: value.rank):
                    self._write_batch_item(connection, item, replace_existing=False)
                connection.commit()
                return True
        except sqlite3.Error as exc:
            raise DatabaseFailure(f"SQLite batch creation failed: {exc}") from exc

    def save_batch_item(self, item: BatchItem) -> None:
        """Commit one item independently so later item failures do not roll it back."""

        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                self._write_batch_item(connection, item, replace_existing=True)
                connection.commit()
        except sqlite3.Error as exc:
            raise DatabaseFailure(f"SQLite batch-item storage failed: {exc}") from exc

    @staticmethod
    def _write_batch_item(
        connection: sqlite3.Connection,
        item: BatchItem,
        *,
        replace_existing: bool,
    ) -> None:
        values = _batch_item_values(item)
        if replace_existing:
            cursor = connection.execute(
                """
                UPDATE batch_items SET
                    ingredient_id = ?, ingredient_name = ?, discovery_status = ?,
                    selection_status = ?, selected_set_id = ?, selected_source_version = ?,
                    document_id = ?, raw_sha256 = ?, ingestion_status = ?,
                    verification_status = ?, quarantine_record_id = ?, error_category = ?,
                    diagnostic_message = ?, manual_review_required = ?,
                    parser_compatibility_status = ?, source_section_count = ?,
                    mapped_section_count = ?, unmapped_section_count = ?,
                    unsupported_structure_count = ?, empty_section_count = ?,
                    parser_warnings_json = ?, discovery_run_id = ?, decision_id = ?,
                    retry_eligible = ?, query_text = ?, candidate_count = ?,
                    selection_reason = ?
                WHERE batch_run_id = ? AND rank = ?
                """,
                (*values[2:], *values[:2]),
            )
            if cursor.rowcount == 1:
                return
        connection.execute(
            """
            INSERT INTO batch_items(
                batch_run_id, rank, ingredient_id, ingredient_name,
                discovery_status, selection_status, selected_set_id,
                selected_source_version, document_id, raw_sha256,
                ingestion_status, verification_status, quarantine_record_id,
                error_category, diagnostic_message, manual_review_required,
                parser_compatibility_status, source_section_count,
                mapped_section_count, unmapped_section_count,
                unsupported_structure_count, empty_section_count,
                parser_warnings_json, discovery_run_id, decision_id,
                retry_eligible, query_text, candidate_count, selection_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                      ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            values,
        )

    def save_parser_compatibility(
        self,
        item: BatchItem,
        *,
        quarantine_reason: str | None = None,
    ) -> None:
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT OR REPLACE INTO parser_compatibility_results(
                        batch_run_id, rank, document_id, status,
                        source_section_count, mapped_section_count,
                        unmapped_section_count, unsupported_structure_count,
                        empty_section_count, parser_warnings_json, quarantine_reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.batch_run_id,
                        item.rank,
                        item.document_id,
                        item.parser_compatibility_status.value,
                        item.source_section_count,
                        item.mapped_section_count,
                        item.unmapped_section_count,
                        item.unsupported_structure_count,
                        item.empty_section_count,
                        canonical_json_bytes(item.parser_warnings).decode("utf-8"),
                        quarantine_reason,
                    ),
                )
                connection.commit()
        except sqlite3.Error as exc:
            raise DatabaseFailure(f"SQLite parser compatibility storage failed: {exc}") from exc

    def update_batch_run(self, run: BatchRun) -> None:
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    """
                    UPDATE batch_runs SET
                        completed_at = ?, status = ?, requested_count = ?,
                        selected_count = ?, fetched_count = ?, ingested_count = ?,
                        verified_count = ?, quarantined_count = ?, unresolved_count = ?,
                        failed_count = ?, canonical_report_sha256 = ?
                    WHERE id = ?
                    """,
                    (
                        _iso_utc(run.completed_at) if run.completed_at else None,
                        run.status.value,
                        run.requested_count,
                        run.selected_count,
                        run.fetched_count,
                        run.ingested_count,
                        run.verified_count,
                        run.quarantined_count,
                        run.unresolved_count,
                        run.failed_count,
                        run.canonical_report_sha256,
                        run.batch_run_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise DatabaseFailure("batch run was not found for update")
                connection.commit()
        except DatabaseFailure:
            raise
        except sqlite3.Error as exc:
            raise DatabaseFailure(f"SQLite batch update failed: {exc}") from exc

    def get_batch_run(self, run_id: str) -> BatchRun | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT * FROM batch_runs WHERE id = ?", (run_id,)
                ).fetchone()
                return _batch_run_from_row(row) if row is not None else None
        except (sqlite3.Error, ValueError) as exc:
            raise DatabaseFailure(f"SQLite batch lookup failed: {exc}") from exc

    def find_batch_run(
        self,
        *,
        utilization_list_id: str,
        selection_rule_version: str,
        connector_version: str,
        parser_version: str,
        schema_version: str,
        mapping_version: str,
    ) -> BatchRun | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT * FROM batch_runs
                    WHERE utilization_list_id = ? AND selection_rule_version = ?
                      AND connector_version = ? AND parser_version = ?
                      AND schema_version = ? AND mapping_version = ?
                    """,
                    (
                        utilization_list_id,
                        selection_rule_version,
                        connector_version,
                        parser_version,
                        schema_version,
                        mapping_version,
                    ),
                ).fetchone()
                return _batch_run_from_row(row) if row is not None else None
        except (sqlite3.Error, ValueError) as exc:
            raise DatabaseFailure(f"SQLite batch identity lookup failed: {exc}") from exc

    def get_batch_items(self, run_id: str) -> tuple[BatchItem, ...]:
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT * FROM batch_items WHERE batch_run_id = ? ORDER BY rank",
                    (run_id,),
                ).fetchall()
                return tuple(_batch_item_from_row(row) for row in rows)
        except (json.JSONDecodeError, sqlite3.Error, ValueError) as exc:
            raise DatabaseFailure(f"SQLite batch-item lookup failed: {exc}") from exc

    def create_live_batch_run(
        self,
        run: BatchRun,
        items: tuple[BatchItem, ...],
        *,
        observation_token: str,
    ) -> bool:
        """Create a distinct live observation in the additive schema-v4 tables."""

        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                if connection.execute(
                    "SELECT id FROM live_batch_runs WHERE id = ?", (run.batch_run_id,)
                ).fetchone() is not None:
                    connection.rollback()
                    return False
                connection.execute(
                    """
                    INSERT INTO live_batch_runs(
                        id, observation_token, utilization_list_id,
                        selection_rule_version, connector_version, parser_version,
                        schema_version, mapping_version, started_at, completed_at,
                        status, requested_count, selected_count, fetched_count,
                        ingested_count, verified_count, quarantined_count,
                        unresolved_count, failed_count, canonical_report_sha256,
                        observation_mode, snapshot_manifest_sha256,
                        discovery_complete_count, manual_review_count,
                        no_candidate_count, fetch_failure_count, parser_failure_count,
                        database_schema_version
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                              ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (run.batch_run_id, observation_token, *_live_batch_run_values(run)),
                )
                for item in sorted(items, key=lambda value: value.rank):
                    self._write_live_batch_item(connection, item, replace_existing=False)
                connection.commit()
                return True
        except sqlite3.Error as exc:
            raise DatabaseFailure(f"SQLite live-batch creation failed: {exc}") from exc

    def save_live_batch_item(self, item: BatchItem) -> None:
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                self._write_live_batch_item(connection, item, replace_existing=True)
                connection.commit()
        except sqlite3.Error as exc:
            raise DatabaseFailure(f"SQLite live-batch item storage failed: {exc}") from exc

    @staticmethod
    def _write_live_batch_item(
        connection: sqlite3.Connection,
        item: BatchItem,
        *,
        replace_existing: bool,
    ) -> None:
        values = _live_batch_item_values(item)
        if replace_existing:
            cursor = connection.execute(
                """
                UPDATE live_batch_items SET
                    ingredient_id = ?, ingredient_name = ?, discovery_status = ?,
                    selection_status = ?, selected_set_id = ?, selected_source_version = ?,
                    document_id = ?, raw_sha256 = ?, ingestion_status = ?,
                    verification_status = ?, quarantine_record_id = ?, error_category = ?,
                    diagnostic_message = ?, manual_review_required = ?,
                    parser_compatibility_status = ?, source_section_count = ?,
                    mapped_section_count = ?, unmapped_section_count = ?,
                    unsupported_structure_count = ?, empty_section_count = ?,
                    parser_warnings_json = ?, discovery_run_id = ?, decision_id = ?,
                    retry_eligible = ?, query_text = ?, candidate_count = ?,
                    selection_reason = ?, snapshot_id = ?,
                    metadata_total_candidate_count = ?, retrieved_candidate_count = ?,
                    eligible_candidate_count = ?, discovery_completeness = ?,
                    evidence_verification_status = ?
                WHERE batch_run_id = ? AND rank = ?
                """,
                (*values[2:], *values[:2]),
            )
            if cursor.rowcount == 1:
                return
        connection.execute(
            """
            INSERT INTO live_batch_items(
                batch_run_id, rank, ingredient_id, ingredient_name,
                discovery_status, selection_status, selected_set_id,
                selected_source_version, document_id, raw_sha256,
                ingestion_status, verification_status, quarantine_record_id,
                error_category, diagnostic_message, manual_review_required,
                parser_compatibility_status, source_section_count,
                mapped_section_count, unmapped_section_count,
                unsupported_structure_count, empty_section_count,
                parser_warnings_json, discovery_run_id, decision_id,
                retry_eligible, query_text, candidate_count, selection_reason,
                snapshot_id, metadata_total_candidate_count,
                retrieved_candidate_count, eligible_candidate_count,
                discovery_completeness, evidence_verification_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                      ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            values,
        )

    def update_live_batch_run(self, run: BatchRun) -> None:
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    """
                    UPDATE live_batch_runs SET
                        completed_at = ?, status = ?, requested_count = ?,
                        selected_count = ?, fetched_count = ?, ingested_count = ?,
                        verified_count = ?, quarantined_count = ?, unresolved_count = ?,
                        failed_count = ?, canonical_report_sha256 = ?,
                        observation_mode = ?, snapshot_manifest_sha256 = ?,
                        discovery_complete_count = ?, manual_review_count = ?,
                        no_candidate_count = ?, fetch_failure_count = ?,
                        parser_failure_count = ?, database_schema_version = ?
                    WHERE id = ?
                    """,
                    (
                        _iso_utc(run.completed_at) if run.completed_at else None,
                        run.status.value,
                        run.requested_count,
                        run.selected_count,
                        run.fetched_count,
                        run.ingested_count,
                        run.verified_count,
                        run.quarantined_count,
                        run.unresolved_count,
                        run.failed_count,
                        run.canonical_report_sha256,
                        run.observation_mode,
                        run.snapshot_manifest_sha256,
                        run.discovery_complete_count,
                        run.manual_review_count,
                        run.no_candidate_count,
                        run.fetch_failure_count,
                        run.parser_failure_count,
                        run.database_schema_version,
                        run.batch_run_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise DatabaseFailure("live batch run was not found for update")
                connection.commit()
        except DatabaseFailure:
            raise
        except sqlite3.Error as exc:
            raise DatabaseFailure(f"SQLite live-batch update failed: {exc}") from exc

    def get_live_batch_run(self, run_id: str) -> BatchRun | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT * FROM live_batch_runs WHERE id = ?", (run_id,)
                ).fetchone()
                return _live_batch_run_from_row(row) if row is not None else None
        except (sqlite3.Error, ValueError) as exc:
            raise DatabaseFailure(f"SQLite live-batch lookup failed: {exc}") from exc

    def get_live_batch_items(self, run_id: str) -> tuple[BatchItem, ...]:
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT * FROM live_batch_items WHERE batch_run_id = ? ORDER BY rank",
                    (run_id,),
                ).fetchall()
                return tuple(_live_batch_item_from_row(row) for row in rows)
        except (json.JSONDecodeError, sqlite3.Error, ValueError) as exc:
            raise DatabaseFailure(f"SQLite live-batch item lookup failed: {exc}") from exc

    def store_live_batch_artifact(self, report: BatchReport) -> BatchArtifactResult:
        canonical = canonical_batch_report_json_bytes(report)
        digest = sha256_bytes(canonical)
        identifier = batch_artifact_id(
            report.batch_run.batch_run_id,
            report.report_version,
            digest,
        )
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    """
                    SELECT canonical_json, canonical_sha256
                    FROM live_batch_artifacts WHERE id = ?
                    """,
                    (identifier,),
                ).fetchone()
                if existing is not None:
                    if (
                        bytes(existing["canonical_json"]) != canonical
                        or str(existing["canonical_sha256"]) != digest
                    ):
                        raise BatchArtifactConflict(
                            "live batch artifact identity stores different canonical bytes"
                        )
                    connection.rollback()
                    return BatchArtifactResult(report, canonical, digest, True)
                connection.execute(
                    """
                    INSERT INTO live_batch_artifacts(
                        id, batch_run_id, report_version, canonical_json,
                        canonical_sha256, generated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        identifier,
                        report.batch_run.batch_run_id,
                        report.report_version,
                        canonical,
                        digest,
                        _iso_utc(report.generated_at),
                    ),
                )
                connection.execute(
                    "UPDATE live_batch_runs SET canonical_report_sha256 = ? WHERE id = ?",
                    (digest, report.batch_run.batch_run_id),
                )
                connection.commit()
                return BatchArtifactResult(report, canonical, digest, False)
        except BatchArtifactConflict:
            raise
        except sqlite3.Error as exc:
            raise DatabaseFailure(f"SQLite live-batch artifact storage failed: {exc}") from exc

    def live_batch_artifact_integrity(self, run_id: str) -> dict[str, bool]:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT * FROM live_batch_artifacts
                    WHERE batch_run_id = ? ORDER BY rowid DESC LIMIT 1
                    """,
                    (run_id,),
                ).fetchone()
                if row is None:
                    return {
                        "found": False,
                        "hash_matches": False,
                        "item_ordered": False,
                        "run_hash_matches": False,
                    }
                canonical = bytes(row["canonical_json"])
                payload = json.loads(canonical)
                ranks = [int(item["rank"]) for item in payload.get("items", [])]
                run = self.get_live_batch_run(run_id)
                return {
                    "found": True,
                    "hash_matches": sha256_bytes(canonical) == str(row["canonical_sha256"]),
                    "item_ordered": ranks == sorted(ranks) and len(ranks) == len(set(ranks)),
                    "run_hash_matches": bool(
                        run and run.canonical_report_sha256 == str(row["canonical_sha256"])
                    ),
                }
        except (json.JSONDecodeError, sqlite3.Error, TypeError, ValueError) as exc:
            raise DatabaseFailure(f"SQLite live-batch artifact verification failed: {exc}") from exc

    def store_batch_artifact(self, report: BatchReport) -> BatchArtifactResult:
        canonical = canonical_batch_report_json_bytes(report)
        digest = sha256_bytes(canonical)
        identifier = batch_artifact_id(
            report.batch_run.batch_run_id,
            report.report_version,
            digest,
        )
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT canonical_json, canonical_sha256 FROM batch_artifacts WHERE id = ?",
                    (identifier,),
                ).fetchone()
                if existing is not None:
                    if (
                        bytes(existing["canonical_json"]) != canonical
                        or str(existing["canonical_sha256"]) != digest
                    ):
                        raise BatchArtifactConflict(
                            "batch artifact identity already stores different canonical bytes"
                        )
                    connection.rollback()
                    return BatchArtifactResult(report, canonical, digest, True)
                connection.execute(
                    """
                    INSERT INTO batch_artifacts(
                        id, batch_run_id, report_version, canonical_json,
                        canonical_sha256, generated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        identifier,
                        report.batch_run.batch_run_id,
                        report.report_version,
                        canonical,
                        digest,
                        _iso_utc(report.generated_at),
                    ),
                )
                connection.execute(
                    "UPDATE batch_runs SET canonical_report_sha256 = ? WHERE id = ?",
                    (digest, report.batch_run.batch_run_id),
                )
                connection.commit()
                return BatchArtifactResult(report, canonical, digest, False)
        except BatchArtifactConflict:
            raise
        except sqlite3.Error as exc:
            raise DatabaseFailure(f"SQLite batch-artifact storage failed: {exc}") from exc

    def get_batch_artifact(self, artifact_or_run_id: str) -> dict[str, Any] | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT * FROM batch_artifacts
                    WHERE id = ? OR batch_run_id = ?
                    ORDER BY rowid DESC LIMIT 1
                    """,
                    (artifact_or_run_id, artifact_or_run_id),
                ).fetchone()
                return dict(row) if row is not None else None
        except sqlite3.Error as exc:
            raise DatabaseFailure(f"SQLite batch-artifact lookup failed: {exc}") from exc

    def batch_artifact_integrity(self, artifact_or_run_id: str) -> dict[str, Any]:
        artifact = self.get_batch_artifact(artifact_or_run_id)
        if artifact is None:
            return {
                "found": False,
                "hash_matches": False,
                "item_ordered": False,
                "run_hash_matches": False,
            }
        canonical = bytes(artifact["canonical_json"])
        payload = json.loads(canonical)
        ranks = [int(item["rank"]) for item in payload.get("items", [])]
        run = self.get_batch_run(str(artifact["batch_run_id"]))
        return {
            "found": True,
            "hash_matches": sha256_bytes(canonical) == artifact["canonical_sha256"],
            "item_ordered": ranks == sorted(ranks) and len(ranks) == len(set(ranks)),
            "run_hash_matches": bool(
                run and run.canonical_report_sha256 == artifact["canonical_sha256"]
            ),
        }

    def start_ingestion_run(self, identity: SourceIdentity, started_at: datetime) -> int:
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO ingestion_runs(
                        started_at, status, selected_source_identity_json
                    ) VALUES (?, 'started', ?)
                    """,
                    (
                        _iso_utc(started_at),
                        canonical_json_bytes(source_identity_payload(identity)).decode("utf-8"),
                    ),
                )
                connection.commit()
                if cursor.lastrowid is None:  # pragma: no cover - sqlite contract guard
                    raise DatabaseFailure("SQLite did not return an ingestion run ID")
                return int(cursor.lastrowid)
        except sqlite3.Error as exc:
            raise DatabaseFailure(f"could not start ingestion run: {exc}") from exc

    def fail_ingestion_run(
        self,
        run_id: int,
        *,
        completed_at: datetime,
        error_category: str,
        error_message: str,
    ) -> None:
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    """
                    UPDATE ingestion_runs
                    SET completed_at = ?, status = 'failed', error_category = ?, error_message = ?
                    WHERE id = ?
                    """,
                    (_iso_utc(completed_at), error_category, error_message, run_id),
                )
                if cursor.rowcount != 1:
                    raise DatabaseFailure(f"ingestion run {run_id} does not exist")
                connection.commit()
        except sqlite3.Error as exc:
            raise DatabaseFailure(f"could not record ingestion failure: {exc}") from exc

    def store_history_snapshot(self, history: DailyMedHistory) -> tuple[str, bool]:
        """Persist the exact official history response and parsed entries atomically."""

        raw_sha256 = sha256_bytes(history.raw_body)
        lineage_identifier = document_lineage_id(
            "FDA", "DailyMed", "United States", history.source_document_id
        )
        snapshot_identifier = history_snapshot_id(lineage_identifier, raw_sha256)
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO document_lineages(
                            id, authority, provider, jurisdiction, source_document_id, created_at
                        ) VALUES (?, 'FDA', 'DailyMed', 'United States', ?, ?)
                        """,
                        (
                            lineage_identifier,
                            history.source_document_id,
                            _iso_utc(history.retrieved_at),
                        ),
                    )
                    existing = connection.execute(
                        "SELECT raw_json FROM lineage_history_snapshots WHERE id = ?",
                        (snapshot_identifier,),
                    ).fetchone()
                    if existing is not None:
                        if bytes(existing["raw_json"]) != history.raw_body:
                            raise DiffArtifactConflict(
                                "history snapshot identity already has different raw bytes"
                            )
                        connection.commit()
                        return snapshot_identifier, False
                    connection.execute(
                        """
                        INSERT INTO lineage_history_snapshots(
                            id, lineage_id, source_url, retrieved_at, raw_sha256, raw_json
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            snapshot_identifier,
                            lineage_identifier,
                            history.source_url,
                            _iso_utc(history.retrieved_at),
                            raw_sha256,
                            history.raw_body,
                        ),
                    )
                    for entry in history.entries:
                        connection.execute(
                            """
                            INSERT INTO lineage_history_entries(
                                history_snapshot_id, lineage_id, source_version,
                                publication_date, publication_date_text, sequence_index
                            ) VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (
                                snapshot_identifier,
                                lineage_identifier,
                                entry.source_version,
                                entry.published_date.isoformat()
                                if entry.published_date is not None
                                else None,
                                entry.published_date_text,
                                entry.sequence_index,
                            ),
                        )
                    connection.commit()
                    return snapshot_identifier, True
                except Exception:
                    connection.rollback()
                    raise
        except ODDError:
            raise
        except sqlite3.Error as exc:
            raise DatabaseFailure(f"SQLite history snapshot transaction failed: {exc}") from exc

    def get_history_entries(
        self,
        lineage_identifier: str,
        snapshot_identifier: str | None = None,
    ) -> tuple[str | None, tuple[DailyMedHistoryEntry, ...]]:
        try:
            with self._connect() as connection:
                selected_snapshot = snapshot_identifier
                if selected_snapshot is None:
                    row = connection.execute(
                        """
                        SELECT id FROM lineage_history_snapshots
                        WHERE lineage_id = ? ORDER BY retrieved_at DESC, id DESC LIMIT 1
                        """,
                        (lineage_identifier,),
                    ).fetchone()
                    selected_snapshot = str(row["id"]) if row is not None else None
                if selected_snapshot is None:
                    return None, ()
                rows = connection.execute(
                    """
                    SELECT source_version, publication_date, publication_date_text, sequence_index
                    FROM lineage_history_entries
                    WHERE lineage_id = ? AND history_snapshot_id = ?
                    ORDER BY sequence_index
                    """,
                    (lineage_identifier, selected_snapshot),
                ).fetchall()
                entries = tuple(
                    DailyMedHistoryEntry(
                        source_version=str(row["source_version"]),
                        published_date=date.fromisoformat(str(row["publication_date"]))
                        if row["publication_date"]
                        else None,
                        published_date_text=str(row["publication_date_text"]),
                        sequence_index=int(row["sequence_index"]),
                    )
                    for row in rows
                )
                return selected_snapshot, entries
        except (sqlite3.Error, ValueError) as exc:
            raise DatabaseFailure(f"SQLite lineage history lookup failed: {exc}") from exc

    def get_lineage_id_for_document(self, document_id: str) -> str:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT lsd.lineage_id
                    FROM regulatory_documents rd
                    JOIN lineage_source_documents lsd
                      ON lsd.source_document_row_id = rd.source_document_row_id
                    WHERE rd.id = ?
                    """,
                    (document_id,),
                ).fetchone()
                if row is None:
                    raise SourceNotFound(
                        "document lineage was not found", details={"document_id": document_id}
                    )
                return str(row["lineage_id"])
        except ODDError:
            raise
        except sqlite3.Error as exc:
            raise DatabaseFailure(f"SQLite document lineage lookup failed: {exc}") from exc

    def resolve_document_version(self, set_id: str, source_version: str) -> str:
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT rd.id, rd.parser_version, rd.schema_version, rd.mapping_version
                    FROM regulatory_documents rd
                    JOIN source_documents sd ON sd.id = rd.source_document_row_id
                    WHERE lower(sd.source_document_id) = lower(?) AND sd.source_version = ?
                    ORDER BY rd.id
                    """,
                    (set_id, source_version),
                ).fetchall()
                if not rows:
                    raise SourceNotFound(
                        "no normalized document exists for the requested source version",
                        details={"set_id": set_id, "source_version": source_version},
                    )
                if len(rows) > 1:
                    raise AmbiguousDocumentVersion(
                        "multiple parser/schema/mapping outputs exist for the source version",
                        details={
                            "set_id": set_id,
                            "source_version": source_version,
                            "documents": [dict(row) for row in rows],
                        },
                    )
                return str(rows[0]["id"])
        except ODDError:
            raise
        except sqlite3.Error as exc:
            raise DatabaseFailure(f"SQLite version resolution failed: {exc}") from exc

    def find_lineages(
        self,
        *,
        set_id: str | None = None,
        query: str | None = None,
    ) -> list[dict[str, Any]]:
        if set_id is None and query is None:
            raise ValueError("set_id or query is required")
        try:
            with self._connect() as connection:
                if set_id is not None:
                    rows = connection.execute(
                        """
                        SELECT * FROM document_lineages
                        WHERE lower(source_document_id) = lower(?) ORDER BY source_document_id
                        """,
                        (set_id,),
                    ).fetchall()
                else:
                    pattern = f"%{(query or '').casefold().strip()}%"
                    rows = connection.execute(
                        """
                        SELECT DISTINCT dl.*
                        FROM document_lineages dl
                        JOIN lineage_source_documents lsd ON lsd.lineage_id = dl.id
                        JOIN regulatory_documents rd
                          ON rd.source_document_row_id = lsd.source_document_row_id
                        LEFT JOIN document_products dp ON dp.document_id = rd.id
                        LEFT JOIN products p ON p.id = dp.product_id
                        LEFT JOIN document_ingredients di ON di.document_id = rd.id
                        LEFT JOIN ingredients i ON i.id = di.ingredient_id
                        WHERE lower(COALESCE(rd.generic_name, '')) LIKE ?
                           OR lower(COALESCE(p.brand_name, '')) LIKE ?
                           OR lower(COALESCE(i.name, '')) LIKE ?
                           OR lower(rd.title) LIKE ?
                        ORDER BY dl.source_document_id
                        """,
                        (pattern, pattern, pattern, pattern),
                    ).fetchall()
                return [dict(row) for row in rows]
        except sqlite3.Error as exc:
            raise DatabaseFailure(f"SQLite lineage search failed: {exc}") from exc

    def get_lineage_documents(self, lineage_identifier: str) -> list[dict[str, Any]]:
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT rd.id AS document_id, rd.source_instance_id, rd.effective_date,
                           rd.title, rd.generic_name, rd.brand_names_json,
                           rd.parser_version, rd.schema_version, rd.mapping_version,
                           sd.id AS source_document_row_id, sd.source_version,
                           sd.raw_sha256, sd.raw_path, sd.retrieved_at,
                           lsd.selection_publication_date,
                           lsd.publication_date_status
                    FROM lineage_source_documents lsd
                    JOIN source_documents sd ON sd.id = lsd.source_document_row_id
                    JOIN regulatory_documents rd ON rd.source_document_row_id = sd.id
                    WHERE lsd.lineage_id = ?
                    ORDER BY
                      CASE WHEN sd.source_version NOT GLOB '*[^0-9]*' THEN 0 ELSE 1 END,
                      CASE WHEN sd.source_version NOT GLOB '*[^0-9]*'
                           THEN CAST(sd.source_version AS INTEGER) END,
                      sd.source_version, rd.id
                    """,
                    (lineage_identifier,),
                ).fetchall()
                result: list[dict[str, Any]] = []
                for row in rows:
                    item = dict(row)
                    item["brand_names"] = json.loads(item.pop("brand_names_json"))
                    publication_date, publication_source = self._publication_metadata(
                        str(item["document_id"])
                    )
                    item["publication_date"] = (
                        publication_date.isoformat() if publication_date else None
                    )
                    item["publication_date_source"] = publication_source
                    result.append(item)
                return result
        except (sqlite3.Error, json.JSONDecodeError) as exc:
            raise DatabaseFailure(f"SQLite lineage document lookup failed: {exc}") from exc

    def store_diff(self, diff: DocumentDiff) -> tuple[bytes, str, bool]:
        canonical = canonical_diff_json_bytes(diff)
        canonical_sha256 = sha256_bytes(canonical)
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    lineage = connection.execute(
                        """
                        SELECT id FROM document_lineages
                        WHERE authority = ? AND provider = ? AND jurisdiction = ?
                          AND lower(source_document_id) = lower(?)
                        """,
                        _lineage_lookup_parameters(diff),
                    ).fetchone()
                    if lineage is None:
                        raise SourceNotFound(
                            "diff source lineage was not found",
                            details={"source_document_id": diff.source_document_id},
                        )
                    lineage_identifier = str(lineage["id"])
                    edge_identifier = self._store_version_edge(
                        connection, lineage_identifier, diff
                    )
                    existing = connection.execute(
                        "SELECT canonical_json, canonical_sha256 FROM document_diffs WHERE id = ?",
                        (diff.diff_id,),
                    ).fetchone()
                    if existing is not None:
                        if (
                            bytes(existing["canonical_json"]) != canonical
                            or str(existing["canonical_sha256"]) != canonical_sha256
                        ):
                            raise DiffArtifactConflict(
                                "diff identity already has a different canonical artifact",
                                details={"diff_id": diff.diff_id},
                            )
                        connection.commit()
                        return canonical, canonical_sha256, False

                    connection.execute(
                        """
                        INSERT INTO document_diffs(
                            id, lineage_id, version_edge_id, old_document_id, new_document_id,
                            old_source_version, new_source_version, old_raw_sha256,
                            new_raw_sha256, change_cause, ordering_status,
                            diff_engine_version, canonical_json, canonical_sha256, generated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            diff.diff_id,
                            lineage_identifier,
                            edge_identifier,
                            diff.old_document_id,
                            diff.new_document_id,
                            diff.old_source_version,
                            diff.new_source_version,
                            diff.old_raw_sha256,
                            diff.new_raw_sha256,
                            diff.change_cause.value,
                            diff.ordering_status.value,
                            diff.diff_engine_version,
                            canonical,
                            canonical_sha256,
                            _iso_utc(diff.generated_at or datetime.now(UTC)),
                        ),
                    )
                    for sequence_index, section in enumerate(diff.section_diffs):
                        section_json = canonical_json_bytes(section)
                        connection.execute(
                            """
                            INSERT INTO section_diffs(
                                id, document_diff_id, sequence_index, old_section_id,
                                new_section_id, match_method, match_status, operations_json,
                                canonical_json, canonical_sha256
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                section_diff_id(diff.diff_id, sequence_index),
                                diff.diff_id,
                                sequence_index,
                                section.old_section_id,
                                section.new_section_id,
                                section.match_method.value,
                                section.match_status.value,
                                canonical_json_bytes(section.operations).decode("utf-8"),
                                section_json,
                                sha256_bytes(section_json),
                            ),
                        )
                    connection.commit()
                    return canonical, canonical_sha256, True
                except Exception:
                    connection.rollback()
                    raise
        except ODDError:
            raise
        except sqlite3.Error as exc:
            raise DatabaseFailure(f"SQLite diff artifact transaction failed: {exc}") from exc

    @staticmethod
    def _store_version_edge(
        connection: sqlite3.Connection,
        lineage_identifier: str,
        diff: DocumentDiff,
    ) -> str | None:
        if diff.old_document_id is None or diff.new_document_id is None:
            return None
        edge_identifier = version_edge_id(
            lineage_identifier, diff.old_document_id, diff.new_document_id
        )
        values = (
            lineage_identifier,
            diff.ordering.predecessor_document_id,
            diff.ordering.successor_document_id,
            diff.ordering.status.value,
            diff.ordering.ordering_source,
            diff.ordering.confidence_status,
            int(diff.ordering.known_predecessor),
            int(diff.ordering.known_successor),
            int(diff.ordering.intermediate_versions_possible),
            canonical_json_bytes(diff.ordering.missing_source_versions).decode("utf-8"),
            diff.ordering.history_snapshot_id,
        )
        existing = connection.execute(
            "SELECT * FROM document_version_edges WHERE id = ?", (edge_identifier,)
        ).fetchone()
        if existing is not None:
            stored = (
                str(existing["lineage_id"]),
                str(existing["predecessor_document_id"])
                if existing["predecessor_document_id"]
                else None,
                str(existing["successor_document_id"])
                if existing["successor_document_id"]
                else None,
                str(existing["ordering_status"]),
                str(existing["ordering_source"]),
                str(existing["confidence_status"]),
                int(existing["known_predecessor"]),
                int(existing["known_successor"]),
                int(existing["intermediate_versions_possible"]),
                str(existing["missing_source_versions_json"]),
                str(existing["history_snapshot_id"])
                if existing["history_snapshot_id"]
                else None,
            )
            if stored != values:
                raise DiffArtifactConflict(
                    "version edge identity already has different ordering evidence",
                    details={"edge_id": edge_identifier},
                )
            return edge_identifier
        connection.execute(
            """
            INSERT INTO document_version_edges(
                id, lineage_id, predecessor_document_id, successor_document_id,
                ordering_status, ordering_source, confidence_status,
                known_predecessor, known_successor, intermediate_versions_possible,
                missing_source_versions_json, history_snapshot_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (edge_identifier, *values, _iso_utc(diff.generated_at or datetime.now(UTC))),
        )
        return edge_identifier

    def get_diff_artifact(self, diff_id: str) -> dict[str, Any] | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT * FROM document_diffs WHERE id = ?", (diff_id,)
                ).fetchone()
                if row is None:
                    return None
                result = dict(row)
                result["canonical_json"] = bytes(result["canonical_json"])
                return result
        except sqlite3.Error as exc:
            raise DatabaseFailure(f"SQLite diff artifact lookup failed: {exc}") from exc

    def get_version_edge(self, edge_id: str) -> dict[str, Any] | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT * FROM document_version_edges WHERE id = ?", (edge_id,)
                ).fetchone()
                return dict(row) if row is not None else None
        except sqlite3.Error as exc:
            raise DatabaseFailure(f"SQLite version edge lookup failed: {exc}") from exc

    def get_section_diff_artifacts(self, diff_id: str) -> list[dict[str, Any]]:
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT * FROM section_diffs
                    WHERE document_diff_id = ? ORDER BY sequence_index
                    """,
                    (diff_id,),
                ).fetchall()
                result = []
                for row in rows:
                    item = dict(row)
                    item["canonical_json"] = bytes(item["canonical_json"])
                    result.append(item)
                return result
        except sqlite3.Error as exc:
            raise DatabaseFailure(f"SQLite section diff lookup failed: {exc}") from exc

    def diff_integrity_checks(self, diff_id: str) -> dict[str, Any]:
        try:
            with self._connect() as connection:
                foreign_keys = [dict(row) for row in connection.execute("PRAGMA foreign_key_check")]
                integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
                diff_count = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM document_diffs WHERE id = ?", (diff_id,)
                    ).fetchone()[0]
                )
                section_count = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM section_diffs WHERE document_diff_id = ?",
                        (diff_id,),
                    ).fetchone()[0]
                )
                return {
                    "diff_count": diff_count,
                    "foreign_key_violations": foreign_keys,
                    "integrity_check": integrity,
                    "section_diff_count": section_count,
                }
        except sqlite3.Error as exc:
            raise DatabaseFailure(f"SQLite diff integrity checks failed: {exc}") from exc

    def store_document(
        self,
        normalized: NormalizedDocument,
        raw: RawDocument,
        *,
        run_id: int,
        completed_at: datetime,
    ) -> bool:
        """Persist one normalized output atomically; return ``False`` when idempotent."""

        canonical = canonical_normalized_json_bytes(normalized)
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    source_id = self._upsert_source(connection, raw)
                    existing = connection.execute(
                        "SELECT normalized_json FROM regulatory_documents WHERE id = ?",
                        (normalized.document.document_id,),
                    ).fetchone()
                    inserted = existing is None
                    if existing is not None:
                        stored = bytes(existing["normalized_json"])
                        if stored != canonical:
                            raise DuplicateDocument(
                                "deterministic document ID already has different normalized bytes",
                                details={"document_id": normalized.document.document_id},
                            )
                    else:
                        self._insert_document(connection, normalized, source_id, canonical)
                        self._insert_products(connection, normalized)
                        self._insert_ingredients(connection, normalized)
                        self._insert_sections(connection, normalized)
                        self._insert_mappings(connection, normalized)
                        self._insert_concept_statuses(connection, normalized)

                    mapped_ids = {item.section_id for item in normalized.semantic_mappings}
                    mapped_count = len(mapped_ids)
                    section_count = len(normalized.sections)
                    cursor = connection.execute(
                        """
                        UPDATE ingestion_runs
                        SET completed_at = ?, status = ?, source_document_row_id = ?,
                            document_id = ?, source_section_count = ?, mapped_section_count = ?,
                            unmapped_section_count = ?, error_category = NULL, error_message = NULL
                        WHERE id = ?
                        """,
                        (
                            _iso_utc(completed_at),
                            "succeeded" if inserted else "succeeded_idempotent",
                            source_id,
                            normalized.document.document_id,
                            section_count,
                            mapped_count,
                            section_count - mapped_count,
                            run_id,
                        ),
                    )
                    if cursor.rowcount != 1:
                        raise DatabaseFailure(f"ingestion run {run_id} does not exist")
                    connection.commit()
                    return inserted
                except Exception:
                    connection.rollback()
                    raise
        except ODDError:
            raise
        except sqlite3.Error as exc:
            raise DatabaseFailure(f"SQLite document transaction failed: {exc}") from exc

    def search(self, query: str) -> list[dict[str, Any]]:
        pattern = f"%{query.casefold()}%"
        sql = """
            SELECT DISTINCT
                rd.id AS document_id,
                rd.generic_name,
                rd.brand_names_json,
                rd.document_type,
                rd.parser_version,
                rd.schema_version,
                rd.mapping_version,
                sd.jurisdiction,
                sd.authority,
                sd.provider,
                sd.source_version,
                sd.source_document_id,
                sd.raw_sha256
            FROM regulatory_documents rd
            JOIN source_documents sd ON sd.id = rd.source_document_row_id
            LEFT JOIN document_products dp ON dp.document_id = rd.id
            LEFT JOIN products p ON p.id = dp.product_id
            LEFT JOIN document_ingredients di ON di.document_id = rd.id
            LEFT JOIN ingredients i ON i.id = di.ingredient_id
            WHERE lower(COALESCE(rd.generic_name, '')) LIKE ?
               OR lower(COALESCE(p.brand_name, '')) LIKE ?
               OR lower(COALESCE(i.name, '')) LIKE ?
               OR lower(rd.title) LIKE ?
            ORDER BY lower(COALESCE(rd.generic_name, '')), sd.source_document_id,
                     CAST(sd.source_version AS INTEGER) DESC, rd.id
        """
        try:
            with self._connect() as connection:
                rows = connection.execute(sql, (pattern, pattern, pattern, pattern)).fetchall()
                result = []
                for row in rows:
                    item = dict(row)
                    brands = json.loads(item.pop("brand_names_json"))
                    item["brand_names"] = brands
                    item["brand_name"] = brands[0] if brands else None
                    result.append(item)
                return result
        except (sqlite3.Error, json.JSONDecodeError) as exc:
            raise DatabaseFailure(f"SQLite search failed: {exc}") from exc

    def get_document(self, document_id: str) -> dict[str, Any] | None:
        sql = """
            SELECT
                rd.*, sd.authority, sd.provider, sd.jurisdiction,
                sd.source_document_id, sd.source_version, sd.source_url,
                sd.retrieved_at, sd.raw_sha256, sd.raw_path, sd.metadata_path,
                sd.selection_reason
            FROM regulatory_documents rd
            JOIN source_documents sd ON sd.id = rd.source_document_row_id
            WHERE rd.id = ?
        """
        try:
            with self._connect() as connection:
                row = connection.execute(sql, (document_id,)).fetchone()
                if row is None:
                    return None
                item = dict(row)
                item.pop("normalized_json")
                item["document_id"] = item.pop("id")
                item["brand_names"] = json.loads(item.pop("brand_names_json"))
                item["dosage_forms"] = json.loads(item.pop("dosage_forms_json"))
                item["routes"] = json.loads(item.pop("routes_json"))
                item["active_ingredients"] = json.loads(
                    item.pop("active_ingredients_json")
                )
                item["products"] = self._products(connection, document_id)
                item["concept_statuses"] = self._concept_statuses(connection, document_id)
                return item
        except (sqlite3.Error, json.JSONDecodeError) as exc:
            raise DatabaseFailure(f"SQLite document lookup failed: {exc}") from exc

    def get_sections(
        self, document_id: str, concept: str | None = None
    ) -> list[dict[str, Any]]:
        parameters: list[Any] = [document_id]
        filter_sql = ""
        if concept is not None:
            filter_sql = """
                AND EXISTS (
                    SELECT 1 FROM semantic_mappings selected_mapping
                    WHERE selected_mapping.section_id = ss.id
                      AND selected_mapping.normalized_concept = ?
                )
            """
            parameters.append(concept)
        sql = f"""
            SELECT ss.*
            FROM source_sections ss
            WHERE ss.document_id = ? {filter_sql}
            ORDER BY ss.sequence_index
        """
        try:
            with self._connect() as connection:
                rows = connection.execute(sql, parameters).fetchall()
                result: list[dict[str, Any]] = []
                for row in rows:
                    item = dict(row)
                    structured = item.pop("structured_content_json")
                    item["structured_content"] = json.loads(structured) if structured else None
                    item["semantic_mappings"] = self._mappings(connection, item["id"])
                    item["section_id"] = item.pop("id")
                    result.append(item)
                return result
        except (sqlite3.Error, json.JSONDecodeError) as exc:
            raise DatabaseFailure(f"SQLite section lookup failed: {exc}") from exc

    def get_source_record(self, document_id: str) -> dict[str, Any] | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT sd.* FROM source_documents sd
                    JOIN regulatory_documents rd ON rd.source_document_row_id = sd.id
                    WHERE rd.id = ?
                    """,
                    (document_id,),
                ).fetchone()
                return dict(row) if row is not None else None
        except sqlite3.Error as exc:
            raise DatabaseFailure(f"SQLite source lookup failed: {exc}") from exc

    def get_normalized_bytes(self, document_id: str) -> bytes | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT normalized_json FROM regulatory_documents WHERE id = ?",
                    (document_id,),
                ).fetchone()
                return bytes(row["normalized_json"]) if row is not None else None
        except sqlite3.Error as exc:
            raise DatabaseFailure(f"SQLite normalized output lookup failed: {exc}") from exc

    def get_stored_document(self, document_id: str) -> StoredDocumentVersion:
        document = self.get_document(document_id)
        source = self.get_source_record(document_id)
        normalized = self.get_normalized_bytes(document_id)
        if document is None or source is None or normalized is None:
            raise SourceNotFound(
                "normalized document was not found", details={"document_id": document_id}
            )
        raw_path = Path(str(source["raw_path"]))
        try:
            raw_bytes = raw_path.read_bytes()
        except OSError as exc:
            raise ProvenanceValidationFailure(
                f"stored raw SPL could not be read for diff generation: {exc}",
                details={"raw_path": str(raw_path)},
            ) from exc
        actual_raw_sha = sha256_bytes(raw_bytes)
        if actual_raw_sha != source["raw_sha256"]:
            raise ProvenanceValidationFailure(
                "stored raw SPL hash mismatch prevents diff generation",
                details={
                    "actual_raw_sha256": actual_raw_sha,
                    "expected_raw_sha256": source["raw_sha256"],
                },
            )
        xml_identifiers = extract_section_xml_identifiers(raw_bytes)
        publication_date, publication_source = self._publication_metadata(document_id)
        section_values = self.get_sections(document_id)
        sections = tuple(
            StoredSection(
                section_id=str(item["section_id"]),
                sequence_index=int(item["sequence_index"]),
                source_section_code=str(item["source_section_code"])
                if item["source_section_code"]
                else None,
                xml_identifier=xml_identifiers.get(str(item["source_locator"])),
                original_heading=str(item["original_heading"])
                if item["original_heading"] is not None
                else None,
                original_text=str(item["original_text"]),
                section_sha256=str(item["section_sha256"]),
                source_locator=str(item["source_locator"]),
                parent_section_id=str(item["parent_section_id"])
                if item["parent_section_id"]
                else None,
                depth=int(item["depth"]),
                content_status=str(item["content_status"]),
                structured_content=item["structured_content"],
                normalized_concepts=tuple(
                    sorted(
                        str(mapping["normalized_concept"])
                        for mapping in item["semantic_mappings"]
                    )
                ),
            )
            for item in section_values
        )
        ingestion_metadata = canonical_json_bytes(
            {
                "metadata_path": source["metadata_path"],
                "raw_path": source["raw_path"],
                "retrieved_at": source["retrieved_at"],
                "selection_reason": source["selection_reason"],
                "source_url": source["source_url"],
            }
        )
        effective = (
            date.fromisoformat(str(document["effective_date"]))
            if document["effective_date"]
            else None
        )
        from odd.models import DiffDocumentProvenance

        provenance = DiffDocumentProvenance(
            authority=str(source["authority"]),
            provider=str(source["provider"]),
            jurisdiction=str(source["jurisdiction"]),
            source_document_id=str(source["source_document_id"]),
            source_version=str(source["source_version"]),
            source_instance_id=str(document["source_instance_id"])
            if document["source_instance_id"]
            else None,
            effective_date=effective,
            publication_date=publication_date,
            publication_date_source=publication_source,
            retrieved_at=_parse_datetime(str(source["retrieved_at"])),
            raw_sha256=str(source["raw_sha256"]),
            raw_path=str(raw_path),
            parser_version=str(document["parser_version"]),
            schema_version=str(document["schema_version"]),
            mapping_version=str(document["mapping_version"]),
        )
        return StoredDocumentVersion(
            document_id=document_id,
            provenance=provenance,
            document_type=str(document["document_type"]),
            language=str(document["language"]) if document["language"] else None,
            title=str(document["title"]),
            generic_name=str(document["generic_name"]) if document["generic_name"] else None,
            brand_names=tuple(str(item) for item in document["brand_names"]),
            dosage_forms=tuple(str(item) for item in document["dosage_forms"]),
            routes=tuple(str(item) for item in document["routes"]),
            active_ingredients=tuple(str(item) for item in document["active_ingredients"]),
            normalized_sha256=sha256_bytes(normalized),
            ingestion_metadata_sha256=sha256_bytes(ingestion_metadata),
            sections=sections,
        )

    def _publication_metadata(self, document_id: str) -> tuple[date | None, str | None]:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT lsd.lineage_id, sd.source_version,
                           lsd.selection_publication_date
                    FROM regulatory_documents rd
                    JOIN source_documents sd ON sd.id = rd.source_document_row_id
                    JOIN lineage_source_documents lsd
                      ON lsd.source_document_row_id = sd.id
                    WHERE rd.id = ?
                    """,
                    (document_id,),
                ).fetchone()
                if row is None:
                    return None, None
                history_row = connection.execute(
                    """
                    SELECT lhe.publication_date
                    FROM lineage_history_entries lhe
                    JOIN lineage_history_snapshots lhs
                      ON lhs.id = lhe.history_snapshot_id
                    WHERE lhe.lineage_id = ? AND lhe.source_version = ?
                    ORDER BY lhs.retrieved_at DESC, lhs.id DESC LIMIT 1
                    """,
                    (row["lineage_id"], row["source_version"]),
                ).fetchone()
                if history_row is not None and history_row["publication_date"]:
                    return (
                        date.fromisoformat(str(history_row["publication_date"])),
                        "DAILYMED_HISTORY",
                    )
                if row["selection_publication_date"]:
                    return (
                        date.fromisoformat(str(row["selection_publication_date"])),
                        "SELECTION_METADATA",
                    )
                return None, None
        except (sqlite3.Error, ValueError) as exc:
            raise DatabaseFailure(f"SQLite publication metadata lookup failed: {exc}") from exc

    def integrity_checks(self, document_id: str) -> dict[str, Any]:
        try:
            with self._connect() as connection:
                integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
                foreign_keys = [dict(row) for row in connection.execute("PRAGMA foreign_key_check")]
                orphan_mappings = connection.execute(
                    """
                    SELECT COUNT(*) FROM semantic_mappings sm
                    LEFT JOIN source_sections ss ON ss.id = sm.section_id
                    WHERE ss.id IS NULL
                    """
                ).fetchone()[0]
                cross_document_parents = connection.execute(
                    """
                    SELECT COUNT(*) FROM source_sections child
                    JOIN source_sections parent ON parent.id = child.parent_section_id
                    WHERE child.document_id != parent.document_id
                    """
                ).fetchone()[0]
                document_count = connection.execute(
                    "SELECT COUNT(*) FROM regulatory_documents WHERE id = ?", (document_id,)
                ).fetchone()[0]
                return {
                    "cross_document_parent_count": cross_document_parents,
                    "document_count": document_count,
                    "foreign_key_violations": foreign_keys,
                    "integrity_check": integrity,
                    "orphan_mapping_count": orphan_mappings,
                }
        except sqlite3.Error as exc:
            raise DatabaseFailure(f"SQLite integrity checks failed: {exc}") from exc

    def get_ingestion_run(self, run_id: int) -> dict[str, Any] | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT * FROM ingestion_runs WHERE id = ?", (run_id,)
                ).fetchone()
                return dict(row) if row is not None else None
        except sqlite3.Error as exc:
            raise DatabaseFailure(f"SQLite ingestion run lookup failed: {exc}") from exc

    def table_count(self, table: str) -> int:
        allowed = {
            "source_documents",
            "regulatory_documents",
            "products",
            "ingredients",
            "document_products",
            "document_ingredients",
            "source_sections",
            "semantic_mappings",
            "document_concept_statuses",
            "ingestion_runs",
            "document_lineages",
            "lineage_source_documents",
            "lineage_history_snapshots",
            "lineage_history_entries",
            "document_version_edges",
            "document_diffs",
            "section_diffs",
            "utilization_lists",
            "utilization_entries",
            "candidate_discovery_runs",
            "label_candidates",
            "candidate_decisions",
            "batch_runs",
            "batch_items",
            "batch_artifacts",
            "parser_compatibility_results",
            "candidate_discovery_details",
            "candidate_discovery_pages",
            "live_batch_runs",
            "live_batch_items",
            "live_batch_artifacts",
        }
        if table not in allowed:
            raise ValueError(f"unsupported table name: {table}")
        try:
            with self._connect() as connection:
                return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        except sqlite3.Error as exc:
            raise DatabaseFailure(f"SQLite count failed: {exc}") from exc

    def _upsert_source(self, connection: sqlite3.Connection, raw: RawDocument) -> str:
        identity = raw.identity
        existing = connection.execute(
            """
            SELECT id, raw_sha256 FROM source_documents
            WHERE authority = ? AND provider = ? AND jurisdiction = ?
              AND source_document_id = ? AND source_version = ?
            """,
            (
                identity.authority,
                identity.provider,
                identity.jurisdiction,
                identity.source_document_id,
                identity.source_version,
            ),
        ).fetchone()
        if existing is not None:
            if existing["raw_sha256"] != identity.raw_sha256:
                raise RawHashConflict(
                    "SQLite source identity already has a different raw SHA-256"
                )
            identifier = str(existing["id"])
            self._link_source_lineage(connection, identifier, identity, raw.metadata)
            return identifier

        identifier = source_record_id(identity)
        candidates = raw.metadata.get("candidate_metadata", [])
        selection = raw.metadata.get("selection", {})
        reason = selection.get("reason") if isinstance(selection, dict) else None
        connection.execute(
            """
            INSERT INTO source_documents(
                id, authority, provider, jurisdiction, source_document_id, source_version,
                source_url, retrieved_at, raw_sha256, raw_path, metadata_path,
                candidates_json, selection_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                identifier,
                identity.authority,
                identity.provider,
                identity.jurisdiction,
                identity.source_document_id,
                identity.source_version,
                identity.source_url,
                _iso_utc(identity.retrieved_at),
                identity.raw_sha256,
                str(raw.label_path),
                str(raw.metadata_path),
                canonical_json_bytes(candidates).decode("utf-8"),
                str(reason or "selection reason unavailable"),
            ),
        )
        self._link_source_lineage(connection, identifier, identity, raw.metadata)
        return identifier

    @staticmethod
    def _insert_document(
        connection: sqlite3.Connection,
        normalized: NormalizedDocument,
        source_id: str,
        canonical: bytes,
    ) -> None:
        document = normalized.document
        connection.execute(
            """
            INSERT INTO regulatory_documents(
                id, source_document_row_id, source_instance_id, document_type, language,
                effective_date, title, generic_name, brand_names_json, dosage_forms_json,
                routes_json, active_ingredients_json, parser_version, schema_version,
                mapping_version, normalized_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                document.document_id,
                source_id,
                document.source_instance_id,
                document.document_type,
                document.language,
                document.effective_date.isoformat() if document.effective_date else None,
                document.title,
                document.generic_name,
                canonical_json_bytes(document.brand_names).decode("utf-8"),
                canonical_json_bytes(document.dosage_forms).decode("utf-8"),
                canonical_json_bytes(document.routes).decode("utf-8"),
                canonical_json_bytes(document.active_ingredients).decode("utf-8"),
                document.parser_version,
                document.schema_version,
                document.mapping_version,
                canonical,
            ),
        )

    @staticmethod
    def _insert_products(
        connection: sqlite3.Connection, normalized: NormalizedDocument
    ) -> None:
        for product in normalized.products:
            connection.execute(
                "INSERT INTO products(id, brand_name, dosage_form, route) VALUES (?, ?, ?, ?)",
                (product.product_id, product.brand_name, product.dosage_form, product.route),
            )
            connection.execute(
                """
                INSERT INTO document_products(document_id, product_id, sequence_index)
                VALUES (?, ?, ?)
                """,
                (normalized.document.document_id, product.product_id, product.sequence_index),
            )

    @staticmethod
    def _insert_ingredients(
        connection: sqlite3.Connection, normalized: NormalizedDocument
    ) -> None:
        for index, name in enumerate(normalized.document.active_ingredients):
            identifier = ingredient_id(name)
            connection.execute(
                """
                INSERT OR IGNORE INTO ingredients(id, name, normalized_name) VALUES (?, ?, ?)
                """,
                (identifier, name, name.casefold()),
            )
            connection.execute(
                """
                INSERT INTO document_ingredients(document_id, ingredient_id, sequence_index)
                VALUES (?, ?, ?)
                """,
                (normalized.document.document_id, identifier, index),
            )

    @staticmethod
    def _insert_sections(
        connection: sqlite3.Connection, normalized: NormalizedDocument
    ) -> None:
        for section in normalized.sections:
            structured = (
                canonical_json_bytes(section.structured_content).decode("utf-8")
                if section.structured_content is not None
                else None
            )
            connection.execute(
                """
                INSERT INTO source_sections(
                    id, document_id, source_section_code, original_heading, original_text,
                    sequence_index, section_sha256, source_locator, parent_section_id,
                    depth, content_status, structured_content_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    section.section_id,
                    section.document_id,
                    section.source_section_code,
                    section.original_heading,
                    section.original_text,
                    section.sequence_index,
                    section.section_sha256,
                    section.source_locator,
                    section.parent_section_id,
                    section.depth,
                    section.content_status.value,
                    structured,
                ),
            )

    @staticmethod
    def _insert_mappings(
        connection: sqlite3.Connection, normalized: NormalizedDocument
    ) -> None:
        for mapping in normalized.semantic_mappings:
            connection.execute(
                """
                INSERT INTO semantic_mappings(
                    id, section_id, normalized_concept, mapping_method, mapping_version,
                    confidence, deterministic_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    mapping_id(
                        mapping.section_id,
                        mapping.normalized_concept,
                        mapping.mapping_version,
                    ),
                    mapping.section_id,
                    mapping.normalized_concept,
                    mapping.mapping_method,
                    mapping.mapping_version,
                    mapping.confidence,
                    mapping.deterministic_status,
                ),
            )

    @staticmethod
    def _insert_concept_statuses(
        connection: sqlite3.Connection, normalized: NormalizedDocument
    ) -> None:
        for status in normalized.concept_statuses:
            connection.execute(
                """
                INSERT INTO document_concept_statuses(
                    document_id, normalized_concept, status, section_ids_json
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    normalized.document.document_id,
                    status.normalized_concept,
                    status.status.value,
                    canonical_json_bytes(status.section_ids).decode("utf-8"),
                ),
            )

    @staticmethod
    def _products(connection: sqlite3.Connection, document_id: str) -> list[dict[str, Any]]:
        rows = connection.execute(
            """
            SELECT p.id AS product_id, p.brand_name, p.dosage_form, p.route,
                   dp.sequence_index
            FROM document_products dp
            JOIN products p ON p.id = dp.product_id
            WHERE dp.document_id = ? ORDER BY dp.sequence_index
            """,
            (document_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _concept_statuses(
        connection: sqlite3.Connection, document_id: str
    ) -> list[dict[str, Any]]:
        rows = connection.execute(
            """
            SELECT normalized_concept, status, section_ids_json
            FROM document_concept_statuses
            WHERE document_id = ? ORDER BY normalized_concept
            """,
            (document_id,),
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["section_ids"] = json.loads(item.pop("section_ids_json"))
            result.append(item)
        return result

    @staticmethod
    def _mappings(connection: sqlite3.Connection, section_id: str) -> list[dict[str, Any]]:
        rows = connection.execute(
            """
            SELECT normalized_concept, mapping_method, mapping_version, confidence,
                   deterministic_status
            FROM semantic_mappings WHERE section_id = ?
            ORDER BY normalized_concept, mapping_version
            """,
            (section_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
        finally:
            connection.close()


def _utilization_list_from_stored(payload: dict[str, Any]) -> UtilizationList:
    entries = tuple(
        UtilizationEntry(
            utilization_list_id=str(item["utilization_list_id"]),
            rank=int(item["rank"]),
            ingredient_name=str(item["ingredient_name"]),
            normalized_ingredient_name=str(item["normalized_ingredient_name"]),
            metric_value=(
                float(item["metric_value"]) if item.get("metric_value") is not None else None
            ),
            metric_unit=str(item["metric_unit"]) if item.get("metric_unit") else None,
            source_row_identifier=(
                str(item["source_row_identifier"])
                if item.get("source_row_identifier")
                else None
            ),
        )
        for item in payload["entries"]
    )
    return UtilizationList(
        utilization_list_id=str(payload["utilization_list_id"]),
        schema_version=str(payload["schema_version"]),
        jurisdiction=str(payload["jurisdiction"]),
        dataset_name=str(payload["dataset_name"]),
        dataset_version=str(payload["dataset_version"]),
        measurement_year=int(payload["measurement_year"]),
        metric=str(payload["metric"]),
        source_reference=str(payload["source_reference"]),
        retrieved_at=_parse_datetime(str(payload["retrieved_at"])),
        license_or_terms_status=str(payload["license_or_terms_status"]),
        source_status=str(payload["source_status"]),
        notes=str(payload["notes"]),
        entries=entries,
    )


def _candidate_selection_from_stored(payload: dict[str, Any]) -> CandidateSelection:
    candidates = tuple(
        CandidateEvidence(
            candidate_id=str(item["candidate_id"]),
            discovery_run_id=str(item["discovery_run_id"]),
            candidate_index=int(item["candidate_index"]),
            set_id=str(item["set_id"]) if item.get("set_id") is not None else None,
            source_version=(
                str(item["source_version"])
                if item.get("source_version") is not None
                else None
            ),
            title=str(item["title"]) if item.get("title") is not None else None,
            published_date=(
                str(item["published_date"])
                if item.get("published_date") is not None
                else None
            ),
            generic_name=(
                str(item["generic_name"]) if item.get("generic_name") is not None else None
            ),
            brand_name=(
                str(item["brand_name"]) if item.get("brand_name") is not None else None
            ),
            active_ingredients=tuple(str(value) for value in item["active_ingredients"]),
            dosage_form=(
                str(item["dosage_form"]) if item.get("dosage_form") is not None else None
            ),
            route=str(item["route"]) if item.get("route") is not None else None,
            labeler=str(item["labeler"]) if item.get("labeler") is not None else None,
            marketing_category=(
                str(item["marketing_category"])
                if item.get("marketing_category") is not None
                else None
            ),
            product_type=(
                str(item["product_type"])
                if item.get("product_type") is not None
                else None
            ),
            source_status=(
                str(item["source_status"])
                if item.get("source_status") is not None
                else None
            ),
            source_url=(
                str(item["source_url"]) if item.get("source_url") is not None else None
            ),
            raw_metadata=dict(item["raw_metadata"]),
            raw_metadata_sha256=str(item["raw_metadata_sha256"]),
            classifications=tuple(
                CandidateClassification(str(value)) for value in item["classifications"]
            ),
            accepted_for_selection=bool(item["accepted_for_selection"]),
            rejection_reasons=tuple(str(value) for value in item["rejection_reasons"]),
            duplicate_of_candidate_id=(
                str(item["duplicate_of_candidate_id"])
                if item.get("duplicate_of_candidate_id") is not None
                else None
            ),
        )
        for item in payload["candidates"]
    )
    return CandidateSelection(
        decision_id=str(payload["decision_id"]),
        discovery_run_id=str(payload["discovery_run_id"]),
        ingredient_id=str(payload["ingredient_id"]),
        selection_rule_version=str(payload["selection_rule_version"]),
        selection_status=SelectionStatus(str(payload["selection_status"])),
        selected_candidate_id=(
            str(payload["selected_candidate_id"])
            if payload.get("selected_candidate_id") is not None
            else None
        ),
        selected_set_id=(
            str(payload["selected_set_id"])
            if payload.get("selected_set_id") is not None
            else None
        ),
        selected_source_version=(
            str(payload["selected_source_version"])
            if payload.get("selected_source_version") is not None
            else None
        ),
        selection_reason=str(payload["selection_reason"]),
        applied_rules=tuple(str(value) for value in payload["applied_rules"]),
        manual_review_required=bool(payload["manual_review_required"]),
        selection_scope=str(payload["selection_scope"]),
        candidates=candidates,
    )


def _daily_med_candidate_from_metadata(metadata: dict[str, Any]) -> DailyMedCandidate:
    set_id = metadata.get("setid", metadata.get("set_id"))
    source_version = metadata.get("spl_version", metadata.get("source_version"))
    title = metadata.get("title")
    published_date = metadata.get("published_date", "")
    if set_id is None or source_version is None or title is None:
        raise ValueError("stored candidate metadata lacks its DailyMed identity")
    return DailyMedCandidate(
        set_id=str(set_id),
        source_version=str(source_version),
        title=str(title),
        published_date=str(published_date),
        metadata=metadata,
    )


def _http_attempts_from_json(value: str) -> tuple[HTTPAttemptEvidence, ...]:
    decoded = json.loads(value)
    if not isinstance(decoded, list):
        raise ValueError("stored HTTP attempt evidence must be a list")
    result: list[HTTPAttemptEvidence] = []
    for item in decoded:
        if not isinstance(item, dict):
            raise ValueError("stored HTTP attempt evidence must contain objects")
        result.append(
            HTTPAttemptEvidence(
                attempt_number=int(item["attempt_number"]),
                status_code=(
                    int(item["status_code"])
                    if item.get("status_code") is not None
                    else None
                ),
                error_category=(
                    str(item["error_category"])
                    if item.get("error_category") is not None
                    else None
                ),
                diagnostic_message=(
                    str(item["diagnostic_message"])
                    if item.get("diagnostic_message") is not None
                    else None
                ),
                retry_after_seconds=(
                    float(item["retry_after_seconds"])
                    if item.get("retry_after_seconds") is not None
                    else None
                ),
                backoff_seconds=(
                    float(item["backoff_seconds"])
                    if item.get("backoff_seconds") is not None
                    else None
                ),
                retry_eligible=bool(item["retry_eligible"]),
            )
        )
    return tuple(result)


def _batch_run_values(run: BatchRun) -> tuple[Any, ...]:
    return (
        run.batch_run_id,
        run.utilization_list_id,
        run.selection_rule_version,
        run.connector_version,
        run.parser_version,
        run.schema_version,
        run.mapping_version,
        _iso_utc(run.started_at),
        _iso_utc(run.completed_at) if run.completed_at else None,
        run.status.value,
        run.requested_count,
        run.selected_count,
        run.fetched_count,
        run.ingested_count,
        run.verified_count,
        run.quarantined_count,
        run.unresolved_count,
        run.failed_count,
        run.canonical_report_sha256,
    )


def _batch_item_values(item: BatchItem) -> tuple[Any, ...]:
    return (
        item.batch_run_id,
        item.rank,
        item.ingredient_id,
        item.ingredient_name,
        item.discovery_status.value,
        item.selection_status.value,
        item.selected_set_id,
        item.selected_source_version,
        item.document_id,
        item.raw_sha256,
        item.ingestion_status.value,
        item.verification_status.value,
        item.quarantine_record_id,
        item.error_category,
        item.diagnostic_message,
        int(item.manual_review_required),
        item.parser_compatibility_status.value,
        item.source_section_count,
        item.mapped_section_count,
        item.unmapped_section_count,
        item.unsupported_structure_count,
        item.empty_section_count,
        canonical_json_bytes(item.parser_warnings).decode("utf-8"),
        item.discovery_run_id,
        item.decision_id,
        int(item.retry_eligible),
        item.query_text,
        item.candidate_count,
        item.selection_reason,
    )


def _live_batch_run_values(run: BatchRun) -> tuple[Any, ...]:
    return (
        run.utilization_list_id,
        run.selection_rule_version,
        run.connector_version,
        run.parser_version,
        run.schema_version,
        run.mapping_version,
        _iso_utc(run.started_at),
        _iso_utc(run.completed_at) if run.completed_at else None,
        run.status.value,
        run.requested_count,
        run.selected_count,
        run.fetched_count,
        run.ingested_count,
        run.verified_count,
        run.quarantined_count,
        run.unresolved_count,
        run.failed_count,
        run.canonical_report_sha256,
        run.observation_mode,
        run.snapshot_manifest_sha256,
        run.discovery_complete_count,
        run.manual_review_count,
        run.no_candidate_count,
        run.fetch_failure_count,
        run.parser_failure_count,
        run.database_schema_version,
    )


def _live_batch_item_values(item: BatchItem) -> tuple[Any, ...]:
    return (
        *_batch_item_values(item),
        item.snapshot_id,
        item.metadata_total_candidate_count,
        item.retrieved_candidate_count,
        item.eligible_candidate_count,
        item.discovery_completeness.value,
        item.evidence_verification_status.value,
    )


def _batch_run_from_row(row: sqlite3.Row) -> BatchRun:
    return BatchRun(
        batch_run_id=str(row["id"]),
        utilization_list_id=str(row["utilization_list_id"]),
        selection_rule_version=str(row["selection_rule_version"]),
        connector_version=str(row["connector_version"]),
        parser_version=str(row["parser_version"]),
        schema_version=str(row["schema_version"]),
        mapping_version=str(row["mapping_version"]),
        started_at=_parse_datetime(str(row["started_at"])),
        completed_at=(
            _parse_datetime(str(row["completed_at"])) if row["completed_at"] else None
        ),
        status=BatchStatus(str(row["status"])),
        requested_count=int(row["requested_count"]),
        selected_count=int(row["selected_count"]),
        fetched_count=int(row["fetched_count"]),
        ingested_count=int(row["ingested_count"]),
        verified_count=int(row["verified_count"]),
        quarantined_count=int(row["quarantined_count"]),
        unresolved_count=int(row["unresolved_count"]),
        failed_count=int(row["failed_count"]),
        canonical_report_sha256=(
            str(row["canonical_report_sha256"])
            if row["canonical_report_sha256"]
            else None
        ),
    )


def _live_batch_run_from_row(row: sqlite3.Row) -> BatchRun:
    return BatchRun(
        batch_run_id=str(row["id"]),
        utilization_list_id=str(row["utilization_list_id"]),
        selection_rule_version=str(row["selection_rule_version"]),
        connector_version=str(row["connector_version"]),
        parser_version=str(row["parser_version"]),
        schema_version=str(row["schema_version"]),
        mapping_version=str(row["mapping_version"]),
        started_at=_parse_datetime(str(row["started_at"])),
        completed_at=(
            _parse_datetime(str(row["completed_at"])) if row["completed_at"] else None
        ),
        status=BatchStatus(str(row["status"])),
        requested_count=int(row["requested_count"]),
        selected_count=int(row["selected_count"]),
        fetched_count=int(row["fetched_count"]),
        ingested_count=int(row["ingested_count"]),
        verified_count=int(row["verified_count"]),
        quarantined_count=int(row["quarantined_count"]),
        unresolved_count=int(row["unresolved_count"]),
        failed_count=int(row["failed_count"]),
        canonical_report_sha256=(
            str(row["canonical_report_sha256"])
            if row["canonical_report_sha256"]
            else None
        ),
        database_schema_version=str(row["database_schema_version"]),
        observation_mode=str(row["observation_mode"]),
        snapshot_manifest_sha256=(
            str(row["snapshot_manifest_sha256"])
            if row["snapshot_manifest_sha256"]
            else None
        ),
        discovery_complete_count=int(row["discovery_complete_count"]),
        manual_review_count=int(row["manual_review_count"]),
        no_candidate_count=int(row["no_candidate_count"]),
        fetch_failure_count=int(row["fetch_failure_count"]),
        parser_failure_count=int(row["parser_failure_count"]),
    )


def _batch_item_from_row(row: sqlite3.Row) -> BatchItem:
    return BatchItem(
        batch_run_id=str(row["batch_run_id"]),
        rank=int(row["rank"]),
        ingredient_id=str(row["ingredient_id"]),
        ingredient_name=str(row["ingredient_name"]),
        discovery_status=DiscoveryStatus(str(row["discovery_status"])),
        selection_status=SelectionStatus(str(row["selection_status"])),
        selected_set_id=(str(row["selected_set_id"]) if row["selected_set_id"] else None),
        selected_source_version=(
            str(row["selected_source_version"])
            if row["selected_source_version"]
            else None
        ),
        document_id=str(row["document_id"]) if row["document_id"] else None,
        raw_sha256=str(row["raw_sha256"]) if row["raw_sha256"] else None,
        ingestion_status=IngestionStatus(str(row["ingestion_status"])),
        verification_status=VerificationStatus(str(row["verification_status"])),
        quarantine_record_id=(
            str(row["quarantine_record_id"]) if row["quarantine_record_id"] else None
        ),
        error_category=str(row["error_category"]) if row["error_category"] else None,
        diagnostic_message=(
            str(row["diagnostic_message"]) if row["diagnostic_message"] else None
        ),
        manual_review_required=bool(row["manual_review_required"]),
        parser_compatibility_status=ParserCompatibilityStatus(
            str(row["parser_compatibility_status"])
        ),
        source_section_count=(
            int(row["source_section_count"])
            if row["source_section_count"] is not None
            else None
        ),
        mapped_section_count=(
            int(row["mapped_section_count"])
            if row["mapped_section_count"] is not None
            else None
        ),
        unmapped_section_count=(
            int(row["unmapped_section_count"])
            if row["unmapped_section_count"] is not None
            else None
        ),
        unsupported_structure_count=int(row["unsupported_structure_count"]),
        empty_section_count=int(row["empty_section_count"]),
        parser_warnings=tuple(json.loads(str(row["parser_warnings_json"]))),
        discovery_run_id=(
            str(row["discovery_run_id"]) if row["discovery_run_id"] else None
        ),
        decision_id=str(row["decision_id"]) if row["decision_id"] else None,
        retry_eligible=bool(row["retry_eligible"]),
        query_text=str(row["query_text"]),
        candidate_count=int(row["candidate_count"]),
        selection_reason=(
            str(row["selection_reason"]) if row["selection_reason"] else None
        ),
    )


def _live_batch_item_from_row(row: sqlite3.Row) -> BatchItem:
    legacy = _batch_item_from_row(row)
    return replace(
        legacy,
        snapshot_id=str(row["snapshot_id"]) if row["snapshot_id"] else None,
        metadata_total_candidate_count=(
            int(row["metadata_total_candidate_count"])
            if row["metadata_total_candidate_count"] is not None
            else None
        ),
        retrieved_candidate_count=int(row["retrieved_candidate_count"]),
        eligible_candidate_count=int(row["eligible_candidate_count"]),
        discovery_completeness=DiscoveryCompleteness(str(row["discovery_completeness"])),
        evidence_verification_status=VerificationStatus(
            str(row["evidence_verification_status"])
        ),
    )


def _iso_utc(value: datetime) -> str:
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return aware.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _selection_publication_date(
    candidates_json: str,
    source_document_id: str,
    source_version: str,
) -> tuple[str | None, str]:
    try:
        candidates = json.loads(candidates_json)
        if not isinstance(candidates, list):
            return None, "UNAVAILABLE"
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            if (
                str(candidate.get("set_id", "")).casefold() == source_document_id.casefold()
                and str(candidate.get("source_version", "")) == source_version
            ):
                value = candidate.get("published_date")
                parsed = _parse_publication_date(value) if isinstance(value, str) else None
                return (
                    (parsed.isoformat(), "SELECTION_METADATA")
                    if parsed is not None
                    else (None, "MALFORMED_OR_UNAVAILABLE")
                )
    except (json.JSONDecodeError, TypeError):
        return None, "MALFORMED_OR_UNAVAILABLE"
    return None, "UNAVAILABLE"


def _parse_publication_date(value: str) -> date | None:
    normalized = value.strip()
    if not normalized:
        return None
    try:
        return date.fromisoformat(normalized)
    except ValueError:
        pass
    match = _DAILYMED_DATE.fullmatch(normalized)
    if match is None or match.group(1) not in _MONTHS:
        return None
    try:
        return date(int(match.group(3)), _MONTHS[match.group(1)], int(match.group(2)))
    except ValueError:
        return None


def _lineage_lookup_parameters(diff: DocumentDiff) -> tuple[str, str, str, str]:
    provenance = diff.old_provenance or diff.new_provenance
    if provenance is None:
        raise ValueError("diff has no source provenance")
    return (
        provenance.authority,
        provenance.provider,
        provenance.jurisdiction,
        diff.source_document_id,
    )

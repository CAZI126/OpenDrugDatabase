"""Transactional, version-aware SQLite persistence."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from odd.diffs.source_identifiers import extract_section_xml_identifiers
from odd.errors import (
    AmbiguousDocumentVersion,
    DatabaseFailure,
    DiffArtifactConflict,
    DuplicateDocument,
    ODDError,
    ProvenanceValidationFailure,
    RawHashConflict,
    SourceNotFound,
)
from odd.models import (
    DailyMedHistory,
    DailyMedHistoryEntry,
    DocumentDiff,
    NormalizedDocument,
    RawDocument,
    SourceIdentity,
    StoredDocumentVersion,
    StoredSection,
)
from odd.provenance.canonical import (
    canonical_diff_json_bytes,
    canonical_json_bytes,
    canonical_normalized_json_bytes,
    source_identity_payload,
)
from odd.provenance.hashing import sha256_bytes
from odd.provenance.identifiers import (
    document_lineage_id,
    history_snapshot_id,
    ingredient_id,
    mapping_id,
    section_diff_id,
    source_record_id,
    version_edge_id,
)

DATABASE_SCHEMA_VERSION = "2"
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
                if DATABASE_SCHEMA_VERSION not in applied:
                    connection.execute("BEGIN IMMEDIATE")
                    try:
                        for statement in MIGRATION_2_STATEMENTS:
                            connection.execute(statement)
                        self._backfill_lineages(connection)
                        connection.execute(
                            "INSERT INTO schema_migrations(version) VALUES (?)",
                            (DATABASE_SCHEMA_VERSION,),
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

"""Rebuildable metadata catalog for preserved-document discovery.

The catalog is deliberately not evidence and not a primary source.  It is a
small, deterministic derivative of preserved evidence or preserved SPL bytes,
created by an explicit caller-side command and safe to delete and rebuild.
MCP discovery reads this derivative only; it never creates or repairs it.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from odd.core.evidence import LABEL_PUBLISHER, LABEL_REPOSITORY, UNKNOWN
from odd.errors import ODDError
from odd.models import SourceIdentity
from odd.parsers.spl.parser import DocumentSearchMetadata, SPLParser
from odd.provenance.canonical import canonical_json_bytes
from odd.provenance.hashing import sha256_bytes

CATALOG_SCHEMA_VERSION = "odd-document-catalog/1.0.0"
CATALOG_RECORD_SCHEMA_VERSION = "odd-document-catalog-record/1.0.0"
CATALOG_NOT_BUILT = "CATALOG_NOT_BUILT"
CATALOG_INVALID = "CATALOG_INVALID"
CATALOG_SCHEMA_UNSUPPORTED = "CATALOG_SCHEMA_UNSUPPORTED"
CATALOG_FRESHNESS_NOT_CHECKED = "NOT_CHECKED_DURING_QUERY"

CATALOG_DIRECTORY = "catalog"
CATALOG_DOCUMENTS_FILE = "documents.jsonl"
CATALOG_MANIFEST_FILE = "manifest.json"

DERIVATION_NOTE = (
    "This catalog is a rebuildable derived search index, not primary evidence. "
    "Its fields come only from preserved normalized evidence or preserved raw SPL; "
    "consult and verify the named raw_path and raw_sha256 for primary-source use."
)

CATALOG_CANDIDATE_FIELDS = (
    "set_id",
    "source_version",
    "document_title",
    "brand_names",
    "generic_name",
    "active_ingredients",
    "effective_date",
    "document_type",
    "label_publisher",
    "label_repository",
    "regulatory_recipient",
    "jurisdiction",
    "fda_approval_status",
    "source_url",
    "raw_sha256",
    "raw_path",
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_BUILD_INSTRUCTION = "Run: odd catalog build --data-dir <data-dir>."

__all__ = [
    "CATALOG_CANDIDATE_FIELDS",
    "CATALOG_FRESHNESS_NOT_CHECKED",
    "CATALOG_INVALID",
    "CATALOG_NOT_BUILT",
    "CATALOG_SCHEMA_UNSUPPORTED",
    "CATALOG_SCHEMA_VERSION",
    "CatalogError",
    "CatalogSnapshot",
    "build_document_catalog",
    "load_document_catalog",
    "verify_document_catalog",
]


class CatalogError(Exception):
    """A stable catalog failure suitable for a CLI or MCP response."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": "error",
            "error": {"code": self.code, "details": self.details, "message": self.message},
        }


@dataclass(frozen=True, slots=True)
class CatalogSnapshot:
    """A fully integrity-checked catalog generation."""

    manifest: dict[str, Any]
    records: tuple[dict[str, Any], ...]

    @property
    def schema_version(self) -> str:
        return cast(str, self.manifest["schema_version"])

    @property
    def sha256(self) -> str:
        return cast(str, self.manifest["catalog_sha256"])

    @property
    def built_at(self) -> str:
        return cast(str, self.manifest["built_at"])

    @property
    def source_identity_fingerprint(self) -> str:
        return cast(str, self.manifest["source_identity_fingerprint"])


@dataclass(frozen=True, slots=True)
class _StoredSource:
    identity: SourceIdentity
    label_path: Path
    metadata_path: Path
    raw_path: str


@dataclass(frozen=True, slots=True)
class _Inventory:
    source_document_count: int
    sources: tuple[_StoredSource, ...]
    unindexed: tuple[dict[str, Any], ...]
    fingerprint: str


class _EvidenceUnavailable(Exception):
    pass


class _InventoryFailure(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def build_document_catalog(
    data_root: Path,
    *,
    parser: SPLParser | None = None,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Build a complete catalog generation without network access.

    A valid preserved full-evidence bundle is preferred.  When it is absent or
    unusable, only document-level search metadata is parsed from the preserved
    XML.  Raw and evidence artifacts are never changed.
    """

    started = time.perf_counter()
    root = data_root.resolve()
    inventory = _inventory(root)
    xml_parser = parser or SPLParser()
    records: list[dict[str, Any]] = []
    unindexed = list(inventory.unindexed)
    metadata_source_counts = {"preserved_evidence": 0, "preserved_raw": 0}

    for source in inventory.sources:
        try:
            try:
                record = _record_from_evidence(root, source)
            except _EvidenceUnavailable:
                parsed = xml_parser.parse_document_search_metadata(
                    source.label_path.read_bytes(), source.identity
                )
                record = _record_from_parsed(source, parsed)
            metadata_source = cast(str, record["metadata_source"])
            metadata_source_counts[metadata_source] += 1
            records.append(record)
        except (ODDError, OSError, ValueError) as error:
            if isinstance(error, ODDError):
                reason_code = error.category.value.upper()
                reason = error.message
            else:
                reason_code = "CATALOG_METADATA_READ_FAILED"
                reason = str(error)
            unindexed.append(_unindexed_source(source, reason_code, reason))

    records.sort(key=_record_order_key)
    unindexed.sort(key=_unindexed_order_key)
    documents_bytes = b"".join(canonical_json_bytes(record) + b"\n" for record in records)
    catalog_sha256 = sha256_bytes(documents_bytes)
    built_at = _iso_utc((clock or _utc_now)())
    manifest: dict[str, Any] = {
        "artifact_kind": "rebuildable_derived_search_index",
        "built_at": built_at,
        "catalog_bytes": len(documents_bytes),
        "catalog_file": f"{CATALOG_DIRECTORY}/{CATALOG_DOCUMENTS_FILE}",
        "catalog_sha256": catalog_sha256,
        "derivation_note": DERIVATION_NOTE,
        "indexed_count": len(records),
        "metadata_source_counts": metadata_source_counts,
        "primary_source": False,
        "record_count": len(records),
        "record_order": ["raw_path", "raw_sha256"],
        "record_schema_version": CATALOG_RECORD_SCHEMA_VERSION,
        "schema_version": CATALOG_SCHEMA_VERSION,
        "search_normalization": "Unicode casefold per source field; substring match",
        "source_document_count": inventory.source_document_count,
        "source_identity_fingerprint": inventory.fingerprint,
        "unindexed": unindexed,
        "unindexed_count": len(unindexed),
    }

    directory = root / CATALOG_DIRECTORY
    directory.mkdir(parents=True, exist_ok=True)
    # The manifest is the commit marker.  Replacing it last means no partial
    # generation can pass the reader's digest and count checks as the official
    # catalog, even if a reader arrives between the two replacements.
    _atomic_replace(directory / CATALOG_DOCUMENTS_FILE, documents_bytes)
    manifest_bytes = canonical_json_bytes(manifest) + b"\n"
    _atomic_replace(directory / CATALOG_MANIFEST_FILE, manifest_bytes)

    return {
        "status": "ok",
        "result": "BUILT",
        **manifest,
        "build_wall_seconds": round(time.perf_counter() - started, 6),
        "manifest_bytes": len(manifest_bytes),
    }


def load_document_catalog(data_root: Path) -> CatalogSnapshot:
    """Read and internally verify the current catalog generation only."""

    directory = data_root.resolve() / CATALOG_DIRECTORY
    manifest_path = directory / CATALOG_MANIFEST_FILE
    documents_path = directory / CATALOG_DOCUMENTS_FILE
    if not manifest_path.is_file():
        raise CatalogError(
            CATALOG_NOT_BUILT,
            f"the preserved-document catalog has not been built. {_BUILD_INSTRUCTION}",
            catalog_manifest=str(manifest_path),
        )
    manifest = _read_canonical_object(manifest_path, "catalog manifest")
    schema = manifest.get("schema_version")
    if not isinstance(schema, str):
        raise _invalid("catalog manifest has no string schema_version")
    if schema != CATALOG_SCHEMA_VERSION:
        raise CatalogError(
            CATALOG_SCHEMA_UNSUPPORTED,
            (
                f"catalog schema {schema!r} is unsupported by this ODD version. "
                f"{_BUILD_INSTRUCTION}"
            ),
            actual_schema_version=schema,
            supported_schema_version=CATALOG_SCHEMA_VERSION,
        )
    record_schema = manifest.get("record_schema_version")
    if record_schema != CATALOG_RECORD_SCHEMA_VERSION:
        raise CatalogError(
            CATALOG_SCHEMA_UNSUPPORTED,
            (
                f"catalog record schema {record_schema!r} is unsupported. "
                f"{_BUILD_INSTRUCTION}"
            ),
            actual_record_schema_version=record_schema,
            supported_record_schema_version=CATALOG_RECORD_SCHEMA_VERSION,
        )
    if not documents_path.is_file():
        raise _invalid(
            "catalog manifest exists but documents.jsonl is missing",
            catalog_file=str(documents_path),
        )
    try:
        documents_bytes = documents_path.read_bytes()
    except OSError as error:
        raise _invalid("catalog documents could not be read", reason=str(error)) from error

    expected_bytes = _manifest_nonnegative_int(manifest, "catalog_bytes")
    if len(documents_bytes) != expected_bytes:
        raise _invalid(
            "catalog byte count differs from its manifest",
            actual_bytes=len(documents_bytes),
            expected_bytes=expected_bytes,
        )
    expected_sha256 = _manifest_sha256(manifest, "catalog_sha256")
    actual_sha256 = sha256_bytes(documents_bytes)
    if actual_sha256 != expected_sha256:
        raise _invalid(
            "catalog SHA-256 differs from its manifest",
            actual_catalog_sha256=actual_sha256,
            expected_catalog_sha256=expected_sha256,
        )

    records = _read_records(documents_bytes)
    expected_count = _manifest_nonnegative_int(manifest, "record_count")
    indexed_count = _manifest_nonnegative_int(manifest, "indexed_count")
    if len(records) != expected_count or indexed_count != expected_count:
        raise _invalid(
            "catalog record count differs from its manifest",
            actual_record_count=len(records),
            expected_record_count=expected_count,
            indexed_count=indexed_count,
        )
    _validate_manifest_counts(manifest)
    return CatalogSnapshot(manifest=manifest, records=records)


def verify_document_catalog(data_root: Path) -> dict[str, Any]:
    """Verify catalog integrity and freshness without parsing any SPL XML."""

    root = data_root.resolve()
    snapshot = load_document_catalog(root)
    inventory = _inventory(root)
    manifest = snapshot.manifest
    recorded_source_count = _manifest_nonnegative_int(manifest, "source_document_count")
    if inventory.source_document_count != recorded_source_count:
        raise _invalid(
            "catalog source document count is stale",
            actual_source_document_count=inventory.source_document_count,
            catalog_source_document_count=recorded_source_count,
        )
    recorded_fingerprint = _manifest_sha256(manifest, "source_identity_fingerprint")
    if inventory.fingerprint != recorded_fingerprint:
        raise _invalid(
            "catalog source identity fingerprint is stale",
            actual_source_identity_fingerprint=inventory.fingerprint,
            catalog_source_identity_fingerprint=recorded_fingerprint,
        )

    by_identity = {
        (source.identity.source_document_id, source.identity.source_version): source
        for source in inventory.sources
    }
    for record in snapshot.records:
        key = (cast(str, record["set_id"]), cast(str, record["source_version"]))
        source = by_identity.get(key)
        if source is None:
            raise _invalid(
                "catalog record has no corresponding preserved raw manifest",
                set_id=key[0],
                source_version=key[1],
            )
        if record["raw_sha256"] != source.identity.raw_sha256:
            raise _invalid(
                "catalog raw SHA-256 differs from the preserved raw manifest",
                catalog_raw_sha256=record["raw_sha256"],
                manifest_raw_sha256=source.identity.raw_sha256,
                set_id=key[0],
                source_version=key[1],
            )
        if record["raw_path"] != source.raw_path:
            raise _invalid(
                "catalog raw path differs from the preserved storage identity",
                catalog_raw_path=record["raw_path"],
                expected_raw_path=source.raw_path,
                set_id=key[0],
                source_version=key[1],
            )
        raw_path = (root / source.raw_path).resolve()
        if not raw_path.is_relative_to(root) or not raw_path.is_file():
            raise _invalid(
                "catalog raw path does not name an existing file inside the data root",
                raw_path=source.raw_path,
                set_id=key[0],
                source_version=key[1],
            )

    inventory_raw_keys = {
        (source.raw_path, source.identity.raw_sha256) for source in inventory.sources
    } | {
        (cast(str, item["raw_path"]), cast(str, item["raw_sha256"]))
        for item in inventory.unindexed
    }
    manifest_unindexed = cast(list[dict[str, Any]], manifest["unindexed"])
    catalog_raw_keys = {
        (cast(str, record["raw_path"]), cast(str, record["raw_sha256"]))
        for record in snapshot.records
    } | {
        (cast(str, item["raw_path"]), cast(str, item["raw_sha256"]))
        for item in manifest_unindexed
    }
    if catalog_raw_keys != inventory_raw_keys:
        raise _invalid(
            "catalog indexed and unindexed identities do not cover the source inventory",
            catalog_only=sorted(catalog_raw_keys - inventory_raw_keys),
            source_only=sorted(inventory_raw_keys - catalog_raw_keys),
        )

    return {
        "status": "ok",
        "result": "VERIFIED",
        "catalog_schema_version": snapshot.schema_version,
        "catalog_sha256": snapshot.sha256,
        "catalog_record_count": len(snapshot.records),
        "catalog_built_at": snapshot.built_at,
        "source_document_count": inventory.source_document_count,
        "source_identity_fingerprint": inventory.fingerprint,
        "indexed_count": len(snapshot.records),
        "unindexed_count": _manifest_nonnegative_int(manifest, "unindexed_count"),
        "xml_documents_parsed": 0,
    }


def _inventory(data_root: Path) -> _Inventory:
    raw_root = data_root / "raw" / "dailymed"
    if not raw_root.is_dir():
        return _Inventory(
            source_document_count=0,
            sources=(),
            unindexed=(),
            fingerprint=_source_fingerprint(()),
        )

    sources: list[_StoredSource] = []
    unindexed: list[dict[str, Any]] = []
    source_document_count = 0
    for set_directory in sorted(raw_root.iterdir()):
        if not set_directory.is_dir():
            continue
        for version_directory in sorted(set_directory.iterdir()):
            label_path = version_directory / "label.xml"
            if not label_path.is_file():
                continue
            source_document_count += 1
            metadata_path = version_directory / "metadata.json"
            try:
                sources.append(
                    _stored_source(
                        data_root,
                        set_directory.name,
                        version_directory.name,
                        label_path,
                        metadata_path,
                    )
                )
            except _InventoryFailure as error:
                unindexed.append(
                    {
                        "raw_path": _relative(label_path, data_root),
                        "raw_sha256": _best_effort_raw_sha256(metadata_path),
                        "reason": error.message,
                        "reason_code": error.code,
                        "set_id": set_directory.name,
                        "source_version": version_directory.name,
                    }
                )

    fingerprint = _source_fingerprint(
        (
            source.identity.source_document_id,
            source.identity.source_version,
            source.identity.raw_sha256,
        )
        for source in sources
    )
    return _Inventory(
        source_document_count=source_document_count,
        sources=tuple(sources),
        unindexed=tuple(unindexed),
        fingerprint=fingerprint,
    )


def _stored_source(
    data_root: Path,
    stored_set_id: str,
    stored_version: str,
    label_path: Path,
    metadata_path: Path,
) -> _StoredSource:
    if not metadata_path.is_file():
        raise _InventoryFailure("RAW_MANIFEST_MISSING", "metadata.json is not preserved")
    try:
        payload = json.loads(metadata_path.read_bytes())
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise _InventoryFailure("RAW_MANIFEST_INVALID", str(error)) from error
    if not isinstance(payload, dict):
        raise _InventoryFailure("RAW_MANIFEST_INVALID", "metadata.json is not a JSON object")
    identity_payload = payload.get("source_identity")
    if not isinstance(identity_payload, dict):
        raise _InventoryFailure(
            "RAW_MANIFEST_INVALID", "metadata.json has no source_identity object"
        )
    identity_object = cast(dict[str, Any], identity_payload)
    set_id = _required_text(identity_object, "source_document_id")
    source_version = _required_text(identity_object, "source_version")
    if set_id.casefold() != stored_set_id.casefold() or source_version != stored_version:
        raise _InventoryFailure(
            "RAW_MANIFEST_IDENTITY_MISMATCH",
            "metadata source identity differs from its storage path",
        )
    raw_sha256 = _required_text(identity_object, "raw_sha256")
    if not _SHA256.fullmatch(raw_sha256):
        raise _InventoryFailure("RAW_MANIFEST_INVALID", "raw_sha256 is not a SHA-256")
    source_url_value = identity_object.get("source_url")
    source_url = source_url_value if isinstance(source_url_value, str) else None
    retrieved_at = _parse_datetime(_required_text(identity_object, "retrieved_at"))
    identity = SourceIdentity(
        authority=_required_text(identity_object, "authority"),
        provider=_required_text(identity_object, "provider"),
        jurisdiction=_required_text(identity_object, "jurisdiction"),
        source_document_id=set_id,
        source_version=source_version,
        source_url=source_url,
        retrieved_at=retrieved_at,
        raw_sha256=raw_sha256,
    )
    raw_path = _relative(label_path, data_root)
    return _StoredSource(
        identity=identity,
        label_path=label_path,
        metadata_path=metadata_path,
        raw_path=raw_path,
    )


def _record_from_evidence(data_root: Path, source: _StoredSource) -> dict[str, Any]:
    identity = source.identity
    evidence_path = (
        data_root
        / "evidence"
        / "core"
        / "dailymed"
        / identity.source_document_id
        / identity.source_version
        / "evidence.json"
    )
    if not evidence_path.is_file():
        raise _EvidenceUnavailable
    try:
        payload = json.loads(evidence_path.read_bytes())
        if not isinstance(payload, dict):
            raise ValueError("evidence is not a JSON object")
        evidence = cast(dict[str, Any], payload)
        drug = _required_object(evidence, "drug")
        label = _required_object(evidence, "label_source")
        official_id = _required_object(label, "official_document_id")
        version = _required_object(label, "document_version")
        if official_id.get("value") != identity.source_document_id:
            raise ValueError("evidence set_id differs from raw metadata")
        if version.get("value") != identity.source_version:
            raise ValueError("evidence source_version differs from raw metadata")
        if label.get("raw_sha256") != identity.raw_sha256:
            raise ValueError("evidence raw_sha256 differs from raw metadata")
        if label.get("raw_path") != source.raw_path:
            raise ValueError("evidence raw_path differs from preserved storage")

        title = _unknown_as_none(_optional_text(drug.get("document_title")))
        brands = _evidence_list(drug.get("brand_names"), "brand_names")
        generic_names = _evidence_list(drug.get("generic_names"), "generic_names")
        ingredients = _evidence_list(
            drug.get("active_ingredients"), "active_ingredients"
        )
        return _record(
            source,
            title=title,
            brand_names=brands,
            generic_name=generic_names[0] if generic_names else None,
            active_ingredients=ingredients,
            effective_date=_unknown_as_none(_optional_text(version.get("effective_date"))),
            document_type=_unknown_as_none(_optional_text(version.get("document_type"))),
            metadata_source="preserved_evidence",
        )
    except (OSError, json.JSONDecodeError, UnicodeDecodeError, ValueError, KeyError) as error:
        raise _EvidenceUnavailable from error


def _record_from_parsed(
    source: _StoredSource, parsed: DocumentSearchMetadata
) -> dict[str, Any]:
    return _record(
        source,
        title=parsed.title,
        brand_names=parsed.brand_names,
        generic_name=parsed.generic_name,
        active_ingredients=parsed.active_ingredients,
        effective_date=(
            parsed.effective_date.isoformat() if parsed.effective_date is not None else None
        ),
        document_type=parsed.document_type,
        metadata_source="preserved_raw",
    )


def _record(
    source: _StoredSource,
    *,
    title: str | None,
    brand_names: tuple[str, ...],
    generic_name: str | None,
    active_ingredients: tuple[str, ...],
    effective_date: str | None,
    document_type: str | None,
    metadata_source: str,
) -> dict[str, Any]:
    identity = source.identity
    search_values = (
        *((title,) if title else ()),
        *((generic_name,) if generic_name else ()),
        *brand_names,
        *active_ingredients,
    )
    return {
        "active_ingredients": list(active_ingredients) or UNKNOWN,
        "brand_names": list(brand_names) or UNKNOWN,
        "document_title": title or UNKNOWN,
        "document_type": document_type or UNKNOWN,
        "effective_date": effective_date or UNKNOWN,
        "fda_approval_status": UNKNOWN,
        "generic_name": generic_name or UNKNOWN,
        "jurisdiction": identity.jurisdiction,
        "label_publisher": LABEL_PUBLISHER,
        "label_repository": LABEL_REPOSITORY,
        "metadata_source": metadata_source,
        "raw_path": source.raw_path,
        "raw_sha256": identity.raw_sha256,
        "record_schema_version": CATALOG_RECORD_SCHEMA_VERSION,
        "regulatory_recipient": identity.authority,
        "search_values_normalized": [value.casefold() for value in search_values],
        "set_id": identity.source_document_id,
        "source_url": identity.source_url or UNKNOWN,
        "source_version": identity.source_version,
    }


def _read_records(documents_bytes: bytes) -> tuple[dict[str, Any], ...]:
    if documents_bytes and not documents_bytes.endswith(b"\n"):
        raise _invalid("catalog JSONL does not end with a newline")
    records: list[dict[str, Any]] = []
    for index, line in enumerate(documents_bytes.splitlines(), start=1):
        if not line:
            raise _invalid("catalog JSONL contains a blank record", line=index)
        try:
            value = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise _invalid("catalog JSONL contains invalid JSON", line=index) from error
        if not isinstance(value, dict):
            raise _invalid("catalog JSONL record is not an object", line=index)
        record = cast(dict[str, Any], value)
        if canonical_json_bytes(record) != line:
            raise _invalid("catalog JSONL record is not canonical JSON", line=index)
        _validate_record(record, index)
        records.append(record)

    if records != sorted(records, key=_record_order_key):
        raise _invalid("catalog records are not in canonical storage order")
    seen_keys: set[tuple[str, str, str, str]] = set()
    seen_identities: set[tuple[str, str]] = set()
    for record in records:
        key = (
            cast(str, record["set_id"]),
            cast(str, record["source_version"]),
            cast(str, record["raw_sha256"]),
            cast(str, record["raw_path"]),
        )
        identity_key = key[:2]
        if key in seen_keys or identity_key in seen_identities:
            raise _invalid(
                "catalog contains a duplicate raw document record",
                set_id=key[0],
                source_version=key[1],
                raw_sha256=key[2],
            )
        seen_keys.add(key)
        seen_identities.add(identity_key)
    return tuple(records)


def _validate_record(record: dict[str, Any], line: int) -> None:
    if record.get("record_schema_version") != CATALOG_RECORD_SCHEMA_VERSION:
        raise CatalogError(
            CATALOG_SCHEMA_UNSUPPORTED,
            "a catalog record uses an unsupported schema. " + _BUILD_INSTRUCTION,
            actual_record_schema_version=record.get("record_schema_version"),
            line=line,
            supported_record_schema_version=CATALOG_RECORD_SCHEMA_VERSION,
        )
    for field in (
        "set_id",
        "source_version",
        "document_title",
        "generic_name",
        "effective_date",
        "document_type",
        "label_publisher",
        "label_repository",
        "regulatory_recipient",
        "jurisdiction",
        "fda_approval_status",
        "source_url",
        "raw_path",
        "raw_sha256",
        "metadata_source",
    ):
        if not isinstance(record.get(field), str) or not cast(str, record[field]):
            raise _invalid("catalog record field is not a non-empty string", field=field, line=line)
    if not _SHA256.fullmatch(cast(str, record["raw_sha256"])):
        raise _invalid("catalog record raw_sha256 is invalid", line=line)
    for field in ("brand_names", "active_ingredients"):
        value = record.get(field)
        if value != UNKNOWN and not (
            isinstance(value, list)
            and value
            and all(isinstance(item, str) and item for item in value)
        ):
            raise _invalid("catalog record list field is invalid", field=field, line=line)
    normalized = record.get("search_values_normalized")
    if not isinstance(normalized, list) or not all(
        isinstance(value, str) and value for value in normalized
    ):
        raise _invalid("catalog search_values_normalized is invalid", line=line)
    if normalized != _expected_search_values(record):
        raise _invalid("catalog normalized search values differ from source fields", line=line)


def _expected_search_values(record: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for field in ("document_title", "generic_name"):
        value = record[field]
        if value != UNKNOWN:
            values.append(cast(str, value))
    for field in ("brand_names", "active_ingredients"):
        value = record[field]
        if isinstance(value, list):
            values.extend(cast(list[str], value))
    return [value.casefold() for value in values]


def _validate_manifest_counts(manifest: dict[str, Any]) -> None:
    source_count = _manifest_nonnegative_int(manifest, "source_document_count")
    indexed_count = _manifest_nonnegative_int(manifest, "indexed_count")
    unindexed_count = _manifest_nonnegative_int(manifest, "unindexed_count")
    unindexed = manifest.get("unindexed")
    if not isinstance(unindexed, list) or len(unindexed) != unindexed_count:
        raise _invalid("catalog unindexed count differs from its manifest entries")
    if indexed_count + unindexed_count != source_count:
        raise _invalid(
            "catalog indexed and unindexed counts do not cover every source document",
            indexed_count=indexed_count,
            source_document_count=source_count,
            unindexed_count=unindexed_count,
        )
    seen_unindexed: set[tuple[str, str]] = set()
    for index, value in enumerate(unindexed, start=1):
        if not isinstance(value, dict):
            raise _invalid("catalog unindexed entry is not an object", entry=index)
        item = cast(dict[str, Any], value)
        for field in (
            "set_id",
            "source_version",
            "raw_path",
            "raw_sha256",
            "reason_code",
            "reason",
        ):
            if not isinstance(item.get(field), str) or not cast(str, item[field]):
                raise _invalid(
                    "catalog unindexed field is not a non-empty string",
                    entry=index,
                    field=field,
                )
        raw_sha256 = cast(str, item["raw_sha256"])
        if raw_sha256 != UNKNOWN and not _SHA256.fullmatch(raw_sha256):
            raise _invalid("catalog unindexed raw_sha256 is invalid", entry=index)
        key = cast(str, item["raw_path"]), raw_sha256
        if key in seen_unindexed:
            raise _invalid("catalog contains a duplicate unindexed raw document", entry=index)
        seen_unindexed.add(key)
    _manifest_sha256(manifest, "source_identity_fingerprint")
    if not isinstance(manifest.get("built_at"), str):
        raise _invalid("catalog manifest has no built_at timestamp")
    if manifest.get("primary_source") is not False:
        raise _invalid("catalog manifest does not identify the artifact as derived")
    if manifest.get("record_order") != ["raw_path", "raw_sha256"]:
        raise _invalid("catalog manifest has an unsupported record ordering")


def _read_canonical_object(path: Path, description: str) -> dict[str, Any]:
    try:
        encoded = path.read_bytes()
        value = json.loads(encoded)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise _invalid(f"{description} is unreadable or invalid JSON", reason=str(error)) from error
    if not isinstance(value, dict):
        raise _invalid(f"{description} is not a JSON object")
    payload = cast(dict[str, Any], value)
    if encoded != canonical_json_bytes(payload) + b"\n":
        raise _invalid(f"{description} is not canonical JSON")
    return payload


def _manifest_nonnegative_int(manifest: dict[str, Any], field: str) -> int:
    value = manifest.get(field)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise _invalid("catalog manifest count is invalid", field=field, value=value)
    return value


def _manifest_sha256(manifest: dict[str, Any], field: str) -> str:
    value = manifest.get(field)
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise _invalid("catalog manifest SHA-256 is invalid", field=field, value=value)
    return value


def _source_fingerprint(identities: Iterable[tuple[str, str, str]]) -> str:
    ordered = sorted(identities)
    payload = [
        {"raw_sha256": raw_sha256, "set_id": set_id, "source_version": source_version}
        for set_id, source_version, raw_sha256 in ordered
    ]
    return sha256_bytes(canonical_json_bytes(payload))


def _atomic_replace(path: Path, content: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _record_order_key(record: dict[str, Any]) -> tuple[str, str]:
    return cast(str, record["raw_path"]), cast(str, record["raw_sha256"])


def _unindexed_order_key(record: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(record.get("raw_path", "")),
        str(record.get("raw_sha256", "")),
        str(record.get("reason_code", "")),
    )


def _unindexed_source(
    source: _StoredSource, reason_code: str, reason: str
) -> dict[str, Any]:
    identity = source.identity
    return {
        "raw_path": source.raw_path,
        "raw_sha256": identity.raw_sha256,
        "reason": reason,
        "reason_code": reason_code,
        "set_id": identity.source_document_id,
        "source_version": identity.source_version,
    }


def _required_object(payload: dict[str, Any], field: str) -> dict[str, Any]:
    value = payload.get(field)
    if not isinstance(value, dict):
        raise ValueError(f"{field} is not an object")
    return cast(dict[str, Any], value)


def _required_text(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise _InventoryFailure("RAW_MANIFEST_INVALID", f"{field} is missing")
    return value.strip()


def _optional_text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _unknown_as_none(value: str | None) -> str | None:
    return None if value in {None, UNKNOWN} else value


def _evidence_list(value: Any, field: str) -> tuple[str, ...]:
    if value == UNKNOWN or value is None:
        return ()
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise ValueError(f"evidence {field} is not a string list")
    return tuple(cast(list[str], value))


def _parse_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise _InventoryFailure("RAW_MANIFEST_INVALID", "retrieved_at is invalid") from error
    if parsed.tzinfo is None:
        raise _InventoryFailure("RAW_MANIFEST_INVALID", "retrieved_at has no timezone")
    return parsed.astimezone(UTC)


def _best_effort_raw_sha256(metadata_path: Path) -> str:
    try:
        payload = json.loads(metadata_path.read_bytes())
        if isinstance(payload, dict):
            identity = payload.get("source_identity")
            if isinstance(identity, dict):
                value = identity.get("raw_sha256")
                if isinstance(value, str) and _SHA256.fullmatch(value):
                    return value
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        pass
    return UNKNOWN


def _relative(path: Path, root: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(root.resolve()).as_posix()
    except ValueError as error:
        raise _InventoryFailure(
            "RAW_PATH_OUTSIDE_DATA_ROOT", "raw path escapes the configured data root"
        ) from error


def _iso_utc(value: datetime) -> str:
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return aware.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _invalid(message: str, **details: Any) -> CatalogError:
    return CatalogError(
        CATALOG_INVALID,
        message
        + " Run 'odd catalog verify --data-dir <data-dir>' for a full check, then rebuild.",
        **details,
    )

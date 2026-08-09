"""Immutable raw SPL storage and quarantine diagnostics."""

from __future__ import annotations

import base64
import json
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from odd.connectors.dailymed.selection import candidate_payload
from odd.constants import RAW_MANIFEST_VERSION
from odd.errors import (
    AmbiguousSourceSelection,
    MalformedMetadata,
    ODDError,
    ProvenanceValidationFailure,
    RawHashConflict,
    SourceNotFound,
)
from odd.models import (
    CandidateLookup,
    DailyMedHistory,
    DownloadedSource,
    RawDocument,
    SelectionDecision,
    SourceIdentity,
)
from odd.provenance.canonical import canonical_json_bytes
from odd.provenance.hashing import sha256_bytes, sha256_file

_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class RawStore:
    """Store exact response bytes at ``dailymed/{set_id}/{source_version}``."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def store(
        self,
        download: DownloadedSource,
        lookup: CandidateLookup,
        decision: SelectionDecision,
        history: DailyMedHistory | None = None,
    ) -> RawDocument:
        selected = decision.selected
        if (download.set_id, download.source_version) != (
            selected.set_id,
            selected.source_version,
        ):
            raise ProvenanceValidationFailure(
                "download identity differs from the selected DailyMed candidate"
            )
        raw_sha256 = sha256_bytes(download.body)
        identity = SourceIdentity(
            authority="FDA",
            provider="DailyMed",
            jurisdiction="United States",
            source_document_id=download.set_id,
            source_version=download.source_version,
            source_url=download.source_url,
            retrieved_at=_as_utc(download.retrieved_at),
            raw_sha256=raw_sha256,
        )
        directory = self._identity_directory(download.set_id, download.source_version)
        directory.mkdir(parents=True, exist_ok=True)
        label_path = directory / "label.xml"
        metadata_path = directory / "metadata.json"
        container_path = directory / "source.zip" if download.container_body is not None else None
        existed = label_path.exists()

        if existed:
            existing_sha = sha256_file(label_path)
            if existing_sha != raw_sha256:
                raise RawHashConflict(
                    "different raw bytes already exist at this DailyMed identity",
                    details={
                        "existing_raw_sha256": existing_sha,
                        "incoming_raw_sha256": raw_sha256,
                        "label_path": str(label_path),
                        "set_id": download.set_id,
                        "source_version": download.source_version,
                    },
                )
        else:
            if not _atomic_create(label_path, download.body):
                existed = True
                existing_sha = sha256_file(label_path)
                if existing_sha != raw_sha256:
                    raise RawHashConflict(
                        "different raw bytes won an atomic write at this DailyMed identity",
                        details={
                            "existing_raw_sha256": existing_sha,
                            "incoming_raw_sha256": raw_sha256,
                            "label_path": str(label_path),
                        },
                    )

        if sha256_file(label_path) != raw_sha256:
            raise ProvenanceValidationFailure(
                "raw SPL failed post-write SHA-256 verification",
                details={"label_path": str(label_path), "raw_sha256": raw_sha256},
            )

        if download.container_body is not None:
            if download.container_format != "zip" or not download.container_member:
                raise ProvenanceValidationFailure(
                    "historical transport container metadata is incomplete"
                )
            assert container_path is not None
            container_sha256 = sha256_bytes(download.container_body)
            if container_path.exists():
                existing_container_sha = sha256_file(container_path)
                if existing_container_sha != container_sha256:
                    raise RawHashConflict(
                        "different transport ZIP bytes already exist at this DailyMed identity",
                        details={
                            "existing_container_sha256": existing_container_sha,
                            "incoming_container_sha256": container_sha256,
                            "container_path": str(container_path),
                        },
                    )
            elif not _atomic_create(container_path, download.container_body):
                existing_container_sha = sha256_file(container_path)
                if existing_container_sha != container_sha256:
                    raise RawHashConflict(
                        "different transport ZIP bytes won an atomic historical-source write"
                    )

        manifest = self._manifest(identity, download, lookup, decision, history)
        encoded_manifest = canonical_json_bytes(manifest) + b"\n"
        if metadata_path.exists():
            existing_manifest = self._read_manifest(metadata_path)
            self._validate_manifest_identity(existing_manifest, identity)
        else:
            if not _atomic_create(metadata_path, encoded_manifest):
                existing_manifest = self._read_manifest(metadata_path)
                self._validate_manifest_identity(existing_manifest, identity)

        return RawDocument(
            identity=identity,
            label_path=label_path,
            metadata_path=metadata_path,
            metadata=self._read_manifest(metadata_path),
            already_stored=existed,
            container_path=container_path,
        )

    def resolve(self, set_id: str, source_version: str | None = None) -> RawDocument:
        self._validate_segment(set_id, "set_id")
        set_directory = (self.root / "dailymed" / set_id).resolve()
        if not set_directory.is_relative_to(self.root) or not set_directory.is_dir():
            raise SourceNotFound(
                "no stored raw DailyMed document exists for this set_id",
                details={"set_id": set_id},
            )
        if source_version is None:
            versions = sorted(
                (
                    item.name
                    for item in set_directory.iterdir()
                    if item.is_dir() and _SAFE_SEGMENT.fullmatch(item.name)
                ),
                key=_version_sort_key,
            )
            if not versions:
                raise SourceNotFound(
                    "no stored raw DailyMed versions exist for this set_id",
                    details={"set_id": set_id},
                )
            if len(versions) > 1:
                raise AmbiguousSourceSelection(
                    "multiple raw source versions are stored; specify --source-version",
                    details={"set_id": set_id, "source_versions": versions},
                )
            source_version = versions[0]
        directory = self._identity_directory(set_id, source_version)
        label_path = directory / "label.xml"
        metadata_path = directory / "metadata.json"
        if not label_path.is_file() or not metadata_path.is_file():
            raise SourceNotFound(
                "stored raw DailyMed identity is incomplete or absent",
                details={"set_id": set_id, "source_version": source_version},
            )
        manifest = self._read_manifest(metadata_path)
        identity = self._identity_from_manifest(manifest)
        if (identity.source_document_id, identity.source_version) != (set_id, source_version):
            raise ProvenanceValidationFailure(
                "raw metadata identity does not match its storage path",
                details={"metadata_path": str(metadata_path)},
            )
        calculated = sha256_file(label_path)
        if calculated != identity.raw_sha256:
            raise ProvenanceValidationFailure(
                "stored raw SPL hash does not match immutable metadata",
                details={
                    "actual_raw_sha256": calculated,
                    "expected_raw_sha256": identity.raw_sha256,
                    "label_path": str(label_path),
                },
            )
        return RawDocument(
            identity=identity,
            label_path=label_path,
            metadata_path=metadata_path,
            metadata=manifest,
            already_stored=True,
            container_path=(directory / "source.zip")
            if (directory / "source.zip").is_file()
            else None,
        )

    def _identity_directory(self, set_id: str, source_version: str) -> Path:
        self._validate_segment(set_id, "set_id")
        self._validate_segment(source_version, "source_version")
        directory = (self.root / "dailymed" / set_id / source_version).resolve()
        if not directory.is_relative_to(self.root):
            raise ProvenanceValidationFailure("raw storage path escaped its configured root")
        return directory

    @staticmethod
    def _manifest(
        identity: SourceIdentity,
        download: DownloadedSource,
        lookup: CandidateLookup,
        decision: SelectionDecision,
        history: DailyMedHistory | None,
    ) -> dict[str, Any]:
        retrieval: dict[str, Any] = {
            "headers": download.headers,
            "http_attempts": download.http_attempts,
            "http_status": download.status_code,
            "response_byte_length": len(
                download.container_body if download.container_body is not None else download.body
            ),
            "source_xml_byte_length": len(download.body),
            "source_xml_sha256": identity.raw_sha256,
        }
        if download.container_body is not None:
            retrieval["transport_container"] = {
                "format": download.container_format,
                "member": download.container_member,
                "path": "source.zip",
                "raw_sha256": sha256_bytes(download.container_body),
            }
        manifest: dict[str, Any] = {
            "candidate_metadata": [candidate_payload(item) for item in decision.ordered_candidates],
            "lookup": {
                "payload": lookup.payload,
                "raw_body_base64": base64.b64encode(lookup.raw_body).decode("ascii"),
                "raw_sha256": sha256_bytes(lookup.raw_body),
                "retrieved_at": _iso_utc(lookup.retrieved_at),
                "source_url": lookup.source_url,
            },
            "manifest_version": RAW_MANIFEST_VERSION,
            "retrieval": retrieval,
            "selection": {
                "ambiguity_exposed": decision.ambiguity_exposed,
                "candidate_count": len(decision.ordered_candidates),
                "reason": decision.reason,
                "rule_description": decision.rule_description,
                "rule_version": decision.rule_version,
                "selected_set_id": decision.selected.set_id,
                "selected_source_version": decision.selected.source_version,
            },
            "source_identity": {
                "authority": identity.authority,
                "jurisdiction": identity.jurisdiction,
                "provider": identity.provider,
                "raw_sha256": identity.raw_sha256,
                "retrieved_at": _iso_utc(identity.retrieved_at),
                "source_document_id": identity.source_document_id,
                "source_url": identity.source_url,
                "source_version": identity.source_version,
            },
        }
        if history is not None:
            manifest["history"] = {
                "payload": history.payload,
                "raw_body_base64": base64.b64encode(history.raw_body).decode("ascii"),
                "raw_sha256": sha256_bytes(history.raw_body),
                "retrieved_at": _iso_utc(history.retrieved_at),
                "source_url": history.source_url,
            }
        return manifest

    @staticmethod
    def _read_manifest(path: Path) -> dict[str, Any]:
        try:
            decoded = json.loads(path.read_bytes())
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MalformedMetadata(
                "stored raw metadata is not valid UTF-8 JSON",
                details={"metadata_path": str(path)},
            ) from exc
        if not isinstance(decoded, dict):
            raise MalformedMetadata("stored raw metadata must be a JSON object")
        return cast(dict[str, Any], decoded)

    @classmethod
    def _identity_from_manifest(cls, manifest: dict[str, Any]) -> SourceIdentity:
        value = manifest.get("source_identity")
        if not isinstance(value, dict):
            raise MalformedMetadata("raw metadata has no source_identity object")
        required = (
            "authority",
            "provider",
            "jurisdiction",
            "source_document_id",
            "source_version",
            "retrieved_at",
            "raw_sha256",
        )
        missing = [field for field in required if not value.get(field)]
        if missing:
            raise MalformedMetadata(
                "raw metadata is missing required provenance fields", details={"missing": missing}
            )
        raw_sha256 = value["raw_sha256"]
        if not isinstance(raw_sha256, str) or not _SHA256.fullmatch(raw_sha256):
            raise MalformedMetadata("raw metadata contains an invalid SHA-256")
        try:
            retrieved_at = datetime.fromisoformat(str(value["retrieved_at"]).replace("Z", "+00:00"))
        except ValueError as exc:
            raise MalformedMetadata("raw metadata contains an invalid retrieved_at") from exc
        source_url = value.get("source_url")
        if source_url is not None and not isinstance(source_url, str):
            raise MalformedMetadata("raw metadata source_url must be text or null")
        return SourceIdentity(
            authority=str(value["authority"]),
            provider=str(value["provider"]),
            jurisdiction=str(value["jurisdiction"]),
            source_document_id=str(value["source_document_id"]),
            source_version=str(value["source_version"]),
            source_url=source_url,
            retrieved_at=_as_utc(retrieved_at),
            raw_sha256=raw_sha256,
        )

    @staticmethod
    def _validate_manifest_identity(
        manifest: dict[str, Any], expected: SourceIdentity
    ) -> None:
        existing = RawStore._identity_from_manifest(manifest)
        stable_existing = (
            existing.authority,
            existing.provider,
            existing.jurisdiction,
            existing.source_document_id,
            existing.source_version,
            existing.raw_sha256,
        )
        stable_expected = (
            expected.authority,
            expected.provider,
            expected.jurisdiction,
            expected.source_document_id,
            expected.source_version,
            expected.raw_sha256,
        )
        if stable_existing != stable_expected:
            raise ProvenanceValidationFailure(
                "existing immutable raw metadata conflicts with the incoming source identity"
            )

    @staticmethod
    def _validate_segment(value: str, field_name: str) -> None:
        if value in {".", ".."} or not _SAFE_SEGMENT.fullmatch(value):
            raise ProvenanceValidationFailure(
                f"{field_name} is not safe for stable raw storage", details={field_name: value}
            )


class QuarantineStore:
    """Preserve conflict bytes or diagnostics without changing the immutable raw source."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def record(
        self,
        *,
        set_id: str,
        source_version: str,
        raw_sha256: str,
        stage: str,
        error: ODDError,
        recorded_at: datetime,
        raw_bytes: bytes | None = None,
        raw_path: Path | None = None,
        batch_run_id: str | None = None,
        ingredient_id: str | None = None,
        ingredient_name: str | None = None,
        rank: int | None = None,
        candidate_metadata: dict[str, Any] | None = None,
        quarantine_record_id: str | None = None,
    ) -> Path:
        safe_set_id = _quarantine_segment(set_id)
        safe_version = _quarantine_segment(source_version)
        safe_hash = raw_sha256 if _SHA256.fullmatch(raw_sha256) else "unknown-hash"
        directory = (self.root / "dailymed" / safe_set_id / safe_version / safe_hash).resolve()
        if not directory.is_relative_to(self.root):
            raise ProvenanceValidationFailure("quarantine path escaped its configured root")
        directory.mkdir(parents=True, exist_ok=True)
        if raw_bytes is not None:
            label_path = directory / "label.xml"
            if label_path.exists() and sha256_file(label_path) != sha256_bytes(raw_bytes):
                raise RawHashConflict("quarantine identity already contains different bytes")
            if not label_path.exists():
                _atomic_create(label_path, raw_bytes)
        diagnostic = {
            "batch_run_id": batch_run_id,
            "candidate_metadata": candidate_metadata,
            "diagnostic_message": error.message,
            "error_category": error.category.value,
            "error_details": error.details,
            "failure_stage": stage,
            "ingredient": {
                "ingredient_id": ingredient_id,
                "ingredient_name": ingredient_name,
                "rank": rank,
            },
            "original_raw_hash": raw_sha256,
            "raw_path": str(raw_path) if raw_path is not None else None,
            "recorded_at": _iso_utc(recorded_at),
            "quarantine_record_id": quarantine_record_id,
            "source_identity": {
                "provider": "DailyMed",
                "set_id": set_id,
                "source_version": source_version,
            },
        }
        diagnostic_name = (
            f"failure-{_quarantine_segment(quarantine_record_id)}.json"
            if quarantine_record_id
            else "failure.json"
        )
        diagnostic_path = directory / diagnostic_name
        if not diagnostic_path.exists():
            _atomic_create(diagnostic_path, canonical_json_bytes(diagnostic) + b"\n")
        return diagnostic_path


def _atomic_create(path: Path, content: bytes) -> bool:
    """Atomically create ``path`` without ever replacing an existing file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".odd-", suffix=".tmp", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary_path, path)
        except FileExistsError:
            return False
        return True
    finally:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


def _version_sort_key(value: str) -> tuple[int, int | str]:
    return (0, int(value)) if value.isdecimal() else (1, value)


def _quarantine_segment(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", value.strip()).strip(". ")
    return (cleaned or "unknown")[:128]


def _as_utc(value: datetime) -> datetime:
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return aware.astimezone(UTC)


def _iso_utc(value: datetime) -> str:
    return _as_utc(value).isoformat().replace("+00:00", "Z")

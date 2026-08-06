"""Independent verification of stored ODD-001 documents."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from odd.constants import MAPPING_VERSION, PARSER_VERSION, SCHEMA_VERSION
from odd.errors import SourceNotFound
from odd.models import SourceIdentity, VerificationCheck, VerificationResult
from odd.parsers.spl.parser import SPLParser
from odd.provenance.canonical import canonical_normalized_json_bytes
from odd.provenance.hashing import sha256_bytes
from odd.provenance.section_hash import section_sha256
from odd.storage.sqlite import SQLiteRepository


class Verifier:
    """Recompute hashes, relations, and deterministic parser output."""

    def __init__(self, repository: SQLiteRepository, parser: SPLParser | None = None) -> None:
        self.repository = repository
        self.parser = parser or SPLParser()

    def verify(self, document_id: str) -> VerificationResult:
        document = self.repository.get_document(document_id)
        source = self.repository.get_source_record(document_id)
        if document is None or source is None:
            raise SourceNotFound(
                "normalized document was not found", details={"document_id": document_id}
            )

        checks: list[VerificationCheck] = []
        required = (
            "authority",
            "provider",
            "jurisdiction",
            "source_document_id",
            "source_version",
            "retrieved_at",
            "raw_sha256",
            "raw_path",
            "metadata_path",
        )
        missing = [name for name in required if not source.get(name)]
        checks.append(
            VerificationCheck(
                name="required_provenance",
                ok=not missing,
                message="all required provenance fields are present"
                if not missing
                else f"missing fields: {', '.join(missing)}",
            )
        )

        raw_bytes: bytes | None = None
        raw_path = Path(str(source["raw_path"]))
        try:
            raw_bytes = raw_path.read_bytes()
            actual_hash = sha256_bytes(raw_bytes)
            raw_ok = actual_hash == source["raw_sha256"]
            raw_message = (
                f"raw SHA-256 verified: {actual_hash}"
                if raw_ok
                else f"raw SHA-256 mismatch: expected {source['raw_sha256']}, got {actual_hash}"
            )
        except OSError as exc:
            raw_ok = False
            raw_message = f"raw source could not be read: {exc}"
        checks.append(VerificationCheck("raw_sha256", raw_ok, raw_message))

        metadata_ok, metadata_message = _verify_metadata(source)
        checks.append(VerificationCheck("raw_metadata", metadata_ok, metadata_message))

        try:
            sections = self.repository.get_sections(document_id)
            mismatches = []
            for section in sections:
                actual = section_sha256(
                    source_section_code=section["source_section_code"],
                    original_heading=section["original_heading"],
                    original_text=section["original_text"],
                    structured_content=section["structured_content"],
                )
                if actual != section["section_sha256"]:
                    mismatches.append(section["section_id"])
            section_ok = not mismatches
            section_message = (
                f"verified {len(sections)} source-section SHA-256 values"
                if section_ok
                else f"section hash mismatch: {', '.join(mismatches)}"
            )
        except Exception as exc:  # verification must report each failed check
            sections = []
            section_ok = False
            section_message = f"section verification failed: {exc}"
        checks.append(VerificationCheck("section_sha256", section_ok, section_message))

        try:
            integrity = self.repository.integrity_checks(document_id)
            referential_ok = (
                not integrity["foreign_key_violations"]
                and integrity["orphan_mapping_count"] == 0
                and integrity["cross_document_parent_count"] == 0
                and integrity["document_count"] == 1
            )
            checks.append(
                VerificationCheck(
                    "referential_integrity",
                    referential_ok,
                    "foreign keys and document relationships verified"
                    if referential_ok
                    else f"referential integrity details: {integrity}",
                )
            )
            database_ok = integrity["integrity_check"] == "ok"
            checks.append(
                VerificationCheck(
                    "database_consistency",
                    database_ok,
                    f"SQLite integrity_check: {integrity['integrity_check']}",
                )
            )
        except Exception as exc:
            checks.append(
                VerificationCheck("referential_integrity", False, f"check failed: {exc}")
            )
            checks.append(
                VerificationCheck("database_consistency", False, f"check failed: {exc}")
            )

        deterministic_ok = False
        deterministic_message = "raw source unavailable"
        if raw_bytes is not None and raw_ok:
            versions_match = (
                document["parser_version"] == PARSER_VERSION
                and document["schema_version"] == SCHEMA_VERSION
                and document["mapping_version"] == MAPPING_VERSION
            )
            if not versions_match:
                deterministic_message = "stored parser/schema/mapping versions are unsupported"
            else:
                try:
                    identity = SourceIdentity(
                        authority=str(source["authority"]),
                        provider=str(source["provider"]),
                        jurisdiction=str(source["jurisdiction"]),
                        source_document_id=str(source["source_document_id"]),
                        source_version=str(source["source_version"]),
                        source_url=str(source["source_url"]) if source["source_url"] else None,
                        retrieved_at=datetime.fromisoformat(
                            str(source["retrieved_at"]).replace("Z", "+00:00")
                        ),
                        raw_sha256=str(source["raw_sha256"]),
                    )
                    reproduced = canonical_normalized_json_bytes(
                        self.parser.parse(raw_bytes, identity)
                    )
                    stored = self.repository.get_normalized_bytes(document_id)
                    deterministic_ok = stored == reproduced
                    deterministic_message = (
                        "canonical normalized JSON reproduced byte-for-byte"
                        if deterministic_ok
                        else "reproduced normalized JSON differs from the stored bytes"
                    )
                except Exception as exc:
                    deterministic_message = f"deterministic reproduction failed: {exc}"
        checks.append(
            VerificationCheck(
                "deterministic_normalization",
                deterministic_ok,
                deterministic_message,
            )
        )
        return VerificationResult(
            document_id=document_id,
            ok=all(item.ok for item in checks),
            checks=tuple(checks),
        )


def _verify_metadata(source: dict[str, Any]) -> tuple[bool, str]:
    try:
        payload = json.loads(Path(str(source["metadata_path"])).read_bytes())
        identity = payload["source_identity"]
        expected = {
            "authority": source["authority"],
            "jurisdiction": source["jurisdiction"],
            "provider": source["provider"],
            "raw_sha256": source["raw_sha256"],
            "source_document_id": source["source_document_id"],
            "source_version": source["source_version"],
        }
        mismatches = [key for key, value in expected.items() if identity.get(key) != value]
        if mismatches:
            return False, f"metadata identity mismatch: {', '.join(mismatches)}"
        return True, "immutable raw metadata matches the database source identity"
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        return False, f"raw metadata verification failed: {exc}"

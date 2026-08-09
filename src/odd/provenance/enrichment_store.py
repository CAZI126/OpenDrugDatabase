"""Immutable exact-byte evidence store for ODD-005 detail observations."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from odd.constants import ENRICHMENT_SNAPSHOT_VERSION
from odd.errors import ProvenanceValidationFailure, RawHashConflict
from odd.models.enrichment import DetailResponseEvidence, EvidenceAssertion
from odd.provenance.canonical import canonical_json_bytes
from odd.provenance.hashing import sha256_bytes

_IDENTIFIER = re.compile(r"^[0-9a-f-]{36}$")


@dataclass(frozen=True, slots=True)
class EnrichmentEvidenceStoreResult:
    logical_path: str
    canonical_manifest_sha256: str
    already_stored: bool


class EnrichmentEvidenceStore:
    """Store response bytes and cumulative snapshot manifests without replacement."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def store_response(
        self, response: DetailResponseEvidence
    ) -> EnrichmentEvidenceStoreResult:
        if response.raw_body is None or response.raw_sha256 is None:
            raise ProvenanceValidationFailure("failed HTTP attempts have no cacheable body")
        if sha256_bytes(response.raw_body) != response.raw_sha256:
            raise RawHashConflict("detail response bytes do not match their SHA-256")
        target = self._response_target(response.response_id)
        target.mkdir(parents=True, exist_ok=True)
        body_path = target / "response.body"
        metadata_path = target / "evidence.json"
        canonical_payload = {
            "attempts": response.attempts,
            "candidate_id": response.candidate_id,
            "canonical_request": response.canonical_request,
            "content_type": response.content_type,
            "error_category": response.error_category,
            "etag": response.etag,
            "expected_source_version": response.expected_source_version,
            "final_url": response.final_url,
            "last_modified": response.last_modified,
            "observed_source_version": response.observed_source_version,
            "page_number": response.page_number,
            "parent_discovery_snapshot_id": response.parent_discovery_snapshot_id,
            "raw_sha256": response.raw_sha256,
            "request_url": response.request_url,
            "response_id": response.response_id,
            "response_size": len(response.raw_body),
            "retrieved_at": response.retrieved_at,
            "set_id": response.set_id,
            "status_code": response.status_code,
            "tier": response.tier,
        }
        metadata = canonical_json_bytes(canonical_payload)
        metadata_digest = sha256_bytes(metadata)
        already_stored = True
        if body_path.exists():
            if body_path.read_bytes() != response.raw_body:
                raise RawHashConflict(
                    "detail response identity already stores different exact bytes"
                )
        else:
            _atomic_write_new(body_path, response.raw_body)
            already_stored = False
        if metadata_path.exists():
            if metadata_path.read_bytes() != metadata:
                raise RawHashConflict(
                    "detail response identity already stores different HTTP evidence"
                )
        else:
            _atomic_write_new(metadata_path, metadata)
            already_stored = False
        if not all(self.verify_response(response.response_id).values()):
            raise ProvenanceValidationFailure(
                "stored detail response failed immediate integrity verification"
            )
        return EnrichmentEvidenceStoreResult(
            logical_path=f"dailymed/enrichment/responses/{response.response_id}",
            canonical_manifest_sha256=metadata_digest,
            already_stored=already_stored,
        )

    def store_snapshot(
        self,
        *,
        snapshot_id: str,
        parent_snapshots: tuple[tuple[int, str], ...],
        response_hashes: tuple[tuple[str, str], ...],
        assertions: tuple[EvidenceAssertion, ...],
        completeness: str,
    ) -> EnrichmentEvidenceStoreResult:
        target = self._snapshot_target(snapshot_id)
        target.mkdir(parents=True, exist_ok=True)
        payload = {
            "assertion_identities": tuple(
                sorted(value.canonical_evidence_identity for value in assertions)
            ),
            "completeness": completeness,
            "parent_snapshots": parent_snapshots,
            "response_hashes": response_hashes,
            "snapshot_id": snapshot_id,
            "snapshot_version": ENRICHMENT_SNAPSHOT_VERSION,
        }
        body = canonical_json_bytes(payload)
        digest = sha256_bytes(body)
        manifest_path = target / "manifest.json"
        digest_path = target / "manifest.sha256"
        already_stored = True
        if manifest_path.exists():
            if manifest_path.read_bytes() != body:
                raise RawHashConflict(
                    "enrichment snapshot identity already stores different evidence"
                )
        else:
            _atomic_write_new(manifest_path, body)
            already_stored = False
        digest_body = f"{digest}\n".encode("ascii")
        if digest_path.exists():
            if digest_path.read_bytes() != digest_body:
                raise RawHashConflict("enrichment snapshot digest sidecar conflicts")
        else:
            _atomic_write_new(digest_path, digest_body)
            already_stored = False
        if not all(self.verify_snapshot(snapshot_id).values()):
            raise ProvenanceValidationFailure(
                "stored enrichment snapshot failed immediate integrity verification"
            )
        return EnrichmentEvidenceStoreResult(
            logical_path=f"dailymed/enrichment/snapshots/{snapshot_id}",
            canonical_manifest_sha256=digest,
            already_stored=already_stored,
        )

    def verify_response(self, response_id: str) -> dict[str, bool]:
        target = self._response_target(response_id)
        body_path = target / "response.body"
        metadata_path = target / "evidence.json"
        if not body_path.is_file() or not metadata_path.is_file():
            return {"body_found": False, "metadata_found": False, "raw_hash": False}
        try:
            metadata = json.loads(metadata_path.read_bytes())
            return {
                "body_found": True,
                "metadata_found": isinstance(metadata, dict),
                "raw_hash": isinstance(metadata, dict)
                and sha256_bytes(body_path.read_bytes()) == metadata.get("raw_sha256")
                and len(body_path.read_bytes()) == metadata.get("response_size"),
            }
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return {"body_found": True, "metadata_found": False, "raw_hash": False}

    def verify_snapshot(self, snapshot_id: str) -> dict[str, bool]:
        target = self._snapshot_target(snapshot_id)
        manifest_path = target / "manifest.json"
        digest_path = target / "manifest.sha256"
        if not manifest_path.is_file():
            return {"manifest_found": False, "manifest_hash": False, "response_hashes": False}
        try:
            body = manifest_path.read_bytes()
            payload = json.loads(body)
            digest_ok = (
                digest_path.is_file()
                and digest_path.read_text(encoding="ascii").strip() == sha256_bytes(body)
            )
            responses_ok = all(
                self._response_matches_manifest(
                    str(response_id), str(expected_raw_hash)
                )
                for response_id, expected_raw_hash in payload["response_hashes"]
            )
            return {
                "manifest_found": True,
                "manifest_hash": digest_ok,
                "response_hashes": responses_ok,
            }
        except (KeyError, OSError, TypeError, json.JSONDecodeError):
            return {"manifest_found": True, "manifest_hash": False, "response_hashes": False}

    def _response_target(self, response_id: str) -> Path:
        return self._safe_target("responses", response_id)

    def _response_matches_manifest(
        self, response_id: str, expected_raw_hash: str
    ) -> bool:
        if not all(self.verify_response(response_id).values()):
            return False
        try:
            metadata = json.loads(
                (self._response_target(response_id) / "evidence.json").read_bytes()
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return False
        return (
            isinstance(metadata, dict)
            and metadata.get("raw_sha256") == expected_raw_hash
        )

    def _snapshot_target(self, snapshot_id: str) -> Path:
        return self._safe_target("snapshots", snapshot_id)

    def _safe_target(self, category: str, identifier: str) -> Path:
        if not _IDENTIFIER.fullmatch(identifier):
            raise ProvenanceValidationFailure("unsafe enrichment evidence identity")
        base = (self.root / "dailymed" / "enrichment" / category).resolve()
        target = (base / identifier).resolve()
        if target.parent != base:
            raise ProvenanceValidationFailure("enrichment evidence path escaped its root")
        return target


def _atomic_write_new(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            raise RawHashConflict(
                f"immutable enrichment evidence path already exists: {path.name}"
            ) from exc
    finally:
        if temporary.exists():
            temporary.unlink()

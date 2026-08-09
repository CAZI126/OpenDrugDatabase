"""Immutable filesystem evidence for paginated DailyMed candidate snapshots."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from odd.constants import CONNECTOR_VERSION, LIVE_SNAPSHOT_VERSION
from odd.errors import ProvenanceValidationFailure, RawHashConflict
from odd.models import CandidateLookup
from odd.provenance.canonical import canonical_json_bytes
from odd.provenance.hashing import sha256_bytes
from odd.provenance.identifiers import live_candidate_snapshot_id


@dataclass(frozen=True, slots=True)
class DiscoveryStoreResult:
    snapshot_id: str
    directory: Path
    canonical_manifest_sha256: str
    already_stored: bool


class DiscoveryEvidenceStore:
    """Store exact page bytes without replacing an existing snapshot identity."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def store(self, lookup: CandidateLookup) -> DiscoveryStoreResult:
        if lookup.snapshot_id is None:
            raise ProvenanceValidationFailure("live discovery lookup has no snapshot ID")
        canonical_payload = _canonical_manifest_payload(lookup)
        canonical_sha256 = sha256_bytes(canonical_json_bytes(canonical_payload))
        target = self._target(lookup.snapshot_id)
        target.mkdir(parents=True, exist_ok=True)
        already_stored = True
        for page in lookup.pages:
            page_path = target / f"page-{page.page_number:04d}.response"
            if page_path.exists():
                if page_path.read_bytes() != page.raw_body:
                    raise RawHashConflict(
                        "live snapshot page identity already stores different response bytes",
                        details={"page": page.page_number, "snapshot_id": lookup.snapshot_id},
                    )
            else:
                _atomic_write_new(page_path, page.raw_body)
                already_stored = False

        manifest_path = target / "manifest.json"
        manifest = {
            **canonical_payload,
            "canonical_manifest_sha256": canonical_sha256,
            "diagnostic_message": lookup.diagnostic_message,
            "failure_attempts": lookup.failure_attempts,
            "pages": [
                {
                    "attempts": page.attempts,
                    "content_type": page.content_type,
                    "etag": page.etag,
                    "last_modified": page.last_modified,
                    "page_number": page.page_number,
                    "raw_sha256": page.raw_sha256,
                    "request_url": page.request_url,
                    "response_url": page.response_url,
                    "retrieved_at": page.retrieved_at,
                    "size_bytes": len(page.raw_body),
                    "status_code": page.status_code,
                }
                for page in lookup.pages
            ],
        }
        manifest_bytes = canonical_json_bytes(manifest)
        manifest_digest = sha256_bytes(manifest_bytes)
        digest_path = target / "manifest.sha256"
        if manifest_path.exists():
            try:
                existing_manifest_bytes = manifest_path.read_bytes()
                existing = json.loads(existing_manifest_bytes)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ProvenanceValidationFailure(
                    "live snapshot manifest could not be validated",
                    details={"snapshot_id": lookup.snapshot_id},
                ) from exc
            if not isinstance(existing, dict):
                raise ProvenanceValidationFailure(
                    "live snapshot manifest must contain a JSON object",
                    details={"snapshot_id": lookup.snapshot_id},
                )
            if existing.get("canonical_manifest_sha256") != canonical_sha256:
                raise RawHashConflict(
                    "live snapshot manifest identity already stores different evidence",
                    details={"snapshot_id": lookup.snapshot_id},
                )
            if _ensure_digest_sidecar(
                digest_path, sha256_bytes(existing_manifest_bytes)
            ):
                already_stored = False
        else:
            if digest_path.exists():
                raise RawHashConflict(
                    "live snapshot digest exists without its immutable manifest",
                    details={"snapshot_id": lookup.snapshot_id},
                )
            _atomic_write_new(manifest_path, manifest_bytes)
            _atomic_write_new(digest_path, f"{manifest_digest}\n".encode("ascii"))
            already_stored = False
        verification = self.verify(lookup.snapshot_id)
        if not all(verification.values()):
            raise ProvenanceValidationFailure(
                "stored live discovery evidence failed immediate integrity verification",
                details=verification,
            )
        return DiscoveryStoreResult(
            snapshot_id=lookup.snapshot_id,
            directory=target,
            canonical_manifest_sha256=canonical_sha256,
            already_stored=already_stored,
        )

    def verify(self, snapshot_id: str) -> dict[str, bool]:
        target = self._target(snapshot_id)
        manifest_path = target / "manifest.json"
        if not manifest_path.is_file():
            return {
                "manifest_found": False,
                "manifest_hash": False,
                "manifest_file_hash": False,
                "snapshot_identity": False,
                "page_hashes": False,
                "page_set": False,
            }
        try:
            manifest_bytes = manifest_path.read_bytes()
            payload = json.loads(manifest_bytes)
            digest_path = target / "manifest.sha256"
            manifest_file_ok = (
                digest_path.is_file()
                and digest_path.read_text(encoding="ascii").strip()
                == sha256_bytes(manifest_bytes)
            )
            expected_manifest_hash = str(payload["canonical_manifest_sha256"])
            canonical_payload = {
                key: payload[key]
                for key in (
                    "canonical_request",
                    "completeness",
                    "connector_version",
                    "duplicate_count",
                    "metadata_conflict_count",
                    "metadata_total_elements",
                    "page_hashes",
                    "retrieved_candidate_count",
                    "snapshot_id",
                    "snapshot_version",
                    "total_pages",
                )
            }
            manifest_ok = (
                sha256_bytes(canonical_json_bytes(canonical_payload))
                == expected_manifest_hash
            )
            terminal_fingerprint = ""
            if payload.get("diagnostic_message") is not None:
                terminal_fingerprint = sha256_bytes(
                    canonical_json_bytes(
                        {
                            "completeness": payload["completeness"],
                            "diagnostic": payload["diagnostic_message"],
                            "failure_attempts": payload["failure_attempts"],
                        }
                    )
                )
            identity_ok = (
                live_candidate_snapshot_id(
                    tuple(
                        (str(pair[0]), str(pair[1]))
                        for pair in payload["canonical_request"]
                    ),
                    tuple(
                        (int(pair[0]), str(pair[1])) for pair in payload["page_hashes"]
                    ),
                    connector_version=str(payload["connector_version"]),
                    terminal_fingerprint=terminal_fingerprint,
                )
                == str(payload["snapshot_id"])
            )
            page_hashes_ok = True
            expected_page_names: set[str] = set()
            for page_number, expected_hash in payload["page_hashes"]:
                page_path = target / f"page-{int(page_number):04d}.response"
                expected_page_names.add(page_path.name)
                if (
                    not page_path.is_file()
                    or sha256_bytes(page_path.read_bytes()) != str(expected_hash)
                ):
                    page_hashes_ok = False
                    break
            actual_page_names = {path.name for path in target.glob("page-*.response")}
            return {
                "manifest_found": True,
                "manifest_hash": manifest_ok,
                "manifest_file_hash": manifest_file_ok,
                "snapshot_identity": identity_ok,
                "page_hashes": page_hashes_ok,
                "page_set": actual_page_names == expected_page_names,
            }
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
            return {
                "manifest_found": True,
                "manifest_hash": False,
                "manifest_file_hash": False,
                "snapshot_identity": False,
                "page_hashes": False,
                "page_set": False,
            }

    def _target(self, snapshot_id: str) -> Path:
        if not snapshot_id or any(value in snapshot_id for value in ("/", "\\", "..")):
            raise ProvenanceValidationFailure("unsafe live snapshot identity")
        target = (self.root / "dailymed" / "discovery" / snapshot_id).resolve()
        expected_root = (self.root / "dailymed" / "discovery").resolve()
        if target.parent != expected_root:
            raise ProvenanceValidationFailure("live snapshot path escaped its evidence root")
        return target


def _canonical_manifest_payload(lookup: CandidateLookup) -> dict[str, object]:
    return {
        "canonical_request": lookup.canonical_request,
        "completeness": lookup.completeness,
        "connector_version": CONNECTOR_VERSION,
        "duplicate_count": lookup.duplicate_count,
        "metadata_conflict_count": lookup.metadata_conflict_count,
        "metadata_total_elements": lookup.metadata_total_elements,
        "page_hashes": tuple((page.page_number, page.raw_sha256) for page in lookup.pages),
        "retrieved_candidate_count": lookup.retrieved_candidate_count,
        "snapshot_id": lookup.snapshot_id,
        "snapshot_version": LIVE_SNAPSHOT_VERSION,
        "total_pages": lookup.total_pages,
    }


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
                f"immutable evidence path already exists: {path.name}"
            ) from exc
    finally:
        if temporary.exists():
            temporary.unlink()


def _ensure_digest_sidecar(path: Path, expected_digest: str) -> bool:
    """Validate a digest or finish an interrupted manifest-first write."""

    body = f"{expected_digest}\n".encode("ascii")
    if path.exists():
        try:
            if path.read_bytes() != body:
                raise RawHashConflict(
                    "live snapshot manifest digest conflicts with immutable evidence"
                )
        except OSError as exc:
            raise ProvenanceValidationFailure(
                "live snapshot manifest digest could not be read"
            ) from exc
        return False
    try:
        _atomic_write_new(path, body)
    except RawHashConflict:
        if not path.is_file() or path.read_bytes() != body:
            raise
        return False
    return True

"""Immutable raw source and provenance tests."""

from __future__ import annotations

import base64
import json
from dataclasses import replace
from pathlib import Path

import pytest

from odd.errors import ProvenanceValidationFailure, RawHashConflict
from odd.provenance.hashing import sha256_bytes
from odd.provenance.raw_store import QuarantineStore, RawStore
from tests.odd_support import (
    APIXABAN_SEARCH,
    ELIQUIS_XML,
    NOW,
    SET_ID,
    SOURCE_VERSION,
    connector,
)


def stored(tmp_path: Path):
    client, _transport = connector()
    lookup = client.lookup("apixaban")
    from odd.connectors.dailymed.selection import select_apixaban_candidate

    decision = select_apixaban_candidate(lookup)
    download = client.download(decision.selected)
    return RawStore(tmp_path / "raw").store(download, lookup, decision)


def test_fixture_sha256_is_stable() -> None:
    assert sha256_bytes(ELIQUIS_XML.read_bytes()) == (
        "9a71c970fecf8366ed97fe84588d8d3db7d8a84d0755a2f092df53012ccff261"
    )
    assert sha256_bytes(APIXABAN_SEARCH.read_bytes()) == (
        "e5aae58fda85ce740c33a6b1103c3860db53fff415a539c6041ea69bb3f75132"
    )


def test_exact_raw_bytes_are_preserved_at_stable_identity_path(tmp_path: Path) -> None:
    raw = stored(tmp_path)
    assert raw.label_path == (
        tmp_path
        / "raw"
        / "dailymed"
        / SET_ID
        / SOURCE_VERSION
        / "label.xml"
    ).resolve()
    assert raw.label_path.read_bytes() == ELIQUIS_XML.read_bytes()


def test_required_source_identity_fields_are_recorded(tmp_path: Path) -> None:
    identity = stored(tmp_path).identity
    assert identity.authority == "FDA"
    assert identity.provider == "DailyMed"
    assert identity.jurisdiction == "United States"
    assert identity.source_document_id == SET_ID
    assert identity.source_version == SOURCE_VERSION
    assert identity.source_url
    assert identity.retrieved_at == NOW
    assert len(identity.raw_sha256) == 64


def test_candidate_metadata_and_exact_lookup_body_are_preserved(tmp_path: Path) -> None:
    raw = stored(tmp_path)
    metadata = json.loads(raw.metadata_path.read_bytes())
    assert len(metadata["candidate_metadata"]) == 2
    restored = base64.b64decode(metadata["lookup"]["raw_body_base64"])
    assert restored == APIXABAN_SEARCH.read_bytes()
    assert metadata["lookup"]["raw_sha256"] == sha256_bytes(restored)
    assert metadata["selection"]["ambiguity_exposed"] is True
    assert metadata["selection"]["selected_set_id"] == SET_ID


def test_identical_raw_ingestion_is_idempotent(tmp_path: Path) -> None:
    first = stored(tmp_path)
    second = stored(tmp_path)
    assert first.already_stored is False
    assert second.already_stored is True
    assert first.label_path == second.label_path
    assert first.metadata_path.read_bytes() == second.metadata_path.read_bytes()


def test_conflicting_content_at_same_identity_fails_closed(tmp_path: Path) -> None:
    first = stored(tmp_path)
    client, _transport = connector(xml_body=ELIQUIS_XML.read_bytes() + b"\nconflict")
    lookup = client.lookup("apixaban")
    from odd.connectors.dailymed.selection import select_apixaban_candidate

    decision = select_apixaban_candidate(lookup)
    incoming = client.download(decision.selected)
    with pytest.raises(RawHashConflict) as error:
        RawStore(tmp_path / "raw").store(incoming, lookup, decision)
    assert first.label_path.read_bytes() == ELIQUIS_XML.read_bytes()
    assert error.value.details["incoming_raw_sha256"] == sha256_bytes(incoming.body)


def test_tampered_raw_document_fails_provenance_validation(tmp_path: Path) -> None:
    raw = stored(tmp_path)
    raw.label_path.write_bytes(b"tampered")
    with pytest.raises(ProvenanceValidationFailure, match="hash"):
        RawStore(tmp_path / "raw").resolve(SET_ID, SOURCE_VERSION)


def test_atomic_storage_leaves_no_temporary_files(tmp_path: Path) -> None:
    raw = stored(tmp_path)
    assert not list(raw.label_path.parent.glob(".odd-*.tmp"))


def test_quarantine_preserves_incoming_conflict_bytes_and_diagnostic(tmp_path: Path) -> None:
    incoming = b"different incoming bytes"
    error = RawHashConflict("identity conflict", details={"existing": "a" * 64})
    path = QuarantineStore(tmp_path / "quarantine").record(
        set_id=SET_ID,
        source_version=SOURCE_VERSION,
        raw_sha256=sha256_bytes(incoming),
        stage="raw_storage",
        error=error,
        recorded_at=NOW,
        raw_bytes=incoming,
    )
    assert path.is_file()
    assert path.with_name("label.xml").read_bytes() == incoming
    diagnostic = json.loads(path.read_bytes())
    assert diagnostic["error_category"] == "raw_hash_conflict"
    assert diagnostic["original_raw_hash"] == sha256_bytes(incoming)


def test_manifest_identity_conflict_is_not_overwritten(tmp_path: Path) -> None:
    raw = stored(tmp_path)
    manifest = json.loads(raw.metadata_path.read_bytes())
    manifest["source_identity"]["provider"] = "Other"
    raw.metadata_path.write_text(json.dumps(manifest), encoding="utf-8")
    client, _transport = connector()
    lookup = client.lookup("apixaban")
    from odd.connectors.dailymed.selection import select_apixaban_candidate

    decision = select_apixaban_candidate(lookup)
    with pytest.raises(ProvenanceValidationFailure, match="conflicts"):
        RawStore(tmp_path / "raw").store(client.download(decision.selected), lookup, decision)


def test_download_identity_mismatch_is_rejected(tmp_path: Path) -> None:
    client, _transport = connector()
    lookup = client.lookup("apixaban")
    from odd.connectors.dailymed.selection import select_apixaban_candidate

    decision = select_apixaban_candidate(lookup)
    mismatched = replace(client.download(decision.selected), source_version="29")
    with pytest.raises(ProvenanceValidationFailure):
        RawStore(tmp_path / "raw").store(mismatched, lookup, decision)

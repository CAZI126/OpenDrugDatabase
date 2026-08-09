"""Immutable filesystem evidence tests for ODD-004 discovery snapshots."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from odd.errors import RawHashConflict
from odd.provenance.discovery_store import DiscoveryEvidenceStore
from odd.provenance.hashing import sha256_bytes
from tests.odd004_support import (
    SequenceTransport,
    discovery_body,
    discovery_candidate,
    live_connector,
    response,
)


def _lookup():
    body = discovery_body([discovery_candidate("atorvastatin")])
    return live_connector(SequenceTransport([response(body)])).discover("atorvastatin")


def test_exact_discovery_pages_and_manifest_are_idempotent(tmp_path) -> None:
    lookup = _lookup()
    store = DiscoveryEvidenceStore(tmp_path / "evidence")
    first = store.store(lookup)
    second = store.store(lookup)

    assert first.already_stored is False
    assert second.already_stored is True
    assert first.canonical_manifest_sha256 == second.canonical_manifest_sha256
    assert all(store.verify(first.snapshot_id).values())
    assert (first.directory / "page-0001.response").read_bytes() == lookup.pages[0].raw_body
    assert len((first.directory / "manifest.sha256").read_text().strip()) == 64


def test_interrupted_manifest_write_recovers_missing_digest_sidecar(tmp_path) -> None:
    lookup = _lookup()
    store = DiscoveryEvidenceStore(tmp_path / "evidence")
    first = store.store(lookup)
    (first.directory / "manifest.sha256").unlink()

    recovered = store.store(lookup)
    unchanged = store.store(lookup)

    assert recovered.already_stored is False
    assert unchanged.already_stored is True
    assert all(store.verify(first.snapshot_id).values())


def test_same_snapshot_identity_rejects_different_page_bytes(tmp_path) -> None:
    lookup = _lookup()
    store = DiscoveryEvidenceStore(tmp_path / "evidence")
    store.store(lookup)
    changed_page = replace(
        lookup.pages[0],
        raw_body=lookup.pages[0].raw_body + b" ",
        raw_sha256=sha256_bytes(lookup.pages[0].raw_body + b" "),
    )
    conflicting = replace(lookup, pages=(changed_page,))

    with pytest.raises(RawHashConflict):
        store.store(conflicting)


def test_manifest_operational_metadata_tampering_is_detected(tmp_path) -> None:
    lookup = _lookup()
    store = DiscoveryEvidenceStore(tmp_path / "evidence")
    result = store.store(lookup)
    manifest_path = result.directory / "manifest.json"
    payload = json.loads(manifest_path.read_bytes())
    payload["diagnostic_message"] = "tampered"
    manifest_path.write_text(
        json.dumps(payload, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )

    verification = store.verify(result.snapshot_id)
    assert verification["manifest_hash"] is True
    assert verification["manifest_file_hash"] is False


def test_unmanifested_extra_page_is_detected(tmp_path) -> None:
    lookup = _lookup()
    store = DiscoveryEvidenceStore(tmp_path / "evidence")
    result = store.store(lookup)
    (result.directory / "page-9999.response").write_bytes(b"unexpected")
    assert store.verify(result.snapshot_id)["page_set"] is False

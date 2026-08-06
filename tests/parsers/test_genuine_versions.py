from __future__ import annotations

from datetime import UTC, datetime

from odd.diffs.source_identifiers import extract_section_xml_identifiers
from odd.models import SourceIdentity
from odd.parsers.spl.parser import SPLParser
from odd.provenance.canonical import canonical_normalized_json_bytes
from odd.provenance.hashing import sha256_bytes
from tests.odd002_support import (
    ELIQUIS_V29_XML,
    ELIQUIS_V30_XML,
    SET_ID,
    V29_DOCUMENT_ID,
    V29_SHA256,
    V30_DOCUMENT_ID,
    V30_SHA256,
)


def _parse(path, version: str):
    raw = path.read_bytes()
    identity = SourceIdentity(
        authority="FDA",
        provider="DailyMed",
        jurisdiction="United States",
        source_document_id=SET_ID,
        source_version=version,
        source_url=f"https://dailymed.example/{version}",
        retrieved_at=datetime(2026, 8, 6, tzinfo=UTC),
        raw_sha256=sha256_bytes(raw),
    )
    return SPLParser().parse(raw, identity)


def test_genuine_versions_parse_with_reviewed_identity_and_counts() -> None:
    old = _parse(ELIQUIS_V29_XML, "29")
    new = _parse(ELIQUIS_V30_XML, "30")

    assert old.document.document_id == V29_DOCUMENT_ID
    assert new.document.document_id == V30_DOCUMENT_ID
    assert old.document.source_identity.raw_sha256 == V29_SHA256
    assert new.document.source_identity.raw_sha256 == V30_SHA256
    assert old.document.effective_date.isoformat() == "2021-09-30"
    assert new.document.effective_date.isoformat() == "2025-04-17"
    assert (len(old.sections), len(new.sections)) == (93, 88)
    assert (
        len({item.section_id for item in old.semantic_mappings}),
        len({item.section_id for item in new.semantic_mappings}),
    ) == (39, 34)


def test_each_genuine_version_normalizes_byte_identically_on_repeat() -> None:
    for path, version in ((ELIQUIS_V29_XML, "29"), (ELIQUIS_V30_XML, "30")):
        first = _parse(path, version)
        second = _parse(path, version)
        assert canonical_normalized_json_bytes(first) == canonical_normalized_json_bytes(second)


def test_source_owned_xml_section_identifiers_are_recovered_for_matching() -> None:
    old = extract_section_xml_identifiers(ELIQUIS_V29_XML.read_bytes())
    new = extract_section_xml_identifiers(ELIQUIS_V30_XML.read_bytes())

    assert len(old) == 93
    assert len(new) == 88
    assert len(set(old.values()) & set(new.values())) == 24
    assert all(locator.startswith("/document[1]") for locator in old)

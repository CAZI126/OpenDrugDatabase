"""Synthetic structural-diversity checks; these are not clinical validation."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from odd.models import SourceIdentity
from odd.parsers.spl.parser import SPLParser
from odd.provenance.hashing import sha256_bytes

FIXTURE = (
    Path(__file__).parents[1]
    / "fixtures"
    / "dailymed"
    / "odd003"
    / "highly_unmapped_spl.xml"
)


def test_successful_highly_unmapped_document_is_reportable() -> None:
    raw = FIXTURE.read_bytes()
    identity = SourceIdentity(
        authority="FDA",
        provider="DailyMed",
        jurisdiction="United States",
        source_document_id="bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb",
        source_version="1",
        source_url=None,
        retrieved_at=datetime(2026, 8, 7, tzinfo=UTC),
        raw_sha256=sha256_bytes(raw),
    )
    parsed = SPLParser().parse(raw, identity)
    assert len(parsed.sections) == 5
    assert parsed.semantic_mappings == ()
    assert [section.original_heading for section in parsed.sections] == [
        "UNMAPPED ALPHA",
        "UNMAPPED BETA",
        "UNMAPPED GAMMA",
        "UNMAPPED DELTA",
        "UNMAPPED EPSILON",
    ]

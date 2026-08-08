"""Versioned utilization input validation and canonicalization."""

from __future__ import annotations

import json

import pytest

from odd.errors import UtilizationInputInvalid
from odd.provenance.hashing import sha256_bytes
from odd.provenance.identifiers import ingredient_id
from odd.utilization import (
    canonical_utilization_list_bytes,
    ingredient_identity,
    load_utilization_list,
    normalize_ingredient_name,
    utilization_list_from_payload,
)


def _payload() -> dict[str, object]:
    return json.loads(canonical_utilization_list_bytes(load_utilization_list()))


def test_top_ten_order_is_fixed() -> None:
    value = load_utilization_list("us-top10-2023")
    assert [entry.rank for entry in value.entries] == list(range(1, 11))
    assert [entry.ingredient_name for entry in value.entries] == [
        "atorvastatin",
        "metformin",
        "levothyroxine",
        "lisinopril",
        "amlodipine",
        "metoprolol",
        "albuterol",
        "losartan",
        "gabapentin",
        "omeprazole",
    ]


def test_counts_are_intentionally_absent() -> None:
    value = load_utilization_list()
    assert value.metric == "rank_only"
    assert all(entry.metric_value is None and entry.metric_unit is None for entry in value.entries)
    assert "not FDA or DailyMed regulatory data" in value.notes


def test_duplicate_rank_is_rejected() -> None:
    payload = _payload()
    entries = payload["entries"]
    assert isinstance(entries, list)
    entries[1]["rank"] = 1
    with pytest.raises(UtilizationInputInvalid, match="duplicate utilization rank"):
        utilization_list_from_payload(payload)


def test_duplicate_normalized_ingredient_is_rejected() -> None:
    payload = _payload()
    entries = payload["entries"]
    assert isinstance(entries, list)
    entries[1]["ingredient_name"] = "  ATORVASTATIN  "
    with pytest.raises(UtilizationInputInvalid, match="duplicate normalized"):
        utilization_list_from_payload(payload)


def test_non_contiguous_rank_is_rejected() -> None:
    payload = _payload()
    entries = payload["entries"]
    assert isinstance(entries, list)
    entries[-1]["rank"] = 11
    with pytest.raises(UtilizationInputInvalid, match="contiguous"):
        utilization_list_from_payload(payload)


def test_normalization_is_unicode_and_whitespace_deterministic() -> None:
    assert normalize_ingredient_name("  ＭＥＴＦＯＲＭＩＮ\t") == "metformin"


def test_ingredient_identity_is_internal_not_regulatory() -> None:
    entry = load_utilization_list().entries[0]
    identity = ingredient_identity(entry)
    assert identity.ingredient_id == ingredient_id("atorvastatin")
    assert identity.ingredient_id != entry.ingredient_name
    assert identity.synonyms_used == ()


def test_canonical_list_serialization_is_reproducible() -> None:
    first = canonical_utilization_list_bytes(load_utilization_list())
    second = canonical_utilization_list_bytes(load_utilization_list())
    assert first == second
    assert sha256_bytes(first) == (
        "0b0cee921586ed377c982d396b5d8225fff05905a1417dee05a93bd36dcf7ee1"
    )
    assert b'"retrieved_at":"2026-08-07T00:00:00Z"' in first

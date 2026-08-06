"""Offline DailyMed connector and selection tests."""

from __future__ import annotations

import json

import pytest

from odd.connectors.dailymed.selection import select_apixaban_candidate
from odd.errors import (
    AmbiguousSourceSelection,
    MalformedMetadata,
    NetworkFailure,
    SourceNotFound,
)
from odd.models import CandidateLookup, DailyMedCandidate
from tests.odd_support import APIXABAN_SEARCH, ELIQUIS_XML, NOW, SET_ID, connector


def test_successful_metadata_lookup_preserves_response() -> None:
    client, _transport = connector()
    result = client.lookup("apixaban")
    assert result.raw_body == APIXABAN_SEARCH.read_bytes()
    assert result.payload["metadata"]["total_elements"] == "2"
    assert [item.set_id for item in result.candidates] == [
        "4a000000-0000-4000-8000-000000000004",
        SET_ID,
    ]


def test_multiple_candidate_metadata_is_preserved() -> None:
    client, _transport = connector()
    candidates = client.lookup("apixaban").candidates
    assert len(candidates) == 2
    assert candidates[0].metadata["title"].startswith("APIXABAN-")
    assert candidates[1].metadata["spl_version"] == "30"


def test_deterministic_candidate_selection_prefers_unique_eliquis_set() -> None:
    client, _transport = connector()
    decision = select_apixaban_candidate(client.lookup("apixaban"))
    assert decision.selected.set_id == SET_ID
    assert decision.selected.source_version == "30"
    assert decision.ambiguity_exposed is True
    assert "unique set_id" in decision.reason


def test_selection_chooses_highest_numeric_version_within_one_set() -> None:
    base = DailyMedCandidate(SET_ID, "9", "ELIQUIS- apixaban tablet", "May 01, 2025")
    newer = DailyMedCandidate(SET_ID, "30", "ELIQUIS- apixaban tablet", "Apr 17, 2025")
    lookup = CandidateLookup((base, newer), "fixture://search", NOW, b"{}", {})
    assert select_apixaban_candidate(lookup).selected.source_version == "30"


def test_ambiguous_preferred_brand_selection_fails_with_candidates() -> None:
    candidates = (
        DailyMedCandidate("set-a", "1", "ELIQUIS- apixaban tablet", "Apr 17, 2025"),
        DailyMedCandidate("set-b", "2", "ELIQUIS- apixaban tablet", "Apr 18, 2025"),
    )
    lookup = CandidateLookup(candidates, "fixture://search", NOW, b"{}", {})
    with pytest.raises(AmbiguousSourceSelection) as error:
        select_apixaban_candidate(lookup)
    assert error.value.details["candidate_count"] == 2
    assert len(error.value.details["candidates"]) == 2


def test_no_candidates_is_explicit() -> None:
    lookup = CandidateLookup((), "fixture://search", NOW, b"{}", {})
    with pytest.raises(SourceNotFound):
        select_apixaban_candidate(lookup)


def test_successful_xml_retrieval_preserves_exact_bytes() -> None:
    client, _transport = connector()
    selected = select_apixaban_candidate(client.lookup("apixaban")).selected
    download = client.download(selected)
    assert download.body == ELIQUIS_XML.read_bytes()
    assert download.set_id == SET_ID
    assert download.headers["content-type"] == "application/xml"


def test_network_failure_is_not_converted_to_success() -> None:
    failure = NetworkFailure("offline")
    client, _transport = connector(error=failure)
    with pytest.raises(NetworkFailure, match="offline"):
        client.lookup("apixaban")


def test_non_success_status_is_network_failure() -> None:
    client, _transport = connector(status_code=503)
    with pytest.raises(NetworkFailure) as error:
        client.lookup("apixaban")
    assert error.value.details["status_code"] == 503


@pytest.mark.parametrize(
    "body",
    [b"not-json", b"[]", b'{"metadata": {}}', b'{"data": [null]}'],
)
def test_malformed_metadata_response_is_explicit(body: bytes) -> None:
    client, _transport = connector(search_body=body)
    with pytest.raises(MalformedMetadata):
        client.lookup("apixaban")


def test_query_is_encoded_and_request_contract_is_explicit() -> None:
    client, transport = connector()
    client.lookup("apixaban + test")
    url, headers, timeout = transport.requests[0]
    assert "drug_name=apixaban+%2B+test" in url
    assert "pagesize=100" in url
    assert headers == {"Accept": "application/json", "User-Agent": "ODD-test/1"}
    assert timeout == 7


def test_integer_source_version_is_normalized_to_text() -> None:
    payload = json.loads(APIXABAN_SEARCH.read_bytes())
    payload["data"][1]["spl_version"] = 30
    client, _transport = connector(search_body=json.dumps(payload).encode())
    assert client.lookup("apixaban").candidates[1].source_version == "30"

"""Offline ODD-004 pagination, HTTP safety, and snapshot determinism tests."""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from http.client import HTTPMessage
from io import BytesIO
from urllib.request import Request

import pytest

from odd.connectors.dailymed.batch_selection import classify_and_select_candidates
from odd.connectors.dailymed.client import (
    MAX_JSON_RESPONSE_BYTES,
    DailyMedConnector,
    _SameOriginRedirectHandler,
)
from odd.errors import NetworkFailure
from odd.models import DiscoveryCompleteness, SelectionStatus
from odd.provenance.hashing import sha256_bytes
from odd.utilization import ingredient_identity, load_utilization_list
from tests.odd004_support import (
    BASE_URL,
    SequenceTransport,
    discovery_body,
    discovery_candidate,
    live_connector,
    response,
)


def test_discover_retrieves_and_hashes_every_advertised_page() -> None:
    first = discovery_candidate("atorvastatin", rank=1)
    second = discovery_candidate("atorvastatin", rank=2, source_version="2")
    transport = SequenceTransport(
        [
            response(
                discovery_body(
                    [first],
                    current_page="1",
                    elements_per_page="1",
                    total_elements="2",
                    total_pages="2",
                ),
                headers={"etag": '"page-one"'},
            ),
            response(
                discovery_body(
                    [second],
                    current_page="2",
                    elements_per_page="1",
                    total_elements="2",
                    total_pages="2",
                ),
                headers={"last-modified": "Sat, 08 Aug 2026 00:00:00 GMT"},
            ),
        ]
    )
    lookup = live_connector(transport).discover("atorvastatin")

    assert lookup.completeness is DiscoveryCompleteness.COMPLETE
    assert lookup.metadata_total_elements == lookup.retrieved_candidate_count == 2
    assert lookup.total_pages == 2
    assert [page.page_number for page in lookup.pages] == [1, 2]
    assert lookup.pages[0].etag == '"page-one"'
    assert lookup.pages[1].last_modified == "Sat, 08 Aug 2026 00:00:00 GMT"
    assert all(page.raw_sha256 == sha256_bytes(page.raw_body) for page in lookup.pages)
    assert ("endpoint", f"{BASE_URL}/spls.json") in lookup.canonical_request
    assert all("doctype=34391-3" in url for url in transport.requests)
    assert all("name_type=generic" in url for url in transport.requests)


def test_response_order_changes_exact_snapshot_but_not_candidate_order_or_result() -> None:
    older = discovery_candidate(
        "atorvastatin",
        rank=1,
        source_version="1",
        complete_selection_metadata=True,
    )
    newer = discovery_candidate(
        "atorvastatin",
        rank=2,
        source_version="2",
        complete_selection_metadata=True,
    )
    first_lookup = live_connector(
        SequenceTransport([response(discovery_body([older, newer]))])
    ).discover("atorvastatin")
    second_lookup = live_connector(
        SequenceTransport([response(discovery_body([newer, older]))])
    ).discover("atorvastatin")
    identity = ingredient_identity(load_utilization_list().entries[0])
    first = classify_and_select_candidates(
        first_lookup, identity, utilization_list_id="us-top10-2023"
    )
    second = classify_and_select_candidates(
        second_lookup, identity, utilization_list_id="us-top10-2023"
    )

    assert first_lookup.snapshot_id != second_lookup.snapshot_id
    assert [item.set_id for item in first.candidates] == [
        item.set_id for item in second.candidates
    ]
    assert first.selection_status is second.selection_status is SelectionStatus.SELECTED
    assert first.selected_set_id == second.selected_set_id == newer["setid"]
    assert first.selection_reason.split(";", 1)[1] == second.selection_reason.split(";", 1)[1]


def test_same_exact_response_ignores_retrieval_timestamp_in_snapshot_identity() -> None:
    body = discovery_body([discovery_candidate("atorvastatin")])
    first = DailyMedConnector(
        base_url=BASE_URL,
        clock=lambda: datetime(2026, 8, 8, tzinfo=UTC),
        inter_request_delay_seconds=0,
        transport=SequenceTransport([response(body)]),
    ).discover("atorvastatin")
    second = DailyMedConnector(
        base_url=BASE_URL,
        clock=lambda: datetime(2027, 1, 1, tzinfo=UTC),
        inter_request_delay_seconds=0,
        transport=SequenceTransport([response(body)]),
    ).discover("atorvastatin")

    assert first.retrieved_at != second.retrieved_at
    assert first.snapshot_id == second.snapshot_id


def test_different_response_bytes_produce_a_different_snapshot_identity() -> None:
    first = live_connector(
        SequenceTransport(
            [response(discovery_body([discovery_candidate("atorvastatin")]))]
        )
    ).discover("atorvastatin")
    second_candidate = discovery_candidate("atorvastatin", source_version="2")
    second = live_connector(
        SequenceTransport([response(discovery_body([second_candidate]))])
    ).discover("atorvastatin")
    assert first.snapshot_id != second.snapshot_id


def test_metadata_total_mismatch_prohibits_automatic_selection() -> None:
    lookup = live_connector(
        SequenceTransport(
            [
                response(
                    discovery_body(
                        [
                            discovery_candidate(
                                "atorvastatin", complete_selection_metadata=True
                            )
                        ],
                        total_elements="2",
                    )
                )
            ]
        )
    ).discover("atorvastatin")
    decision = classify_and_select_candidates(
        lookup,
        ingredient_identity(load_utilization_list().entries[0]),
        utilization_list_id="us-top10-2023",
    )
    assert lookup.completeness is DiscoveryCompleteness.INCOMPLETE
    assert decision.selection_status is SelectionStatus.MANUAL_REVIEW_REQUIRED
    assert decision.selected_set_id is None


def test_duplicate_candidate_across_page_data_is_detected() -> None:
    candidate = discovery_candidate("atorvastatin")
    lookup = live_connector(
        SequenceTransport(
            [response(discovery_body([candidate, candidate], total_elements="2"))]
        )
    ).discover("atorvastatin")
    assert lookup.duplicate_count == 1
    assert lookup.completeness is DiscoveryCompleteness.INCOMPLETE


def test_conflicting_metadata_for_one_set_id_is_detected() -> None:
    first = discovery_candidate("atorvastatin", source_version="1")
    second = {**first, "spl_version": "2"}
    lookup = live_connector(
        SequenceTransport(
            [response(discovery_body([first, second], total_elements="2"))]
        )
    ).discover("atorvastatin")
    assert lookup.metadata_conflict_count == 1
    assert lookup.completeness is DiscoveryCompleteness.INCOMPLETE


@pytest.mark.parametrize("bad_total", [-1, "-1", "NaN", math.inf, 1.5, True])
def test_malformed_nonfinite_or_negative_total_is_rejected(bad_total: object) -> None:
    body = discovery_body(
        [discovery_candidate("atorvastatin")], total_elements=bad_total
    )
    lookup = live_connector(SequenceTransport([response(body)])).discover("atorvastatin")
    assert lookup.completeness is DiscoveryCompleteness.INVALID
    assert lookup.metadata_total_elements is None
    assert lookup.diagnostic_message and "total_elements" in lookup.diagnostic_message


def test_missing_total_metadata_is_rejected_without_guessing() -> None:
    payload = json.loads(discovery_body([discovery_candidate("atorvastatin")]))
    del payload["metadata"]["total_elements"]
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    lookup = live_connector(SequenceTransport([response(body)])).discover("atorvastatin")
    assert lookup.completeness is DiscoveryCompleteness.INVALID
    assert lookup.metadata_total_elements is None


def test_middle_page_failure_preserves_prior_page_and_retry_evidence() -> None:
    first = discovery_candidate("atorvastatin")
    unavailable = response(b"temporarily unavailable", status=503)
    transport = SequenceTransport(
        [
            response(
                discovery_body(
                    [first],
                    elements_per_page="1",
                    total_elements="2",
                    total_pages="2",
                )
            ),
            unavailable,
            unavailable,
            unavailable,
        ]
    )
    lookup = live_connector(transport).discover("atorvastatin")
    assert lookup.completeness is DiscoveryCompleteness.INCOMPLETE
    assert len(lookup.pages) == 1
    assert len(lookup.failure_attempts) == 3
    assert all(attempt.status_code == 503 for attempt in lookup.failure_attempts)


def test_429_respects_retry_after_before_success() -> None:
    sleeps: list[float] = []
    body = discovery_body([discovery_candidate("atorvastatin")])
    transport = SequenceTransport(
        [
            response(b"slow down", status=429, headers={"retry-after": "3"}),
            response(body),
        ]
    )
    lookup = live_connector(transport, sleeps=sleeps).discover("atorvastatin")
    assert lookup.completeness is DiscoveryCompleteness.COMPLETE
    assert sleeps == [3.0]
    assert [attempt.status_code for attempt in lookup.pages[0].attempts] == [429, 200]


def test_429_retry_after_beyond_wait_cap_is_not_shortened_or_retried() -> None:
    sleeps: list[float] = []
    transport = SequenceTransport(
        [response(b"slow down", status=429, headers={"retry-after": "60"})]
    )
    lookup = live_connector(transport, sleeps=sleeps).discover("atorvastatin")
    assert lookup.completeness is DiscoveryCompleteness.INCOMPLETE
    assert len(transport.requests) == 1
    assert sleeps == []
    assert lookup.failure_attempts[0].retry_after_seconds == 60
    assert "wait cap" in (lookup.failure_attempts[0].diagnostic_message or "")


def test_transient_5xx_stops_at_bounded_retry_limit() -> None:
    failure = response(b"unavailable", status=503)
    transport = SequenceTransport([failure, failure, failure])
    lookup = live_connector(transport).discover("atorvastatin")
    assert len(transport.requests) == 3
    assert len(lookup.failure_attempts) == 3
    assert lookup.completeness is DiscoveryCompleteness.INCOMPLETE


def test_permanent_4xx_is_not_retried() -> None:
    transport = SequenceTransport([response(b"not found", status=404)])
    lookup = live_connector(transport).discover("atorvastatin")
    assert len(transport.requests) == 1
    assert len(lookup.failure_attempts) == 1
    assert lookup.failure_attempts[0].retry_eligible is False


def test_content_type_mismatch_is_a_recorded_incomplete_discovery() -> None:
    transport = SequenceTransport(
        [response(b"<html/>", content_type="text/html")]
    )
    lookup = live_connector(transport).discover("atorvastatin")
    assert lookup.completeness is DiscoveryCompleteness.INCOMPLETE
    assert len(lookup.failure_attempts) == 1
    assert "Content-Type" in (lookup.failure_attempts[0].diagnostic_message or "")


def test_oversized_response_is_rejected_before_json_decoding() -> None:
    body = b" " * (MAX_JSON_RESPONSE_BYTES + 1)
    lookup = live_connector(
        SequenceTransport([response(body)])
    ).discover("atorvastatin")
    assert lookup.completeness is DiscoveryCompleteness.INCOMPLETE
    assert "byte limit" in (lookup.diagnostic_message or "")


def test_off_origin_redirect_is_rejected() -> None:
    body = discovery_body([discovery_candidate("atorvastatin")])
    lookup = live_connector(
        SequenceTransport([response(body, url="https://example.invalid/spls.json")])
    ).discover("atorvastatin")
    assert lookup.completeness is DiscoveryCompleteness.INCOMPLETE
    assert "redirected outside" in (lookup.diagnostic_message or "")


def test_default_transport_blocks_off_origin_redirect_before_following() -> None:
    handler = _SameOriginRedirectHandler()

    with pytest.raises(NetworkFailure, match="redirected outside") as raised:
        handler.redirect_request(
            Request(f"{BASE_URL}/spls.json"),
            BytesIO(),
            302,
            "Found",
            HTTPMessage(),
            "https://example.invalid/dailymed/services/v2/spls.json",
        )

    assert raised.value.details["transient"] is False


def test_live_connector_rejects_non_https_base_url() -> None:
    with pytest.raises(ValueError, match="HTTPS origin"):
        DailyMedConnector(
            base_url="http://dailymed.example/services/v2",
            transport=SequenceTransport([]),
        )


def test_declared_xml_with_non_xml_bytes_is_rejected() -> None:
    candidate = discovery_candidate("atorvastatin")
    lookup = live_connector(
        SequenceTransport([response(discovery_body([candidate]))])
    ).discover("atorvastatin")
    transport = SequenceTransport(
        [response(b'{"not":"xml"}', content_type="application/xml")]
    )
    connector = live_connector(transport)
    with pytest.raises(NetworkFailure, match="not an XML representation"):
        connector.download(lookup.candidates[0])

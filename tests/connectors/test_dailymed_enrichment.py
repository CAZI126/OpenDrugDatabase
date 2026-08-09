"""Offline HTTP-contract tests for ODD-005 DailyMed detail evidence."""

from __future__ import annotations

import json
from collections.abc import Mapping

import pytest

from odd.connectors.dailymed.client import (
    DailyMedConnector,
    HTTPResponse,
    MalformedDetailResponse,
)
from odd.errors import MalformedMetadata, NetworkFailure
from odd.models import DailyMedCandidate
from tests.odd004_support import SequenceTransport, response
from tests.odd_support import FixedClock

BASE_URL = "https://dailymed.example/services/v2"
SET_ID = "00000000-0000-4000-8000-000000000001"


def test_packaging_detail_preserves_exact_bytes_http_evidence_and_locator() -> None:
    body = _packaging_body()
    transport = SequenceTransport(
        [
            response(
                body,
                url=f"{BASE_URL}/spls/{SET_ID}/packaging.json?page=1&pagesize=100",
                headers={"etag": '"detail-etag"', "last-modified": "Sat, 08 Aug 2026 00:00:00 GMT"},
            )
        ]
    )
    page = _connector(transport).packaging_page(
        SET_ID, page_number=1, max_response_bytes=4096
    )
    assert page.raw_body == body
    assert page.set_id == SET_ID
    assert page.observed_source_version == "1"
    assert page.etag == '"detail-etag"'
    assert page.last_modified == "Sat, 08 Aug 2026 00:00:00 GMT"
    assert page.canonical_request[-1] == ("setid", SET_ID)
    assert page.attempts[0].response_size_bytes == len(body)


@pytest.mark.parametrize(
    "payload",
    (
        {},
        {"data": []},
        {"data": {"setid": SET_ID, "spl_version": "1"}},
        {"data": {"setid": SET_ID, "spl_version": True, "products": []}},
    ),
)
def test_packaging_rejects_malformed_identity_or_products(payload: object) -> None:
    body = json.dumps(payload).encode()
    connector = _connector(SequenceTransport([response(body)]))
    with pytest.raises(MalformedMetadata):
        connector.packaging_page(SET_ID, page_number=1)


def test_packaging_retains_a_returned_set_id_mismatch_for_source_drift() -> None:
    different = "00000000-0000-4000-8000-000000000002"
    body = json.dumps(
        {
            "data": {
                "setid": different,
                "spl_version": "1",
                "title": "ATORVASTATIN detail",
                "published_date": "Aug 08, 2026",
                "products": [],
            }
        }
    ).encode()
    page = _connector(SequenceTransport([response(body)])).packaging_page(
        SET_ID, page_number=1
    )
    assert page.set_id == different
    assert page.raw_body == body


def test_packaging_parse_failure_exposes_exact_valid_http_response() -> None:
    body = b'{"data":'
    connector = _connector(SequenceTransport([response(body)]))
    with pytest.raises(MalformedDetailResponse) as raised:
        connector.packaging_page(SET_ID, page_number=1)
    assert raised.value.response.body == body
    assert raised.value.response.status_code == 200


def test_packaging_rejects_content_type_mismatch() -> None:
    connector = _connector(
        SequenceTransport(
            [response(_packaging_body(), content_type="text/html")]
        )
    )
    with pytest.raises(NetworkFailure, match="Content-Type"):
        connector.packaging_page(SET_ID, page_number=1)


def test_packaging_rejects_oversized_response() -> None:
    connector = _connector(SequenceTransport([response(_packaging_body())]))
    with pytest.raises(NetworkFailure, match="byte limit") as raised:
        connector.packaging_page(SET_ID, page_number=1, max_response_bytes=8)
    attempts = raised.value.details["attempts"]
    assert attempts[0]["response_size_bytes"] == len(_packaging_body())


def test_packaging_429_honors_retry_after_with_bounded_retry() -> None:
    sleeps: list[float] = []
    transport = SequenceTransport(
        [
            response(
                b"slow down",
                status=429,
                content_type="text/plain",
                headers={"retry-after": "2"},
            ),
            response(_packaging_body()),
        ]
    )
    connector = _connector(transport, sleeps=sleeps, max_retries=1)
    page = connector.packaging_page(SET_ID, page_number=1)
    assert len(page.attempts) == 2
    assert page.attempts[0].status_code == 429
    assert page.attempts[0].retry_after_seconds == 2
    assert sleeps == [2.0]


def test_packaging_transient_5xx_stops_at_retry_cap() -> None:
    transport = SequenceTransport(
        [
            response(b"one", status=503, content_type="text/plain"),
            response(b"two", status=503, content_type="text/plain"),
        ]
    )
    connector = _connector(transport, max_retries=1)
    with pytest.raises(NetworkFailure) as raised:
        connector.packaging_page(SET_ID, page_number=1)
    assert len(transport.requests) == 2
    assert len(raised.value.details["attempts"]) == 2


def test_packaging_permanent_4xx_is_not_retried() -> None:
    transport = SequenceTransport(
        [response(b"missing", status=404, content_type="text/plain")]
    )
    connector = _connector(transport, max_retries=2)
    with pytest.raises(NetworkFailure) as raised:
        connector.packaging_page(SET_ID, page_number=1)
    assert len(transport.requests) == 1
    assert raised.value.details["transient"] is False


def test_packaging_rejects_off_origin_final_url() -> None:
    transport = SequenceTransport(
        [response(_packaging_body(), url="https://evil.example/packaging.json")]
    )
    connector = _connector(transport)
    with pytest.raises(NetworkFailure, match="outside"):
        connector.packaging_page(SET_ID, page_number=1)


def test_spl_download_uses_neutral_accept_and_still_requires_xml() -> None:
    class HeaderTransport:
        def __init__(self) -> None:
            self.headers: Mapping[str, str] = {}

        def get(
            self,
            url: str,
            *,
            headers: Mapping[str, str],
            timeout: float,
            max_bytes: int,
        ) -> HTTPResponse:
            del timeout, max_bytes
            self.headers = dict(headers)
            return response(
                b"<?xml version='1.0'?><document/>",
                content_type="application/xml",
                url=url,
            )

    transport = HeaderTransport()
    downloaded = DailyMedConnector(
        base_url=BASE_URL,
        clock=FixedClock(),
        transport=transport,
    ).download(
        DailyMedCandidate(
            set_id=SET_ID,
            source_version="1",
            title="synthetic",
            published_date="Aug 08, 2026",
            metadata={},
        )
    )
    assert transport.headers["Accept"] == "*/*"
    assert downloaded.headers["content-type"] == "application/xml"


def _connector(
    transport: SequenceTransport,
    *,
    sleeps: list[float] | None = None,
    max_retries: int = 0,
) -> DailyMedConnector:
    delays = sleeps if sleeps is not None else []
    return DailyMedConnector(
        base_url=BASE_URL,
        clock=FixedClock(),
        max_retries=max_retries,
        retry_backoff_seconds=1,
        sleep=delays.append,
        transport=transport,
    )


def _packaging_body() -> bytes:
    return json.dumps(
        {
            "data": {
                "products": [
                    {
                        "active_ingredients": [
                            {"name": "atorvastatin", "strength": "10 mg"}
                        ],
                        "product_code": "00000-001",
                    }
                ],
                "published_date": "Aug 08, 2026",
                "setid": SET_ID,
                "spl_version": "1",
                "title": "ATORVASTATIN synthetic detail",
            },
            "metadata": {"current_url": f"{BASE_URL}/spls/{SET_ID}/packaging.json"},
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()

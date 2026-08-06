"""Shared offline ODD-001 test helpers."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from odd.connectors.dailymed.client import DailyMedConnector, HTTPResponse
from odd.service import ODDService, create_service

FIXTURE_DIRECTORY = Path(__file__).parent / "fixtures" / "dailymed"
ELIQUIS_XML = FIXTURE_DIRECTORY / "apixaban_eliquis_v30.xml"
APIXABAN_SEARCH = FIXTURE_DIRECTORY / "apixaban_search.json"
SET_ID = "e9481622-7cc6-418a-acb6-c5450daae9b0"
SOURCE_VERSION = "30"
BASE_URL = "https://dailymed.example/services/v2"
NOW = datetime(2025, 4, 18, 12, 0, tzinfo=UTC)


class FixedClock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


class FixtureTransport:
    def __init__(
        self,
        *,
        search_body: bytes | None = None,
        xml_body: bytes | None = None,
        status_code: int = 200,
        error: Exception | None = None,
    ) -> None:
        self.search_body = search_body if search_body is not None else APIXABAN_SEARCH.read_bytes()
        self.xml_body = xml_body if xml_body is not None else ELIQUIS_XML.read_bytes()
        self.status_code = status_code
        self.error = error
        self.requests: list[tuple[str, dict[str, str], float]] = []

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
    ) -> HTTPResponse:
        self.requests.append((url, dict(headers), timeout))
        if self.error is not None:
            raise self.error
        body = self.search_body if "/spls.json?" in url else self.xml_body
        media_type = "application/json" if "/spls.json?" in url else "application/xml"
        return HTTPResponse(
            status_code=self.status_code,
            url=url,
            body=body,
            headers={"content-length": str(len(body)), "content-type": media_type},
        )


def connector(
    *,
    search_body: bytes | None = None,
    xml_body: bytes | None = None,
    status_code: int = 200,
    error: Exception | None = None,
    clock: FixedClock | None = None,
) -> tuple[DailyMedConnector, FixtureTransport]:
    transport = FixtureTransport(
        search_body=search_body,
        xml_body=xml_body,
        status_code=status_code,
        error=error,
    )
    return (
        DailyMedConnector(
            base_url=BASE_URL,
            timeout_seconds=7,
            user_agent="ODD-test/1",
            transport=transport,
            clock=clock or FixedClock(),
        ),
        transport,
    )


def service(tmp_path: Path, *, xml_body: bytes | None = None) -> ODDService:
    dailymed, _transport = connector(xml_body=xml_body)
    return create_service(
        data_root=tmp_path / "data",
        database_path=tmp_path / "odd.sqlite3",
        connector=dailymed,
        clock=FixedClock(),
    )


def fetched_service(tmp_path: Path, *, xml_body: bytes | None = None) -> ODDService:
    application = service(tmp_path, xml_body=xml_body)
    application.fetch("apixaban")
    return application

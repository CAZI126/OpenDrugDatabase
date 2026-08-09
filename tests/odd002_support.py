"""Offline genuine-source helpers for ODD-002 tests."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from odd.connectors.dailymed.client import DailyMedConnector, HTTPResponse
from odd.service import ODDService, create_service

FIXTURE_DIRECTORY = Path(__file__).parent / "fixtures" / "dailymed"
HISTORY_DIRECTORY = FIXTURE_DIRECTORY / "history"
ELIQUIS_V29_XML = HISTORY_DIRECTORY / "apixaban_eliquis_v29.xml"
ELIQUIS_V30_XML = HISTORY_DIRECTORY / "apixaban_eliquis_v30.xml"
ELIQUIS_HISTORY = HISTORY_DIRECTORY / "eliquis_history.json"
APIXABAN_SEARCH = FIXTURE_DIRECTORY / "apixaban_search.json"
SET_ID = "e9481622-7cc6-418a-acb6-c5450daae9b0"
V29_SHA256 = "ac5703e97b6c5f095ed319cdfd87d36b80a5cef0e0946251eae5587e4ceb8716"
V30_SHA256 = "d6549bce376b88394da0a802a479a7bea699a48f6da3ae0be087f927e101e1aa"
V29_DOCUMENT_ID = "dfa2c522-601e-5e44-a66f-f27ab455152b"
V30_DOCUMENT_ID = "1ec0a382-ce54-52a1-97ac-00b0558556ba"
BASE_URL = "https://dailymed.example/dailymed/services/v2"
ARCHIVE_BASE_URL = "https://dailymed.example/dailymed"
NOW = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)


class FixedClock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


class TemporalFixtureTransport:
    def __init__(self) -> None:
        self.history_body = ELIQUIS_HISTORY.read_bytes()
        self.search_body = APIXABAN_SEARCH.read_bytes()
        self.v29_body = ELIQUIS_V29_XML.read_bytes()
        self.v30_body = ELIQUIS_V30_XML.read_bytes()
        self.archive_body = historical_zip(self.v29_body)
        self.requests: list[str] = []

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
        max_bytes: int,
    ) -> HTTPResponse:
        del headers, timeout, max_bytes
        self.requests.append(url)
        if url.endswith("/history.json"):
            body = self.history_body
            media_type = "application/json"
        elif "/getFile.cfm?" in url:
            body = self.archive_body
            media_type = "application/zip"
        elif "/spls.json?" in url:
            body = self.search_body
            media_type = "application/json"
        else:
            body = self.v30_body
            media_type = "application/xml"
        return HTTPResponse(
            status_code=200,
            url=url,
            body=body,
            headers={"content-length": str(len(body)), "content-type": media_type},
        )


def historical_zip(xml_bytes: bytes, *, member_name: str = "v29-source.xml") -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        member = ZipInfo(member_name, date_time=(2023, 1, 30, 6, 17, 0))
        member.compress_type = ZIP_DEFLATED
        member.external_attr = 0o100644 << 16
        archive.writestr(member, xml_bytes)
    return output.getvalue()


def temporal_connector() -> tuple[DailyMedConnector, TemporalFixtureTransport]:
    transport = TemporalFixtureTransport()
    connector = DailyMedConnector(
        base_url=BASE_URL,
        archive_base_url=ARCHIVE_BASE_URL,
        timeout_seconds=7,
        user_agent="ODD-002-test/1",
        transport=transport,
        clock=FixedClock(),
    )
    return connector, transport


def temporal_service(tmp_path: Path) -> tuple[ODDService, str, str]:
    connector, _transport = temporal_connector()
    application = create_service(
        data_root=tmp_path / "data",
        database_path=tmp_path / "odd.sqlite3",
        connector=connector,
        clock=FixedClock(),
    )
    application.fetch("apixaban", "29")
    old = application.ingest(SET_ID, "29")
    application.fetch("apixaban")
    new = application.ingest(SET_ID, "30")
    return application, old.document_id, new.document_id

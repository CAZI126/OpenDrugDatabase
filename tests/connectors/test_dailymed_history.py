from __future__ import annotations

import json
from io import BytesIO
from zipfile import ZipFile

import pytest

from odd.errors import MalformedArchive, MalformedMetadata, SourceNotFound
from tests.odd002_support import (
    ELIQUIS_HISTORY,
    ELIQUIS_V29_XML,
    SET_ID,
    TemporalFixtureTransport,
    historical_zip,
    temporal_connector,
)


def test_history_lookup_preserves_exact_official_response() -> None:
    connector, transport = temporal_connector()
    history = connector.history(SET_ID)

    assert history.raw_body == ELIQUIS_HISTORY.read_bytes()
    assert history.source_document_id == SET_ID
    assert len(history.entries) == 28
    assert history.entries[0].source_version == "30"
    assert history.entries[1].source_version == "29"
    assert history.entries[1].published_date is not None
    assert history.entries[1].published_date.isoformat() == "2023-01-30"
    assert transport.requests[-1].endswith(f"/spls/{SET_ID}/history.json")


def test_historical_archive_retrieval_preserves_zip_and_exact_xml_member() -> None:
    connector, transport = temporal_connector()
    history = connector.history(SET_ID)
    download = connector.download_version(history, "29")

    assert download.body == ELIQUIS_V29_XML.read_bytes()
    assert download.container_body == transport.archive_body
    assert download.container_format == "zip"
    assert download.container_member == "v29-source.xml"
    assert "type=zip" in transport.requests[-1]
    assert f"setid={SET_ID}" in transport.requests[-1]
    assert "version=29" in transport.requests[-1]


def test_unknown_historical_version_is_explicit() -> None:
    connector, _transport = temporal_connector()
    history = connector.history(SET_ID)

    with pytest.raises(SourceNotFound, match="absent from DailyMed history"):
        connector.download_version(history, "999")


def test_malformed_zip_is_explicit() -> None:
    connector, transport = temporal_connector()
    history = connector.history(SET_ID)
    transport.archive_body = b"not a zip"

    with pytest.raises(MalformedArchive):
        connector.download_version(history, "29")


def test_archive_with_multiple_xml_members_is_rejected() -> None:
    connector, transport = temporal_connector()
    history = connector.history(SET_ID)
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("one.xml", b"<document />")
        archive.writestr("two.xml", b"<document />")
    transport.archive_body = output.getvalue()

    with pytest.raises(MalformedArchive, match="exactly one"):
        connector.download_version(history, "29")


def test_archive_with_unsafe_xml_member_is_rejected() -> None:
    connector, transport = temporal_connector()
    history = connector.history(SET_ID)
    transport.archive_body = historical_zip(b"<document />", member_name="../escape.xml")

    with pytest.raises(MalformedArchive, match="unsafe"):
        connector.download_version(history, "29")


@pytest.mark.parametrize(
    "mutation",
    (
        lambda payload: payload["data"].pop("history"),
        lambda payload: payload["data"]["history"][1].update({"published_date": "2023/01/30"}),
        lambda payload: payload["data"]["history"].append(
            {"spl_version": 29, "published_date": "Jan 30, 2023"}
        ),
    ),
)
def test_malformed_history_metadata_is_explicit(mutation: object) -> None:
    transport = TemporalFixtureTransport()
    payload = json.loads(transport.history_body)
    assert callable(mutation)
    mutation(payload)
    transport.history_body = json.dumps(payload).encode()
    connector, _unused = temporal_connector()
    connector.transport = transport

    with pytest.raises(MalformedMetadata):
        connector.history(SET_ID)

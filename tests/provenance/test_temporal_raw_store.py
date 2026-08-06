from __future__ import annotations

import base64
import json
from pathlib import Path

from odd.provenance.hashing import sha256_bytes
from odd.service import create_service
from tests.odd002_support import (
    ELIQUIS_HISTORY,
    ELIQUIS_V29_XML,
    ELIQUIS_V30_XML,
    SET_ID,
    V29_SHA256,
    V30_SHA256,
    FixedClock,
    temporal_connector,
)


def _service(tmp_path: Path):
    connector, transport = temporal_connector()
    application = create_service(
        data_root=tmp_path / "data",
        database_path=tmp_path / "odd.sqlite3",
        connector=connector,
        clock=FixedClock(),
    )
    return application, transport


def test_historical_raw_store_preserves_exact_xml_zip_and_history_bytes(tmp_path: Path) -> None:
    application, transport = _service(tmp_path)
    result = application.fetch("apixaban", "29")
    directory = tmp_path / "data" / "raw" / "dailymed" / SET_ID / "29"
    manifest = json.loads((directory / "metadata.json").read_bytes())

    assert (directory / "label.xml").read_bytes() == ELIQUIS_V29_XML.read_bytes()
    assert (directory / "source.zip").read_bytes() == transport.archive_body
    assert result["raw_sha256"] == V29_SHA256
    assert manifest["retrieval"]["source_xml_sha256"] == V29_SHA256
    assert manifest["retrieval"]["response_byte_length"] == len(transport.archive_body)
    assert base64.b64decode(manifest["history"]["raw_body_base64"]) == ELIQUIS_HISTORY.read_bytes()
    assert manifest["history"]["raw_sha256"] == sha256_bytes(ELIQUIS_HISTORY.read_bytes())


def test_two_genuine_source_versions_have_independent_immutable_paths(tmp_path: Path) -> None:
    application, _transport = _service(tmp_path)
    application.fetch("apixaban", "29")
    application.fetch("apixaban")
    root = tmp_path / "data" / "raw" / "dailymed" / SET_ID

    assert sha256_bytes((root / "29" / "label.xml").read_bytes()) == V29_SHA256
    assert sha256_bytes((root / "30" / "label.xml").read_bytes()) == V30_SHA256
    assert (root / "29" / "label.xml").read_bytes() == ELIQUIS_V29_XML.read_bytes()
    assert (root / "30" / "label.xml").read_bytes() == ELIQUIS_V30_XML.read_bytes()


def test_identical_historical_fetch_and_history_snapshot_are_idempotent(tmp_path: Path) -> None:
    application, _transport = _service(tmp_path)
    first = application.fetch("apixaban", "29")
    second = application.fetch("apixaban", "29")

    assert first["history_snapshot_id"] == second["history_snapshot_id"]
    assert second["status"] == "already_stored"
    assert application.repository.table_count("lineage_history_snapshots") == 1

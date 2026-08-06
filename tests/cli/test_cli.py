"""CLI retrieval, filtering, and verification tests."""

from __future__ import annotations

import io
import json
from pathlib import Path

from odd.cli.main import run_cli
from odd.service import create_service
from tests.odd_support import SET_ID, FixedClock, connector, fetched_service, service


def invoke(application, *arguments: str):
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = run_cli(arguments, service=application, stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


def ingested(tmp_path: Path):
    application = fetched_service(tmp_path)
    outcome = application.ingest(SET_ID)
    return application, outcome


def test_fetch_displays_candidates_rule_and_selected_identity(tmp_path: Path) -> None:
    application = service(tmp_path)
    code, stdout, stderr = invoke(application, "fetch", "--drug", "apixaban")
    payload = json.loads(stdout)
    assert code == 0
    assert stderr == ""
    assert payload["candidate_count"] == 2
    assert payload["ambiguity_exposed"] is True
    assert payload["selected_set_id"] == SET_ID
    assert payload["selection_rule_version"]


def test_ingest_command_reports_explicit_counts(tmp_path: Path) -> None:
    application = fetched_service(tmp_path)
    code, stdout, _stderr = invoke(application, "ingest", "--set-id", SET_ID)
    payload = json.loads(stdout)
    assert code == 0
    assert payload["status"] == "ingested"
    assert payload["source_section_count"] == 21
    assert payload["mapped_section_count"] == 19
    assert payload["unmapped_section_count"] == 2


def test_search_output_contains_required_fields(tmp_path: Path) -> None:
    application, outcome = ingested(tmp_path)
    code, stdout, _stderr = invoke(application, "search", "apixaban")
    payload = json.loads(stdout)
    assert code == 0
    assert payload["count"] == 1
    item = payload["documents"][0]
    assert item["document_id"] == outcome.document_id
    assert item["generic_name"] == "apixaban"
    assert item["brand_name"] == "ELIQUIS"
    assert item["source_document_id"] == SET_ID


def test_show_output_contains_provenance_and_source_text(tmp_path: Path) -> None:
    application, outcome = ingested(tmp_path)
    code, stdout, _stderr = invoke(
        application, "show", "--document", outcome.document_id
    )
    payload = json.loads(stdout)
    assert code == 0
    assert payload["document"]["raw_sha256"] == outcome.raw_sha256
    assert payload["document"]["parser_version"]
    assert payload["document"]["schema_version"]
    assert payload["sections"][8]["original_heading"] == "7 DRUG INTERACTIONS"
    assert "Rifampin" in payload["sections"][8]["original_text"]


def test_show_section_filter_uses_normalized_concept(tmp_path: Path) -> None:
    application, outcome = ingested(tmp_path)
    code, stdout, _stderr = invoke(
        application,
        "show",
        "--document",
        outcome.document_id,
        "--section",
        "drug_interactions",
    )
    payload = json.loads(stdout)
    assert code == 0
    assert payload["section_filter"] == "drug_interactions"
    assert len(payload["sections"]) == 1
    assert payload["sections"][0]["source_section_code"] == "34073-7"


def test_verify_success_returns_zero(tmp_path: Path) -> None:
    application, outcome = ingested(tmp_path)
    code, stdout, stderr = invoke(
        application, "verify", "--document", outcome.document_id
    )
    payload = json.loads(stdout)
    assert code == 0
    assert stderr == ""
    assert payload["ok"] is True
    assert all(item["ok"] for item in payload["checks"])


def test_verify_failure_returns_nonzero(tmp_path: Path) -> None:
    application, outcome = ingested(tmp_path)
    raw = application.raw_store.resolve(SET_ID)
    raw.label_path.write_bytes(b"tampered after ingestion")
    code, stdout, _stderr = invoke(
        application, "verify", "--document", outcome.document_id
    )
    payload = json.loads(stdout)
    assert code == 1
    assert payload["ok"] is False
    raw_check = next(item for item in payload["checks"] if item["name"] == "raw_sha256")
    assert raw_check["ok"] is False


def test_ingest_parser_failure_returns_nonzero_and_category(tmp_path: Path) -> None:
    application = service(tmp_path, xml_body=b"<broken>")
    application.fetch("apixaban")
    code, stdout, stderr = invoke(application, "ingest", "--set-id", SET_ID)
    assert code == 1
    assert stdout == ""
    assert json.loads(stderr)["error"]["category"] == "malformed_xml"


def test_ambiguous_fetch_returns_nonzero_and_exposes_candidates(tmp_path: Path) -> None:
    search = b"""{
      "metadata": {"total_elements": "2"},
      "data": [
        {
          "spl_version": "1", "published_date": "Apr 17, 2025",
          "setid": "set-a", "title": "ELIQUIS- apixaban tablet"
        },
        {
          "spl_version": "2", "published_date": "Apr 18, 2025",
          "setid": "set-b", "title": "ELIQUIS- apixaban tablet"
        }
      ]
    }"""
    dailymed, _transport = connector(search_body=search)
    application = create_service(
        data_root=tmp_path / "data",
        database_path=tmp_path / "odd.sqlite3",
        connector=dailymed,
        clock=FixedClock(),
    )
    code, stdout, stderr = invoke(application, "fetch", "--drug", "apixaban")
    payload = json.loads(stderr)
    assert code == 2
    assert stdout == ""
    assert payload["error"]["category"] == "ambiguous_source_selection"
    assert len(payload["error"]["details"]["candidates"]) == 2

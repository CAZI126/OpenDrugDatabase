"""Offline tests for the MCP tool surface over the preserved Eliquis document.

Everything here runs from the committed fixture. No network, no live archive.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from odd.core.direct import fetch_by_set_id
from odd.core.evidence import UNKNOWN
from odd.mcp.tools import OddTools, ToolError
from tests.core.test_core_pipeline import ELIQUIS_SET_ID, ELIQUIS_VERSION, pipeline
from tests.core.test_drugsfda import (
    archive_bytes,
    install_fixture_archive,
    preserve_fixture_archive,
    spl_with_application,
)

INDICATIONS = "34067-9"
ABSENT_CODE = "00000-0"
APPLICATION = "NDA202155"


def tools(tmp_path: Path, *, with_application: bool = False) -> OddTools:
    core = pipeline(
        tmp_path, xml_body=spl_with_application() if with_application else None
    )
    core.acquire("Eliquis", set_id=ELIQUIS_SET_ID)
    return OddTools(core)


# -- 1. finding documents ---------------------------------------------------
def test_a_matching_name_returns_the_preserved_document_with_its_provenance(
    tmp_path: Path,
) -> None:
    result = tools(tmp_path).find_documents("apixaban")

    assert result["candidate_count"] == 1
    found = result["candidates"][0]
    assert found["set_id"] == ELIQUIS_SET_ID
    assert found["source_version"] == ELIQUIS_VERSION
    assert found["raw_sha256"]
    assert found["source_url"].endswith(f"/spls/{ELIQUIS_SET_ID}.xml")
    assert found["label_repository"] == "DailyMed"
    assert found["jurisdiction"] == "United States"
    assert found["effective_date"] != UNKNOWN


def test_the_finder_never_chooses_between_matching_documents(tmp_path: Path) -> None:
    """Two preserved documents matching one name must both come back."""

    second_set_id = "aaaaaaaa-0000-4000-8000-00000000000a"
    core = pipeline(tmp_path)
    core.acquire("Eliquis", set_id=ELIQUIS_SET_ID)
    # A second preserved document stating the same ingredient under its own
    # identity, retrieved by that identity alone so no listing is involved.
    other = spl_with_application().replace(ELIQUIS_SET_ID.encode(), second_set_id.encode())
    twin = pipeline(tmp_path, xml_body=other)
    fetch_by_set_id(twin.connector, twin.raw_store, second_set_id)

    result = OddTools(core).find_documents("apixaban")

    assert result["candidate_count"] == 2
    assert result["selection_performed"] is False
    assert len({item["set_id"] for item in result["candidates"]}) == 2


def test_a_name_no_preserved_document_states_returns_no_candidates(tmp_path: Path) -> None:
    result = tools(tmp_path).find_documents("a drug no preserved label mentions")

    assert result["candidate_count"] == 0
    assert result["candidates"] == []


def test_a_blank_query_is_a_structured_error(tmp_path: Path) -> None:
    with pytest.raises(ToolError) as caught:
        tools(tmp_path).find_documents("   ")

    assert caught.value.as_dict()["error"]["code"] == "BLANK_QUERY"


# -- 2. section index -------------------------------------------------------
def test_the_index_lists_every_section_and_carries_no_text(tmp_path: Path) -> None:
    surface = tools(tmp_path)

    index = surface.get_section_index(ELIQUIS_SET_ID)

    assert index["section_count"] > 0
    assert index["carries_section_text"] is False
    for entry in index["sections"]:
        assert "text" not in entry
        assert entry["evidence_locator"] and entry["section_sha256"] and entry["text_sha256"]
    rendered = json.dumps(index)
    assert "ELIQUIS is indicated" not in rendered


def test_the_index_states_the_subsection_relationship(tmp_path: Path) -> None:
    index = tools(tmp_path).get_section_index(ELIQUIS_SET_ID)

    nested = [e for e in index["sections"] if e["depth"] > 0]
    assert nested, "the fixture must carry at least one subsection"
    assert all(e["parent_sequence_index"] is not None for e in nested)
    assert all(
        e["parent_sequence_index"] is None for e in index["sections"] if e["depth"] == 0
    )


def test_an_identity_that_is_not_preserved_is_a_structured_error(tmp_path: Path) -> None:
    with pytest.raises(ToolError) as caught:
        tools(tmp_path).get_section_index("00000000-0000-4000-8000-000000000000")

    assert caught.value.as_dict()["error"]["code"] == "NOT_PRESERVED"


# -- 3. evidence slice ------------------------------------------------------
def code_present(surface: OddTools) -> str:
    index = surface.get_section_index(ELIQUIS_SET_ID)
    return next(
        e["section_code"] for e in index["sections"] if e["content_status"] == "present"
    )


def test_a_slice_returns_only_the_codes_that_were_named(tmp_path: Path) -> None:
    surface = tools(tmp_path)
    wanted = code_present(surface)

    result = surface.get_evidence_slice(ELIQUIS_SET_ID, [wanted])

    assert result["returned_section_codes"] == [wanted]
    assert result["unexpected_section_codes"] == []
    assert result["subsections_added_implicitly"] is False
    for section in result["sections"]:
        assert section["text"]
        assert section["evidence"]["xml_locator"]
        assert section["evidence"]["section_sha256"]
        assert section["evidence"]["raw_sha256"]


def test_two_named_codes_return_those_two_and_nothing_else(tmp_path: Path) -> None:
    surface = tools(tmp_path)
    index = surface.get_section_index(ELIQUIS_SET_ID)
    present = [e["section_code"] for e in index["sections"] if e["content_status"] == "present"]
    first, second = present[0], next(c for c in present if c != present[0])

    result = surface.get_evidence_slice(ELIQUIS_SET_ID, [first, second])

    assert set(result["returned_section_codes"]) == {first, second}
    assert result["unexpected_section_codes"] == []


def test_a_code_the_document_does_not_state_is_reported_not_invented(
    tmp_path: Path,
) -> None:
    surface = tools(tmp_path)
    wanted = code_present(surface)

    result = surface.get_evidence_slice(ELIQUIS_SET_ID, [wanted, ABSENT_CODE])

    assert result["section_codes_not_found"] == [ABSENT_CODE]
    assert ABSENT_CODE not in result["returned_section_codes"]
    assert len(result["sections"]) == 1


def test_a_slice_carries_source_url_version_and_effective_date(tmp_path: Path) -> None:
    surface = tools(tmp_path)

    result = surface.get_evidence_slice(ELIQUIS_SET_ID, [code_present(surface)])

    document = result["document"]
    assert document["source_url"].endswith(f"/spls/{ELIQUIS_SET_ID}.xml")
    assert document["source_version"] == ELIQUIS_VERSION
    assert document["effective_date"] != UNKNOWN
    assert document["raw_sha256"]
    assert document["label_publisher"] == "National Library of Medicine"


def test_naming_no_section_code_is_a_structured_error(tmp_path: Path) -> None:
    with pytest.raises(ToolError) as caught:
        tools(tmp_path).get_evidence_slice(ELIQUIS_SET_ID, [])

    assert caught.value.as_dict()["error"]["code"] == "NO_SECTION_CODES"


def test_not_asking_drugs_fda_is_not_the_same_as_finding_nothing(tmp_path: Path) -> None:
    surface = tools(tmp_path)

    result = surface.get_evidence_slice(ELIQUIS_SET_ID, [code_present(surface)])

    assert result["drugs_fda"]["status"] == "UNKNOWN"
    assert result["drugs_fda"]["sources"] == []


# -- Drugs@FDA, exact identity only ----------------------------------------
def test_the_named_application_number_links_by_exact_identity(tmp_path: Path) -> None:
    surface = tools(tmp_path, with_application=True)
    preserve_fixture_archive(surface.pipeline, archive_bytes())

    result = surface.get_evidence_slice(
        ELIQUIS_SET_ID, [code_present(surface)], APPLICATION
    )

    fda = result["drugs_fda"]
    assert fda["requested_application_number"] == APPLICATION
    assert fda["status"] == "EXACT"
    assert [s["application_number"] for s in fda["sources"]] == [APPLICATION]
    rows = fda["sources"][0]["link"]["fda_evidence"]["rows"]
    assert rows and all(r["row_sha256"] and r["zip_member"] and r["row_number"] for r in rows)


def test_an_application_number_that_is_not_an_exact_match_returns_nothing(
    tmp_path: Path,
) -> None:
    """A prefix of the real number must not connect to it."""

    surface = tools(tmp_path, with_application=True)
    preserve_fixture_archive(surface.pipeline, archive_bytes())

    for requested in ("202155", "NDA2021", "NDA999999"):
        result = surface.get_evidence_slice(
            ELIQUIS_SET_ID, [code_present(surface)], requested
        )
        assert result["drugs_fda"]["sources"] == [], requested
        assert result["drugs_fda"]["status"] == "NOT_FOUND", requested


# -- 4. verification --------------------------------------------------------
def test_verification_rehashes_the_preserved_source(tmp_path: Path) -> None:
    surface = tools(tmp_path)

    result = surface.verify_document(ELIQUIS_SET_ID)

    assert result["result"] == "VERIFIED"
    assert result["raw_bytes_sha256"]["observed"] == "VERIFIED"
    assert result["section_anchors"]["observed"] == "VERIFIED"
    assert result["source_version_consistency"]["document_identity"]["observed"] == "VERIFIED"
    assert result["failure_reasons"] == []
    assert result["document"]["raw_sha256"] in result["raw_bytes_sha256"]["message"]


def test_verification_fails_when_the_preserved_bytes_change(tmp_path: Path) -> None:
    surface = tools(tmp_path)
    surface.verify_document(ELIQUIS_SET_ID)
    raw = surface.pipeline.raw_store.resolve(ELIQUIS_SET_ID, ELIQUIS_VERSION)
    raw.label_path.write_bytes(raw.label_path.read_bytes() + b"<!-- tampered -->")

    result = surface.verify_document(ELIQUIS_SET_ID)

    assert result["result"] == "FAILED"
    assert result["failure_reasons"]


def test_verification_reports_drugs_fda_linkage_when_the_bundle_carries_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fixture_archive(monkeypatch, archive_bytes())
    surface = tools(tmp_path, with_application=True)
    surface.pipeline.extract(ELIQUIS_SET_ID, ELIQUIS_VERSION, include_drugsfda=True)

    result = surface.verify_document(ELIQUIS_SET_ID)

    linkage = result["drugs_fda_linkage"]
    assert result["result"] == "VERIFIED"
    assert linkage["archive_sha256"]["observed"] == "VERIFIED"
    assert linkage["row_evidence"]["observed"] == "VERIFIED"
    assert linkage["link_status"]["observed"] == "VERIFIED"


# -- determinism ------------------------------------------------------------
def test_repeating_a_call_returns_the_same_answer(tmp_path: Path) -> None:
    surface = tools(tmp_path)
    wanted = code_present(surface)

    assert surface.find_documents("apixaban") == surface.find_documents("apixaban")
    assert surface.get_section_index(ELIQUIS_SET_ID) == surface.get_section_index(ELIQUIS_SET_ID)
    assert surface.get_evidence_slice(ELIQUIS_SET_ID, [wanted]) == surface.get_evidence_slice(
        ELIQUIS_SET_ID, [wanted]
    )


def test_the_mcp_layer_adds_no_drug_specific_branch() -> None:
    import odd.mcp.server
    import odd.mcp.tools

    for module in (odd.mcp.tools, odd.mcp.server):
        source = Path(module.__file__).read_text(encoding="utf-8").casefold()
        for name in ("eliquis", "apixaban", "e9481622", "202155", "bristol"):
            assert name not in source, f"{module.__name__} hardcodes {name}"

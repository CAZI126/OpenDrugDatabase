"""Offline tests for index-first, exact-match evidence delivery."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from odd.core.selective import CORE_INDEX_SCHEMA_VERSION, CORE_SLICE_SCHEMA_VERSION
from tests.core.test_core_pipeline import ELIQUIS_SET_ID, ELIQUIS_VERSION, pipeline
from tests.core.test_drugsfda import archive_bytes, install_fixture_archive, spl_with_application


def prepared(tmp_path: Path, *, with_application: bool = False):
    core = pipeline(
        tmp_path, xml_body=spl_with_application() if with_application else None
    )
    core.acquire("Eliquis", set_id=ELIQUIS_SET_ID)
    return core


def index_of(core, **kwargs) -> dict:
    return core.extract(ELIQUIS_SET_ID, ELIQUIS_VERSION, index_only=True, **kwargs).payload


def slice_of(core, codes: tuple[str, ...], **kwargs) -> dict:
    return core.extract(
        ELIQUIS_SET_ID, ELIQUIS_VERSION, section_codes=codes, slice_only=True, **kwargs
    ).payload


def test_the_index_carries_no_section_text(tmp_path: Path) -> None:
    payload = index_of(prepared(tmp_path))

    assert payload["schema_version"] == CORE_INDEX_SCHEMA_VERSION
    for entry in payload["sections"]:
        assert "text" not in entry
        assert "original_text" not in entry
    rendered = json.dumps(payload)
    # A section's own words must not reach the index by any route.
    assert "ELIQUIS is indicated" not in rendered


def test_the_index_carries_no_fda_row_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fixture_archive(monkeypatch, archive_bytes())
    core = prepared(tmp_path, with_application=True)

    payload = index_of(core, include_drugsfda=True)

    rendered = json.dumps(payload)
    assert "BRISTOL MYERS SQUIBB" not in rendered
    assert "row_raw_text" not in rendered
    index = payload["regulatory_index"]
    assert index["application_numbers"] == ["NDA202155"]
    assert index["matching_row_counts"]["NDA202155"]["Applications.txt"] == 1
    assert "Applications.txt" in index["available_tables"]


def test_every_section_appears_in_the_index(tmp_path: Path) -> None:
    core = prepared(tmp_path)
    full = core.extract(ELIQUIS_SET_ID, ELIQUIS_VERSION).payload

    payload = index_of(core)

    assert len(payload["sections"]) == len(full["sections"])
    assert payload["completeness"]["section_index"] == "COMPLETE"
    assert [entry["evidence_locator"] for entry in payload["sections"]] == [
        section["evidence"]["xml_locator"] for section in full["sections"]
    ]


def test_a_slice_returns_only_the_codes_that_were_named(tmp_path: Path) -> None:
    core = prepared(tmp_path)
    index = index_of(core)
    wanted = next(
        entry["section_code"]
        for entry in index["sections"]
        if entry["content_status"] == "present" and entry["depth"] > 0
    )

    payload = slice_of(core, (wanted,))

    assert payload["schema_version"] == CORE_SLICE_SCHEMA_VERSION
    assert payload["label_evidence"]
    assert {item["section_code"] for item in payload["label_evidence"]} == {wanted}


def test_a_named_parent_is_not_widened_to_its_subsections(tmp_path: Path) -> None:
    """Exact match means exact: naming a section never pulls in its children."""

    core = prepared(tmp_path)
    index = index_of(core)
    codes = [entry["section_code"] for entry in index["sections"]]
    parent = next(
        entry["section_code"]
        for entry in index["sections"]
        if entry["depth"] == 0 and codes.count(entry["section_code"]) == 1
    )

    payload = slice_of(core, (parent,))

    assert {item["section_code"] for item in payload["label_evidence"]} == {parent}


def test_two_named_codes_return_those_two_and_nothing_else(tmp_path: Path) -> None:
    core = prepared(tmp_path)
    index = index_of(core)
    present = [
        entry["section_code"]
        for entry in index["sections"]
        if entry["content_status"] == "present"
    ]
    first, second = present[0], next(code for code in present if code != present[0])

    payload = slice_of(core, (first, second))

    assert {item["section_code"] for item in payload["label_evidence"]} == {first, second}


def test_a_code_absent_from_a_complete_index_is_not_found(tmp_path: Path) -> None:
    payload = slice_of(prepared(tmp_path), ("00000-0",))

    assert payload["completeness"]["section_index"] == "COMPLETE"
    assert payload["completeness"]["requested_section_codes"]["00000-0"] == "NOT_FOUND"
    assert payload["label_evidence"] == []


def test_regulatory_completeness_is_unknown_when_fda_was_not_retrieved(
    tmp_path: Path,
) -> None:
    """Not asking FDA is not the same as asking FDA and finding nothing."""

    payload = slice_of(prepared(tmp_path), ("00000-0",))

    assert payload["completeness"]["regulatory_index"] == "UNKNOWN"
    assert payload["regulatory_evidence"] == []


def test_only_the_named_application_number_is_returned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fixture_archive(monkeypatch, archive_bytes())
    core = prepared(tmp_path, with_application=True)

    matched = slice_of(
        core, (), include_drugsfda=True, application_numbers=("NDA202155",)
    )
    other = slice_of(
        core, (), include_drugsfda=True, application_numbers=("NDA000001",)
    )

    assert [item["application_number"] for item in matched["regulatory_evidence"]] == [
        "NDA202155"
    ]
    assert matched["completeness"]["requested_application_numbers"] == {
        "NDA202155": "EXACT"
    }
    assert other["regulatory_evidence"] == []


def test_a_slice_verifies_back_to_the_preserved_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fixture_archive(monkeypatch, archive_bytes())
    core = prepared(tmp_path, with_application=True)
    index = index_of(core, include_drugsfda=True)
    wanted = next(
        entry["section_code"]
        for entry in index["sections"]
        if entry["content_status"] == "present"
    )

    payload = slice_of(core, (wanted,), include_drugsfda=True)
    report = core.verify(payload)

    assert report.ok is True
    assert report.failures == ()
    names = {check.name for check in report.checks}
    assert "section_evidence" in names
    assert "regulatory_row_evidence" in names


def test_a_tampered_slice_still_fails_verification(tmp_path: Path) -> None:
    core = prepared(tmp_path)
    index = index_of(core)
    wanted = next(
        entry["section_code"]
        for entry in index["sections"]
        if entry["content_status"] == "present"
    )
    payload = slice_of(core, (wanted,))
    payload["label_evidence"][0]["text"] = "text no preserved source contains"

    report = core.verify(payload)

    assert report.ok is False


def test_an_index_run_reports_indexed_not_a_verification_failure(tmp_path: Path) -> None:
    """Returning no evidence is not the same as returning evidence that failed."""

    core = prepared(tmp_path)

    result = core.run("Eliquis", set_id=ELIQUIS_SET_ID, index_only=True)

    assert result["status"] == "indexed"
    assert result["verification"] is None
    assert result["evidence"]["schema_version"] == CORE_INDEX_SCHEMA_VERSION


def test_the_whole_bundle_path_is_unchanged(tmp_path: Path) -> None:
    """Index and slice are additions; the existing full bundle must be untouched."""

    core = prepared(tmp_path)

    full = core.extract(ELIQUIS_SET_ID, ELIQUIS_VERSION)
    index_of(core)
    slice_of(core, ("00000-0",))
    again = core.extract(ELIQUIS_SET_ID, ELIQUIS_VERSION)

    assert full.payload == again.payload
    assert again.status == "unchanged", "derived artifacts must not disturb the bundle"
    assert full.payload["schema_version"] == "odd-core-evidence/2.0.0"
    assert len(full.payload["sections"]) == len(index_of(core)["sections"])
    assert core.verify(again.payload).ok is True

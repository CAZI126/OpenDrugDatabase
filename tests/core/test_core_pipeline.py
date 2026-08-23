"""Offline tests for the ODD core mainline.

These tests deliberately build their own transport instead of importing
``tests.odd_support``: that helper constructs the full ``ODDService``, and the
point of the core is that it runs without it.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree

import pytest

from odd.connectors.dailymed.client import DailyMedConnector, HTTPResponse
from odd.core.evidence import UNKNOWN
from odd.core.locator import resolve_locator
from odd.core.pipeline import CorePipeline
from odd.errors import NetworkFailure, ProvenanceValidationFailure, SourceNotFound
from odd.models import DiscoveryCompleteness
from odd.parsers.spl.parser import build_locator_map, parse_document_root, read_section_evidence

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "dailymed"
ELIQUIS_XML = FIXTURES / "apixaban_eliquis_v30.xml"
APIXABAN_SEARCH = FIXTURES / "apixaban_search.json"
ELIQUIS_SET_ID = "e9481622-7cc6-418a-acb6-c5450daae9b0"
ELIQUIS_VERSION = "30"
BASE_URL = "https://dailymed.example/services/v2"
NOW = datetime(2026, 8, 23, 9, 0, tzinfo=UTC)


class _Transport:
    def __init__(self, *, xml_body: bytes | None = None) -> None:
        self.search_body = APIXABAN_SEARCH.read_bytes()
        self.xml_body = xml_body if xml_body is not None else ELIQUIS_XML.read_bytes()
        self.search_urls: list[str] = []

    def search_page(self, url: str) -> bytes:
        del url
        return self.search_body

    def get(
        self, url: str, *, headers: Mapping[str, str], timeout: float, max_bytes: int
    ) -> HTTPResponse:
        del headers, timeout, max_bytes
        is_search = "/spls.json?" in url
        if is_search:
            self.search_urls.append(url)
            body = self.search_page(url)
        else:
            body = self.xml_body
        return HTTPResponse(
            status_code=200,
            url=url,
            body=body,
            headers={
                "content-length": str(len(body)),
                "content-type": "application/json" if is_search else "application/xml",
            },
        )


class _PagedTransport(_Transport):
    """Serve a two-page official listing; the wanted set_id is only on page two."""

    PAGE_TWO_SET_ID = "b0000000-0000-4000-8000-00000000000b"

    def search_page(self, url: str) -> bytes:
        page_one = json.loads(APIXABAN_SEARCH.read_bytes())
        first = page_one["data"][0]
        page_two_record = {
            **first,
            "setid": self.PAGE_TWO_SET_ID,
            "spl_version": "7",
            "title": "ATORVASTATIN CALCIUM TABLET [ONLY ON PAGE TWO]",
        }
        metadata = {
            "total_elements": len(page_one["data"]) + 1,
            "total_pages": 2,
            "elements_per_page": len(page_one["data"]),
            "current_page": 2 if "page=2" in url else 1,
        }
        data = [page_two_record] if "page=2" in url else page_one["data"]
        return json.dumps({"data": data, "metadata": metadata}).encode("utf-8")


class _TruncatedTransport(_PagedTransport):
    """Serve page one, then fail page two the way a real outage would."""

    def get(
        self, url: str, *, headers: Mapping[str, str], timeout: float, max_bytes: int
    ) -> HTTPResponse:
        if "page=2" in url:
            self.search_urls.append(url)
            raise NetworkFailure(
                "DailyMed request failed: connection reset",
                details={"url": url},
            )
        return super().get(url, headers=headers, timeout=timeout, max_bytes=max_bytes)


def pipeline(
    tmp_path: Path,
    *,
    xml_body: bytes | None = None,
    transport: _Transport | None = None,
) -> CorePipeline:
    return CorePipeline(
        data_root=tmp_path / "data",
        connector=DailyMedConnector(
            base_url=BASE_URL,
            user_agent="odd-core-test/1",
            transport=transport or _Transport(xml_body=xml_body),
            clock=lambda: NOW,
            inter_request_delay_seconds=0,
        ),
        clock=lambda: NOW,
    )


def test_ambiguous_term_returns_every_candidate_and_chooses_none(tmp_path: Path) -> None:
    result = pipeline(tmp_path).acquire("apixaban")

    assert result.status == "ambiguous"
    assert result.raw is None
    assert {item.set_id for item in result.candidates} == {
        ELIQUIS_SET_ID,
        "4a000000-0000-4000-8000-000000000004",
    }


def test_caller_supplied_identity_is_matched_not_selected(tmp_path: Path) -> None:
    result = pipeline(tmp_path).acquire("apixaban", set_id=ELIQUIS_SET_ID)

    assert result.status == "fetched"
    assert result.raw is not None
    assert result.raw.identity.source_document_id == ELIQUIS_SET_ID
    # Every candidate the official response exposed is still preserved.
    assert len(result.candidates) == 2
    manifest = json.loads(result.raw.metadata_path.read_bytes())
    assert manifest["selection"]["rule_version"] == "odd-core-no-selection/1.0.0"
    assert len(manifest["candidate_metadata"]) == 2


def test_unknown_identity_is_reported_with_the_candidates_that_were_seen(
    tmp_path: Path,
) -> None:
    with pytest.raises(SourceNotFound) as error:
        pipeline(tmp_path).acquire("apixaban", set_id="00000000-0000-4000-8000-000000000000")

    details = error.value.details
    assert len(details["candidates"]) == 2
    # "no match" must never be reported without saying how much was examined.
    assert details["candidates_examined"] == 2
    assert details["listing_completeness"] in {v.value for v in DiscoveryCompleteness}


def test_an_identity_beyond_the_first_listing_page_is_still_found(tmp_path: Path) -> None:
    """The official listing is paginated; reading page one only is not reading it."""

    transport = _PagedTransport()
    core = pipeline(tmp_path, transport=transport)

    result = core.acquire("atorvastatin", set_id=_PagedTransport.PAGE_TWO_SET_ID)

    assert result.status == "fetched"
    assert result.raw is not None
    assert len(result.candidates) == 3, "every page of the official listing must be kept"
    assert sum("page=2" in url for url in transport.search_urls) == 1


def test_a_page_that_could_not_be_read_is_never_reported_as_absence(
    tmp_path: Path,
) -> None:
    """An unread page is a hole in the observed range, not an empty result."""

    core = pipeline(tmp_path, transport=_TruncatedTransport())

    result = core.acquire("atorvastatin", set_id=_PagedTransport.PAGE_TWO_SET_ID)

    assert result.status == "unknown", "an unobserved range must not resolve"
    assert result.raw is None
    assert result.listing_completeness == DiscoveryCompleteness.INCOMPLETE.value
    assert "page 2" in (result.listing_diagnostic or "")
    # The part that was read is still reported, and reported as partial.
    assert result.listing_declared_total == 3
    assert len(result.candidates) == 2


def test_an_ambiguous_term_exposes_candidates_from_every_page(tmp_path: Path) -> None:
    result = pipeline(tmp_path, transport=_PagedTransport()).acquire("atorvastatin")

    assert result.status == "ambiguous"
    assert result.listing_completeness == DiscoveryCompleteness.COMPLETE.value
    assert _PagedTransport.PAGE_TWO_SET_ID in {item.set_id for item in result.candidates}


def test_whole_path_reaches_a_verified_bundle(tmp_path: Path) -> None:
    result = pipeline(tmp_path).run("Eliquis", set_id=ELIQUIS_SET_ID)

    assert result["status"] == "verified"
    assert result["verification"]["ok"] is True
    assert result["verification"]["failures"] == []

    evidence = result["evidence"]
    source = evidence["source"]
    assert evidence["drug"]["requested_term"] == "Eliquis"
    assert source["official_document_id"] == {
        "scheme": "dailymed_set_id",
        "value": ELIQUIS_SET_ID,
    }
    assert source["official_url"].endswith(f"/spls/{ELIQUIS_SET_ID}.xml")
    assert source["retrieved_at"] == "2026-08-23T09:00:00Z"
    assert source["document_version"]["value"] == ELIQUIS_VERSION
    assert len(source["raw_sha256"]) == 64
    assert source["raw_path"].endswith("label.xml")

    section = evidence["sections"][0]
    assert set(section) >= {"section_name", "section_code", "text", "evidence"}
    assert section["evidence"]["xml_locator"].startswith("/document[1]/")
    assert len(section["evidence"]["section_sha256"]) == 64

    # Every check the bundle claims was actually run.
    names = {item["name"] for item in result["verification"]["checks"]}
    assert names == {
        "document_identity",
        "raw_metadata",
        "raw_present",
        "raw_sha256",
        "section_count",
        "section_evidence",
    }


def test_evidence_locator_re_retrieves_the_same_passage_from_raw(tmp_path: Path) -> None:
    core = pipeline(tmp_path)
    result = core.run("Eliquis", set_id=ELIQUIS_SET_ID)
    evidence = result["evidence"]

    raw_bytes = (core.data_root / evidence["source"]["raw_path"]).read_bytes()
    root = parse_document_root(raw_bytes)
    locators = build_locator_map(root)

    for section in evidence["sections"]:
        element = resolve_locator(root, section["evidence"]["xml_locator"])
        reread = read_section_evidence(element, locators)
        assert reread.section_sha256 == section["evidence"]["section_sha256"]
        assert reread.original_text == section["text"]


def test_rerunning_the_same_input_neither_duplicates_nor_corrupts(tmp_path: Path) -> None:
    core = pipeline(tmp_path)
    first = core.run("Eliquis", set_id=ELIQUIS_SET_ID)
    written = Path(first["evidence_path"]).read_bytes()

    second = core.run("Eliquis", set_id=ELIQUIS_SET_ID)

    assert first["acquisition"]["status"] == "fetched"
    assert second["acquisition"]["status"] == "already_stored"
    assert first["evidence_status"] == "created"
    assert second["evidence_status"] == "unchanged"
    assert second["status"] == "verified"
    assert Path(second["evidence_path"]) == Path(first["evidence_path"])
    assert Path(second["evidence_path"]).read_bytes() == written
    assert second["evidence"] == first["evidence"]

    stored = sorted(
        path.name for path in (core.raw_store.root / "dailymed" / ELIQUIS_SET_ID).iterdir()
    )
    assert stored == [ELIQUIS_VERSION]


def test_a_bundle_that_no_longer_matches_its_raw_source_fails_verification(
    tmp_path: Path,
) -> None:
    core = pipeline(tmp_path)
    result = core.run("Eliquis", set_id=ELIQUIS_SET_ID)
    raw_path = core.data_root / result["evidence"]["source"]["raw_path"]
    raw_path.write_bytes(raw_path.read_bytes().replace(b"ELIQUIS", b"PLACEBO", 1))

    report = core.verify(result["evidence"])

    assert report.ok is False
    assert [item.name for item in report.checks if not item.ok] == ["raw_sha256"]


def test_a_locator_that_does_not_resolve_is_reported_not_ignored(tmp_path: Path) -> None:
    core = pipeline(tmp_path)
    result = core.run("Eliquis", set_id=ELIQUIS_SET_ID)
    payload = result["evidence"]
    payload["sections"][0]["evidence"]["xml_locator"] = "/document[1]/component[99]/section[1]"

    report = core.verify(payload)

    assert report.ok is False
    assert report.failures[0]["xml_locator"] == "/document[1]/component[99]/section[1]"


def test_edited_extracted_text_is_caught_against_the_raw_source(tmp_path: Path) -> None:
    core = pipeline(tmp_path)
    result = core.run("Eliquis", set_id=ELIQUIS_SET_ID)
    payload = result["evidence"]
    payload["sections"][0]["text"] = "text an AI must never be handed as source-backed"

    report = core.verify(payload)

    assert report.ok is False
    assert "text" in report.failures[0]["differing_fields"]


def test_a_bundle_may_not_point_outside_the_data_root(tmp_path: Path) -> None:
    core = pipeline(tmp_path)
    result = core.run("Eliquis", set_id=ELIQUIS_SET_ID)
    payload = result["evidence"]
    payload["source"]["raw_path"] = "../../etc/passwd"

    report = core.verify(payload)

    assert report.ok is False
    assert report.checks[-1].name == "raw_present"


def test_section_filter_returns_only_what_was_asked_for(tmp_path: Path) -> None:
    core = pipeline(tmp_path)
    core.acquire("Eliquis", set_id=ELIQUIS_SET_ID)
    everything = core.extract(ELIQUIS_SET_ID, ELIQUIS_VERSION)
    all_sections = everything.payload["sections"]
    wanted = all_sections[1]["section_code"]

    filtered = core.extract(ELIQUIS_SET_ID, ELIQUIS_VERSION, section_codes=(wanted,))

    returned = filtered.payload["sections"]
    assert filtered.payload["extraction"]["document_section_count"] == len(all_sections)
    assert 0 < len(returned) < len(all_sections)
    assert returned[0]["section_code"] == wanted
    assert core.verify(filtered.payload).ok is True


def test_a_filtered_section_brings_its_subsections_with_it(tmp_path: Path) -> None:
    core = pipeline(tmp_path)
    core.acquire("Eliquis", set_id=ELIQUIS_SET_ID)
    everything = core.extract(ELIQUIS_SET_ID, ELIQUIS_VERSION).payload["sections"]
    # Sections are depth-first, so a parent is any depth-0 section followed by a deeper one.
    parent = next(
        current
        for current, following in zip(everything, everything[1:], strict=False)
        if current["depth"] == 0 and following["depth"] > 0
    )

    filtered = core.extract(
        ELIQUIS_SET_ID, ELIQUIS_VERSION, section_codes=(parent["section_code"],)
    ).payload

    depths = {item["depth"] for item in filtered["sections"]}
    assert depths > {0}, "a numbered section must return the subsections holding its text"
    assert filtered["extraction"]["section_filter"]["include_subsections"] is True


def test_missing_official_facts_stay_unknown(tmp_path: Path) -> None:
    core = pipeline(tmp_path)
    core.acquire("Eliquis", set_id=ELIQUIS_SET_ID)
    payload = core.extract(ELIQUIS_SET_ID, ELIQUIS_VERSION).payload

    assert payload["drug"]["requested_term"] == UNKNOWN
    untitled = [
        item for item in payload["sections"] if item["section_name"] == UNKNOWN
    ]
    for section in untitled:
        element = resolve_locator(
            parse_document_root((core.data_root / payload["source"]["raw_path"]).read_bytes()),
            section["evidence"]["xml_locator"],
        )
        assert element.find("{urn:hl7-org:v3}title") is None


def test_locator_rejects_a_path_that_is_not_a_local_name_walk() -> None:
    root = ElementTree.fromstring("<document><a/></document>")

    with pytest.raises(ProvenanceValidationFailure):
        resolve_locator(root, "//document[1]/a[1]")
    with pytest.raises(ProvenanceValidationFailure):
        resolve_locator(root, "/document[1]/a[1]/../b[1]")

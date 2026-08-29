"""A slice file is named after everything that decides what is in it.

Two different requests landing on one file name is not a cosmetic problem: the
second write destroys the first, and the loss is silent. Locators decide the
contents exactly as codes do, so these tests hold the fingerprint to that.
"""

from __future__ import annotations

import json
from pathlib import Path

from odd.catalog import build_document_catalog
from odd.core.direct import fetch_by_set_id
from odd.core.selective import CORE_SLICE_SCHEMA_VERSION, slice_fingerprint
from odd.mcp.tools import OddTools
from tests.core.test_core_pipeline import ELIQUIS_SET_ID, ELIQUIS_VERSION, pipeline
from tests.mcp.test_codeless_section_slice import codeless_xml

CODE = "34067-9"


def request(
    codes: list[str] | None = None,
    locators: list[str] | None = None,
    numbers: list[str] | None = None,
) -> dict:
    """A payload shaped like the request block build_slice_payload writes."""

    return {
        "request": {
            "requested_section_codes": sorted({c for c in (codes or []) if c}),
            "requested_section_locators": sorted({v for v in (locators or []) if v}),
            "requested_application_numbers": sorted({n for n in (numbers or []) if n}),
        }
    }


A = "/document[1]/component[1]/structuredBody[1]/component[3]/section[1]"
B = "/document[1]/component[1]/structuredBody[1]/component[4]/section[1]"


# -- the fingerprint itself -------------------------------------------------
def test_order_and_repetition_do_not_change_the_fingerprint() -> None:
    assert slice_fingerprint(request(locators=[A, B])) == slice_fingerprint(
        request(locators=[B, A, A])
    )


def test_a_different_locator_set_gets_a_different_fingerprint() -> None:
    assert slice_fingerprint(request(locators=[A])) != slice_fingerprint(
        request(locators=[B])
    )
    assert slice_fingerprint(request(locators=[A])) != slice_fingerprint(
        request(locators=[A, B])
    )


def test_a_code_only_request_keeps_the_fingerprint_it_always_had() -> None:
    """Slice files already written must stay reachable under their own names."""

    import hashlib

    for codes, numbers in (
        ([CODE], []),
        ([CODE, "34068-7"], []),
        ([CODE], ["NDA202155"]),
        ([], []),
    ):
        legacy = hashlib.sha256(
            f"{','.join(sorted(set(codes)))}|{','.join(sorted(set(numbers)))}".encode()
        ).hexdigest()[:12]
        assert slice_fingerprint(request(codes=codes, numbers=numbers)) == legacy


def test_a_code_only_request_and_a_code_plus_locator_request_differ() -> None:
    assert slice_fingerprint(request(codes=[CODE])) != slice_fingerprint(
        request(codes=[CODE], locators=[A])
    )


def test_application_numbers_still_separate_requests() -> None:
    assert slice_fingerprint(request(codes=[CODE], numbers=["NDA202155"])) != (
        slice_fingerprint(request(codes=[CODE], numbers=["NDA999999"]))
    )
    assert slice_fingerprint(request(locators=[A], numbers=["NDA202155"])) != (
        slice_fingerprint(request(locators=[A], numbers=["NDA999999"]))
    )


def test_a_locator_that_matches_nothing_still_names_its_own_request() -> None:
    """A not-found request must not overwrite the file of a request that found something."""

    absent = "/document[1]/component[1]/structuredBody[1]/component[999]/section[1]"
    assert slice_fingerprint(request(locators=[absent])) != slice_fingerprint(
        request(locators=[A])
    )
    assert slice_fingerprint(request(locators=[absent])) != slice_fingerprint(
        request(codes=[CODE])
    )


def test_the_slice_schema_version_states_the_added_fields() -> None:
    assert CORE_SLICE_SCHEMA_VERSION == "odd-core-evidence-slice/1.1.0"


# -- the reason it matters: two writes must not collide ---------------------
def test_two_locator_slices_written_to_disk_keep_both_files(tmp_path: Path) -> None:
    core = pipeline(tmp_path, xml_body=codeless_xml())
    fetch_by_set_id(core.connector, core.raw_store, ELIQUIS_SET_ID)
    build_document_catalog(core.data_root, parser=core.parser, clock=core.clock)
    index = OddTools(core).get_section_index(ELIQUIS_SET_ID)
    codeless = [e for e in index["sections"] if e["section_code"] == "UNKNOWN"]
    first, second = codeless[0], codeless[1]

    written_first = core.extract(
        ELIQUIS_SET_ID, ELIQUIS_VERSION, slice_only=True, offline=True,
        section_locators=(first["evidence_locator"],),
    )
    written_second = core.extract(
        ELIQUIS_SET_ID, ELIQUIS_VERSION, slice_only=True, offline=True,
        section_locators=(second["evidence_locator"],),
    )

    assert written_first.path != written_second.path, "one name for two slices loses one"
    assert written_first.path.is_file() and written_second.path.is_file()

    kept_first = json.loads(written_first.path.read_text(encoding="utf-8"))
    kept_second = json.loads(written_second.path.read_text(encoding="utf-8"))
    assert [s["evidence"]["xml_locator"] for s in kept_first["label_evidence"]] == [
        first["evidence_locator"]
    ]
    assert [s["evidence"]["xml_locator"] for s in kept_second["label_evidence"]] == [
        second["evidence_locator"]
    ]
    assert kept_first["schema_version"] == CORE_SLICE_SCHEMA_VERSION

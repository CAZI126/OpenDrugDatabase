"""Offline tests for the batch conveyor: order, isolation, and honest statuses."""

from __future__ import annotations

from pathlib import Path

import pytest

from odd.core.batch import (
    AMBIGUOUS,
    BLANK_SET_ID,
    ERROR,
    NOT_PRESERVED_LOCALLY,
    UNKNOWN,
    VERIFIED,
    read_set_id_file,
    run_batch,
)
from odd.errors import MalformedXML
from tests.core.test_core_pipeline import ELIQUIS_SET_ID, ELIQUIS_VERSION, pipeline

ABSENT_SET_ID = "00000000-0000-4000-8000-000000000000"
MALFORMED_SET_ID = "not a valid segment/../etc"


def prepared(tmp_path: Path):
    core = pipeline(tmp_path)
    core.acquire("Eliquis", set_id=ELIQUIS_SET_ID)
    return core


def test_three_preserved_identities_all_verify(tmp_path: Path) -> None:
    core = prepared(tmp_path)

    report = run_batch(core, [ELIQUIS_SET_ID, ELIQUIS_SET_ID.upper(), ELIQUIS_SET_ID])

    assert report["total"] == 1
    assert report["verified"] == 1
    assert report["items"][0]["status"] == VERIFIED
    assert report["items"][0]["section_count"] > 0
    assert report["items"][0]["index_status"] == "COMPLETE"


def test_items_after_a_failure_are_still_processed(tmp_path: Path) -> None:
    """Two identities failing must not cost the one behind them."""

    core = prepared(tmp_path)

    report = run_batch(core, [MALFORMED_SET_ID, ABSENT_SET_ID, ELIQUIS_SET_ID])

    assert [item["status"] for item in report["items"]] == [ERROR, UNKNOWN, VERIFIED]
    assert report["items"][2]["section_count"] > 0
    assert report["total"] == 3


def test_a_parser_failure_mid_batch_is_isolated_to_its_item(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A raised error inside one item must become that item's status, not a crash."""

    core = prepared(tmp_path)
    original = core.extract
    attempts: list[str] = []

    def flaky(set_id: str, *args: object, **kwargs: object):
        attempts.append(set_id)
        if len(attempts) == 1:
            raise MalformedXML("simulated parser failure")
        return original(set_id, *args, **kwargs)

    monkeypatch.setattr(core, "extract", flaky)
    first = run_batch(core, [ELIQUIS_SET_ID])
    second = run_batch(core, [ELIQUIS_SET_ID])

    assert first["items"][0]["status"] == ERROR
    assert first["items"][0]["error_code"] == "MALFORMED_XML"
    # Provenance observed before the failure is still reported, not discarded.
    assert first["items"][0]["raw_sha256"]
    assert second["items"][0]["status"] == VERIFIED


def test_an_identity_that_is_not_preserved_is_unknown_not_error(tmp_path: Path) -> None:
    """Not held locally is not the same as not existing officially."""

    report = run_batch(prepared(tmp_path), [ABSENT_SET_ID])

    assert report["items"][0]["status"] == UNKNOWN
    assert report["items"][0]["error_code"] == NOT_PRESERVED_LOCALLY
    assert report["items"][0]["raw_sha256"] is None


def test_a_malformed_identity_is_an_item_level_error(tmp_path: Path) -> None:
    core = prepared(tmp_path)

    report = run_batch(core, [MALFORMED_SET_ID, ELIQUIS_SET_ID])

    assert report["items"][0]["status"] == ERROR
    assert report["items"][0]["error_code"]
    assert report["items"][1]["status"] == VERIFIED, "a bad line must not sink the batch"
    assert report["error"] == 1 and report["verified"] == 1


def test_blank_lines_are_skipped_when_reading_the_file(tmp_path: Path) -> None:
    path = tmp_path / "ids.txt"
    path.write_text(f"\n{ELIQUIS_SET_ID}\n\n   \n{ABSENT_SET_ID}\n\n", encoding="utf-8")

    assert read_set_id_file(path) == [ELIQUIS_SET_ID, ABSENT_SET_ID]


def test_a_blank_identity_passed_directly_is_an_error(tmp_path: Path) -> None:
    report = run_batch(prepared(tmp_path), ["   "])

    assert report["items"][0]["status"] == ERROR
    assert report["items"][0]["error_code"] == BLANK_SET_ID


def test_duplicates_collapse_deterministically_to_the_first_occurrence(
    tmp_path: Path,
) -> None:
    core = prepared(tmp_path)

    report = run_batch(
        core, [ABSENT_SET_ID, ELIQUIS_SET_ID, ABSENT_SET_ID, ELIQUIS_SET_ID.upper()]
    )

    assert [item["set_id"] for item in report["items"]] == [
        ABSENT_SET_ID,
        ELIQUIS_SET_ID,
    ], "first occurrence wins, in input order"
    assert report["duplicates_ignored"] == 2
    assert report["total"] == 2


def test_input_order_is_preserved(tmp_path: Path) -> None:
    core = prepared(tmp_path)
    forward = run_batch(core, [ELIQUIS_SET_ID, ABSENT_SET_ID])
    backward = run_batch(core, [ABSENT_SET_ID, ELIQUIS_SET_ID])

    assert [item["set_id"] for item in forward["items"]] == [
        ELIQUIS_SET_ID,
        ABSENT_SET_ID,
    ]
    assert [item["set_id"] for item in backward["items"]] == [
        ABSENT_SET_ID,
        ELIQUIS_SET_ID,
    ]
    assert forward["verified"] == backward["verified"] == 1


def test_totals_always_account_for_every_item(tmp_path: Path) -> None:
    report = run_batch(
        prepared(tmp_path), [ELIQUIS_SET_ID, ABSENT_SET_ID, MALFORMED_SET_ID, "  "]
    )

    counted = sum(report[name] for name in (VERIFIED, AMBIGUOUS, UNKNOWN, ERROR))
    assert report["total"] == len(report["items"]) == counted


def test_the_same_input_produces_the_same_report(tmp_path: Path) -> None:
    """Nothing time-varying may reach the result."""

    core = prepared(tmp_path)
    ids = [ELIQUIS_SET_ID, ABSENT_SET_ID, MALFORMED_SET_ID]

    assert run_batch(core, ids) == run_batch(core, ids)


def test_batch_drives_the_existing_single_document_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The conveyor must call the same extract a single-document run calls."""

    core = prepared(tmp_path)
    seen: list[dict[str, object]] = []
    original = core.extract

    def record(set_id: str, *args: object, **kwargs: object):
        seen.append({"set_id": set_id, "index_only": kwargs.get("index_only")})
        return original(set_id, *args, **kwargs)

    monkeypatch.setattr(core, "extract", record)
    run_batch(core, [ELIQUIS_SET_ID])

    assert seen == [{"set_id": ELIQUIS_SET_ID, "index_only": True}]


def test_batch_adds_no_drug_specific_branch() -> None:
    source = Path(__import__("odd.core.batch", fromlist=["x"]).__file__).read_text(
        encoding="utf-8"
    )
    for name in ("eliquis", "atorvastatin", "metformin", "apixaban", "e9481622"):
        assert name not in source.casefold()


def test_index_slice_and_full_bundle_are_unchanged_by_batch(tmp_path: Path) -> None:
    core = prepared(tmp_path)
    full = core.extract(ELIQUIS_SET_ID, ELIQUIS_VERSION).payload
    index = core.extract(ELIQUIS_SET_ID, ELIQUIS_VERSION, index_only=True).payload

    run_batch(core, [ELIQUIS_SET_ID])

    assert core.extract(ELIQUIS_SET_ID, ELIQUIS_VERSION).payload == full
    assert core.extract(ELIQUIS_SET_ID, ELIQUIS_VERSION, index_only=True).payload == index
    assert core.verify(full).ok is True

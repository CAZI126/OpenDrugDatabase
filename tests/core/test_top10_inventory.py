"""Offline tests for cohort inventory building and retrieval by identity alone.

Snapshots here are built in-process from a few rows. No network, and no real
distribution is committed.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from odd.connectors.dailymed.client import DailyMedConnector
from odd.core.direct import fetch_by_set_id
from odd.errors import ProvenanceValidationFailure, SourceNotFound
from odd.provenance.hashing import sha256_bytes
from odd.provenance.raw_store import RawStore
from tests.core.test_core_pipeline import BASE_URL, ELIQUIS_SET_ID, ELIQUIS_XML, _Transport

_SPEC = importlib.util.spec_from_file_location(
    "build_top10_inventory",
    Path(__file__).resolve().parents[2] / "scripts" / "build_top10_inventory.py",
)
assert _SPEC and _SPEC.loader
inventory = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(inventory)

HOST = "https://dailymed.nlm.nih.gov/dailymed/services/v2/spls.json"


def page_url(drug: str, page: int) -> str:
    return f"{HOST}?doctype=34391-3&drug_name={drug}&name_type=generic&pagesize=2&page={page}"


def write_snapshot(
    root: Path,
    drug: str,
    pages: list[list[str]],
    *,
    current_page_override: dict[int, int] | None = None,
    drop_page: int | None = None,
    corrupt_hash_page: int | None = None,
    strip_query_page: int | None = None,
) -> Path:
    """Write one preserved snapshot, optionally with a specific defect."""

    directory = root / f"snapshot-{drug}"
    directory.mkdir(parents=True, exist_ok=True)
    total = sum(len(rows) for rows in pages)
    entries: list[dict[str, Any]] = []
    for index, rows in enumerate(pages, start=1):
        url = page_url(drug, index)
        body = json.dumps(
            {
                "data": [
                    {
                        "setid": set_id,
                        "spl_version": 1,
                        "title": f"{drug.upper()} TABLET",
                        "published_date": "Jan 01, 2026",
                    }
                    for set_id in rows
                ],
                "metadata": {
                    "current_page": (current_page_override or {}).get(index, index),
                    "current_url": url,
                    "elements_per_page": 2,
                    "total_elements": total,
                    "total_pages": len(pages),
                },
            }
        ).encode("utf-8")
        digest = sha256_bytes(body)
        if index != drop_page:
            (directory / f"page-{index:04d}.response").write_bytes(body)
        entries.append(
            {
                "page_number": index,
                "raw_sha256": "0" * 64 if index == corrupt_hash_page else digest,
                "request_url": (
                    f"{HOST}?page={index}" if index == strip_query_page else url
                ),
                "response_url": url,
                "status_code": 200,
            }
        )
    (directory / "manifest.json").write_bytes(
        json.dumps(
            {
                "completeness": "COMPLETE",
                "metadata_total_elements": total,
                "pages": entries,
                "snapshot_id": f"snapshot-{drug}",
                "total_pages": len(pages),
            }
        ).encode("utf-8")
    )
    return directory


def write_cohort(root: Path, names: list[str]) -> Path:
    path = root / "cohort.json"
    path.write_bytes(
        json.dumps(
            {
                "entries": [
                    {"ingredient_name": name, "rank": index}
                    for index, name in enumerate(names, start=1)
                ],
                "utilization_list_id": "test-cohort",
            }
        ).encode("utf-8")
    )
    return path


def build(tmp_path: Path, **kwargs: Any) -> dict[str, Any]:
    return inventory.build(
        tmp_path / "cohort.json", tmp_path / "snapshots", tmp_path / "out", **kwargs
    )


def test_the_frozen_cohort_is_used_exactly_as_written(tmp_path: Path) -> None:
    """Rank and membership come from the frozen list, never from the snapshots."""

    write_cohort(tmp_path, ["beta", "alpha"])
    write_snapshot(tmp_path / "snapshots", "alpha", [["a-1", "a-2"]])
    write_snapshot(tmp_path / "snapshots", "beta", [["b-1"]])

    summary = build(tmp_path)

    assert [(d["rank"], d["drug_name"]) for d in summary["drugs"]] == [
        (1, "beta"),
        (2, "alpha"),
    ]
    assert summary["cohort"]["entries"][0]["ingredient_name"] == "beta"


def test_candidates_are_collected_from_every_page_of_every_drug(tmp_path: Path) -> None:
    write_cohort(tmp_path, ["alpha", "beta"])
    write_snapshot(tmp_path / "snapshots", "alpha", [["a-1", "a-2"], ["a-3"]])
    write_snapshot(tmp_path / "snapshots", "beta", [["b-1", "b-2"]])

    summary = build(tmp_path)

    assert summary["snapshot_records"] == 5
    assert summary["unique_set_ids"] == 5
    assert summary["incomplete_drugs"] == []
    assert all(d["completeness"] == "COMPLETE" for d in summary["drugs"])


def test_one_identity_in_two_drugs_keeps_both_memberships(tmp_path: Path) -> None:
    """A shared identity is a fact about the source, not a duplicate to discard."""

    write_cohort(tmp_path, ["alpha", "beta"])
    write_snapshot(tmp_path / "snapshots", "alpha", [["shared", "a-1"]])
    write_snapshot(tmp_path / "snapshots", "beta", [["shared", "b-1"]])

    summary = build(tmp_path)
    records = [
        json.loads(line)
        for line in (tmp_path / "out" / "top10_records.jsonl").read_text("utf-8").splitlines()
    ]

    assert summary["snapshot_records"] == 4
    assert summary["unique_set_ids"] == 3
    assert summary["set_ids_in_more_than_one_drug"] == 1
    assert {r["drug_name"] for r in records if r["set_id"] == "shared"} == {"alpha", "beta"}


def test_the_batch_input_carries_each_identity_once_in_first_seen_order(
    tmp_path: Path,
) -> None:
    write_cohort(tmp_path, ["alpha", "beta"])
    write_snapshot(tmp_path / "snapshots", "alpha", [["shared", "a-1"]])
    write_snapshot(tmp_path / "snapshots", "beta", [["shared", "b-1"]])

    build(tmp_path)
    ids = (tmp_path / "out" / "top10_set_ids.txt").read_text("utf-8").split()

    assert ids == ["shared", "a-1", "b-1"]


def test_a_page_whose_query_was_lost_is_reported(tmp_path: Path) -> None:
    write_cohort(tmp_path, ["alpha"])
    write_snapshot(tmp_path / "snapshots", "alpha", [["a-1"], ["a-2"]], strip_query_page=2)

    summary = build(tmp_path)

    assert summary["incomplete_drugs"] == ["alpha"]
    assert any("query" in p for p in summary["drugs"][0]["problems"])


def test_a_missing_page_is_reported(tmp_path: Path) -> None:
    write_cohort(tmp_path, ["alpha"])
    write_snapshot(tmp_path / "snapshots", "alpha", [["a-1"], ["a-2"]], drop_page=2)

    summary = build(tmp_path)

    assert summary["incomplete_drugs"] == ["alpha"]
    assert any("contiguous" in p for p in summary["drugs"][0]["problems"])


def test_a_current_page_that_disagrees_is_reported(tmp_path: Path) -> None:
    write_cohort(tmp_path, ["alpha"])
    write_snapshot(
        tmp_path / "snapshots", "alpha", [["a-1"], ["a-2"]], current_page_override={2: 7}
    )

    summary = build(tmp_path)

    assert summary["incomplete_drugs"] == ["alpha"]
    assert any("current_page" in p for p in summary["drugs"][0]["problems"])


def test_a_page_whose_bytes_changed_is_reported(tmp_path: Path) -> None:
    write_cohort(tmp_path, ["alpha"])
    write_snapshot(tmp_path / "snapshots", "alpha", [["a-1"], ["a-2"]], corrupt_hash_page=1)

    summary = build(tmp_path)

    assert summary["incomplete_drugs"] == ["alpha"]
    assert any("SHA-256" in p for p in summary["drugs"][0]["problems"])


def test_rebuilding_from_the_same_snapshot_reproduces_the_same_bytes(
    tmp_path: Path,
) -> None:
    write_cohort(tmp_path, ["alpha", "beta"])
    write_snapshot(tmp_path / "snapshots", "alpha", [["a-1", "a-2"], ["a-3"]])
    write_snapshot(tmp_path / "snapshots", "beta", [["b-1"]])

    build(tmp_path)
    first = [(tmp_path / "out" / n).read_bytes() for n in
             ("top10_records.jsonl", "top10_set_ids.txt", "top10_inventory_summary.json")]
    build(tmp_path)
    second = [(tmp_path / "out" / n).read_bytes() for n in
              ("top10_records.jsonl", "top10_set_ids.txt", "top10_inventory_summary.json")]

    assert first == second


def test_per_drug_counts_account_for_every_record(tmp_path: Path) -> None:
    write_cohort(tmp_path, ["alpha", "beta"])
    write_snapshot(tmp_path / "snapshots", "alpha", [["shared", "a-1"], ["a-2"]])
    write_snapshot(tmp_path / "snapshots", "beta", [["shared"]])

    summary = build(tmp_path)

    assert sum(d["snapshot_records"] for d in summary["drugs"]) == summary["snapshot_records"]
    assert summary["unique_set_ids"] == 3


def test_retrieval_by_set_id_accepts_only_the_document_that_was_asked_for(
    tmp_path: Path,
) -> None:
    connector = DailyMedConnector(
        base_url=BASE_URL, user_agent="t/1", transport=_Transport(), clock=None
    )
    store = RawStore(tmp_path / "raw")

    raw = fetch_by_set_id(connector, store, ELIQUIS_SET_ID)

    assert raw.identity.source_document_id == ELIQUIS_SET_ID
    # The version came from the document, not from any listing.
    assert raw.identity.source_version == "30"
    assert raw.label_path.read_bytes() == ELIQUIS_XML.read_bytes()


def test_a_document_declaring_another_identity_is_not_stored(tmp_path: Path) -> None:
    """A mismatch is a failure, never a near miss quietly kept."""

    connector = DailyMedConnector(
        base_url=BASE_URL, user_agent="t/1", transport=_Transport(), clock=None
    )
    store = RawStore(tmp_path / "raw")
    other = "11111111-2222-4333-8444-555555555555"

    with pytest.raises(ProvenanceValidationFailure) as error:
        fetch_by_set_id(connector, store, other)

    assert error.value.details["requested_set_id"] == other
    assert error.value.details["declared_set_id"] == ELIQUIS_SET_ID
    assert not list((tmp_path / "raw").rglob("label.xml")), "nothing may be preserved"


def test_a_document_declaring_its_set_id_in_another_case_still_resolves(
    tmp_path: Path,
) -> None:
    """A set id is case-insensitive; the same document must not read as a mismatch.

    Retrieval by identity takes the set id from the document itself, so a label
    that spells its own setId in upper case is stored that way while the caller
    asks in the case the listing used. That is one document, not two.
    """

    connector = DailyMedConnector(
        base_url=BASE_URL, user_agent="t/1", transport=_Transport(), clock=None
    )
    store = RawStore(tmp_path / "raw")
    fetch_by_set_id(connector, store, ELIQUIS_SET_ID)

    resolved = store.resolve(ELIQUIS_SET_ID.upper(), "30")

    assert resolved.identity.source_document_id.casefold() == ELIQUIS_SET_ID.casefold()
    assert resolved.identity.source_version == "30"
    # The version is still compared exactly.
    with pytest.raises(SourceNotFound):
        store.resolve(ELIQUIS_SET_ID, "29")

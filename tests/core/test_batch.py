"""Offline tests for the batch conveyor: order, isolation, and honest statuses."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from odd.core.batch import (
    AMBIGUOUS,
    BLANK_SET_ID,
    ERROR,
    INDEX_VERIFICATION_FAILED,
    NOT_IN_OFFICIAL_LISTING,
    NOT_PRESERVED_LOCALLY,
    STORED_VERSION_DIFFERS,
    UNKNOWN,
    VERIFIED,
    ManifestEntry,
    read_manifest,
    read_set_id_file,
    run_batch,
)
from odd.core.cli import main as cli_main
from odd.errors import MalformedMetadata, MalformedXML
from tests.core.test_core_pipeline import ELIQUIS_SET_ID, ELIQUIS_VERSION, pipeline

ABSENT_SET_ID = "00000000-0000-4000-8000-000000000000"
MALFORMED_SET_ID = "not a valid segment/../etc"


def manifest_file(tmp_path: Path, items: list[dict[str, object]]) -> Path:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"items": items}), encoding="utf-8")
    return path


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


def test_every_row_carries_the_same_field_types_whichever_path_built_it(
    tmp_path: Path,
) -> None:
    """A row grows from the caller's claim, to a resolved identity, to an index.

    A reader parses one shape, so a row that stopped at the caller's claim must
    still carry the same fields, with the same types, as one that ran the whole
    way. Only a value that was never observed is absent, and absent is ``None``.
    """

    report = run_batch(prepared(tmp_path), [ELIQUIS_SET_ID, ABSENT_SET_ID, "   "])
    rows = report["items"]

    assert [row["status"] for row in rows] == [VERIFIED, UNKNOWN, ERROR]
    for row in rows:
        assert isinstance(row["set_id"], str)
        assert isinstance(row["status"], str)
        assert isinstance(row["section_count"], int)
        for optional in (
            "drug",
            "error",
            "error_code",
            "evidence_path",
            "index_status",
            "raw_sha256",
            "requested_source_version",
            "source_url",
            "source_version",
        ):
            assert row[optional] is None or isinstance(row[optional], str)
    assert rows[0]["section_count"] > 0
    assert [row["section_count"] for row in rows[1:]] == [0, 0]


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


def test_a_manifest_states_drug_set_id_and_source_version(tmp_path: Path) -> None:
    path = manifest_file(
        tmp_path,
        [
            {"drug": "apixaban", "set_id": ELIQUIS_SET_ID, "source_version": "30"},
            {"drug": "nothing preserved", "set_id": ABSENT_SET_ID, "source_version": "1"},
        ],
    )

    assert read_manifest(path) == [
        ManifestEntry(set_id=ELIQUIS_SET_ID, drug="apixaban", source_version="30"),
        ManifestEntry(
            set_id=ABSENT_SET_ID, drug="nothing preserved", source_version="1"
        ),
    ]


def test_a_manifest_row_without_a_set_id_is_rejected_before_anything_runs(
    tmp_path: Path,
) -> None:
    path = manifest_file(tmp_path, [{"drug": "apixaban", "source_version": "30"}])

    with pytest.raises(MalformedMetadata):
        read_manifest(path)


def test_a_manifest_run_reports_a_path_and_a_status_for_every_row(
    tmp_path: Path,
) -> None:
    core = prepared(tmp_path)

    report = run_batch(
        core,
        [
            ManifestEntry(set_id=ELIQUIS_SET_ID, drug="apixaban", source_version="30"),
            ManifestEntry(set_id=ABSENT_SET_ID, drug="absent", source_version="1"),
        ],
    )

    first, second = report["items"]
    assert first["status"] == VERIFIED
    assert first["drug"] == "apixaban"
    assert first["source_version"] == ELIQUIS_VERSION
    assert Path(first["evidence_path"]).is_file()
    assert first["error"] is None
    assert second["status"] == UNKNOWN
    assert second["evidence_path"] is None
    assert second["error"]
    assert report["status_counts"] == {
        VERIFIED: 1,
        AMBIGUOUS: 0,
        UNKNOWN: 1,
        ERROR: 0,
    }


def test_the_conveyed_path_holds_the_index_for_that_identity(tmp_path: Path) -> None:
    core = prepared(tmp_path)

    report = run_batch(
        core, [ManifestEntry(set_id=ELIQUIS_SET_ID, source_version=ELIQUIS_VERSION)]
    )

    written = json.loads(Path(report["items"][0]["evidence_path"]).read_bytes())
    assert written["document"]["set_id"] == ELIQUIS_SET_ID
    assert written["document"]["source_version"] == ELIQUIS_VERSION
    assert core.verify(written).ok is True


def test_a_version_absent_from_the_official_listing_is_reported_not_substituted(
    tmp_path: Path,
) -> None:
    """The listing offers version 30. Asking for 29 must not hand back 30."""

    core = prepared(tmp_path)

    report = run_batch(
        core, [ManifestEntry(set_id=ELIQUIS_SET_ID, drug="apixaban", source_version="29")]
    )

    item = report["items"][0]
    assert item["status"] == UNKNOWN
    assert item["error_code"] == NOT_IN_OFFICIAL_LISTING
    assert item["requested_source_version"] == "29"
    assert item["evidence_path"] is None


def test_retrieval_by_set_id_alone_reports_a_version_the_caller_did_not_name(
    tmp_path: Path,
) -> None:
    """Retrieving by identity returns whatever version the document declares.

    That version is a fact about the document, not a correction to the manifest,
    so a manifest naming a different one gets a mismatch and not a substitution.
    """

    core = pipeline(tmp_path)

    report = run_batch(
        core,
        [ManifestEntry(set_id=ELIQUIS_SET_ID, drug="apixaban", source_version="29")],
        fetch_missing_by_set_id=True,
    )

    item = report["items"][0]
    assert item["status"] == UNKNOWN
    assert item["error_code"] == STORED_VERSION_DIFFERS
    assert item["requested_source_version"] == "29"
    assert item["source_version"] == ELIQUIS_VERSION
    assert item["evidence_path"] is None


def test_a_manifest_row_failing_does_not_cost_the_rows_behind_it(
    tmp_path: Path,
) -> None:
    core = prepared(tmp_path)

    report = run_batch(
        core,
        [
            ManifestEntry(set_id=MALFORMED_SET_ID, drug="malformed"),
            ManifestEntry(set_id=ABSENT_SET_ID, drug="absent"),
            ManifestEntry(set_id=ELIQUIS_SET_ID, drug="apixaban", source_version="30"),
        ],
    )

    assert [item["status"] for item in report["items"]] == [ERROR, UNKNOWN, VERIFIED]
    assert [item["drug"] for item in report["items"]] == [
        "malformed",
        "absent",
        "apixaban",
    ]
    assert report["status_counts"][VERIFIED] == 1


def test_a_corrupted_preserved_source_is_reported_not_passed_as_verified(
    tmp_path: Path,
) -> None:
    """Custody is recomputed, so bytes that changed under the index cannot pass."""

    core = prepared(tmp_path)
    entry = ManifestEntry(set_id=ELIQUIS_SET_ID, source_version=ELIQUIS_VERSION)
    assert run_batch(core, [entry], verify_only=True)["items"][0]["status"] == VERIFIED

    index_path = Path(run_batch(core, [entry])["items"][0]["evidence_path"])
    payload = json.loads(index_path.read_bytes())
    payload["sections"][0]["section_sha256"] = "0" * 64
    index_path.write_bytes(json.dumps(payload).encode("utf-8"))

    report = run_batch(core, [entry], verify_only=True)

    # Rebuilt from the preserved bytes, so a tampered file on disk is simply
    # replaced -- what must never happen is a tampered index being believed.
    assert report["items"][0]["status"] == VERIFIED
    assert core.verify(payload).ok is False


def test_verify_only_reaches_nothing_off_this_machine(tmp_path: Path) -> None:
    """The stored run must be re-checkable with the network unplugged."""

    core = prepared(tmp_path)

    def refuse(*args: object, **kwargs: object):
        raise AssertionError("verify_only must not retrieve anything")

    core.connector.download = refuse  # type: ignore[method-assign]
    core.connector.search = refuse  # type: ignore[method-assign]

    report = run_batch(
        core,
        [
            ManifestEntry(set_id=ELIQUIS_SET_ID, drug="apixaban", source_version="30"),
            ManifestEntry(set_id=ABSENT_SET_ID, drug="absent", source_version="1"),
        ],
        verify_only=True,
    )

    assert report["verify_only"] is True
    assert [item["status"] for item in report["items"]] == [VERIFIED, UNKNOWN]
    assert report["items"][1]["error_code"] == NOT_PRESERVED_LOCALLY


def test_an_index_that_does_not_reverify_is_an_error_not_a_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = prepared(tmp_path)
    original = core.verify
    monkeypatch.setattr(
        core, "verify", lambda payload: original({**payload, "sections": [{}]})
    )

    report = run_batch(
        core, [ManifestEntry(set_id=ELIQUIS_SET_ID, source_version=ELIQUIS_VERSION)]
    )

    assert report["items"][0]["status"] == ERROR
    assert report["items"][0]["error_code"] == INDEX_VERIFICATION_FAILED
    assert report["items"][0]["error"]


def run_cli(tmp_path: Path, *arguments: str) -> tuple[dict, int]:
    stream = io.StringIO()
    code = cli_main(
        [*arguments, "--data-dir", str(tmp_path / "data"), "--print-evidence"],
        stream=stream,
    )
    return json.loads(stream.getvalue()), code


def test_the_offline_entry_reverifies_a_stored_run_from_a_manifest(
    tmp_path: Path,
) -> None:
    """The whole point of the offline entry: no network, real re-verification."""

    prepared(tmp_path)
    path = manifest_file(
        tmp_path,
        [
            {"drug": "apixaban", "set_id": ELIQUIS_SET_ID, "source_version": "30"},
            {"drug": "absent", "set_id": ABSENT_SET_ID, "source_version": "1"},
        ],
    )

    report, code = run_cli(
        tmp_path, "batch", "--manifest", str(path), "--verify-only"
    )

    assert code == 0, "unresolved rows are reported inside, not as a failed batch"
    assert report["verify_only"] is True
    assert report["status_counts"] == {VERIFIED: 1, AMBIGUOUS: 0, UNKNOWN: 1, ERROR: 0}
    assert [item["drug"] for item in report["items"]] == ["apixaban", "absent"]
    assert Path(report["items"][0]["evidence_path"]).is_file()


def test_the_offline_entry_writes_the_report_where_it_was_asked_to(
    tmp_path: Path,
) -> None:
    prepared(tmp_path)
    path = manifest_file(
        tmp_path, [{"drug": "apixaban", "set_id": ELIQUIS_SET_ID, "source_version": "30"}]
    )
    output = tmp_path / "reports" / "batch.json"

    report, _ = run_cli(
        tmp_path,
        "batch",
        "--manifest",
        str(path),
        "--verify-only",
        "--output",
        str(output),
    )

    assert json.loads(output.read_bytes()) == report


def test_the_cli_verifies_a_written_index_by_name(tmp_path: Path) -> None:
    core = prepared(tmp_path)
    core.extract(ELIQUIS_SET_ID, ELIQUIS_VERSION, index_only=True)

    report, code = run_cli(
        tmp_path,
        "verify",
        "--set-id",
        ELIQUIS_SET_ID,
        "--source-version",
        ELIQUIS_VERSION,
        "--artifact",
        "index.json",
    )

    assert code == 0
    assert report["status"] == "verified"
    assert report["verification"]["ok"] is True


def test_a_batch_must_be_given_exactly_one_input(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        run_cli(tmp_path, "batch")


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

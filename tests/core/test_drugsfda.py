"""Offline tests for Drugs@FDA as a second preserved primary source.

The archive fixtures here are built in-process and kept to a handful of rows.
The official distribution is several megabytes and is never committed.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Any

import pytest

from odd.core.drugsfda import (
    DrugsFdaStore,
    extract_application_references,
    find_application,
    read_member_row,
)
from odd.errors import MalformedArchive
from odd.parsers.spl.parser import build_locator_map, parse_document_root
from odd.provenance.hashing import sha256_bytes
from tests.core.test_core_pipeline import ELIQUIS_SET_ID, ELIQUIS_VERSION, ELIQUIS_XML, pipeline

APPLICATIONS_HEADER = "ApplNo\tApplType\tApplPublicNotes\tSponsorName"
ELIQUIS_APPLICATION_ROW = "202155\tNDA\t\tBRISTOL MYERS SQUIBB"


def archive_bytes(
    *,
    applications: tuple[str, ...] = (ELIQUIS_APPLICATION_ROW,),
    include_applications_table: bool = True,
) -> bytes:
    """Build a minimal Drugs@FDA archive with the tables the link path reads."""

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        if include_applications_table:
            archive.writestr(
                "Applications.txt", "\n".join((APPLICATIONS_HEADER, *applications)) + "\n"
            )
        archive.writestr(
            "Products.txt",
            "ApplNo\tProductNo\tForm\tStrength\tReferenceDrug\tDrugName\tActiveIngredient\t"
            "ReferenceStandard\n"
            "202155\t001\tTABLET;ORAL\t2.5MG\t1\tELIQUIS\tAPIXABAN\t0\n",
        )
        archive.writestr(
            "Submissions.txt",
            "ApplNo\tSubmissionClassCodeID\tSubmissionType\tSubmissionNo\tSubmissionStatus\t"
            "SubmissionStatusDate\tSubmissionsPublicNotes\tReviewPriority\n"
            "202155\t2\tSUPPL\t40\tAP\t2025-04-17 00:00:00\t\tPRIORITY\n",
        )
        archive.writestr(
            "MarketingStatus.txt", "MarketingStatusID\tApplNo\tProductNo\n1\t202155\t001\n"
        )
        archive.writestr(
            "MarketingStatus_Lookup.txt",
            "MarketingStatusID\tMarketingStatusDescription\n1\tPrescription\n",
        )
    return buffer.getvalue()


def stored_archive(tmp_path: Path, body: bytes) -> tuple[Path, str]:
    store = DrugsFdaStore(tmp_path / "data" / "raw")
    snapshot = store.store(body, {"requested_url": "https://www.fda.gov/media/0/download"})
    return snapshot.archive_path, snapshot.sha256


def spl_with_application(application_number: str = "NDA202155") -> bytes:
    """The SPL fixture plus the approval fragment a real label carries.

    The committed fixture is a trimmed label with no approval element, so the
    application identifier is supplied here as a small fragment rather than by
    committing a full multi-megabyte label.
    """

    text = ELIQUIS_XML.read_text(encoding="utf-8")
    approval = (
        "<subjectOf><approval>"
        f'<id extension="{application_number}" root="2.16.840.1.113883.3.150"/>'
        '<code code="C73594" codeSystem="2.16.840.1.113883.3.26.1.1" displayName="NDA"/>'
        "</approval></subjectOf>"
    )
    return text.replace("</manufacturedProduct>", approval + "</manufacturedProduct>", 1).encode(
        "utf-8"
    )


def eliquis_reference() -> Any:
    root = parse_document_root(spl_with_application())
    return extract_application_references(root, build_locator_map(root))[0]


def install_fixture_archive(monkeypatch: pytest.MonkeyPatch, body: bytes) -> None:
    """Serve a fixture archive in place of the official FDA download."""

    monkeypatch.setattr(
        "odd.core.pipeline.resolve_download",
        lambda: {
            "data_last_updated": "January 1st, 2026",
            "download_url": "https://www.fda.gov/media/0/download",
            "landing_page_raw_sha256": sha256_bytes(b"landing"),
            "landing_page_retrieved_at": "2026-01-01T00:00:00Z",
            "landing_page_status": 200,
            "landing_page_url": "https://www.fda.gov/drugs/x",
        },
    )
    monkeypatch.setattr(
        "odd.core.pipeline.retrieve_archive",
        lambda plan: (body, {**plan, "retrieved_at": "2026-01-01T00:00:01Z"}),
    )


def test_every_position_stating_the_same_application_number_is_kept() -> None:
    """A label states its application number once per product; none may be dropped."""

    text = ELIQUIS_XML.read_text(encoding="utf-8")
    approval = (
        "<subjectOf><approval>"
        '<id extension="ANDA213853" root="2.16.840.1.113883.3.150"/>'
        "</approval></subjectOf>"
    )
    # The same value stated at two separate positions in the document.
    body = text.replace(
        "</manufacturedProduct>", approval + "</manufacturedProduct>", 2
    ).encode("utf-8")
    root = parse_document_root(body)

    references = extract_application_references(root, build_locator_map(root))

    assert len(references) == 1, "one value stated twice is still one application number"
    reference = references[0]
    assert len(reference.occurrences) == 2
    assert len({item.xml_locator for item in reference.occurrences}) == 2
    assert reference.as_dict()["occurrence_count"] == 2
    assert len(reference.as_dict()["occurrences"]) == 2


def test_the_application_number_is_read_from_the_spl_with_its_position() -> None:
    reference = eliquis_reference()

    assert reference.application_number == "NDA202155"
    assert reference.application_type == "NDA"
    assert reference.numeric_key == "202155"
    assert reference.xml_locator.startswith("/document[1]/")
    assert reference.xml_locator.endswith("/approval[1]/id[1]")
    assert 'extension="NDA202155"' in reference.evidence_xml
    assert len(reference.evidence_sha256) == 64


def test_one_exactly_matching_application_is_reported_as_exact(tmp_path: Path) -> None:
    path, digest = stored_archive(tmp_path, archive_bytes())

    result = find_application(
        path, eliquis_reference(), archive_sha256=digest, archive_raw_path="raw/a.zip"
    )

    assert result.status == "EXACT"
    assert result.facts["sponsor_name"] == "BRISTOL MYERS SQUIBB"
    assert result.facts["products"][0]["marketing_status"] == "Prescription"
    assert {row["table_name"] for row in result.rows} == {
        "Applications.txt",
        "Products.txt",
        "Submissions.txt",
    }


def test_two_matching_rows_are_not_narrowed_to_one(tmp_path: Path) -> None:
    """Ambiguity in the source is reported, never resolved by ODD."""

    path, digest = stored_archive(
        tmp_path,
        archive_bytes(
            applications=(ELIQUIS_APPLICATION_ROW, "202155\tNDA\t\tA DIFFERENT SPONSOR")
        ),
    )

    result = find_application(
        path, eliquis_reference(), archive_sha256=digest, archive_raw_path="raw/a.zip"
    )

    assert result.status == "MULTIPLE"
    assert len(result.rows) == 2
    assert result.facts == {}, "no product facts may be asserted while the match is ambiguous"


def test_not_found_is_returned_only_after_every_row_was_read(tmp_path: Path) -> None:
    path, digest = stored_archive(
        tmp_path, archive_bytes(applications=("000004\tNDA\t\tPHARMICS",))
    )

    result = find_application(
        path, eliquis_reference(), archive_sha256=digest, archive_raw_path="raw/a.zip"
    )

    assert result.status == "NOT_FOUND"
    assert "every row" in (result.diagnostic or "")


def test_an_archive_that_cannot_be_read_completely_is_unknown(tmp_path: Path) -> None:
    """An archive we could not read is not an archive that lacks the application."""

    broken = tmp_path / "broken.zip"
    broken.write_bytes(b"this is not a zip file")

    result = find_application(
        broken, eliquis_reference(), archive_sha256="0" * 64, archive_raw_path="raw/a.zip"
    )

    assert result.status == "UNKNOWN"
    assert result.rows == ()


def test_a_missing_applications_table_is_unknown_not_absence(tmp_path: Path) -> None:
    path, digest = stored_archive(tmp_path, archive_bytes(include_applications_table=False))

    result = find_application(
        path, eliquis_reference(), archive_sha256=digest, archive_raw_path="raw/a.zip"
    )

    assert result.status == "UNKNOWN"


def test_a_recorded_row_re_reads_to_the_same_bytes(tmp_path: Path) -> None:
    path, digest = stored_archive(tmp_path, archive_bytes())
    result = find_application(
        path, eliquis_reference(), archive_sha256=digest, archive_raw_path="raw/a.zip"
    )
    row = next(item for item in result.rows if item["table_name"] == "Applications.txt")

    text = read_member_row(path, row["zip_member"], row["row_number"])

    assert text == row["row_raw_text"] == ELIQUIS_APPLICATION_ROW
    assert sha256_bytes(text.encode("utf-8")) == row["row_sha256"]


def test_a_row_number_past_the_end_is_an_error_not_an_empty_answer(tmp_path: Path) -> None:
    path, _ = stored_archive(tmp_path, archive_bytes())

    with pytest.raises(MalformedArchive):
        read_member_row(path, "Applications.txt", 9999)


def test_a_second_archive_becomes_a_new_snapshot_and_never_overwrites(
    tmp_path: Path,
) -> None:
    store = DrugsFdaStore(tmp_path / "data" / "raw")
    first = store.store(archive_bytes(), {"requested_url": "https://www.fda.gov/media/0/download"})
    changed = archive_bytes(applications=("202155\tNDA\t\tRENAMED SPONSOR",))

    second = store.store(changed, {"requested_url": "https://www.fda.gov/media/0/download"})
    again = store.store(archive_bytes(), {"requested_url": "https://www.fda.gov/media/0/download"})

    assert second.sha256 != first.sha256
    assert second.archive_path != first.archive_path
    assert first.archive_path.read_bytes() == archive_bytes(), "the old snapshot must survive"
    assert again.already_stored is True
    assert again.archive_path == first.archive_path


def test_the_whole_path_carries_both_primary_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fixture_archive(monkeypatch, archive_bytes())
    core = pipeline(tmp_path, xml_body=spl_with_application())
    core.acquire("Eliquis", set_id=ELIQUIS_SET_ID)

    payload = core.extract(ELIQUIS_SET_ID, ELIQUIS_VERSION, include_drugsfda=True).payload
    report = core.verify(payload)

    assert report.ok is True
    assert report.failures == ()
    names = {check.name for check in report.checks}
    assert {"regulatory_archive_sha256", "regulatory_row_evidence", "regulatory_link_status"} <= (
        names
    )

    source = payload["regulatory_sources"][0]
    assert source["authority"] == "FDA"
    assert source["repository"] == "Drugs@FDA"
    assert source["application_number"] == "NDA202155"
    assert source["link"]["status"] == "EXACT"
    # The two primary sources keep their own bytes and their own hashes.
    assert source["archive"]["raw_sha256"] != payload["label_source"]["raw_sha256"]
    # FDA data never rewrites the label.
    assert payload["label_source"]["fda_approval_status"] == "UNKNOWN"


def test_a_dailymed_only_run_carries_no_regulatory_source(tmp_path: Path) -> None:
    core = pipeline(tmp_path)
    core.acquire("Eliquis", set_id=ELIQUIS_SET_ID)

    payload = core.extract(ELIQUIS_SET_ID, ELIQUIS_VERSION).payload

    assert payload["regulatory_sources"] == []
    assert core.verify(payload).ok is True


def test_an_altered_archive_row_fails_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fixture_archive(monkeypatch, archive_bytes())
    core = pipeline(tmp_path, xml_body=spl_with_application())
    core.acquire("Eliquis", set_id=ELIQUIS_SET_ID)
    payload = core.extract(ELIQUIS_SET_ID, ELIQUIS_VERSION, include_drugsfda=True).payload

    archive_path = core.data_root / payload["regulatory_sources"][0]["archive"]["raw_path"]
    archive_path.write_bytes(archive_bytes(applications=("202155\tNDA\t\tSOMEONE ELSE",)))

    report = core.verify(payload)

    assert report.ok is False
    failed = [check.name for check in report.checks if not check.ok]
    assert "regulatory_archive_sha256" in failed


def test_an_edited_fda_row_in_the_bundle_fails_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fixture_archive(monkeypatch, archive_bytes())
    core = pipeline(tmp_path, xml_body=spl_with_application())
    core.acquire("Eliquis", set_id=ELIQUIS_SET_ID)
    payload = core.extract(ELIQUIS_SET_ID, ELIQUIS_VERSION, include_drugsfda=True).payload

    rows = payload["regulatory_sources"][0]["link"]["fda_evidence"]["rows"]
    rows[0]["row_raw_text"] = "202155\tNDA\t\tA SPONSOR FDA NEVER RECORDED"

    report = core.verify(payload)

    assert report.ok is False
    assert any("row" in str(item.get("reason", "")) for item in report.failures)

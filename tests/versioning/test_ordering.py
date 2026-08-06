from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

from odd.models import (
    DailyMedHistoryEntry,
    DiffDocumentProvenance,
    OrderingStatus,
    StoredDocumentVersion,
)
from odd.versioning import determine_version_order


def _document(
    document_id: str,
    version: str,
    *,
    effective: date | None,
    published: date | None,
    retrieved: datetime,
) -> StoredDocumentVersion:
    provenance = DiffDocumentProvenance(
        authority="FDA",
        provider="DailyMed",
        jurisdiction="United States",
        source_document_id="set-id",
        source_version=version,
        source_instance_id=document_id,
        effective_date=effective,
        publication_date=published,
        publication_date_source="DAILYMED_HISTORY" if published else None,
        retrieved_at=retrieved,
        raw_sha256=("a" if version == "29" else "b") * 64,
        raw_path=f"{version}.xml",
        parser_version="parser/1",
        schema_version="schema/1",
        mapping_version="mapping/1",
    )
    return StoredDocumentVersion(
        document_id=document_id,
        provenance=provenance,
        document_type="LABEL",
        language="en-US",
        title="Title",
        generic_name="apixaban",
        brand_names=("ELIQUIS",),
        dosage_forms=(),
        routes=(),
        active_ingredients=("APIXABAN",),
        normalized_sha256=version * 32,
        ingestion_metadata_sha256=document_id * 4,
        sections=(),
    )


NOW = datetime(2025, 1, 1, tzinfo=UTC)


def _history(*versions: str) -> tuple[DailyMedHistoryEntry, ...]:
    return tuple(
        DailyMedHistoryEntry(version, None, "unknown", index)
        for index, version in enumerate(versions)
    )


def test_official_adjacent_versions_are_known_predecessor_and_successor() -> None:
    old = _document(
        "old", "29", effective=date(2021, 9, 30), published=date(2023, 1, 30), retrieved=NOW
    )
    new = _document(
        "new",
        "30",
        effective=date(2025, 4, 17),
        published=date(2025, 5, 5),
        retrieved=NOW + timedelta(days=1),
    )
    ordering = determine_version_order(
        old,
        new,
        history_entries=_history("30", "29", "28"),
        history_snapshot_id="history-1",
    )

    assert ordering.status == OrderingStatus.SOURCE_VERSION_ORDERED
    assert ordering.known_predecessor is True
    assert ordering.known_successor is True
    assert ordering.intermediate_versions_possible is False
    assert ordering.missing_source_versions == ()


def test_consecutive_numbers_without_official_history_do_not_prove_continuity() -> None:
    old = _document("old", "29", effective=None, published=None, retrieved=NOW)
    new = _document("new", "30", effective=None, published=None, retrieved=NOW)
    ordering = determine_version_order(old, new)

    assert ordering.status == OrderingStatus.SOURCE_VERSION_ORDERED
    assert ordering.known_predecessor is False
    assert ordering.intermediate_versions_possible is True


def test_official_history_exposes_known_intermediate_versions() -> None:
    old = _document("old", "28", effective=None, published=None, retrieved=NOW)
    new = _document("new", "30", effective=None, published=None, retrieved=NOW)
    ordering = determine_version_order(old, new, history_entries=_history("30", "29", "28"))

    assert ordering.missing_source_versions == ("29",)
    assert ordering.intermediate_versions_possible is True
    assert ordering.known_predecessor is False


def test_source_version_and_effective_date_disagreement_is_a_conflict() -> None:
    old = _document("old", "29", effective=date(2025, 1, 1), published=None, retrieved=NOW)
    new = _document("new", "30", effective=date(2024, 1, 1), published=None, retrieved=NOW)
    ordering = determine_version_order(old, new)

    assert ordering.status == OrderingStatus.ORDER_CONFLICT
    assert ordering.predecessor_document_id is None


def test_effective_date_orders_non_numeric_versions() -> None:
    old = _document("old", "draft-a", effective=date(2024, 1, 1), published=None, retrieved=NOW)
    new = _document("new", "draft-b", effective=date(2025, 1, 1), published=None, retrieved=NOW)

    assert determine_version_order(old, new).status == OrderingStatus.EFFECTIVE_DATE_ORDERED


def test_publication_date_is_used_when_other_source_order_is_unavailable() -> None:
    old = _document("old", "a", effective=None, published=date(2024, 1, 1), retrieved=NOW)
    new = _document("new", "b", effective=None, published=date(2025, 1, 1), retrieved=NOW)

    assert determine_version_order(old, new).status == OrderingStatus.PUBLICATION_DATE_ORDERED


def test_ingestion_order_is_explicitly_low_confidence() -> None:
    old = _document("old", "same", effective=None, published=None, retrieved=NOW)
    new = replace(
        _document("new", "same", effective=None, published=None, retrieved=NOW),
        provenance=replace(
            old.provenance, retrieved_at=NOW + timedelta(days=1), source_instance_id="new"
        ),
    )
    ordering = determine_version_order(old, new)

    assert ordering.status == OrderingStatus.INGESTION_ORDER_ONLY
    assert ordering.intermediate_versions_possible is True


def test_equal_ordering_fields_are_undetermined() -> None:
    document = _document("same", "same", effective=None, published=None, retrieved=NOW)
    assert determine_version_order(document, document).status == OrderingStatus.ORDER_UNDETERMINED


def test_reverse_requested_direction_is_not_silently_reordered() -> None:
    old = _document("old", "30", effective=None, published=None, retrieved=NOW)
    new = _document("new", "29", effective=None, published=None, retrieved=NOW)
    assert determine_version_order(old, new).status == OrderingStatus.ORDER_CONFLICT

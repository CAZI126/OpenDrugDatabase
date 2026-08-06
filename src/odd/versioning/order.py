"""Deterministic ordering without pretending ingestion order proves continuity."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime

from odd.models import (
    DailyMedHistoryEntry,
    OrderingStatus,
    StoredDocumentVersion,
    VersionOrdering,
)


def determine_version_order(
    old: StoredDocumentVersion | None,
    new: StoredDocumentVersion | None,
    *,
    history_entries: Sequence[DailyMedHistoryEntry] = (),
    history_snapshot_id: str | None = None,
) -> VersionOrdering:
    """Describe how the requested old-to-new direction is supported.

    A negative comparison means the supplied ``old`` value precedes ``new``.
    Source/version dates participate in conflict detection; retrieval time is
    used only when no source-owned ordering signal is available.
    """

    if old is None or new is None:
        return _undetermined(history_snapshot_id)

    source_direction = _version_direction(
        old.provenance.source_version, new.provenance.source_version
    )
    history_direction, known_adjacent, missing = _history_direction(
        old.provenance.source_version,
        new.provenance.source_version,
        history_entries,
    )
    effective_direction = _value_direction(
        old.provenance.effective_date, new.provenance.effective_date
    )
    publication_direction = _value_direction(
        old.provenance.publication_date, new.provenance.publication_date
    )

    source_signals = [
        item
        for item in (
            source_direction,
            history_direction,
            effective_direction,
            publication_direction,
        )
        if item not in {None, 0}
    ]
    if source_signals and (1 in source_signals or len(set(source_signals)) > 1):
        return VersionOrdering(
            status=OrderingStatus.ORDER_CONFLICT,
            ordering_source="conflicting_source_fields",
            confidence_status="CONFLICT",
            predecessor_document_id=None,
            successor_document_id=None,
            known_predecessor=False,
            known_successor=False,
            intermediate_versions_possible=True,
            missing_source_versions=missing,
            history_snapshot_id=history_snapshot_id,
        )

    if source_direction == -1 or history_direction == -1:
        signal_count = len(source_signals)
        if known_adjacent:
            confidence = "AUTHORITATIVE_HISTORY_ADJACENT"
        elif history_direction == -1:
            confidence = "AUTHORITATIVE_HISTORY_WITH_INTERMEDIATES"
        elif signal_count > 1:
            confidence = "MULTIPLE_SOURCE_FIELDS_AGREE"
        else:
            confidence = "SOURCE_VERSION_ONLY"
        return _ordered(
            old,
            new,
            status=OrderingStatus.SOURCE_VERSION_ORDERED,
            source="dailymed_history" if history_direction == -1 else "source_version",
            confidence=confidence,
            known_adjacent=known_adjacent,
            possible=not known_adjacent,
            missing=missing,
            history_snapshot_id=history_snapshot_id,
        )

    if effective_direction == -1:
        return _ordered(
            old,
            new,
            status=OrderingStatus.EFFECTIVE_DATE_ORDERED,
            source="effective_date",
            confidence="DATE_ONLY" if publication_direction in {None, 0} else "DATES_AGREE",
            known_adjacent=known_adjacent,
            possible=not known_adjacent,
            missing=missing,
            history_snapshot_id=history_snapshot_id,
        )

    if publication_direction == -1:
        return _ordered(
            old,
            new,
            status=OrderingStatus.PUBLICATION_DATE_ORDERED,
            source="publication_date",
            confidence="DATE_ONLY",
            known_adjacent=known_adjacent,
            possible=not known_adjacent,
            missing=missing,
            history_snapshot_id=history_snapshot_id,
        )

    ingestion_direction = _value_direction(
        old.provenance.retrieved_at, new.provenance.retrieved_at
    )
    if ingestion_direction == -1:
        return _ordered(
            old,
            new,
            status=OrderingStatus.INGESTION_ORDER_ONLY,
            source="retrieved_at",
            confidence="INGESTION_METADATA_ONLY",
            known_adjacent=False,
            possible=True,
            missing=(),
            history_snapshot_id=history_snapshot_id,
        )
    if ingestion_direction == 1:
        return VersionOrdering(
            status=OrderingStatus.ORDER_CONFLICT,
            ordering_source="retrieved_at",
            confidence_status="INGESTION_DIRECTION_CONFLICT",
            predecessor_document_id=None,
            successor_document_id=None,
            known_predecessor=False,
            known_successor=False,
            intermediate_versions_possible=True,
            missing_source_versions=(),
            history_snapshot_id=history_snapshot_id,
        )
    return _undetermined(history_snapshot_id)


def _ordered(
    old: StoredDocumentVersion,
    new: StoredDocumentVersion,
    *,
    status: OrderingStatus,
    source: str,
    confidence: str,
    known_adjacent: bool,
    possible: bool,
    missing: tuple[str, ...],
    history_snapshot_id: str | None,
) -> VersionOrdering:
    return VersionOrdering(
        status=status,
        ordering_source=source,
        confidence_status=confidence,
        predecessor_document_id=old.document_id,
        successor_document_id=new.document_id,
        known_predecessor=known_adjacent,
        known_successor=known_adjacent,
        intermediate_versions_possible=possible,
        missing_source_versions=missing,
        history_snapshot_id=history_snapshot_id,
    )


def _undetermined(history_snapshot_id: str | None) -> VersionOrdering:
    return VersionOrdering(
        status=OrderingStatus.ORDER_UNDETERMINED,
        ordering_source="none",
        confidence_status="UNDETERMINED",
        predecessor_document_id=None,
        successor_document_id=None,
        known_predecessor=False,
        known_successor=False,
        intermediate_versions_possible=True,
        missing_source_versions=(),
        history_snapshot_id=history_snapshot_id,
    )


def _version_direction(old: str, new: str) -> int | None:
    if old == new:
        return 0
    if old.isdecimal() and new.isdecimal():
        old_number = int(old)
        new_number = int(new)
        if old_number < new_number:
            return -1
        if old_number > new_number:
            return 1
        return 0
    return None


def _history_direction(
    old_version: str,
    new_version: str,
    entries: Sequence[DailyMedHistoryEntry],
) -> tuple[int | None, bool, tuple[str, ...]]:
    positions = {entry.source_version: index for index, entry in enumerate(entries)}
    if old_version not in positions or new_version not in positions:
        return None, False, ()
    old_position = positions[old_version]
    new_position = positions[new_version]
    if old_position == new_position:
        return 0, False, ()
    # DailyMed history is newest first, so an older version has the larger index.
    direction = -1 if old_position > new_position else 1
    lower = min(old_position, new_position)
    upper = max(old_position, new_position)
    missing = tuple(entry.source_version for entry in entries[lower + 1 : upper])
    return direction, upper - lower == 1 and direction == -1, missing


def _value_direction(old: date | datetime | None, new: date | datetime | None) -> int | None:
    if old is None or new is None:
        return None
    if type(old) is not type(new):
        return None
    old_value = old.isoformat()
    new_value = new.isoformat()
    if old_value < new_value:
        return -1
    if old_value > new_value:
        return 1
    return 0

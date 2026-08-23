"""Run the existing single-document path over a caller-supplied list of identities.

This is a conveyor, not a selector. The identities come from the caller, in the
caller's order; ODD adds none, drops none, reorders none, and ranks none. Each
one goes through exactly the same path a single document goes through, and one
identity failing does not stop the ones after it.

``verified`` here is a statement about custody, not about medicine: the official
document for that identity was resolved, its bytes hashed to the value on
record, its sections extracted, its index built, and the preserved bytes are
still reachable. Anything that cannot be established is reported as it stands --
``ambiguous`` when the stored identity resolves to more than one document,
``unknown`` when it could not be observed at all, ``error`` when the attempt
itself failed. Nothing is promoted to ``verified`` by assumption.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from odd.core.selective import COMPLETE
from odd.errors import AmbiguousSourceSelection, ODDError, SourceNotFound
from odd.provenance.hashing import sha256_file

if TYPE_CHECKING:
    from odd.core.pipeline import CorePipeline

VERIFIED = "verified"
AMBIGUOUS = "ambiguous"
UNKNOWN = "unknown"
ERROR = "error"

# Stable, machine-checkable reasons. These describe what was observed, not what
# ODD concluded about the product.
BLANK_SET_ID = "BLANK_SET_ID"
NOT_PRESERVED_LOCALLY = "NOT_PRESERVED_LOCALLY"
AMBIGUOUS_STORED_VERSION = "AMBIGUOUS_STORED_VERSION"
AMBIGUOUS_OFFICIAL_CANDIDATES = "AMBIGUOUS_OFFICIAL_CANDIDATES"
INCOMPLETE_LISTING = "INCOMPLETE_LISTING"
EMPTY_SECTION_INDEX = "EMPTY_SECTION_INDEX"
INCOMPLETE_SECTION_INDEX = "INCOMPLETE_SECTION_INDEX"
RAW_UNREACHABLE = "RAW_UNREACHABLE"

__all__ = [
    "AMBIGUOUS",
    "ERROR",
    "UNKNOWN",
    "VERIFIED",
    "read_set_id_file",
    "run_batch",
]


@dataclass(frozen=True, slots=True)
class BatchItem:
    """One identity's outcome, in the order it was supplied."""

    set_id: str
    status: str
    source_url: str | None = None
    raw_sha256: str | None = None
    index_status: str | None = None
    section_count: int = 0
    error_code: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "error_code": self.error_code,
            "index_status": self.index_status,
            "raw_sha256": self.raw_sha256,
            "section_count": self.section_count,
            "set_id": self.set_id,
            "source_url": self.source_url,
            "status": self.status,
        }


def read_set_id_file(path: Path) -> list[str]:
    """Read one identity per line, keeping the caller's order.

    Blank lines are skipped. Nothing else is interpreted: no comments, no
    columns, no manifest format. A line is an identity or it is a problem to
    report against that line.
    """

    text = Path(path).read_text(encoding="utf-8")
    return [line.strip() for line in text.splitlines() if line.strip()]


def run_batch(
    pipeline: CorePipeline,
    set_ids: Sequence[str],
    *,
    drug: str | None = None,
    include_drugsfda: bool = False,
) -> dict[str, Any]:
    """Put every supplied identity through the single-document path, in order."""

    items: list[BatchItem] = []
    seen: set[str] = set()
    duplicates = 0
    for raw_set_id in set_ids:
        key = raw_set_id.strip().casefold()
        if not key:
            items.append(
                BatchItem(set_id=raw_set_id, status=ERROR, error_code=BLANK_SET_ID)
            )
            continue
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        items.append(
            _run_one(
                pipeline,
                raw_set_id.strip(),
                drug=drug,
                include_drugsfda=include_drugsfda,
            )
        )
    counts = {name: 0 for name in (VERIFIED, AMBIGUOUS, UNKNOWN, ERROR)}
    for item in items:
        counts[item.status] += 1
    return {
        "duplicates_ignored": duplicates,
        "items": [item.as_dict() for item in items],
        "total": len(items),
        **counts,
    }


def _run_one(
    pipeline: CorePipeline,
    set_id: str,
    *,
    drug: str | None,
    include_drugsfda: bool,
) -> BatchItem:
    """One identity through the same calls a single-document run makes."""

    try:
        raw = pipeline.raw_store.resolve(set_id)
    except AmbiguousSourceSelection:
        return BatchItem(
            set_id=set_id, status=AMBIGUOUS, error_code=AMBIGUOUS_STORED_VERSION
        )
    except SourceNotFound:
        if drug is None:
            # Not held locally is not the same as not existing officially.
            return BatchItem(
                set_id=set_id, status=UNKNOWN, error_code=NOT_PRESERVED_LOCALLY
            )
        outcome = _retrieve(pipeline, set_id, drug=drug)
        if isinstance(outcome, BatchItem):
            return outcome
        raw = outcome
    except ODDError as error:
        return BatchItem(set_id=set_id, status=ERROR, error_code=_code(error))

    identity = raw.identity
    try:
        index = pipeline.extract(
            set_id,
            identity.source_version,
            requested_term=drug,
            index_only=True,
            include_drugsfda=include_drugsfda,
        ).payload
    except ODDError as error:
        return BatchItem(
            set_id=identity.source_document_id,
            status=ERROR,
            source_url=identity.source_url,
            raw_sha256=identity.raw_sha256,
            error_code=_code(error),
        )

    document = index["document"]
    index_status = str(index["completeness"]["section_index"])
    section_count = len(index["sections"])
    common = {
        "set_id": identity.source_document_id,
        "source_url": document["official_url"],
        "raw_sha256": identity.raw_sha256,
        "index_status": index_status,
        "section_count": section_count,
    }
    if index_status != COMPLETE:
        return BatchItem(**common, status=UNKNOWN, error_code=INCOMPLETE_SECTION_INDEX)
    if section_count < 1:
        return BatchItem(**common, status=UNKNOWN, error_code=EMPTY_SECTION_INDEX)
    if not _still_reachable(pipeline, document):
        return BatchItem(**common, status=ERROR, error_code=RAW_UNREACHABLE)
    return BatchItem(**common, status=VERIFIED)


def _retrieve(pipeline: CorePipeline, set_id: str, *, drug: str) -> Any:
    """Fall back to the official retrieval the caller already has, unchanged."""

    try:
        acquisition = pipeline.acquire(drug, set_id=set_id)
    except SourceNotFound:
        return BatchItem(set_id=set_id, status=UNKNOWN, error_code=NOT_PRESERVED_LOCALLY)
    except ODDError as error:
        return BatchItem(set_id=set_id, status=ERROR, error_code=_code(error))
    if acquisition.raw is None:
        return BatchItem(
            set_id=set_id,
            status=AMBIGUOUS if acquisition.ambiguous else UNKNOWN,
            error_code=(
                AMBIGUOUS_OFFICIAL_CANDIDATES
                if acquisition.ambiguous
                else INCOMPLETE_LISTING
            ),
        )
    return acquisition.raw


def _still_reachable(pipeline: CorePipeline, document: dict[str, Any]) -> bool:
    """Confirm the preserved bytes the index points at are still there and unchanged."""

    try:
        path = pipeline.data_root / str(document["raw_path"])
        return path.is_file() and sha256_file(path) == document["raw_sha256"]
    except (OSError, KeyError, TypeError):
        return False


def _code(error: ODDError) -> str:
    return error.category.value.upper()

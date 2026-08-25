"""Run the existing single-document path over a caller-supplied list of identities.

This is a conveyor, not a selector. The identities come from the caller, in the
caller's order; ODD adds none, drops none, reorders none, and ranks none. Each
one goes through exactly the same path a single document goes through, and one
identity failing does not stop the ones after it.

The caller states each document as ``drug``, ``set_id``, and ``source_version``
in a manifest it writes itself. All three are the caller's claims: ODD retrieves
the identity, checks it against the official listing exactly, and reports the
mismatch when the version it gets back is not the version that was named. It
never searches for a nearer document, and it never reads the drug name back out
of a set id.

``verified`` here is a statement about custody, not about medicine: the official
document for that identity was resolved, its bytes hashed to the value on
record, its sections extracted, its index built, and the preserved bytes are
still reachable. Anything that cannot be established is reported as it stands --
``ambiguous`` when the stored identity resolves to more than one document,
``unknown`` when it could not be observed at all, ``error`` when the attempt
itself failed. Nothing is promoted to ``verified`` by assumption.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from odd.core.direct import fetch_by_set_id
from odd.core.selective import COMPLETE
from odd.errors import (
    AmbiguousSourceSelection,
    MalformedMetadata,
    ODDError,
    SourceNotFound,
)

if TYPE_CHECKING:
    from odd.core.pipeline import CorePipeline

VERIFIED = "verified"
AMBIGUOUS = "ambiguous"
UNKNOWN = "unknown"
ERROR = "error"

BATCH_MANIFEST_SCHEMA_VERSION = "odd-core-batch-manifest/1.0.0"

# Stable, machine-checkable reasons. These describe what was observed, not what
# ODD concluded about the product.
BLANK_SET_ID = "BLANK_SET_ID"
NOT_PRESERVED_LOCALLY = "NOT_PRESERVED_LOCALLY"
NOT_IN_OFFICIAL_LISTING = "NOT_IN_OFFICIAL_LISTING"
AMBIGUOUS_STORED_VERSION = "AMBIGUOUS_STORED_VERSION"
AMBIGUOUS_OFFICIAL_CANDIDATES = "AMBIGUOUS_OFFICIAL_CANDIDATES"
INCOMPLETE_LISTING = "INCOMPLETE_LISTING"
EMPTY_SECTION_INDEX = "EMPTY_SECTION_INDEX"
INCOMPLETE_SECTION_INDEX = "INCOMPLETE_SECTION_INDEX"
INDEX_VERIFICATION_FAILED = "INDEX_VERIFICATION_FAILED"
STORED_VERSION_DIFFERS = "STORED_VERSION_DIFFERS"

__all__ = [
    "AMBIGUOUS",
    "BATCH_MANIFEST_SCHEMA_VERSION",
    "ERROR",
    "UNKNOWN",
    "VERIFIED",
    "ManifestEntry",
    "read_manifest",
    "read_set_id_file",
    "run_batch",
]


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    """One document the caller named, exactly as the caller named it.

    ``drug`` is a label the caller attached to this row so it can read its own
    report. ODD neither derives it from the identity nor checks the document
    against it: the identity is what is retrieved, and the identity alone.
    """

    set_id: str
    drug: str | None = None
    source_version: str | None = None


@dataclass(frozen=True, slots=True)
class BatchItem:
    """One identity's outcome, in the order it was supplied."""

    set_id: str
    status: str
    drug: str | None = None
    requested_source_version: str | None = None
    source_version: str | None = None
    source_url: str | None = None
    raw_sha256: str | None = None
    index_status: str | None = None
    section_count: int = 0
    evidence_path: str | None = None
    error_code: str | None = None
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "drug": self.drug,
            "error": self.error,
            "error_code": self.error_code,
            "evidence_path": self.evidence_path,
            "index_status": self.index_status,
            "raw_sha256": self.raw_sha256,
            "requested_source_version": self.requested_source_version,
            "section_count": self.section_count,
            "set_id": self.set_id,
            "source_url": self.source_url,
            "source_version": self.source_version,
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


def read_manifest(path: Path) -> list[ManifestEntry]:
    """Read a caller-written manifest of documents to convey, in its own order.

    The manifest is input, not output: ODD does not write it, does not rank it,
    and does not add to it. Every row must name the ``set_id`` it means; ``drug``
    and ``source_version`` are the caller's own statements about that row.
    """

    try:
        decoded = json.loads(Path(path).read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MalformedMetadata(
            "batch manifest is not readable UTF-8 JSON", details={"manifest_path": str(path)}
        ) from exc
    if not isinstance(decoded, dict) or not isinstance(decoded.get("items"), list):
        raise MalformedMetadata(
            "batch manifest must be a JSON object carrying an items array",
            details={"manifest_path": str(path)},
        )
    entries: list[ManifestEntry] = []
    for position, item in enumerate(decoded["items"]):
        if not isinstance(item, dict):
            raise MalformedMetadata(
                "batch manifest item must be an object", details={"item_index": position}
            )
        set_id = str(item.get("set_id", "")).strip()
        if not set_id:
            raise MalformedMetadata(
                "batch manifest item names no set_id", details={"item_index": position}
            )
        version = item.get("source_version")
        drug = item.get("drug")
        entries.append(
            ManifestEntry(
                set_id=set_id,
                drug=str(drug).strip() if drug not in (None, "") else None,
                source_version=(
                    str(version).strip() if version not in (None, "") else None
                ),
            )
        )
    return entries


def run_batch(
    pipeline: CorePipeline,
    identities: Sequence[str | ManifestEntry],
    *,
    drug: str | None = None,
    include_drugsfda: bool = False,
    fetch_missing_by_set_id: bool = False,
    verify_only: bool = False,
) -> dict[str, Any]:
    """Put every supplied identity through the single-document path, in order.

    ``verify_only`` reaches nothing off this machine: identities that are not
    already preserved are reported as such rather than retrieved, so a stored
    run can be re-checked with the network unplugged.
    """

    items: list[BatchItem] = []
    seen: set[str] = set()
    duplicates = 0
    for supplied in identities:
        entry = (
            supplied
            if isinstance(supplied, ManifestEntry)
            else ManifestEntry(set_id=supplied, drug=drug)
        )
        key = entry.set_id.strip().casefold()
        if not key:
            items.append(
                BatchItem(
                    set_id=entry.set_id,
                    drug=entry.drug,
                    status=ERROR,
                    error_code=BLANK_SET_ID,
                    error="the manifest row names no set id",
                )
            )
            continue
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        # Each identity is its own attempt. Nothing below may raise past here,
        # or one bad document would cost every document behind it.
        items.append(
            _run_one(
                pipeline,
                entry,
                fallback_drug=drug,
                include_drugsfda=include_drugsfda,
                fetch_missing_by_set_id=fetch_missing_by_set_id,
                verify_only=verify_only,
            )
        )
    counts = {name: 0 for name in (VERIFIED, AMBIGUOUS, UNKNOWN, ERROR)}
    for item in items:
        counts[item.status] += 1
    return {
        "duplicates_ignored": duplicates,
        "items": [item.as_dict() for item in items],
        "status_counts": counts,
        "total": len(items),
        "verify_only": verify_only,
        **counts,
    }


def _run_one(
    pipeline: CorePipeline,
    entry: ManifestEntry,
    *,
    fallback_drug: str | None,
    include_drugsfda: bool,
    fetch_missing_by_set_id: bool = False,
    verify_only: bool = False,
) -> BatchItem:
    """One identity through the same calls a single-document run makes."""

    set_id = entry.set_id.strip()
    drug = entry.drug or fallback_drug
    stated = {
        "set_id": set_id,
        "drug": entry.drug,
        "requested_source_version": entry.source_version,
    }
    try:
        raw = pipeline.raw_store.resolve(set_id, entry.source_version)
    except AmbiguousSourceSelection:
        return BatchItem(
            **stated,
            status=AMBIGUOUS,
            error_code=AMBIGUOUS_STORED_VERSION,
            error="several versions of this identity are stored; name source_version",
        )
    except SourceNotFound:
        if verify_only:
            return BatchItem(
                **stated,
                status=UNKNOWN,
                error_code=NOT_PRESERVED_LOCALLY,
                error="this identity is not preserved locally and nothing was retrieved",
            )
        outcome = _obtain(
            pipeline,
            entry,
            drug=drug,
            stated=stated,
            fetch_missing_by_set_id=fetch_missing_by_set_id,
        )
        if isinstance(outcome, BatchItem):
            return outcome
        raw = outcome
    except ODDError as error:
        return BatchItem(
            **stated, status=ERROR, error_code=_code(error), error=error.message
        )

    identity = raw.identity
    # The caller named a version. A different one coming back is a mismatch to
    # report, never a near enough substitute to convey silently.
    if entry.source_version and identity.source_version != entry.source_version:
        return BatchItem(
            **stated,
            status=UNKNOWN,
            source_version=identity.source_version,
            raw_sha256=identity.raw_sha256,
            error_code=STORED_VERSION_DIFFERS,
            error=(
                f"the caller named version {entry.source_version}; the preserved "
                f"document is version {identity.source_version}"
            ),
        )

    observed = {
        **stated,
        "set_id": identity.source_document_id,
        "source_version": identity.source_version,
        "source_url": identity.source_url,
        "raw_sha256": identity.raw_sha256,
    }
    try:
        result = pipeline.extract(
            set_id,
            identity.source_version,
            requested_term=drug,
            index_only=True,
            include_drugsfda=include_drugsfda,
        )
    except ODDError as error:
        return BatchItem(
            **observed, status=ERROR, error_code=_code(error), error=error.message
        )

    index = result.payload
    index_status = str(index["completeness"]["section_index"])
    section_count = len(index["sections"])
    common = {
        **observed,
        "source_url": index["document"]["official_url"],
        "index_status": index_status,
        "section_count": section_count,
        "evidence_path": str(result.path),
    }
    if index_status != COMPLETE:
        return BatchItem(
            **common,
            status=UNKNOWN,
            error_code=INCOMPLETE_SECTION_INDEX,
            error="the section index could not be shown to be complete",
        )
    if section_count < 1:
        return BatchItem(
            **common,
            status=UNKNOWN,
            error_code=EMPTY_SECTION_INDEX,
            error="the preserved document yielded no sections",
        )
    # Custody, recomputed: every locator in the index is re-resolved against the
    # preserved bytes and re-hashed. Nothing is verified by assertion.
    report = pipeline.verify(index)
    if not report.ok:
        return BatchItem(
            **common,
            status=ERROR,
            error_code=INDEX_VERIFICATION_FAILED,
            error="; ".join(
                check.message for check in report.checks if not check.ok
            )
            or "the index did not re-verify against the preserved source",
        )
    return BatchItem(**common, status=VERIFIED)


def _obtain(
    pipeline: CorePipeline,
    entry: ManifestEntry,
    *,
    drug: str | None,
    stated: dict[str, Any],
    fetch_missing_by_set_id: bool,
) -> Any:
    """Retrieve an identity that is not preserved yet, or say why it was not."""

    if fetch_missing_by_set_id:
        try:
            return fetch_by_set_id(pipeline.connector, pipeline.raw_store, entry.set_id)
        except ODDError as error:
            return BatchItem(
                **stated, status=ERROR, error_code=_code(error), error=error.message
            )
    if drug is None:
        # Not held locally is not the same as not existing officially.
        return BatchItem(
            **stated,
            status=UNKNOWN,
            error_code=NOT_PRESERVED_LOCALLY,
            error="this identity is not preserved locally and no lookup term was given",
        )
    return _retrieve(pipeline, entry, drug=drug, stated=stated)


def _retrieve(
    pipeline: CorePipeline, entry: ManifestEntry, *, drug: str, stated: dict[str, Any]
) -> Any:
    """Fall back to the official retrieval the caller already has, unchanged.

    The named set id and, when the caller named one, the named version must both
    match the official listing exactly. A term that resolves to some other
    document is not a substitute for the one that was asked for.
    """

    try:
        acquisition = pipeline.acquire(
            drug, set_id=entry.set_id, source_version=entry.source_version
        )
    except SourceNotFound as error:
        return BatchItem(
            **stated,
            status=UNKNOWN,
            error_code=NOT_IN_OFFICIAL_LISTING,
            error=error.message,
        )
    except ODDError as error:
        return BatchItem(
            **stated, status=ERROR, error_code=_code(error), error=error.message
        )
    if acquisition.raw is None:
        return BatchItem(
            **stated,
            status=AMBIGUOUS if acquisition.ambiguous else UNKNOWN,
            error_code=(
                AMBIGUOUS_OFFICIAL_CANDIDATES
                if acquisition.ambiguous
                else INCOMPLETE_LISTING
            ),
            error=(
                "more than one official document matched; ODD core does not choose"
                if acquisition.ambiguous
                else "the official listing was not observed completely enough to answer"
            ),
        )
    return acquisition.raw


def _code(error: ODDError) -> str:
    return error.category.value.upper()

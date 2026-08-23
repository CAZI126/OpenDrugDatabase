"""Read the official candidate listing completely, or say that it was not complete.

The official ``/spls.json`` listing is paginated. Reading only the first page
makes ODD report "no candidate matched" when the truth is "I did not look at
all of them", and makes a truncated candidate list look exhaustive. Both are
failures of the core's one job, so the core walks every page the official
response declares and carries the completeness of that walk forward.

No filter, no ranking, and no discarding happens here. Every candidate the
official response returns is kept, in the order it was returned.
"""

from __future__ import annotations

from typing import Any

from odd.connectors.dailymed.client import DailyMedConnector
from odd.errors import MalformedMetadata, NetworkFailure
from odd.models import CandidateLookup, DailyMedCandidate, DiscoveryCompleteness
from odd.provenance.canonical import canonical_json_bytes
from odd.provenance.hashing import sha256_bytes

MAX_LOOKUP_PAGES = 100

__all__ = ["MAX_LOOKUP_PAGES", "paged_lookup"]


def paged_lookup(connector: DailyMedConnector, drug: str) -> CandidateLookup:
    """Retrieve every page of the official candidate listing for ``drug``."""

    first = connector.lookup(drug)
    declared_total = _optional_int(first.payload, "total_elements")
    declared_pages = _optional_int(first.payload, "total_pages")

    candidates: list[DailyMedCandidate] = list(first.candidates)
    page_records: list[dict[str, Any]] = [_page_record(1, first)]
    diagnostic: str | None = None

    last_page = declared_pages if declared_pages is not None else 1
    if last_page > MAX_LOOKUP_PAGES:
        diagnostic = (
            f"the official listing declares {last_page} pages, beyond the "
            f"{MAX_LOOKUP_PAGES}-page limit this retrieval will walk"
        )
        last_page = MAX_LOOKUP_PAGES

    for page_number in range(2, last_page + 1):
        if connector.inter_request_delay_seconds:
            connector.sleep(connector.inter_request_delay_seconds)
        try:
            page = connector.lookup(drug, page=page_number)
        except (NetworkFailure, MalformedMetadata) as exc:
            # A page we could not read is a hole in the observed range, not an
            # empty result. Stop, keep what was actually retrieved, and say so.
            diagnostic = (
                f"page {page_number} of {last_page} could not be retrieved "
                f"({exc.category.value}: {exc.message})"
            )
            break
        candidates.extend(page.candidates)
        page_records.append(_page_record(page_number, page))

    retrieved = len(candidates)
    if declared_total is None or declared_pages is None:
        completeness = DiscoveryCompleteness.UNKNOWN
        diagnostic = diagnostic or "the official listing did not declare its own totals"
    elif diagnostic is not None:
        completeness = DiscoveryCompleteness.INCOMPLETE
    elif retrieved != declared_total:
        completeness = DiscoveryCompleteness.INCOMPLETE
        diagnostic = (
            f"the official listing declares {declared_total} candidate(s) but "
            f"{retrieved} were returned across {len(page_records)} page(s)"
        )
    else:
        completeness = DiscoveryCompleteness.COMPLETE

    merged: dict[str, Any] = {
        "data": [candidate.metadata for candidate in candidates],
        "metadata": {
            "completeness": completeness.value,
            "diagnostic": diagnostic,
            "pages_retrieved": len(page_records),
            "retrieved_elements": retrieved,
            "total_elements": declared_total,
            "total_pages": declared_pages,
        },
        "pages": page_records,
    }
    return CandidateLookup(
        candidates=tuple(candidates),
        source_url=first.source_url,
        retrieved_at=first.retrieved_at,
        raw_body=canonical_json_bytes(merged),
        payload=merged,
        metadata_total_elements=declared_total,
        retrieved_candidate_count=retrieved,
        total_pages=declared_pages,
        completeness=completeness,
        diagnostic_message=diagnostic,
    )


def _page_record(page_number: int, page: CandidateLookup) -> dict[str, Any]:
    return {
        "candidate_count": len(page.candidates),
        "page": page_number,
        "raw_sha256": sha256_bytes(page.raw_body),
        "source_url": page.source_url,
    }


def _optional_int(payload: dict[str, Any], name: str) -> int | None:
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        return None
    value = metadata.get(name)
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    text = str(value).strip()
    if not text.isdecimal():
        return None
    result = int(text)
    if name == "total_pages" and result <= 0:
        raise MalformedMetadata(
            "the official listing declared a non-positive page count",
            details={"total_pages": result},
        )
    return result

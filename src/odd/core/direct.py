"""Retrieve one official document by its identity alone, with no search involved.

Retrieving by set id asks the source for one named document and accepts only
that document. There is no query, so there is no result list, so there is
nothing to pick from and nothing to rank. The drug name is never inferred back
out of the identity.

The version is taken from the document itself rather than from a listing: the
SPL declares its own ``setId`` and ``versionNumber``, and those are the only
identity claims accepted. If the document that comes back declares a different
set id than the one asked for, nothing is stored -- a mismatch is a failure, not
a near miss.

The URL form is the one the existing connector already builds and every
preserved manifest already records; it is not constructed here from guesswork.
"""

from __future__ import annotations

from dataclasses import replace

from odd.connectors.dailymed.client import DailyMedConnector
from odd.constants import CORE_NO_SELECTION_RULE_VERSION
from odd.errors import ProvenanceValidationFailure
from odd.models import (
    CandidateLookup,
    DailyMedCandidate,
    DiscoveryCompleteness,
    RawDocument,
    SelectionDecision,
)
from odd.parsers.spl.parser import Q, parse_document_root
from odd.provenance.canonical import canonical_json_bytes
from odd.provenance.raw_store import RawStore

_DIRECT_DESCRIPTION = (
    "ODD core performed no candidate selection and ran no search. The caller named "
    "one official set id, the source was asked for that document alone, and the "
    "document's own setId and versionNumber were required to match what it claims."
)

__all__ = ["fetch_by_set_id"]


def fetch_by_set_id(
    connector: DailyMedConnector,
    raw_store: RawStore,
    set_id: str,
) -> RawDocument:
    """Ask the official source for one named document and preserve it."""

    requested = set_id.strip()
    if not requested:
        raise ProvenanceValidationFailure("a set id is required to retrieve a document")

    probe = DailyMedCandidate(
        set_id=requested,
        # Unknown until the document states it; never taken from a listing here.
        source_version="",
        title="",
        published_date="",
        metadata={},
    )
    download = connector.download(probe)

    root = parse_document_root(download.body)
    declared_set_id = _attribute(root, "setId", "root")
    declared_version = _attribute(root, "versionNumber", "value")
    if declared_set_id is None or declared_version is None:
        raise ProvenanceValidationFailure(
            "the retrieved document does not declare its own set id and version",
            details={"requested_set_id": requested, "source_url": download.source_url},
        )
    if declared_set_id.casefold() != requested.casefold():
        raise ProvenanceValidationFailure(
            "the retrieved document declares a different set id than the one requested",
            details={
                "declared_set_id": declared_set_id,
                "requested_set_id": requested,
                "source_url": download.source_url,
            },
        )

    identified = replace(
        download, set_id=declared_set_id, source_version=declared_version
    )
    candidate = DailyMedCandidate(
        set_id=declared_set_id,
        source_version=declared_version,
        title="",
        published_date="",
        metadata={
            "retrieval_mode": "direct_set_id",
            "setid": declared_set_id,
            "spl_version": declared_version,
        },
    )
    lookup = CandidateLookup(
        candidates=(candidate,),
        source_url=download.source_url,
        retrieved_at=download.retrieved_at,
        raw_body=canonical_json_bytes(
            {
                "requested_set_id": requested,
                "retrieval_mode": "direct_set_id",
                "source_url": download.source_url,
            }
        ),
        payload={
            "data": [candidate.metadata],
            "metadata": {"retrieval_mode": "direct_set_id"},
        },
        completeness=DiscoveryCompleteness.UNKNOWN,
        retrieved_candidate_count=1,
        diagnostic_message=(
            "retrieved by set id; no search was performed, so no candidate listing exists"
        ),
    )
    decision = SelectionDecision(
        selected=candidate,
        ordered_candidates=(candidate,),
        rule_version=CORE_NO_SELECTION_RULE_VERSION,
        rule_description=_DIRECT_DESCRIPTION,
        reason=(
            f"the caller named set id {declared_set_id}; the document returned declares "
            f"that same set id at version {declared_version}."
        ),
        ambiguity_exposed=False,
    )
    return raw_store.store(identified, lookup, decision)


def _attribute(root: object, child: str, attribute: str) -> str | None:
    element = root.find(f"{Q}{child}")  # type: ignore[attr-defined]
    if element is None:
        return None
    value = element.attrib.get(attribute)
    return value.strip() if value and value.strip() else None

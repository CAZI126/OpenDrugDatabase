"""Explicit deterministic selection for the initial apixaban/Eliquis slice."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from odd.connectors.dailymed.candidates import (
    candidate_payload as candidate_payload,  # re-exported for existing importers
)
from odd.constants import SELECTION_RULE_VERSION
from odd.errors import AmbiguousSourceSelection, SourceNotFound
from odd.models import CandidateLookup, DailyMedCandidate, SelectionDecision

SELECTION_RULE_DESCRIPTION = (
    "Filter titles to the requested active ingredient; prefer titles containing the whole-word "
    "brand ELIQUIS; require one unique DailyMed set_id after that filter; when one set_id has "
    "multiple records, select its highest numeric SPL version, then newest published date."
)


def select_apixaban_candidate(
    lookup: CandidateLookup,
    *,
    active_ingredient: str = "apixaban",
    preferred_brand: str = "Eliquis",
) -> SelectionDecision:
    """Select only when the documented rule resolves to one unique source identity."""

    ordered = tuple(sorted(lookup.candidates, key=_candidate_sort_key))
    if not ordered:
        raise SourceNotFound(
            f"DailyMed returned no candidates for {active_ingredient}",
            details={"candidates": [], "selection_rule": SELECTION_RULE_DESCRIPTION},
        )

    ingredient_matches = tuple(
        item for item in ordered if _contains_term(item.title, active_ingredient)
    )
    if not ingredient_matches:
        raise SourceNotFound(
            f"no candidate title explicitly contained {active_ingredient!r}",
            details={
                "candidates": [_candidate_payload(item) for item in ordered],
                "selection_rule": SELECTION_RULE_DESCRIPTION,
            },
        )

    preferred_matches = tuple(
        item for item in ingredient_matches if _contains_term(item.title, preferred_brand)
    )
    pool = preferred_matches or ingredient_matches
    unique_set_ids = {item.set_id.casefold() for item in pool}
    if len(unique_set_ids) != 1:
        raise AmbiguousSourceSelection(
            "the deterministic DailyMed selection rule did not resolve one unique set_id",
            details={
                "candidate_count": len(ordered),
                "candidates": [_candidate_payload(item) for item in ordered],
                "preferred_match_count": len(preferred_matches),
                "selection_rule": SELECTION_RULE_DESCRIPTION,
                "selection_rule_version": SELECTION_RULE_VERSION,
            },
        )

    selected = pool[0]
    if preferred_matches:
        reason = (
            f"{len(ordered)} candidate(s) were exposed; the preferred-brand and active-ingredient "
            f"filter resolved to the unique set_id {selected.set_id}; selected source version "
            f"{selected.source_version} by the version/date tie-break rule."
        )
    else:
        reason = (
            f"{len(ordered)} candidate(s) were exposed; no preferred-brand title matched, but the "
            f"active-ingredient filter resolved to the unique set_id {selected.set_id}; selected "
            f"source version {selected.source_version} by the version/date tie-break rule."
        )
    return SelectionDecision(
        selected=selected,
        ordered_candidates=ordered,
        rule_version=SELECTION_RULE_VERSION,
        rule_description=SELECTION_RULE_DESCRIPTION,
        reason=reason,
        ambiguity_exposed=len(ordered) > 1,
    )


def _candidate_payload(candidate: DailyMedCandidate) -> dict[str, Any]:
    return candidate_payload(candidate)


def _contains_term(value: str, term: str) -> bool:
    expression = rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])"
    return re.search(expression, value, flags=re.IGNORECASE) is not None


def _candidate_sort_key(candidate: DailyMedCandidate) -> tuple[int, int, str, str]:
    published = _published_ordinal(candidate.published_date)
    version = int(candidate.source_version) if candidate.source_version.isdecimal() else -1
    return (-version, -published, candidate.set_id.casefold(), candidate.title.casefold())


def _published_ordinal(value: str) -> int:
    for format_string in ("%b %d, %Y", "%B %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, format_string).date().toordinal()
        except ValueError:
            continue
    return -1

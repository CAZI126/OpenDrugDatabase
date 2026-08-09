"""Deterministic ODD-005 evidence aggregation and decision revision."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from odd.models import CandidateEvidence, SelectionStatus
from odd.models.enrichment import (
    EnrichmentCompleteness,
    EvidenceAssertion,
    EvidenceResult,
    EvidenceType,
)

_POSITIVE_REQUIRED = (
    EvidenceType.HUMAN_USE,
    EvidenceType.CURRENT,
    EvidenceType.PRESCRIPTION,
    EvidenceType.SINGLE_ACTIVE_INGREDIENT,
    EvidenceType.EXACT_INGREDIENT_IDENTITY,
    EvidenceType.SUPPORTED_DOCUMENT_STRUCTURE,
    EvidenceType.SOURCE_IDENTITY_MATCH,
)
_NEGATIVE_REQUIRED = (
    EvidenceType.COMBINATION_PRODUCT,
    EvidenceType.REPACKAGED_PRODUCT,
    EvidenceType.ARCHIVED,
)


@dataclass(frozen=True, slots=True)
class CandidateEvaluation:
    candidate: CandidateEvidence
    effective_results: tuple[tuple[EvidenceType, EvidenceResult], ...]
    eligible: bool
    proven_ineligible: bool
    unknown: bool
    conflict: bool
    source_drift: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EnrichedSelection:
    completeness: EnrichmentCompleteness
    selection_status: SelectionStatus
    selected_candidate: CandidateEvidence | None
    manual_review_required: bool
    reason: str
    evaluations: tuple[CandidateEvaluation, ...]


def deterministic_candidate_queue(
    candidates: tuple[CandidateEvidence, ...],
) -> tuple[CandidateEvidence, ...]:
    """Order work without using that order as a selection tie-break."""

    return tuple(
        sorted(
            candidates,
            key=lambda value: (
                (value.set_id or "").casefold(),
                _numeric_version(value.source_version),
                value.source_version or "",
                value.raw_metadata_sha256,
                value.candidate_id,
            ),
        )
    )


def evaluate_candidates(
    candidates: tuple[CandidateEvidence, ...],
    assertions: tuple[EvidenceAssertion, ...],
) -> tuple[CandidateEvaluation, ...]:
    by_candidate: dict[str, list[EvidenceAssertion]] = {}
    for assertion in assertions:
        by_candidate.setdefault(assertion.candidate_id, []).append(assertion)
    return tuple(
        _evaluate(candidate, tuple(by_candidate.get(candidate.candidate_id, ())))
        for candidate in deterministic_candidate_queue(candidates)
    )


def revise_selection(
    candidates: tuple[CandidateEvidence, ...],
    assertions: tuple[EvidenceAssertion, ...],
) -> EnrichedSelection:
    evaluations = evaluate_candidates(candidates, assertions)
    if any(item.source_drift for item in evaluations):
        return EnrichedSelection(
            EnrichmentCompleteness.SOURCE_DRIFT,
            SelectionStatus.MANUAL_REVIEW_REQUIRED,
            None,
            True,
            "SOURCE_DRIFT: one or more detail documents do not match the parent set ID and "
            "SPL version; a new discovery observation is required.",
            evaluations,
        )
    if any(item.conflict for item in evaluations):
        return EnrichedSelection(
            EnrichmentCompleteness.CONFLICT,
            SelectionStatus.MANUAL_REVIEW_REQUIRED,
            None,
            True,
            "Official evidence conflicts for one or more candidates; no favorable assertion "
            "was chosen over another.",
            evaluations,
        )
    unresolved = tuple(
        item for item in evaluations if not item.eligible and not item.proven_ineligible
    )
    if unresolved:
        return EnrichedSelection(
            EnrichmentCompleteness.INCOMPLETE,
            SelectionStatus.MANUAL_REVIEW_REQUIRED,
            None,
            True,
            f"ENRICHMENT_INCOMPLETE: {len(unresolved)} candidate(s) retain UNKNOWN required "
            "evidence and could still affect the winner.",
            evaluations,
        )
    eligible = tuple(item.candidate for item in evaluations if item.eligible)
    if not eligible:
        return EnrichedSelection(
            EnrichmentCompleteness.COMPLETE,
            SelectionStatus.NO_ACCEPTABLE_CANDIDATE,
            None,
            False,
            "Every candidate was proven ineligible by retained official evidence.",
            evaluations,
        )
    if any(
        candidate.source_version is None
        or not candidate.source_version.isdecimal()
        or _published_ordinal(candidate.published_date) < 0
        for candidate in eligible
    ):
        return EnrichedSelection(
            EnrichmentCompleteness.INCOMPLETE,
            SelectionStatus.MANUAL_REVIEW_REQUIRED,
            None,
            True,
            "Authoritative numeric source version or publication date is missing from an "
            "otherwise eligible candidate.",
            evaluations,
        )
    best_score = max(_selection_score(candidate) for candidate in eligible)
    winners = tuple(
        candidate for candidate in eligible if _selection_score(candidate) == best_score
    )
    if len(winners) != 1:
        return EnrichedSelection(
            EnrichmentCompleteness.COMPLETE,
            SelectionStatus.MANUAL_REVIEW_REQUIRED,
            None,
            True,
            "Multiple candidates share the authoritative top score; response order and set "
            "ID lexical order were not used as tie-breakers.",
            evaluations,
        )
    winner = winners[0]
    return EnrichedSelection(
        EnrichmentCompleteness.COMPLETE,
        SelectionStatus.SELECTED,
        winner,
        False,
        "All potentially competitive candidates have complete evidence; the unique highest "
        "numeric SPL version and publication date was selected.",
        evaluations,
    )


def effective_result(
    assertions: tuple[EvidenceAssertion, ...], evidence_type: EvidenceType
) -> EvidenceResult:
    values = {
        assertion.result
        for assertion in assertions
        if assertion.evidence_type is evidence_type
        and assertion.result is not EvidenceResult.UNKNOWN
    }
    if EvidenceResult.CONFLICT in values or (
        EvidenceResult.PROVEN_TRUE in values and EvidenceResult.PROVEN_FALSE in values
    ):
        return EvidenceResult.CONFLICT
    if EvidenceResult.PROVEN_TRUE in values:
        return EvidenceResult.PROVEN_TRUE
    if EvidenceResult.PROVEN_FALSE in values:
        return EvidenceResult.PROVEN_FALSE
    return EvidenceResult.UNKNOWN


def _evaluate(
    candidate: CandidateEvidence, assertions: tuple[EvidenceAssertion, ...]
) -> CandidateEvaluation:
    results = tuple(
        (evidence_type, effective_result(assertions, evidence_type))
        for evidence_type in EvidenceType
    )
    lookup = dict(results)
    conflict_types = tuple(
        evidence_type
        for evidence_type, result in results
        if result is EvidenceResult.CONFLICT
    )
    source_drift = lookup[EvidenceType.SOURCE_IDENTITY_MATCH] is EvidenceResult.CONFLICT
    false_positive = tuple(
        evidence_type
        for evidence_type in _POSITIVE_REQUIRED
        if lookup[evidence_type] is EvidenceResult.PROVEN_FALSE
    )
    true_exclusion = tuple(
        evidence_type
        for evidence_type in _NEGATIVE_REQUIRED
        if lookup[evidence_type] is EvidenceResult.PROVEN_TRUE
    )
    proven_ineligible = bool(false_positive or true_exclusion) and not conflict_types
    eligible = not conflict_types and all(
        lookup[value] is EvidenceResult.PROVEN_TRUE for value in _POSITIVE_REQUIRED
    ) and all(lookup[value] is EvidenceResult.PROVEN_FALSE for value in _NEGATIVE_REQUIRED)
    unknown_types = tuple(
        value
        for value in (*_POSITIVE_REQUIRED, *_NEGATIVE_REQUIRED)
        if lookup[value] is EvidenceResult.UNKNOWN
    )
    reasons = (
        *(f"{value.value}=CONFLICT" for value in conflict_types),
        *(f"{value.value}=PROVEN_FALSE" for value in false_positive),
        *(f"{value.value}=PROVEN_TRUE" for value in true_exclusion),
        *(f"{value.value}=UNKNOWN" for value in unknown_types),
    )
    return CandidateEvaluation(
        candidate=candidate,
        effective_results=results,
        eligible=eligible,
        proven_ineligible=proven_ineligible,
        unknown=not eligible and not proven_ineligible and not bool(conflict_types),
        conflict=bool(conflict_types),
        source_drift=source_drift,
        reasons=tuple(reasons),
    )


def _selection_score(candidate: CandidateEvidence) -> tuple[int, int]:
    return _numeric_version(candidate.source_version), _published_ordinal(
        candidate.published_date
    )


def _numeric_version(value: str | None) -> int:
    return int(value) if value and value.isdecimal() else -1


def _published_ordinal(value: str | None) -> int:
    if not value:
        return -1
    for format_string in ("%b %d, %Y", "%B %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, format_string).date().toordinal()
        except ValueError:
            continue
    return -1

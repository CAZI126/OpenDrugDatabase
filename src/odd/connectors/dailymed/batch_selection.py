"""Deterministic, non-clinical DailyMed candidate classification for ODD-003."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any

from odd.constants import (
    BATCH_SELECTION_RULE_VERSION,
    CONNECTOR_VERSION,
    SELECTION_SCOPE,
)
from odd.models import (
    CandidateClassification,
    CandidateEvidence,
    CandidateLookup,
    CandidateSelection,
    DailyMedCandidate,
    IngredientIdentity,
    SelectionStatus,
)
from odd.provenance.canonical import canonical_json_bytes
from odd.provenance.hashing import sha256_bytes
from odd.provenance.identifiers import (
    candidate_decision_id,
    candidate_discovery_id,
    candidate_evidence_id,
)
from odd.utilization import normalize_ingredient_name

SELECTION_RULES = (
    "require explicit human-product metadata",
    "require one exact or deterministically normalized single-active-ingredient match",
    "require a current prescription product",
    "exclude repackaged, archived, non-human, OTC, combination, and unsupported products",
    "prefer exact-name class, then higher numeric source version, then later publication date",
    "treat equal top candidates from different set_ids as unresolved rather than "
    "using response order",
    "sort all evidence by stable identity fields; lexical set_id is presentation order only",
)

_FATAL_CLASSIFICATIONS = {
    CandidateClassification.COMBINATION_PRODUCT,
    CandidateClassification.WRONG_INGREDIENT,
    CandidateClassification.SALT_OR_FORM_VARIANT,
    CandidateClassification.NON_HUMAN_PRODUCT,
    CandidateClassification.OTC_PRODUCT,
    CandidateClassification.REPACKAGED_PRODUCT,
    CandidateClassification.ARCHIVED_OR_INACTIVE,
    CandidateClassification.MISSING_REQUIRED_METADATA,
    CandidateClassification.DUPLICATE_CANDIDATE,
    CandidateClassification.UNSUPPORTED_PRODUCT_TYPE,
    CandidateClassification.AMBIGUOUS,
}

_REASON_BY_CLASSIFICATION = {
    CandidateClassification.COMBINATION_PRODUCT: (
        "combination product is outside one-label single-ingredient validation"
    ),
    CandidateClassification.WRONG_INGREDIENT: (
        "explicit active ingredient does not match the ranked ingredient"
    ),
    CandidateClassification.SALT_OR_FORM_VARIANT: (
        "salt or formulation variant is not treated as chemically equivalent"
    ),
    CandidateClassification.NON_HUMAN_PRODUCT: "non-human product is outside this validation set",
    CandidateClassification.OTC_PRODUCT: "ODD-003 selection policy requires a prescription product",
    CandidateClassification.REPACKAGED_PRODUCT: (
        "repackaged labels are excluded from the validation-label policy"
    ),
    CandidateClassification.ARCHIVED_OR_INACTIVE: (
        "archived or inactive label is not a current validation candidate"
    ),
    CandidateClassification.MISSING_REQUIRED_METADATA: (
        "required non-clinical selection metadata is incomplete"
    ),
    CandidateClassification.DUPLICATE_CANDIDATE: (
        "duplicate source identity is retained but not selected twice"
    ),
    CandidateClassification.UNSUPPORTED_PRODUCT_TYPE: (
        "product type is outside the supported human drug classes"
    ),
    CandidateClassification.AMBIGUOUS: (
        "metadata does not explicitly establish a current or active source status"
    ),
}


def classify_and_select_candidates(
    lookup: CandidateLookup,
    identity: IngredientIdentity,
    *,
    utilization_list_id: str,
    selection_rule_version: str = BATCH_SELECTION_RULE_VERSION,
    connector_version: str = CONNECTOR_VERSION,
) -> CandidateSelection:
    """Classify every result and select only one uniquely highest supported candidate."""

    lookup_sha256 = sha256_bytes(lookup.raw_body)
    discovery_identifier = candidate_discovery_id(
        utilization_list_id,
        identity.ingredient_id,
        connector_version,
        lookup_sha256,
    )
    prepared = []
    for response_index, candidate in enumerate(lookup.candidates):
        metadata_sha256 = sha256_bytes(canonical_json_bytes(candidate.metadata))
        prepared.append((candidate, response_index, metadata_sha256))
    prepared.sort(key=lambda item: _stable_candidate_key(item[0], item[2]))

    seen_sources: dict[tuple[str, str], str] = {}
    evidence: list[CandidateEvidence] = []
    for deterministic_index, (candidate, _response_index, metadata_sha256) in enumerate(prepared):
        identifier = candidate_evidence_id(
            discovery_identifier,
            candidate.set_id,
            candidate.source_version,
            metadata_sha256,
            deterministic_index,
        )
        duplicate_key = (candidate.set_id.casefold(), candidate.source_version)
        duplicate_of = seen_sources.get(duplicate_key)
        classified = _classify_candidate(
            candidate,
            identity,
            candidate_id=identifier,
            discovery_run_id=discovery_identifier,
            response_index=deterministic_index,
            raw_metadata_sha256=metadata_sha256,
            duplicate_of_candidate_id=duplicate_of,
        )
        if duplicate_of is None:
            seen_sources[duplicate_key] = identifier
        evidence.append(classified)

    decision_identifier = candidate_decision_id(discovery_identifier, selection_rule_version)
    if not evidence:
        return CandidateSelection(
            decision_id=decision_identifier,
            discovery_run_id=discovery_identifier,
            ingredient_id=identity.ingredient_id,
            selection_rule_version=selection_rule_version,
            selection_status=SelectionStatus.NO_CANDIDATE,
            selected_candidate_id=None,
            selected_set_id=None,
            selected_source_version=None,
            selection_reason="DailyMed returned no candidates for the normalized search string.",
            applied_rules=SELECTION_RULES,
            manual_review_required=False,
            selection_scope=SELECTION_SCOPE,
            candidates=(),
        )

    acceptable = [item for item in evidence if item.accepted_for_selection]
    if not acceptable:
        return CandidateSelection(
            decision_id=decision_identifier,
            discovery_run_id=discovery_identifier,
            ingredient_id=identity.ingredient_id,
            selection_rule_version=selection_rule_version,
            selection_status=SelectionStatus.NO_ACCEPTABLE_CANDIDATE,
            selected_candidate_id=None,
            selected_set_id=None,
            selected_source_version=None,
            selection_reason=(
                f"{len(evidence)} candidate(s) were retained, but none satisfied all explicit "
                "human/current/prescription/single-ingredient metadata rules."
            ),
            applied_rules=SELECTION_RULES,
            manual_review_required=True,
            selection_scope=SELECTION_SCOPE,
            candidates=tuple(evidence),
        )

    if _lookup_is_truncated(lookup):
        evidence = [
            replace(
                item,
                classifications=_ordered_classifications(
                    (*item.classifications, CandidateClassification.AMBIGUOUS)
                ),
                accepted_for_selection=False,
                rejection_reasons=(
                    *item.rejection_reasons,
                    "DailyMed candidate response is paginated and discovery is incomplete",
                ),
            )
            if item.accepted_for_selection
            else item
            for item in evidence
        ]
        return CandidateSelection(
            decision_id=decision_identifier,
            discovery_run_id=discovery_identifier,
            ingredient_id=identity.ingredient_id,
            selection_rule_version=selection_rule_version,
            selection_status=SelectionStatus.AMBIGUOUS_REQUIRES_REVIEW,
            selected_candidate_id=None,
            selected_set_id=None,
            selected_source_version=None,
            selection_reason=(
                "DailyMed reported more candidates than this preserved response contains; "
                "selection is withheld until pagination is explicitly supported."
            ),
            applied_rules=SELECTION_RULES,
            manual_review_required=True,
            selection_scope=SELECTION_SCOPE,
            candidates=tuple(evidence),
        )

    best_score = max(_selection_score(item) for item in acceptable)
    winners = [item for item in acceptable if _selection_score(item) == best_score]
    if len(winners) != 1:
        winner_ids = {item.set_id.casefold() for item in winners if item.set_id}
        status = (
            SelectionStatus.MULTIPLE_EQUIVALENT_CANDIDATES
            if len(winner_ids) > 1
            else SelectionStatus.AMBIGUOUS_REQUIRES_REVIEW
        )
        ambiguous_ids = {item.candidate_id for item in winners}
        evidence = [
            replace(
                item,
                classifications=_ordered_classifications(
                    (*item.classifications, CandidateClassification.AMBIGUOUS)
                ),
                rejection_reasons=(
                    *item.rejection_reasons,
                    "equal top-ranked candidate requires manual review",
                ),
            )
            if item.candidate_id in ambiguous_ids
            else item
            for item in evidence
        ]
        return CandidateSelection(
            decision_id=decision_identifier,
            discovery_run_id=discovery_identifier,
            ingredient_id=identity.ingredient_id,
            selection_rule_version=selection_rule_version,
            selection_status=status,
            selected_candidate_id=None,
            selected_set_id=None,
            selected_source_version=None,
            selection_reason=(
                f"{len(winners)} candidates remained equal after every authoritative tie-break; "
                "lexical identity and response order are not used to claim a regulatory winner."
            ),
            applied_rules=SELECTION_RULES,
            manual_review_required=True,
            selection_scope=SELECTION_SCOPE,
            candidates=tuple(evidence),
        )

    selected = winners[0]
    updated = []
    for item in evidence:
        if item.candidate_id == selected.candidate_id or not item.accepted_for_selection:
            updated.append(item)
        else:
            updated.append(
                replace(
                    item,
                    rejection_reasons=(
                        *item.rejection_reasons,
                        "lower deterministic priority than the selected validation candidate",
                    ),
                )
            )
    return CandidateSelection(
        decision_id=decision_identifier,
        discovery_run_id=discovery_identifier,
        ingredient_id=identity.ingredient_id,
        selection_rule_version=selection_rule_version,
        selection_status=SelectionStatus.SELECTED,
        selected_candidate_id=selected.candidate_id,
        selected_set_id=selected.set_id,
        selected_source_version=selected.source_version,
        selection_reason=(
            f"Selected set_id {selected.set_id} source version {selected.source_version}; it was "
            "the unique highest candidate after explicit class, version, and "
            "publication-date rules."
        ),
        applied_rules=SELECTION_RULES,
        manual_review_required=False,
        selection_scope=SELECTION_SCOPE,
        candidates=tuple(updated),
    )


def _classify_candidate(
    candidate: DailyMedCandidate,
    identity: IngredientIdentity,
    *,
    candidate_id: str,
    discovery_run_id: str,
    response_index: int,
    raw_metadata_sha256: str,
    duplicate_of_candidate_id: str | None,
) -> CandidateEvidence:
    metadata = candidate.metadata
    active_ingredients = _text_values(
        metadata.get("active_ingredients", metadata.get("active_ingredient"))
    )
    generic_name = _text(metadata, "generic_name", "genericname")
    brand_name = _text(metadata, "brand_name", "brandname")
    dosage_form = _text(metadata, "dosage_form", "dosageform")
    route = _text(metadata, "route", "route_name")
    labeler = _text(metadata, "labeler", "labeler_name", "manufacturer")
    marketing_category = _text(metadata, "marketing_category", "marketingcategory")
    product_type = _text(metadata, "product_type", "producttype")
    source_status = _text(metadata, "status", "source_status", "marketing_status")
    source_url = _text(metadata, "source_url", "url")

    classifications: list[CandidateClassification] = []
    target = identity.normalized_search_string
    if len(active_ingredients) > 1:
        classifications.append(CandidateClassification.COMBINATION_PRODUCT)
    elif len(active_ingredients) == 1:
        active = active_ingredients[0]
        normalized_active = normalize_ingredient_name(active)
        if active.strip().casefold() == identity.original_ranked_ingredient.strip().casefold():
            classifications.append(CandidateClassification.EXACT_SINGLE_INGREDIENT_MATCH)
        elif normalized_active == target:
            classifications.append(CandidateClassification.SINGLE_INGREDIENT_NORMALIZED_MATCH)
        elif _is_salt_or_form_variant(normalized_active, target):
            classifications.append(CandidateClassification.SALT_OR_FORM_VARIANT)
        else:
            classifications.append(CandidateClassification.WRONG_INGREDIENT)

    product_text = (product_type or "").casefold()
    marketing_text = (marketing_category or "").casefold()
    if any(term in product_text for term in ("animal", "veterinary", "non-human")):
        classifications.append(CandidateClassification.NON_HUMAN_PRODUCT)
    elif "human" in product_text and (
        "over-the-counter" in product_text or "otc" in product_text
    ):
        classifications.append(CandidateClassification.OTC_PRODUCT)
    elif "human" in product_text and "prescription" in product_text:
        classifications.append(CandidateClassification.PRESCRIPTION_PRODUCT)
    elif product_type:
        classifications.append(CandidateClassification.UNSUPPORTED_PRODUCT_TYPE)

    repackaged_value = metadata.get("repackaged")
    if (
        repackaged_value is True
        or "repack" in (labeler or "").casefold()
        or "repack" in marketing_text
    ):
        classifications.append(CandidateClassification.REPACKAGED_PRODUCT)
    if source_status and any(
        term in source_status.casefold() for term in ("archived", "inactive", "discontinued")
    ):
        classifications.append(CandidateClassification.ARCHIVED_OR_INACTIVE)
    elif source_status and not any(
        term in source_status.casefold() for term in ("current", "active")
    ):
        classifications.append(CandidateClassification.AMBIGUOUS)

    required_values = (
        active_ingredients,
        product_type,
        source_status,
        labeler,
        marketing_category,
        dosage_form,
        route,
    )
    if any(not value for value in required_values):
        classifications.append(CandidateClassification.MISSING_REQUIRED_METADATA)
    if duplicate_of_candidate_id is not None:
        classifications.append(CandidateClassification.DUPLICATE_CANDIDATE)

    ordered = _ordered_classifications(classifications)
    has_match = any(
        value
        in {
            CandidateClassification.EXACT_SINGLE_INGREDIENT_MATCH,
            CandidateClassification.SINGLE_INGREDIENT_NORMALIZED_MATCH,
        }
        for value in ordered
    )
    has_prescription = CandidateClassification.PRESCRIPTION_PRODUCT in ordered
    accepted = has_match and has_prescription and not any(
        value in _FATAL_CLASSIFICATIONS for value in ordered
    )
    reasons = tuple(
        _REASON_BY_CLASSIFICATION[value]
        for value in ordered
        if value in _REASON_BY_CLASSIFICATION
    )
    return CandidateEvidence(
        candidate_id=candidate_id,
        discovery_run_id=discovery_run_id,
        candidate_index=response_index,
        set_id=candidate.set_id,
        source_version=candidate.source_version,
        title=candidate.title,
        published_date=candidate.published_date,
        generic_name=generic_name,
        brand_name=brand_name,
        active_ingredients=active_ingredients,
        dosage_form=dosage_form,
        route=route,
        labeler=labeler,
        marketing_category=marketing_category,
        product_type=product_type,
        source_status=source_status,
        source_url=source_url,
        raw_metadata=dict(metadata),
        raw_metadata_sha256=raw_metadata_sha256,
        classifications=ordered,
        accepted_for_selection=accepted,
        rejection_reasons=reasons,
        duplicate_of_candidate_id=duplicate_of_candidate_id,
    )


def _selection_score(candidate: CandidateEvidence) -> tuple[int, int, int]:
    exact = int(
        CandidateClassification.EXACT_SINGLE_INGREDIENT_MATCH in candidate.classifications
    )
    version = (
        int(candidate.source_version)
        if candidate.source_version and candidate.source_version.isdecimal()
        else -1
    )
    return exact, version, _published_ordinal(candidate.published_date)


def _stable_candidate_key(
    candidate: DailyMedCandidate, raw_metadata_sha256: str
) -> tuple[str, str, str, str, str]:
    return (
        candidate.set_id.casefold(),
        candidate.source_version,
        candidate.title.casefold(),
        candidate.published_date,
        raw_metadata_sha256,
    )


def _published_ordinal(value: str | None) -> int:
    if not value:
        return -1
    for format_string in ("%b %d, %Y", "%B %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, format_string).date().toordinal()
        except ValueError:
            continue
    return -1


def _lookup_is_truncated(lookup: CandidateLookup) -> bool:
    metadata = lookup.payload.get("metadata")
    if not isinstance(metadata, dict):
        return False
    value = metadata.get("total_elements")
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return False
    try:
        total = int(value)
    except (OverflowError, ValueError):
        return False
    return total > len(lookup.candidates)


def _text(metadata: dict[str, Any], *names: str) -> str | None:
    for name in names:
        value = metadata.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _text_values(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value.strip(),) if value.strip() else ()
    if not isinstance(value, list):
        return ()
    result = []
    for item in value:
        if isinstance(item, str) and item.strip():
            result.append(item.strip())
        elif isinstance(item, dict):
            name = item.get("name")
            if isinstance(name, str) and name.strip():
                result.append(name.strip())
    return tuple(result)


def _is_salt_or_form_variant(candidate: str, target: str) -> bool:
    return candidate.startswith(f"{target} ") or candidate.startswith(f"{target}-")


def _ordered_classifications(
    values: tuple[CandidateClassification, ...] | list[CandidateClassification],
) -> tuple[CandidateClassification, ...]:
    unique = set(values)
    return tuple(value for value in CandidateClassification if value in unique)

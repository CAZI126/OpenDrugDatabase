"""Offline ODD-005 four-valued evidence and structured extraction tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from odd.enrichment.decision import revise_selection
from odd.enrichment.extractor import AssertionDraft, CandidateEvidenceExtractor
from odd.errors import MalformedXML
from odd.models import CandidateEvidence, SelectionStatus
from odd.models.enrichment import (
    CandidateDetailPage,
    EnrichmentCompleteness,
    EnrichmentTier,
    EvidenceResult,
    EvidenceType,
)
from odd.provenance.hashing import sha256_bytes

NOW = datetime(2026, 8, 9, tzinfo=UTC)


def test_packaging_proves_single_exact_active_and_ignores_inactive_text() -> None:
    extractor = CandidateEvidenceExtractor()
    candidate = _candidate("atorvastatin")
    page = _page(
        candidate,
        [
            {
                "active_ingredients": [{"name": "atorvastatin", "strength": "10 mg"}],
                "inactive_ingredients": [{"name": "metformin"}],
                "product_code": "00001-001",
            }
        ],
    )
    assertions = _materialize(
        extractor,
        candidate,
        extractor.packaging(
            (page,),
            ingredient_name="atorvastatin",
            expected_set_id=candidate.set_id or "",
            expected_source_version="1",
            complete=True,
        ),
    )
    results = {value.evidence_type: value.result for value in assertions}
    assert results[EvidenceType.SINGLE_ACTIVE_INGREDIENT] is EvidenceResult.PROVEN_TRUE
    assert results[EvidenceType.EXACT_INGREDIENT_IDENTITY] is EvidenceResult.PROVEN_TRUE
    assert results[EvidenceType.COMBINATION_PRODUCT] is EvidenceResult.PROVEN_FALSE
    assert results[EvidenceType.REPACKAGED_PRODUCT] is EvidenceResult.UNKNOWN
    exact = next(
        value
        for value in assertions
        if value.evidence_type is EvidenceType.EXACT_INGREDIENT_IDENTITY
    )
    assert exact.source_locator == "#/data/products/*/active_ingredients/*/name"
    assert exact.raw_response_sha256 is not None
    assert exact.source_response_sha256s == (page.raw_sha256,)


def test_tier0_current_scope_keeps_unsupported_detail_facts_unknown() -> None:
    extractor = CandidateEvidenceExtractor()
    candidate = _candidate("atorvastatin")
    assertions = _materialize(extractor, candidate, extractor.tier0(candidate))
    results = {value.evidence_type: value.result for value in assertions}
    assert results[EvidenceType.HUMAN_USE] is EvidenceResult.PROVEN_TRUE
    assert results[EvidenceType.PRESCRIPTION] is EvidenceResult.PROVEN_TRUE
    assert results[EvidenceType.CURRENT] is EvidenceResult.PROVEN_TRUE
    assert results[EvidenceType.ARCHIVED] is EvidenceResult.PROVEN_FALSE
    assert results[EvidenceType.REPACKAGED_PRODUCT] is EvidenceResult.UNKNOWN


def test_packaging_proves_combination_product() -> None:
    extractor = CandidateEvidenceExtractor()
    candidate = _candidate("atorvastatin")
    page = _page(
        candidate,
        [
            {
                "active_ingredients": [
                    {"name": "atorvastatin"},
                    {"name": "amlodipine"},
                ],
                "product_code": "00001-001",
            }
        ],
    )
    assertions = _materialize(
        extractor,
        candidate,
        extractor.packaging(
            (page,),
            ingredient_name="atorvastatin",
            expected_set_id=candidate.set_id or "",
            expected_source_version="1",
            complete=True,
        ),
    )
    results = {value.evidence_type: value.result for value in assertions}
    assert results[EvidenceType.COMBINATION_PRODUCT] is EvidenceResult.PROVEN_TRUE
    assert results[EvidenceType.SINGLE_ACTIVE_INGREDIENT] is EvidenceResult.PROVEN_FALSE


def test_packaging_evaluates_product_and_part_active_ingredients_together() -> None:
    extractor = CandidateEvidenceExtractor()
    candidate = _candidate("atorvastatin")
    page = _page(
        candidate,
        [
            {
                "active_ingredients": [{"name": "atorvastatin"}],
                "parts": [
                    {"active_ingredients": [{"name": "amlodipine"}]}
                ],
                "product_code": "00001-001",
            }
        ],
    )
    assertions = _materialize(
        extractor,
        candidate,
        extractor.packaging(
            (page,),
            ingredient_name="atorvastatin",
            expected_set_id=candidate.set_id or "",
            expected_source_version="1",
            complete=True,
        ),
    )
    results = {value.evidence_type: value.result for value in assertions}
    assert results[EvidenceType.COMBINATION_PRODUCT] is EvidenceResult.PROVEN_TRUE
    assert results[EvidenceType.EXACT_INGREDIENT_IDENTITY] is EvidenceResult.PROVEN_FALSE


def test_packaging_accepts_structured_part_active_ingredient_without_product_array() -> None:
    extractor = CandidateEvidenceExtractor()
    candidate = _candidate("atorvastatin")
    page = _page(
        candidate,
        [
            {
                "parts": [
                    {"active_ingredients": [{"name": "atorvastatin"}]}
                ],
                "product_code": "00001-001",
            }
        ],
    )
    assertions = _materialize(
        extractor,
        candidate,
        extractor.packaging(
            (page,),
            ingredient_name="atorvastatin",
            expected_set_id=candidate.set_id or "",
            expected_source_version="1",
            complete=True,
        ),
    )
    results = {value.evidence_type: value.result for value in assertions}
    assert results[EvidenceType.SINGLE_ACTIVE_INGREDIENT] is EvidenceResult.PROVEN_TRUE
    assert results[EvidenceType.EXACT_INGREDIENT_IDENTITY] is EvidenceResult.PROVEN_TRUE


@pytest.mark.parametrize(
    "variant",
    (
        "atorvastatin calcium",
        "atorvastatin hydrate",
        "atorvastatin ester",
        "atorvastatin complex",
    ),
)
def test_salt_ester_hydrate_and_complex_are_not_mapped_to_parent(variant: str) -> None:
    extractor = CandidateEvidenceExtractor()
    candidate = _candidate("atorvastatin")
    page = _page(
        candidate,
        [{"active_ingredients": [{"name": variant}], "product_code": "00001-001"}],
    )
    assertions = _materialize(
        extractor,
        candidate,
        extractor.packaging(
            (page,),
            ingredient_name="atorvastatin",
            expected_set_id=candidate.set_id or "",
            expected_source_version="1",
            complete=True,
        ),
    )
    exact = next(
        value
        for value in assertions
        if value.evidence_type is EvidenceType.EXACT_INGREDIENT_IDENTITY
    )
    assert exact.result is EvidenceResult.PROVEN_FALSE
    assert "no salt, ester, hydrate" in exact.diagnostic


def test_incomplete_packaging_page_never_proves_single_or_exact() -> None:
    extractor = CandidateEvidenceExtractor()
    candidate = _candidate("atorvastatin")
    page = _page(
        candidate,
        [{"active_ingredients": [{"name": "atorvastatin"}], "product_code": "x"}],
    )
    assertions = _materialize(
        extractor,
        candidate,
        extractor.packaging(
            (page,),
            ingredient_name="atorvastatin",
            expected_set_id=candidate.set_id or "",
            expected_source_version="1",
            complete=False,
        ),
    )
    results = {value.evidence_type: value.result for value in assertions}
    assert results[EvidenceType.SINGLE_ACTIVE_INGREDIENT] is EvidenceResult.UNKNOWN
    assert results[EvidenceType.EXACT_INGREDIENT_IDENTITY] is EvidenceResult.UNKNOWN


def test_packaging_version_drift_is_conflict() -> None:
    extractor = CandidateEvidenceExtractor()
    candidate = _candidate("atorvastatin")
    page = replace(_page(candidate, []), observed_source_version="2")
    assertions = _materialize(
        extractor,
        candidate,
        extractor.packaging(
            (page,),
            ingredient_name="atorvastatin",
            expected_set_id=candidate.set_id or "",
            expected_source_version="1",
            complete=True,
        ),
    )
    identity = next(
        value for value in assertions if value.evidence_type is EvidenceType.SOURCE_IDENTITY_MATCH
    )
    assert identity.result is EvidenceResult.CONFLICT


def test_spl_uses_active_class_codes_and_proves_repack_positive_only() -> None:
    extractor = CandidateEvidenceExtractor()
    candidate = _candidate("atorvastatin")
    xml = _xml(candidate, operation_code="C73606")
    result = extractor.spl_xml(
        xml,
        ingredient_name="atorvastatin",
        expected_set_id=candidate.set_id or "",
        expected_source_version="1",
        source_url="https://dailymed.example/spl.xml",
        retrieved_at=NOW,
    )
    assertions = _materialize(extractor, candidate, result.drafts)
    values = {value.evidence_type: value.result for value in assertions}
    assert values[EvidenceType.REPACKAGED_PRODUCT] is EvidenceResult.PROVEN_TRUE
    assert values[EvidenceType.EXACT_INGREDIENT_IDENTITY] is EvidenceResult.PROVEN_TRUE
    assert values[EvidenceType.SUPPORTED_DOCUMENT_STRUCTURE] is EvidenceResult.PROVEN_TRUE


def test_spl_active_moiety_name_does_not_replace_the_active_ingredient_name() -> None:
    extractor = CandidateEvidenceExtractor()
    candidate = _candidate("atorvastatin")
    xml = (
        '<document xmlns="urn:hl7-org:v3">'
        '<code code="34391-3"/>'
        f'<setId root="{candidate.set_id}"/>'
        '<versionNumber value="1"/>'
        '<component><structuredBody><component><section><subject><manufacturedProduct>'
        '<manufacturedProduct><ingredient classCode="ACTIM"><ingredientSubstance>'
        '<name>atorvastatin calcium</name><activeMoiety><activeMoiety>'
        '<name>atorvastatin</name></activeMoiety></activeMoiety>'
        '</ingredientSubstance></ingredient></manufacturedProduct>'
        '</manufacturedProduct></subject></section></component></structuredBody></component>'
        '</document>'
    ).encode()
    result = extractor.spl_xml(
        xml,
        ingredient_name="atorvastatin",
        expected_set_id=candidate.set_id or "",
        expected_source_version="1",
        source_url="https://dailymed.example/spl.xml",
        retrieved_at=NOW,
    )
    assertions = _materialize(extractor, candidate, result.drafts)
    exact = next(
        value
        for value in assertions
        if value.evidence_type is EvidenceType.EXACT_INGREDIENT_IDENTITY
    )
    assert exact.result is EvidenceResult.PROVEN_FALSE


def test_spl_absent_repack_code_remains_unknown() -> None:
    extractor = CandidateEvidenceExtractor()
    candidate = _candidate("atorvastatin")
    result = extractor.spl_xml(
        _xml(candidate),
        ingredient_name="atorvastatin",
        expected_set_id=candidate.set_id or "",
        expected_source_version="1",
        source_url="https://dailymed.example/spl.xml",
        retrieved_at=NOW,
    )
    assertions = _materialize(extractor, candidate, result.drafts)
    repack = next(
        value for value in assertions if value.evidence_type is EvidenceType.REPACKAGED_PRODUCT
    )
    assert repack.result is EvidenceResult.UNKNOWN


@pytest.mark.parametrize(
    ("document_code", "expected_human", "expected_prescription"),
    (
        ("34391-3", EvidenceResult.PROVEN_TRUE, EvidenceResult.PROVEN_TRUE),
        ("34390-5", EvidenceResult.PROVEN_TRUE, EvidenceResult.PROVEN_FALSE),
        ("50578-4", EvidenceResult.PROVEN_FALSE, EvidenceResult.PROVEN_TRUE),
        ("50577-6", EvidenceResult.PROVEN_FALSE, EvidenceResult.PROVEN_FALSE),
        ("unmapped", EvidenceResult.UNKNOWN, EvidenceResult.UNKNOWN),
    ),
)
def test_spl_document_codes_distinguish_human_animal_and_prescription_otc(
    document_code: str,
    expected_human: EvidenceResult,
    expected_prescription: EvidenceResult,
) -> None:
    extractor = CandidateEvidenceExtractor()
    candidate = _candidate("atorvastatin")
    result = extractor.spl_xml(
        _xml(candidate, document_code=document_code),
        ingredient_name="atorvastatin",
        expected_set_id=candidate.set_id or "",
        expected_source_version="1",
        source_url="https://dailymed.example/spl.xml",
        retrieved_at=NOW,
    )
    assertions = _materialize(extractor, candidate, result.drafts)
    values = {value.evidence_type: value.result for value in assertions}
    assert values[EvidenceType.HUMAN_USE] is expected_human
    assert values[EvidenceType.PRESCRIPTION] is expected_prescription


def test_spl_dtd_and_entity_are_rejected_before_parsing() -> None:
    extractor = CandidateEvidenceExtractor()
    with pytest.raises(MalformedXML, match="DTD or entity"):
        extractor.spl_xml(
            b'<!DOCTYPE document [<!ENTITY x SYSTEM "file:///etc/passwd">]><document/>',
            ingredient_name="atorvastatin",
            expected_set_id="00000000-0000-4000-8000-000000000001",
            expected_source_version="1",
            source_url="https://dailymed.example/spl.xml",
            retrieved_at=NOW,
        )


def test_unknown_candidate_blocks_selection_even_when_another_is_eligible() -> None:
    extractor = CandidateEvidenceExtractor()
    winner = _candidate("atorvastatin", suffix=1, version="2")
    unknown = _candidate("atorvastatin", suffix=2, version="1")
    assertions = (
        *_complete_assertions(extractor, winner),
        *_materialize(extractor, unknown, extractor.tier0(unknown)),
    )
    result = revise_selection((winner, unknown), assertions)
    assert result.completeness is EnrichmentCompleteness.INCOMPLETE
    assert result.selection_status is SelectionStatus.MANUAL_REVIEW_REQUIRED
    assert result.selected_candidate is None


def test_conflicting_official_assertions_block_selection() -> None:
    extractor = CandidateEvidenceExtractor()
    candidate = _candidate("atorvastatin")
    assertions = list(_complete_assertions(extractor, candidate))
    repack_false = next(
        value for value in assertions if value.evidence_type is EvidenceType.REPACKAGED_PRODUCT
    )
    conflict_draft = AssertionDraft(
        evidence_type=EvidenceType.REPACKAGED_PRODUCT,
        result=EvidenceResult.PROVEN_TRUE,
        tier=EnrichmentTier.TIER_2,
        raw_response_sha256="f" * 64,
        source_url_identity="https://dailymed.example/spl.xml",
        source_locator="/document//performance",
        source_field_or_code="C73606",
        diagnostic="synthetic conflict",
        observed_source_version="1",
        retrieved_at=NOW,
    )
    assertions.extend(_materialize(extractor, candidate, (conflict_draft,)))
    assert repack_false.result is EvidenceResult.PROVEN_FALSE
    result = revise_selection((candidate,), tuple(assertions))
    assert result.completeness is EnrichmentCompleteness.CONFLICT
    assert result.selected_candidate is None


def test_candidate_order_does_not_change_unique_selection() -> None:
    extractor = CandidateEvidenceExtractor()
    winner = _candidate("atorvastatin", suffix=1, version="2")
    loser = _candidate("atorvastatin", suffix=2, version="1")
    assertions = (*_complete_assertions(extractor, winner), *_complete_assertions(extractor, loser))
    forward = revise_selection((winner, loser), assertions)
    reverse = revise_selection((loser, winner), assertions)
    assert forward.selected_candidate == reverse.selected_candidate == winner


def test_equal_authoritative_score_requires_manual_review_without_setid_tiebreak() -> None:
    extractor = CandidateEvidenceExtractor()
    first = _candidate("atorvastatin", suffix=1)
    second = _candidate("atorvastatin", suffix=2)
    assertions = (*_complete_assertions(extractor, first), *_complete_assertions(extractor, second))
    result = revise_selection((first, second), assertions)
    assert result.selection_status is SelectionStatus.MANUAL_REVIEW_REQUIRED
    assert result.completeness is EnrichmentCompleteness.COMPLETE
    assert "set ID lexical" in result.reason


def _candidate(
    ingredient: str, *, suffix: int = 1, version: str = "1"
) -> CandidateEvidence:
    return CandidateEvidence(
        candidate_id=f"10000000-0000-4000-8000-{suffix:012d}",
        discovery_run_id="20000000-0000-4000-8000-000000000001",
        candidate_index=suffix - 1,
        set_id=f"30000000-0000-4000-8000-{suffix:012d}",
        source_version=version,
        title=f"{ingredient} synthetic",
        published_date="Aug 08, 2026",
        generic_name=None,
        brand_name=None,
        active_ingredients=(),
        dosage_form=None,
        route=None,
        labeler=None,
        marketing_category=None,
        product_type="HUMAN PRESCRIPTION DRUG",
        source_status="current",
        source_url="https://dailymed.example/spl.xml",
        raw_metadata={},
        raw_metadata_sha256="a" * 64,
    )


def _page(
    candidate: CandidateEvidence, products: list[dict[str, object]]
) -> CandidateDetailPage:
    body = b'{"synthetic":"packaging"}'
    return CandidateDetailPage(
        set_id=candidate.set_id or "",
        observed_source_version=candidate.source_version or "",
        title=candidate.title or "synthetic",
        published_date=candidate.published_date or "Aug 08, 2026",
        page_number=1,
        page_size=100,
        request_url="https://dailymed.example/packaging.json?page=1&pagesize=100",
        canonical_request=(("endpoint", "https://dailymed.example/packaging.json"),),
        final_url="https://dailymed.example/packaging.json?page=1&pagesize=100",
        status_code=200,
        content_type="application/json",
        retrieved_at=NOW,
        etag=None,
        last_modified=None,
        raw_body=body,
        raw_sha256=sha256_bytes(body),
        payload={"data": {"products": products}},
        products=tuple(products),
        attempts=(),
    )


def _materialize(
    extractor: CandidateEvidenceExtractor,
    candidate: CandidateEvidence,
    drafts: tuple[AssertionDraft, ...],
):
    return extractor.materialize(
        drafts,
        parent_discovery_snapshot_id="40000000-0000-4000-8000-000000000001",
        enrichment_run_id="50000000-0000-4000-8000-000000000001",
        enrichment_snapshot_id="60000000-0000-4000-8000-000000000001",
        candidate=candidate,
    )


def _complete_assertions(
    extractor: CandidateEvidenceExtractor, candidate: CandidateEvidence
):
    results = {
        EvidenceType.HUMAN_USE: EvidenceResult.PROVEN_TRUE,
        EvidenceType.CURRENT: EvidenceResult.PROVEN_TRUE,
        EvidenceType.PRESCRIPTION: EvidenceResult.PROVEN_TRUE,
        EvidenceType.SINGLE_ACTIVE_INGREDIENT: EvidenceResult.PROVEN_TRUE,
        EvidenceType.EXACT_INGREDIENT_IDENTITY: EvidenceResult.PROVEN_TRUE,
        EvidenceType.COMBINATION_PRODUCT: EvidenceResult.PROVEN_FALSE,
        EvidenceType.REPACKAGED_PRODUCT: EvidenceResult.PROVEN_FALSE,
        EvidenceType.ARCHIVED: EvidenceResult.PROVEN_FALSE,
        EvidenceType.SUPPORTED_DOCUMENT_STRUCTURE: EvidenceResult.PROVEN_TRUE,
        EvidenceType.SOURCE_IDENTITY_MATCH: EvidenceResult.PROVEN_TRUE,
    }
    drafts = tuple(
        AssertionDraft(
            evidence_type=evidence_type,
            result=result,
            tier=EnrichmentTier.TIER_2,
            raw_response_sha256="e" * 64,
            source_url_identity="https://dailymed.example/spl.xml",
            source_locator=f"/synthetic/{evidence_type.value}",
            source_field_or_code="synthetic explicit evidence",
            diagnostic="synthetic complete evidence",
            observed_source_version=candidate.source_version,
            retrieved_at=NOW,
        )
        for evidence_type, result in results.items()
    )
    return _materialize(extractor, candidate, drafts)


def _xml(
    candidate: CandidateEvidence,
    operation_code: str | None = None,
    *,
    document_code: str = "34391-3",
) -> bytes:
    operation = (
        ""
        if operation_code is None
        else (
            "<performance><actDefinition><code code=\""
            f"{operation_code}\"/></actDefinition></performance>"
        )
    )
    return (
        '<document xmlns="urn:hl7-org:v3">'
        f'<code code="{document_code}"/>'
        f'<setId root="{candidate.set_id}"/>'
        f'<versionNumber value="{candidate.source_version}"/>'
        '<component><structuredBody><component><section><subject><manufacturedProduct>'
        '<manufacturedProduct><ingredient classCode="ACTIB"><ingredientSubstance>'
        '<name>atorvastatin</name></ingredientSubstance></ingredient></manufacturedProduct>'
        f"{operation}"
        "</manufacturedProduct></subject></section></component></structuredBody></component>"
        "</document>"
    ).encode()

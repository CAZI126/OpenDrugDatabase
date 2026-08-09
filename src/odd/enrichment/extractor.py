"""Conservative extraction of candidate facts from official DailyMed evidence."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace
from datetime import datetime

from odd.constants import ENRICHMENT_EXTRACTOR_VERSION, ENRICHMENT_RULE_VERSION
from odd.errors import MalformedMetadata, MalformedXML
from odd.models import CandidateEvidence
from odd.models.enrichment import (
    CandidateDetailPage,
    EnrichmentTier,
    EvidenceAssertion,
    EvidenceResult,
    EvidenceType,
)
from odd.provenance.hashing import sha256_bytes
from odd.provenance.identifiers import evidence_assertion_id, evidence_identity

HUMAN_PRESCRIPTION_DOCUMENT_CODE = "34391-3"
HUMAN_OTC_DOCUMENT_CODE = "34390-5"
PRESCRIPTION_ANIMAL_DOCUMENT_CODE = "50578-4"
OTC_ANIMAL_DOCUMENT_CODE = "50577-6"
HUMAN_DOCUMENT_CODES = frozenset(
    {HUMAN_PRESCRIPTION_DOCUMENT_CODE, HUMAN_OTC_DOCUMENT_CODE}
)
ANIMAL_DOCUMENT_CODES = frozenset(
    {PRESCRIPTION_ANIMAL_DOCUMENT_CODE, OTC_ANIMAL_DOCUMENT_CODE}
)
PRESCRIPTION_DOCUMENT_CODES = frozenset(
    {HUMAN_PRESCRIPTION_DOCUMENT_CODE, PRESCRIPTION_ANIMAL_DOCUMENT_CODE}
)
OTC_DOCUMENT_CODES = frozenset({HUMAN_OTC_DOCUMENT_CODE, OTC_ANIMAL_DOCUMENT_CODE})
ACTIVE_INGREDIENT_CLASS_CODES = frozenset({"ACTIB", "ACTIM", "ACTIR"})
REPACK_OR_RELABEL_CODES = frozenset({"C73606", "C73607"})
_SPACE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class AssertionDraft:
    evidence_type: EvidenceType
    result: EvidenceResult
    tier: EnrichmentTier
    raw_response_sha256: str | None
    source_url_identity: str
    source_locator: str
    source_field_or_code: str
    diagnostic: str
    observed_source_version: str | None = None
    retrieved_at: datetime | None = None
    source_response_sha256s: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class XMLExtraction:
    drafts: tuple[AssertionDraft, ...]
    set_id: str | None
    source_version: str | None
    document_code: str | None


class CandidateEvidenceExtractor:
    """Extract only facts supported by documented fields or SPL structures."""

    extractor_version = ENRICHMENT_EXTRACTOR_VERSION
    extraction_rule_version = ENRICHMENT_RULE_VERSION

    def tier0(self, candidate: CandidateEvidence) -> tuple[AssertionDraft, ...]:
        source = candidate.source_url or "dailymed-current-spls-query"
        return (
            self._draft(
                EvidenceType.HUMAN_USE,
                EvidenceResult.PROVEN_TRUE,
                EnrichmentTier.TIER_0,
                source,
                "canonical_request/doctype",
                HUMAN_PRESCRIPTION_DOCUMENT_CODE,
                "The complete parent discovery used the documented human prescription "
                "document-type filter.",
            ),
            self._draft(
                EvidenceType.PRESCRIPTION,
                EvidenceResult.PROVEN_TRUE,
                EnrichmentTier.TIER_0,
                source,
                "canonical_request/doctype",
                HUMAN_PRESCRIPTION_DOCUMENT_CODE,
                "Document code 34391-3 is HUMAN PRESCRIPTION DRUG LABEL.",
            ),
            self._draft(
                EvidenceType.CURRENT,
                EvidenceResult.PROVEN_TRUE,
                EnrichmentTier.TIER_0,
                source,
                "candidate/_odd_live_evidence/api_scope",
                "current SPL information",
                "The parent snapshot used DailyMed's current-SPL web-service scope.",
            ),
            self._draft(
                EvidenceType.ARCHIVED,
                EvidenceResult.PROVEN_FALSE,
                EnrichmentTier.TIER_0,
                source,
                "candidate/_odd_live_evidence/api_scope",
                "current SPL information",
                "A candidate retained from the current-SPL scope is not classified archived.",
            ),
            self._draft(
                EvidenceType.SOURCE_IDENTITY_MATCH,
                EvidenceResult.PROVEN_TRUE,
                EnrichmentTier.TIER_0,
                source,
                "candidate/{setid,spl_version}",
                "setid,spl_version",
                "Parent discovery supplied the candidate identity; detail evidence must "
                "independently confirm it.",
            ),
            *(
                self._draft(
                    evidence_type,
                    EvidenceResult.UNKNOWN,
                    EnrichmentTier.TIER_0,
                    source,
                    "candidate/search-metadata",
                    "unsupported",
                    "The documented search result does not expose this required fact.",
                )
                for evidence_type in (
                    EvidenceType.SINGLE_ACTIVE_INGREDIENT,
                    EvidenceType.EXACT_INGREDIENT_IDENTITY,
                    EvidenceType.COMBINATION_PRODUCT,
                    EvidenceType.REPACKAGED_PRODUCT,
                    EvidenceType.SUPPORTED_DOCUMENT_STRUCTURE,
                )
            ),
        )

    def packaging(
        self,
        pages: tuple[CandidateDetailPage, ...],
        *,
        ingredient_name: str,
        expected_set_id: str,
        expected_source_version: str,
        complete: bool,
        completeness_diagnostic: str | None = None,
        expected_published_date: str | None = None,
    ) -> tuple[AssertionDraft, ...]:
        if not pages:
            raise MalformedMetadata("packaging extraction requires at least one response page")
        versions = {page.observed_source_version for page in pages}
        set_ids = {page.set_id.casefold() for page in pages}
        published_dates = {page.published_date for page in pages}
        source_response_hashes = tuple(
            page.raw_sha256 for page in sorted(pages, key=lambda value: value.page_number)
        )
        raw_hash = source_response_hashes[0] if len(source_response_hashes) == 1 else None
        source_url = pages[0].canonical_request[0][1]
        retrieved_at = pages[0].retrieved_at
        identity_matches = (
            set_ids == {expected_set_id.casefold()}
            and versions == {expected_source_version}
            and (
                expected_published_date is None
                or published_dates == {expected_published_date}
            )
        )
        observed_version = next(iter(versions)) if len(versions) == 1 else None
        identity_result = (
            EvidenceResult.PROVEN_TRUE if identity_matches else EvidenceResult.CONFLICT
        )
        drafts: list[AssertionDraft] = [
            self._draft(
                EvidenceType.SOURCE_IDENTITY_MATCH,
                identity_result,
                EnrichmentTier.TIER_1,
                source_url,
                "#/data/{setid,spl_version,published_date}",
                "setid,spl_version,published_date",
                (
                    "Packaging detail identity and publication date match the parent candidate."
                    if identity_matches
                    else "Packaging detail identity or publication date conflicts with the "
                    "parent candidate."
                ),
                raw_hash=raw_hash,
                observed_version=observed_version,
                retrieved_at=retrieved_at,
                source_response_hashes=source_response_hashes,
            )
        ]
        names, malformed = _packaging_active_ingredient_names(pages)
        normalized_names = {_normalize_name(name) for name in names if _normalize_name(name)}
        expected_name = _normalize_name(ingredient_name)
        if not complete and completeness_diagnostic and "conflicting metadata" in (
            completeness_diagnostic
        ):
            single = exact = combination = EvidenceResult.CONFLICT
            diagnostic = completeness_diagnostic
        elif malformed or not names:
            single = exact = combination = EvidenceResult.UNKNOWN
            diagnostic = "One or more structured product active-ingredient arrays were absent."
        elif len(normalized_names) > 1:
            single = EvidenceResult.PROVEN_FALSE
            exact = EvidenceResult.PROVEN_FALSE
            combination = EvidenceResult.PROVEN_TRUE
            diagnostic = "Structured packaging metadata proves multiple active ingredients."
        elif not complete:
            single = exact = combination = EvidenceResult.UNKNOWN
            diagnostic = completeness_diagnostic or (
                "Packaging pagination did not reach a documented short terminal page."
            )
        else:
            only_name = next(iter(normalized_names))
            single = EvidenceResult.PROVEN_TRUE
            combination = EvidenceResult.PROVEN_FALSE
            exact = (
                EvidenceResult.PROVEN_TRUE
                if only_name == expected_name
                else EvidenceResult.PROVEN_FALSE
            )
            diagnostic = (
                "The sole structured active-ingredient name exactly matches the ranked name."
                if exact is EvidenceResult.PROVEN_TRUE
                else "The sole structured active-ingredient name is not an exact ranked-name "
                "match; no salt, ester, hydrate, moiety, or synonym mapping was applied."
            )
        for evidence_type, result in (
            (EvidenceType.SINGLE_ACTIVE_INGREDIENT, single),
            (EvidenceType.EXACT_INGREDIENT_IDENTITY, exact),
            (EvidenceType.COMBINATION_PRODUCT, combination),
        ):
            drafts.append(
                self._draft(
                    evidence_type,
                    result,
                    EnrichmentTier.TIER_1,
                    source_url,
                    "#/data/products/*/active_ingredients/*/name",
                    "active_ingredients[].name",
                    diagnostic,
                    raw_hash=raw_hash,
                    observed_version=observed_version,
                    retrieved_at=retrieved_at,
                    source_response_hashes=source_response_hashes,
                )
            )
        drafts.append(
            self._draft(
                EvidenceType.REPACKAGED_PRODUCT,
                EvidenceResult.UNKNOWN,
                EnrichmentTier.TIER_1,
                source_url,
                "#/data",
                "not documented by packaging response",
                "The packaging endpoint does not document a non-repackager field; absence is "
                "not evidence of PROVEN_FALSE.",
                raw_hash=raw_hash,
                observed_version=observed_version,
                retrieved_at=retrieved_at,
                source_response_hashes=source_response_hashes,
            )
        )
        return tuple(drafts)

    def spl_xml(
        self,
        body: bytes,
        *,
        ingredient_name: str,
        expected_set_id: str,
        expected_source_version: str,
        source_url: str,
        retrieved_at: datetime,
    ) -> XMLExtraction:
        if b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
            raise MalformedXML("SPL XML containing a DTD or entity declaration is rejected")
        try:
            root = ET.fromstring(body)
        except ET.ParseError as exc:
            raise MalformedXML(f"SPL XML is malformed: {exc}") from exc
        raw_hash = sha256_bytes(body)
        namespace = _namespace(root.tag)
        document_ok = _local_name(root.tag) == "document" and namespace == "urn:hl7-org:v3"
        set_id_element = root.find(_qualified(namespace, "setId"))
        version_element = root.find(_qualified(namespace, "versionNumber"))
        code_element = root.find(_qualified(namespace, "code"))
        observed_set_id = set_id_element.get("root") if set_id_element is not None else None
        observed_version = (
            version_element.get("value") if version_element is not None else None
        )
        document_code = code_element.get("code") if code_element is not None else None
        identity_matches = bool(
            observed_set_id
            and observed_version
            and observed_set_id.casefold() == expected_set_id.casefold()
            and observed_version == expected_source_version
        )
        active_nodes = tuple(
            element
            for element in root.iter(_qualified(namespace, "ingredient"))
            if element.get("classCode") in ACTIVE_INGREDIENT_CLASS_CODES
        )
        active_names: list[str] = []
        missing_active_name = False
        for ingredient in active_nodes:
            name = ingredient.find(
                f"{_qualified(namespace, 'ingredientSubstance')}/"
                f"{_qualified(namespace, 'name')}"
            )
            normalized = "" if name is None or name.text is None else name.text.strip()
            if normalized:
                active_names.append(normalized)
            else:
                missing_active_name = True
        normalized_names = {_normalize_name(name) for name in active_names}
        expected_name = _normalize_name(ingredient_name)
        if not active_nodes or missing_active_name:
            single = exact = combination = EvidenceResult.UNKNOWN
        elif len(normalized_names) > 1:
            single = EvidenceResult.PROVEN_FALSE
            exact = EvidenceResult.PROVEN_FALSE
            combination = EvidenceResult.PROVEN_TRUE
        else:
            single = EvidenceResult.PROVEN_TRUE
            combination = EvidenceResult.PROVEN_FALSE
            exact = (
                EvidenceResult.PROVEN_TRUE
                if next(iter(normalized_names)) == expected_name
                else EvidenceResult.PROVEN_FALSE
            )
        repack_codes = {
            element.get("code")
            for performance in root.iter(_qualified(namespace, "performance"))
            for act in performance.iter(_qualified(namespace, "actDefinition"))
            for element in act.iter(_qualified(namespace, "code"))
            if element.get("code") in REPACK_OR_RELABEL_CODES
        }
        repack_result = (
            EvidenceResult.PROVEN_TRUE if repack_codes else EvidenceResult.UNKNOWN
        )
        structure_result = (
            EvidenceResult.PROVEN_TRUE
            if (
                document_ok
                and observed_set_id
                and observed_version
                and document_code
                and active_nodes
            )
            else EvidenceResult.PROVEN_FALSE
        )
        human_result = (
            EvidenceResult.PROVEN_TRUE
            if document_code in HUMAN_DOCUMENT_CODES
            else (
                EvidenceResult.PROVEN_FALSE
                if document_code in ANIMAL_DOCUMENT_CODES
                else EvidenceResult.UNKNOWN
            )
        )
        prescription_result = (
            EvidenceResult.PROVEN_TRUE
            if document_code in PRESCRIPTION_DOCUMENT_CODES
            else (
                EvidenceResult.PROVEN_FALSE
                if document_code in OTC_DOCUMENT_CODES
                else EvidenceResult.UNKNOWN
            )
        )
        drafts = (
            self._draft(
                EvidenceType.SOURCE_IDENTITY_MATCH,
                EvidenceResult.PROVEN_TRUE
                if identity_matches
                else EvidenceResult.CONFLICT,
                EnrichmentTier.TIER_2,
                source_url,
                "/document/{setId@root,versionNumber@value}",
                "setId@root,versionNumber@value",
                "SPL identity matches the parent candidate."
                if identity_matches
                else "SPL identity conflicts with the parent candidate.",
                raw_hash=raw_hash,
                observed_version=observed_version,
                retrieved_at=retrieved_at,
            ),
            self._draft(
                EvidenceType.HUMAN_USE,
                human_result,
                EnrichmentTier.TIER_2,
                source_url,
                "/document/code@code",
                document_code or "missing",
                "The versioned FDA document-code map proves human use."
                if human_result is EvidenceResult.PROVEN_TRUE
                else (
                    "The versioned FDA document-code map proves animal use."
                    if human_result is EvidenceResult.PROVEN_FALSE
                    else "The document code does not prove human or animal use under this "
                    "extractor."
                ),
                raw_hash=raw_hash,
                observed_version=observed_version,
                retrieved_at=retrieved_at,
            ),
            self._draft(
                EvidenceType.PRESCRIPTION,
                prescription_result,
                EnrichmentTier.TIER_2,
                source_url,
                "/document/code@code",
                document_code or "missing",
                "The versioned FDA document-code map proves prescription status."
                if prescription_result is EvidenceResult.PROVEN_TRUE
                else (
                    "The versioned FDA document-code map proves OTC status."
                    if prescription_result is EvidenceResult.PROVEN_FALSE
                    else "The document code does not prove prescription or OTC status under "
                    "this extractor."
                ),
                raw_hash=raw_hash,
                observed_version=observed_version,
                retrieved_at=retrieved_at,
            ),
            *(
                self._draft(
                    evidence_type,
                    result,
                    EnrichmentTier.TIER_2,
                    source_url,
                    "/document//manufacturedProduct//ingredient[@classCode="
                    "'ACTIB'|'ACTIM'|'ACTIR']/ingredientSubstance/name",
                    "ingredient@classCode,ingredientSubstance/name",
                    "Only SPL active-ingredient class codes were evaluated; inactive "
                    "ingredient and product-title text were ignored.",
                    raw_hash=raw_hash,
                    observed_version=observed_version,
                    retrieved_at=retrieved_at,
                )
                for evidence_type, result in (
                    (EvidenceType.SINGLE_ACTIVE_INGREDIENT, single),
                    (EvidenceType.EXACT_INGREDIENT_IDENTITY, exact),
                    (EvidenceType.COMBINATION_PRODUCT, combination),
                )
            ),
            self._draft(
                EvidenceType.REPACKAGED_PRODUCT,
                repack_result,
                EnrichmentTier.TIER_2,
                source_url,
                "/document//performance/actDefinition/code@code",
                ",".join(sorted(code for code in repack_codes if code)) or "absent",
                "C73606/C73607 proves repack/relabel; absence remains UNKNOWN and is never "
                "treated as proof of a non-repackaged product.",
                raw_hash=raw_hash,
                observed_version=observed_version,
                retrieved_at=retrieved_at,
            ),
            self._draft(
                EvidenceType.SUPPORTED_DOCUMENT_STRUCTURE,
                structure_result,
                EnrichmentTier.TIER_2,
                source_url,
                "/document",
                "urn:hl7-org:v3 document identity/code/active ingredient",
                "The extractor found the required documented SPL structures."
                if structure_result is EvidenceResult.PROVEN_TRUE
                else "One or more required SPL structures were absent or unsupported.",
                raw_hash=raw_hash,
                observed_version=observed_version,
                retrieved_at=retrieved_at,
            ),
        )
        return XMLExtraction(drafts, observed_set_id, observed_version, document_code)

    def materialize(
        self,
        drafts: tuple[AssertionDraft, ...],
        *,
        parent_discovery_snapshot_id: str,
        enrichment_run_id: str,
        enrichment_snapshot_id: str,
        candidate: CandidateEvidence,
    ) -> tuple[EvidenceAssertion, ...]:
        values: list[EvidenceAssertion] = []
        for draft in drafts:
            identity_payload: dict[str, object] = {
                "candidate_id": candidate.candidate_id,
                "diagnostic": draft.diagnostic,
                "evidence_type": draft.evidence_type,
                "expected_source_version": candidate.source_version or "",
                "extraction_rule_version": self.extraction_rule_version,
                "extractor_version": self.extractor_version,
                "observed_source_version": draft.observed_source_version,
                "parent_discovery_snapshot_id": parent_discovery_snapshot_id,
                "raw_response_sha256": draft.raw_response_sha256,
                "result": draft.result,
                "set_id": candidate.set_id or "",
                "source_field_or_code": draft.source_field_or_code,
                "source_locator": draft.source_locator,
                "source_url_identity": draft.source_url_identity,
                "source_response_sha256s": draft.source_response_sha256s,
                "tier": draft.tier,
            }
            identity = evidence_identity(identity_payload)
            values.append(
                EvidenceAssertion(
                    assertion_id=evidence_assertion_id(identity),
                    canonical_evidence_identity=identity,
                    parent_discovery_snapshot_id=parent_discovery_snapshot_id,
                    enrichment_run_id=enrichment_run_id,
                    enrichment_snapshot_id=enrichment_snapshot_id,
                    candidate_id=candidate.candidate_id,
                    set_id=candidate.set_id or "",
                    expected_source_version=candidate.source_version or "",
                    observed_source_version=draft.observed_source_version,
                    evidence_type=draft.evidence_type,
                    result=draft.result,
                    tier=draft.tier,
                    raw_response_sha256=draft.raw_response_sha256,
                    source_url_identity=draft.source_url_identity,
                    source_locator=draft.source_locator,
                    source_field_or_code=draft.source_field_or_code,
                    extraction_rule_version=self.extraction_rule_version,
                    extractor_version=self.extractor_version,
                    diagnostic=draft.diagnostic,
                    retrieved_at=draft.retrieved_at,
                    source_response_sha256s=draft.source_response_sha256s,
                )
            )
        return tuple(values)

    @staticmethod
    def with_snapshot(
        assertions: tuple[EvidenceAssertion, ...], snapshot_id: str
    ) -> tuple[EvidenceAssertion, ...]:
        return tuple(
            replace(assertion, enrichment_snapshot_id=snapshot_id)
            for assertion in assertions
        )

    @staticmethod
    def _draft(
        evidence_type: EvidenceType,
        result: EvidenceResult,
        tier: EnrichmentTier,
        source_url: str,
        locator: str,
        field_or_code: str,
        diagnostic: str,
        *,
        raw_hash: str | None = None,
        observed_version: str | None = None,
        retrieved_at: datetime | None = None,
        source_response_hashes: tuple[str, ...] = (),
    ) -> AssertionDraft:
        return AssertionDraft(
            evidence_type=evidence_type,
            result=result,
            tier=tier,
            raw_response_sha256=raw_hash,
            source_url_identity=source_url,
            source_locator=locator,
            source_field_or_code=field_or_code,
            diagnostic=diagnostic,
            observed_source_version=observed_version,
            retrieved_at=retrieved_at,
            source_response_sha256s=(
                source_response_hashes
                if source_response_hashes
                else ((raw_hash,) if raw_hash is not None else ())
            ),
        )


def _packaging_active_ingredient_names(
    pages: tuple[CandidateDetailPage, ...],
) -> tuple[list[str], bool]:
    names: list[str] = []
    malformed = False
    for page in sorted(pages, key=lambda value: value.page_number):
        for product in page.products:
            active = product.get("active_ingredients")
            product_has_name = False
            if isinstance(active, list):
                product_names, invalid_active = _ingredient_names(active)
                names.extend(product_names)
                product_has_name = bool(product_names)
                malformed = malformed or invalid_active
            elif active is not None:
                malformed = True
            parts = product.get("parts")
            part_values: list[object]
            if isinstance(parts, dict):
                part_values = list(parts.values())
            elif isinstance(parts, list):
                part_values = list(parts)
            elif parts is None:
                part_values = []
            else:
                malformed = True
                part_values = []
            for part in part_values:
                if not isinstance(part, dict):
                    malformed = True
                    continue
                part_active = part.get("active_ingredients")
                if not isinstance(part_active, list):
                    malformed = True
                    continue
                part_names, invalid_part = _ingredient_names(part_active)
                names.extend(part_names)
                product_has_name = product_has_name or bool(part_names)
                malformed = malformed or invalid_part
            if not product_has_name:
                malformed = True
    return names, malformed


def _ingredient_names(values: list[object]) -> tuple[list[str], bool]:
    names: list[str] = []
    malformed = False
    for value in values:
        if not isinstance(value, dict):
            malformed = True
            continue
        name = value.get("name")
        if isinstance(name, str) and name.strip():
            names.append(name.strip())
        else:
            malformed = True
    return names, malformed


def _normalize_name(value: str) -> str:
    return _SPACE.sub(" ", value.strip()).casefold()


def _namespace(tag: str) -> str:
    return tag[1:].split("}", 1)[0] if tag.startswith("{") and "}" in tag else ""


def _local_name(tag: str) -> str:
    return tag.split("}", 1)[-1]


def _qualified(namespace: str, local_name: str) -> str:
    return f"{{{namespace}}}{local_name}" if namespace else local_name

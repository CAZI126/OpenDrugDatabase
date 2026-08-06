"""Versioned deterministic SPL section-to-concept rules."""

from __future__ import annotations

import re

from odd.constants import MAPPING_VERSION
from odd.models import SemanticMapping, SourceSection

CODE_MAPPINGS = {
    "34066-1": "boxed_warning",
    "34067-9": "indications_and_usage",
    "34068-7": "dosage_and_administration",
    "43678-2": "dosage_forms_and_strengths",
    "34070-3": "contraindications",
    "43685-7": "warnings_and_precautions",
    "34084-4": "adverse_reactions",
    "34073-7": "drug_interactions",
    "43684-0": "use_in_specific_populations",
    "42228-7": "pregnancy",
    "77290-5": "lactation",
    "34081-0": "pediatric_use",
    "34082-8": "geriatric_use",
    "34088-5": "overdosage",
    "34090-1": "clinical_pharmacology",
    "34092-7": "clinical_studies",
    "34069-5": "how_supplied",
    "44425-7": "storage_and_handling",
}

HEADING_MAPPINGS = {
    "renal impairment": "renal_impairment",
    "hepatic impairment": "hepatic_impairment",
    "how supplied": "how_supplied",
    "storage and handling": "storage_and_handling",
}


def map_section(section: SourceSection) -> SemanticMapping | None:
    concept = CODE_MAPPINGS.get(section.source_section_code or "")
    method = "loinc_code_exact"
    if concept is None and section.original_heading:
        normalized_heading = _normalized_heading(section.original_heading)
        concept = HEADING_MAPPINGS.get(normalized_heading)
        method = "normalized_heading_exact"
    if concept is None:
        return None
    return SemanticMapping(
        section_id=section.section_id,
        normalized_concept=concept,
        mapping_method=method,
        mapping_version=MAPPING_VERSION,
        confidence=1.0,
        deterministic_status="deterministic",
    )


def _normalized_heading(value: str) -> str:
    lowered = value.casefold().strip()
    without_number = re.sub(r"^\d+(?:\.\d+)*\s*", "", lowered)
    return re.sub(r"\s+", " ", without_number).strip()

"""Deterministic SPL parsing and clinical-text preservation tests."""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from odd.constants import INITIAL_CONCEPTS, MAPPING_VERSION, PARSER_VERSION, SCHEMA_VERSION
from odd.errors import MalformedXML, ProvenanceValidationFailure, UnsupportedDocumentStructure
from odd.models import ConceptStatus, SectionContentStatus, SourceIdentity, StructuredNode
from odd.parsers.spl.parser import SPLParser
from odd.provenance.canonical import canonical_normalized_json_bytes
from odd.provenance.hashing import sha256_bytes
from tests.odd_support import ELIQUIS_XML, NOW, SET_ID, SOURCE_VERSION


def identity(xml: bytes | None = None) -> SourceIdentity:
    content = xml if xml is not None else ELIQUIS_XML.read_bytes()
    return SourceIdentity(
        authority="FDA",
        provider="DailyMed",
        jurisdiction="United States",
        source_document_id=SET_ID,
        source_version=SOURCE_VERSION,
        source_url="fixture://eliquis-v30",
        retrieved_at=NOW,
        raw_sha256=sha256_bytes(content),
    )


def parsed():
    xml = ELIQUIS_XML.read_bytes()
    return SPLParser().parse(xml, identity(xml))


def test_extracts_document_identity_and_version_dimensions() -> None:
    result = parsed()
    document = result.document
    assert document.source_identity.source_document_id == SET_ID
    assert document.source_identity.source_version == "30"
    assert document.source_instance_id == "c6b2240a-a9d6-4dd9-9bc4-b42dc90c0d2f"
    assert document.parser_version == PARSER_VERSION
    assert document.schema_version == SCHEMA_VERSION
    assert document.mapping_version == MAPPING_VERSION


def test_extracts_explicit_product_metadata() -> None:
    document = parsed().document
    assert document.generic_name == "apixaban"
    assert document.brand_names == ("ELIQUIS",)
    assert document.dosage_forms == ("TABLET, FILM COATED",)
    assert document.routes == ("ORAL",)
    assert document.active_ingredients == ("apixaban",)


def test_repeated_parsing_is_byte_deterministic() -> None:
    xml = ELIQUIS_XML.read_bytes()
    parser = SPLParser()
    first = canonical_normalized_json_bytes(parser.parse(xml, identity(xml)))
    second = canonical_normalized_json_bytes(parser.parse(xml, identity(xml)))
    assert first == second


def test_retrieval_timestamp_does_not_change_normalized_bytes() -> None:
    xml = ELIQUIS_XML.read_bytes()
    first_identity = identity(xml)
    second_identity = replace(
        first_identity,
        retrieved_at=datetime(2030, 1, 1, tzinfo=UTC),
        source_url="https://mirror.invalid/label.xml",
    )
    parser = SPLParser()
    assert canonical_normalized_json_bytes(parser.parse(xml, first_identity)) == (
        canonical_normalized_json_bytes(parser.parse(xml, second_identity))
    )


def test_stable_preorder_section_sequence() -> None:
    sections = parsed().sections
    assert [item.sequence_index for item in sections] == list(range(21))
    assert sections[1].original_heading == "1 INDICATIONS AND USAGE"
    assert sections[2].original_heading == "1.1 Adult patients"
    assert sections[3].original_heading == "2 DOSAGE AND ADMINISTRATION"


@pytest.mark.parametrize(
    ("concept", "heading"),
    [
        ("indications_and_usage", "1 INDICATIONS AND USAGE"),
        ("contraindications", "4 CONTRAINDICATIONS"),
        ("warnings_and_precautions", "5 WARNINGS AND PRECAUTIONS"),
        ("drug_interactions", "7 DRUG INTERACTIONS"),
    ],
)
def test_required_concepts_are_extracted(concept: str, heading: str) -> None:
    result = parsed()
    section_ids = {
        item.section_id for item in result.semantic_mappings if item.normalized_concept == concept
    }
    matching = [item for item in result.sections if item.section_id in section_ids]
    assert [item.original_heading for item in matching] == [heading]


def test_missing_section_remains_absent() -> None:
    status = {
        item.normalized_concept: item.status for item in parsed().concept_statuses
    }
    assert set(status) == set(INITIAL_CONCEPTS)
    assert status["clinical_studies"] is ConceptStatus.ABSENT


def test_present_but_empty_is_distinct_from_absent() -> None:
    result = parsed()
    lactation = next(
        item for item in result.sections if item.original_heading == "8.2 Lactation"
    )
    assert lactation.content_status is SectionContentStatus.PRESENT_EMPTY
    statuses = {item.normalized_concept: item.status for item in result.concept_statuses}
    assert statuses["lactation"] is ConceptStatus.PRESENT_EMPTY
    assert statuses["clinical_studies"] is ConceptStatus.ABSENT


def test_empty_mapped_parent_with_populated_child_makes_concept_present() -> None:
    xml = ELIQUIS_XML.read_bytes().replace(
        b"""<title>8.2 Lactation</title>
              <text/>""",
        b"""<title>8.2 Lactation</title>
              <text/>
              <component>
                <section>
                  <code code="42229-5"/>
                  <title>Risk Summary</title>
                  <text><paragraph>Nested source text is present.</paragraph></text>
                </section>
              </component>""",
    )
    result = SPLParser().parse(xml, identity(xml))
    lactation = next(
        item for item in result.sections if item.original_heading == "8.2 Lactation"
    )
    status = next(
        item for item in result.concept_statuses if item.normalized_concept == "lactation"
    )
    assert lactation.content_status is SectionContentStatus.PRESENT_EMPTY
    assert status.status is ConceptStatus.PRESENT


def test_unknown_sections_remain_stored_and_unmapped() -> None:
    result = parsed()
    unknown = next(item for item in result.sections if item.source_section_code == "99999-9")
    mapped_ids = {item.section_id for item in result.semantic_mappings}
    assert unknown.original_text.startswith("This source section")
    assert unknown.section_id not in mapped_ids


def test_nested_subsection_relationships_are_preserved() -> None:
    result = parsed()
    parent = next(
        item
        for item in result.sections
        if item.original_heading == "8 USE IN SPECIFIC POPULATIONS"
    )
    child = next(
        item for item in result.sections if item.original_heading == "8.6 Renal Impairment"
    )
    assert child.parent_section_id == parent.section_id
    assert child.depth == parent.depth + 1


def test_section_hash_and_locator_are_stable() -> None:
    first = parsed().sections
    second = parsed().sections
    assert [(item.source_locator, item.section_sha256) for item in first] == [
        (item.source_locator, item.section_sha256) for item in second
    ]
    assert all(item.source_locator.startswith("/document[1]/") for item in first)
    assert len({item.source_locator for item in first}) == len(first)


def test_table_structure_is_preserved_with_traceable_cells() -> None:
    interactions = next(
        item for item in parsed().sections if item.original_heading == "7 DRUG INTERACTIONS"
    )
    assert interactions.structured_content is not None
    nodes = list(_walk(interactions.structured_content))
    assert any(item.tag == "table" for item in nodes)
    assert [item.text for item in nodes if item.tag == "td"] == [
        "Strong dual inhibitors",
        "Reduce the dose by 50% in specified patients.",
        "Rifampin",
        "Avoid concomitant use.",
    ]
    assert "Concomitant drug Source-label instruction" in interactions.original_text
    assert "Strong dual inhibitors Reduce the dose by 50%" in interactions.original_text
    assert "Rifampin Avoid concomitant use." in interactions.original_text
    assert all(item.locator.startswith(interactions.source_locator) for item in nodes)


def test_clinical_numeric_values_units_and_operators_are_preserved() -> None:
    dosage = next(
        item for item in parsed().sections if item.original_heading == "2 DOSAGE AND ADMINISTRATION"
    )
    for protected_text in ("5 mg", "2.5 mg", "≥ 80 years", "≤ 60 kg", "≥ 1.5 mg/dL"):
        assert protected_text in dosage.original_text


def test_clinical_negation_and_warning_qualifiers_are_preserved() -> None:
    result = parsed()
    boxed = result.sections[0].original_text
    warnings = next(
        item.original_text
        for item in result.sections
        if item.original_heading == "5 WARNINGS AND PRECAUTIONS"
    )
    assert "Do not discontinue" in boxed
    assert "may increase this risk" in warnings
    assert "not recommended" in warnings


def test_malformed_xml_failure_is_explicit() -> None:
    xml = b'<document xmlns="urn:hl7-org:v3"><id root="broken">'
    with pytest.raises(MalformedXML):
        SPLParser().parse(xml, identity(xml))


def test_non_hl7_document_is_unsupported() -> None:
    xml = b'<document><id root="doc"/></document>'
    with pytest.raises(UnsupportedDocumentStructure):
        SPLParser().parse(xml, identity(xml))


def test_source_identity_mismatch_fails_provenance_validation() -> None:
    xml = ELIQUIS_XML.read_bytes()
    with pytest.raises(ProvenanceValidationFailure):
        SPLParser().parse(xml, replace(identity(xml), source_version="29"))


def test_doctype_is_rejected_before_xml_parsing() -> None:
    xml = b'<!DOCTYPE document><document xmlns="urn:hl7-org:v3"/>'
    with pytest.raises(UnsupportedDocumentStructure, match="DOCTYPE"):
        SPLParser().parse(xml, identity(xml))


# -- a real label that states no title of its own --------------------------
def titleless() -> bytes:
    """The preserved fixture with its document title removed, and nothing else.

    This is the shape the cohort run actually found: whole, valid SPLs that
    simply carry no document-level ``<title>``.
    """

    xml = ELIQUIS_XML.read_bytes()
    without = re.sub(rb"\s*<title>.*?</title>", b"", xml, count=1)
    assert without != xml, "the fixture must carry a title to remove"
    return without


def test_a_document_stating_no_title_still_parses() -> None:
    xml = titleless()

    document = SPLParser().parse(xml, identity(xml)).document

    assert document.title is None
    assert document.source_identity.source_document_id == SET_ID
    assert document.source_identity.source_version == SOURCE_VERSION
    assert document.source_identity.raw_sha256 == sha256_bytes(xml)


def test_a_missing_title_is_never_filled_in_from_what_the_label_does_say() -> None:
    """The absence must not be repaired from the brand, generic name, or id."""

    xml = titleless()

    document = SPLParser().parse(xml, identity(xml)).document

    assert document.title is None
    # These are stated, and none of them may stand in for the title.
    assert document.generic_name
    assert document.brand_names
    assert document.active_ingredients
    for stated in (
        document.generic_name,
        *document.brand_names,
        *document.active_ingredients,
        SET_ID,
        SOURCE_VERSION,
    ):
        assert document.title != stated


def test_sections_are_still_extracted_from_a_titleless_document() -> None:
    xml = titleless()

    result = SPLParser().parse(xml, identity(xml))

    assert result.sections
    assert all(section.section_sha256 for section in result.sections)
    assert all(section.source_locator for section in result.sections)
    with_title = SPLParser().parse(ELIQUIS_XML.read_bytes(), identity())
    assert len(result.sections) == len(with_title.sections)


def test_a_stated_title_is_unchanged_by_allowing_absent_ones() -> None:
    document = parsed().document

    assert document.title == (
        "ELIQUIS (apixaban) tablets, for oral use — reduced ODD test fixture"
    )


def test_an_empty_title_states_no_more_than_a_missing_one() -> None:
    xml = re.sub(
        rb"<title>.*?</title>", b"<title>   </title>", ELIQUIS_XML.read_bytes(), count=1
    )

    document = SPLParser().parse(xml, identity(xml)).document

    assert document.title is None, "whitespace is not a title the label stated"


def test_search_metadata_reads_a_titleless_document_the_same_way() -> None:
    xml = titleless()

    metadata = SPLParser().parse_document_search_metadata(xml, identity(xml))

    assert metadata.title is None
    assert metadata.document_type
    assert metadata.active_ingredients


def test_identity_and_type_are_still_required_when_the_title_is_not() -> None:
    """Allowing an absent title must not wave through a broken document."""

    without_code = re.sub(rb"\s*<code[^>]*/>", b"", ELIQUIS_XML.read_bytes(), count=1)
    assert without_code != ELIQUIS_XML.read_bytes()
    with pytest.raises(UnsupportedDocumentStructure):
        SPLParser().parse(without_code, identity(without_code))

    without_set_id = re.sub(rb'\s*<setId[^>]*/>', b"", ELIQUIS_XML.read_bytes(), count=1)
    assert without_set_id != ELIQUIS_XML.read_bytes()
    with pytest.raises(UnsupportedDocumentStructure):
        SPLParser().parse(without_set_id, identity(without_set_id))


def _walk(node: StructuredNode):
    yield node
    for child in node.children:
        yield from _walk(child)

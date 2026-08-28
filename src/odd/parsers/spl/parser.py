"""Deterministic, namespace-aware parser for the ODD-001 SPL subset."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from xml.etree import ElementTree

from odd.constants import INITIAL_CONCEPTS, MAPPING_VERSION, PARSER_VERSION, SCHEMA_VERSION
from odd.errors import (
    MalformedXML,
    ODDError,
    ParserFailure,
    ProvenanceValidationFailure,
    UnsupportedDocumentStructure,
)
from odd.models import (
    ConceptPresence,
    ConceptStatus,
    NormalizedDocument,
    Product,
    RegulatoryDocument,
    SectionContentStatus,
    SemanticMapping,
    SourceIdentity,
    SourceSection,
    StructuredNode,
)
from odd.parsers.spl.mapping import map_section
from odd.provenance.hashing import sha256_bytes
from odd.provenance.identifiers import product_id, regulatory_document_id, section_id
from odd.provenance.section_hash import section_sha256

SPL_NAMESPACE = "urn:hl7-org:v3"
Q = f"{{{SPL_NAMESPACE}}}"
MAX_XML_BYTES = 64 * 1024 * 1024
_FORBIDDEN_DECLARATION = re.compile(br"<!\s*(?:DOCTYPE|ENTITY)\b", flags=re.IGNORECASE)
_WHITESPACE = re.compile(r"\s+")
_BLOCK_ELEMENTS = {
    "br",
    "caption",
    "item",
    "list",
    "paragraph",
    "table",
    "tbody",
    "td",
    "tfoot",
    "th",
    "thead",
    "tr",
}


@dataclass(frozen=True, slots=True)
class SectionEvidence:
    """Source-derived section content read from one ``section`` element."""

    source_section_code: str | None
    original_heading: str | None
    original_text: str
    structured_content: StructuredNode | None
    content_status: SectionContentStatus
    section_sha256: str
    source_locator: str


@dataclass(frozen=True, slots=True)
class DocumentSearchMetadata:
    """The source-stated document fields used by preserved-document discovery.

    Reading these fields does not build section locators, structured section
    trees, semantic mappings, or concept-presence results.  It is therefore the
    appropriate parser boundary for the rebuildable document catalog, while the
    full :meth:`SPLParser.parse` path remains unchanged for evidence extraction.
    """

    document_type: str
    effective_date: date | None
    title: str
    generic_name: str | None
    brand_names: tuple[str, ...]
    active_ingredients: tuple[str, ...]


def parse_document_root(
    xml_bytes: bytes,
    *,
    expected_raw_sha256: str | None = None,
) -> ElementTree.Element:
    """Apply the ODD-001 input guards and return the HL7 v3 document root."""

    if not xml_bytes:
        raise MalformedXML("SPL XML is empty")
    if len(xml_bytes) > MAX_XML_BYTES:
        raise UnsupportedDocumentStructure(
            f"SPL XML exceeds the supported {MAX_XML_BYTES}-byte limit"
        )
    if _FORBIDDEN_DECLARATION.search(xml_bytes):
        raise UnsupportedDocumentStructure(
            "SPL XML with a DOCTYPE or entity declaration is unsupported"
        )
    if expected_raw_sha256 is not None and sha256_bytes(xml_bytes) != expected_raw_sha256:
        raise ProvenanceValidationFailure(
            "parser input bytes do not match SourceIdentity.raw_sha256"
        )
    try:
        root = ElementTree.fromstring(xml_bytes)
    except ElementTree.ParseError as exc:
        raise MalformedXML(f"malformed SPL XML: {exc}") from exc
    if root.tag != f"{Q}document":
        raise UnsupportedDocumentStructure(
            "root element must be an HL7 v3 document",
            details={"root_tag": root.tag},
        )
    return root


def build_locator_map(root: ElementTree.Element) -> dict[ElementTree.Element, str]:
    """Map every element to its stable local-name/position locator."""

    return _locator_map(root)


def read_section_evidence(
    section_element: ElementTree.Element,
    locators: dict[ElementTree.Element, str],
) -> SectionEvidence:
    """Read one section's source-derived content and its content hash.

    This is the single definition used both when extracting a document and when
    re-reading the same passage from preserved raw bytes, so a locator always
    resolves to the content its hash was taken over.
    """

    code_element = _direct_child(section_element, "code")
    title_element = _direct_child(section_element, "title")
    text_element = _direct_child(section_element, "text")
    source_code = _attribute(code_element, "code")
    heading = _element_text(title_element)
    original_text = _element_text(text_element) or ""
    if text_element is None:
        content_status = SectionContentStatus.TEXT_ELEMENT_ABSENT
        structured = None
    elif original_text:
        content_status = SectionContentStatus.PRESENT
        structured = _structured_node(text_element, locators)
    else:
        content_status = SectionContentStatus.PRESENT_EMPTY
        structured = _structured_node(text_element, locators)
    return SectionEvidence(
        source_section_code=source_code,
        original_heading=heading,
        original_text=original_text,
        structured_content=structured,
        content_status=content_status,
        section_sha256=section_sha256(
            source_section_code=source_code,
            original_heading=heading,
            original_text=original_text,
            structured_content=structured,
        ),
        source_locator=locators[section_element],
    )


class SPLParser:
    """Extract only explicit SPL content and preserve section hierarchy."""

    parser_version = PARSER_VERSION
    schema_version = SCHEMA_VERSION
    mapping_version = MAPPING_VERSION

    def parse_document_search_metadata(
        self, xml_bytes: bytes, identity: SourceIdentity
    ) -> DocumentSearchMetadata:
        """Read exactly the fields used by document discovery from preserved XML."""

        try:
            root = parse_document_root(xml_bytes, expected_raw_sha256=identity.raw_sha256)

            # Keep the same document-level guards as the full parser.  In
            # particular, a title-less SPL remains unsupported for this change.
            _required_attribute(root, "id", "root")
            set_id = _required_attribute(root, "setId", "root")
            source_version = _required_attribute(root, "versionNumber", "value")
            if (set_id.casefold(), source_version) != (
                identity.source_document_id.casefold(),
                identity.source_version,
            ):
                raise ProvenanceValidationFailure(
                    "SPL identity differs from immutable raw metadata",
                    details={
                        "metadata_set_id": identity.source_document_id,
                        "metadata_source_version": identity.source_version,
                        "xml_set_id": set_id,
                        "xml_source_version": source_version,
                    },
                )

            title = _element_text(root.find(f"{Q}title"))
            if not title:
                raise UnsupportedDocumentStructure(
                    "SPL document title is required for ODD-001"
                )
            code = root.find(f"{Q}code")
            document_type = _attribute(code, "displayName") or _attribute(code, "code")
            if not document_type:
                raise UnsupportedDocumentStructure(
                    "SPL document type code is required for ODD-001"
                )

            parent_map = {child: parent for parent in root.iter() for child in parent}
            product_values = _extract_products(root, parent_map)
            brand_names = _deduplicate(
                product.brand_name for product in product_values if product.brand_name
            )
            generic_names = _extract_generic_names(root)
            return DocumentSearchMetadata(
                document_type=document_type,
                effective_date=_effective_date(root.find(f"{Q}effectiveTime")),
                title=title,
                generic_name=generic_names[0] if generic_names else None,
                brand_names=brand_names,
                active_ingredients=_extract_active_ingredients(root),
            )
        except ODDError:
            raise
        except Exception as exc:  # pragma: no cover - defensive error boundary
            raise ParserFailure(f"unexpected SPL parser failure: {exc}") from exc

    def parse(self, xml_bytes: bytes, identity: SourceIdentity) -> NormalizedDocument:
        try:
            return self._parse(xml_bytes, identity)
        except ODDError:
            raise
        except Exception as exc:  # pragma: no cover - defensive error boundary
            raise ParserFailure(f"unexpected SPL parser failure: {exc}") from exc

    def _parse(self, xml_bytes: bytes, identity: SourceIdentity) -> NormalizedDocument:
        root = parse_document_root(xml_bytes, expected_raw_sha256=identity.raw_sha256)

        source_instance_id = _required_attribute(root, "id", "root")
        set_id = _required_attribute(root, "setId", "root")
        source_version = _required_attribute(root, "versionNumber", "value")
        if (set_id.casefold(), source_version) != (
            identity.source_document_id.casefold(),
            identity.source_version,
        ):
            raise ProvenanceValidationFailure(
                "SPL identity differs from immutable raw metadata",
                details={
                    "metadata_set_id": identity.source_document_id,
                    "metadata_source_version": identity.source_version,
                    "xml_set_id": set_id,
                    "xml_source_version": source_version,
                },
            )

        title_element = root.find(f"{Q}title")
        title = _element_text(title_element)
        if not title:
            raise UnsupportedDocumentStructure("SPL document title is required for ODD-001")
        code = root.find(f"{Q}code")
        document_type = _attribute(code, "displayName") or _attribute(code, "code")
        if not document_type:
            raise UnsupportedDocumentStructure("SPL document type code is required for ODD-001")
        language_element = root.find(f"{Q}languageCode")
        language = _attribute(language_element, "code")
        effective_date = _effective_date(root.find(f"{Q}effectiveTime"))

        parent_map = {child: parent for parent in root.iter() for child in parent}
        locators = _locator_map(root)
        product_values = _extract_products(root, parent_map)
        brand_names = _deduplicate(
            product.brand_name for product in product_values if product.brand_name
        )
        dosage_forms = _deduplicate(
            product.dosage_form for product in product_values if product.dosage_form
        )
        routes = _deduplicate(product.route for product in product_values if product.route)
        generic_names = _extract_generic_names(root)
        active_ingredients = _extract_active_ingredients(root)

        document_identifier = regulatory_document_id(
            identity,
            parser_version=self.parser_version,
            schema_version=self.schema_version,
            mapping_version=self.mapping_version,
        )
        products = tuple(
            Product(
                product_id=product_id(
                    document_identifier,
                    index,
                    item.brand_name,
                    item.dosage_form,
                    item.route,
                ),
                brand_name=item.brand_name,
                dosage_form=item.dosage_form,
                route=item.route,
                sequence_index=index,
            )
            for index, item in enumerate(product_values)
        )
        document = RegulatoryDocument(
            document_id=document_identifier,
            source_identity=identity,
            source_instance_id=source_instance_id,
            document_type=document_type,
            language=language,
            effective_date=effective_date,
            title=title,
            generic_name=generic_names[0] if generic_names else None,
            brand_names=brand_names,
            dosage_forms=dosage_forms,
            routes=routes,
            active_ingredients=active_ingredients,
            parser_version=self.parser_version,
            schema_version=self.schema_version,
            mapping_version=self.mapping_version,
        )

        sections = self._sections(root, locators, document_identifier)
        mappings = tuple(
            mapping for section in sections if (mapping := map_section(section)) is not None
        )
        concept_statuses = _concept_statuses(sections, mappings)
        return NormalizedDocument(
            document=document,
            products=products,
            sections=sections,
            semantic_mappings=mappings,
            concept_statuses=concept_statuses,
        )

    @staticmethod
    def _sections(
        root: ElementTree.Element,
        locators: dict[ElementTree.Element, str],
        document_id: str,
    ) -> tuple[SourceSection, ...]:
        bodies = [item for item in root.iter() if item.tag == f"{Q}structuredBody"]
        if len(bodies) > 1:
            raise UnsupportedDocumentStructure("multiple structuredBody elements are unsupported")
        if not bodies:
            return ()

        sections: list[SourceSection] = []

        def visit(section_element: ElementTree.Element, parent_id: str | None, depth: int) -> None:
            sequence = len(sections)
            evidence = read_section_evidence(section_element, locators)
            identifier = section_id(
                document_id, evidence.source_locator, evidence.section_sha256
            )
            section = SourceSection(
                section_id=identifier,
                document_id=document_id,
                source_section_code=evidence.source_section_code,
                original_heading=evidence.original_heading,
                original_text=evidence.original_text,
                sequence_index=sequence,
                section_sha256=evidence.section_sha256,
                source_locator=evidence.source_locator,
                parent_section_id=parent_id,
                depth=depth,
                content_status=evidence.content_status,
                structured_content=evidence.structured_content,
            )
            sections.append(section)
            for component in _direct_children(section_element, "component"):
                for child_section in _direct_children(component, "section"):
                    visit(child_section, identifier, depth + 1)

        for component in _direct_children(bodies[0], "component"):
            for top_level_section in _direct_children(component, "section"):
                visit(top_level_section, None, 0)
        return tuple(sections)


@dataclass(frozen=True, slots=True)
class _ProductValue:
    brand_name: str | None
    dosage_form: str | None
    route: str | None


def _extract_products(
    root: ElementTree.Element,
    parent_map: dict[ElementTree.Element, ElementTree.Element],
) -> tuple[_ProductValue, ...]:
    products: list[_ProductValue] = []
    for element in root.iter():
        if _local_name(element.tag) not in {"manufacturedProduct", "manufacturedMedicine"}:
            continue
        name = _element_text(_direct_child(element, "name"))
        form_element = _direct_child(element, "formCode")
        dosage_form = _attribute(form_element, "displayName") or _attribute(form_element, "code")
        has_generic = any(_local_name(item.tag) == "genericMedicine" for item in element.iter())
        if not name or (dosage_form is None and not has_generic):
            continue
        ancestor = element
        while ancestor in parent_map and _local_name(ancestor.tag) != "subject":
            ancestor = parent_map[ancestor]
        routes = _deduplicate(
            (_attribute(item, "displayName") or _attribute(item, "code"))
            for item in ancestor.iter()
            if _local_name(item.tag) == "routeCode"
        )
        if routes:
            products.extend(_ProductValue(name, dosage_form, route) for route in routes)
        else:
            products.append(_ProductValue(name, dosage_form, None))
    return tuple(products)


def _extract_generic_names(root: ElementTree.Element) -> tuple[str, ...]:
    values: list[str] = []
    for element in root.iter():
        if _local_name(element.tag) != "genericMedicine":
            continue
        name = _element_text(_direct_child(element, "name"))
        if name:
            values.append(name)
    return _deduplicate(values)


def _extract_active_ingredients(root: ElementTree.Element) -> tuple[str, ...]:
    values: list[str] = []
    for ingredient in root.iter():
        if _local_name(ingredient.tag) != "ingredient":
            continue
        class_code = ingredient.attrib.get("classCode", "")
        if class_code not in {"ACTIB", "ACTIM"}:
            continue
        for substance in ingredient.iter():
            if _local_name(substance.tag) != "ingredientSubstance":
                continue
            name = _element_text(_direct_child(substance, "name"))
            if name:
                values.append(name)
    return _deduplicate(values)


def _concept_statuses(
    sections: tuple[SourceSection, ...],
    mappings: tuple[SemanticMapping, ...],
) -> tuple[ConceptPresence, ...]:
    section_by_id = {item.section_id: item for item in sections}
    children: dict[str, list[str]] = {}
    for section in sections:
        if section.parent_section_id is not None:
            children.setdefault(section.parent_section_id, []).append(section.section_id)

    def subtree_has_text(identifier: str) -> bool:
        section = section_by_id[identifier]
        if section.content_status == SectionContentStatus.PRESENT:
            return True
        return any(subtree_has_text(child) for child in children.get(identifier, []))

    result: list[ConceptPresence] = []
    for concept in INITIAL_CONCEPTS:
        section_ids = tuple(
            item.section_id for item in mappings if item.normalized_concept == concept
        )
        if not section_ids:
            status = ConceptStatus.ABSENT
        elif any(subtree_has_text(item) for item in section_ids):
            status = ConceptStatus.PRESENT
        else:
            status = ConceptStatus.PRESENT_EMPTY
        result.append(
            ConceptPresence(
                normalized_concept=concept,
                status=status,
                section_ids=section_ids,
            )
        )
    return tuple(result)


def _locator_map(root: ElementTree.Element) -> dict[ElementTree.Element, str]:
    result = {root: f"/{_local_name(root.tag)}[1]"}

    def visit(parent: ElementTree.Element) -> None:
        counts: dict[str, int] = {}
        for child in parent:
            local = _local_name(child.tag)
            counts[local] = counts.get(local, 0) + 1
            result[child] = f"{result[parent]}/{local}[{counts[local]}]"
            visit(child)

    visit(root)
    return result


def _structured_node(
    element: ElementTree.Element,
    locators: dict[ElementTree.Element, str],
) -> StructuredNode:
    return StructuredNode(
        tag=_local_name(element.tag),
        locator=locators[element],
        attributes=tuple(sorted((key, value) for key, value in element.attrib.items())),
        text=_normalize_whitespace(element.text),
        tail=_normalize_whitespace(element.tail),
        children=tuple(_structured_node(child, locators) for child in element),
    )


def _required_attribute(root: ElementTree.Element, child_name: str, attribute: str) -> str:
    child = root.find(f"{Q}{child_name}")
    value = _attribute(child, attribute)
    if not value:
        raise UnsupportedDocumentStructure(
            f"SPL {child_name}/@{attribute} is required for ODD-001"
        )
    return value


def _effective_date(element: ElementTree.Element | None) -> date | None:
    value = _attribute(element, "value")
    if value is None:
        return None
    if not re.fullmatch(r"\d{8}", value):
        raise UnsupportedDocumentStructure("SPL effectiveTime must use YYYYMMDD for ODD-001")
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError as exc:
        raise UnsupportedDocumentStructure("SPL effectiveTime is not a valid date") from exc


def _direct_child(element: ElementTree.Element, local_name: str) -> ElementTree.Element | None:
    return next((child for child in element if _local_name(child.tag) == local_name), None)


def _direct_children(
    element: ElementTree.Element, local_name: str
) -> tuple[ElementTree.Element, ...]:
    return tuple(child for child in element if _local_name(child.tag) == local_name)


def _attribute(element: ElementTree.Element | None, name: str) -> str | None:
    if element is None:
        return None
    value = element.attrib.get(name)
    return value.strip() if value and value.strip() else None


def _element_text(element: ElementTree.Element | None) -> str | None:
    if element is None:
        return None
    return _normalize_whitespace(_render_text(element))


def _render_text(element: ElementTree.Element) -> str:
    """Render text in source order with boundaries for block/table elements."""

    parts = [element.text or ""]
    for child in element:
        is_block = _local_name(child.tag) in _BLOCK_ELEMENTS
        if is_block:
            parts.append(" ")
        parts.append(_render_text(child))
        if is_block:
            parts.append(" ")
        parts.append(child.tail or "")
    return "".join(parts)


def _normalize_whitespace(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = _WHITESPACE.sub(" ", value).strip()
    return normalized or None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _deduplicate(values: Iterable[str | None]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value:
            continue
        key = value.casefold()
        if key not in seen:
            seen.add(key)
            result.append(value)
    return tuple(result)

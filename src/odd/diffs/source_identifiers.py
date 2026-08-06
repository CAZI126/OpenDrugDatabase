"""Recover source-owned SPL section identifiers without changing normalized output."""

from __future__ import annotations

import re
from xml.etree import ElementTree

from odd.errors import MalformedXML, UnsupportedDocumentStructure

SPL_NAMESPACE = "urn:hl7-org:v3"
Q = f"{{{SPL_NAMESPACE}}}"
MAX_XML_BYTES = 64 * 1024 * 1024
_FORBIDDEN_DECLARATION = re.compile(br"<!\s*(?:DOCTYPE|ENTITY)\b", flags=re.IGNORECASE)


def extract_section_xml_identifiers(xml_bytes: bytes) -> dict[str, str]:
    """Return parser-compatible source locator to direct ``section/id/@root``."""

    if not xml_bytes:
        raise MalformedXML("SPL XML is empty while extracting section identifiers")
    if len(xml_bytes) > MAX_XML_BYTES or _FORBIDDEN_DECLARATION.search(xml_bytes):
        raise UnsupportedDocumentStructure(
            "SPL XML is unsupported while extracting section identifiers"
        )
    try:
        root = ElementTree.fromstring(xml_bytes)
    except ElementTree.ParseError as exc:
        raise MalformedXML(
            f"malformed SPL XML while extracting section identifiers: {exc}"
        ) from exc
    if root.tag != f"{Q}document":
        raise UnsupportedDocumentStructure(
            "section identity extraction requires an HL7 v3 document"
        )
    locators = _locator_map(root)
    result: dict[str, str] = {}
    for element in root.iter(f"{Q}section"):
        source_id = _direct_child(element, "id")
        value = source_id.attrib.get("root", "").strip() if source_id is not None else ""
        if value:
            result[locators[element]] = value
    return result


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


def _direct_child(
    element: ElementTree.Element, local_name: str
) -> ElementTree.Element | None:
    return next((child for child in element if _local_name(child.tag) == local_name), None)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag

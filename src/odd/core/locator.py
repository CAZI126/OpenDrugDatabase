"""Resolve an evidence locator back to its element in the preserved raw XML.

An evidence locator is the position ODD records for every extracted passage,
for example::

    /document[1]/component[1]/structuredBody[1]/component[4]/section[1]

Each step is an XML local name plus its 1-based position among the siblings
that share that local name, in document order. The form is namespace-agnostic
on purpose: it must stay resolvable from the stored bytes alone, without the
database, the parser's identifiers, or any ODD state.
"""

from __future__ import annotations

import re
from xml.etree import ElementTree

from odd.errors import ProvenanceValidationFailure

_SEGMENT = re.compile(r"^([A-Za-z_][A-Za-z0-9_.-]*)\[([1-9][0-9]{0,6})\]$")


def parse_locator(locator: str) -> tuple[tuple[str, int], ...]:
    """Parse a locator into ``(local_name, position)`` steps."""

    if not locator.startswith("/") or locator.startswith("//"):
        raise ProvenanceValidationFailure(
            "evidence locator must be an absolute local-name path",
            details={"locator": locator},
        )
    steps: list[tuple[str, int]] = []
    for segment in locator[1:].split("/"):
        match = _SEGMENT.fullmatch(segment)
        if match is None:
            raise ProvenanceValidationFailure(
                "evidence locator segment is not a supported name[index] step",
                details={"locator": locator, "segment": segment},
            )
        steps.append((match.group(1), int(match.group(2))))
    return tuple(steps)


def resolve_locator(root: ElementTree.Element, locator: str) -> ElementTree.Element:
    """Return the element ``locator`` addresses, or explain why it does not resolve."""

    steps = parse_locator(locator)
    root_name, root_index = steps[0]
    if local_name(root.tag) != root_name or root_index != 1:
        raise ProvenanceValidationFailure(
            "evidence locator does not start at this document root",
            details={
                "locator": locator,
                "root_local_name": local_name(root.tag),
                "expected_root": f"{root_name}[{root_index}]",
            },
        )
    current = root
    for depth, (name, index) in enumerate(steps[1:], start=1):
        matches = [child for child in current if local_name(child.tag) == name]
        if index > len(matches):
            raise ProvenanceValidationFailure(
                "evidence locator does not resolve in the preserved raw source",
                details={
                    "available_siblings": len(matches),
                    "failed_step": f"{name}[{index}]",
                    "locator": locator,
                    "step_depth": depth,
                },
            )
        current = matches[index - 1]
    return current


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag

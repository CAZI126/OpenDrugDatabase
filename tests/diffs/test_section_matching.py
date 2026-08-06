from __future__ import annotations

from odd.diffs.matching import match_sections
from odd.models import SectionMatchMethod, SectionMatchStatus, StoredSection


def _section(
    identifier: str,
    sequence: int,
    *,
    code: str | None,
    xml_id: str | None,
    heading: str,
    text: str,
    locator: str,
    parent: str | None = None,
    depth: int = 0,
) -> StoredSection:
    return StoredSection(
        section_id=identifier,
        sequence_index=sequence,
        source_section_code=code,
        xml_identifier=xml_id,
        original_heading=heading,
        original_text=text,
        section_sha256=identifier.ljust(64, "0")[:64],
        source_locator=locator,
        parent_section_id=parent,
        depth=depth,
        content_status="present",
        structured_content=None,
        normalized_concepts=(),
    )


def test_stable_xml_identifier_matches_a_moved_and_renamed_section() -> None:
    old = _section(
        "old", 1, code="A", xml_id="stable", heading="Old", text="same", locator="/section[1]"
    )
    new = _section(
        "new", 9, code="B", xml_id="stable", heading="New", text="changed", locator="/section[7]"
    )

    match = match_sections((old,), (new,))[0]
    assert match.method == SectionMatchMethod.XML_IDENTIFIER
    assert match.status == SectionMatchStatus.EXACT
    assert match.old == old
    assert match.new == new


def test_unique_section_code_is_used_before_ordinal_position() -> None:
    old = _section(
        "old", 0, code="34067-9", xml_id=None, heading="Warnings", text="old", locator="/section[1]"
    )
    new = _section(
        "new", 4, code="34067-9", xml_id=None, heading="Warnings", text="new", locator="/section[5]"
    )

    assert match_sections((old,), (new,))[0].method == SectionMatchMethod.SECTION_CODE


def test_locator_alone_does_not_false_match_unrelated_replacement() -> None:
    old = _section(
        "old",
        0,
        code="A",
        xml_id=None,
        heading="Alpha",
        text="one two three",
        locator="/section[1]",
    )
    new = _section(
        "new",
        0,
        code="B",
        xml_id=None,
        heading="Beta",
        text="unrelated words only",
        locator="/section[1]",
    )
    matches = match_sections((old,), (new,))

    assert len(matches) == 2
    assert all(item.status == SectionMatchStatus.UNMATCHED for item in matches)


def test_heading_and_parent_preserve_nested_hierarchy() -> None:
    old_parent = _section(
        "old-parent",
        0,
        code=None,
        xml_id="parent",
        heading="Parent",
        text="",
        locator="/section[1]",
    )
    old_child = _section(
        "old-child",
        1,
        code=None,
        xml_id=None,
        heading="Nested",
        text="old",
        locator="/section[1]/section[1]",
        parent="old-parent",
        depth=1,
    )
    new_parent = _section(
        "new-parent",
        0,
        code=None,
        xml_id="parent",
        heading="Parent",
        text="",
        locator="/section[2]",
    )
    new_child = _section(
        "new-child",
        1,
        code=None,
        xml_id=None,
        heading="Nested",
        text="new",
        locator="/section[2]/section[1]",
        parent="new-parent",
        depth=1,
    )
    matches = match_sections((old_parent, old_child), (new_parent, new_child))

    child = next(item for item in matches if item.old == old_child)
    assert child.method == SectionMatchMethod.HEADING_AND_PARENT


def test_content_assisted_match_is_recorded_as_heuristic() -> None:
    text = "This stable source wording contains enough tokens for deterministic matching."
    old = _section(
        "old", 0, code=None, xml_id=None, heading="Old heading", text=text, locator="/section[1]"
    )
    new = _section(
        "new",
        1,
        code=None,
        xml_id=None,
        heading="Renamed heading",
        text=text,
        locator="/section[2]",
    )
    match = match_sections((old,), (new,))[0]

    assert match.method == SectionMatchMethod.CONTENT_ASSISTED
    assert match.status == SectionMatchStatus.HEURISTIC


def test_content_assisted_tie_is_left_unmatched_to_avoid_false_identity() -> None:
    text = "identical repeated content cannot establish which source section is which"
    old_one = _section(
        "old-1", 0, code=None, xml_id=None, heading="A", text=text, locator="/old[1]"
    )
    old_two = _section(
        "old-2", 1, code=None, xml_id=None, heading="B", text=text, locator="/old[2]"
    )
    new_one = _section(
        "new-1", 0, code=None, xml_id=None, heading="C", text=text, locator="/new[1]"
    )
    new_two = _section(
        "new-2", 1, code=None, xml_id=None, heading="D", text=text, locator="/new[2]"
    )
    matches = match_sections((old_one, old_two), (new_one, new_two))

    assert len(matches) == 4
    assert all(item.status == SectionMatchStatus.UNMATCHED for item in matches)


def test_unrelated_content_below_threshold_is_not_matched() -> None:
    old = _section(
        "old",
        0,
        code=None,
        xml_id=None,
        heading="Old",
        text="alpha beta gamma delta",
        locator="/old",
    )
    new = _section(
        "new", 0, code=None, xml_id=None, heading="New", text="one two three four", locator="/new"
    )

    assert all(
        item.status == SectionMatchStatus.UNMATCHED for item in match_sections((old,), (new,))
    )

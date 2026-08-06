"""Deterministic hierarchical section matching for ODD-002."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher

from odd.constants import CONTENT_ASSISTED_MATCH_THRESHOLD
from odd.models import (
    SectionMatchMethod,
    SectionMatchStatus,
    StoredSection,
)

_SPACE = re.compile(r"\s+")
_WORD = re.compile(r"[^\W_]+(?:[-'][^\W_]+)*|[<>]=?|=", flags=re.UNICODE)
_HEURISTIC_MARGIN = 0.03


@dataclass(frozen=True, slots=True)
class SectionMatch:
    old: StoredSection | None
    new: StoredSection | None
    method: SectionMatchMethod
    status: SectionMatchStatus


def match_sections(
    old_sections: Sequence[StoredSection],
    new_sections: Sequence[StoredSection],
) -> tuple[SectionMatch, ...]:
    old_by_id = {item.section_id: item for item in old_sections}
    new_by_id = {item.section_id: item for item in new_sections}
    unmatched_old = set(old_by_id)
    unmatched_new = set(new_by_id)
    matches: list[SectionMatch] = []

    def exact_phase(
        method: SectionMatchMethod,
        old_key: Callable[[StoredSection], object | None],
        new_key: Callable[[StoredSection], object | None],
        corroborates: Callable[[StoredSection, StoredSection], bool] | None = None,
    ) -> None:
        old_values = {
            identifier: old_key(old_by_id[identifier]) for identifier in unmatched_old
        }
        new_values = {
            identifier: new_key(new_by_id[identifier]) for identifier in unmatched_new
        }
        old_counts = Counter(value for value in old_values.values() if value is not None)
        new_counts = Counter(value for value in new_values.values() if value is not None)
        candidates: list[tuple[int, int, str, str]] = []
        new_for_key = {
            value: identifier
            for identifier, value in new_values.items()
            if value is not None
        }
        for old_id, value in old_values.items():
            if value is None or old_counts[value] != 1 or new_counts[value] != 1:
                continue
            new_id = new_for_key[value]
            old_section = old_by_id[old_id]
            new_section = new_by_id[new_id]
            if corroborates is not None and not corroborates(old_section, new_section):
                continue
            candidates.append(
                (old_section.sequence_index, new_section.sequence_index, old_id, new_id)
            )
        for _old_sequence, _new_sequence, old_id, new_id in sorted(candidates):
            if old_id not in unmatched_old or new_id not in unmatched_new:
                continue
            matches.append(
                SectionMatch(
                    old=old_by_id[old_id],
                    new=new_by_id[new_id],
                    method=method,
                    status=SectionMatchStatus.EXACT,
                )
            )
            unmatched_old.remove(old_id)
            unmatched_new.remove(new_id)

    exact_phase(
        SectionMatchMethod.SOURCE_SECTION_ID,
        lambda item: item.section_id,
        lambda item: item.section_id,
    )
    exact_phase(
        SectionMatchMethod.XML_IDENTIFIER,
        lambda item: item.xml_identifier,
        lambda item: item.xml_identifier,
    )
    exact_phase(
        SectionMatchMethod.SECTION_CODE,
        lambda item: item.source_section_code,
        lambda item: item.source_section_code,
    )
    exact_phase(
        SectionMatchMethod.SOURCE_LOCATOR,
        lambda item: item.source_locator,
        lambda item: item.source_locator,
        corroborates=lambda old, new: (
            old.source_section_code == new.source_section_code
            or _heading(old.original_heading) == _heading(new.original_heading)
        ),
    )

    old_parent = _parent_signatures(old_sections)
    new_parent = _parent_signatures(new_sections)
    exact_phase(
        SectionMatchMethod.HEADING_AND_PARENT,
        lambda item: _heading_parent_key(item, old_parent),
        lambda item: _heading_parent_key(item, new_parent),
    )

    heuristic = _content_assisted_matches(
        [old_by_id[item] for item in unmatched_old],
        [new_by_id[item] for item in unmatched_new],
        old_parent,
        new_parent,
    )
    for old_section, new_section in heuristic:
        if (
            old_section.section_id not in unmatched_old
            or new_section.section_id not in unmatched_new
        ):
            continue
        matches.append(
            SectionMatch(
                old=old_section,
                new=new_section,
                method=SectionMatchMethod.CONTENT_ASSISTED,
                status=SectionMatchStatus.HEURISTIC,
            )
        )
        unmatched_old.remove(old_section.section_id)
        unmatched_new.remove(new_section.section_id)

    matches.extend(
        SectionMatch(
            old_by_id[identifier],
            None,
            SectionMatchMethod.UNMATCHED,
            SectionMatchStatus.UNMATCHED,
        )
        for identifier in sorted(unmatched_old, key=lambda item: old_by_id[item].sequence_index)
    )
    matches.extend(
        SectionMatch(
            None,
            new_by_id[identifier],
            SectionMatchMethod.UNMATCHED,
            SectionMatchStatus.UNMATCHED,
        )
        for identifier in sorted(unmatched_new, key=lambda item: new_by_id[item].sequence_index)
    )
    return tuple(sorted(matches, key=_match_sort_key))


def _content_assisted_matches(
    old_sections: Sequence[StoredSection],
    new_sections: Sequence[StoredSection],
    old_parent: dict[str, tuple[str, str, int]],
    new_parent: dict[str, tuple[str, str, int]],
) -> tuple[tuple[StoredSection, StoredSection], ...]:
    scores: dict[tuple[str, str], float] = {}
    for old in old_sections:
        for new in new_sections:
            if abs(old.depth - new.depth) > 1:
                continue
            score = _similarity(old, new, old_parent, new_parent)
            if score >= CONTENT_ASSISTED_MATCH_THRESHOLD:
                scores[(old.section_id, new.section_id)] = score

    old_ranked: dict[str, list[tuple[float, str]]] = {}
    new_ranked: dict[str, list[tuple[float, str]]] = {}
    for (old_id, new_id), score in scores.items():
        old_ranked.setdefault(old_id, []).append((score, new_id))
        new_ranked.setdefault(new_id, []).append((score, old_id))
    for values in old_ranked.values():
        values.sort(key=lambda item: (-item[0], item[1]))
    for values in new_ranked.values():
        values.sort(key=lambda item: (-item[0], item[1]))

    old_lookup = {item.section_id: item for item in old_sections}
    new_lookup = {item.section_id: item for item in new_sections}
    accepted: list[tuple[float, StoredSection, StoredSection]] = []
    for old_id, ranked in old_ranked.items():
        best_score, new_id = ranked[0]
        reverse = new_ranked[new_id]
        if reverse[0][1] != old_id:
            continue
        if len(ranked) > 1 and best_score - ranked[1][0] < _HEURISTIC_MARGIN:
            continue
        if len(reverse) > 1 and best_score - reverse[1][0] < _HEURISTIC_MARGIN:
            continue
        accepted.append((best_score, old_lookup[old_id], new_lookup[new_id]))
    accepted.sort(key=lambda item: (-item[0], item[1].sequence_index, item[2].sequence_index))
    return tuple((old, new) for _score, old, new in accepted)


def _similarity(
    old: StoredSection,
    new: StoredSection,
    old_parent: dict[str, tuple[str, str, int]],
    new_parent: dict[str, tuple[str, str, int]],
) -> float:
    old_tokens = tuple(_WORD.findall(old.original_text.casefold()))
    new_tokens = tuple(_WORD.findall(new.original_text.casefold()))
    if not old_tokens and not new_tokens:
        return 0.0
    content = SequenceMatcher(a=old_tokens, b=new_tokens, autojunk=False).ratio()
    heading = SequenceMatcher(
        a=_heading(old.original_heading),
        b=_heading(new.original_heading),
        autojunk=False,
    ).ratio()
    parent = 1.0 if old_parent.get(old.section_id) == new_parent.get(new.section_id) else 0.0
    return 0.94 * content + 0.04 * heading + 0.02 * parent


def _parent_signatures(sections: Sequence[StoredSection]) -> dict[str, tuple[str, str, int]]:
    lookup = {item.section_id: item for item in sections}
    result: dict[str, tuple[str, str, int]] = {}
    for section in sections:
        parent = lookup.get(section.parent_section_id or "")
        result[section.section_id] = (
            (parent.source_section_code or "") if parent else "<root>",
            _heading(parent.original_heading) if parent else "<root>",
            parent.depth if parent else -1,
        )
    return result


def _heading_parent_key(
    section: StoredSection,
    parents: dict[str, tuple[str, str, int]],
) -> tuple[str, tuple[str, str, int], int] | None:
    heading = _heading(section.original_heading)
    if not heading:
        return None
    return heading, parents[section.section_id], section.depth


def _heading(value: str | None) -> str:
    return _SPACE.sub(" ", (value or "").strip().casefold())


def _match_sort_key(item: SectionMatch) -> tuple[int, int, int]:
    if item.new is not None:
        return item.new.sequence_index, 0, item.old.sequence_index if item.old else -1
    assert item.old is not None
    return item.old.sequence_index, 1, item.old.sequence_index

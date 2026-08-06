"""Deterministic textual diff; it makes no clinical-equivalence claims."""

from __future__ import annotations

import re
from difflib import SequenceMatcher, unified_diff

from odd.models import StructuredTextDiff, TextDiffChunk, TextDiffOperation

_TOKEN = re.compile(r"\S+")
_DISPLAY_WORDS_PER_LINE = 14


def build_text_diff(
    old_text: str,
    new_text: str,
    *,
    old_label: str,
    new_label: str,
) -> StructuredTextDiff:
    old_tokens = tuple(_TOKEN.findall(old_text))
    new_tokens = tuple(_TOKEN.findall(new_text))
    matcher = SequenceMatcher(a=old_tokens, b=new_tokens, autojunk=False)
    chunks: list[TextDiffChunk] = []
    for tag, old_start, old_end, new_start, new_end in matcher.get_opcodes():
        if tag == "equal":
            chunks.append(
                _chunk(
                    TextDiffOperation.CONTEXT,
                    old_tokens[old_start:old_end],
                    old_start,
                    old_end,
                    new_start,
                    new_end,
                )
            )
        elif tag == "delete":
            chunks.append(
                _chunk(
                    TextDiffOperation.DELETION,
                    old_tokens[old_start:old_end],
                    old_start,
                    old_end,
                    new_start,
                    new_end,
                )
            )
        elif tag == "insert":
            chunks.append(
                _chunk(
                    TextDiffOperation.ADDITION,
                    new_tokens[new_start:new_end],
                    old_start,
                    old_end,
                    new_start,
                    new_end,
                )
            )
        else:  # replace: deletion first, then addition, for a fixed ordering
            chunks.append(
                _chunk(
                    TextDiffOperation.DELETION,
                    old_tokens[old_start:old_end],
                    old_start,
                    old_end,
                    new_start,
                    new_start,
                )
            )
            chunks.append(
                _chunk(
                    TextDiffOperation.ADDITION,
                    new_tokens[new_start:new_end],
                    old_end,
                    old_end,
                    new_start,
                    new_end,
                )
            )

    additions = tuple(item.text for item in chunks if item.operation == TextDiffOperation.ADDITION)
    deletions = tuple(item.text for item in chunks if item.operation == TextDiffOperation.DELETION)
    context = tuple(item.text for item in chunks if item.operation == TextDiffOperation.CONTEXT)
    human_lines = unified_diff(
        _display_lines(old_tokens),
        _display_lines(new_tokens),
        fromfile=old_label,
        tofile=new_label,
        lineterm="",
        n=3,
    )
    return StructuredTextDiff(
        chunks=tuple(chunks),
        additions=additions,
        deletions=deletions,
        unchanged_context=context,
        unified_diff="\n".join(human_lines),
    )


def _chunk(
    operation: TextDiffOperation,
    tokens: tuple[str, ...],
    old_start: int,
    old_end: int,
    new_start: int,
    new_end: int,
) -> TextDiffChunk:
    return TextDiffChunk(
        operation=operation,
        text=" ".join(tokens),
        old_start=old_start,
        old_end=old_end,
        new_start=new_start,
        new_end=new_end,
    )


def _display_lines(tokens: tuple[str, ...]) -> list[str]:
    return [
        " ".join(tokens[index : index + _DISPLAY_WORDS_PER_LINE])
        for index in range(0, len(tokens), _DISPLAY_WORDS_PER_LINE)
    ]

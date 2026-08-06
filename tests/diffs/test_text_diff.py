from __future__ import annotations

from odd.diffs.text import build_text_diff
from odd.provenance.canonical import canonical_json_bytes


def test_structured_text_diff_preserves_additions_deletions_and_context() -> None:
    old = "Do not use more than 5 mg in patients with CrCl < 15 mL/min."
    new = "Do not use more than 2.5 mg in patients with CrCl < 15 mL/min."
    result = build_text_diff(old, new, old_label="old", new_label="new")

    assert result.deletions == ("5",)
    assert result.additions == ("2.5",)
    assert "Do not use more than" in result.unchanged_context[0]
    assert "mg" in " ".join(result.unchanged_context)
    assert "<" in " ".join(result.unchanged_context)
    assert "mL/min." in " ".join(result.unchanged_context)


def test_warning_negation_and_qualifier_tokens_are_not_rewritten() -> None:
    old = "WARNING: should not ordinarily be discontinued unless pathological bleeding occurs."
    new = "WARNING: must not be discontinued unless clinically significant bleeding occurs."
    result = build_text_diff(old, new, old_label="old", new_label="new")
    changed = " ".join((*result.deletions, *result.additions, *result.unchanged_context))

    assert "WARNING:" in changed
    assert "not" in changed
    assert "unless" in changed
    assert "pathological" in result.deletions
    assert "clinically significant" in result.additions


def test_text_diff_serialization_is_byte_deterministic() -> None:
    first = build_text_diff("one two three", "one four three", old_label="a", new_label="b")
    second = build_text_diff("one two three", "one four three", old_label="a", new_label="b")
    assert canonical_json_bytes(first) == canonical_json_bytes(second)

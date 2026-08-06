"""Definition of a source-section content hash."""

from __future__ import annotations

from typing import Any

from odd.provenance.canonical import canonical_json_bytes
from odd.provenance.hashing import sha256_bytes


def section_sha256(
    *,
    source_section_code: str | None,
    original_heading: str | None,
    original_text: str,
    structured_content: Any,
) -> str:
    """Hash source-derived section content, independent of parser-generated IDs."""

    return sha256_bytes(
        canonical_json_bytes(
            {
                "original_heading": original_heading,
                "original_text": original_text,
                "source_section_code": source_section_code,
                "structured_content": structured_content,
            }
        )
    )

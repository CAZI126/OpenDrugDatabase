"""The AI-facing evidence bundle: extracted content plus the way back to the source.

Every extracted passage carries the official identifier, the official URL, the
retrieval time, the document version, the SHA-256 of the preserved raw bytes,
and an evidence locator. A consumer holding only this JSON can re-open the
preserved raw source and mechanically re-retrieve the exact same passage.

Anything the official source does not state is reported as ``UNKNOWN``. Nothing
here infers, ranks, or adjudicates.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

from odd.constants import CORE_EVIDENCE_SCHEMA_VERSION, PARSER_VERSION, SCHEMA_VERSION
from odd.models import NormalizedDocument, RawDocument, SourceSection
from odd.provenance.hashing import sha256_bytes

UNKNOWN = "UNKNOWN"

_LOCATOR_INSTRUCTIONS = (
    "Open source.raw_path relative to the ODD data root, confirm its SHA-256 equals "
    "source.raw_sha256, resolve evidence.xml_locator as a sequence of name[index] XML "
    "steps from the document root, then recompute evidence.section_sha256 over that "
    "element to confirm the extracted text is the passage the locator addresses."
)

__all__ = [
    "CORE_EVIDENCE_SCHEMA_VERSION",
    "UNKNOWN",
    "build_evidence_payload",
    "relative_to_root",
    "select_sections",
]


def relative_to_root(path: Path, root: Path) -> str:
    """Render ``path`` as a portable POSIX path relative to the ODD data root."""

    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError:
        return path.resolve().as_posix()
    return PurePosixPath(relative).as_posix()


def select_sections(
    sections: tuple[SourceSection, ...],
    *,
    section_codes: tuple[str, ...] = (),
    section_name_contains: tuple[str, ...] = (),
) -> tuple[SourceSection, ...]:
    """Keep the sections the caller asked for; keep everything when nothing was asked.

    This is an exact filter over what the source states. It never reorders,
    scores, or drops a section for being unrecognized.

    A matched section brings its subsections with it. SPL routinely places a
    numbered section's content in its children, so returning the parent alone
    would hand back an empty passage while the official text sits one level down.
    """

    if not section_codes and not section_name_contains:
        return sections
    wanted_codes = {value.strip().casefold() for value in section_codes if value.strip()}
    wanted_names = tuple(
        value.strip().casefold() for value in section_name_contains if value.strip()
    )
    matched = {
        section.section_id
        for section in sections
        if (section.source_section_code or "").casefold() in wanted_codes
        or any(term in (section.original_heading or "").casefold() for term in wanted_names)
    }
    kept = set(matched)
    for section in sections:  # parents always precede their children
        if section.parent_section_id in kept:
            kept.add(section.section_id)
    return tuple(section for section in sections if section.section_id in kept)


def build_evidence_payload(
    normalized: NormalizedDocument,
    raw: RawDocument,
    *,
    data_root: Path,
    requested_term: str | None = None,
    section_codes: tuple[str, ...] = (),
    section_name_contains: tuple[str, ...] = (),
    candidate_count: int | None = None,
    candidate_listing_completeness: str | None = None,
    lookup_url: str | None = None,
) -> dict[str, Any]:
    """Build the deterministic AI-facing bundle for one preserved raw document.

    The payload contains no wall-clock value of its own: every timestamp comes
    from the immutable raw manifest, so re-running the same input reproduces the
    same bytes.
    """

    identity = raw.identity
    document = normalized.document
    raw_path = relative_to_root(raw.label_path, data_root)
    selected = select_sections(
        normalized.sections,
        section_codes=section_codes,
        section_name_contains=section_name_contains,
    )
    return {
        "schema_version": CORE_EVIDENCE_SCHEMA_VERSION,
        "drug": {
            "requested_term": requested_term or UNKNOWN,
            "document_title": document.title or UNKNOWN,
            "brand_names": list(document.brand_names) or UNKNOWN,
            "generic_names": [document.generic_name] if document.generic_name else UNKNOWN,
            "active_ingredients": list(document.active_ingredients) or UNKNOWN,
        },
        "source": {
            "authority": identity.authority,
            "provider": identity.provider,
            "jurisdiction": identity.jurisdiction,
            "official_document_id": {
                "scheme": "dailymed_set_id",
                "value": identity.source_document_id,
            },
            "official_url": identity.source_url or UNKNOWN,
            "official_lookup_url": lookup_url or UNKNOWN,
            "retrieved_at": _iso(raw.metadata),
            "document_version": {
                "scheme": "dailymed_spl_version",
                "value": identity.source_version,
                "effective_date": (
                    document.effective_date.isoformat()
                    if document.effective_date is not None
                    else UNKNOWN
                ),
                "document_type": document.document_type or UNKNOWN,
            },
            "raw_sha256": identity.raw_sha256,
            "raw_path": raw_path,
            "raw_metadata_path": relative_to_root(raw.metadata_path, data_root),
        },
        "selection": {
            "performed": False,
            "candidate_count": candidate_count if candidate_count is not None else UNKNOWN,
            "candidate_listing_completeness": candidate_listing_completeness or UNKNOWN,
            "note": (
                "ODD core does not select among candidates. This source identity was "
                "supplied by the caller and matched exactly against the official lookup "
                "response."
            ),
        },
        "extraction": {
            "parser_version": PARSER_VERSION,
            "normalized_schema_version": SCHEMA_VERSION,
            "document_section_count": len(normalized.sections),
            "returned_section_count": len(selected),
            "section_filter": {
                "include_subsections": True,
                "section_codes": sorted(
                    {value.strip() for value in section_codes if value.strip()}
                ),
                "section_name_contains": sorted(
                    {value.strip() for value in section_name_contains if value.strip()}
                ),
            },
        },
        "sections": [
            _section_payload(section, raw_path=raw_path, raw_sha256=identity.raw_sha256)
            for section in selected
        ],
        "evidence_retrieval": _LOCATOR_INSTRUCTIONS,
    }


def _section_payload(
    section: SourceSection,
    *,
    raw_path: str,
    raw_sha256: str,
) -> dict[str, Any]:
    structured = section.structured_content
    return {
        "section_id": section.section_id,
        "section_name": section.original_heading or UNKNOWN,
        "section_code": section.source_section_code or UNKNOWN,
        "sequence_index": section.sequence_index,
        "depth": section.depth,
        "content_status": section.content_status.value,
        "text": section.original_text,
        "evidence": {
            "raw_path": raw_path,
            "raw_sha256": raw_sha256,
            "xml_locator": section.source_locator,
            "text_locator": structured.locator if structured is not None else UNKNOWN,
            "section_sha256": section.section_sha256,
            "text_sha256": sha256_bytes(section.original_text.encode("utf-8")),
        },
    }


def _iso(metadata: dict[str, Any]) -> str:
    identity = metadata.get("source_identity")
    if isinstance(identity, dict):
        value = identity.get("retrieved_at")
        if isinstance(value, str) and value:
            return value
    return UNKNOWN

"""Hand an AI a map of the evidence first, then only the parts it asks for.

Delivering a whole label costs the reader most of its attention before it has
read anything relevant. Instead ODD can publish an index -- what sections exist,
what they are called, whether they carry text, and where each one lives -- and
then return exactly the passages the caller names.

The index states what the source contains. It does not recommend, rank, score,
summarize, or interpret, and it carries no section text and no FDA row text.
Choosing what to read is the caller's job; ODD only says what is there.

Retrieval is exact-match on the codes the caller names. A parent section is not
silently widened to its subsections here: the index reports each section's
content status, so a caller that asks for a section carrying no text can see
that and name the subsections it wants.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any

from odd.constants import PARSER_VERSION
from odd.core.evidence import UNKNOWN, relative_to_root
from odd.models import NormalizedDocument, RawDocument, SourceSection
from odd.provenance.hashing import sha256_bytes

CORE_INDEX_SCHEMA_VERSION = "odd-core-index/1.0.0"
CORE_SLICE_SCHEMA_VERSION = "odd-core-evidence-slice/1.0.0"

COMPLETE = "COMPLETE"
INCOMPLETE = "INCOMPLETE"
FOUND = "FOUND"
NOT_FOUND = "NOT_FOUND"

_INDEX_NOTE = (
    "This index states what the source contains. It carries no section text and no "
    "FDA row text, and it does not recommend, rank, or select. Name the section codes "
    "and application numbers you want, and ODD returns exactly those by exact match."
)

__all__ = [
    "CORE_INDEX_SCHEMA_VERSION",
    "CORE_SLICE_SCHEMA_VERSION",
    "build_index_payload",
    "build_slice_payload",
    "regulatory_index",
    "select_exact_sections",
]


def select_exact_sections(
    sections: tuple[SourceSection, ...], codes: tuple[str, ...]
) -> tuple[SourceSection, ...]:
    """Return only sections whose official code exactly matches one that was named.

    No subsection widening, no name matching, no ordering by relevance.
    """

    wanted = {value.strip().casefold() for value in codes if value.strip()}
    return tuple(
        section
        for section in sections
        if (section.source_section_code or "").casefold() in wanted
    )


def build_index_payload(
    normalized: NormalizedDocument,
    raw: RawDocument,
    *,
    data_root: Path,
    requested_term: str | None = None,
    regulatory_sources: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Describe every section and every reachable FDA table, with no content."""

    identity = raw.identity
    document = normalized.document
    return {
        "schema_version": CORE_INDEX_SCHEMA_VERSION,
        "document": {
            "set_id": identity.source_document_id,
            "source_version": identity.source_version,
            "official_url": identity.source_url or UNKNOWN,
            "raw_sha256": identity.raw_sha256,
            "raw_path": relative_to_root(raw.label_path, data_root),
            "document_title": document.title or UNKNOWN,
            "requested_term": requested_term or UNKNOWN,
            "publisher": "National Library of Medicine",
            "repository": "DailyMed",
            "fda_approval_status": UNKNOWN,
            "parser_version": PARSER_VERSION,
        },
        "sections": [
            {
                "section_code": section.source_section_code or UNKNOWN,
                "section_name": section.original_heading or UNKNOWN,
                "content_status": section.content_status.value,
                "text_length": len(section.original_text),
                "depth": section.depth,
                "sequence_index": section.sequence_index,
                "evidence_locator": section.source_locator,
            }
            for section in normalized.sections
        ],
        "regulatory_index": regulatory_index(regulatory_sources or [], data_root=data_root),
        "completeness": {
            "section_index": COMPLETE,
            "section_count": len(normalized.sections),
            "regulatory_index": _regulatory_completeness(regulatory_sources or []),
        },
        "retrieval_note": _INDEX_NOTE,
    }


def regulatory_index(
    regulatory_sources: list[dict[str, Any]], *, data_root: Path
) -> dict[str, Any]:
    """List the application numbers and tables reachable, without any row text."""

    if not regulatory_sources:
        return {
            "application_numbers": [],
            "archive_sha256": UNKNOWN,
            "available_tables": [],
            "matching_row_counts": {},
        }
    archive = regulatory_sources[0].get("archive", {})
    archive_path = data_root / str(archive.get("raw_path", ""))
    tables: list[str] = []
    try:
        with zipfile.ZipFile(archive_path) as handle:
            tables = sorted(handle.namelist())
    except (OSError, zipfile.BadZipFile):
        tables = []
    counts: dict[str, dict[str, int]] = {}
    numbers: list[str] = []
    for source in regulatory_sources:
        number = str(source.get("application_number", UNKNOWN))
        numbers.append(number)
        per_table: dict[str, int] = {}
        link = source.get("link")
        rows = (
            link.get("fda_evidence", {}).get("rows", [])
            if isinstance(link, dict)
            else []
        )
        for row in rows:
            if isinstance(row, dict):
                name = str(row.get("table_name", UNKNOWN))
                per_table[name] = per_table.get(name, 0) + 1
        counts[number] = dict(sorted(per_table.items()))
    return {
        "application_numbers": sorted(set(numbers)),
        "archive_sha256": str(archive.get("raw_sha256", UNKNOWN)),
        "archive_raw_path": str(archive.get("raw_path", UNKNOWN)),
        "available_tables": tables,
        "matching_row_counts": counts,
    }


def build_slice_payload(
    normalized: NormalizedDocument,
    raw: RawDocument,
    *,
    data_root: Path,
    requested_section_codes: tuple[str, ...],
    requested_application_numbers: tuple[str, ...] = (),
    include_drugsfda: bool = False,
    regulatory_sources: list[dict[str, Any]] | None = None,
    section_payload: Any,
) -> dict[str, Any]:
    """Return exactly the passages and FDA rows that were named, and nothing else."""

    identity = raw.identity
    raw_path = relative_to_root(raw.label_path, data_root)
    selected = select_exact_sections(normalized.sections, requested_section_codes)
    present_codes = {
        (section.source_section_code or "").casefold() for section in normalized.sections
    }
    sources = regulatory_sources or []
    wanted_numbers = {value.strip().casefold() for value in requested_application_numbers}
    kept = [
        source
        for source in sources
        if not wanted_numbers
        or str(source.get("application_number", "")).casefold() in wanted_numbers
    ]
    return {
        "schema_version": CORE_SLICE_SCHEMA_VERSION,
        "request": {
            "set_id": identity.source_document_id,
            "source_version": identity.source_version,
            "requested_section_codes": sorted(
                {value.strip() for value in requested_section_codes if value.strip()}
            ),
            "requested_application_numbers": sorted(
                {value.strip() for value in requested_application_numbers if value.strip()}
            ),
            "include_drugsfda": include_drugsfda,
        },
        "label_source": {
            "publisher": "National Library of Medicine",
            "repository": "DailyMed",
            "regulatory_recipient": identity.authority,
            "jurisdiction": identity.jurisdiction,
            "official_document_id": {
                "scheme": "dailymed_set_id",
                "value": identity.source_document_id,
            },
            "official_url": identity.source_url or UNKNOWN,
            "document_version": {
                "scheme": "dailymed_spl_version",
                "value": identity.source_version,
            },
            "fda_approval_status": UNKNOWN,
            "raw_sha256": identity.raw_sha256,
            "raw_path": raw_path,
            "raw_metadata_path": relative_to_root(raw.metadata_path, data_root),
        },
        "label_evidence": [
            section_payload(section, raw_path=raw_path, raw_sha256=identity.raw_sha256)
            for section in selected
        ],
        "regulatory_evidence": kept,
        "completeness": {
            "section_index": COMPLETE,
            "requested_section_codes": {
                code: (FOUND if code.casefold() in present_codes else NOT_FOUND)
                for code in sorted(
                    {value.strip() for value in requested_section_codes if value.strip()}
                )
            },
            "returned_section_count": len(selected),
            "regulatory_index": (
                _regulatory_completeness(sources) if include_drugsfda else UNKNOWN
            ),
            "requested_application_numbers": {
                str(source.get("application_number", UNKNOWN)): str(
                    source.get("link", {}).get("status", UNKNOWN)
                )
                for source in kept
            },
        },
    }


def _regulatory_completeness(regulatory_sources: list[dict[str, Any]]) -> str:
    """The archive was read completely only if every link reached a settled answer."""

    if not regulatory_sources:
        return UNKNOWN
    statuses = {
        str(source.get("link", {}).get("status", UNKNOWN)) for source in regulatory_sources
    }
    return INCOMPLETE if UNKNOWN in statuses else COMPLETE


def slice_fingerprint(payload: dict[str, Any]) -> str:
    request = payload.get("request", {})
    codes = ",".join(request.get("requested_section_codes", []))
    numbers = ",".join(request.get("requested_application_numbers", []))
    return sha256_bytes(f"{codes}|{numbers}".encode())[:12]

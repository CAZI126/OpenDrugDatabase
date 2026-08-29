"""The four things an AI client can ask ODD for, and nothing more.

Each tool is a thin composition over :class:`odd.core.pipeline.CorePipeline`.
The rules the core enforces are the rules here:

* a name that matches several preserved documents returns all of them, and the
  caller chooses -- this layer never picks one;
* a slice returns the section codes that were named, matched exactly, and says
  which named codes were not found rather than inventing them;
* Drugs@FDA is reached only by exact application-number identity;
* anything the sources do not state comes back as ``UNKNOWN``, and anything that
  cannot be established at all comes back as a structured error.

Every tool here reads and only reads. No call retrieves anything over the network
and no call writes into the data root, so the FDA archive is consulted only where
one is already preserved. Having no archive to read is reported as
``NOT_PRESERVED``, which is not the same answer as the archive being read and not
naming this application, which is ``NOT_FOUND``.

No tool contains a branch for a particular drug, application, or manufacturer.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from odd.catalog import (
    CATALOG_CANDIDATE_FIELDS,
    CATALOG_FRESHNESS_NOT_CHECKED,
    CatalogError,
    load_document_catalog,
)
from odd.core.evidence import UNKNOWN
from odd.core.pipeline import CorePipeline
from odd.errors import AmbiguousSourceSelection, ODDError, SourceNotFound
from odd.models import NormalizedDocument, RawDocument
from odd.provenance.hashing import sha256_file

VERIFIED = "VERIFIED"
FAILED = "FAILED"
UNRESOLVED = "UNKNOWN"
EXACT = "EXACT"

# Stable machine-readable reasons. They describe what was observed, never what
# ODD concluded about a product.
BLANK_QUERY = "BLANK_QUERY"
NO_SECTION_CODES = "NO_SECTION_CODES"
NOT_PRESERVED = "NOT_PRESERVED"
NOT_FOUND = "NOT_FOUND"
AMBIGUOUS_VERSION = "AMBIGUOUS_STORED_VERSION"

_NOT_PRESERVED_NOTE = (
    "No Drugs@FDA archive is preserved under this data root, so there was "
    "nothing to read and nothing was retrieved. This is not the archive saying "
    "this application does not exist. Preserve one with the CLI first: "
    "odd extract --set-id <id> --include-drugsfda."
)
_NOT_FOUND_NOTE = (
    "The preserved archive was read and states no application with this exact "
    "identity for this label. Brand name, ingredient, and sponsor never create "
    "a link, and a prefix or a bare number is a different application."
)

_NO_SELECTION_NOTE = (
    "ODD does not choose between documents. Every preserved document whose own "
    "text matched the query is listed here in storage order; name the set_id you "
    "want in the next call."
)
_EVIDENCE_NOTE = (
    "Open raw_path relative to the ODD data root, confirm its SHA-256 equals "
    "raw_sha256, then resolve evidence.xml_locator from the document root to "
    "re-retrieve this passage from the preserved source."
)

__all__ = ["OddTools", "ToolError"]


class ToolError(Exception):
    """A failure that must reach the caller as data, not as a stack trace."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": "error",
            "error": {"code": self.code, "details": self.details, "message": self.message},
        }


@dataclass(frozen=True, slots=True)
class _Stored:
    raw: RawDocument
    normalized: NormalizedDocument


class OddTools:
    """The MCP-facing surface over one ODD data root."""

    def __init__(self, pipeline: CorePipeline | None = None, *, data_root: Path | None = None):
        if pipeline is None:
            pipeline = CorePipeline(data_root=Path(data_root or "data"))
        self.pipeline = pipeline

    # -- 1. which preserved documents could this question be about? ---------
    def find_documents(self, query: str) -> dict[str, Any]:
        """List every preserved document whose own text matches ``query``.

        The match is a case-insensitive substring of what the document states
        about itself -- its title, brand names, generic name, and active
        ingredients. Nothing is scored, ordered by relevance, or discarded for
        being an unexpected kind of product.
        """

        wanted = query.strip().casefold()
        if not wanted:
            raise ToolError(BLANK_QUERY, "a query is required to find preserved documents")

        try:
            catalog = load_document_catalog(self.pipeline.data_root)
        except CatalogError as error:
            raise ToolError(error.code, error.message, **error.details) from error

        candidates = []
        for record in catalog.records:
            values = record["search_values_normalized"]
            if not any(wanted in value for value in values):
                continue
            candidates.append(
                {
                    **{field: record[field] for field in CATALOG_CANDIDATE_FIELDS},
                    "matched_query": query,
                }
            )

        return {
            "status": "ok",
            "query": query,
            "candidate_count": len(candidates),
            "candidates": candidates,
            "selection_performed": False,
            "note": _NO_SELECTION_NOTE,
            "catalog_schema_version": catalog.schema_version,
            "catalog_sha256": catalog.sha256,
            "catalog_record_count": len(catalog.records),
            "catalog_built_at": catalog.built_at,
            "catalog_built_from_fingerprint": catalog.source_identity_fingerprint,
            "catalog_freshness": CATALOG_FRESHNESS_NOT_CHECKED,
        }

    # -- 2. what is in the document, without reading it --------------------
    def get_section_index(
        self, set_id: str, source_version: str | None = None
    ) -> dict[str, Any]:
        """Return every section the document contains, carrying none of its text."""

        stored = self._resolve(set_id, source_version)
        index = self._extract(stored, index_only=True).payload
        entries = index["sections"]
        return {
            "status": "ok",
            "document": self._document_block(stored),
            "section_count": len(entries),
            "completeness": index["completeness"],
            "sections": [
                {
                    "section_code": entry["section_code"],
                    "section_title": entry["section_name"],
                    "content_status": entry["content_status"],
                    "text_length": entry["text_length"],
                    "depth": entry["depth"],
                    "sequence_index": entry["sequence_index"],
                    "parent_sequence_index": parent,
                    "evidence_locator": entry["evidence_locator"],
                    "section_sha256": entry["section_sha256"],
                    "text_sha256": entry["text_sha256"],
                }
                for entry, parent in zip(entries, _parents(entries), strict=True)
            ],
            "carries_section_text": False,
            "note": index["retrieval_note"],
        }

    # -- 3. only the passages that were named ------------------------------
    def get_evidence_slice(
        self,
        set_id: str,
        section_codes: list[str] | None = None,
        application_number: str | None = None,
        source_version: str | None = None,
        section_locators: list[str] | None = None,
    ) -> dict[str, Any]:
        """Return exactly the sections that were named, matched exactly.

        A passage can be named by its official section code or by the position
        the index reported for it. The position is the identifier every section
        has: a real label can carry sections with no code at all, and more than
        one of them, so a code cannot always name one passage. Either way the
        match is exact -- no widening to parents, siblings or subsections.
        """

        codes = tuple(
            value.strip() for value in (section_codes or []) if value and value.strip()
        )
        locators = tuple(
            value.strip() for value in (section_locators or []) if value and value.strip()
        )
        if not codes and not locators:
            raise ToolError(
                NO_SECTION_CODES,
                "name at least one section code or section locator; call the section "
                "index first to see them",
            )
        stored = self._resolve(set_id, source_version)
        wanted_applications = (application_number.strip(),) if application_number else ()
        payload = self._extract(
            stored,
            slice_only=True,
            section_codes=codes,
            section_locators=locators,
            application_numbers=wanted_applications,
            include_drugsfda=bool(wanted_applications),
        ).payload

        returned = payload["label_evidence"]
        found = payload["completeness"]["requested_section_codes"]
        found_locators = payload["completeness"]["requested_section_locators"]
        wanted_codes = {code.casefold() for code in codes} | set(codes)
        wanted_locators = set(locators)
        # A returned section is expected when the caller named its code or its
        # position. Anything else would be widening, which this slice never does.
        unexpected = {
            item["section_code"]
            for item in returned
            if (item["section_code"] or "").casefold() not in wanted_codes
            and item["section_code"] not in wanted_codes
            and item["evidence"]["xml_locator"] not in wanted_locators
        }
        return {
            "status": "ok",
            "document": self._document_block(stored),
            "requested_section_codes": payload["request"]["requested_section_codes"],
            "requested_section_locators": payload["request"]["requested_section_locators"],
            "returned_section_codes": [item["section_code"] for item in returned],
            "returned_section_locators": [
                item["evidence"]["xml_locator"] for item in returned
            ],
            "section_codes_not_found": sorted(
                code for code, state in found.items() if state != "FOUND"
            ),
            "section_locators_not_found": sorted(
                locator for locator, state in found_locators.items() if state != "FOUND"
            ),
            # An exact-match slice returns what was named only, so anything outside
            # the request is a contract breach the caller can check for itself.
            "unexpected_section_codes": sorted(unexpected),
            "subsections_added_implicitly": False,
            "sections": [
                {
                    "section_code": item["section_code"],
                    "section_title": item["section_name"],
                    "content_status": item["content_status"],
                    "text": item["text"],
                    "evidence": item["evidence"],
                }
                for item in returned
            ],
            "drugs_fda": self._drugs_fda_block(payload, wanted_applications),
            "evidence_retrieval": _EVIDENCE_NOTE,
        }

    def _drugs_fda_block(
        self, payload: dict[str, Any], requested: tuple[str, ...]
    ) -> dict[str, Any]:
        """What the preserved FDA archive states, or why it states nothing."""

        if not requested:
            return {
                "requested_application_number": None,
                "status": UNRESOLVED,
                "network_attempted": False,
                "note": (
                    "Drugs@FDA was not consulted. Not asking is not the same as "
                    "asking and finding nothing."
                ),
                "sources": [],
            }
        sources = payload.get("regulatory_evidence") or []
        if sources:
            status = str(sources[0].get("link", {}).get("status", UNRESOLVED))
            note = _NOT_FOUND_NOTE if status == NOT_FOUND else (
                "Linked by exact application-number identity, read from the "
                "preserved archive. Brand name, ingredient, and sponsor never "
                "create a link."
            )
        elif self._archive_preserved():
            status, note = NOT_FOUND, _NOT_FOUND_NOTE
        else:
            status, note = NOT_PRESERVED, _NOT_PRESERVED_NOTE
        return {
            "requested_application_number": requested[0],
            "status": status,
            "match_rule": "exact application number identity only",
            "network_attempted": False,
            "sources": sources,
            "note": note,
        }

    # -- 4. does any of it still hold up against the preserved bytes? ------
    def verify_document(
        self,
        set_id: str,
        application_number: str | None = None,
        source_version: str | None = None,
    ) -> dict[str, Any]:
        """Walk a bundle back to the preserved raw source and report.

        Bytes that no longer agree with their own immutable manifest are the
        answer this tool exists to give, so they are reported as ``FAILED``
        rather than raised. Only having nothing to verify is an error.

        Naming an ``application_number`` carries the same re-verification through
        to the FDA link: the preserved archive is re-hashed, the cited rows are
        re-read from it by member and row number, and the exact-identity match is
        recomputed. With no archive preserved, the FDA half is reported as
        ``NOT_PRESERVED`` and the label's own verification stands on its own.
        """

        wanted = (application_number or "").strip()
        try:
            stored = self._resolve(set_id, source_version)
        except ToolError as error:
            if error.code in {NOT_PRESERVED, AMBIGUOUS_VERSION, BLANK_QUERY}:
                raise
            return {
                "status": "ok",
                "document": {"set_id": set_id, "source_version": source_version or UNKNOWN},
                "verified_artifact": None,
                "result": FAILED,
                "failure_reasons": [error.message],
                "checks": [],
                "failures": [{"reason": error.message, **error.details}],
            }
        identity = stored.raw.identity
        if wanted:
            # The FDA link is only verifiable against a bundle that carries one,
            # so build that bundle here from the preserved bytes on both sides.
            evidence = self._extract(
                stored, include_drugsfda=True, application_numbers=(wanted,)
            )
        else:
            try:
                evidence = self.pipeline.load_evidence(
                    identity.source_document_id, identity.source_version
                )
            except (SourceNotFound, ODDError):
                # Nothing written yet is not a verification failure; build the
                # bundle from the preserved bytes and verify that.
                evidence = self._extract(stored)
        report = self.pipeline.verify(evidence.payload)
        checks = {check.name: check for check in report.checks}

        def state(name: str) -> dict[str, Any]:
            check = checks.get(name)
            if check is None:
                return {"observed": UNRESOLVED, "message": "this check did not run"}
            return {"observed": VERIFIED if check.ok else FAILED, "message": check.message}

        return {
            "status": "ok",
            "document": self._document_block(stored),
            "verified_artifact": evidence.path.name,
            "raw_bytes_sha256": state("raw_sha256"),
            "section_anchors": state("section_evidence"),
            "source_version_consistency": {
                "document_identity": state("document_identity"),
                "raw_metadata": state("raw_metadata"),
            },
            "drugs_fda_linkage": self._linkage_block(evidence.payload, wanted, state),
            "checks": [check.as_dict() for check in report.checks],
            "failures": list(report.failures),
            "result": VERIFIED if report.ok else FAILED,
            "failure_reasons": [
                check.message for check in report.checks if not check.ok
            ],
        }

    def _linkage_block(
        self,
        payload: dict[str, Any],
        requested: str,
        state: Callable[[str], dict[str, Any]],
    ) -> dict[str, Any]:
        """The FDA half of the verification, re-read from the preserved archive."""

        sources = payload.get("regulatory_sources") or payload.get("regulatory_evidence") or []
        block: dict[str, Any] = {
            "requested_application_number": requested or None,
            "network_attempted": False,
            "archive_sha256": state("regulatory_archive_sha256"),
            "row_evidence": state("regulatory_row_evidence"),
            "link_status": state("regulatory_link_status"),
        }
        if not requested:
            block["result"] = UNRESOLVED
            block["note"] = "no application number was named, so no link was checked"
            return block
        if not sources:
            preserved = self._archive_preserved()
            block["result"] = NOT_FOUND if preserved else NOT_PRESERVED
            block["exact_match_status"] = block["result"]
            block["matched_application_number"] = None
            block["rows"] = []
            block["note"] = _NOT_FOUND_NOTE if preserved else _NOT_PRESERVED_NOTE
            return block
        source = sources[0]
        archive = source.get("archive") or {}
        link = source.get("link") or {}
        rows = (link.get("fda_evidence") or {}).get("rows") or []
        expected = str(archive.get("raw_sha256", UNKNOWN))
        block.update(
            {
                "archive_path": archive.get("raw_path", UNKNOWN),
                "archive_sha256_expected": expected,
                "archive_sha256_actual": self._archive_digest(archive.get("raw_path")),
                "exact_match_status": str(link.get("status", UNRESOLVED)),
                "matched_application_number": source.get("application_number", UNKNOWN),
                "match_rule": "exact application number identity only",
                "rows": [
                    {
                        "zip_member": row.get("zip_member"),
                        "row_number": row.get("row_number"),
                        "row_sha256": row.get("row_sha256"),
                    }
                    for row in rows
                    if isinstance(row, dict)
                ],
            }
        )
        checked = (
            block["archive_sha256"],
            block["row_evidence"],
            block["link_status"],
        )
        block["result"] = (
            VERIFIED
            if all(item["observed"] == VERIFIED for item in checked)
            and block["exact_match_status"] == EXACT
            else FAILED
        )
        return block

    def _archive_digest(self, raw_path: Any) -> str:
        """Re-hash the preserved archive the bundle names, without retrieving it."""

        try:
            return sha256_file(self.pipeline.data_root / str(raw_path))
        except OSError:
            return UNKNOWN

    # -- shared helpers -----------------------------------------------------
    def _resolve(self, set_id: str, source_version: str | None) -> _Stored:
        identity = (set_id or "").strip()
        if not identity:
            raise ToolError(NOT_PRESERVED, "a set_id is required")
        try:
            raw = self.pipeline.raw_store.resolve(identity, source_version)
        except AmbiguousSourceSelection as error:
            raise ToolError(
                AMBIGUOUS_VERSION,
                "several versions of this document are preserved; name source_version",
                **error.details,
            ) from error
        except SourceNotFound as error:
            raise ToolError(
                NOT_PRESERVED,
                "no preserved document exists for this identity in this data root",
                **{
                    "set_id": identity,
                    "source_version": source_version,
                    **error.details,
                },
            ) from error
        except ODDError as error:
            raise ToolError(
                error.category.value.upper(), error.message, **error.details
            ) from error
        return _Stored(raw=raw, normalized=self._parse(raw))

    def _parse(self, raw: RawDocument) -> NormalizedDocument:
        return self.pipeline.parser.parse(raw.label_path.read_bytes(), raw.identity)

    def _extract(self, stored: _Stored, **kwargs: Any) -> Any:
        """Build a bundle from preserved bytes only, and leave nothing behind.

        ``offline`` and ``write`` are fixed here rather than passed in: an MCP
        call is a question about what is already preserved, so no tool may make
        this server retrieve anything or change the data root under it.
        """

        identity = stored.raw.identity
        try:
            return self.pipeline.extract(
                identity.source_document_id,
                identity.source_version,
                offline=True,
                write=False,
                **kwargs,
            )
        except ODDError as error:
            raise ToolError(
                error.category.value.upper(), error.message, **error.details
            ) from error

    def _document_block(self, stored: _Stored) -> dict[str, Any]:
        identity = stored.raw.identity
        document = stored.normalized.document
        return {
            "set_id": identity.source_document_id,
            "source_version": identity.source_version,
            "document_title": document.title or UNKNOWN,
            "brand_names": list(document.brand_names) or UNKNOWN,
            "generic_name": document.generic_name or UNKNOWN,
            "active_ingredients": list(document.active_ingredients) or UNKNOWN,
            "effective_date": (
                document.effective_date.isoformat()
                if document.effective_date is not None
                else UNKNOWN
            ),
            "document_type": document.document_type or UNKNOWN,
            "label_publisher": "National Library of Medicine",
            "label_repository": "DailyMed",
            "regulatory_recipient": identity.authority,
            "jurisdiction": identity.jurisdiction,
            "fda_approval_status": UNKNOWN,
            "source_url": identity.source_url or UNKNOWN,
            "raw_sha256": identity.raw_sha256,
            "raw_path": _relative(stored.raw.label_path, self.pipeline.data_root),
        }

    def _archive_preserved(self) -> bool:
        """Is there an FDA archive here at all? Reads the store; retrieves nothing."""

        return bool(self.pipeline.drugsfda_store.preserved())


def _parents(entries: list[dict[str, Any]]) -> list[int | None]:
    """The sequence index of each entry's nearest shallower ancestor."""

    parents: list[int | None] = []
    open_by_depth: dict[int, int] = {}
    for entry in entries:
        depth = int(entry["depth"])
        parents.append(open_by_depth.get(depth - 1))
        open_by_depth[depth] = int(entry["sequence_index"])
    return parents


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()

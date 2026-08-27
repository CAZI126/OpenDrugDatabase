"""The ODD core pipeline: acquire, extract, verify.

One way in, one way back:

    official primary source
      -> preserved raw bytes + SHA-256
      -> sections extracted from those bytes
      -> structured output carrying source, version, and evidence locators
      -> re-verification of that output against the preserved bytes

Nothing on this path selects a drug, ranks a manufacturer, adjudicates a claim,
or fills a gap with a guess. When more than one official candidate matches, all
of them are returned and the caller decides.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from xml.etree import ElementTree

from odd.connectors.dailymed.client import DailyMedConnector
from odd.constants import CORE_NO_SELECTION_RULE_VERSION
from odd.core.drugsfda import (
    ApplicationReference,
    ArchiveSnapshot,
    DrugsFdaStore,
    Occurrence,
    extract_application_references,
    find_application,
    read_member_row,
    resolve_download,
    retrieve_archive,
)
from odd.core.evidence import (
    UNKNOWN,
    build_evidence_payload,
    relative_to_root,
    section_payload,
)
from odd.core.locator import resolve_locator
from odd.core.lookup import paged_lookup
from odd.core.selective import (
    CORE_INDEX_SCHEMA_VERSION,
    build_index_payload,
    build_slice_payload,
    index_view,
    slice_fingerprint,
)
from odd.errors import ODDError, ProvenanceValidationFailure, SourceNotFound
from odd.models import (
    CandidateLookup,
    DailyMedCandidate,
    DiscoveryCompleteness,
    RawDocument,
    SelectionDecision,
)
from odd.parsers.spl.parser import (
    Q,
    SPLParser,
    build_locator_map,
    parse_document_root,
    read_section_evidence,
)
from odd.provenance.canonical import canonical_json_bytes
from odd.provenance.hashing import sha256_bytes, sha256_file
from odd.provenance.raw_store import RawStore

DEFAULT_DATA_ROOT = Path("data")
# The status of a bundle that was built and returned but deliberately not kept.
NOT_WRITTEN = "not_written"

_NO_SELECTION_DESCRIPTION = (
    "ODD core performs no candidate selection. The caller supplies the official "
    "DailyMed set_id, and optionally the SPL version; ODD core requires an exact "
    "match against the official lookup response and preserves every candidate it saw."
)


@dataclass(frozen=True, slots=True)
class Candidate:
    """One official candidate exactly as the source reported it."""

    set_id: str
    source_version: str
    title: str
    published_date: str

    def as_dict(self) -> dict[str, str]:
        return {
            "published_date": self.published_date or UNKNOWN,
            "set_id": self.set_id,
            "source_version": self.source_version,
            "title": self.title or UNKNOWN,
        }


@dataclass(frozen=True, slots=True)
class AcquisitionResult:
    """What one retrieval attempt observed and preserved."""

    status: str
    candidates: tuple[Candidate, ...]
    lookup_url: str
    lookup_sha256: str
    raw: RawDocument | None = None
    listing_completeness: str = UNKNOWN
    listing_diagnostic: str | None = None
    listing_declared_total: int | None = None

    @property
    def ambiguous(self) -> bool:
        return self.status == "ambiguous"

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "candidate_listing_completeness": self.listing_completeness,
            "candidate_listing_declared_total": self.listing_declared_total,
            "candidate_listing_diagnostic": self.listing_diagnostic,
            "candidates": [item.as_dict() for item in self.candidates],
            "candidates_examined": len(self.candidates),
            "lookup_sha256": self.lookup_sha256,
            "lookup_url": self.lookup_url,
            "status": self.status,
        }
        if self.raw is not None:
            payload["raw_path"] = str(self.raw.label_path)
            payload["raw_metadata_path"] = str(self.raw.metadata_path)
            payload["raw_sha256"] = self.raw.identity.raw_sha256
            payload["set_id"] = self.raw.identity.source_document_id
            payload["source_version"] = self.raw.identity.source_version
        return payload


@dataclass(frozen=True, slots=True)
class EvidenceResult:
    """The AI-facing bundle and where it was written."""

    payload: dict[str, Any]
    path: Path
    status: str


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    ok: bool
    message: str

    def as_dict(self) -> dict[str, Any]:
        return {"message": self.message, "name": self.name, "ok": self.ok}


@dataclass(frozen=True, slots=True)
class VerificationReport:
    """The result of walking the structured output back to the preserved bytes."""

    ok: bool
    checks: tuple[Check, ...]
    failures: tuple[dict[str, Any], ...] = field(default=())

    def as_dict(self) -> dict[str, Any]:
        return {
            "checks": [item.as_dict() for item in self.checks],
            "failures": list(self.failures),
            "ok": self.ok,
        }


class CorePipeline:
    """The whole ODD core. No database, no selection, no adjudication, no audit."""

    def __init__(
        self,
        *,
        data_root: Path = DEFAULT_DATA_ROOT,
        connector: DailyMedConnector | None = None,
        parser: SPLParser | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.data_root = Path(data_root).resolve()
        self.raw_store = RawStore(self.data_root / "raw")
        self.drugsfda_store = DrugsFdaStore(self.data_root / "raw")
        self.evidence_root = self.data_root / "evidence" / "core"
        self.clock = clock or (lambda: datetime.now(UTC))
        self.connector = connector or DailyMedConnector(clock=self.clock)
        self.parser = parser or SPLParser()

    # 1. retrieve  2. preserve  3. hash  4. record version and provenance
    def acquire(
        self,
        drug: str,
        *,
        set_id: str | None = None,
        source_version: str | None = None,
    ) -> AcquisitionResult:
        """Retrieve the official primary source and preserve its exact bytes."""

        lookup = paged_lookup(self.connector, drug)
        observed = tuple(
            Candidate(
                set_id=item.set_id,
                source_version=item.source_version,
                title=item.title,
                published_date=item.published_date,
            )
            for item in lookup.candidates
        )
        lookup_sha256 = sha256_bytes(lookup.raw_body)
        complete = lookup.completeness is DiscoveryCompleteness.COMPLETE

        matches = tuple(lookup.candidates)
        if set_id is not None:
            wanted = set_id.strip().casefold()
            matches = tuple(item for item in matches if item.set_id.casefold() == wanted)
        if source_version is not None:
            wanted_version = source_version.strip()
            matches = tuple(item for item in matches if item.source_version == wanted_version)

        if not matches:
            # "Not present in a range I fully observed" and "not present in the part
            # I managed to observe" are different answers. Only the first is absence.
            if not complete:
                return AcquisitionResult(
                    status="unknown",
                    candidates=observed,
                    lookup_url=lookup.source_url,
                    lookup_sha256=lookup_sha256,
                    listing_completeness=lookup.completeness.value,
                    listing_diagnostic=lookup.diagnostic_message,
                    listing_declared_total=lookup.metadata_total_elements,
                )
            raise SourceNotFound(
                "no official candidate matched the requested identity"
                if observed
                else "the official source returned no candidates for this term",
                details={
                    "candidates": [item.as_dict() for item in observed],
                    "candidates_examined": len(observed),
                    "listing_completeness": lookup.completeness.value,
                    "listing_declared_total": lookup.metadata_total_elements,
                    "listing_diagnostic": lookup.diagnostic_message,
                    "requested_set_id": set_id,
                    "requested_source_version": source_version,
                },
            )

        identities = {(item.set_id.casefold(), item.source_version) for item in matches}
        if len(identities) > 1:
            # More than one official document still matches. ODD core does not choose.
            return AcquisitionResult(
                status="ambiguous",
                candidates=tuple(
                    Candidate(
                        set_id=item.set_id,
                        source_version=item.source_version,
                        title=item.title,
                        published_date=item.published_date,
                    )
                    for item in matches
                ),
                lookup_url=lookup.source_url,
                lookup_sha256=lookup_sha256,
                listing_completeness=lookup.completeness.value,
                listing_diagnostic=lookup.diagnostic_message,
                listing_declared_total=lookup.metadata_total_elements,
            )

        candidate = matches[0]
        download = self.connector.download(candidate)
        raw = self.raw_store.store(
            download,
            lookup,
            self._no_selection_decision(candidate, lookup),
        )
        return AcquisitionResult(
            status="already_stored" if raw.already_stored else "fetched",
            candidates=observed,
            lookup_url=lookup.source_url,
            lookup_sha256=lookup_sha256,
            raw=raw,
            listing_completeness=lookup.completeness.value,
            listing_diagnostic=lookup.diagnostic_message,
            listing_declared_total=lookup.metadata_total_elements,
        )

    # 5. extract sections  6. return structured data an AI can consume
    def extract(
        self,
        set_id: str,
        source_version: str | None = None,
        *,
        requested_term: str | None = None,
        section_codes: tuple[str, ...] = (),
        section_name_contains: tuple[str, ...] = (),
        candidate_count: int | None = None,
        candidate_listing_completeness: str | None = None,
        lookup_url: str | None = None,
        include_drugsfda: bool = False,
        index_only: bool = False,
        slice_only: bool = False,
        application_numbers: tuple[str, ...] = (),
        offline: bool = False,
        write: bool = True,
    ) -> EvidenceResult:
        """Extract from the preserved bytes: the whole document, an index, or a slice.

        ``offline`` reaches nothing off this machine: the preserved label is read
        as always, and the FDA archive is read only if one is already preserved
        here. ``write`` off returns the same bundle without leaving anything
        behind, for a caller that wants to read the evidence rather than keep it.
        """

        raw = self.raw_store.resolve(set_id, source_version)
        xml_bytes = raw.label_path.read_bytes()
        normalized = self.parser.parse(xml_bytes, raw.identity)
        regulatory = (
            self._regulatory_sources(
                xml_bytes,
                raw.identity.raw_sha256,
                application_numbers=application_numbers,
                offline=offline,
            )
            if include_drugsfda
            else None
        )
        if index_only:
            index = build_index_payload(
                normalized,
                raw,
                data_root=self.data_root,
                requested_term=requested_term,
                regulatory_sources=regulatory,
            )
            path, status = self._keep(raw, index, "index.json", write=write)
            return EvidenceResult(payload=index, path=path, status=status)
        if slice_only:
            piece = build_slice_payload(
                normalized,
                raw,
                data_root=self.data_root,
                requested_section_codes=section_codes,
                requested_application_numbers=application_numbers,
                include_drugsfda=include_drugsfda,
                regulatory_sources=regulatory,
                section_payload=section_payload,
            )
            name = f"slice-{slice_fingerprint(piece)}.json"
            path, status = self._keep(raw, piece, name, write=write)
            return EvidenceResult(payload=piece, path=path, status=status)
        payload = build_evidence_payload(
            normalized,
            raw,
            data_root=self.data_root,
            requested_term=requested_term,
            section_codes=section_codes,
            section_name_contains=section_name_contains,
            candidate_count=candidate_count,
            candidate_listing_completeness=candidate_listing_completeness,
            lookup_url=lookup_url,
            regulatory_sources=regulatory,
        )
        if write:
            path, status = self._write_evidence(raw, payload)
        else:
            path, status = self._evidence_path(raw, payload), NOT_WRITTEN
        return EvidenceResult(payload=payload, path=path, status=status)

    # 7. walk the structured data back to the preserved bytes and re-verify
    def verify(self, payload: dict[str, Any]) -> VerificationReport:
        """Re-verify an evidence bundle against the raw source it points at.

        Only the bundle is trusted as input. Every fact it asserts about the raw
        source is recomputed from the bytes on disk.
        """

        checks: list[Check] = []
        failures: list[dict[str, Any]] = []
        # An index describes the same preserved bytes without carrying any of the
        # text, so it is walked back entry by entry rather than passage by passage.
        is_index = payload.get("schema_version") == CORE_INDEX_SCHEMA_VERSION
        reverify = _reverify_index_entry if is_index else _reverify_section
        source = index_view(payload) if is_index else payload.get("label_source")
        # A slice names its passages label_evidence; the whole bundle calls them sections.
        sections = payload.get("sections")
        if sections is None:
            sections = payload.get("label_evidence")
        if not isinstance(source, dict) or not source or not isinstance(sections, list):
            return VerificationReport(
                ok=False,
                checks=(Check("bundle_shape", False, "evidence bundle is malformed"),),
            )

        try:
            raw_path = self._resolve_inside_root(str(source.get("raw_path", "")))
            raw_bytes = raw_path.read_bytes()
            checks.append(
                Check("raw_present", True, f"preserved raw source is readable at {raw_path}")
            )
        except (ProvenanceValidationFailure, OSError) as exc:
            return VerificationReport(
                ok=False,
                checks=(
                    *checks,
                    Check("raw_present", False, f"preserved raw source is unreachable: {exc}"),
                ),
            )

        expected_raw_sha256 = str(source.get("raw_sha256", ""))
        actual_raw_sha256 = sha256_bytes(raw_bytes)
        raw_ok = actual_raw_sha256 == expected_raw_sha256
        checks.append(
            Check(
                "raw_sha256",
                raw_ok,
                f"raw SHA-256 re-verified: {actual_raw_sha256}"
                if raw_ok
                else f"raw SHA-256 mismatch: bundle {expected_raw_sha256}, "
                f"file {actual_raw_sha256}",
            )
        )

        checks.append(self._check_metadata(source))

        if not raw_ok:
            # Re-reading passages from bytes that already failed their hash would
            # report agreement with the wrong document.
            return VerificationReport(ok=False, checks=tuple(checks))

        try:
            root = parse_document_root(raw_bytes)
        except Exception as exc:
            checks.append(Check("document_identity", False, f"raw source did not parse: {exc}"))
            return VerificationReport(ok=False, checks=tuple(checks))

        checks.append(self._check_document_identity(root, source))

        locators = build_locator_map(root)
        for index, section in enumerate(sections):
            failure = reverify(root, locators, section, index)
            if failure is not None:
                failures.append(failure)
        section_ok = not failures
        checks.append(
            Check(
                "section_evidence",
                section_ok,
                f"re-retrieved {len(sections)} section(s) from the preserved raw source "
                f"by evidence locator and re-verified their content hashes"
                if section_ok
                else f"{len(failures)} of {len(sections)} section(s) failed re-verification",
            )
        )
        if is_index:
            checks.append(_check_index_carries_no_text(sections))

        extraction = payload.get("extraction") or payload.get("completeness")
        declared = (
            (
                extraction.get("section_count")
                if is_index
                else extraction.get("returned_section_count")
            )
            if isinstance(extraction, dict)
            else None
        )
        count_ok = declared == len(sections)
        checks.append(
            Check(
                "section_count",
                count_ok,
                f"bundle declares and carries {len(sections)} section(s)"
                if count_ok
                else f"bundle declares {declared} section(s) but carries {len(sections)}",
            )
        )
        regulatory_checks, regulatory_failures = self._check_regulatory_sources(payload)
        checks.extend(regulatory_checks)
        failures.extend(regulatory_failures)
        return VerificationReport(
            ok=all(item.ok for item in checks) and not failures,
            checks=tuple(checks),
            failures=tuple(failures),
        )

    def run(
        self,
        drug: str,
        *,
        set_id: str | None = None,
        source_version: str | None = None,
        section_codes: tuple[str, ...] = (),
        section_name_contains: tuple[str, ...] = (),
        include_drugsfda: bool = False,
        index_only: bool = False,
        slice_only: bool = False,
        application_numbers: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        """Run the whole path for one drug and return every step's result."""

        acquisition = self.acquire(drug, set_id=set_id, source_version=source_version)
        if acquisition.raw is None:
            note = (
                "More than one official document matched. ODD core does not choose "
                "between them; re-run with --set-id (and --source-version if needed)."
                if acquisition.status == "ambiguous"
                else (
                    "The requested identity was not among the candidates retrieved, but "
                    "the official listing was not observed completely. This is not an "
                    "absence; the identity may exist in the part that was not read."
                )
            )
            return {
                "acquisition": acquisition.as_dict(),
                "status": acquisition.status,
                "note": note,
            }
        identity = acquisition.raw.identity
        evidence = self.extract(
            identity.source_document_id,
            identity.source_version,
            requested_term=drug,
            section_codes=section_codes,
            section_name_contains=section_name_contains,
            candidate_count=len(acquisition.candidates),
            candidate_listing_completeness=acquisition.listing_completeness,
            lookup_url=acquisition.lookup_url,
            include_drugsfda=include_drugsfda,
            index_only=index_only,
            slice_only=slice_only,
            application_numbers=application_numbers,
        )
        if index_only:
            # An index carries no passages and no rows, so there is nothing to walk
            # back to the source. Reporting a verification failure here would say the
            # evidence did not hold up, when no evidence was returned at all.
            return {
                "acquisition": acquisition.as_dict(),
                "evidence": evidence.payload,
                "evidence_path": str(evidence.path),
                "evidence_status": evidence.status,
                "status": "indexed",
                "verification": None,
            }
        verification = self.verify(evidence.payload)
        return {
            "acquisition": acquisition.as_dict(),
            "evidence": evidence.payload,
            "evidence_path": str(evidence.path),
            "evidence_status": evidence.status,
            "status": "verified" if verification.ok else "verification_failed",
            "verification": verification.as_dict(),
        }

    def load_evidence(
        self,
        set_id: str,
        source_version: str | None = None,
        *,
        file_name: str = "evidence.json",
    ) -> EvidenceResult:
        """Load a previously written artifact, so verification can start from the file.

        The full bundle, the index, and a slice all sit beside one another under
        the same identity, and all three are walked back to the same preserved
        bytes, so which one to re-verify is just a file name.
        """

        raw = self.raw_store.resolve(set_id, source_version)
        path = self._evidence_path(raw).with_name(_artifact_name(file_name))
        try:
            payload = json.loads(path.read_bytes())
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SourceNotFound(
                "no readable evidence bundle exists for this source identity",
                details={"evidence_path": str(path)},
            ) from exc
        if not isinstance(payload, dict):
            raise ProvenanceValidationFailure("evidence bundle must be a JSON object")
        return EvidenceResult(payload=payload, path=path, status="loaded")

    def _regulatory_sources(
        self,
        xml_bytes: bytes,
        spl_raw_sha256: str,
        *,
        application_numbers: tuple[str, ...] = (),
        offline: bool = False,
    ) -> list[dict[str, Any]]:
        """Cite what the FDA archive states about this label's application.

        ``offline`` reads an archive already preserved under this data root and
        retrieves nothing. With none preserved there is nothing to cite, and
        having nothing to read is not the archive saying this application does
        not exist, so the caller gets no sources rather than an absence dressed
        up as an answer.
        """

        snapshot = self._preserved_archive() if offline else self._retrieved_archive()
        if snapshot is None:
            return []
        # Take retrieval time from the immutable stored manifest, not the wall
        # clock, so the same archive bytes always produce the same bundle bytes.
        stored_retrieval = snapshot.metadata["retrieval"]
        archive_raw_path = relative_to_root(snapshot.archive_path, self.data_root)
        archive = {
            **stored_retrieval,
            "raw_metadata_path": relative_to_root(snapshot.metadata_path, self.data_root),
            "raw_path": archive_raw_path,
            "raw_sha256": snapshot.sha256,
        }

        root = parse_document_root(xml_bytes)
        references = extract_application_references(root, build_locator_map(root))
        if not references:
            # Nothing to filter and nothing to match: the SPL names no application.
            return [
                _regulatory_payload(
                    archive,
                    application_number=UNKNOWN,
                    status=UNKNOWN,
                    spl_evidence={"spl_raw_sha256": spl_raw_sha256},
                    fda_rows=(),
                    facts={},
                    diagnostic=(
                        "the preserved SPL states no FDA application identifier, so no "
                        "exact-match key exists; nothing was inferred from names."
                    ),
                )
            ]
        if application_numbers:
            # Exact identity only. A prefix, a bare number, or a different
            # application type is a different application, so it matches nothing.
            wanted = {value.strip().casefold() for value in application_numbers if value.strip()}
            references = tuple(
                reference
                for reference in references
                if reference.application_number.casefold() in wanted
            )
        sources: list[dict[str, Any]] = []
        for reference in references:
            link = find_application(
                snapshot.archive_path,
                reference,
                archive_sha256=snapshot.sha256,
                archive_raw_path=archive_raw_path,
            )
            sources.append(
                _regulatory_payload(
                    archive,
                    application_number=reference.application_number,
                    status=link.status,
                    spl_evidence={**reference.as_dict(), "spl_raw_sha256": spl_raw_sha256},
                    fda_rows=link.rows,
                    facts=link.facts,
                    diagnostic=link.diagnostic,
                )
            )
        return sources

    def _retrieved_archive(self) -> ArchiveSnapshot:
        """Retrieve the official archive and preserve its exact bytes."""

        plan = resolve_download()
        body, retrieval = retrieve_archive(plan)
        return self.drugsfda_store.store(body, retrieval)

    def _preserved_archive(self) -> ArchiveSnapshot | None:
        """The archive already preserved here, or nothing. Retrieves nothing.

        An archive is a dated snapshot of one continuously published dataset, not
        a document competing with another document, so the most recently
        retrieved one is the current one. Which snapshot was read is recorded in
        the bundle by path and digest and re-verified from its own bytes, so the
        choice is never something the reader has to take on trust.
        """

        preserved = self.drugsfda_store.preserved()
        if not preserved:
            return None
        return max(preserved, key=_retrieved_at)

    def _check_regulatory_sources(self, payload: dict[str, Any]) -> tuple[
        list[Check], list[dict[str, Any]]
    ]:
        """Walk every FDA fact back to the row it came from in the preserved archive."""

        sources = payload.get("regulatory_sources")
        if sources is None:
            sources = payload.get("regulatory_evidence")
        if not isinstance(sources, list) or not sources:
            return [], []
        checks: list[Check] = []
        failures: list[dict[str, Any]] = []
        archives_ok = rows_ok = links_ok = 0
        for index, source in enumerate(sources):
            if not isinstance(source, dict):
                failures.append({"index": index, "reason": "regulatory source is not an object"})
                continue
            archive = source.get("archive")
            if not isinstance(archive, dict):
                failures.append({"index": index, "reason": "regulatory source carries no archive"})
                continue
            try:
                archive_path = self._resolve_inside_root(str(archive.get("raw_path", "")))
                actual = sha256_file(archive_path)
            except (ProvenanceValidationFailure, OSError) as exc:
                failures.append({"index": index, "reason": f"preserved archive unreadable: {exc}"})
                continue
            if actual != archive.get("raw_sha256"):
                failures.append(
                    {
                        "index": index,
                        "reason": "preserved archive SHA-256 differs from the bundle",
                        "recomputed_archive_sha256": actual,
                    }
                )
                continue
            archives_ok += 1
            failures.extend(self._reread_rows(source, archive_path, index))
            rows_ok += len(_rows_of(source))
            link_failure = self._recheck_link(payload, source, archive_path, actual, index)
            if link_failure is None:
                links_ok += 1
            else:
                failures.append(link_failure)
        checks.append(
            Check(
                "regulatory_archive_sha256",
                archives_ok == len(sources),
                f"re-verified {archives_ok} of {len(sources)} preserved FDA archive(s)",
            )
        )
        checks.append(
            Check(
                "regulatory_row_evidence",
                not any("row" in str(item.get("reason", "")) for item in failures),
                f"re-read {rows_ok} FDA row(s) from the preserved archive by member and row number",
            )
        )
        checks.append(
            Check(
                "regulatory_link_status",
                links_ok == len(sources),
                f"recomputed {links_ok} of {len(sources)} link status(es) from preserved bytes",
            )
        )
        return checks, failures

    def _reread_rows(
        self, source: dict[str, Any], archive_path: Path, index: int
    ) -> list[dict[str, Any]]:
        failures: list[dict[str, Any]] = []
        for row in _rows_of(source):
            member = str(row.get("zip_member", ""))
            number = row.get("row_number")
            if not isinstance(number, int):
                failures.append({"index": index, "reason": "row evidence has no row number"})
                continue
            try:
                text = read_member_row(archive_path, member, number)
            except ODDError as exc:
                failures.append(
                    {"index": index, "reason": f"row could not be re-read: {exc.message}"}
                )
                continue
            if text != row.get("row_raw_text") or sha256_bytes(
                text.encode("utf-8")
            ) != row.get("row_sha256"):
                failures.append(
                    {
                        "index": index,
                        "reason": "the row at this locator differs from the bundle",
                        "row_number": number,
                        "zip_member": member,
                    }
                )
        return failures

    def _recheck_link(
        self,
        payload: dict[str, Any],
        source: dict[str, Any],
        archive_path: Path,
        archive_sha256: str,
        index: int,
    ) -> dict[str, Any] | None:
        link = source.get("link")
        if not isinstance(link, dict):
            return {"index": index, "reason": "regulatory source carries no link"}
        spl = link.get("spl_evidence")
        if not isinstance(spl, dict) or not spl.get("application_number"):
            return None if link.get("status") == UNKNOWN else {
                "index": index,
                "reason": "link claims a status without SPL evidence",
            }
        label = payload.get("label_source")
        if isinstance(label, dict) and spl.get("spl_raw_sha256") != label.get("raw_sha256"):
            return {"index": index, "reason": "link cites a different SPL than this bundle"}
        try:
            raw_bytes = self._resolve_inside_root(
                str(label.get("raw_path", "")) if isinstance(label, dict) else ""
            ).read_bytes()
            root = parse_document_root(raw_bytes)
        except (ProvenanceValidationFailure, OSError, ODDError) as exc:
            return {"index": index, "reason": f"the preserved SPL could not be reopened: {exc}"}
        # Every recorded position is re-resolved, not just the first one.
        occurrences: list[Occurrence] = []
        for recorded in _occurrences_of(spl):
            locator = str(recorded.get("xml_locator", ""))
            try:
                element = resolve_locator(root, locator)
            except (ProvenanceValidationFailure, ODDError) as exc:
                return {
                    "index": index,
                    "reason": f"SPL application locator did not resolve: {exc}",
                    "xml_locator": locator,
                }
            serialized = ElementTree.tostring(element, encoding="unicode").strip()
            digest = sha256_bytes(serialized.encode("utf-8"))
            if serialized != recorded.get("evidence_xml") or digest != recorded.get(
                "evidence_sha256"
            ):
                return {
                    "index": index,
                    "reason": "the SPL element at this locator differs from the bundle",
                    "xml_locator": locator,
                }
            occurrences.append(
                Occurrence(
                    xml_locator=locator, evidence_xml=serialized, evidence_sha256=digest
                )
            )
        declared = spl.get("occurrence_count")
        if isinstance(declared, int) and declared != len(occurrences):
            return {
                "index": index,
                "reason": "the bundle declares more SPL evidence positions than it carries",
            }
        reference = ApplicationReference(
            application_number=str(spl["application_number"]),
            application_type=str(spl.get("application_type", "")),
            numeric_key=_numeric_key(str(spl["application_number"])),
            occurrences=tuple(occurrences),
        )
        recomputed = find_application(
            archive_path,
            reference,
            archive_sha256=archive_sha256,
            archive_raw_path=str(source.get("archive", {}).get("raw_path", "")),
        )
        if recomputed.status != link.get("status"):
            return {
                "index": index,
                "reason": "recomputed link status differs from the bundle",
                "recomputed_status": recomputed.status,
                "recorded_status": link.get("status"),
            }
        if source.get("application_number") != spl.get("application_number"):
            return {"index": index, "reason": "application number differs from its SPL evidence"}
        return None

    def _check_metadata(self, source: dict[str, Any]) -> Check:
        try:
            metadata_path = self._resolve_inside_root(str(source.get("raw_metadata_path", "")))
            stored = json.loads(metadata_path.read_bytes())
            identity = stored["source_identity"]
        except (ProvenanceValidationFailure, OSError, KeyError, TypeError,
                json.JSONDecodeError) as exc:
            return Check("raw_metadata", False, f"raw metadata is unreadable: {exc}")
        official_id = source.get("official_document_id")
        version = source.get("document_version")
        # The stored manifest names these roles as authority/provider; the bundle
        # now names what each one actually is. Same facts, stated without the
        # implication that FDA published or verified the document.
        expected = {
            "authority": source.get("regulatory_recipient"),
            "jurisdiction": source.get("jurisdiction"),
            "provider": source.get("repository"),
            "raw_sha256": source.get("raw_sha256"),
            "source_document_id": (
                official_id.get("value") if isinstance(official_id, dict) else None
            ),
            "source_version": version.get("value") if isinstance(version, dict) else None,
        }
        mismatches = sorted(
            key for key, value in expected.items() if identity.get(key) != value
        )
        if mismatches:
            return Check(
                "raw_metadata",
                False,
                f"bundle provenance differs from the immutable raw manifest: "
                f"{', '.join(mismatches)}",
            )
        return Check(
            "raw_metadata",
            True,
            "bundle provenance matches the immutable raw manifest",
        )

    @staticmethod
    def _check_document_identity(
        root: ElementTree.Element, source: dict[str, Any]
    ) -> Check:
        set_element = root.find(f"{Q}setId")
        version_element = root.find(f"{Q}versionNumber")
        document_set_id = set_element.attrib.get("root") if set_element is not None else None
        document_version = (
            version_element.attrib.get("value") if version_element is not None else None
        )
        official_id = source.get("official_document_id")
        version = source.get("document_version")
        expected_set_id = official_id.get("value") if isinstance(official_id, dict) else None
        expected_version = version.get("value") if isinstance(version, dict) else None
        ok = (
            document_set_id is not None
            and expected_set_id is not None
            and document_set_id.casefold() == str(expected_set_id).casefold()
            and document_version == expected_version
        )
        return Check(
            "document_identity",
            ok,
            f"raw document declares set_id {document_set_id} version {document_version}"
            if ok
            else f"raw document declares set_id {document_set_id} version "
            f"{document_version}, bundle claims {expected_set_id} version {expected_version}",
        )

    def _resolve_inside_root(self, relative: str) -> Path:
        if not relative:
            raise ProvenanceValidationFailure("evidence bundle carries no source path")
        candidate = Path(relative)
        resolved = (
            candidate.resolve()
            if candidate.is_absolute()
            else (self.data_root / candidate).resolve()
        )
        if not resolved.is_relative_to(self.data_root):
            raise ProvenanceValidationFailure(
                "evidence bundle points outside the configured data root",
                details={"path": relative},
            )
        return resolved

    @staticmethod
    def _no_selection_decision(
        candidate: DailyMedCandidate, lookup: CandidateLookup
    ) -> SelectionDecision:
        return SelectionDecision(
            selected=candidate,
            ordered_candidates=tuple(lookup.candidates),
            rule_version=CORE_NO_SELECTION_RULE_VERSION,
            rule_description=_NO_SELECTION_DESCRIPTION,
            reason=(
                f"the caller-supplied identity matched exactly one official document: "
                f"set_id {candidate.set_id} version {candidate.source_version}; "
                f"{len(lookup.candidates)} candidate(s) were exposed and none were discarded."
            ),
            ambiguity_exposed=len(lookup.candidates) > 1,
        )

    def _evidence_path(self, raw: RawDocument, payload: dict[str, Any] | None = None) -> Path:
        """Give each distinct section filter its own file.

        A filtered request must never overwrite the document's full bundle, so a
        filter contributes a short fingerprint to the file name.
        """

        name = "evidence.json"
        extraction = (payload or {}).get("extraction")
        section_filter = extraction.get("section_filter") if isinstance(extraction, dict) else None
        if isinstance(section_filter, dict) and (
            section_filter.get("section_codes") or section_filter.get("section_name_contains")
        ):
            fingerprint = sha256_bytes(canonical_json_bytes(section_filter))[:12]
            name = f"evidence-filtered-{fingerprint}.json"
        return (
            self.evidence_root
            / "dailymed"
            / raw.identity.source_document_id
            / raw.identity.source_version
            / name
        )

    def _keep(
        self, raw: RawDocument, payload: dict[str, Any], file_name: str, *, write: bool
    ) -> tuple[Path, str]:
        """Write the derived artifact, or name where it would have gone."""

        if write:
            return self._write_derived(raw, payload, file_name)
        return self._evidence_path(raw).with_name(file_name), NOT_WRITTEN

    def _write_derived(
        self, raw: RawDocument, payload: dict[str, Any], file_name: str
    ) -> tuple[Path, str]:
        """Write a derived artifact beside the bundle, never over the raw source."""

        return self._write_at(self._evidence_path(raw).with_name(file_name), payload)

    def _write_evidence(
        self, raw: RawDocument, payload: dict[str, Any]
    ) -> tuple[Path, str]:
        return self._write_at(self._evidence_path(raw, payload), payload)

    def _write_at(self, path: Path, payload: dict[str, Any]) -> tuple[Path, str]:
        encoded = canonical_json_bytes(payload) + b"\n"
        if path.is_file():
            if sha256_file(path) == sha256_bytes(encoded):
                return path, "unchanged"
            status = "updated"
        else:
            status = "created"
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".odd-core-", suffix=".tmp", dir=path.parent
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, path)
        finally:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass
        return path, status


def _artifact_name(file_name: str) -> str:
    """Accept a file name and only a file name, so no path can be traversed."""

    name = file_name.strip()
    if not name or name != PurePosixPath(name).name or name in {".", ".."}:
        raise ProvenanceValidationFailure(
            "an evidence artifact is named by file name, not by path",
            details={"artifact": file_name},
        )
    return name


def _regulatory_payload(
    archive: dict[str, Any],
    *,
    application_number: str,
    status: str,
    spl_evidence: dict[str, Any],
    fda_rows: tuple[dict[str, Any], ...],
    facts: dict[str, Any],
    diagnostic: str | None,
) -> dict[str, Any]:
    return {
        "application_number": application_number,
        "archive": archive,
        "authority": "FDA",
        "fda_record": facts,
        "link": {
            "diagnostic": diagnostic,
            "fda_evidence": {"rows": list(fda_rows)},
            "key": "application_number",
            "spl_evidence": spl_evidence,
            "status": status,
        },
        "publisher": "U.S. Food and Drug Administration",
        "repository": "Drugs@FDA",
    }


def _retrieved_at(snapshot: ArchiveSnapshot) -> tuple[str, str]:
    """Order archives by when they were retrieved, with the digest breaking ties."""

    retrieval = snapshot.metadata.get("retrieval")
    stamp = retrieval.get("retrieved_at") if isinstance(retrieval, dict) else None
    return (str(stamp or ""), snapshot.sha256)


def _rows_of(source: dict[str, Any]) -> list[dict[str, Any]]:
    link = source.get("link")
    if not isinstance(link, dict):
        return []
    evidence = link.get("fda_evidence")
    if not isinstance(evidence, dict):
        return []
    rows = evidence.get("rows")
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _occurrences_of(spl_evidence: dict[str, Any]) -> list[dict[str, Any]]:
    """Every recorded SPL position for one application number."""

    recorded = spl_evidence.get("occurrences")
    if isinstance(recorded, list):
        return [item for item in recorded if isinstance(item, dict)]
    return [spl_evidence]


def _numeric_key(application_number: str) -> str:
    digits = "".join(character for character in application_number if character.isdecimal())
    return str(int(digits)) if digits else ""


def _check_index_carries_no_text(sections: list[Any]) -> Check:
    """An index that carries a passage has stopped being an index.

    The whole point of delivering an index first is that the caller spends no
    attention on text it did not ask for, so text leaking into one is a
    contract failure and not merely untidy.
    """

    carrying = [
        index
        for index, entry in enumerate(sections)
        if isinstance(entry, dict) and ("text" in entry or "original_text" in entry)
    ]
    return Check(
        "index_carries_no_text",
        not carrying,
        f"index describes {len(sections)} section(s) and carries none of their text"
        if not carrying
        else f"{len(carrying)} index entr(ies) carry section text",
    )


def _reverify_index_entry(
    root: ElementTree.Element,
    locators: dict[ElementTree.Element, str],
    entry: Any,
    index: int,
) -> dict[str, Any] | None:
    """Re-retrieve the passage an index entry points at without returning it.

    The entry states where a passage is, what it is called, how long it is, and
    what it hashes to. Every one of those is recomputed from the preserved bytes;
    the text itself is read and discarded, never carried back into the report.
    """

    if not isinstance(entry, dict):
        return {"index": index, "reason": "index entry is not an object"}
    locator = str(entry.get("evidence_locator", ""))
    try:
        element = resolve_locator(root, locator)
    except ProvenanceValidationFailure as exc:
        return {
            "index": index,
            "reason": exc.message,
            "section_code": entry.get("section_code"),
            "xml_locator": locator,
            **exc.details,
        }
    reread = read_section_evidence(element, locators)
    differences = []
    if reread.section_sha256 != entry.get("section_sha256"):
        differences.append("section_sha256")
    if sha256_bytes(reread.original_text.encode("utf-8")) != entry.get("text_sha256"):
        differences.append("text_sha256")
    if len(reread.original_text) != entry.get("text_length"):
        differences.append("text_length")
    if (reread.original_heading or UNKNOWN) != entry.get("section_name"):
        differences.append("section_name")
    if (reread.source_section_code or UNKNOWN) != entry.get("section_code"):
        differences.append("section_code")
    if not differences:
        return None
    return {
        "differing_fields": differences,
        "index": index,
        "reason": "the passage at this locator differs from the index entry",
        "recomputed_section_sha256": reread.section_sha256,
        "section_code": entry.get("section_code"),
        "xml_locator": locator,
    }


def _reverify_section(
    root: ElementTree.Element,
    locators: dict[ElementTree.Element, str],
    section: Any,
    index: int,
) -> dict[str, Any] | None:
    """Re-retrieve one passage from raw bytes; return a failure record or ``None``."""

    if not isinstance(section, dict):
        return {"index": index, "reason": "section entry is not an object"}
    evidence = section.get("evidence")
    if not isinstance(evidence, dict):
        return {"index": index, "reason": "section carries no evidence locator"}
    locator = str(evidence.get("xml_locator", ""))
    try:
        element = resolve_locator(root, locator)
    except ProvenanceValidationFailure as exc:
        return {
            "index": index,
            "reason": exc.message,
            "section_name": section.get("section_name"),
            "xml_locator": locator,
            **exc.details,
        }
    reread = read_section_evidence(element, locators)
    differences = []
    if reread.section_sha256 != evidence.get("section_sha256"):
        differences.append("section_sha256")
    if reread.original_text != section.get("text"):
        differences.append("text")
    if (reread.original_heading or UNKNOWN) != section.get("section_name"):
        differences.append("section_name")
    if (reread.source_section_code or UNKNOWN) != section.get("section_code"):
        differences.append("section_code")
    if sha256_bytes(reread.original_text.encode("utf-8")) != evidence.get("text_sha256"):
        differences.append("text_sha256")
    if not differences:
        return None
    return {
        "differing_fields": differences,
        "index": index,
        "reason": "the passage at this locator differs from the bundle",
        "recomputed_section_sha256": reread.section_sha256,
        "section_name": section.get("section_name"),
        "xml_locator": locator,
    }

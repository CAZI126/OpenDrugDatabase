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
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from odd.connectors.dailymed.client import DailyMedConnector
from odd.constants import CORE_NO_SELECTION_RULE_VERSION
from odd.core.evidence import UNKNOWN, build_evidence_payload
from odd.core.locator import resolve_locator
from odd.errors import ProvenanceValidationFailure, SourceNotFound
from odd.models import (
    CandidateLookup,
    DailyMedCandidate,
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

    @property
    def ambiguous(self) -> bool:
        return self.status == "ambiguous"

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "candidate_count": len(self.candidates),
            "candidates": [item.as_dict() for item in self.candidates],
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

        lookup = self.connector.lookup(drug)
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
        if not observed:
            raise SourceNotFound(
                "the official source returned no candidates for this term",
                details={"drug": drug, "lookup_url": lookup.source_url},
            )

        matches = tuple(lookup.candidates)
        if set_id is not None:
            wanted = set_id.strip().casefold()
            matches = tuple(item for item in matches if item.set_id.casefold() == wanted)
        if source_version is not None:
            wanted_version = source_version.strip()
            matches = tuple(item for item in matches if item.source_version == wanted_version)
        if not matches:
            raise SourceNotFound(
                "no official candidate matched the requested identity",
                details={
                    "candidates": [item.as_dict() for item in observed],
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
        lookup_url: str | None = None,
    ) -> EvidenceResult:
        """Extract sections from the preserved bytes and emit the evidence bundle."""

        raw = self.raw_store.resolve(set_id, source_version)
        xml_bytes = raw.label_path.read_bytes()
        normalized = self.parser.parse(xml_bytes, raw.identity)
        payload = build_evidence_payload(
            normalized,
            raw,
            data_root=self.data_root,
            requested_term=requested_term,
            section_codes=section_codes,
            section_name_contains=section_name_contains,
            candidate_count=candidate_count,
            lookup_url=lookup_url,
        )
        path, status = self._write_evidence(raw, payload)
        return EvidenceResult(payload=payload, path=path, status=status)

    # 7. walk the structured data back to the preserved bytes and re-verify
    def verify(self, payload: dict[str, Any]) -> VerificationReport:
        """Re-verify an evidence bundle against the raw source it points at.

        Only the bundle is trusted as input. Every fact it asserts about the raw
        source is recomputed from the bytes on disk.
        """

        checks: list[Check] = []
        failures: list[dict[str, Any]] = []
        source = payload.get("source")
        sections = payload.get("sections")
        if not isinstance(source, dict) or not isinstance(sections, list):
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
            failure = _reverify_section(root, locators, section, index)
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

        extraction = payload.get("extraction")
        declared = (
            extraction.get("returned_section_count") if isinstance(extraction, dict) else None
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
        return VerificationReport(
            ok=all(item.ok for item in checks),
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
    ) -> dict[str, Any]:
        """Run the whole path for one drug and return every step's result."""

        acquisition = self.acquire(drug, set_id=set_id, source_version=source_version)
        if acquisition.raw is None:
            return {
                "acquisition": acquisition.as_dict(),
                "status": acquisition.status,
                "note": (
                    "More than one official document matched. ODD core does not choose "
                    "between them; re-run with --set-id (and --source-version if needed)."
                ),
            }
        identity = acquisition.raw.identity
        evidence = self.extract(
            identity.source_document_id,
            identity.source_version,
            requested_term=drug,
            section_codes=section_codes,
            section_name_contains=section_name_contains,
            candidate_count=len(acquisition.candidates),
            lookup_url=acquisition.lookup_url,
        )
        verification = self.verify(evidence.payload)
        return {
            "acquisition": acquisition.as_dict(),
            "evidence": evidence.payload,
            "evidence_path": str(evidence.path),
            "evidence_status": evidence.status,
            "status": "verified" if verification.ok else "verification_failed",
            "verification": verification.as_dict(),
        }

    def load_evidence(self, set_id: str, source_version: str | None = None) -> EvidenceResult:
        """Load a previously written bundle, so verification can start from the file."""

        raw = self.raw_store.resolve(set_id, source_version)
        path = self._evidence_path(raw)
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
        expected = {
            "authority": source.get("authority"),
            "jurisdiction": source.get("jurisdiction"),
            "provider": source.get("provider"),
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

    def _write_evidence(
        self, raw: RawDocument, payload: dict[str, Any]
    ) -> tuple[Path, str]:
        path = self._evidence_path(raw, payload)
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

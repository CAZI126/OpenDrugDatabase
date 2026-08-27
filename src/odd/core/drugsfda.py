"""Drugs@FDA as a second primary source, preserved and cited the same way.

FDA publishes application, sponsor, product, and submission records as a
downloadable archive. ODD treats that archive exactly as it treats a label: the
bytes are preserved unmodified, hashed, and every fact returned from them
carries a locator that re-retrieves the same row from the same preserved bytes.

The link between a label and an application is an exact identifier match and
nothing else. ODD does not match on brand name, ingredient, sponsor similarity,
or search rank, and it never fills in an application number it did not read out
of the preserved SPL.
"""

from __future__ import annotations

import json
import re
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from xml.etree import ElementTree

from odd.errors import MalformedArchive, MalformedMetadata, NetworkFailure
from odd.provenance.canonical import canonical_json_bytes
from odd.provenance.hashing import sha256_bytes, sha256_file

LANDING_PAGE_URL = "https://www.fda.gov/drugs/drug-approvals-and-databases/drugsfda-data-files"
FDA_HOST_SUFFIX = "fda.gov"
ARCHIVE_FILE_NAME = "drugsatfda.zip"
MAX_LANDING_BYTES = 8 * 1024 * 1024
MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
DEFAULT_USER_AGENT = (
    "OpenDrugDatabase/0.5.0 (ODD-core; +https://github.com/CAZI126/OpenDrugDatabase)"
)

APPLICATIONS_TABLE = "Applications.txt"
PRODUCTS_TABLE = "Products.txt"
SUBMISSIONS_TABLE = "Submissions.txt"
MARKETING_STATUS_TABLE = "MarketingStatus.txt"
MARKETING_STATUS_LOOKUP = "MarketingStatus_Lookup.txt"

UNKNOWN = "UNKNOWN"

# The SPL approval identifier, e.g. NDA202155 / ANDA091321 / BLA125057.
_APPLICATION_ID = re.compile(r"^(?P<type>[A-Z]{2,5})(?P<number>\d{1,10})$")
_LINK_HREF = re.compile(r'href="([^"]+)"[^>]*title="([^"]*)"', re.IGNORECASE)
_DATA_UPDATED = re.compile(r"Data Last Updated:\s*([^<\n]{3,60})", re.IGNORECASE)

__all__ = [
    "ApplicationReference",
    "ArchiveSnapshot",
    "DrugsFdaStore",
    "LANDING_PAGE_URL",
    "LinkResult",
    "extract_application_references",
    "find_application",
    "read_member_row",
    "resolve_download",
    "retrieve_archive",
]


@dataclass(frozen=True, slots=True)
class Occurrence:
    """One position in the SPL where an application number is stated."""

    xml_locator: str
    evidence_xml: str
    evidence_sha256: str

    def as_dict(self) -> dict[str, str]:
        return {
            "evidence_sha256": self.evidence_sha256,
            "evidence_xml": self.evidence_xml,
            "xml_locator": self.xml_locator,
        }


@dataclass(frozen=True, slots=True)
class ApplicationReference:
    """An application number read out of the preserved SPL, with every position.

    A label states the same application number once per product, so the same
    value routinely appears several times. Keeping only the first position would
    silently discard evidence the document actually carries, so every occurrence
    is retained and the repeats are treated as repeats of one value.
    """

    application_number: str
    application_type: str
    numeric_key: str
    occurrences: tuple[Occurrence, ...]

    @property
    def xml_locator(self) -> str:
        return self.occurrences[0].xml_locator

    @property
    def evidence_xml(self) -> str:
        return self.occurrences[0].evidence_xml

    @property
    def evidence_sha256(self) -> str:
        return self.occurrences[0].evidence_sha256

    def as_dict(self) -> dict[str, Any]:
        return {
            "application_number": self.application_number,
            "application_type": self.application_type,
            "evidence_sha256": self.evidence_sha256,
            "evidence_xml": self.evidence_xml,
            "occurrence_count": len(self.occurrences),
            "occurrences": [item.as_dict() for item in self.occurrences],
            "xml_locator": self.xml_locator,
        }


@dataclass(frozen=True, slots=True)
class ArchiveSnapshot:
    """One preserved Drugs@FDA archive, addressed by the hash of its bytes."""

    archive_path: Path
    metadata_path: Path
    sha256: str
    already_stored: bool
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class LinkResult:
    """The outcome of looking one application number up in the preserved archive."""

    status: str
    rows: tuple[dict[str, Any], ...]
    facts: dict[str, Any]
    diagnostic: str | None = None


class _RedirectRecorder(HTTPRedirectHandler):
    """Record every hop so the retrieval path is part of the evidence."""

    def __init__(self) -> None:
        self.history: list[dict[str, Any]] = []

    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> Request | None:
        self.history.append({"from_url": req.full_url, "status": int(code), "to_url": newurl})
        if not _is_fda_https(newurl):
            raise NetworkFailure(
                "Drugs@FDA redirected outside the official FDA HTTPS origin",
                details={"requested_url": req.full_url, "response_url": newurl},
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


@dataclass(frozen=True, slots=True)
class _Response:
    status_code: int
    requested_url: str
    final_url: str
    body: bytes
    headers: dict[str, str]
    redirects: tuple[dict[str, Any], ...]
    retrieved_at: datetime


def _get(url: str, *, accept: str, max_bytes: int, timeout: float = 180.0) -> _Response:
    if not _is_fda_https(url):
        raise NetworkFailure(
            "Drugs@FDA retrieval requires an official FDA HTTPS URL", details={"url": url}
        )
    recorder = _RedirectRecorder()
    opener = build_opener(recorder)
    request = Request(url, headers={"Accept": accept, "User-Agent": DEFAULT_USER_AGENT})
    try:
        with opener.open(request, timeout=timeout) as response:  # noqa: S310
            body = response.read(max_bytes + 1)
            headers = {key.lower(): value for key, value in response.headers.items()}
            final_url = response.geturl()
            status = int(response.status)
    except HTTPError as exc:
        raise NetworkFailure(
            f"Drugs@FDA returned HTTP {exc.code}", details={"status_code": exc.code, "url": url}
        ) from exc
    except (TimeoutError, URLError, OSError) as exc:
        raise NetworkFailure(f"Drugs@FDA request failed: {exc}", details={"url": url}) from exc
    if len(body) > max_bytes:
        raise NetworkFailure(
            "Drugs@FDA response exceeds the configured byte limit",
            details={"maximum_bytes": max_bytes, "url": final_url},
        )
    if not _is_fda_https(final_url):
        raise NetworkFailure(
            "Drugs@FDA response came from outside the official FDA HTTPS origin",
            details={"response_url": final_url},
        )
    return _Response(
        status_code=status,
        requested_url=url,
        final_url=final_url,
        body=body,
        headers=headers,
        redirects=tuple(recorder.history),
        retrieved_at=datetime.now(UTC),
    )


def resolve_download(landing_page_url: str = LANDING_PAGE_URL) -> dict[str, Any]:
    """Read the official FDA page and resolve the archive URL it actually links to.

    The download location is never assumed or hardcoded; it is whatever the
    official page publishes at retrieval time.
    """

    response = _get(landing_page_url, accept="text/html", max_bytes=MAX_LANDING_BYTES)
    page = response.body.decode("utf-8", errors="replace")
    href = next(
        (
            value
            for value, title in _LINK_HREF.findall(page)
            if "drugs@fda" in title.casefold() and "data file" in title.casefold()
        ),
        None,
    )
    if href is None:
        raise MalformedMetadata(
            "the official Drugs@FDA page did not publish a recognizable data-file link",
            details={"landing_page_url": response.final_url},
        )
    download_url = urljoin(response.final_url, href)
    if not _is_fda_https(download_url):
        raise MalformedMetadata(
            "the resolved Drugs@FDA download link is not an official FDA HTTPS URL",
            details={"download_url": download_url},
        )
    updated = _DATA_UPDATED.search(page)
    return {
        "data_last_updated": updated.group(1).strip() if updated else UNKNOWN,
        "download_url": download_url,
        "landing_page_raw_sha256": sha256_bytes(response.body),
        "landing_page_retrieved_at": _iso(response.retrieved_at),
        "landing_page_status": response.status_code,
        "landing_page_url": response.final_url,
    }


def retrieve_archive(plan: dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
    """Retrieve the archive and everything needed to describe how it was retrieved."""

    response = _get(
        str(plan["download_url"]), accept="application/zip", max_bytes=MAX_ARCHIVE_BYTES
    )
    if not response.body:
        raise NetworkFailure(
            "Drugs@FDA returned an empty archive", details={"url": response.final_url}
        )
    declared = response.headers.get("content-length")
    return response.body, {
        "content_length_header": int(declared) if declared and declared.isdecimal() else None,
        "content_type": response.headers.get("content-type", UNKNOWN),
        "data_last_updated": plan["data_last_updated"],
        "final_url": response.final_url,
        "http_status": response.status_code,
        "landing_page_raw_sha256": plan["landing_page_raw_sha256"],
        "landing_page_retrieved_at": plan["landing_page_retrieved_at"],
        "landing_page_url": plan["landing_page_url"],
        "received_byte_count": len(response.body),
        "redirect_history": list(response.redirects),
        "requested_url": response.requested_url,
        "retrieved_at": _iso(response.retrieved_at),
    }


class DrugsFdaStore:
    """Preserve archives under the hash of their bytes, so nothing is ever replaced."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def store(self, body: bytes, retrieval: dict[str, Any]) -> ArchiveSnapshot:
        digest = sha256_bytes(body)
        directory = (self.root / "drugsfda" / digest).resolve()
        if not directory.is_relative_to(self.root):
            raise MalformedMetadata("Drugs@FDA storage path escaped its configured root")
        archive_path = directory / ARCHIVE_FILE_NAME
        metadata_path = directory / "metadata.json"
        already = archive_path.is_file()
        if already:
            if sha256_file(archive_path) != digest:
                raise MalformedArchive(
                    "a different archive is already stored at this content address",
                    details={"archive_path": str(archive_path), "raw_sha256": digest},
                )
        else:
            directory.mkdir(parents=True, exist_ok=True)
            archive_path.write_bytes(body)
            if sha256_file(archive_path) != digest:
                raise MalformedArchive("Drugs@FDA archive failed post-write verification")
        if not metadata_path.is_file():
            metadata = {
                "archive_file_name": ARCHIVE_FILE_NAME,
                "authority": "FDA",
                "raw_sha256": digest,
                "repository": "Drugs@FDA",
                "retrieval": retrieval,
            }
            metadata_path.write_bytes(canonical_json_bytes(metadata) + b"\n")
        return ArchiveSnapshot(
            archive_path=archive_path,
            metadata_path=metadata_path,
            sha256=digest,
            already_stored=already,
            metadata=json.loads(metadata_path.read_bytes()),
        )

    def preserved(self) -> tuple[ArchiveSnapshot, ...]:
        """Every archive already preserved here. Reads; never retrieves.

        The SHA-256 reported is the one the archive was stored under and recorded
        in its own manifest: the claim, not a fresh measurement. Measuring the
        bytes here instead would let an altered archive re-describe itself and
        then pass the verification that exists to catch exactly that.
        """

        container = (self.root / "drugsfda").resolve()
        if not container.is_relative_to(self.root) or not container.is_dir():
            return ()
        found: list[ArchiveSnapshot] = []
        for directory in sorted(container.iterdir()):
            archive_path = directory / ARCHIVE_FILE_NAME
            metadata_path = directory / "metadata.json"
            if not archive_path.is_file() or not metadata_path.is_file():
                continue
            try:
                metadata = json.loads(metadata_path.read_bytes())
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                # An unreadable manifest is not an archive that can be cited, and
                # is not a reason to hide the ones that can.
                continue
            if not isinstance(metadata, dict):
                continue
            found.append(
                ArchiveSnapshot(
                    archive_path=archive_path,
                    metadata_path=metadata_path,
                    sha256=str(metadata.get("raw_sha256") or directory.name),
                    already_stored=True,
                    metadata=metadata,
                )
            )
        return tuple(found)


def extract_application_references(
    root: ElementTree.Element,
    locators: dict[ElementTree.Element, str],
) -> tuple[ApplicationReference, ...]:
    """Read FDA application identifiers stated by the SPL, with their positions.

    Only identifiers the document itself carries in an ``approval`` element are
    returned. Nothing is inferred from a brand name, an ingredient, or a sponsor.
    """

    found: dict[str, list[Occurrence]] = {}
    types: dict[str, str] = {}
    numbers: dict[str, str] = {}
    for element in root.iter():
        if _local_name(element.tag) != "approval":
            continue
        identifier = next(
            (child for child in element if _local_name(child.tag) == "id"), None
        )
        if identifier is None:
            continue
        extension = (identifier.attrib.get("extension") or "").strip()
        match = _APPLICATION_ID.fullmatch(extension.upper())
        if match is None:
            continue
        number = extension.upper()
        serialized = ElementTree.tostring(identifier, encoding="unicode").strip()
        found.setdefault(number, []).append(
            Occurrence(
                xml_locator=locators[identifier],
                evidence_xml=serialized,
                evidence_sha256=sha256_bytes(serialized.encode("utf-8")),
            )
        )
        types.setdefault(number, match.group("type"))
        numbers.setdefault(number, str(int(match.group("number"))))
    return tuple(
        ApplicationReference(
            application_number=number,
            application_type=types[number],
            numeric_key=numbers[number],
            occurrences=tuple(found[number]),
        )
        for number in sorted(found)
    )


def read_member_row(archive_path: Path, member: str, row_number: int) -> str:
    """Re-read one row from a preserved archive by member name and row number."""

    try:
        with zipfile.ZipFile(archive_path) as archive:
            with archive.open(member) as stream:
                for current, line in enumerate(stream, start=1):
                    if current == row_number:
                        return line.decode("utf-8", errors="replace").rstrip("\r\n")
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        raise MalformedArchive(
            f"preserved Drugs@FDA archive could not be read: {exc}",
            details={"archive_path": str(archive_path), "member": member},
        ) from exc
    raise MalformedArchive(
        "the recorded row number is beyond the end of this archive member",
        details={"member": member, "row_number": row_number},
    )


def find_application(
    archive_path: Path,
    reference: ApplicationReference,
    *,
    archive_sha256: str,
    archive_raw_path: str,
) -> LinkResult:
    """Look one application number up in the preserved archive by exact identity.

    ``NOT_FOUND`` is returned only after every row of the applications table has
    been read. Anything that prevents that complete read returns ``UNKNOWN``.
    """

    try:
        with zipfile.ZipFile(archive_path) as archive:
            names = set(archive.namelist())
            if APPLICATIONS_TABLE not in names:
                return LinkResult(
                    status=UNKNOWN,
                    rows=(),
                    facts={},
                    diagnostic=f"{APPLICATIONS_TABLE} is absent from the preserved archive",
                )
            applications = _matching_rows(
                archive,
                APPLICATIONS_TABLE,
                lambda row: _same_application(row, reference),
            )
            if not applications:
                return LinkResult(
                    status="NOT_FOUND",
                    rows=(),
                    facts={},
                    diagnostic=(
                        f"every row of {APPLICATIONS_TABLE} was read; no row states "
                        f"application {reference.application_number}"
                    ),
                )
            status = "EXACT" if len(applications) == 1 else "MULTIPLE"
            rows = [_row_payload(APPLICATIONS_TABLE, r, archive_sha256, archive_raw_path)
                    for r in applications]
            facts: dict[str, Any] = {}
            if status == "EXACT":
                application = applications[0]
                products = _matching_rows(
                    archive, PRODUCTS_TABLE, lambda row: _same_appl_no(row, reference)
                )
                submissions = _matching_rows(
                    archive, SUBMISSIONS_TABLE, lambda row: _same_appl_no(row, reference)
                )
                marketing = _matching_rows(
                    archive, MARKETING_STATUS_TABLE, lambda row: _same_appl_no(row, reference)
                )
                lookup = _marketing_lookup(archive, names)
                rows.extend(
                    _row_payload(PRODUCTS_TABLE, r, archive_sha256, archive_raw_path)
                    for r in products
                )
                rows.extend(
                    _row_payload(SUBMISSIONS_TABLE, r, archive_sha256, archive_raw_path)
                    for r in submissions
                )
                facts = _facts(application, products, submissions, marketing, lookup)
            return LinkResult(status=status, rows=tuple(rows), facts=facts)
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        return LinkResult(
            status=UNKNOWN,
            rows=(),
            facts={},
            diagnostic=f"the preserved Drugs@FDA archive could not be read completely: {exc}",
        )


@dataclass(frozen=True, slots=True)
class _Row:
    table: str
    row_number: int
    raw_text: str
    values: dict[str, str]


def _matching_rows(
    archive: zipfile.ZipFile,
    member: str,
    predicate: Any,
) -> list[_Row]:
    if member not in set(archive.namelist()):
        return []
    result: list[_Row] = []
    with archive.open(member) as stream:
        header_line = stream.readline().decode("utf-8", errors="replace").rstrip("\r\n")
        header = header_line.split("\t")
        for row_number, line in enumerate(stream, start=2):
            text = line.decode("utf-8", errors="replace").rstrip("\r\n")
            if not text:
                continue
            values = dict(zip(header, text.split("\t"), strict=False))
            if predicate(values):
                result.append(_Row(member, row_number, text, values))
    return result


def _marketing_lookup(archive: zipfile.ZipFile, names: set[str]) -> dict[str, str]:
    if MARKETING_STATUS_LOOKUP not in names:
        return {}
    rows = _matching_rows(archive, MARKETING_STATUS_LOOKUP, lambda row: True)
    return {
        row.values.get("MarketingStatusID", ""): row.values.get("MarketingStatusDescription", "")
        for row in rows
    }


def _same_application(values: dict[str, str], reference: ApplicationReference) -> bool:
    return _same_appl_no(values, reference) and (
        values.get("ApplType", "").strip().upper() == reference.application_type
    )


def _same_appl_no(values: dict[str, str], reference: ApplicationReference) -> bool:
    raw = values.get("ApplNo", "").strip()
    return raw.isdecimal() and str(int(raw)) == reference.numeric_key


def _row_payload(
    table: str, row: _Row, archive_sha256: str, archive_raw_path: str
) -> dict[str, Any]:
    return {
        "archive_raw_path": archive_raw_path,
        "archive_sha256": archive_sha256,
        "row_number": row.row_number,
        "row_raw_text": row.raw_text,
        "row_sha256": sha256_bytes(row.raw_text.encode("utf-8")),
        "table_name": table,
        "zip_member": row.table,
    }


def _facts(
    application: _Row,
    products: list[_Row],
    submissions: list[_Row],
    marketing: list[_Row],
    lookup: dict[str, str],
) -> dict[str, Any]:
    """Return FDA's own field values. Absent means UNKNOWN, never a guess."""

    status_by_product = {
        row.values.get("ProductNo", ""): lookup.get(
            row.values.get("MarketingStatusID", ""), UNKNOWN
        )
        for row in marketing
    }
    return {
        "application_number": _value(application.values, "ApplNo"),
        "application_type": _value(application.values, "ApplType"),
        "sponsor_name": _value(application.values, "SponsorName"),
        "application_public_notes": _value(application.values, "ApplPublicNotes"),
        "products": [
            {
                "product_number": _value(row.values, "ProductNo"),
                "product_name": _value(row.values, "DrugName"),
                "active_ingredient": _value(row.values, "ActiveIngredient"),
                "dosage_form_and_route": _value(row.values, "Form"),
                "strength": _value(row.values, "Strength"),
                "marketing_status": status_by_product.get(
                    row.values.get("ProductNo", ""), UNKNOWN
                ),
            }
            for row in products
        ],
        "submissions": [
            {
                "submission_type": _value(row.values, "SubmissionType"),
                "submission_number": _value(row.values, "SubmissionNo"),
                "submission_status": _value(row.values, "SubmissionStatus"),
                "action_date": _value(row.values, "SubmissionStatusDate"),
                "review_priority": _value(row.values, "ReviewPriority"),
            }
            for row in submissions
        ],
    }


def _value(values: dict[str, str], name: str) -> str:
    value = values.get(name, "").strip()
    return value or UNKNOWN


def _is_fda_https(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
    except ValueError:
        return False
    return bool(
        parsed.scheme.casefold() == "https"
        and host is not None
        and (host.casefold() == FDA_HOST_SUFFIX or host.casefold().endswith(f".{FDA_HOST_SUFFIX}"))
        and parsed.username is None
        and parsed.password is None
    )


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")

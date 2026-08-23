"""Small synchronous client for the documented DailyMed REST API v2."""

from __future__ import annotations

import json
import math
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from http.client import HTTPMessage
from io import BytesIO
from pathlib import PurePosixPath
from typing import IO, TYPE_CHECKING, Any, Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zipfile import BadZipFile, ZipFile

from odd.constants import CONNECTOR_VERSION, DAILYMED_QUERY_RESULTS_SCOPE
from odd.errors import MalformedArchive, MalformedMetadata, NetworkFailure, SourceNotFound
from odd.models import (
    CandidateDiscoveryPage,
    CandidateLookup,
    DailyMedCandidate,
    DailyMedHistory,
    DailyMedHistoryEntry,
    DiscoveryCompleteness,
    DownloadedSource,
    HTTPAttemptEvidence,
)
from odd.provenance.canonical import canonical_json_bytes
from odd.provenance.hashing import sha256_bytes
from odd.provenance.identifiers import live_candidate_snapshot_id

if TYPE_CHECKING:
    # Packaging detail belongs to ODD-005 enrichment. Retrieving and preserving an
    # official document must not require importing enrichment definitions, so the
    # model is resolved inside the one method that builds it.
    from odd.models.enrichment import CandidateDetailPage

DEFAULT_BASE_URL = "https://dailymed.nlm.nih.gov/dailymed/services/v2"
DEFAULT_ARCHIVE_BASE_URL = "https://dailymed.nlm.nih.gov/dailymed"
DEFAULT_USER_AGENT = (
    "OpenDrugDatabase/0.5.0 (ODD-005; +https://github.com/CAZI126/OpenDrugDatabase)"
)
MAX_ARCHIVED_XML_BYTES = 64 * 1024 * 1024
MAX_JSON_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_XML_RESPONSE_BYTES = 64 * 1024 * 1024
MAX_TRANSPORT_RESPONSE_BYTES = MAX_XML_RESPONSE_BYTES
DEFAULT_MAX_RETRIES = 2
DEFAULT_RETRY_BACKOFF_SECONDS = 0.5
DEFAULT_MAX_BACKOFF_SECONDS = 8.0
DEFAULT_INTER_REQUEST_DELAY_SECONDS = 0.2
LIVE_PAGE_SIZE = 100
DETAIL_PAGE_SIZE = 100
MAX_DETAIL_JSON_RESPONSE_BYTES = 512 * 1024
HUMAN_PRESCRIPTION_DOCUMENT_CODE = "34391-3"
_DAILYMED_DATE = re.compile(r"^([A-Za-z]{3}) (\d{2}), (\d{4})$")
_MONTHS = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}


@dataclass(frozen=True, slots=True)
class HTTPResponse:
    status_code: int
    url: str
    body: bytes
    headers: dict[str, str]
    attempts: tuple[HTTPAttemptEvidence, ...] = ()


class MalformedDetailResponse(MalformedMetadata):
    """A valid HTTP representation whose exact bytes fail detail parsing."""

    def __init__(self, message: str, *, response: HTTPResponse) -> None:
        super().__init__(message)
        self.response = response


class HTTPTransport(Protocol):
    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
        max_bytes: int,
    ) -> HTTPResponse: ...


class _SameOriginRedirectHandler(HTTPRedirectHandler):
    """Reject an off-origin redirect before urllib sends the follow-up request."""

    def redirect_request(
        self,
        req: Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> Request | None:
        if not _same_origin(req.full_url, newurl):
            raise NetworkFailure(
                "DailyMed redirected outside the configured HTTPS origin",
                details={
                    "requested_url": req.full_url,
                    "response_url": newurl,
                    "transient": False,
                },
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class UrllibTransport:
    """Standard-library HTTP transport kept behind a mockable interface."""

    def __init__(self) -> None:
        self._opener = build_opener(_SameOriginRedirectHandler())

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
        max_bytes: int,
    ) -> HTTPResponse:
        request = Request(url, headers=dict(headers), method="GET")
        try:
            with self._opener.open(request, timeout=timeout) as response:  # noqa: S310
                body = response.read(max_bytes + 1)
                return HTTPResponse(
                    status_code=int(response.status),
                    url=response.geturl(),
                    body=body,
                    headers={key.lower(): value for key, value in response.headers.items()},
                )
        except HTTPError as exc:
            body = exc.read(max_bytes + 1)
            return HTTPResponse(
                status_code=int(exc.code),
                url=exc.geturl(),
                body=body,
                headers={key.lower(): value for key, value in exc.headers.items()},
            )
        except (TimeoutError, URLError, OSError) as exc:
            raise NetworkFailure(
                f"DailyMed request failed: {exc}", details={"url": url}
            ) from exc


class DailyMedConnector:
    """Retrieve DailyMed candidates and exact SPL response bytes."""

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        archive_base_url: str = DEFAULT_ARCHIVE_BASE_URL,
        timeout_seconds: float = 30.0,
        user_agent: str = DEFAULT_USER_AGENT,
        transport: HTTPTransport | None = None,
        clock: Callable[[], datetime] | None = None,
        sleep: Callable[[float], None] | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS,
        max_backoff_seconds: float = DEFAULT_MAX_BACKOFF_SECONDS,
        inter_request_delay_seconds: float = DEFAULT_INTER_REQUEST_DELAY_SECONDS,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.archive_base_url = archive_base_url.rstrip("/")
        _require_https_origin(self.base_url, name="base_url")
        _require_https_origin(self.archive_base_url, name="archive_base_url")
        self.timeout_seconds = timeout_seconds
        self.user_agent = user_agent
        self.transport = transport or UrllibTransport()
        self.clock = clock or (lambda: datetime.now(UTC))
        if max_retries < 0:
            raise ValueError("max_retries must not be negative")
        if (
            retry_backoff_seconds < 0
            or max_backoff_seconds < 0
            or inter_request_delay_seconds < 0
        ):
            raise ValueError("retry backoff values must not be negative")
        self.sleep = sleep or time.sleep
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self.max_backoff_seconds = max_backoff_seconds
        self.inter_request_delay_seconds = inter_request_delay_seconds

    def with_operational_limits(
        self,
        *,
        timeout_seconds: float,
        max_retries: int,
        inter_request_delay_seconds: float,
    ) -> DailyMedConnector:
        """Reuse the configured origin/transport with one explicit bounded execution policy."""

        return DailyMedConnector(
            base_url=self.base_url,
            archive_base_url=self.archive_base_url,
            timeout_seconds=timeout_seconds,
            user_agent=self.user_agent,
            transport=self.transport,
            clock=self.clock,
            sleep=self.sleep,
            max_retries=max_retries,
            retry_backoff_seconds=self.retry_backoff_seconds,
            max_backoff_seconds=self.max_backoff_seconds,
            inter_request_delay_seconds=inter_request_delay_seconds,
        )

    def lookup(self, drug: str, *, page: int = 1) -> CandidateLookup:
        normalized_drug = drug.strip()
        if not normalized_drug:
            raise MalformedMetadata("drug lookup term must not be blank")
        if page <= 0:
            raise ValueError("lookup page must be positive")
        query = urlencode(
            [("drug_name", normalized_drug), ("page", str(page)), ("pagesize", "100")]
        )
        url = f"{self.base_url}/spls.json?{query}"
        response = self._get(
            url,
            accept="application/json",
            expected_content_types=("application/json", "text/json"),
            max_response_bytes=MAX_JSON_RESPONSE_BYTES,
        )
        if not response.body:
            raise MalformedMetadata("DailyMed metadata response was empty", details={"url": url})
        try:
            decoded = json.loads(response.body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MalformedMetadata(
                "DailyMed metadata response was not valid UTF-8 JSON",
                details={"url": response.url},
            ) from exc
        if not isinstance(decoded, dict):
            raise MalformedMetadata("DailyMed metadata response must be a JSON object")
        payload = cast(dict[str, Any], decoded)
        raw_candidates = payload.get("data")
        if not isinstance(raw_candidates, list):
            raise MalformedMetadata("DailyMed metadata response has no data array")

        candidates = tuple(
            self._parse_candidate(item, index) for index, item in enumerate(raw_candidates)
        )
        return CandidateLookup(
            candidates=candidates,
            source_url=response.url,
            retrieved_at=self._utc_now(),
            raw_body=response.body,
            payload=payload,
        )

    def discover(self, drug: str) -> CandidateLookup:
        """Preserve and validate every page in one current human-Rx observation.

        The official ``/spls`` response does not expose every field required by the
        selection policy. Query-derived facts are explicitly identified in candidate
        metadata; missing facts remain missing and therefore cannot manufacture a
        winner.
        """

        normalized_drug = drug.strip()
        if not normalized_drug:
            raise MalformedMetadata("drug lookup term must not be blank")
        request_filters = tuple(
            sorted(
                (
                    ("doctype", HUMAN_PRESCRIPTION_DOCUMENT_CODE),
                    ("drug_name", normalized_drug),
                    ("name_type", "generic"),
                    ("pagesize", str(LIVE_PAGE_SIZE)),
                )
            )
        )
        endpoint = f"{self.base_url}/spls.json"
        canonical_request = (("endpoint", endpoint), *request_filters)
        pages: list[CandidateDiscoveryPage] = []
        candidates: list[DailyMedCandidate] = []
        raw_candidate_values: list[dict[str, Any]] = []
        failure_attempts: tuple[HTTPAttemptEvidence, ...] = ()
        diagnostic: str | None = None
        completeness = DiscoveryCompleteness.INCOMPLETE
        metadata_total: int | None = None
        expected_pages: int | None = None
        elements_per_page: int | None = None
        page_number = 1

        while True:
            query_values = (*request_filters, ("page", str(page_number)))
            url = f"{endpoint}?{urlencode(query_values)}"
            try:
                response = self._get(
                    url,
                    accept="application/json",
                    expected_content_types=("application/json", "text/json"),
                    max_response_bytes=MAX_JSON_RESPONSE_BYTES,
                )
            except NetworkFailure as exc:
                failure_attempts = _attempts_from_error(exc)
                diagnostic = f"{exc.category.value}: {exc.message}"
                break

            page = CandidateDiscoveryPage(
                page_number=page_number,
                request_url=url,
                canonical_query=tuple(query_values),
                response_url=response.url,
                status_code=response.status_code,
                content_type=response.headers.get("content-type", ""),
                retrieved_at=self._utc_now(),
                etag=response.headers.get("etag"),
                last_modified=response.headers.get("last-modified"),
                raw_body=response.body,
                raw_sha256=sha256_bytes(response.body),
                attempts=response.attempts,
            )
            pages.append(page)

            try:
                payload = _decode_json_object(response.body, response.url)
                metadata = _metadata_object(payload, page_number)
                page_total = _strict_nonnegative_int(metadata, "total_elements")
                page_size = _strict_positive_int(metadata, "elements_per_page", maximum=100)
                page_count = _strict_nonnegative_int(metadata, "total_pages")
                current_page = _strict_positive_int(metadata, "current_page")
                if current_page != page_number:
                    raise MalformedMetadata(
                        "DailyMed metadata current_page differs from the requested page",
                        details={"requested_page": page_number, "current_page": current_page},
                    )
                raw_values = payload.get("data")
                if not isinstance(raw_values, list):
                    raise MalformedMetadata("DailyMed metadata response has no data array")
                if len(raw_values) > page_size:
                    raise MalformedMetadata(
                        "DailyMed page contains more candidates than elements_per_page",
                        details={"page": page_number, "candidate_count": len(raw_values)},
                    )
                if metadata_total is None:
                    metadata_total = page_total
                    expected_pages = page_count
                    elements_per_page = page_size
                    mathematically_expected = (
                        math.ceil(page_total / page_size) if page_total else 0
                    )
                    if page_count not in (
                        mathematically_expected,
                        1 if mathematically_expected == 0 else mathematically_expected,
                    ):
                        raise MalformedMetadata(
                            "DailyMed total_pages is inconsistent with candidate totals",
                            details={
                                "total_elements": page_total,
                                "elements_per_page": page_size,
                                "total_pages": page_count,
                            },
                        )
                elif (
                    page_total != metadata_total
                    or page_count != expected_pages
                    or page_size != elements_per_page
                ):
                    raise MalformedMetadata(
                        "DailyMed pagination metadata changed between pages",
                        details={"page": page_number},
                    )
                for value in raw_values:
                    if not isinstance(value, dict):
                        raise MalformedMetadata(
                            "DailyMed candidate must be an object",
                            details={"page": page_number},
                        )
                    raw_value = cast(dict[str, Any], value)
                    parsed = self._parse_candidate(raw_value, len(candidates))
                    evidence_metadata = {
                        **raw_value,
                        "_odd_live_evidence": {
                            "api_scope": "current SPL information",
                            "doctype_filter": HUMAN_PRESCRIPTION_DOCUMENT_CODE,
                            "drug_name_filter": normalized_drug,
                            "name_type_filter": "generic",
                            "unsupported_fields": [
                                "active_ingredients",
                                "dosage_form",
                                "route",
                                "labeler",
                                "marketing_category",
                                "repackaged",
                            ],
                        },
                        "product_type": "HUMAN PRESCRIPTION DRUG",
                        "status": "current",
                        "source_url": (
                            f"{self.base_url}/spls/{quote(parsed.set_id, safe='')}.xml"
                        ),
                    }
                    candidates.append(
                        DailyMedCandidate(
                            set_id=parsed.set_id,
                            source_version=parsed.source_version,
                            title=parsed.title,
                            published_date=parsed.published_date,
                            metadata=evidence_metadata,
                        )
                    )
                    raw_candidate_values.append(dict(raw_value))
            except MalformedMetadata as exc:
                completeness = DiscoveryCompleteness.INVALID
                diagnostic = f"{exc.category.value}: {exc.message}"
                break

            if expected_pages is None or page_number >= max(expected_pages, 1):
                completeness = DiscoveryCompleteness.COMPLETE
                break
            page_number += 1
            if self.inter_request_delay_seconds:
                self.sleep(self.inter_request_delay_seconds)

        duplicate_count, conflict_count = _candidate_consistency_counts(raw_candidate_values)
        retrieved_count = len(candidates)
        if completeness is DiscoveryCompleteness.COMPLETE:
            if metadata_total != retrieved_count:
                completeness = DiscoveryCompleteness.INCOMPLETE
                diagnostic = (
                    "DailyMed metadata total_elements does not equal the retained candidate "
                    f"count ({metadata_total} != {retrieved_count})"
                )
            elif duplicate_count:
                completeness = DiscoveryCompleteness.INCOMPLETE
                diagnostic = (
                    f"DailyMed pagination repeated {duplicate_count} candidate identity value(s)"
                )
            elif conflict_count:
                completeness = DiscoveryCompleteness.INCOMPLETE
                diagnostic = (
                    f"DailyMed returned conflicting metadata for {conflict_count} set ID(s)"
                )

        terminal_fingerprint = ""
        if diagnostic is not None:
            terminal_fingerprint = sha256_bytes(
                canonical_json_bytes(
                    {
                        "completeness": completeness,
                        "diagnostic": diagnostic,
                        "failure_attempts": failure_attempts,
                    }
                )
            )
        snapshot_id = live_candidate_snapshot_id(
            canonical_request,
            tuple((page.page_number, page.raw_sha256) for page in pages),
            connector_version=CONNECTOR_VERSION,
            terminal_fingerprint=terminal_fingerprint,
        )
        merged_payload = {
            "data": [candidate.metadata for candidate in candidates],
            "metadata": {
                "completeness": completeness.value,
                "retrieved_elements": retrieved_count,
                "total_elements": metadata_total,
                "total_pages": expected_pages,
            },
            "snapshot_id": snapshot_id,
        }
        return CandidateLookup(
            candidates=tuple(candidates),
            source_url=pages[0].response_url if pages else f"{self.base_url}/spls.json",
            retrieved_at=pages[0].retrieved_at if pages else self._utc_now(),
            raw_body=canonical_json_bytes(merged_payload),
            payload=merged_payload,
            pages=tuple(pages),
            canonical_request=canonical_request,
            snapshot_id=snapshot_id,
            metadata_total_elements=metadata_total,
            retrieved_candidate_count=retrieved_count,
            total_pages=expected_pages,
            completeness=completeness,
            duplicate_count=duplicate_count,
            metadata_conflict_count=conflict_count,
            diagnostic_message=diagnostic,
            failure_attempts=failure_attempts,
            intended_use_scope=DAILYMED_QUERY_RESULTS_SCOPE,
        )

    def download(
        self,
        candidate: DailyMedCandidate,
        *,
        max_response_bytes: int = MAX_XML_RESPONSE_BYTES,
    ) -> DownloadedSource:
        encoded_set_id = quote(candidate.set_id, safe="")
        url = f"{self.base_url}/spls/{encoded_set_id}.xml"
        response = self._get(
            url,
            # DailyMed's documented .xml endpoint returns application/xml but
            # rejects an explicit ``Accept: application/xml`` with HTTP 406.
            # A wildcard keeps content negotiation neutral; the response is
            # still required to be XML below before any bytes are accepted.
            accept="*/*",
            expected_content_types=("application/xml", "text/xml"),
            max_response_bytes=max_response_bytes,
        )
        if not response.body:
            raise NetworkFailure(
                "DailyMed returned an empty SPL response",
                details={"set_id": candidate.set_id, "url": response.url},
            )
        _validate_xml_representation(response.body, response)
        return DownloadedSource(
            set_id=candidate.set_id,
            source_version=candidate.source_version,
            source_url=response.url,
            retrieved_at=self._utc_now(),
            body=response.body,
            status_code=response.status_code,
            headers=response.headers,
            http_attempts=response.attempts,
        )

    def packaging_page(
        self,
        set_id: str,
        *,
        page_number: int,
        max_response_bytes: int = MAX_DETAIL_JSON_RESPONSE_BYTES,
    ) -> CandidateDetailPage:
        """Fetch one documented packaging-detail page and retain exact bytes."""

        normalized_set_id = set_id.strip()
        if not normalized_set_id:
            raise MalformedMetadata("DailyMed packaging set_id must not be blank")
        if page_number <= 0:
            raise ValueError("packaging page_number must be positive")
        if max_response_bytes <= 0:
            raise ValueError("packaging max_response_bytes must be positive")
        encoded_set_id = quote(normalized_set_id, safe="")
        endpoint = f"{self.base_url}/spls/{encoded_set_id}/packaging.json"
        query_values = (
            ("page", str(page_number)),
            ("pagesize", str(DETAIL_PAGE_SIZE)),
        )
        url = f"{endpoint}?{urlencode(query_values)}"
        response = self._get(
            url,
            accept="application/json",
            expected_content_types=("application/json", "text/json"),
            max_response_bytes=max_response_bytes,
        )
        try:
            return _parse_packaging_page(
                response,
                normalized_set_id=normalized_set_id,
                page_number=page_number,
                endpoint=endpoint,
                request_url=url,
                retrieved_at=self._utc_now(),
            )
        except MalformedMetadata as exc:
            raise MalformedDetailResponse(exc.message, response=response) from exc

    def history(self, set_id: str) -> DailyMedHistory:
        normalized_set_id = set_id.strip()
        if not normalized_set_id:
            raise MalformedMetadata("DailyMed history set_id must not be blank")
        encoded_set_id = quote(normalized_set_id, safe="")
        url = f"{self.base_url}/spls/{encoded_set_id}/history.json"
        response = self._get(
            url,
            accept="application/json",
            expected_content_types=("application/json", "text/json"),
            max_response_bytes=MAX_JSON_RESPONSE_BYTES,
        )
        if not response.body:
            raise MalformedMetadata(
                "DailyMed history response was empty", details={"url": response.url}
            )
        try:
            decoded = json.loads(response.body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MalformedMetadata(
                "DailyMed history response was not valid UTF-8 JSON",
                details={"url": response.url},
            ) from exc
        if not isinstance(decoded, dict):
            raise MalformedMetadata("DailyMed history response must be a JSON object")
        payload = cast(dict[str, Any], decoded)
        data = payload.get("data")
        if not isinstance(data, dict):
            raise MalformedMetadata("DailyMed history response has no data object")
        spl = data.get("spl")
        values = data.get("history")
        if not isinstance(spl, dict) or not isinstance(values, list):
            raise MalformedMetadata("DailyMed history response has malformed SPL history data")
        returned_set_id = spl.get("setid")
        title = spl.get("title")
        if not isinstance(returned_set_id, str) or not isinstance(title, str):
            raise MalformedMetadata("DailyMed history SPL identity is malformed")
        if returned_set_id.casefold() != normalized_set_id.casefold():
            raise MalformedMetadata(
                "DailyMed history set_id differs from the request",
                details={"requested_set_id": normalized_set_id, "returned_set_id": returned_set_id},
            )
        entries = tuple(self._parse_history_entry(item, index) for index, item in enumerate(values))
        versions = [item.source_version for item in entries]
        if not entries:
            raise SourceNotFound(
                "DailyMed returned no history entries", details={"set_id": normalized_set_id}
            )
        if len(versions) != len(set(versions)):
            raise MalformedMetadata("DailyMed history contains duplicate source versions")
        return DailyMedHistory(
            source_document_id=returned_set_id,
            title=title.strip(),
            entries=entries,
            source_url=response.url,
            retrieved_at=self._utc_now(),
            raw_body=response.body,
            payload=payload,
        )

    def download_version(
        self,
        history: DailyMedHistory,
        source_version: str,
    ) -> DownloadedSource:
        version = source_version.strip()
        if not version:
            raise MalformedMetadata("historical source version must not be blank")
        if not any(item.source_version == version for item in history.entries):
            raise SourceNotFound(
                "requested source version is absent from DailyMed history",
                details={
                    "set_id": history.source_document_id,
                    "source_version": version,
                    "known_versions": [item.source_version for item in history.entries],
                },
            )
        query = urlencode(
            [("type", "zip"), ("setid", history.source_document_id), ("version", version)]
        )
        url = f"{self.archive_base_url}/getFile.cfm?{query}"
        response = self._get(
            url,
            accept="application/zip",
            expected_content_types=(
                "application/zip",
                "application/x-zip-compressed",
                "application/octet-stream",
            ),
            max_response_bytes=MAX_XML_RESPONSE_BYTES,
        )
        xml_body, member_name = _extract_archive_xml(response.body)
        _validate_xml_representation(xml_body, response)
        return DownloadedSource(
            set_id=history.source_document_id,
            source_version=version,
            source_url=response.url,
            retrieved_at=self._utc_now(),
            body=xml_body,
            status_code=response.status_code,
            headers=response.headers,
            http_attempts=response.attempts,
            container_body=response.body,
            container_format="zip",
            container_member=member_name,
        )

    def _get(
        self,
        url: str,
        *,
        accept: str,
        expected_content_types: tuple[str, ...] | None = None,
        max_response_bytes: int | None = None,
    ) -> HTTPResponse:
        expected = expected_content_types or (accept,)
        maximum = max_response_bytes or (
            MAX_JSON_RESPONSE_BYTES if "json" in accept else MAX_XML_RESPONSE_BYTES
        )
        attempts: list[HTTPAttemptEvidence] = []
        for attempt_number in range(1, self.max_retries + 2):
            try:
                response = self.transport.get(
                    url,
                    headers={"Accept": accept, "User-Agent": self.user_agent},
                    timeout=self.timeout_seconds,
                    max_bytes=maximum,
                )
            except NetworkFailure as exc:
                retry = (
                    exc.details.get("transient") is not False
                    and attempt_number <= self.max_retries
                )
                delay = self._backoff(attempt_number) if retry else None
                attempts.append(
                    HTTPAttemptEvidence(
                        attempt_number=attempt_number,
                        status_code=_optional_status(exc.details.get("status_code")),
                        error_category=exc.category.value,
                        diagnostic_message=exc.message,
                        retry_after_seconds=None,
                        backoff_seconds=delay,
                        retry_eligible=retry,
                        response_size_bytes=None,
                    )
                )
                if retry:
                    if delay:
                        self.sleep(delay)
                    continue
                raise NetworkFailure(
                    exc.message,
                    details={**exc.details, "attempts": _attempt_payload(attempts)},
                ) from exc

            response = HTTPResponse(
                status_code=response.status_code,
                url=response.url,
                body=response.body,
                headers={key.lower(): value for key, value in response.headers.items()},
                attempts=response.attempts,
            )
            status = response.status_code
            if 200 <= status < 300:
                try:
                    self._validate_response(
                        requested_url=url,
                        response=response,
                        expected_content_types=expected,
                        max_response_bytes=maximum,
                    )
                except NetworkFailure as exc:
                    attempts.append(
                        HTTPAttemptEvidence(
                            attempt_number=attempt_number,
                            status_code=status,
                            error_category=exc.category.value,
                            diagnostic_message=exc.message,
                            retry_after_seconds=None,
                            backoff_seconds=None,
                            retry_eligible=False,
                            response_size_bytes=len(response.body),
                        )
                    )
                    raise NetworkFailure(
                        exc.message,
                        details={
                            **exc.details,
                            "attempts": _attempt_payload(attempts),
                            "status_code": status,
                            "transient": False,
                        },
                    ) from exc
                attempts.append(
                    HTTPAttemptEvidence(
                        attempt_number=attempt_number,
                        status_code=status,
                        error_category=None,
                        diagnostic_message=None,
                        retry_after_seconds=None,
                        backoff_seconds=None,
                        retry_eligible=False,
                        response_size_bytes=len(response.body),
                    )
                )
                return HTTPResponse(
                    status_code=response.status_code,
                    url=response.url,
                    body=response.body,
                    headers={key.lower(): value for key, value in response.headers.items()},
                    attempts=tuple(attempts),
                )

            transient = status == 429 or 500 <= status <= 599
            retry = transient and attempt_number <= self.max_retries
            retry_after = (
                self._retry_after_seconds(response.headers.get("retry-after"))
                if status == 429
                else None
            )
            retry_after_exceeds_cap = bool(
                retry
                and retry_after is not None
                and retry_after > self.max_backoff_seconds
            )
            if retry_after_exceeds_cap:
                retry = False
            delay = (
                min(
                    self.max_backoff_seconds,
                    retry_after if retry_after is not None else self._backoff(attempt_number),
                )
                if retry
                else None
            )
            diagnostic = response.body[:512].decode("utf-8", errors="replace").strip()
            if retry_after_exceeds_cap:
                diagnostic = (
                    f"{diagnostic + '; ' if diagnostic else ''}"
                    f"Retry-After {retry_after} seconds exceeds the configured "
                    f"{self.max_backoff_seconds}-second in-process wait cap"
                )
            attempts.append(
                HTTPAttemptEvidence(
                    attempt_number=attempt_number,
                    status_code=status,
                    error_category="transient_http" if transient else "permanent_http",
                    diagnostic_message=diagnostic or f"HTTP {status}",
                    retry_after_seconds=retry_after,
                    backoff_seconds=delay,
                    retry_eligible=retry,
                    response_size_bytes=len(response.body),
                )
            )
            if retry:
                if delay:
                    self.sleep(delay)
                continue
            raise NetworkFailure(
                f"DailyMed returned HTTP {status}",
                details={
                    "attempts": _attempt_payload(attempts),
                    "status_code": status,
                    "transient": transient,
                    "url": response.url,
                },
            )
        raise AssertionError("bounded retry loop did not return or raise")

    def _validate_response(
        self,
        *,
        requested_url: str,
        response: HTTPResponse,
        expected_content_types: tuple[str, ...],
        max_response_bytes: int,
    ) -> None:
        if not _same_origin(requested_url, response.url):
            raise NetworkFailure(
                "DailyMed redirected outside the configured HTTPS origin",
                details={
                    "requested_url": requested_url,
                    "response_url": response.url,
                    "transient": False,
                },
            )
        if len(response.body) > max_response_bytes:
            raise NetworkFailure(
                "DailyMed response exceeds the configured byte limit",
                details={
                    "byte_count": len(response.body),
                    "maximum_bytes": max_response_bytes,
                    "transient": False,
                    "url": response.url,
                },
            )
        length_header = response.headers.get("content-length")
        if length_header is not None:
            try:
                expected_length = int(length_header)
            except ValueError as exc:
                raise NetworkFailure(
                    "DailyMed Content-Length header is malformed",
                    details={
                        "content_length": length_header,
                        "transient": False,
                        "url": response.url,
                    },
                ) from exc
            if expected_length != len(response.body):
                raise NetworkFailure(
                    "DailyMed response byte count differs from Content-Length",
                    details={
                        "content_length": expected_length,
                        "received_bytes": len(response.body),
                        "transient": False,
                        "url": response.url,
                    },
                )
        content_type = response.headers.get("content-type", "")
        media_type = content_type.split(";", 1)[0].strip().casefold()
        if media_type not in {value.casefold() for value in expected_content_types}:
            raise NetworkFailure(
                "DailyMed response Content-Type does not match the requested representation",
                details={
                    "content_type": content_type,
                    "expected": list(expected_content_types),
                    "transient": False,
                    "url": response.url,
                },
            )

    def _backoff(self, attempt_number: int) -> float:
        return float(
            min(
                self.max_backoff_seconds,
                self.retry_backoff_seconds * (2 ** (attempt_number - 1)),
            )
        )

    def _retry_after_seconds(self, value: str | None) -> float | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        try:
            seconds = float(normalized)
            if math.isfinite(seconds) and seconds >= 0:
                return seconds
            return None
        except ValueError:
            pass
        try:
            retry_at = parsedate_to_datetime(normalized)
        except (TypeError, ValueError, OverflowError):
            return None
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=UTC)
        return max(0.0, (retry_at.astimezone(UTC) - self._utc_now()).total_seconds())

    def _utc_now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @staticmethod
    def _parse_candidate(value: object, index: int) -> DailyMedCandidate:
        if not isinstance(value, dict):
            raise MalformedMetadata(
                "DailyMed candidate must be an object", details={"candidate_index": index}
            )
        item = cast(dict[str, Any], value)
        required = ("setid", "spl_version", "title", "published_date")
        missing = [field for field in required if field not in item]
        if missing:
            raise MalformedMetadata(
                "DailyMed candidate is missing required fields",
                details={"candidate_index": index, "missing": missing},
            )
        set_id = item["setid"]
        version = item["spl_version"]
        title = item["title"]
        published_date = item["published_date"]
        if not isinstance(set_id, str) or not set_id.strip():
            raise MalformedMetadata("DailyMed candidate setid must be a non-empty string")
        if isinstance(version, bool) or not isinstance(version, (str, int)):
            raise MalformedMetadata("DailyMed candidate spl_version must be text or an integer")
        normalized_version = str(version).strip()
        if not normalized_version:
            raise MalformedMetadata("DailyMed candidate spl_version must not be blank")
        if not isinstance(title, str) or not title.strip():
            raise MalformedMetadata("DailyMed candidate title must be a non-empty string")
        if not isinstance(published_date, str):
            raise MalformedMetadata("DailyMed candidate published_date must be a string")
        return DailyMedCandidate(
            set_id=set_id.strip(),
            source_version=normalized_version,
            title=title.strip(),
            published_date=published_date.strip(),
            metadata=dict(item),
        )

    @staticmethod
    def _parse_history_entry(value: object, index: int) -> DailyMedHistoryEntry:
        if not isinstance(value, dict):
            raise MalformedMetadata(
                "DailyMed history entry must be an object",
                details={"history_index": index},
            )
        item = cast(dict[str, Any], value)
        version = item.get("spl_version")
        published = item.get("published_date")
        if isinstance(version, bool) or not isinstance(version, (str, int)):
            raise MalformedMetadata("DailyMed history spl_version must be text or an integer")
        normalized_version = str(version).strip()
        if not normalized_version or not isinstance(published, str) or not published.strip():
            raise MalformedMetadata("DailyMed history entry has incomplete version metadata")
        published_text = published.strip()
        try:
            match = _DAILYMED_DATE.fullmatch(published_text)
            if match is None or match.group(1) not in _MONTHS:
                raise ValueError("unrecognized DailyMed month/date form")
            published_date = date(
                int(match.group(3)), _MONTHS[match.group(1)], int(match.group(2))
            )
        except ValueError as exc:
            raise MalformedMetadata(
                "DailyMed history published_date must use Mon DD, YYYY",
                details={"published_date": published_text, "source_version": normalized_version},
            ) from exc
        return DailyMedHistoryEntry(
            source_version=normalized_version,
            published_date=published_date,
            published_date_text=published_text,
            sequence_index=index,
        )


def _parse_packaging_page(
    response: HTTPResponse,
    *,
    normalized_set_id: str,
    page_number: int,
    endpoint: str,
    request_url: str,
    retrieved_at: datetime,
) -> CandidateDetailPage:
    from odd.models.enrichment import CandidateDetailPage

    payload = _decode_json_object(response.body, response.url)
    data_value = payload.get("data")
    if not isinstance(data_value, dict):
        raise MalformedMetadata("DailyMed packaging response has no data object")
    data = cast(dict[str, Any], data_value)
    returned_set_id = data.get("setid")
    source_version = data.get("spl_version")
    title = data.get("title")
    published_date = data.get("published_date")
    products_value = data.get("products")
    if not isinstance(returned_set_id, str) or not returned_set_id.strip():
        raise MalformedMetadata("DailyMed packaging setid must be non-empty text")
    if isinstance(source_version, bool) or not isinstance(source_version, (str, int)):
        raise MalformedMetadata("DailyMed packaging spl_version must be text or an integer")
    normalized_version = str(source_version).strip()
    if not normalized_version:
        raise MalformedMetadata("DailyMed packaging spl_version must not be blank")
    if not isinstance(title, str) or not title.strip():
        raise MalformedMetadata("DailyMed packaging title must be non-empty text")
    if not isinstance(published_date, str) or not published_date.strip():
        raise MalformedMetadata("DailyMed packaging published_date must be non-empty text")
    if not isinstance(products_value, list):
        raise MalformedMetadata("DailyMed packaging products must be an array")
    if len(products_value) > DETAIL_PAGE_SIZE:
        raise MalformedMetadata(
            "DailyMed packaging page exceeds the documented page size",
            details={"page": page_number, "product_count": len(products_value)},
        )
    products: list[dict[str, object]] = []
    for index, product in enumerate(products_value):
        if not isinstance(product, dict):
            raise MalformedMetadata(
                "DailyMed packaging product must be an object",
                details={"page": page_number, "product_index": index},
            )
        products.append(cast(dict[str, object], product))
    return CandidateDetailPage(
        set_id=returned_set_id,
        observed_source_version=normalized_version,
        title=title.strip(),
        published_date=published_date.strip(),
        page_number=page_number,
        page_size=DETAIL_PAGE_SIZE,
        request_url=request_url,
        canonical_request=(
            ("endpoint", endpoint),
            ("page", str(page_number)),
            ("pagesize", str(DETAIL_PAGE_SIZE)),
            ("setid", normalized_set_id.casefold()),
        ),
        final_url=response.url,
        status_code=response.status_code,
        content_type=response.headers.get("content-type", ""),
        retrieved_at=retrieved_at,
        etag=response.headers.get("etag"),
        last_modified=response.headers.get("last-modified"),
        raw_body=response.body,
        raw_sha256=sha256_bytes(response.body),
        payload=cast(dict[str, object], payload),
        products=tuple(products),
        attempts=response.attempts,
    )


def _validate_xml_representation(body: bytes, response: HTTPResponse) -> None:
    """Reject bytes that cannot be an XML representation before raw storage.

    Full SPL parsing intentionally remains a later, quarantinable stage: exact raw
    evidence must survive malformed or unsupported SPL structures.
    """

    details = {
        "attempts": _attempt_payload(list(response.attempts)),
        "raw_sha256": sha256_bytes(body),
        "status_code": response.status_code,
        "transient": False,
        "url": response.url,
    }
    if not body.lstrip().startswith(b"<"):
        raise NetworkFailure(
            "DailyMed response declared XML but its bytes are not an XML representation",
            details=details,
        )


def _effective_port(scheme: str, port: int | None) -> int | None:
    if port is not None:
        return port
    return {"http": 80, "https": 443}.get(scheme.casefold())


def _same_origin(requested_url: str, response_url: str) -> bool:
    try:
        requested = urlsplit(requested_url)
        returned = urlsplit(response_url)
        requested_hostname = requested.hostname
        returned_hostname = returned.hostname
        requested_port = _effective_port(requested.scheme, requested.port)
        returned_port = _effective_port(returned.scheme, returned.port)
    except ValueError:
        return False
    return bool(
        requested.scheme.casefold() == "https"
        and returned.scheme.casefold() == requested.scheme.casefold()
        and requested_hostname is not None
        and returned_hostname is not None
        and returned_hostname.casefold() == requested_hostname.casefold()
        and returned_port == requested_port
        and requested.username is None
        and requested.password is None
        and returned.username is None
        and returned.password is None
    )


def _require_https_origin(url: str, *, name: str) -> None:
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"{name} must contain a valid HTTPS origin") from exc
    if (
        parsed.scheme.casefold() != "https"
        or hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        and not 1 <= port <= 65535
    ):
        raise ValueError(f"{name} must contain a valid HTTPS origin")


def _extract_archive_xml(body: bytes) -> tuple[bytes, str]:
    if not body:
        raise MalformedArchive("DailyMed historical ZIP response was empty")
    try:
        with ZipFile(BytesIO(body)) as archive:
            candidates = [
                item for item in archive.infolist() if item.filename.lower().endswith(".xml")
            ]
            if len(candidates) != 1:
                raise MalformedArchive(
                    "DailyMed historical ZIP must contain exactly one SPL XML member",
                    details={"xml_member_count": len(candidates)},
                )
            member = candidates[0]
            path = PurePosixPath(member.filename.replace("\\", "/"))
            if path.is_absolute() or ".." in path.parts:
                raise MalformedArchive("DailyMed historical ZIP contains an unsafe XML path")
            if member.file_size > MAX_ARCHIVED_XML_BYTES:
                raise MalformedArchive("DailyMed historical XML exceeds the supported size limit")
            xml_body = archive.read(member)
    except MalformedArchive:
        raise
    except (BadZipFile, KeyError, OSError) as exc:
        raise MalformedArchive(f"DailyMed historical ZIP could not be read: {exc}") from exc
    if len(xml_body) != member.file_size:
        raise MalformedArchive("DailyMed historical XML byte length differs from ZIP metadata")
    return xml_body, member.filename


def _decode_json_object(body: bytes, url: str) -> dict[str, Any]:
    if not body:
        raise MalformedMetadata("DailyMed metadata response was empty", details={"url": url})
    try:
        decoded = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MalformedMetadata(
            "DailyMed metadata response was not valid UTF-8 JSON",
            details={"url": url},
        ) from exc
    if not isinstance(decoded, dict):
        raise MalformedMetadata("DailyMed metadata response must be a JSON object")
    return cast(dict[str, Any], decoded)


def _metadata_object(payload: dict[str, Any], page_number: int) -> dict[str, Any]:
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        raise MalformedMetadata(
            "DailyMed response has no metadata object",
            details={"page": page_number},
        )
    return cast(dict[str, Any], metadata)


def _strict_nonnegative_int(metadata: dict[str, Any], name: str) -> int:
    value = metadata.get(name)
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise MalformedMetadata(
            f"DailyMed metadata {name} must be a non-negative integer",
            details={"field": name, "value_type": type(value).__name__},
        )
    normalized = str(value).strip()
    if not normalized.isdecimal():
        raise MalformedMetadata(
            f"DailyMed metadata {name} must be a non-negative integer",
            details={"field": name},
        )
    return int(normalized)


def _strict_positive_int(
    metadata: dict[str, Any],
    name: str,
    *,
    maximum: int | None = None,
) -> int:
    result = _strict_nonnegative_int(metadata, name)
    if result <= 0 or (maximum is not None and result > maximum):
        raise MalformedMetadata(
            f"DailyMed metadata {name} is outside the supported range",
            details={"field": name, "maximum": maximum},
        )
    return result


def _candidate_consistency_counts(values: list[dict[str, Any]]) -> tuple[int, int]:
    by_set_id: dict[str, set[str]] = {}
    duplicate_count = 0
    for value in values:
        set_id = value.get("setid")
        if not isinstance(set_id, str) or not set_id.strip():
            continue
        digest = sha256_bytes(canonical_json_bytes(value))
        known = by_set_id.setdefault(set_id.strip().casefold(), set())
        if digest in known:
            duplicate_count += 1
        known.add(digest)
    conflict_count = sum(len(digests) > 1 for digests in by_set_id.values())
    return duplicate_count, conflict_count


def _attempt_payload(values: list[HTTPAttemptEvidence]) -> list[dict[str, object]]:
    return [
        {
            "attempt_number": value.attempt_number,
            "backoff_seconds": value.backoff_seconds,
            "diagnostic_message": value.diagnostic_message,
            "error_category": value.error_category,
            "retry_after_seconds": value.retry_after_seconds,
            "retry_eligible": value.retry_eligible,
            "response_size_bytes": value.response_size_bytes,
            "status_code": value.status_code,
        }
        for value in values
    ]


def _attempts_from_error(error: NetworkFailure) -> tuple[HTTPAttemptEvidence, ...]:
    raw = error.details.get("attempts")
    if not isinstance(raw, list):
        return ()
    result: list[HTTPAttemptEvidence] = []
    for value in raw:
        if not isinstance(value, dict):
            continue
        try:
            result.append(
                HTTPAttemptEvidence(
                    attempt_number=int(value["attempt_number"]),
                    status_code=_optional_status(value.get("status_code")),
                    error_category=(
                        str(value["error_category"])
                        if value.get("error_category") is not None
                        else None
                    ),
                    diagnostic_message=(
                        str(value["diagnostic_message"])
                        if value.get("diagnostic_message") is not None
                        else None
                    ),
                    retry_after_seconds=(
                        float(value["retry_after_seconds"])
                        if value.get("retry_after_seconds") is not None
                        else None
                    ),
                    backoff_seconds=(
                        float(value["backoff_seconds"])
                        if value.get("backoff_seconds") is not None
                        else None
                    ),
                    retry_eligible=bool(value["retry_eligible"]),
                    response_size_bytes=(
                        int(value["response_size_bytes"])
                        if value.get("response_size_bytes") is not None
                        else None
                    ),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return tuple(result)


def _optional_status(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if not isinstance(value, (str, int)):
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None

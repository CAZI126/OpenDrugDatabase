"""Small synchronous client for the documented DailyMed REST API v2."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from io import BytesIO
from pathlib import PurePosixPath
from typing import Any, Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from zipfile import BadZipFile, ZipFile

from odd.errors import MalformedArchive, MalformedMetadata, NetworkFailure, SourceNotFound
from odd.models import (
    CandidateLookup,
    DailyMedCandidate,
    DailyMedHistory,
    DailyMedHistoryEntry,
    DownloadedSource,
)

DEFAULT_BASE_URL = "https://dailymed.nlm.nih.gov/dailymed/services/v2"
DEFAULT_ARCHIVE_BASE_URL = "https://dailymed.nlm.nih.gov/dailymed"
DEFAULT_USER_AGENT = "OpenDrugDatabase/0.2 (ODD-002)"
MAX_ARCHIVED_XML_BYTES = 64 * 1024 * 1024
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


class HTTPTransport(Protocol):
    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
    ) -> HTTPResponse: ...


class UrllibTransport:
    """Standard-library HTTP transport kept behind a mockable interface."""

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
    ) -> HTTPResponse:
        request = Request(url, headers=dict(headers), method="GET")
        try:
            with urlopen(request, timeout=timeout) as response:  # noqa: S310
                body = response.read()
                return HTTPResponse(
                    status_code=int(response.status),
                    url=response.geturl(),
                    body=body,
                    headers={key.lower(): value for key, value in response.headers.items()},
                )
        except HTTPError as exc:
            diagnostic = exc.read(512).decode("utf-8", errors="replace").strip()
            raise NetworkFailure(
                f"DailyMed returned HTTP {exc.code}",
                details={"status_code": exc.code, "url": url, "response": diagnostic},
            ) from exc
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
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.archive_base_url = archive_base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.user_agent = user_agent
        self.transport = transport or UrllibTransport()
        self.clock = clock or (lambda: datetime.now(UTC))

    def lookup(self, drug: str) -> CandidateLookup:
        normalized_drug = drug.strip()
        if not normalized_drug:
            raise MalformedMetadata("drug lookup term must not be blank")
        query = urlencode(
            [("drug_name", normalized_drug), ("page", "1"), ("pagesize", "100")]
        )
        url = f"{self.base_url}/spls.json?{query}"
        response = self._get(url, accept="application/json")
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

    def download(self, candidate: DailyMedCandidate) -> DownloadedSource:
        encoded_set_id = quote(candidate.set_id, safe="")
        url = f"{self.base_url}/spls/{encoded_set_id}.xml"
        response = self._get(url, accept="application/xml")
        if not response.body:
            raise NetworkFailure(
                "DailyMed returned an empty SPL response",
                details={"set_id": candidate.set_id, "url": response.url},
            )
        return DownloadedSource(
            set_id=candidate.set_id,
            source_version=candidate.source_version,
            source_url=response.url,
            retrieved_at=self._utc_now(),
            body=response.body,
            status_code=response.status_code,
            headers=response.headers,
        )

    def history(self, set_id: str) -> DailyMedHistory:
        normalized_set_id = set_id.strip()
        if not normalized_set_id:
            raise MalformedMetadata("DailyMed history set_id must not be blank")
        encoded_set_id = quote(normalized_set_id, safe="")
        url = f"{self.base_url}/spls/{encoded_set_id}/history.json"
        response = self._get(url, accept="application/json")
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
        response = self._get(url, accept="application/zip")
        xml_body, member_name = _extract_archive_xml(response.body)
        return DownloadedSource(
            set_id=history.source_document_id,
            source_version=version,
            source_url=response.url,
            retrieved_at=self._utc_now(),
            body=xml_body,
            status_code=response.status_code,
            headers=response.headers,
            container_body=response.body,
            container_format="zip",
            container_member=member_name,
        )

    def _get(self, url: str, *, accept: str) -> HTTPResponse:
        response = self.transport.get(
            url,
            headers={"Accept": accept, "User-Agent": self.user_agent},
            timeout=self.timeout_seconds,
        )
        if not 200 <= response.status_code < 300:
            raise NetworkFailure(
                f"DailyMed returned HTTP {response.status_code}",
                details={"status_code": response.status_code, "url": response.url},
            )
        return response

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

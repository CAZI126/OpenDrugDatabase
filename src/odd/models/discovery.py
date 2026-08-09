"""Typed immutable evidence for paginated DailyMed discovery."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class DiscoveryCompleteness(StrEnum):
    """Whether a discovery snapshot proves that every advertised result was retained."""

    UNKNOWN = "UNKNOWN"
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    INVALID = "INVALID"


@dataclass(frozen=True, slots=True)
class HTTPAttemptEvidence:
    """One bounded HTTP attempt; timestamps remain operational evidence."""

    attempt_number: int
    status_code: int | None
    error_category: str | None
    diagnostic_message: str | None
    retry_after_seconds: float | None
    backoff_seconds: float | None
    retry_eligible: bool
    response_size_bytes: int | None = None


@dataclass(frozen=True, slots=True)
class CandidateDiscoveryPage:
    """Exact response evidence for one numbered candidate-discovery page."""

    page_number: int
    request_url: str
    canonical_query: tuple[tuple[str, str], ...]
    response_url: str
    status_code: int
    content_type: str
    retrieved_at: datetime
    etag: str | None
    last_modified: str | None
    raw_body: bytes
    raw_sha256: str
    attempts: tuple[HTTPAttemptEvidence, ...]

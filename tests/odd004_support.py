"""Offline-only transports and service helpers for ODD-004 live observations."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from odd.connectors.dailymed.client import DailyMedConnector, HTTPResponse
from odd.errors import NetworkFailure
from odd.service import ODDService, create_service
from odd.utilization import load_utilization_list
from tests.odd003_support import synthetic_spl
from tests.odd_support import FixedClock

BASE_URL = "https://dailymed.example/services/v2"


def discovery_candidate(
    ingredient: str,
    *,
    rank: int = 1,
    source_version: str = "1",
    complete_selection_metadata: bool = False,
) -> dict[str, object]:
    """Return synthetic search metadata, never a claim about the live API."""

    value: dict[str, object] = {
        "published_date": "Aug 08, 2026",
        "setid": f"00000000-0000-4000-8000-{rank:012d}",
        "spl_version": source_version,
        "title": f"{ingredient.upper()}- {ingredient} tablet",
    }
    if complete_selection_metadata:
        value.update(
            {
                "active_ingredients": [ingredient],
                "brand_name": ingredient.upper(),
                "dosage_form": "TABLET",
                "generic_name": ingredient,
                "labeler": "Synthetic Validation Manufacturer",
                "marketing_category": "ANDA",
                "product_type": "HUMAN PRESCRIPTION DRUG",
                "repackaged": False,
                "route": "ORAL",
                "status": "current",
            }
        )
    return value


def discovery_body(
    candidates: list[dict[str, object]],
    *,
    current_page: object = "1",
    elements_per_page: object = "100",
    total_elements: object | None = None,
    total_pages: object = "1",
) -> bytes:
    return json.dumps(
        {
            "data": candidates,
            "metadata": {
                "current_page": current_page,
                "elements_per_page": elements_per_page,
                "total_elements": len(candidates)
                if total_elements is None
                else total_elements,
                "total_pages": total_pages,
            },
        },
        allow_nan=True,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def response(
    body: bytes,
    *,
    status: int = 200,
    content_type: str = "application/json; charset=UTF-8",
    url: str = "",
    headers: Mapping[str, str] | None = None,
) -> HTTPResponse:
    values = {
        "content-length": str(len(body)),
        "content-type": content_type,
        **dict(headers or {}),
    }
    return HTTPResponse(status, url, body, values)


class SequenceTransport:
    """Return a bounded sequence of HTTP results and record every request."""

    def __init__(self, values: list[HTTPResponse | NetworkFailure]) -> None:
        self.values = list(values)
        self.requests: list[str] = []

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
        max_bytes: int,
    ) -> HTTPResponse:
        del headers, timeout, max_bytes
        self.requests.append(url)
        if not self.values:
            raise AssertionError(f"unexpected offline request: {url}")
        value = self.values.pop(0)
        if isinstance(value, NetworkFailure):
            raise value
        return HTTPResponse(
            value.status_code,
            value.url or url,
            value.body,
            value.headers,
            value.attempts,
        )


class LiveTop10Transport:
    """Official-shape synthetic search pages plus opt-in synthetic SPL bodies."""

    def __init__(
        self,
        *,
        complete_selection_metadata: bool = False,
        fetch_failure_ingredient: str | None = None,
        permanent_fetch_failure_ingredient: str | None = None,
        parser_failure_ingredient: str | None = None,
        unsupported_ingredient: str | None = None,
    ) -> None:
        self.complete_selection_metadata = complete_selection_metadata
        self.fetch_failure_ingredient = fetch_failure_ingredient
        self.permanent_fetch_failure_ingredient = permanent_fetch_failure_ingredient
        self.parser_failure_ingredient = parser_failure_ingredient
        self.unsupported_ingredient = unsupported_ingredient
        self.requests: list[str] = []
        self.xml_overrides: dict[str, bytes] = {}
        utilization = load_utilization_list()
        self.by_set_id = {
            f"00000000-0000-4000-8000-{entry.rank:012d}": (
                entry.ingredient_name,
                "1",
            )
            for entry in utilization.entries
        }

    @property
    def discovery_request_count(self) -> int:
        return sum("/spls.json?" in url for url in self.requests)

    @property
    def xml_request_count(self) -> int:
        return sum(url.endswith(".xml") for url in self.requests)

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
        max_bytes: int,
    ) -> HTTPResponse:
        del headers, timeout, max_bytes
        self.requests.append(url)
        if "/spls.json?" in url:
            query = parse_qs(urlparse(url).query).get("drug_name", [""])[0]
            rank = next(
                entry.rank
                for entry in load_utilization_list().entries
                if entry.normalized_ingredient_name == query
            )
            candidate = discovery_candidate(
                query,
                rank=rank,
                complete_selection_metadata=self.complete_selection_metadata,
            )
            body = discovery_body([candidate])
            return response(
                body,
                url=url,
                headers={"etag": f'"synthetic-{rank}"'},
            )
        set_id = unquote(url.rsplit("/", 1)[-1].removesuffix(".xml"))
        ingredient, source_version = self.by_set_id[set_id]
        if ingredient == self.permanent_fetch_failure_ingredient:
            return response(
                b"not found",
                status=404,
                content_type="text/plain",
                url=url,
            )
        if ingredient == self.fetch_failure_ingredient:
            raise NetworkFailure("synthetic ODD-004 fetch failure")
        if set_id in self.xml_overrides:
            body = self.xml_overrides[set_id]
        elif ingredient == self.parser_failure_ingredient:
            body = b"<broken>"
        else:
            body = synthetic_spl(ingredient, set_id, source_version)
            if ingredient == self.unsupported_ingredient:
                body = body.replace(b"<document", b"<unsupportedDocument", 1)
                body = body.replace(b"</document>", b"</unsupportedDocument>", 1)
        return response(body, content_type="application/xml", url=url)


def live_connector(
    transport: SequenceTransport | LiveTop10Transport,
    *,
    sleeps: list[float] | None = None,
    max_retries: int = 2,
) -> DailyMedConnector:
    delays = sleeps if sleeps is not None else []
    return DailyMedConnector(
        base_url=BASE_URL,
        clock=FixedClock(),
        inter_request_delay_seconds=0,
        max_retries=max_retries,
        retry_backoff_seconds=1,
        sleep=delays.append,
        transport=transport,
    )


def live_service(
    tmp_path: Path,
    *,
    complete_selection_metadata: bool = False,
    fetch_failure_ingredient: str | None = None,
    permanent_fetch_failure_ingredient: str | None = None,
    parser_failure_ingredient: str | None = None,
    unsupported_ingredient: str | None = None,
) -> tuple[ODDService, LiveTop10Transport]:
    transport = LiveTop10Transport(
        complete_selection_metadata=complete_selection_metadata,
        fetch_failure_ingredient=fetch_failure_ingredient,
        permanent_fetch_failure_ingredient=permanent_fetch_failure_ingredient,
        parser_failure_ingredient=parser_failure_ingredient,
        unsupported_ingredient=unsupported_ingredient,
    )
    connector = live_connector(transport)
    return (
        create_service(
            data_root=tmp_path / "live-data",
            database_path=tmp_path / "live.sqlite3",
            connector=connector,
            clock=FixedClock(),
        ),
        transport,
    )
